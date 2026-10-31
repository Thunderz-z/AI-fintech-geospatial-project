"""End-to-end pipeline tests on synthetic scenes (offline; approval-gate checks)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json

import numpy as np
import pytest
import rasterio
from _terrascope_fixtures import RES_10M

from terrascope.ingestion.gate import DownloadGate, DownloadNotApprovedError
from terrascope.ingestion.pipeline import IngestionConfig, run_composite, run_download

UTC = dt.UTC

SCENE_B = "S2B_MSIL2A_20240115T050229_N0510_R028_T44QPH_20240115T081234"  # 2024-01-15
SCENE_A = "S2A_MSIL2A_20240210T050301_N0510_R028_T44QPH_20240210T082111"  # 2024-02-10


def _sha256(path) -> str:  # noqa: ANN001 - pytest tmp paths
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class TestDownloadGate:
    def test_unapproved_run_never_touches_network(self, small_aoi, data_root) -> None:  # noqa: ANN001
        """The default search_fn is the real one; the gate must block it *before*
        any request. If a network call were attempted, the test would hang or
        fail with a connection error instead of the typed gate error."""
        with pytest.raises(DownloadNotApprovedError) as excinfo:
            run_download(
                small_aoi,
                start=dt.date(2024, 1, 1),
                end=dt.date(2024, 3, 31),
                gate=DownloadGate(),
                root=data_root,
            )
        assert "STAC search" in str(excinfo.value)

    def test_approved_run_reads_only_local_fixtures(
        self, small_aoi, data_root, fake_search_factory  # noqa: ANN001
    ) -> None:
        """With an injected offline search, an approved run writes cached
        windows + acquisition log; the gate never trips (all hrefs local)."""
        search_fn = fake_search_factory(
            [
                {"scene_id": SCENE_B, "date": "2024-01-15"},
                {"scene_id": SCENE_A, "date": "2024-02-10"},
            ]
        )
        report = run_download(
            small_aoi,
            start=dt.date(2024, 1, 1),
            end=dt.date(2024, 3, 31),
            gate=DownloadGate.approved(),
            search_fn=search_fn,
            root=data_root,
        )
        assert report.scenes_read == [SCENE_B, SCENE_A]  # sorted by acquisition time
        assert not report.scenes_cached
        assert len(report.files_written) == 14  # (6 bands + SCL) x 2 scenes
        assert report.total_mb > 0

        scene_dir = data_root / "raw" / "sentinel-2-l2a" / SCENE_B
        for band in ("B02", "B03", "B04", "B08", "B11", "B12", "SCL"):
            assert (scene_dir / f"{band}.tif").is_file()

        log_path = data_root / "raw" / "sentinel-2-l2a" / "acquisition_log.jsonl"
        entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert len(entries) == 14
        entry = next(e for e in entries if e["scene_id"] == SCENE_B and e["band"] == "B04")
        assert entry["sha256"] == _sha256(scene_dir / "B04.tif")
        assert entry["bytes"] > 0
        assert entry["scene_datetime"].startswith("2024-01-15")
        assert "sentinel-2-l2a" in entry["source_collection"]

    def test_rerun_skips_cached_scenes(
        self, small_aoi, data_root, fake_search_factory  # noqa: ANN001
    ) -> None:
        search_fn = fake_search_factory([{"scene_id": SCENE_B, "date": "2024-01-15"}])
        common = {
            "start": dt.date(2024, 1, 1),
            "end": dt.date(2024, 3, 31),
            "gate": DownloadGate.approved(),
            "search_fn": search_fn,
            "root": data_root,
        }
        first = run_download(small_aoi, **common)
        assert len(first.scenes_read) == 1
        second = run_download(small_aoi, **common)
        assert second.scenes_read == []
        assert second.scenes_cached == first.scenes_read
        assert second.files_written == []

    def test_cloudy_scene_filtered_out(
        self, small_aoi, data_root, fake_search_factory  # noqa: ANN001
    ) -> None:
        search_fn = fake_search_factory(
            [
                {"scene_id": SCENE_B, "date": "2024-01-15"},
                {"scene_id": SCENE_A, "date": "2024-02-10", "cloud_cover": 65.0},
            ]
        )
        report = run_download(
            small_aoi,
            start=dt.date(2024, 1, 1),
            end=dt.date(2024, 3, 31),
            gate=DownloadGate.approved(),
            search_fn=search_fn,
            root=data_root,
        )
        assert report.scenes_filtered_out == 1
        assert report.scenes_read == [SCENE_B]


class TestComposite:
    @pytest.fixture()
    def downloaded(self, small_aoi, data_root, fake_search_factory):  # noqa: ANN001
        """Two winter scenes cached under data_root:
        scene 2 has a cloud patch (SCL 8) inside the AOI, a half-pixel grid
        drift, and a different B08 value so masking is visible in the values.
        """
        search_fn = fake_search_factory(
            [
                {"scene_id": SCENE_B, "date": "2024-01-15"},  # B08 = 4000 everywhere
                {
                    "scene_id": SCENE_A,
                    "date": "2024-02-10",
                    "scl_classes": [(8, 24, 24)],  # 4x4 px at 20 m, inside the AOI
                    "offset_m": 5.0,
                    "band_values": {"B08": 4200.0},
                },
            ]
        )
        run_download(
            small_aoi,
            start=dt.date(2024, 1, 1),
            end=dt.date(2024, 3, 31),
            gate=DownloadGate.approved(),
            search_fn=search_fn,
            root=data_root,
        )
        return data_root

    def test_seasonal_composites_offline(self, small_aoi, downloaded) -> None:  # noqa: ANN001
        report = run_composite(
            small_aoi, start=dt.date(2024, 1, 1), end=dt.date(2024, 3, 31), root=downloaded
        )
        assert report.season_scene_counts == {"winter": 2}
        assert report.scenes_used == [SCENE_B, SCENE_A]
        winter_dir = downloaded / "processed" / "composites" / "winter"
        for band in ("B02", "B03", "B04", "B08", "B11", "B12"):
            assert (winter_dir / f"{band}_median.tif").is_file()
            assert (winter_dir / f"{band}_validcount.tif").is_file()

        provenance = json.loads(
            (winter_dir / "provenance.json").read_text(encoding="utf-8")
        )
        assert provenance["season"] == "winter"
        assert provenance["scene_ids"] == [SCENE_B, SCENE_A]
        assert provenance["scl_exclude"] == [0, 1, 3, 8, 9, 10, 11]
        assert provenance["grid"]["resolution_m"] == RES_10M
        assert "approximate" in provenance["aoi"]["boundary_status"]

    def test_composite_values_and_cloud_masking(self, small_aoi, downloaded) -> None:  # noqa: ANN001
        report = run_composite(
            small_aoi, start=dt.date(2024, 1, 1), end=dt.date(2024, 3, 31), root=downloaded
        )
        winter_dir = downloaded / "processed" / "composites" / "winter"

        with rasterio.open(winter_dir / "B08_median.tif") as src:
            assert src.profile["driver"] == "GTiff"  # COG layout writes as GTiff
            assert src.profile["tiled"]
            median = src.read(1)
        with rasterio.open(winter_dir / "B08_validcount.tif") as src:
            count = src.read(1)

        # Two valid observations everywhere except the cloud patch: median of
        # (4000, 4200) = 4100 there; patch pixels only have scene 1 -> 4000.
        assert count.min() == 1
        assert count.max() == 2
        assert (count == 2).mean() > 0.9
        assert np.allclose(median[count == 2], 4100.0, atol=2.0)
        assert np.allclose(median[count == 1], 4000.0, atol=2.0)
        # The compositing reported a maximum of two valid observations per pixel.
        assert report.valid_obs_max == {"winter": 2}

    def test_empty_cache_raises(self, small_aoi, data_root) -> None:  # noqa: ANN001
        with pytest.raises(RuntimeError, match="No cached scenes"):
            run_composite(
                small_aoi, start=dt.date(2030, 1, 1), end=dt.date(2030, 3, 31), root=data_root
            )


class TestConfig:
    def test_defaults_mirror_repo_config(self) -> None:
        config = IngestionConfig()
        assert config.all_bands == ("B02", "B03", "B04", "B08", "B11", "B12", "SCL")
        assert config.cloud_cover_max_pct == 20.0
        assert config.scl_exclude == frozenset({0, 1, 3, 8, 9, 10, 11})
        assert config.grid_resolution_m == 10.0
