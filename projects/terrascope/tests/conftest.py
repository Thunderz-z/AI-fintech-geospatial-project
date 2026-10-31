"""Pytest fixtures for TerraScope ingestion tests (offline; no network).

Scene-building helpers live in ``_terrascope_fixtures`` (uniquely named to
avoid module collisions across the monorepo's test suites); test modules
import helpers from there directly.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path

import pytest
from _terrascope_fixtures import central_aoi, make_scene_fixture, make_stac_item

from terrascope.ingestion.aoi import StudyAOI
from terrascope.ingestion.scenes import SceneCandidate, extract_candidate

UTC = dt.UTC


@pytest.fixture()
def small_aoi() -> StudyAOI:
    """AOI covering the central 400 m x 400 m of the synthetic scene extent."""
    return central_aoi()


@pytest.fixture()
def fake_search_factory(tmp_path: Path) -> Callable[..., Callable[..., list[SceneCandidate]]]:
    """Factory for offline search functions backed by synthetic local scenes."""

    def _factory(
        scenes: list[dict],
    ) -> Callable[..., list[SceneCandidate]]:
        """Each entry of *scenes*: dict(scene_id, date, cloud_cover, scl_classes, offset_m)."""
        candidates: list[SceneCandidate] = []
        for spec in scenes:
            scene_dir = tmp_path / "fixtures" / spec["scene_id"]
            hrefs = make_scene_fixture(
                scene_dir,
                scl_classes=spec.get("scl_classes"),
                band_values=spec.get("band_values"),
                grid_offset_m=spec.get("offset_m", 0.0),
            )
            item = make_stac_item(
                spec["scene_id"],
                dt.datetime.fromisoformat(spec["date"]).replace(tzinfo=UTC),
                hrefs,
                cloud_cover=spec.get("cloud_cover", 5.0),
            )
            candidates.append(extract_candidate(item))

        def _search(
            aoi, start, end, max_cloud_cover_pct, gate
        ):  # noqa: ANN001 - mirrors the SearchFn protocol (called with keywords)
            # Deliberately NO server-side cloud/date filtering: the real STAC
            # query filters server-side, but returning everything here exercises
            # the pipeline's own scene filter (the thing under test).
            return candidates

        return _search

    return _factory


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Temporary PORTFOLIO_DATA_ROOT with the terrascope subtree (ADR-0003 path)."""
    root = tmp_path / "data root"  # space on purpose: real root path has spaces
    (root / "terrascope").mkdir(parents=True)
    monkeypatch.setenv("PORTFOLIO_DATA_ROOT", str(root))
    return root
