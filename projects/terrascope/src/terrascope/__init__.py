"""TerraScope — geospatial environmental intelligence for the Pallikaranai Marsh.

Status: M0 ingestion implemented (``terrascope.ingestion``: STAC search,
AOI-bounded windowed COG reads, SCL masking, seasonal median compositing —
downloads gated behind explicit approval; no satellite data retrieved yet).
Spectral indices, classification and change detection remain planned; the
pipeline design lives in ``docs/architecture/terrascope.md`` and the dataset
strategy in ``docs/data-sources/terrascope-datasets.md`` +
``data/manifests/terrascope-manifest.yaml``.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
