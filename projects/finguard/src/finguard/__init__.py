"""FinGuard — financial fraud and AML intelligence.

Status: M1 data foundation implemented (synthetic-fixture validated). The
ingestion → features → temporal split → model → graph motifs → investigation
→ evidence pipeline is designed in ``docs/architecture/finguard.md``;
dataset strategy + verified acquisition facts live in
``docs/data-sources/finguard-datasets.md`` and
``data/manifests/finguard-manifest.yaml``.

Implemented (M1 steps 1-4):

* :mod:`finguard.schema` — canonical transaction schema + validation
* :mod:`finguard.ingest` — IBM AML CSV ingestion + Parquet conversion
* :mod:`finguard.splitting` — temporal splits + leakage assertions (ADR-0006)
* :mod:`finguard.synthetic` — synthetic fixtures with planted AML typologies

Planned (M1 steps 5-6 and beyond, *not* implemented yet): LightGBM fraud
baseline, transaction-graph build + motif detectors, RAG explanations via
RELIA, investigation workflow + evidence contracts.
"""

from finguard.config import DATA_SUBDIRS, data_dir, data_subdir
from finguard.ingest import (
    ConversionReport,
    convert_ibm_aml_csv_to_parquet,
    ingest_ibm_aml_csv,
    load_transaction_parquet,
)
from finguard.schema import (
    CANONICAL_COLUMNS,
    IBM_AML_COLUMN_MAP,
    SCHEMA_VERSION,
    SchemaValidationError,
    normalize_ibm_aml_columns,
    validate_transactions,
)
from finguard.splitting import (
    LeakageError,
    TemporalSplit,
    assert_no_post_event_information,
    assert_temporal_containment,
    temporal_split,
)
from finguard.synthetic import (
    TYPOLOGIES,
    PlantedMotif,
    generate_synthetic_transactions,
)

__all__ = [
    "CANONICAL_COLUMNS",
    "ConversionReport",
    "DATA_SUBDIRS",
    "IBM_AML_COLUMN_MAP",
    "LeakageError",
    "PlantedMotif",
    "SCHEMA_VERSION",
    "SchemaValidationError",
    "TemporalSplit",
    "TYPOLOGIES",
    "assert_no_post_event_information",
    "assert_temporal_containment",
    "convert_ibm_aml_csv_to_parquet",
    "data_dir",
    "data_subdir",
    "generate_synthetic_transactions",
    "ingest_ibm_aml_csv",
    "load_transaction_parquet",
    "normalize_ibm_aml_columns",
    "temporal_split",
    "validate_transactions",
]

__version__ = "0.2.0"
