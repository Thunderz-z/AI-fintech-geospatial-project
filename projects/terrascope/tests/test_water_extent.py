"""End-to-end water-extent tests on synthetic scenes (offline, no network)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pytest
from _terrascope_fixtures import SCENE_LEFT, SCENE_TOP, central_aoi, write_band
from affine import Affine

from terrascope.features.water_extent import (
    WaterExtentObservation,
    ramsar_mask_on_grid,
    scene_water_extent,
    water_extent_time_series,
    write_water_extent_report,
)
from terrascope.ingestion.cog_reader import CompositeGrid
from terrascope.ingestion.gate import DownloadGate
from terrascope.ingestion.pipeline import run_download

UTC = dt.UTC

SCENE_CLEAR = "S2A_MSIL2A_20240301T050111_R119_T44PMV_20240301T081416"

# A 4x4-pixel water block at 20 m (aligned to the 20 m grid): dark SWIR + bright green.
WATER_PATCH_B03 = (40, 40, 8, 8, 3000.0)  # 10 m rows/cols 40-47 -> 20 m rows/cols 20-23
WATER_PATCH_B11 = (20, 20, 4, 4, 500.0)  # 20 m rows/cols 20-23


@pytest.fixture()
def water_setup(tmp_path: Path, data_root: Path, fake_search_factory) -> Path:  # noqa: ANN001
    """One clear synthetic scene cached under data_root (cloudy ones never pass
    the metadata filter, so only the clear scene is downloaded)."""
    search_fn = fake_search_factory(
        [
            {
                "scene_id": SCENE_CLEAR,
                "date": "2024-03-01",
                "band_values": {"B03": 500.0, "B11": 5000.0},  # dry everywhere...
                # ...except the aligned water block:
                "band_patches": {"B03": WATER_PATCH_B03, "B11": WATER_PATCH_B11},
            },
            {
                "scene_id": "S2A_MSIL2A_20240306T050211_R119_T44PMV_20240306T081516",
                "date": "2024-03-06",
                "cloud_cover": 65.0,  # filtered out at download time
            },
        ]
    )
    run_download(
        central_aoi(),
        start=dt.date(2024, 3, 1),
        end=dt.date(2024, 3, 31),
        gate=DownloadGate.approved(),
        search_fn=search_fn,
        root=data_root,
    )
    return data_root


def _boundary_left_half(grid: CompositeGrid, path: Path) -> Path:
    """Boundary polygon covering the grid's left half, written as EPSG:4326
    GeoJSON (the format the real Ramsar file uses — GeoJSON is always parsed
    as WGS84, so the helper writes degrees via the inverse transform)."""
    from pyproj import Transformer

    left, bottom, right, top = grid.bounds
    mid = (left + right) / 2
    inverse = Transformer.from_crs(grid.crs_epsg, 4326, always_xy=True)
    lon_left, lat_bottom = inverse.transform(left, bottom)
    lon_mid, _ = inverse.transform(mid, bottom)
    _, lat_top = inverse.transform(mid, top)
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "left half"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [lon_left, lat_bottom],
                                    [lon_mid, lat_bottom],
                                    [lon_mid, lat_top],
                                    [lon_left, lat_top],
                                    [lon_left, lat_bottom],
                                ]
                            ],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


class TestWaterExtent:
    def test_clear_scene_water_fractions(self, water_setup: Path) -> None:  # noqa: ANN001
        grid20 = CompositeGrid.from_aoi(central_aoi(), resolution_m=10.0).at_resolution(2)
        boundary = _boundary_left_half(grid20, water_setup / "boundary.geojson")
        mask = ramsar_mask_on_grid(boundary, grid20)

        scene_dir = water_setup / "raw" / "sentinel-2-l2a" / SCENE_CLEAR
        obs = scene_water_extent(scene_dir, grid20, mask)

        assert not obs.abstained
        assert obs.valid_fraction == pytest.approx(1.0)
        # The aligned 4x4 water block maps to exactly 16 grid20 pixels.
        assert obs.water_px_aoi == 16
        assert obs.water_fraction_aoi == pytest.approx(16 / (grid20.height * grid20.width))
        # All 16 water pixels lie inside the left-half boundary.
        assert obs.water_px_ramsar == 16
        ramsar_valid = int(np.count_nonzero(mask))
        assert obs.water_fraction_ramsar == pytest.approx(16 / ramsar_valid)

    def test_metadata_filtered_scene_never_enters_series(self, water_setup: Path) -> None:  # noqa: ANN001
        grid20 = CompositeGrid.from_aoi(central_aoi(), resolution_m=10.0).at_resolution(2)
        boundary = _boundary_left_half(grid20, water_setup / "boundary.geojson")
        series = water_extent_time_series(
            start=dt.date(2024, 3, 1),
            end=dt.date(2024, 3, 31),
            boundary_geojson=boundary,
            root=water_setup,
            aoi=central_aoi(),
        )
        assert len(series) == 1  # the 65%-cloud scene was never downloaded
        assert series[0].scene_id == SCENE_CLEAR
        assert not series[0].abstained

    def test_abstention_on_poor_quality(self, water_setup: Path) -> None:  # noqa: ANN001
        """A scene whose SCL is nearly all cloud is recorded as abstained."""
        grid20 = CompositeGrid.from_aoi(central_aoi(), resolution_m=10.0).at_resolution(2)
        scene_dir = water_setup / "raw" / "sentinel-2-l2a" / SCENE_CLEAR
        scl_path = scene_dir / "SCL.tif"
        scl_path.unlink()
        write_band(
            scl_path,
            np.full((50, 50), 8, dtype=np.uint8),
            Affine(20, 0, SCENE_LEFT, 0, -20, SCENE_TOP),
        )

        obs = scene_water_extent(scene_dir, grid20, np.zeros(grid20.shape, dtype=bool))
        assert obs.abstained
        assert obs.water_fraction_aoi is None
        assert obs.abstention_reason is not None and "valid fraction" in obs.abstention_reason

    def test_report_writer(self, tmp_path: Path) -> None:  # noqa: ANN001
        obs = WaterExtentObservation(
            scene_id="s",
            sensing_date="2024-03-01",
            processing_stamp="20240301T081416",
            valid_fraction=0.99,
            water_fraction_aoi=0.25,
            water_fraction_ramsar=0.1,
            valid_px_aoi=1000,
            water_px_aoi=250,
            valid_px_ramsar=200,
            water_px_ramsar=20,
            threshold=0.0,
            abstained=False,
            abstention_reason=None,
        )
        out = write_water_extent_report([obs], tmp_path / "report.json")
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["observations"][0]["water_fraction_aoi"] == 0.25
