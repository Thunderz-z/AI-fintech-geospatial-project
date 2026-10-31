# FinGuard

Financial fraud detection and AML intelligence on synthetic transaction data — temporal
features, imbalance-aware models, transaction-graph AML typologies, evidence-grounded RAG
explanations and a human-in-the-loop investigation workflow.

**Status: designed, not implemented.** The package skeleton, configuration integration and
tests exist; the pipeline does not. See:

- Architecture: [`../../docs/architecture/finguard.md`](../../docs/architecture/finguard.md)
- Dataset research: [`../../docs/data-sources/finguard-datasets.md`](../../docs/data-sources/finguard-datasets.md)
- Manifest: [`../../data/manifests/finguard-manifest.yaml`](../../data/manifests/finguard-manifest.yaml)
- Roadmap: [`../../docs/implementation-plans/roadmap.md`](../../docs/implementation-plans/roadmap.md)

## Layout

```
src/finguard/      core package (config: validated dataset-dir resolution via relia)
backend/           service layer (planned)
data/              dataset loaders + validation (planned; data itself lives on the external drive)
features/          temporal transaction feature engineering (planned)
models/            LightGBM fraud model, temporal splits, imbalance handling (planned)
graph/             transaction graph + AML motif detectors (planned)
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
