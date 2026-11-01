# FinGuard

Financial fraud detection and AML intelligence on synthetic transaction data — temporal
features, imbalance-aware models, transaction-graph AML typologies, evidence-grounded RAG
explanations and a human-in-the-loop investigation workflow.

FinGuard runs end-to-end on real acquired data. The data foundation:
schema/ingest/splitting/synthetic fixtures, leakage-safe features, LightGBM baseline
(HI-Small test PR-AUC 0.0159 = 15.6× base rate; 92% precision at a 0.1% alert budget),
fan-in/structuring detectors. On top of it: fan-in alert ranking (precision on detectable
planted attempts 0.667 at the 0.1% budget vs 0.000 unranked), EvidenceContract bundles for
alerts (with thin-evidence abstention), fan-out + cycle detectors (fan-out mirrors fan-in's
recall/precision profile; cycle is the inverse: precision 0.166-0.385, detectable recall
0.66 at degree_cap=100). The M3 layer: an **investigation queue with an immutable audit
log** (named reviewer required, no autonomous decision surface), scatter-gather +
rapid-movement detectors, and a FastAPI investigation surface + client. Next on the roadmap:
ranking for fan-out/cycle
alerts, RAG explanations via RELIA (awaits provider keys). Metrics JSONs
live in `<data_root>/finguard/processed/`; all data is SYNTHETIC. See:

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
  graph.py             fan-in / fan-out / cycle / structuring detectors (vectorized,
                       5M-edge scale; cycle via scipy SCC pre-filter + bounded DFS)
  patterns.py          AMLSim Patterns.txt ground-truth parser
  ranking.py           fan-in alert ranking features + LightGBM ranker (M1.5/F1)
  evidence.py          alert -> relia.contracts.EvidenceContract bundles (M1.5/F2)
scripts/               reproducible runs: ingest_raw.py, run_fraud_baseline.py,
                       evaluate_motifs.py (v2: fan-out/cycle), evaluate_alert_ranking.py,
                       export_alert_evidence.py (reports to <data_root>/finguard/processed)
configs/               experiment configuration (template present)
tests/                 synthetic-fixture unit + smoke tests (dataset-free)
```

Planned (not implemented): alert-level ranking features for fan-out/cycle (only fan-in
is ranked so far), RAG explanations via RELIA (M2), investigation queue/workflow,
FastAPI surface, investigation UI.

## Non-negotiables

- Temporal splits only; random splits are leakage
- A detected motif is a *suspicious pattern*, never a finding of money laundering
- Consequential decisions are human-approved; no autonomous financial actions
- Metrics reported only from reproducible experiments; synthetic data labelled synthetic
- Datasets resolved via `PORTFOLIO_DATA_ROOT` (external drive), ≤ 5 GB budget
