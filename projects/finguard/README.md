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
src/finguard/          core package (flat modules):
  config.py            data-dir resolution via relia (PORTFOLIO_DATA_ROOT, raw/interim/
                       processed/models subdirs)
  schema.py            canonical transaction schema + validation (never silently drops rows)
  ingest.py            IBM AML CSV -> Parquet conversion (chunked, validated, manifest report)
  splitting.py         temporal train/valid/test split + leakage assertions (ADR-0006)
  synthetic.py         deterministic typology fixtures (fan-in/out, structuring, cycle,
                       scatter-gather) with PlantedMotif ground truth
  features.py          leakage-safe baseline features (strictly-prior account aggregates)
  model.py             LightGBM fraud baseline + rank-based alert-budget operating points
  graph.py             fan-in / structuring detectors (vectorized, 5M-edge scale)
  patterns.py          AMLSim Patterns.txt ground-truth parser
scripts/               reproducible runs: ingest_raw.py, run_fraud_baseline.py,
                       evaluate_motifs.py (reports to <data_root>/finguard/processed)
configs/               experiment configuration (template present)
tests/                 synthetic-fixture unit + smoke tests (dataset-free)
```

Planned (not implemented): alert ranking module (M1.5/F1), evidence-contract wiring
(M1.5/F2), fan-out + cycle detectors (M1.5/F3), RAG explanations via RELIA (M2),
investigation queue/workflow, FastAPI surface, investigation UI.

## Non-negotiables

- Temporal splits only; random splits are leakage
- A detected motif is a *suspicious pattern*, never a finding of money laundering
- Consequential decisions are human-approved; no autonomous financial actions
- Metrics reported only from reproducible experiments; synthetic data labelled synthetic
- Datasets resolved via `PORTFOLIO_DATA_ROOT` (external drive), ≤ 5 GB budget
