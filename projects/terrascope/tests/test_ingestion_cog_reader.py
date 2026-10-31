"""Tests for windowed COG reads and composite-grid alignment (local fixtures)."""

from __future__ import annotations

import numpy as np
import pytest
from _terrascope_fixtures import (
    DIMS_10M,
    RES_10M,
    SCENE_LEFT,
    SCENE_TOP,
    TRANSFORM_10M,
    TRANSFORM_20M,
    make_scl,
    write_band,
)
from affine import Affine

from terrascope.ingestion.aoi import aoi_from_bbox
from terrascope.ingestion.cog_reader import (
    CompositeGrid,
    read_asset_window,
    read_band_onto_grid,
    read_scl_onto_grid,
)
from terrascope.ingestion.gate import DownloadGate, DownloadNotApprovedError


class TestReadAssetWindow:
    def test_window_shape_and_values(self, small_aoi, tmp_path) -> None:  # noqa: ANN001
        band_path = tmp_path / "B04.tif"
        write_band(band_path, np.full((DIMS_10M, DIMS_10M), 1234, dtype=np.uint16), TRANSFORM_10M)
        window_read = read_asset_window(band_path.as_uri(), "B04", small_aoi, DownloadGate())
        # 400 m AOI at 10 m -> ~40x40 px (window rounding may add a pixel).
        assert 38 <= window_read.array.shape[0] <= 42
        assert 38 <= window_read.array.shape[1] <= 42
        assert (window_read.array == 1234).all()
        assert window_read.resolution_m == RES_10M

    def test_window_is_smaller_than_full_scene(self, small_aoi, tmp_path) -> None:  # noqa: ANN001
        band_path = tmp_path / "B04.tif"
        write_band(band_path, np.full((DIMS_10M, DIMS_10M), 7, dtype=np.uint16), TRANSFORM_10M)
        window_read = read_asset_window(band_path.as_uri(), "B04", small_aoi, DownloadGate())
        assert window_read.array.shape[0] < DIMS_10M  # clipped, not a full-scene read

    def test_remote_href_blocked_by_gate(self, small_aoi) -> None:  # noqa: ANN001
        with pytest.raises(DownloadNotApprovedError):
            read_asset_window(
                "https://planetarycomputer.example/B04.tif", "B04", small_aoi, DownloadGate()
            )

    def test_nonoverlapping_extent_raises(self, tmp_path) -> None:  # noqa: ANN001
        """A scene far away must not be silently read as garbage."""
        band_path = tmp_path / "B04.tif"
        write_band(band_path, np.full((DIMS_10M, DIMS_10M), 7, dtype=np.uint16), TRANSFORM_10M)
        paris_aoi = aoi_from_bbox((2.25, 48.80, 2.45, 48.90), name="Paris (non-overlapping)")
        with pytest.raises(ValueError, match="does not overlap"):
            read_asset_window(band_path.as_uri(), "B04", paris_aoi, DownloadGate())


class TestCompositeGrid:
    def test_from_aoi_snaps_origin(self, small_aoi) -> None:  # noqa: ANN001
        grid = CompositeGrid.from_aoi(small_aoi, resolution_m=10.0)
        assert grid.transform.c % 10 == 0
        assert grid.transform.f % 10 == 0
        assert 38 <= grid.width <= 44  # ~400 m AOI at 10 m
        assert 38 <= grid.height <= 44

    def test_at_resolution_coarsens(self, small_aoi) -> None:  # noqa: ANN001
        grid10 = CompositeGrid.from_aoi(small_aoi, resolution_m=10.0)
        grid20 = grid10.at_resolution(2)
        assert grid20.resolution_m == 20.0
        assert grid20.height == int(np.ceil(grid10.height / 2))
        assert grid20.width == int(np.ceil(grid10.width / 2))
        assert grid20.transform.c == grid10.transform.c  # shared origin


class TestGridAlignedReads:
    def test_offset_scene_lands_on_grid(self, small_aoi, tmp_path) -> None:  # noqa: ANN001
        """A scene offset by half a pixel still lands exactly on the composite grid."""
        grid = CompositeGrid.from_aoi(small_aoi, resolution_m=RES_10M)
        transform = TRANSFORM_10M @ Affine(1, 0, 5.0, 0, 1, -5.0)  # half-pixel shift
        band_path = tmp_path / "B04_offset.tif"
        write_band(band_path, np.full((DIMS_10M, DIMS_10M), 999, dtype=np.uint16), transform)
        plane = read_band_onto_grid(band_path.as_uri(), "B04", grid, DownloadGate())
        assert plane.shape == grid.shape
        interior = plane[4:-4, 4:-4]
        assert np.isfinite(interior).all()
        # Bilinear resampling of a constant field returns the constant.
        assert np.allclose(interior, 999.0, atol=2.0)

    def test_beyond_scene_filled_with_nan(self, small_aoi, tmp_path) -> None:  # noqa: ANN001
        """AOI wider than the scene: in-scene data kept, out-of-scene is NaN."""
        grid = CompositeGrid.from_aoi(small_aoi, resolution_m=RES_10M)
        # Raster shifted 500 m right: it only covers the right part of the grid.
        transform = Affine(RES_10M, 0, SCENE_LEFT + 500.0, 0, -RES_10M, SCENE_TOP)
        band_path = tmp_path / "B04_shifted.tif"
        write_band(band_path, np.full((DIMS_10M, DIMS_10M), 555, dtype=np.uint16), transform)
        plane = read_band_onto_grid(band_path.as_uri(), "B04", grid, DownloadGate())
        assert plane.shape == grid.shape
        assert np.isnan(plane[:, :5]).all()  # columns left of the scene edge
        interior = plane[np.isfinite(plane)]
        assert interior.size > 0
        assert np.allclose(interior, 555.0, atol=2.0)

    def test_scl_read_stays_categorical(self, small_aoi, tmp_path) -> None:  # noqa: ANN001
        grid20 = CompositeGrid.from_aoi(small_aoi, resolution_m=RES_10M).at_resolution(2)
        scl_path = tmp_path / "SCL.tif"
        # Patch at 20 m (24, 24) lies inside the AOI extent (the AOI covers the
        # scene's central 400 m: UTM x 500300..500700, y 1429300..1429700).
        write_band(scl_path, make_scl([(8, 24, 24)]), TRANSFORM_20M)
        result = read_scl_onto_grid(scl_path.as_uri(), grid20, DownloadGate())
        assert result.dtype == np.uint8
        assert set(np.unique(result)) <= set(range(12))
        assert (result == 8).sum() > 0  # the cloud patch survived reprojection
