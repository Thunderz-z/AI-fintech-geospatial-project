# FinGuard

Financial fraud detection and AML intelligence on synthetic transaction data — temporal
features, imbalance-aware models, transaction-graph AML typologies, evidence-grounded RAG
explanations and a human-in-the-loop investigation workflow.

**Status: M1 implemented on real acquired data (steps 1-6 of the roadmap).**
Schema/ingest/splitting/synthetic fixtures (tested), leakage-safe features, LightGBM
baseline (HI-Small test PR-AUC 0.0159 = 15.6x base rate; 92% precision at a 0.1% alert
budget), fan-in/structuring detectors (fan-in: 100% recall on detectable planted attempts,
precision is the open problem). RAG, investigation workflow and API still planned. Metrics
JSONs live in `<data_root>/finguard/processed/`; all data is SYNTHETIC. See:

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
