# ADR-0002: Typed Evidence Contracts as the Shared Verification Envelope

- Status: Accepted
- Date: 2026-10-31
- Deciders: portfolio owner, initialization run

## Context

All three projects generate claims that must be trustworthy: environmental findings
(TerraScope), suspicious-activity narratives (FinGuard), evaluation answers (RELIA). Free-text
explanations are unverifiable; a machine-checkable binding between a claim and its evidence is
the portfolio's differentiating theme.

## Decision

`relia.contracts.evidence` provides a **domain-agnostic envelope** (Pydantic v2,
`schema_version`-gated):

- `EvidenceContract` — claim text, typed evidence list, methodology, observation period,
  confidence, uncertainty, validation status, limitations, abstention, timestamps.
- `EvidenceRef` — one artefact: type, description, location (URI/path/scene-ID/table-key),
  provenance, period, checksum, metadata.
- `MethodologyInfo` — reproducibility metadata.
- `AbstentionInfo` — explicit refusal with reason and missing requirements.

Enforced invariants (validators): abstained ⇒ reason present; `VALID` ⇒ ≥ 1 evidence ref;
confidence ∈ [0, 1]. Domain data structures stay in the applications; only the envelope is
shared.

## Alternatives considered

- *Per-project evidence schemas* — maximum flexibility, no cross-project guarantees, duplicate
  concepts. Rejected: the theme depends on a shared contract.
- *Fully unified domain model* — one schema covering rasters and transactions. Rejected:
  forces artificial generalization and migration pain.

## Consequences

- Schema changes are additive and versioned; breaking changes require a new `schema_version`
  and an ADR (protected per AGENTS.md).
- Applications must be disciplined: a `VALID` claim without real evidence fails validation, and
  insufficient data must produce an abstention rather than a guess.
