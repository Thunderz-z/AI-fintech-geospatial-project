"""TerraScope — geospatial environmental intelligence for the Pallikaranai Marsh.

Status: foundation phase. The ingestion → masking → compositing → indices →
classification → change-detection pipeline is designed in
``docs/architecture/terrascope.md``; the dataset strategy is documented in
``docs/data-sources/terrascope-datasets.md`` and
``data/manifests/terrascope-manifest.yaml``. No pipeline code is implemented
yet.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
