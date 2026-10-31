"""STAC search against Microsoft Planetary Computer (network — approval-gated).

This module is the *only* place the pipeline talks to the Planetary Computer
STAC API, and every call passes through :class:`~terrascope.ingestion.gate.DownloadGate`
first. Tests inject a fake search function into the pipeline instead of
calling into this module, so the suite never touches the network.
"""

from __future__ import annotations

import datetime as dt

import planetary_computer
import pystac_client

from terrascope.ingestion.aoi import StudyAOI
from terrascope.ingestion.gate import DownloadGate
from terrascope.ingestion.scenes import SceneCandidate, extract_candidate

__all__ = ["MPC_STAC_API_URL", "SENTINEL2_L2A_COLLECTION", "search_sentinel2"]

MPC_STAC_API_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
SENTINEL2_L2A_COLLECTION = "sentinel-2-l2a"


def search_sentinel2(
    aoi: StudyAOI,
    *,
    start: dt.date,
    end: dt.date,
    max_cloud_cover_pct: float,
    gate: DownloadGate,
    collection: str = SENTINEL2_L2A_COLLECTION,
) -> list[SceneCandidate]:
    """Search ``sentinel-2-l2a`` on Planetary Computer and return scene candidates.

    Args:
        aoi: Study area (bbox used for the STAC ``bbox`` filter).
        start: Inclusive start date (UTC).
        end: Inclusive end date (UTC).
        max_cloud_cover_pct: Metadata cloud filter (``eo:cloud_cover`` < value).
        gate: Approval gate; raises :class:`DownloadNotApprovedError` for the
            API request unless explicitly approved.

    Returns:
        Scene candidates sorted by acquisition time. Band asset hrefs point at
        Azure blob storage COGs and are **signed** for the windowed reads.
    """
    gate.require(MPC_STAC_API_URL, f"STAC search ({collection})")
    catalog = pystac_client.Client.open(
        MPC_STAC_API_URL, modifier=planetary_computer.sign_inplace
    )
    search = catalog.search(
        collections=[collection],
        bbox=list(aoi.bbox_wgs84),
        datetime=f"{start.isoformat()}/{end.isoformat()}",
        query={"eo:cloud_cover": {"lt": max_cloud_cover_pct}},
    )
    return [extract_candidate(item) for item in search.items()]
