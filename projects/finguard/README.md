# FinGuard

Financial fraud detection and AML intelligence on synthetic transaction data — temporal
features, imbalance-aware models, transaction-graph AML typologies, evidence-grounded RAG
explanations and a human-in-the-loop investigation workflow.

**Status: M1 data foundation implemented; model/graph/API layers designed, not implemented.**
Schema validation, CSV ingestion + Parquet conversion, temporal splitting with leakage
assertions, and the synthetic typology generator exist and are tested (40 tests, dataset-free).
LightGBM baseline, graph motif detectors, RAG and API are still planned. See:

- Architecture: [`../../docs/architecture/finguard.md`](../../docs/architecture/finguard.md)
- Dataset research: [`../../docs/data-sources/finguard-datasets.md`](../../docs/data-sources/finguard-datasets.md)
- Manifest: [`../../data/manifests/finguard-manifest.yaml`](../../data/manifests/finguard-manifest.yaml)
- Roadmap: [`../../docs/implementation-plans/roadmap.md`](../../docs/implementation-plans/roadmap.md)

## Layout

```
src/finguard/      core package: config (data-dir resolution via relia), schema (canonical
                   transaction schema + validation), ingest (IBM AML CSV -> Parquet),
                   splitting (temporal split + leakage assertions), synthetic (typology fixtures)
backend/           service layer (planned)
data/              further dataset loaders (planned; data itself lives on the external drive)
features/          temporal transaction feature engineering (planned; leakage gate ready)
models/            LightGBM fraud model, imbalance handling (planned; splits implemented)
graph/             transaction graph + AML motif detectors (planned; synthetic ground truth ready)
rag/               evidence-grounded explanation via RELIA (planned)
investigation/     alert queue, human review workflow, audit log (planned)
evidence/          evidence-contract production for alerts (planned)
evaluation/        PR-AUC, alert-threshold metrics, leakage tests (planned)
api/               FastAPI surface (planned)
frontend/          investigation UI (planned)
configs/           experiment configuration (template present)
tests/             synthetic-fixture unit + smoke tests (working)
```

## Non-negotiables

- Temporal splits only; random splits are leakage
- A detected motif is a *suspicious pattern*, never a finding of money laundering
- Consequential decisions are human-approved; no autonomous financial actions
- Metrics reported only from reproducible experiments; synthetic data labelled synthetic
- Datasets resolved via `PORTFOLIO_DATA_ROOT` (external drive), ≤ 5 GB budget
