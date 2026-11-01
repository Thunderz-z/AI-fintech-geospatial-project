"""MNDWI threshold calibration against a reference water mask (M1 task T2).

The v0 water threshold (MNDWI > 0) was an uncalibrated default; M0's
threshold-sensitivity QA showed absolute water fractions depend strongly on it
while the seasonal ordering is stable. This module fits the threshold
against a reference mask and scores every candidate:

* **Reference**: a class raster on the data root (ESA WorldCover 2021 v200
  ``map`` asset, class 80 = permanent water). The class raster is binarised at
  native resolution and reduced to per-cell fractions on the 20 m analysis
  grid (average resampling); a cell is reference-water when its fraction is
  >= ``min_fraction``. Cells the reference raster does not cover are marked
  *undefined* and excluded from scoring. Reference agreement is evaluated on
  the Ramsar polygon only — the authoritative boundary, and it avoids the
  bbox ocean sliver.
* **Sweep**: per usable scene date, the confusion matrix of ``MNDWI > t``
  vs the reference over valid, defined pixels; Cohen's kappa per threshold;
  the chosen threshold maximises the **mean kappa across dates**.
* **Manual QA points**: an optional GeoJSON of hand-interpreted points
  (property ``class``: ``water`` / ``not_water``) scored against the chosen
  threshold as an independent check — never a fitting target.

Honesty: WorldCover is a 2021 single-epoch product compared against scenes
from other years, and "permanent water" is not "MNDWI-positive at acquisition
time" (seasonal marsh water varies). The calibration therefore reports
agreement statistics, not ground truth; the evidence contracts state the
reference product and these limitations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject as rasterio_reproject
from rasterio.windows import transform as window_transform

from terrascope.features.water_extent import read_scene_mndwi, scene_date
from terrascope.ingestion.cog_reader import CompositeGrid, window_covering_bounds
from terrascope.ingestion.gate import DownloadGate
from terrascope.ingestion.masking import SCL_EXCLUDE_DEFAULT, scl_valid_mask

__all__ = [
    "CalibrationResult",
    "CalibrationScore",
    "QAPointScore",
    "calibrate_threshold",
    "read_reference_water_mask",
    "result_to_dict",
    "score_qa_points",
    "score_threshold",
]

#: Reference cell counts as water when at least this fraction of its native
#: pixels carry a reference water class (majority-ish at the 20 m grid).
DEFAULT_MIN_REFERENCE_FRACTION = 0.5

#: Threshold sweep: MNDWI water/non-water separations in the marsh QA data
#: span roughly -0.3..+0.3 (M0 sensitivity artefact).
DEFAULT_SWEEP = tuple(np.arange(-0.30, 0.31, 0.05).round(2))

#: Fill for grid cells the reference raster does not cover.
_UNDEFINED = -1.0


@dataclass(frozen=True)
class CalibrationScore:
    """Confusion-matrix scores of one threshold against the reference mask."""

    threshold: float
    accuracy: float
    precision_water: float | None
    recall_water: float | None
    f1_water: float | None
    kappa: float
    n_pixels: int


@dataclass(frozen=True)
class CalibrationResult:
    """Outcome of the sweep: chosen threshold plus the full score table."""

    threshold: float
    method: str
    reference: str
    n_dates: int
    per_date_optimal: dict[str, float]
    mean_kappa_by_threshold: dict[str, float]
    scores_at_chosen: list[CalibrationScore]


@dataclass(frozen=True)
class QAPointScore:
    """One manual QA point evaluated against the calibrated threshold."""

    name: str
    expected_water: bool
    mndwi: float
    predicted_water: bool
    agrees: bool


def read_reference_water_mask(
    class_raster_path: Path,
    grid: CompositeGrid,
    *,
    water_class_codes: tuple[int, ...] = (80,),
    min_fraction: float = DEFAULT_MIN_REFERENCE_FRACTION,
    gate: DownloadGate | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Reference water + defined masks on *grid*.

    The stored class raster (any source CRS) is binarised at native resolution
    and reduced to per-cell fractions via average resampling; cells with
    fraction >= *min_fraction* are reference water. Cells the raster does not
    cover are ``defined == False`` and excluded from scoring.
    """
    gate = gate or DownloadGate()
    gate.require(str(class_raster_path), "reference class raster read")
    fraction = np.full(grid.shape, _UNDEFINED, dtype=np.float32)
    with rasterio.open(class_raster_path) as dataset:
        window = window_covering_bounds(dataset, grid.bounds, grid.crs_epsg)
        source = dataset.read(1, window=window)
        source_binary = np.isin(source, water_class_codes).astype(np.float32)
        rasterio_reproject(
            source=source_binary,
            destination=fraction,
            src_transform=window_transform(window, dataset.transform),
            src_crs=dataset.crs,
            src_nodata=None,
            dst_transform=grid.transform,
            dst_crs=f"EPSG:{grid.crs_epsg}",
            dst_nodata=_UNDEFINED,
            resampling=Resampling.average,
        )
    defined = fraction >= 0.0
    water = defined & (fraction >= min_fraction)
    return water, defined


def _kappa(tp: int, tn: int, fp: int, fn: int) -> float:
    total = tp + tn + fp + fn
    if total == 0:
        return float("nan")
    po = (tp + tn) / total
    pe = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / (total * total)
    if pe >= 1.0:
        return 0.0
    return (po - pe) / (1.0 - pe)


def score_threshold(
    water_index: np.ndarray,
    valid: np.ndarray,
    reference: np.ndarray,
    reference_defined: np.ndarray,
    threshold: float,
) -> CalibrationScore:
    """Confusion matrix of ``water_index > threshold`` vs the reference.

    Scored only where the scene is valid AND the reference is defined; NaN
    index cells cannot pass the comparison and drop out automatically.
    """
    comparable = valid & reference_defined
    predicted = (water_index > threshold) & comparable
    actual = reference & comparable
    tp = int(np.count_nonzero(predicted & actual))
    tn = int(np.count_nonzero(~predicted & ~actual & comparable))
    fp = int(np.count_nonzero(predicted & ~actual & comparable))
    fn = int(np.count_nonzero(~predicted & actual & comparable))
    total = tp + tn + fp + fn
    accuracy = (tp + tn) / total if total else float("nan")
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and (precision + recall)
        else None
    )
    return CalibrationScore(
        threshold=float(threshold),
        accuracy=round(float(accuracy), 4),
        precision_water=round(precision, 4) if precision is not None else None,
        recall_water=round(recall, 4) if recall is not None else None,
        f1_water=round(f1, 4) if f1 is not None else None,
        kappa=round(float(_kappa(tp, tn, fp, fn)), 4),
        n_pixels=total,
    )


def _scene_valid_and_mndwi(
    scene_dir: Path,
    grid20: CompositeGrid,
    scl_exclude: frozenset[int] | set[int],
    gate: DownloadGate,
) -> tuple[np.ndarray, np.ndarray]:
    from terrascope.ingestion.cog_reader import read_scl_onto_grid

    scl = read_scl_onto_grid(str(scene_dir / "SCL.tif"), grid20, gate)
    valid = scl_valid_mask(scl, scl_exclude)
    return valid, read_scene_mndwi(scene_dir, grid20, gate)


def calibrate_threshold(
    scene_dirs: list[Path],
    grid20: CompositeGrid,
    reference: np.ndarray,
    reference_defined: np.ndarray,
    *,
    thresholds: tuple[float, ...] = DEFAULT_SWEEP,
    scl_exclude: frozenset[int] | set[int] = SCL_EXCLUDE_DEFAULT,
    gate: DownloadGate | None = None,
) -> CalibrationResult:
    """Sweep thresholds across scene dates; pick the max mean kappa.

    Args:
        scene_dirs: Cached scene directories (local reads only).
        grid20: The 20 m analysis grid the scenes and reference share.
        reference / reference_defined: Masks from
            :func:`read_reference_water_mask`.
        thresholds: Candidate MNDWI thresholds.
        scl_exclude: SCL classes excluded from validity.

    Returns:
        :class:`CalibrationResult` — the chosen threshold maximises mean kappa
        across dates; per-date optima and the score table at the chosen
        threshold are included.
    """
    gate = gate or DownloadGate()
    if not scene_dirs:
        msg = "No scenes supplied for calibration"
        raise ValueError(msg)
    if reference.dtype != bool or reference_defined.dtype != bool:
        msg = "reference and reference_defined must be boolean masks"
        raise ValueError(msg)

    per_date: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for scene_dir in sorted(scene_dirs, key=lambda path: scene_date(path.name)):
        date_key = scene_date(scene_dir.name).isoformat()
        per_date[date_key] = _scene_valid_and_mndwi(scene_dir, grid20, scl_exclude, gate)

    per_date_optimal: dict[str, float] = {}
    for date_key, (valid, water_index) in per_date.items():
        scores = [
            score_threshold(water_index, valid, reference, reference_defined, threshold)
            for threshold in thresholds
        ]
        per_date_optimal[date_key] = max(scores, key=lambda score: score.kappa).threshold

    def _kappa_at(threshold: float) -> float:
        return float(
            np.mean(
                [
                    score_threshold(
                        water_index, valid, reference, reference_defined, threshold
                    ).kappa
                    for valid, water_index in per_date.values()
                ]
            )
        )

    mean_kappa = {threshold: _kappa_at(threshold) for threshold in thresholds}
    chosen = max(mean_kappa, key=lambda t: (mean_kappa[t], -abs(t)))

    scores_at_chosen = [
        score_threshold(water_index, valid, reference, reference_defined, chosen)
        for valid, water_index in per_date.values()
    ]
    return CalibrationResult(
        threshold=chosen,
        method="max mean Cohen's kappa across usable dates (MNDWI sweep)",
        reference="reference water mask (source product stated in the evidence contract)",
        n_dates=len(per_date),
        per_date_optimal=per_date_optimal,
        mean_kappa_by_threshold={f"{t:+.2f}": round(v, 4) for t, v in mean_kappa.items()},
        scores_at_chosen=scores_at_chosen,
    )


def score_qa_points(
    qa_points_path: Path,
    water_index: np.ndarray,
    grid: CompositeGrid,
    threshold: float,
) -> list[QAPointScore]:
    """Score manual QA points against ``water_index > threshold``.

    The QA file is a GeoJSON with a ``class`` property (``water`` or
    ``not_water``) — hand-interpreted check points, never a fitting target.
    Points outside the grid are skipped (recorded in the caller's artefact).
    """
    frame = gpd.read_file(qa_points_path)
    if frame.crs is not None and frame.crs.to_epsg() != grid.crs_epsg:
        frame = frame.to_crs(grid.crs_epsg)
    scores: list[QAPointScore] = []
    for _, row in frame.iterrows():
        x, y = float(row.geometry.x), float(row.geometry.y)
        col = int((x - grid.transform.c) / grid.resolution_m)
        row_i = int((grid.transform.f - y) / grid.resolution_m)
        if not (0 <= row_i < grid.height and 0 <= col < grid.width):
            continue
        value = float(water_index[row_i, col])
        expected = str(row.get("class", "not_water")).lower() == "water"
        scores.append(
            QAPointScore(
                name=str(row.get("name", f"point_{len(scores)}")),
                expected_water=expected,
                mndwi=round(value, 4) if np.isfinite(value) else float("nan"),
                predicted_water=bool(value > threshold),
                agrees=bool((value > threshold) == expected),
            )
        )
    return scores


def result_to_dict(result: CalibrationResult) -> dict:
    """JSON-safe serialisation for artefacts."""
    return {
        "threshold": result.threshold,
        "method": result.method,
        "reference": result.reference,
        "n_dates": result.n_dates,
        "per_date_optimal": result.per_date_optimal,
        "mean_kappa_by_threshold": result.mean_kappa_by_threshold,
        "scores_at_chosen": [asdict(score) for score in result.scores_at_chosen],
    }
