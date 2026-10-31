# RELIA — Architecture

Status: foundation implemented (config, contracts, interfaces, CLI); runners, adapters and
regression bisection designed, not implemented.

## Purpose

RELIA is the reusable reliability, evaluation, tracing and evidence-contract infrastructure
shared by TerraScope and FinGuard. It deliberately does **not** become a months-long
infrastructure detour: its minimum useful foundation ships first (this phase), and its scope
grows when the applications expose real engineering requirements (ADR-0005).

## Module map

| Module | Status | Content |
|---|---|---|
| `relia.config.paths` | **implemented** | `PORTFOLIO_DATA_ROOT` resolution (.env fallback), validation, writability probe, project dirs, diagnostics |
| `relia.contracts.evidence` | **implemented** | `EvidenceContract`, `EvidenceRef`, `MethodologyInfo`, `AbstentionInfo`, versioned schema |
| `relia.providers.base` | **implemented (interfaces)** | `LLMProvider` protocol, `CompletionRequest/Response`, `Usage`, error hierarchy (`ReliaError` → `ProviderError` → timeout/rate-limit/malformed-output) |
| `relia.tracing.base` | **implemented (interface)** | `TraceRecorder` protocol (OTel-compatible surface; never raises into traced code) |
| `relia.evaluations.base` | **implemented (schema)** | `EvalCase`, `EvalDataset`, `EvalMetric` (bootstrap CI fields), `EvalResult` |
| `relia.replay.base` | **implemented (schema)** | `Cassette`, `RecordedInteraction`, `ReplayMismatchError` |
| `relia.regression` | designed | version comparison, cassette bisection, failure categorization |
| `relia.observability` | designed | structured logging config, OTel exporter wiring, cost accounting |

## Planned components (when applications need them)

1. **Provider adapters** — hosted-LLM implementations of `LLMProvider` with timeouts, retries
   with backoff, fallback chains, token/cost accounting, structured-output validation
   (`MalformedStructuredOutputError` on schema violation).
2. **Prompt management** — versioned prompt registry; every evaluation result records the
   prompt/config version (`EvalResult.config_version`).
3. **Evaluation runners** — execute `EvalDataset`s against a provider or pipeline; deterministic
   checks separated from LLM-as-judge metrics; CLI `relia eval run/compare`.
4. **Retrieval evaluation + groundedness** — retrieval metrics and evidence-validation checks
   feeding `EvidenceContract`s for generated answers.
5. **Record/replay adapters** — tape a provider adapter's interactions into `Cassette`s;
   replay in tests; mismatch raises `ReplayMismatchError` (never silent).
6. **Regression analysis + bisection** — the flagship capability: compare `EvalResult`s across
   prompt/config versions with bootstrap CIs, then bisect the prompt/config history against
   recorded cassettes to locate the change that introduced a regression; emit reproducible
   regression reports with failure categorization. LLM evaluation is not deterministic —
   comparisons are statistical and reported honestly.

## Testing strategy

Implemented tests cover: data-root resolution and failure modes, evidence-contract invariants
(abstention reasons, evidence grounding, confidence bounds, JSON round-trips), CLI behaviour,
interface schema validation and the error hierarchy. Planned: adapter timeout/retry/error tests
against fake providers, replay-mismatch tests, evaluation reproducibility tests, regression
detection tests.

## What RELIA deliberately does not do

- No agent framework in the core; LangGraph stays in the applications where stateful
  orchestration is genuinely useful.
- No dashboard UI; reproducible CLI reports and versioned artifacts first.
- No premature abstractions beyond the protocol surface above.
