"""Random-forest land-cover classification with spatial block CV (M1 T3).

Setup (deliberately simple, fully documented):

* **Features**: the seasonal composite medians — B02/B03/B04/B08 (10 m),
  B11/B12 (20 m) plus the NDVI/NDWI/MNDWI/NDBI index rasters — all aligned on
  the 20 m analysis grid by the grid-aligned readers.
* **Labels**: WorldCover 2021 v200 dominant class per 20 m cell (per-class
  fraction via average resampling of a one-hot stack, then argmax). These are
  **weak labels**: single-epoch 2021 product, 10 m native resolution, applied
  to 2024 imagery, and land-cover classes — not surveyed ground truth. The
  limitation is carried into every contract and report.
* **Validation**: :class:`~terrascope.evaluation.spatial_cv.SpatialBlockSplitter`
  block folds only (ADR-0006) — spatially disjoint train/test blocks; random
  pixel splits never occur.
* **Model**: sklearn `RandomForestClassifier` (CPU), `class_weight=
  "balanced_subsample"`, fixed `random_state` for reproducibility.

The classifier is an *agreement-with-weak-labels* measurement, not a claim of
map accuracy against reality.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import rasterio
from sklearn.ensemble import RandomForestClassifier

from terrascope.evaluation.spatial_cv import (
    SpatialBlockSplitter,
    block_size_pixels,
    validate_splits,
)
from terrascope.ingestion.cog_reader import CompositeGrid, read_band_onto_grid
from terrascope.ingestion.gate import DownloadGate
from terrascope.models.classification_labels import dominant_class_raster

__all__ = ["ClassificationConfig", "ClassificationReport", "classify_composite"]

#: WorldCover v200 class codes handled here (legend in the manifest entry).
WC_CLASS_CODES: tuple[int, ...] = (10, 20, 30, 40, 50, 60, 80, 90)

#: Human-readable names for the handled codes (report tables).
WC_CLASS_NAMES: dict[int, str] = {
    10: "tree_cover",
    20: "shrubland",
    30: "grassland",
    40: "cropland",
    50: "built_up",
    60: "bare_sparse",
    80: "permanent_water",
    90: "herbaceous_wetland",
}


@dataclass(frozen=True)
class ClassificationConfig:
    """Reproducible classification hyper-parameters (recorded in artefacts)."""

    block_size_m: float = 2000.0
    n_folds: int = 5
    n_estimators: int = 200
    min_samples_leaf: int = 2
    max_samples_per_class: int = 20000
    random_state: int = 42

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ClassificationReport:
    """Aggregated block-CV outcome (no per-pixel map is claimed here)."""

    n_training_pixels: int = 0
    n_labelled_pixels: int = 0
    n_folds: int = 0
    fold_accuracy: list[float] = field(default_factory=list)
    mean_accuracy: float | None = None
    sd_accuracy: float | None = None
    class_support: dict[str, int] = field(default_factory=dict)
    confusion_matrix: list[list[int]] = field(default_factory=list)
    class_order: list[str] = field(default_factory=list)

    def finalize(self) -> None:
        if self.fold_accuracy:
            self.mean_accuracy = round(float(np.mean(self.fold_accuracy)), 4)
            self.sd_accuracy = round(float(np.std(self.fold_accuracy)), 4)

    def to_dict(self) -> dict:
        return asdict(self)


def _read_grid20(path: Path, grid10: CompositeGrid, grid20: CompositeGrid) -> np.ndarray:
    """Read an index/median raster onto the 20 m grid without the 0->NaN nodata
    rewrite (0.0 is a legitimate index value; NaN stays the nodata marker)."""
    with rasterio.open(path) as dataset:
        array = dataset.read(1).astype(np.float32)
    if array.shape == grid20.shape:
        return array
    if array.shape == grid10.shape:  # 10 m product -> 2x2 block mean (shared origin)
        height2, width2 = grid20.shape
        with np.errstate(invalid="ignore"):
            return np.nanmean(
                array[: height2 * 2, : width2 * 2].reshape(height2, 2, width2, 2), axis=(1, 3)
            )
    msg = f"Raster shape {array.shape} matches neither grid: {path.name}"
    raise ValueError(msg)


def _composite_features(
    season_dir: Path, grid10: CompositeGrid, grid20: CompositeGrid, gate: DownloadGate
) -> tuple[np.ndarray, list[str]]:
    """Feature stack ``(n_features, height, width)`` on the 20 m grid."""
    bands = ("B02", "B03", "B04", "B08", "B11", "B12")
    planes: list[np.ndarray] = []
    names: list[str] = []
    for band in bands:
        plane = read_band_onto_grid(str(season_dir / f"{band}_median.tif"), band, grid20, gate)
        planes.append(plane)
        names.append(band)

    # Index rasters carry NaN nodata natively; 0.0 is a valid value, so they
    # are read directly (never through the reflectance reader).
    for name in ("ndvi", "ndwi", "mndwi", "ndbi"):
        path = season_dir / f"{name}_median.tif"
        if path.is_file():  # built by features.indices.build_season_indices
            planes.append(_read_grid20(path, grid10, grid20))
            names.append(name.upper())
        else:
            msg = f"Missing index raster {path.name}; run build_season_indices first"
            raise FileNotFoundError(msg)
    return np.stack(planes, axis=0), names


def classify_composite(
    season_dir: Path,
    wc_class_raster: Path,
    config: ClassificationConfig | None = None,
    *,
    gate: DownloadGate | None = None,
) -> tuple[ClassificationReport, RandomForestClassifier, list[str]]:
    """Block-CV classification of a seasonal composite against WC labels.

    Returns:
        ``(report, fitted_model_on_all_labelled_data, feature_names)`` — the
        returned model is refit on all labelled pixels for reuse; the reported
        accuracy comes strictly from the held-out block folds.
    """
    config = config or ClassificationConfig()
    gate = gate or DownloadGate()
    provenance = json.loads((season_dir / "provenance.json").read_text(encoding="utf-8"))
    from affine import Affine

    grid10 = CompositeGrid(
        crs_epsg=int(provenance["grid"]["crs"].split(":")[1]),
        transform=Affine(*provenance["grid"]["transform"][:6]),
        width=provenance["grid"]["width"],
        height=provenance["grid"]["height"],
        resolution_m=provenance["grid"]["resolution_m"],
    )
    grid20 = grid10.at_resolution(2)

    features, feature_names = _composite_features(season_dir, grid10, grid20, gate)
    labels, labelled = dominant_class_raster(wc_class_raster, grid20, WC_CLASS_CODES)

    feature_stack = features.reshape(features.shape[0], -1).T  # (n_cells, n_features)
    finite = np.isfinite(features).all(axis=0)  # per-cell (2D)
    usable = finite & labelled
    usable_flat = usable.reshape(-1)
    labels_flat = labels.reshape(-1)
    report = ClassificationReport(n_labelled_pixels=int(np.count_nonzero(usable_flat)))

    counts: dict[int, int] = {}
    rng = np.random.default_rng(config.random_state)
    selected_indices: list[int] = []
    for code in np.unique(labels_flat[usable_flat]):
        candidates = np.flatnonzero(usable_flat & (labels_flat == code))
        if candidates.size > config.max_samples_per_class:
            candidates = rng.choice(candidates, size=config.max_samples_per_class, replace=False)
        counts[int(code)] = int(candidates.size)
        selected_indices.append(candidates)
    sample_idx = np.concatenate(selected_indices)
    report.n_training_pixels = int(sample_idx.size)

    x_all = feature_stack[sample_idx]
    y_all = labels_flat[sample_idx]

    splitter = SpatialBlockSplitter(
        height=grid20.height,
        width=grid20.width,
        block_size_px=block_size_pixels(config.block_size_m, grid20.resolution_m),
        n_folds=config.n_folds,
    )
    splits = splitter.splits()
    validate_splits(splits, splitter.block_raster)

    sample_block_ids = splitter.block_raster.flat[sample_idx]
    class_order = sorted(counts)
    confusion = np.zeros((len(class_order), len(class_order)), dtype=np.int64)
    for split in splits:
        train_mask = ~np.isin(sample_block_ids, split.test_block_ids)
        test_mask = np.isin(sample_block_ids, split.test_block_ids)
        if not train_mask.any() or not test_mask.any():
            msg = f"Fold {split.fold} has an empty train or test side"
            raise RuntimeError(msg)
        clf = RandomForestClassifier(
            n_estimators=config.n_estimators,
            min_samples_leaf=config.min_samples_leaf,
            class_weight="balanced_subsample",
            n_jobs=-1,
            random_state=config.random_state,
        )
        clf.fit(x_all[train_mask], y_all[train_mask])
        predictions = clf.predict(x_all[test_mask])
        truth = y_all[test_mask]
        report.fold_accuracy.append(round(float(np.mean(predictions == truth)), 4))
        for true_code, pred_code in zip(truth, predictions, strict=True):
            confusion[class_order.index(int(true_code)), class_order.index(int(pred_code))] += 1

    report.class_support = {WC_CLASS_NAMES.get(code, str(code)): counts[code] for code in counts}
    report.class_order = [WC_CLASS_NAMES.get(code, str(code)) for code in class_order]
    report.confusion_matrix = confusion.tolist()
    report.n_folds = len(splits)
    report.finalize()

    final_model = RandomForestClassifier(
        n_estimators=config.n_estimators,
        min_samples_leaf=config.min_samples_leaf,
        class_weight="balanced_subsample",
        n_jobs=-1,
        random_state=config.random_state,
    )
    final_model.fit(x_all, y_all)
    return report, final_model, feature_names
