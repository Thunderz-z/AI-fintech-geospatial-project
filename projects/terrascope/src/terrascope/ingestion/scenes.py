"""Sentinel-2 scene candidates: extraction from STAC items and offline filtering.

The search itself (network) lives in :mod:`terrascope.ingestion.stac_search`
behind the download gate; everything here is pure and covered by offline tests
constructing real ``pystac`` items in memory (no network).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pystac

__all__ = [
    "BANDS_10M",
    "BANDS_20M",
    "ALL_BANDS",
    "SceneCandidate",
    "extract_candidate",
    "filter_scenes",
]

#: 10 m bands (Sentinel-2 L2A on Microsoft Planetary Computer).
BANDS_10M: tuple[str, ...] = ("B02", "B03", "B04", "B08")

#: 20 m bands including the Scene Classification Layer.
BANDS_20M: tuple[str, ...] = ("B11", "B12", "SCL")

#: All bands the ingestion pipeline requires per scene.
ALL_BANDS: tuple[str, ...] = BANDS_10M + BANDS_20M


@dataclass(frozen=True)
class SceneCandidate:
    """One usable Sentinel-2 L2A scene: identity, quality and asset hrefs."""

    scene_id: str
    datetime_utc: dt.datetime
    cloud_cover_pct: float | None
    mgrs_tile: str | None
    epsg: int | None
    band_hrefs: dict[str, str] = field(default_factory=dict)

    def missing_bands(self, required: tuple[str, ...] = ALL_BANDS) -> tuple[str, ...]:
        """Bands from *required* that this scene does not provide."""
        return tuple(band for band in required if band not in self.band_hrefs)


def extract_candidate(item: pystac.Item) -> SceneCandidate:
    """Build a :class:`SceneCandidate` from a ``pystac.Item`` (offline, no I/O).

    Band assets are matched by asset key (MPC ``sentinel-2-l2a`` uses the band
    name, e.g. ``B04``/``SCL``). Unknown assets are ignored.
    """
    properties = item.properties
    cloud_cover = properties.get("eo:cloud_cover")
    scene_datetime = item.datetime
    if scene_datetime is None:
        msg = f"STAC item {item.id!r} has no datetime"
        raise ValueError(msg)
    if scene_datetime.tzinfo is None:
        scene_datetime = scene_datetime.replace(tzinfo=dt.UTC)
    band_hrefs = {
        key: asset.href
        for key, asset in item.assets.items()
        if key in ALL_BANDS and asset.href
    }
    return SceneCandidate(
        scene_id=item.id,
        datetime_utc=scene_datetime,
        cloud_cover_pct=float(cloud_cover) if cloud_cover is not None else None,
        mgrs_tile=properties.get("grid:code"),
        epsg=properties.get("proj:epsg"),
        band_hrefs=band_hrefs,
    )


def filter_scenes(
    candidates: list[SceneCandidate],
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    max_cloud_cover_pct: float | None = None,
    required_bands: tuple[str, ...] = ALL_BANDS,
) -> list[SceneCandidate]:
    """Filter candidates by date window, cloud cover and band completeness.

    All criteria are inclusive; ``None`` disables a criterion. Scenes missing
    any required band are dropped (the pipeline refuses partial scenes —
    compositing semantics would silently change).
    """
    filtered: list[SceneCandidate] = []
    for candidate in candidates:
        if start is not None and candidate.datetime_utc.date() < start:
            continue
        if end is not None and candidate.datetime_utc.date() > end:
            continue
        if max_cloud_cover_pct is not None:
            if candidate.cloud_cover_pct is None:
                continue  # unknown quality is treated as unusable, not pass-through
            if candidate.cloud_cover_pct > max_cloud_cover_pct:
                continue
        if candidate.missing_bands(required_bands):
            continue
        filtered.append(candidate)
    return sorted(filtered, key=lambda scene: scene.datetime_utc)
