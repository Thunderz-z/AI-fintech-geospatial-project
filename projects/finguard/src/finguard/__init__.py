"""FinGuard — financial fraud and AML intelligence.

Status: M1 steps 1-6 implemented (data foundation, fraud baseline, motif
detectors) on the real acquired IBM AML HI-Small/LI-Small datasets; M1.5
adds fan-in alert ranking, evidence-contract wiring and fan-out/cycle
detectors. Dataset facts live in ``docs/data-sources/finguard-datasets.md``
and ``data/manifests/finguard-manifest.yaml``.

Implemented:

* :mod:`finguard.schema` — canonical transaction schema + validation
* :mod:`finguard.ingest` — IBM AML CSV ingestion + Parquet conversion
* :mod:`finguard.splitting` — temporal splits + leakage assertions (ADR-0006)
* :mod:`finguard.synthetic` — synthetic fixtures with planted AML typologies
* :mod:`finguard.features` — leakage-safe baseline feature engineering
* :mod:`finguard.model` — LightGBM fraud baseline + alert-budget metrics
* :mod:`finguard.graph` — fan-in/structuring (+ M1.5 fan-out/cycle)
  detectors (suspicious patterns, never laundering findings)
* :mod:`finguard.patterns` — AMLSim Patterns.txt ground-truth parser
* :mod:`finguard.ranking` — fan-in alert ranking features + ranker (M1.5/F1)
* :mod:`finguard.evidence` — alert → EvidenceContract bundles (M1.5/F2)

Planned (M2+ and beyond, *not* implemented yet): RAG explanations via RELIA,
investigation workflow, FastAPI surface.
"""

from finguard.config import DATA_SUBDIRS, data_dir, data_subdir
from finguard.features import FEATURE_COLUMNS, build_baseline_features
from finguard.graph import (
    MotifAlert,
    build_transaction_graph,
    detect_fan_in,
    detect_structuring,
)
from finguard.ingest import (
    ConversionReport,
    convert_ibm_aml_csv_to_parquet,
    ingest_ibm_aml_csv,
    load_transaction_parquet,
)
from finguard.model import ALERT_BUDGETS, FraudBaselineReport, train_fraud_baseline
from finguard.patterns import parse_patterns_file
from finguard.ranking import (
    RANKING_FEATURE_COLUMNS,
    fan_in_alert_features,
    label_alerts,
    score_alerts,
    train_alert_ranker,
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
    "ALERT_BUDGETS",
    "CANONICAL_COLUMNS",
    "ConversionReport",
    "DATA_SUBDIRS",
    "FEATURE_COLUMNS",
    "FraudBaselineReport",
    "IBM_AML_COLUMN_MAP",
    "LeakageError",
    "MotifAlert",
    "PlantedMotif",
    "RANKING_FEATURE_COLUMNS",
    "SCHEMA_VERSION",
    "SchemaValidationError",
    "TemporalSplit",
    "TYPOLOGIES",
    "assert_no_post_event_information",
    "assert_temporal_containment",
    "build_baseline_features",
    "build_transaction_graph",
    "convert_ibm_aml_csv_to_parquet",
    "data_dir",
    "data_subdir",
    "detect_fan_in",
    "detect_structuring",
    "fan_in_alert_features",
    "generate_synthetic_transactions",
    "ingest_ibm_aml_csv",
    "label_alerts",
    "load_transaction_parquet",
    "normalize_ibm_aml_columns",
    "parse_patterns_file",
    "score_alerts",
    "temporal_split",
    "train_alert_ranker",
    "train_fraud_baseline",
    "validate_transactions",
]

__version__ = "0.4.0"
