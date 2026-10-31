"""FinGuard — financial fraud and AML intelligence.

Status: foundation phase. The ingestion → features → temporal split → model →
graph motifs → investigation → evidence pipeline is designed in
``docs/architecture/finguard.md``; the dataset strategy is documented in
``docs/data-sources/finguard-datasets.md`` and
``data/manifests/finguard-manifest.yaml``. No pipeline code is implemented
yet.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
