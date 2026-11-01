"""Tests for cached-scene iteration: sensing-date dedupe across baselines."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from terrascope.ingestion.pipeline import IngestionConfig, iter_cached_scenes

OCT = dt.date(2023, 10, 1)
OCT_END = dt.date(2023, 10, 31)


def _make_fake_scene(root: Path, scene_id: str) -> Path:
    scene_dir = root / "raw" / "sentinel-2-l2a" / scene_id
    scene_dir.mkdir(parents=True)
    for band in IngestionConfig().all_bands:
        (scene_dir / f"{band}.tif").write_bytes(b"")  # presence is what completeness checks
    return scene_dir


class TestIterCachedScenes:
    def test_duplicate_baseline_keeps_latest_processing(self, tmp_path: Path) -> None:
        _make_fake_scene(tmp_path, "S2B_MSIL2A_20231022T045839_R119_T44PMV_20231022T092540")
        _make_fake_scene(tmp_path, "S2B_MSIL2A_20231022T045839_R119_T44PMV_20240917T135946")
        scenes = iter_cached_scenes(
            tmp_path, start=OCT, end=OCT_END, config=IngestionConfig()
        )
        assert len(scenes) == 1
        assert scenes[0][1].name.endswith("20240917T135946")  # latest baseline wins

    def test_distinct_dates_all_kept_sorted(self, tmp_path: Path) -> None:
        for scene_id in (
            "S2A_MSIL2A_20231007T045701_R119_T44PMV_20231007T102707",
            "S2A_MSIL2A_20240115T050141_R119_T44PMV_20240115T081416",
        ):
            _make_fake_scene(tmp_path, scene_id)
        scenes = iter_cached_scenes(
            tmp_path,
            start=dt.date(2023, 10, 1),
            end=dt.date(2024, 1, 31),
            config=IngestionConfig(),
        )
        dates = [date for date, _ in scenes]
        assert dates == sorted(dates) == [dt.date(2023, 10, 7), dt.date(2024, 1, 15)]

    def test_window_and_incomplete_scenes_ignored(self, tmp_path: Path) -> None:
        inside = "S2A_MSIL2A_20231007T045701_R119_T44PMV_20231007T102707"
        outside = "S2A_MSIL2A_20240115T050141_R119_T44PMV_20240115T081416"
        _make_fake_scene(tmp_path, inside)
        _make_fake_scene(tmp_path, outside)
        (tmp_path / "raw" / "sentinel-2-l2a" / outside / "B04.tif").unlink()  # incomplete
        scenes = iter_cached_scenes(
            tmp_path, start=OCT, end=OCT_END, config=IngestionConfig()
        )
        assert [scene_dir.name for _, scene_dir in scenes] == [inside]
