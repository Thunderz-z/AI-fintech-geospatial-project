# FinGuard — Architecture

Status: designed. No pipeline code implemented yet (Phase 6 delivered package skeleton,
configuration, data-path integration and tests only).

## Problem

Financial fraud detection and anti-money-laundering intelligence on synthetic transaction data:
predictive fraud modelling, transaction-graph typology detection, evidence-grounded explanation
and a human-in-the-loop investigation workflow — with a strict separation between *suspicious
pattern detection* and *conclusions about criminal activity*.

## Pipeline (target)

```
Transaction ingestion → data validation → feature engineering
  → temporal split (train/validation/test)
  → fraud model (LightGBM, imbalance-aware)
  → transaction graph construction → AML motif detection
  → investigation workflow → evidence validation → explanation (RAG via RELIA)
  → human review / approval → audit log
```

## Modelling methodology

- **Temporal splits only** — random splitting is leakage when time exists (ADR-0006).
- Imbalance handled by class weights/resampling evaluated properly; metrics: precision, recall,
  F1, PR-AUC (primary), ROC-AUC where relevant, false-positive rate, and performance at
  realistic alert thresholds (alert-budget constrained operating points).
- Explainability: per-alert feature attributions referenced to transaction evidence; no
  black-box verdicts.

## Graph analytics

- Motif detectors: fan-in, fan-out, cycles, structuring (amount splitting under reporting
  thresholds), scatter-gather, rapid movement of funds, layering-like patterns.
- Each detector validated against synthetic fixtures with known planted motifs (precision of the
  detector itself is measured).
- A detected motif is a *suspicious pattern*, never a *finding of money laundering*; alerts and
  narratives reference the transaction-level evidence (`EvidenceRef(evidence_type=...)`) and the
  applicable policy/regulatory excerpts.

## RAG explanation (via RELIA)

- Versioned source documents (policy/typology references); retrieved passages recorded with the
  answer; explanations cite transaction evidence + graph motif + supporting material; the system
  abstains when retrieved evidence is insufficient.
- All LLM calls go through RELIA's provider abstraction with tracing, cassettes and evaluation.

## Human-in-the-loop workflow

Alerts arrive at an investigation queue: analyst reviews evidence bundle, model explanation and
graph context, then disposition (escalate / close / annotate). Consequential decisions are
always human-approved; **no autonomous financial actions**. Every step appends to an audit log.

## Data architecture

- Datasets under `PORTFOLIO_DATA_ROOT/finguard/{raw,interim,processed,models}`.
- Sources researched in [../data-sources/finguard-datasets.md](../data-sources/finguard-datasets.md);
  IBM AML synthetic datasets (HI-Small/LI-Small) primary, PaySim secondary, IEEE-CIS deferred.
- ≤ 5 GB initial budget; manifests + checksums required.

## API (planned)

FastAPI: alert queue, alert detail (evidence bundle), disposition endpoints (audited),
explanations endpoint; auth deferred until deployment phase, documented as a limitation.

## Testing

Synthetic transaction generators with planted typologies; motif-detector unit tests; temporal
leakage tests (assert no future information in features); model metric computation tests on
tiny fixtures; API tests. No raw dataset required for the test suite.
