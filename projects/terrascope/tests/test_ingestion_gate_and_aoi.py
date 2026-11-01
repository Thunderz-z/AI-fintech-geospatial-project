"""Tests for the download gate and study-area geometry."""

from __future__ import annotations

import datetime as dt

import pytest
from _terrascope_fixtures import central_aoi

from terrascope.ingestion.aoi import (
    APPROXIMATE_PALLIKARANAI_BBOX_4326,
    StudyAOI,
    aoi_from_bbox,
    approximate_pallikaranai_aoi,
    load_boundary_geojson,
)
from terrascope.ingestion.gate import DownloadGate, DownloadNotApprovedError, is_remote_uri
from terrascope.ingestion.pipeline import scene_date_from_id


class TestGate:
    def test_local_uris_allowed(self) -> None:
        gate = DownloadGate()
        gate.require("C:/some/path/band.tif", "test")  # does not raise
        gate.require("file:///d/band.tif", "test")  # does not raise
        assert not is_remote_uri("relative/path.tif")

    def test_remote_uris_blocked_without_approval(self) -> None:
        gate = DownloadGate()
        with pytest.raises(DownloadNotApprovedError) as excinfo:
            gate.require("https://planetarycomputer.example/blob.tif", "test read")
        assert "approval" in str(excinfo.value).lower()
        assert "https://planetarycomputer.example/blob.tif" in str(excinfo.value)

    @pytest.mark.parametrize("uri", ["https://x/y", "http://x/y", "s3://bucket/key", "abfs://c/k"])
    def test_is_remote_uri(self, uri: str) -> None:
        assert is_remote_uri(uri)

    def test_approved_gate_allows_remote(self) -> None:
        DownloadGate.approved().require("https://x/y", "test")  # does not raise


class TestApproximateAOI:
    def test_bbox_and_status(self) -> None:
        aoi = approximate_pallikaranai_aoi()
        assert aoi.bbox_wgs84 == pytest.approx(APPROXIMATE_PALLIKARANAI_BBOX_4326)
        assert "approximate" in aoi.boundary_status.lower()
        assert aoi.geometry_wgs84.is_valid

    def test_reprojection_to_study_crs(self) -> None:
        aoi = approximate_pallikaranai_aoi()
        utm = aoi.geometry_in_crs(32644)
        # Pallikaranai spans roughly 10-11 km E-W and ~14 km N-S in UTM 44N.
        minx, miny, maxx, maxy = utm.bounds
        assert 8_000 < maxx - minx < 14_000
        assert 13_000 < maxy - miny < 16_000

    def test_invalid_bbox_rejected(self) -> None:
        with pytest.raises(ValueError, match="bbox"):
            aoi_from_bbox((80.0, 13.0, 79.0, 12.0))  # minx > maxx

    def test_central_aoi_inside_synthetic_scene(self) -> None:
        aoi = central_aoi()
        assert "synthetic" in aoi.name


class TestBoundaryLoader:
    def test_load_geojson_boundary(self, tmp_path) -> None:  # noqa: ANN001 - pytest tmp_path
        geojson_path = tmp_path / "boundary.geojson"
        geojson_path.write_text(
            '{"type": "FeatureCollection", "features": [{"type": "Feature", '
            '"properties": {"name": "Pallikaranai Marsh Reserve Forest (Ramsar IN2481)"}, '
            '"geometry": {"type": "Polygon", "coordinates": [[[80.20, 12.88], [80.26, 12.88], '
            '[80.26, 12.96], [80.20, 12.96], [80.20, 12.88]]]}}]}',
            encoding="utf-8",
        )
        aoi = load_boundary_geojson(geojson_path)
        assert isinstance(aoi, StudyAOI)
        assert "Ramsar" in aoi.name
        assert "authoritative" in aoi.boundary_status
        assert aoi.bbox_wgs84 == pytest.approx((80.20, 12.88, 80.26, 12.96))

    def test_empty_boundary_rejected(self, tmp_path) -> None:  # noqa: ANN001 - pytest tmp_path
        geojson_path = tmp_path / "empty.geojson"
        geojson_path.write_text(
            '{"type": "FeatureCollection", "features": []}', encoding="utf-8"
        )
        with pytest.raises(ValueError, match="no features"):
            load_boundary_geojson(geojson_path)


class TestSceneDateFromId:
    def test_sentinel2_scene_id(self) -> None:
        scene_id = "S2B_MSIL2A_20240115T050229_N0510_R028_T44QPH_20240115T081234"
        assert scene_date_from_id(scene_id) == dt.date(2024, 1, 15)

    def test_unparseable_id(self) -> None:
        assert scene_date_from_id("not-a-scene-id") is None
