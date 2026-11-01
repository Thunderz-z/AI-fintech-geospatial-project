"""Tests for epoch change detection (terrascope.features.change)."""

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from affine import Affine

from terrascope.features.change import (
    CHANGE_CODES,
    ChangeConfig,
    compare_epochs,
    read_epoch_layers,
)
from terrascope.ingestion.cog_reader import CompositeGrid

EPOCH_A = "winter_2019-20"
EPOCH_B = "winter"


def _grid() -> CompositeGrid:
    """Small deterministic grid (test-only; geometry values arbitrary but
    consistent across epochs)."""
    return CompositeGrid(
        crs_epsg=32644,
        transform=Affine(10.0, 0.0, 500000.0, 0.0, -10.0, 4000000.0),
        width=40,
        height=30,
        resolution_m=10.0,
    )


def _write_tif(
    path: Path, array: np.ndarray, grid: CompositeGrid, *, nodata: float | None
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=grid.height,
        width=grid.width,
        count=1,
        dtype=str(array.dtype),
        crs=f"EPSG:{grid.crs_epsg}",
        transform=grid.transform,
        nodata=nodata,
    ) as dst:
        dst.write(array, 1)


def _write_epoch(
    root: Path,
    name: str,
    grid: CompositeGrid,
    *,
    flip_20m_rows: slice = slice(0, 0),
    valid_min: int = 5,
    nan_mask: tuple[slice, slice] | None = None,
) -> Path:
    """One epoch dir: provenance + mndwi_median + B11_validcount (20 m grid).

    Base pattern: 20 m rows ``0..height2//2-1`` are water (MNDWI +0.5), the
    rest land (-0.5). ``flip_20m_rows`` inverts water/land on those rows.
    ``nan_mask`` blanks MNDWI cells and zeroes their valid counts.
    """
    grid20 = grid.at_resolution(2)
    height2, width2 = grid20.shape
    base_water = np.arange(height2)[:, None] < height2 // 2
    flip = np.zeros((height2, 1), dtype=bool)
    flip[flip_20m_rows, 0] = True
    mndwi = np.where(base_water != flip, 0.5, -0.5).astype(np.float32)
    valid = np.full((height2, width2), valid_min, dtype=np.uint16)
    if nan_mask is not None:
        mndwi[nan_mask] = np.nan
        valid[nan_mask] = 0

    epoch = root / "composites" / name
    provenance = {
        "grid": {
            "crs": f"EPSG:{grid.crs_epsg}",
            "resolution_m": grid.resolution_m,
            "width": grid.width,
            "height": grid.height,
            "transform": list(grid.transform)[:6],
        },
        "season": name,
    }
    epoch.mkdir(parents=True, exist_ok=True)
    (epoch / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    _write_tif(epoch / "mndwi_median.tif", mndwi, grid20, nodata=None)
    _write_tif(epoch / "B11_validcount.tif", valid, grid20, nodata=0)
    return epoch


@pytest.fixture()
def epochs(tmp_path: Path) -> tuple[Path, Path, CompositeGrid]:
    grid = _grid()
    # Epoch A: the first four 20 m water rows are flipped to land -> less water.
    a = _write_epoch(tmp_path, EPOCH_A, grid, flip_20m_rows=slice(0, 4), valid_min=5)
    # Epoch B: base pattern; a 2x2 coverage hole in the corner.
    b = _write_epoch(
        tmp_path, EPOCH_B, grid, valid_min=5, nan_mask=(slice(0, 2), slice(0, 2))
    )
    return a, b, grid


def test_transitions_and_gating(epochs: tuple[Path, Path, CompositeGrid]) -> None:
    a, b, _ = epochs
    report, map_path, uncertainty_path = compare_epochs(a, b, config=ChangeConfig())
    assert report.compared_pixels > 0
    # Epoch B restored the flipped rows to water => only gains, no losses.
    assert report.transition_matrix["lost_water"] == 0.0
    assert report.transition_matrix["gained_water"] > 0.0
    assert report.water_fraction_b > report.water_fraction_a
    # Transition fractions must partition the compared area exactly.
    assert sum(report.transition_matrix.values()) == pytest.approx(1.0, abs=1e-6)
    # No rasters requested.
    assert map_path is None and uncertainty_path is None


def test_coverage_hole_excluded(epochs: tuple[Path, Path, CompositeGrid]) -> None:
    a, b, grid = epochs
    report, map_path, _ = compare_epochs(
        a, b, config=ChangeConfig(min_valid_obs=2), out_dir=a.parent.parent / "cd"
    )
    grid20 = grid.at_resolution(2)
    total_cells = grid20.shape[0] * grid20.shape[1]
    # The 2x2 hole is invalid in epoch B and must be gated out of the comparison.
    assert report.compared_pixels == total_cells - 4
    assert report.valid_fraction_of_grid == pytest.approx(
        report.compared_pixels / total_cells, abs=1e-4  # report rounds to 4 decimals
    )
    with rasterio.open(map_path) as dataset:
        change_map = dataset.read(1)
    # Nodata (0) appears exactly on the hole cells.
    assert int((change_map == CHANGE_CODES["nodata"]).sum()) == 4


def test_artifacts_written(epochs: tuple[Path, Path, CompositeGrid]) -> None:
    a, b, grid = epochs
    out_dir = a.parent.parent / "change-detection"
    report, map_path, uncertainty_path = compare_epochs(
        a, b, config=ChangeConfig(min_valid_obs=2), out_dir=out_dir,
    )
    assert map_path is not None and map_path.is_file()
    assert uncertainty_path is not None and uncertainty_path.is_file()
    sidecar = json.loads(map_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert sidecar["change_map_legend"] == CHANGE_CODES
    assert sidecar["report"]["epoch_a"] == EPOCH_A
    with rasterio.open(map_path) as dataset:
        change_map = dataset.read(1)
    assert change_map.shape == grid.at_resolution(2).shape
    assert set(np.unique(change_map)) <= set(CHANGE_CODES.values())
    with rasterio.open(uncertainty_path) as dataset:
        uncertainty = dataset.read(1)
        assert dataset.nodata == 0.0
    assert float(uncertainty.max()) <= 1.0


def test_zero_overlap_abstains(epochs: tuple[Path, Path, CompositeGrid]) -> None:
    a, _, _ = epochs
    blank = _write_epoch(a.parent.parent, "winter_blank", _grid(), valid_min=0)
    with pytest.raises(RuntimeError, match="abstains"):
        compare_epochs(a, blank, config=ChangeConfig(min_valid_obs=1))


def test_read_epoch_layers_shapes(epochs: tuple[Path, Path, CompositeGrid]) -> None:
    a, _, grid = epochs
    mndwi, valid = read_epoch_layers(a, grid, grid.at_resolution(2))
    assert mndwi.shape == valid.shape == grid.at_resolution(2).shape
    assert valid.dtype == np.float32
