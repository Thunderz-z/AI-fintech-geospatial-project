"""TerraScope ingestion: STAC search, AOI-bounded windowed reads, masking, compositing.

Status: implemented for M0 steps 3 (module + offline tests). The first real
network retrieval is gated behind :class:`~terrascope.ingestion.gate.DownloadGate`
approval — see ``python -m terrascope.ingestion --help``.

Public API:

* :mod:`~terrascope.ingestion.aoi` — study-area geometry (approximate bbox /
  authoritative Ramsar boundary once acquired)
* :mod:`~terrascope.ingestion.gate` — the download-approval gate
* :mod:`~terrascope.ingestion.stac_search` — Planetary Computer STAC search
* :mod:`~terrascope.ingestion.scenes` — scene candidates + filtering
* :mod:`~terrascope.ingestion.cog_reader` — windowed COG reads + grid alignment
* :mod:`~terrascope.ingestion.masking` — SCL masking
* :mod:`~terrascope.ingestion.composite` — seasonal grouping + median compositing
* :mod:`~terrascope.ingestion.pipeline` — orchestration (download / composite)
"""

from __future__ import annotations

from terrascope.ingestion.aoi import (
    APPROXIMATE_PALLIKARANAI_BBOX_4326,
    STUDY_CRS_EPSG,
    StudyAOI,
    approximate_pallikaranai_aoi,
    load_boundary_geojson,
)
from terrascope.ingestion.composite import DEFAULT_SEASON_MONTHS, group_by_season, median_composite
from terrascope.ingestion.gate import (
    UNAPPROVED,
    DownloadGate,
    DownloadNotApprovedError,
    is_remote_uri,
)
from terrascope.ingestion.masking import (
    SCL_EXCLUDE_DEFAULT,
    apply_mask,
    scl_valid_mask,
    upscale_mask_nearest,
    valid_fraction,
)
from terrascope.ingestion.pipeline import (
    DEFAULT_SEARCH_FN,
    CompositeGrid,
    IngestionConfig,
    run_composite,
    run_download,
)
from terrascope.ingestion.scenes import (
    ALL_BANDS,
    BANDS_10M,
    BANDS_20M,
    SceneCandidate,
    extract_candidate,
    filter_scenes,
)

__all__ = [
    "ALL_BANDS",
    "APPROXIMATE_PALLIKARANAI_BBOX_4326",
    "BANDS_10M",
    "BANDS_20M",
    "DEFAULT_SEARCH_FN",
    "DEFAULT_SEASON_MONTHS",
    "SCL_EXCLUDE_DEFAULT",
    "STUDY_CRS_EPSG",
    "CompositeGrid",
    "DownloadGate",
    "DownloadNotApprovedError",
    "IngestionConfig",
    "SceneCandidate",
    "StudyAOI",
    "UNAPPROVED",
    "apply_mask",
    "approximate_pallikaranai_aoi",
    "extract_candidate",
    "filter_scenes",
    "group_by_season",
    "is_remote_uri",
    "load_boundary_geojson",
    "median_composite",
    "run_composite",
    "run_download",
    "scl_valid_mask",
    "upscale_mask_nearest",
    "valid_fraction",
]
