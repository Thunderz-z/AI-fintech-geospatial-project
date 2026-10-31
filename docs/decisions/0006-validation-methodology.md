# ADR-0006: Validation Methodology — Spatial Blocks and Temporal Splits

- Status: Accepted
- Date: 2026-10-31
- Deciders: portfolio owner, initialization run

## Context

Random train/test splits are quietly wrong in both flagship domains: spatially autocorrelated
pixels inflate TerraScope land-cover accuracy, and future-leaking features inflate FinGuard
fraud metrics. Both errors fabricate performance — the one thing this portfolio must never do.

## Decision

1. **TerraScope**: spatial **block cross-validation** (spatially disjoint folds, e.g. grid
   blocks). Random pixel splits are forbidden in evaluation code. Spatial autocorrelation is
   reported alongside accuracy.
2. **FinGuard**: **temporal** train/validation/test splits aligned to transaction time. Feature
   engineering excludes post-event information; leakage tests assert this on synthetic data.
3. **LLM evaluation** (RELIA): deterministic checks separated from LLM-as-judge scores;
   bootstrap confidence intervals when metrics are sampled; results tied to dataset + prompt
   config versions; nothing reported that is not reproducible from a recorded run.
4. **Claims**: observed change ≠ attributed causation (TerraScope); suspicious pattern ≠ proven
   laundering (FinGuard). Insufficient evidence ⇒ explicit abstention via `EvidenceContract`.

## Consequences

- Metrics will look *lower* than leaky baselines — that is the point, and project READMEs will
  say so.
- Validation utilities are shared candidates (block splitters in TerraScope, temporal splitters
  in FinGuard; a future RELIA home only if genuinely shared).
- Reviewers treat a random split in evaluation code as a blocking defect.
