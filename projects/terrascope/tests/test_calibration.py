"""Tests for MNDWI threshold calibration (offline, grid-aligned synthetic data)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from _terrascope_fixtures import central_aoi, write_band

from terrascope.features.calibration import (
    calibrate_threshold,
    read_reference_water_mask,
    result_to_dict,
    score_qa_points,
    score_threshold,
)
from terrascope.ingestion.cog_reader import CompositeGrid

SCENE_CLEAR = "S2A_MSIL2A_20240301T050111_R119_T44PMV_20240301T081416"

# A 4x4-cell water block on the 20 m grid, away from edges.
BLOCK_ROW, BLOCK_COL, BLOCK = 5, 5, 4


def _grids() -> tuple[CompositeGrid, CompositeGrid]:
    grid10 = CompositeGrid.from_aoi(central_aoi(), resolution_m=10.0)
    return grid10, grid10.at_resolution(2)


def _block_bounds(grid: CompositeGrid) -> tuple[float, float, float, float]:
    """UTM (left, bottom, right, top) of the synthetic water block."""
    left = grid.transform.c + BLOCK_COL * grid.resolution_m
    top = grid.transform.f - BLOCK_ROW * grid.resolution_m
    size = BLOCK * grid.resolution_m
    return (left, top - size, left + size, top)


def _reference_raster(grid: CompositeGrid, path: Path) -> Path:
    """Grid-aligned uint8 class raster: 80 (water) inside the block, 40 outside."""
    classes = np.full(grid.shape, 40, dtype=np.uint8)
    classes[BLOCK_ROW : BLOCK_ROW + BLOCK, BLOCK_COL : BLOCK_COL + BLOCK] = 80
    return write_band(path, classes, grid.transform)


def _scene_with_water_block(grid10: CompositeGrid, grid20: CompositeGrid, scene_dir: Path) -> Path:
    """Minimal cached scene (SCL/B03/B11) whose MNDWI is +0.71 inside the
    block and -0.82 outside, written on the *grid* transforms so the block
    aligns exactly regardless of the snapped grid origin."""
    import numpy as np
    from _terrascope_fixtures import BAND_BASE_VALUES  # noqa: F401 - docs only

    scl = np.full(grid20.shape, 4, dtype=np.uint8)  # vegetation = valid
    write_band(scene_dir / "SCL.tif", scl, grid20.transform)

    b03 = np.full(grid10.shape, 500, dtype=np.uint16)  # dry green (dark)
    b03[
        BLOCK_ROW * 2 : (BLOCK_ROW + BLOCK) * 2, BLOCK_COL * 2 : (BLOCK_COL + BLOCK) * 2
    ] = 3000  # water block: bright green
    write_band(scene_dir / "B03.tif", b03, grid10.transform)

    b11 = np.full(grid20.shape, 5000, dtype=np.uint16)  # dry SWIR (bright)
    b11[BLOCK_ROW : BLOCK_ROW + BLOCK, BLOCK_COL : BLOCK_COL + BLOCK] = 500
    write_band(scene_dir / "B11.tif", b11, grid20.transform)
    return scene_dir


class TestScoreThreshold:
    def test_perfect_separation(self) -> None:
        index = np.array([[0.5, -0.5], [0.8, -0.2]], dtype=np.float32)
        reference = np.array([[True, False], [True, False]])
        valid = np.ones_like(reference)
        defined = np.ones_like(reference)
        score = score_threshold(index, valid, reference, defined, 0.0)
        assert score.kappa == 1.0
        assert score.accuracy == 1.0
        assert score.precision_water == 1.0 and score.recall_water == 1.0
        assert score.n_pixels == 4

    def test_nan_and_undefined_excluded(self) -> None:
        index = np.array([[0.5, np.nan], [0.8, -0.2]], dtype=np.float32)
        reference = np.array([[True, False], [True, False]])
        valid = np.ones_like(reference)
        defined = np.array([[True, True], [True, False]])  # bottom-right undefined
        score = score_threshold(index, valid, reference, defined, 0.0)
        assert score.n_pixels == 3  # NaN and undefined cells drop out


class TestReferenceMask:
    def test_grid_aligned_block(self, tmp_path: Path) -> None:  # noqa: ANN001
        _, grid = _grids()
        raster = _reference_raster(grid, tmp_path / "wc_map.tif")
        water, defined = read_reference_water_mask(raster, grid)
        assert defined.all()  # raster covers the whole grid
        assert water[BLOCK_ROW, BLOCK_COL]
        assert water.sum() == BLOCK * BLOCK
        assert not water[0, 0]

    def test_nonoverlap_raises(self, tmp_path: Path) -> None:  # noqa: ANN001
        from _terrascope_fixtures import TRANSFORM_20M, write_band

        from terrascope.ingestion.aoi import aoi_from_bbox

        _, grid = _grids()
        raster = write_band(
            tmp_path / "far.tif", np.full((50, 50), 80, dtype=np.uint8), TRANSFORM_20M
        )
        paris_grid = CompositeGrid.from_aoi(
            aoi_from_bbox((2.25, 48.80, 2.45, 48.90)), resolution_m=20.0
        )
        with pytest.raises(ValueError, match="does not overlap"):
            read_reference_water_mask(raster, paris_grid)


class TestCalibrate:
    def test_chooses_the_separating_threshold(self, tmp_path: Path) -> None:  # noqa: ANN001
        grid10, grid20 = _grids()
        _reference_raster(grid20, tmp_path / "wc_map.tif")
        reference, reference_defined = read_reference_water_mask(
            tmp_path / "wc_map.tif", grid20
        )
        scene_dir = _scene_with_water_block(grid10, grid20, tmp_path / SCENE_CLEAR)
        result = calibrate_threshold([scene_dir], grid20, reference, reference_defined)

        assert result.n_dates == 1
        # Everything in (-0.82, +0.71) separates perfectly; the tie-break picks
        # the threshold closest to zero.
        assert result.threshold == pytest.approx(0.0)
        chosen = result.scores_at_chosen[0]
        assert chosen.kappa == 1.0
        assert chosen.n_pixels == grid20.width * grid20.height
        payload = result_to_dict(result)
        assert payload["scores_at_chosen"][0]["kappa"] == 1.0

    def test_empty_scene_list_rejected(self, tmp_path: Path) -> None:  # noqa: ANN001
        _, grid20 = _grids()
        reference = np.zeros(grid20.shape, dtype=bool)
        defined = np.ones(grid20.shape, dtype=bool)
        with pytest.raises(ValueError, match="No scenes"):
            calibrate_threshold([], grid20, reference, defined)


class TestQAPoints:
    def test_points_scored_against_grid(self, tmp_path: Path) -> None:  # noqa: ANN001
        from pyproj import Transformer

        grid10, grid20 = _grids()
        index = np.full(grid20.shape, -0.5, dtype=np.float32)
        index[BLOCK_ROW : BLOCK_ROW + BLOCK, BLOCK_COL : BLOCK_COL + BLOCK] = 0.7

        left, bottom, right, top = _block_bounds(grid20)
        cx, cy = (left + right) / 2, (bottom + top) / 2
        dry_x = grid20.transform.c + 1 * grid20.resolution_m
        dry_y = grid20.transform.f - 1 * grid20.resolution_m
        inverse = Transformer.from_crs(grid20.crs_epsg, 4326, always_xy=True)
        cx84, cy84 = inverse.transform(cx, cy)
        dry_x84, dry_y84 = inverse.transform(dry_x, dry_y)

        # GeoJSON is parsed as EPSG:4326, so the helper writes degrees.
        qa = tmp_path / "qa.geojson"
        qa.write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"name": "pond", "class": "water"},
                            "geometry": {"type": "Point", "coordinates": [cx84, cy84]},
                        },
                        {
                            "type": "Feature",
                            "properties": {"name": "dryland", "class": "not_water"},
                            "geometry": {"type": "Point", "coordinates": [dry_x84, dry_y84]},
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        scores = score_qa_points(qa, index, grid20, threshold=0.0)
        assert len(scores) == 2
        pond = next(s for s in scores if s.name == "pond")
        dry = next(s for s in scores if s.name == "dryland")
        assert pond.expected_water and pond.predicted_water and pond.agrees
        assert not dry.expected_water and not dry.predicted_water and dry.agrees
