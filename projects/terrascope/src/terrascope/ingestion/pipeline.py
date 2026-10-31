"""Ingestion pipeline: search -> windowed reads -> cache -> mask -> composites.

Stages are deliberately separate so each can run offline against the cache:

* :func:`run_download` — STAC search (network, approval-gated) + AOI-bounded
  windowed COG reads persisted as-acquired under ``raw/`` with SHA-256
  checksums and an append-only acquisition log. Idempotent: scenes already
  cached with all required bands are skipped.
* :func:`run_composite` — offline from the cache: SCL masking + seasonal
  median compositing onto a fixed grid, written as COGs under ``processed/``
  with a provenance sidecar per composite.

Data locations resolve through ``terrascope.config.data_dir`` (ADR-0003 —
``PORTFOLIO_DATA_ROOT``; never a silent fallback). All layout paths are
relative to that root.

Testing: pass ``search_fn=...`` to inject synthetic scenes whose asset hrefs
point at local fixture files, so the whole flow runs without network.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import rasterio

from terrascope.config import data_dir
from terrascope.ingestion.aoi import STUDY_CRS_EPSG, StudyAOI
from terrascope.ingestion.cog_reader import (
    CompositeGrid,
    WindowRead,
    read_band_onto_grid,
    read_bounds_window,
    read_scl_onto_grid,
)
from terrascope.ingestion.composite import DEFAULT_SEASON_MONTHS, group_by_season, median_composite
from terrascope.ingestion.gate import DownloadGate
from terrascope.ingestion.masking import (
    SCL_EXCLUDE_DEFAULT,
    apply_mask,
    scl_valid_mask,
    upscale_mask_nearest,
    valid_fraction,
)
from terrascope.ingestion.scenes import (
    BANDS_10M,
    BANDS_20M,
    SceneCandidate,
    filter_scenes,
)
from terrascope.ingestion.stac_search import search_sentinel2

__all__ = [
    "DEFAULT_SEARCH_FN",
    "DownloadReport",
    "IngestionConfig",
    "CompositeReport",
    "run_composite",
    "run_download",
]

#: Search function protocol. Called with keywords:
#: ``search_fn(aoi=..., start=..., end=..., max_cloud_cover_pct=..., gate=...)``.
#: The default (:func:`terrascope.ingestion.stac_search.search_sentinel2`) hits
#: the network and enforces *gate*; tests inject an offline equivalent.
SearchFn = Callable[..., list[SceneCandidate]]

#: Real search (network, must be called with an approved gate via ``gate``).
DEFAULT_SEARCH_FN: SearchFn = search_sentinel2


@dataclass(frozen=True)
class IngestionConfig:
    """Processing configuration (mirrors ``configs/processing.example.yaml``)."""

    bands_10m: tuple[str, ...] = BANDS_10M
    bands_20m: tuple[str, ...] = BANDS_20M
    cloud_cover_max_pct: float = 20.0
    scl_exclude: frozenset[int] = SCL_EXCLUDE_DEFAULT
    season_months: dict[str, frozenset[int]] = field(default_factory=lambda: DEFAULT_SEASON_MONTHS)
    grid_resolution_m: float = 10.0
    grid_crs_epsg: int = STUDY_CRS_EPSG

    @property
    def all_bands(self) -> tuple[str, ...]:
        return self.bands_10m + self.bands_20m


@dataclass
class DownloadReport:
    """What :func:`run_download` did (persisted inputs; no analysis claims)."""

    scenes_read: list[str] = field(default_factory=list)
    scenes_cached: list[str] = field(default_factory=list)
    scenes_filtered_out: int = 0
    files_written: list[Path] = field(default_factory=list)
    total_bytes: int = 0
    valid_fractions: dict[str, float] = field(default_factory=dict)  # scene -> SCL valid fraction

    @property
    def total_mb(self) -> float:
        return self.total_bytes / (1024 * 1024)


@dataclass
class CompositeReport:
    """What :func:`run_composite` produced (paths + coverage diagnostics)."""

    composites: list[Path] = field(default_factory=list)
    provenance: list[Path] = field(default_factory=list)
    scenes_used: list[str] = field(default_factory=list)
    season_scene_counts: dict[str, int] = field(default_factory=dict)
    valid_obs_max: dict[str, int] = field(default_factory=dict)  # season -> max valid_count


def _raw_dir(root: Path) -> Path:
    return root / "raw" / "sentinel-2-l2a"


def _processed_dir(root: Path) -> Path:
    return root / "processed" / "composites"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_window(
    path: Path, window_read: WindowRead
) -> None:
    """Persist one as-acquired band window as a tiled GeoTIFF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    profile: dict[str, Any] = {
        "driver": "GTiff",
        "height": window_read.array.shape[0],
        "width": window_read.array.shape[1],
        "count": 1,
        "dtype": str(window_read.array.dtype),
        "crs": f"EPSG:{window_read.crs_epsg}",
        "transform": window_read.transform,
        "compress": "deflate",
        "tiled": True,
    }
    if window_read.nodata is not None:
        profile["nodata"] = window_read.nodata
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(window_read.array, 1)


def _log_acquisition(log_path: Path, entry: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def _scene_complete(scene_dir: Path, bands: tuple[str, ...]) -> bool:
    return scene_dir.is_dir() and all((scene_dir / f"{band}.tif").is_file() for band in bands)


def run_download(
    aoi: StudyAOI,
    *,
    start: dt.date,
    end: dt.date,
    gate: DownloadGate,
    config: IngestionConfig | None = None,
    search_fn: SearchFn = DEFAULT_SEARCH_FN,
    root: Path | None = None,
) -> DownloadReport:
    """Search Sentinel-2 L2A and persist AOI-bounded band windows under ``raw/``.

    The STAC search passes through *gate* (raises
    :class:`DownloadNotApprovedError` when not approved); asset hrefs are
    signed by the search and read window-by-window. Windows are clipped to the
    **composite-grid bounds** (the AOI bbox snapped to the analysis resolution)
    so the cache and the compositing grid coincide exactly — no permanent
    zero-observation edges, and re-runs after interruption only fetch what is
    missing (cached scenes with all required bands are skipped).

    Args:
        aoi: Study area (bbox drives the STAC search; grid bounds clip reads).
        start / end: Inclusive date window (UTC).
        gate: Approval gate for the search and any remote reads.
        config: Processing configuration (defaults mirror the repo config).
        search_fn: Injectable for tests; the default hits Planetary Computer.
        root: Data-root override (tests); default resolves via
            ``terrascope.config.data_dir`` (external drive, ADR-0003).

    Returns:
        :class:`DownloadReport` describing what was fetched or already cached.
    """
    config = config or IngestionConfig()
    root = root or data_dir()
    raw_dir = _raw_dir(root)
    log_path = raw_dir / "acquisition_log.jsonl"
    report = DownloadReport()

    grid10 = CompositeGrid.from_aoi(
        aoi, resolution_m=config.grid_resolution_m, epsg=config.grid_crs_epsg
    )
    grid20 = grid10.at_resolution(2)

    candidates = search_fn(
        aoi=aoi,
        start=start,
        end=end,
        max_cloud_cover_pct=config.cloud_cover_max_pct,
        gate=gate,
    )
    usable = filter_scenes(
        candidates,
        start=start,
        end=end,
        max_cloud_cover_pct=config.cloud_cover_max_pct,
        required_bands=config.all_bands,
    )
    report.scenes_filtered_out = len(candidates) - len(usable)

    for scene in usable:
        scene_dir = raw_dir / scene.scene_id
        if _scene_complete(scene_dir, config.all_bands):
            report.scenes_cached.append(scene.scene_id)
            continue
        bands_to_fetch = tuple(
            band
            for band in config.all_bands
            if not (scene_dir / f"{band}.tif").is_file()
        )
        for band in bands_to_fetch:
            grid = grid20 if band in config.bands_20m else grid10
            window_read = read_bounds_window(
                scene.band_hrefs[band], band, grid.bounds, grid.crs_epsg, gate
            )
            out_path = scene_dir / f"{band}.tif"
            _write_window(out_path, window_read)
            size = out_path.stat().st_size
            report.files_written.append(out_path)
            report.total_bytes += size
            _log_acquisition(
                log_path,
                {
                    "acquired_at": dt.datetime.now(tz=dt.UTC).isoformat(),
                    "scene_id": scene.scene_id,
                    "scene_datetime": scene.datetime_utc.isoformat(),
                    "cloud_cover_pct": scene.cloud_cover_pct,
                    "mgrs_tile": scene.mgrs_tile,
                    "band": band,
                    "file": str(out_path.relative_to(root)),
                    "bytes": size,
                    "sha256": _sha256(out_path),
                    "source_collection": "sentinel-2-l2a (Microsoft Planetary Computer)",
                },
            )
            if band == "SCL":
                report.valid_fractions[scene.scene_id] = round(
                    valid_fraction(window_read.array, config.scl_exclude), 4
                )
        report.scenes_read.append(scene.scene_id)
    return report


def _load_cached_scenes(
    root: Path, *, start: dt.date, end: dt.date, config: IngestionConfig
) -> list[tuple[dt.date, Path]]:
    """Cached scene directories with an acquisition date inside the window."""
    scenes: list[tuple[dt.date, Path]] = []
    raw_dir = _raw_dir(root)
    if not raw_dir.is_dir():
        return scenes
    for scene_dir in sorted(raw_dir.iterdir()):
        if not scene_dir.is_dir() or not _scene_complete(scene_dir, config.all_bands):
            continue
        scene_date = _scene_date_from_id(scene_dir.name)
        if scene_date is None:
            continue
        if start <= scene_date <= end:
            scenes.append((scene_date, scene_dir))
    return sorted(scenes, key=lambda pair: pair[0])


def _scene_date_from_id(scene_id: str) -> dt.date | None:
    """Sentinel-2 scene IDs embed the acquisition date (``_YYYYMMDDTHHMMSS_``)."""
    for part in scene_id.split("_"):
        if len(part) == 15 and part[8] == "T" and part[:8].isdigit():
            try:
                return dt.datetime.strptime(part[:8], "%Y%m%d").date()
            except ValueError:
                continue
    return None


def _write_composite_cog(
    path: Path,
    array: np.ndarray,
    grid: CompositeGrid,
    *,
    nodata_value: float,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="COG",
        height=grid.height,
        width=grid.width,
        count=1,
        dtype=str(array.dtype),
        crs=f"EPSG:{grid.crs_epsg}",
        transform=grid.transform,
        nodata=nodata_value,
        compress="deflate",
        blocksize=512,
    ) as dst:
        dst.write(array, 1)


def run_composite(
    aoi: StudyAOI,
    *,
    start: dt.date,
    end: dt.date,
    config: IngestionConfig | None = None,
    root: Path | None = None,
    gate: DownloadGate | None = None,
) -> CompositeReport:
    """Build seasonal median composites from cached windows (fully offline).

    Reads the cached AOI windows for every scene in *start*..*end*, aligns
    them onto the fixed composite grid, masks by SCL (excluding the configured
    classes), and writes a median + valid-count COG per band and season under
    ``processed/composites/<season>/`` with a provenance sidecar.

    Args:
        aoi: Study area (defines the composite grid extent).
        start / end: Inclusive date window selecting cached scenes.
        config: Processing configuration.
        root: Data-root override (tests); default resolves via the data root.
        gate: Unused for local reads; accepted so callers can pass one gate
            through every stage (local cache reads never trigger it).

    Returns:
        :class:`CompositeReport` with written paths and coverage diagnostics.
    """
    config = config or IngestionConfig()
    root = root or data_dir()
    gate = gate or DownloadGate()  # local cache reads never trip it; kept for a uniform signature
    grid10 = CompositeGrid.from_aoi(
        aoi, resolution_m=config.grid_resolution_m, epsg=config.grid_crs_epsg
    )
    grid20 = grid10.at_resolution(2)
    cached = _load_cached_scenes(root, start=start, end=end, config=config)
    if not cached:
        msg = (
            f"No cached scenes in {start}..{end} under {_raw_dir(root)}. "
            "Run the download stage first (requires an approved retrieval)."
        )
        raise RuntimeError(msg)

    report = CompositeReport()
    scene_dates = [date for date, _ in cached]
    season_groups = group_by_season(scene_dates, config.season_months)

    for season, indices in season_groups.items():
        if not indices:
            continue
        season_dir = _processed_dir(root) / season
        stacks: dict[str, list[np.ndarray]] = {band: [] for band in config.all_bands}
        season_scene_ids: list[str] = []
        for index in indices:
            _, scene_dir = cached[index]
            scene_id = scene_dir.name
            scl = read_scl_onto_grid(str(scene_dir / "SCL.tif"), grid20, gate)
            valid20 = scl_valid_mask(scl, config.scl_exclude)
            valid10 = upscale_mask_nearest(valid20, 2)[: grid10.height, : grid10.width]
            for band in config.bands_10m:
                plane = read_band_onto_grid(str(scene_dir / f"{band}.tif"), band, grid10, gate)
                stacks[band].append(apply_mask(plane, valid10))
            for band in config.bands_20m:
                if band == "SCL":
                    continue
                plane = read_band_onto_grid(str(scene_dir / f"{band}.tif"), band, grid20, gate)
                stacks[band].append(apply_mask(plane, valid20))
            season_scene_ids.append(scene_id)

        written: list[Path] = []
        max_valid = 0
        for band, planes in stacks.items():
            if band == "SCL":
                continue  # SCL is the mask layer, not a composite band
            stack = np.stack(planes, axis=0)
            median, valid_count = median_composite(stack)
            max_valid = max(max_valid, int(valid_count.max()))
            median_out = np.where(np.isnan(median), np.float32(0.0), median).astype(np.float32)
            out_grid = grid10 if band in config.bands_10m else grid20
            out_path = season_dir / f"{band}_median.tif"
            _write_composite_cog(out_path, median_out, out_grid, nodata_value=0.0)
            count_out = (
                valid_count if band in config.bands_10m else _downsample_count(valid_count)
            ).astype(np.uint16)
            count_path = season_dir / f"{band}_validcount.tif"
            _write_composite_cog(count_path, count_out, out_grid, nodata_value=0)
            written.extend([out_path, count_path])

        provenance_path = season_dir / "provenance.json"
        provenance = {
            "season": season,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "scene_ids": season_scene_ids,
            "scene_dates": [scene_dates[i].isoformat() for i in indices],
            "bands_10m": list(config.bands_10m),
            "bands_20m": list(config.bands_20m),
            "scl_exclude": sorted(config.scl_exclude),
            "season_months": {
                name: sorted(months) for name, months in config.season_months.items()
            },
            "grid": {
                "crs": f"EPSG:{grid10.crs_epsg}",
                "resolution_m": grid10.resolution_m,
                "width": grid10.width,
                "height": grid10.height,
                "transform": list(grid10.transform)[:6],
            },
            "aoi": {"name": aoi.name, "boundary_status": aoi.boundary_status},
            "compositing": (
                "per-pixel median over valid (SCL-passing) observations; NaN convention internally"
            ),
            "note": (
                "median output stores 0.0 where no valid observation exists (nodata); "
                "see <band>_validcount.tif"
            ),
        }
        provenance_path.parent.mkdir(parents=True, exist_ok=True)
        provenance_path.write_text(
            json.dumps(provenance, indent=2, sort_keys=True), encoding="utf-8"
        )

        report.composites.extend(written)
        report.provenance.append(provenance_path)
        report.scenes_used.extend(season_scene_ids)
        report.season_scene_counts[season] = len(season_scene_ids)
        report.valid_obs_max[season] = max_valid
    return report


def _downsample_count(valid_count10: np.ndarray) -> np.ndarray:
    """Sum the 10 m valid-count plane onto the 20 m grid (2x2 blocks)."""
    height2 = int(np.ceil(valid_count10.shape[0] / 2))
    width2 = int(np.ceil(valid_count10.shape[1] / 2))
    padded = np.zeros((height2 * 2, width2 * 2), dtype=valid_count10.dtype)
    padded[: valid_count10.shape[0], : valid_count10.shape[1]] = valid_count10
    return padded.reshape(height2, 2, width2, 2).sum(axis=(1, 3))
