"""Tests for scene candidate extraction and offline filtering (real pystac items)."""

from __future__ import annotations

import datetime as dt

import pystac
import pytest
from _terrascope_fixtures import make_stac_item

from terrascope.ingestion.scenes import (
    ALL_BANDS,
    BANDS_10M,
    BANDS_20M,
    SceneCandidate,
    extract_candidate,
    filter_scenes,
)

UTC = dt.UTC


def _scene_id(date: str) -> str:
    stamp = date.replace("-", "")
    return f"S2B_MSIL2A_{stamp}T050229_N0510_R028_T44QPH_{stamp}T081234"


def _candidate(
    date: str, *, cloud: float = 5.0, drop_bands: tuple[str, ...] = ()
) -> SceneCandidate:
    hrefs = {band: f"https://example/{band}.tif" for band in ALL_BANDS if band not in drop_bands}
    item = make_stac_item(
        _scene_id(date),
        dt.datetime.fromisoformat(f"{date}T05:02:29").replace(tzinfo=UTC),
        hrefs,
        cloud_cover=cloud,
    )
    return extract_candidate(item)


class TestExtractCandidate:
    def test_extracts_metadata_and_bands(self) -> None:
        candidate = _candidate("2024-01-15", cloud=12.5)
        assert candidate.scene_id == _scene_id("2024-01-15")
        assert candidate.cloud_cover_pct == pytest.approx(12.5)
        assert candidate.datetime_utc.tzinfo is UTC
        assert candidate.mgrs_tile == "MGRS-44QPH"
        assert candidate.epsg == 32644
        assert set(candidate.band_hrefs) == set(ALL_BANDS)

    def test_naive_datetime_coerced_to_utc(self) -> None:
        item = make_stac_item(
            "naive-item",
            dt.datetime(2024, 2, 1, 5, 0),  # naive
            {band: f"https://example/{band}.tif" for band in ALL_BANDS},
        )
        candidate = extract_candidate(item)
        assert candidate.datetime_utc.tzinfo is UTC

    def test_item_without_datetime_rejected(self) -> None:
        item = make_stac_item("x", dt.datetime(2024, 1, 1, tzinfo=UTC), {})
        item.properties["start_datetime"] = "2024-01-01T00:00:00Z"
        item.datetime = None
        with pytest.raises(ValueError, match="no datetime"):
            extract_candidate(item)

    def test_missing_bands_reported(self) -> None:
        candidate = _candidate("2024-02-01", drop_bands=("B08", "SCL"))
        assert candidate.missing_bands() == ("B08", "SCL")
        assert candidate.missing_bands(("B04",)) == ()


class TestFilterScenes:
    def test_cloud_cover_filter(self) -> None:
        candidates = [
            _candidate("2024-01-10", cloud=5.0),
            _candidate("2024-01-11", cloud=25.0),
            _candidate("2024-01-12"),  # cloud unknown? -> set explicitly below
        ]
        # Candidate 3 has cloud 5.0 by default; craft an unknown one:
        unknown = make_stac_item(
            _scene_id("2024-01-13"),
            dt.datetime(2024, 1, 13, 5, tzinfo=UTC),
            {band: f"https://example/{band}.tif" for band in ALL_BANDS},
        )
        unknown.properties.pop("eo:cloud_cover")
        candidates.append(extract_candidate(unknown))
        assert len(candidates) == 4

        kept = filter_scenes(candidates, max_cloud_cover_pct=20.0)
        assert [c.scene_id for c in kept] == [
            _scene_id("2024-01-10"),
            _scene_id("2024-01-12"),
        ]  # 25% too cloudy; unknown cloud cover excluded, not silently passed

    def test_date_window_filter_inclusive(self) -> None:
        candidates = [
            _candidate("2024-01-09"),
            _candidate("2024-01-10"),
            _candidate("2024-01-11"),
        ]
        kept = filter_scenes(candidates, start=dt.date(2024, 1, 10), end=dt.date(2024, 1, 11))
        assert [c.scene_id for c in kept] == [_scene_id("2024-01-10"), _scene_id("2024-01-11")]

    def test_incomplete_scenes_dropped(self) -> None:
        candidates = [
            _candidate("2024-01-10"),
            _candidate("2024-01-11", drop_bands=("B11",)),
        ]
        kept = filter_scenes(candidates)
        assert [c.scene_id for c in kept] == [_scene_id("2024-01-10")]

    def test_sorted_by_time(self) -> None:
        candidates = [_candidate("2024-01-12"), _candidate("2024-01-10")]
        kept = filter_scenes(candidates)
        assert [c.scene_id for c in kept] == [_scene_id("2024-01-10"), _scene_id("2024-01-12")]

    def test_band_group_constants(self) -> None:
        assert BANDS_10M == ("B02", "B03", "B04", "B08")
        assert BANDS_20M == ("B11", "B12", "SCL")
        assert ALL_BANDS == BANDS_10M + BANDS_20M

    def test_pystac_item_type_roundtrip(self) -> None:
        """The fixture items are real pystac Items (not mocks)."""
        item = make_stac_item("real", dt.datetime(2024, 1, 1, tzinfo=UTC), {})
        assert isinstance(item, pystac.Item)
