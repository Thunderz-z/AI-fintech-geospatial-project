"""Change detection between two composite epochs (post-classification, M3).

Method (deliberately simple and fully documented):

* **Input**: two index composite directories (different epochs, same AOI and
  grid) each with an ``mndwi_median.tif`` and a ``B11_validcount.tif``.
* **Water decision**: calibrated MNDWI threshold (default 0.0) per epoch.
* **Validity**: a pixel is compared only where *both* epochs have at least
  ``min_valid_obs`` valid (SCL-passing) observations.
* **Transitions**: gained (land -> water), lost (water -> land), stable
  water / stable land — a 2x2 transition matrix per epoch pair. This is an
  *observation*, never a causal statement (ADR-0006).
* **Uncertainty map**: per-pixel *classifier-agreement proxy* — the block-mean
  of ``min(valid_a, valid_b) / max_valid`` and the |MNDWI_B - MNDWI_A|
  margin. Pixels whose MNDWI margin is near the threshold are genuinely
  ambiguous; the map records that instead of hiding it. Block means are
  quantile-free deterministic statistics.

The claim phrasing is "observed change" — the evidence contract states the
threshold, validity gate, margins and explicitly disclaims causation and
single-epoch-reference limitations.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import rasterio

from terrascope.features.water_extent import DEFAULT_MNDWI_WATER_THRESHOLD
from terrascope.ingestion.cog_reader import CompositeGrid
from terrascope.ingestion.gate import DownloadGate


def _grid_from_provenance(provenance: dict) -> CompositeGrid:
    """Rebuild the composite grid from a provenance sidecar (shared convention
    with ``models.classification`` and ``features.indices``)."""
    from affine import Affine

    return CompositeGrid(
        crs_epsg=int(provenance["grid"]["crs"].split(":")[1]),
        transform=Affine(*provenance["grid"]["transform"][:6]),
        width=provenance["grid"]["width"],
        height=provenance["grid"]["height"],
        resolution_m=provenance["grid"]["resolution_m"],
    )

__all__ = [
    "ChangeConfig",
    "ChangeReport",
    "compare_epochs",
    "read_epoch_layers",
]

#: Water-transition codes written to the change map (GeoTIFF uint8).
CHANGE_CODES: dict[str, int] = {
    "nodata": 0,
    "stable_land": 1,
    "stable_water": 2,
    "gained_water": 3,
    "lost_water": 4,
}


@dataclass(frozen=True)
class ChangeConfig:
    """Reproducible change-detection parameters (recorded in artefacts)."""

    mndwi_threshold: float = DEFAULT_MNDWI_WATER_THRESHOLD
    min_valid_obs: int = 2
    uncertainty_block_px: int = 25  # 500 m at 20 m
    margin_band: float = 0.05  # |MNDWI diff| below this = "ambiguous margin"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ChangeReport:
    """Observed water transition fractions between two epochs."""

    epoch_a: str = ""
    epoch_b: str = ""
    season: str = ""
    compared_pixels: int = 0
    valid_fraction_of_grid: float | None = None
    water_fraction_a: float | None = None
    water_fraction_b: float | None = None
    gained_fraction: float | None = None
    lost_fraction: float | None = None
    transition_matrix: dict[str, float] = field(default_factory=dict)
    areas_ha: dict[str, float] = field(default_factory=dict)
    ambiguous_margin_fraction: float | None = None
    median_abs_margin: float | None = None
    agreement_uncertainty: dict[str, float] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _read_index(path: Path, grid10: CompositeGrid, grid20: CompositeGrid) -> np.ndarray:
    """Read an index raster onto the 20 m grid (NaN-native; 0.0 is a value)."""
    with rasterio.open(path) as dataset:
        array = dataset.read(1).astype(np.float32)
    if array.shape == grid20.shape:
        return array
    if array.shape == grid10.shape:
        height2, width2 = grid20.shape
        with np.errstate(invalid="ignore"):
            return np.nanmean(
                array[: height2 * 2, : width2 * 2].reshape(height2, 2, width2, 2), axis=(1, 3)
            )
    msg = f"Raster shape {array.shape} matches neither grid: {path.name}"
    raise ValueError(msg)


def _read_validcount(path: Path, grid10: CompositeGrid, grid20: CompositeGrid) -> np.ndarray:
    """Read a valid-count raster onto the 20 m grid (0 = nodata)."""
    with rasterio.open(path) as dataset:
        array = dataset.read(1).astype(np.float32)
        nodata = dataset.nodata
    if nodata is not None:
        array = np.where(array == nodata, np.nan, array)
    if array.shape == grid20.shape:
        return array
    if array.shape == grid10.shape:
        height2, width2 = grid20.shape
        padded = np.full((height2 * 2, width2 * 2), np.nan, dtype=np.float32)
        padded[: grid10.height, : grid10.width] = array[: grid10.height, : grid10.width]
        return padded.reshape(height2, 2, width2, 2).sum(axis=(1, 3))
    msg = f"Raster shape {array.shape} matches neither grid: {path.name}"
    raise ValueError(msg)


def _block_mean(array: np.ndarray, block_px: int) -> np.ndarray:
    """Deterministic non-overlapping block mean, NaN-aware, edge-padded."""
    height, width = array.shape
    padded = np.full(
        ((height + block_px - 1) // block_px * block_px,
         (width + block_px - 1) // block_px * block_px),
        np.nan,
        dtype=np.float64,
    )
    padded[:height, :width] = array
    blocks = padded.reshape(
        padded.shape[0] // block_px, block_px, padded.shape[1] // block_px, block_px
    )
    with np.errstate(invalid="ignore"):
        means = np.nanmean(blocks, axis=(1, 3))
    expanded = np.repeat(np.repeat(means, block_px, axis=0), block_px, axis=1)
    return expanded[:height, :width].astype(np.float32)


def read_epoch_layers(
    epoch_dir: Path,
    grid10: CompositeGrid,
    grid20: CompositeGrid,
    *,
    gate: DownloadGate | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(mndwi, validcount)`` composites for one epoch directory."""
    gate = gate or DownloadGate()  # local reads never trip it; uniform signature
    mndwi = _read_index(epoch_dir / "mndwi_median.tif", grid10, grid20)
    valid = _read_validcount(epoch_dir / "B11_validcount.tif", grid10, grid20)
    return mndwi, valid


def compare_epochs(
    epoch_a_dir: Path,
    epoch_b_dir: Path,
    *,
    config: ChangeConfig | None = None,
    out_dir: Path | None = None,
    season: str = "winter",
) -> tuple[ChangeReport, Path, Path | None]:
    """Compare two composite epochs; optionally write map + uncertainty rasters.

    Returns:
        ``(report, change_map_path_or_None, uncertainty_path_or_None)`` —
        rasters are written only when *out_dir* is given.
    """
    config = config or ChangeConfig()
    provenance = json.loads((epoch_a_dir / "provenance.json").read_text(encoding="utf-8"))
    grid10 = _grid_from_provenance(provenance)
    grid20 = grid10.at_resolution(2)

    mndwi_a, valid_a = read_epoch_layers(epoch_a_dir, grid10, grid20)
    mndwi_b, valid_b = read_epoch_layers(epoch_b_dir, grid10, grid20)

    with np.errstate(invalid="ignore"):
        water_a = mndwi_a > config.mndwi_threshold
        water_b = mndwi_b > config.mndwi_threshold
    valid = (valid_a >= config.min_valid_obs) & (valid_b >= config.min_valid_obs)

    stable_water = valid & water_a & water_b
    stable_land = valid & ~water_a & ~water_b
    gained = valid & ~water_a & water_b
    lost = valid & water_a & ~water_b
    compared = int(np.count_nonzero(valid))

    pixel_area_m2 = float(grid20.resolution_m) ** 2
    to_ha = pixel_area_m2 / 10_000.0
    if compared == 0:
        msg = (
            "No pixels pass the validity gate — the epochs do not overlap in "
            "usable observations; change detection abstains."
        )
        raise RuntimeError(msg)

    with np.errstate(invalid="ignore"):
        abs_margin = np.abs(mndwi_b - mndwi_a)
    ambiguous = valid & (abs_margin < config.margin_band)
    uncertainty = _block_mean(
        np.where(valid, np.minimum(valid_a, valid_b) / float(np.nanmax(valid_a)), np.nan),
        config.uncertainty_block_px,
    )

    report = ChangeReport(
        epoch_a=epoch_a_dir.name,
        epoch_b=epoch_b_dir.name,
        season=season,
        compared_pixels=compared,
        valid_fraction_of_grid=round(compared / valid.size, 4),
        limitations=[
            "post-classification comparison; observed change, no causal attribution",
            "MNDWI threshold stated; seasonal marsh water is not permanent water",
            "no tidal correction; single-scene epochs from median composites",
            "uncertainty map is an observation-count/agreement proxy, not a probability",
        ],
    )
    transitions = {
        "stable_water": int(np.count_nonzero(stable_water)),
        "gained_water": int(np.count_nonzero(gained)),
        "lost_water": int(np.count_nonzero(lost)),
        "stable_land": int(np.count_nonzero(stable_land)),
    }
    report.transition_matrix = {
        name: round(count / compared, 6) for name, count in transitions.items()
    }
    report.areas_ha = {
        f"{name}_ha": round(count * to_ha, 2) for name, count in transitions.items()
    }
    report.water_fraction_a = round(
        float(np.count_nonzero(valid & water_a)) / compared, 6
    )
    report.water_fraction_b = round(
        float(np.count_nonzero(valid & water_b)) / compared, 6
    )
    report.gained_fraction = report.transition_matrix["gained_water"]
    report.lost_fraction = report.transition_matrix["lost_water"]
    report.ambiguous_margin_fraction = round(
        float(np.count_nonzero(ambiguous)) / compared, 6
    )
    report.median_abs_margin = (
        round(float(np.nanmedian(abs_margin[valid])), 4) if compared else None
    )
    report.agreement_uncertainty = {
        "block_px": config.uncertainty_block_px,
        "statistic": "block mean of min(valid_a, valid_b) / max valid observations",
        "mean": round(float(np.nanmean(uncertainty)), 4),
        "min": round(float(np.nanmin(uncertainty)), 4),
    }

    map_path: Path | None = None
    uncertainty_path: Path | None = None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        change_map = np.full(valid.shape, CHANGE_CODES["nodata"], dtype=np.uint8)
        change_map[stable_land] = CHANGE_CODES["stable_land"]
        change_map[stable_water] = CHANGE_CODES["stable_water"]
        change_map[gained] = CHANGE_CODES["gained_water"]
        change_map[lost] = CHANGE_CODES["lost_water"]
        map_path = out_dir / f"change_map_{season}_{epoch_a_dir.name}_vs_{epoch_b_dir.name}.tif"
        _write_raster(map_path, change_map, grid20, nodata_value=0)
        uncertainty_path = (
            out_dir / f"uncertainty_{season}_{epoch_a_dir.name}_vs_{epoch_b_dir.name}.tif"
        )
        unc_out = np.where(np.isnan(uncertainty), np.float32(0.0), uncertainty)
        _write_raster(uncertainty_path, unc_out, grid20, nodata_value=0.0)

        sidecar = {
            "change_map_legend": CHANGE_CODES,
            "config": config.to_dict(),
            "epoch_a": {
                "dir": epoch_a_dir.name,
                "provenance": str(epoch_a_dir / "provenance.json"),
            },
            "epoch_b": {
                "dir": epoch_b_dir.name,
                "provenance": str(epoch_b_dir / "provenance.json"),
            },
            "report": report.to_dict(),
        }
        map_path.with_suffix(".json").write_text(
            json.dumps(sidecar, indent=2, sort_keys=True), encoding="utf-8"
        )
    return report, map_path, uncertainty_path


def _write_raster(path: Path, array: np.ndarray, grid: CompositeGrid, *, nodata_value: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="COG",
        height=grid.height,
        width=grid.width,
        count=1,
        dtype=str(array.dtype),
        crs=f"EPSG:{grid.crs_epsg}",
        transform=grid.transform,
        nodata=nodata_value,
        compress="deflate",
        blocksize=512,
    ) as dst:
        dst.write(array, 1)


def change_report_payload(report: ChangeReport, config: ChangeConfig) -> dict:
    """Full artefact payload with run metadata and reproducibility fields."""
    return {
        "run_at": dt.datetime.now(tz=dt.UTC).isoformat(),
        "method": "post-classification MNDWI water transition between composite epochs",
        "note": "observed change only — NOT a causal or land-cover-class change statement",
        "config": config.to_dict(),
        **report.to_dict(),
    }
