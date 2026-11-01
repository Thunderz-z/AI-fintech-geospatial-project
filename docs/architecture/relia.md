# RELIA — Architecture

Status: M2 service layer implemented (provider adapter, record/replay cassettes, prompt
registry, deterministic evaluation runner, `relia eval` CLI) on top of the M0 foundation
(config, contracts, interfaces). LLM-as-judge scoring, retrieval evaluation and regression
bisection remain designed, not implemented.

## Purpose

RELIA is the reusable reliability, evaluation, tracing and evidence-contract infrastructure
shared by TerraScope and FinGuard. It deliberately does **not** become a months-long
infrastructure detour: its minimum useful foundation ships first (this phase), and its scope
grows when the applications expose real engineering requirements (ADR-0005).

## Module map

| Module | Status | Content |
|---|---|---|
| `relia.config.paths` | **implemented** | `PORTFOLIO_DATA_ROOT` resolution (.env fallback), validation, writability probe, project dirs, diagnostics; public `read_dotenv()` |
| `relia.contracts.evidence` | **implemented** | `EvidenceContract`, `EvidenceRef`, `MethodologyInfo`, `AbstentionInfo`, versioned schema |
| `relia.providers.base` | **implemented (interfaces)** | `LLMProvider` protocol, `CompletionRequest/Response` (with `cost_usd`), `Usage`, error hierarchy |
| `relia.providers.openai_compat` | **implemented** | OpenAI chat-completions wire protocol (OpenAI, Grok/xAI, Azure, Groq, DeepSeek, vLLM, ...) with per-attempt timeouts, deterministic exponential backoff (retry on 408/429/5xx/transport, never on 4xx/malformed output), client-side `jsonschema` structured-output validation |
| `relia.providers.anthropic` | **implemented** | Anthropic Messages API (Claude): `x-api-key` + version headers, `system` extraction, mandatory `max_tokens` resolution (request → config → 1024), 529-overloaded retryable, instruction-based structured outputs validated client-side (the API has no `response_format`; a violating answer fails loudly) |
| `relia.providers.presets` | **implemented** | `create_provider()` over named presets — `claude` (RELIA_ANTHROPIC_), `grok` (RELIA_GROK_, xAI speaks the OpenAI wire format), `custom` (RELIA_CUSTOM_, `BASE_URL` required), `openai-compatible` (RELIA_LLM_) — per-vendor env prefixes so vendors coexist in one `.env` |
| `relia.providers.config` / `_http_base` | **implemented** | Shared `ProviderConfig` (per-prefix `from_env`, `SecretStr` key, price sheet), `UsageLedger` cost accounting and the retry/timeout/ledger HTTP base both wire protocols build on |
| `relia.providers.fake` | **implemented** | `ScriptedProvider` test double (network-free; explicitly a fake, not a stub) |
| `relia.replay.cassette` | **implemented** | `RecordingProvider` / `ReplayProvider` behind the provider interface; strict request equality, `ReplayMismatchError` on divergence/exhaustion/corruption, `verify_complete()`, JSON save/load |
| `relia.prompts.registry` | **implemented** | `PromptTemplate` (`$variable`, JSON-brace-safe), `PromptRegistry` with numeric-aware latest-version lookup, strict rendering, TOML loading (stdlib `tomllib`) |
| `relia.evaluations.base` | **implemented (schema)** | `EvalCase`, `EvalDataset`, `EvalMetric` (bootstrap CI fields), `EvalResult` + `CaseResult` (additive) |
| `relia.evaluations.checks` | **implemented** | Deterministic checks: `ExactMatch`, `ContainsCheck`, `RegexCheck`, `ValidJsonCheck` — no model judging |
| `relia.evaluations.runner` | **implemented** | `EvalRunner`: answer-fn injection, per-case error recording, `case_success_rate` metric, exact aggregate metrics |
| `relia.evaluations.datasets` | **implemented** | `load_eval_dataset()` from TOML |
| `relia.cli` | **implemented** | `check-data-root`; `eval run` (scripted / cassette / OpenAI-compatible sources, `--check`, `--fail-under`, `EvalResult` JSON to `docs/evaluations/`); `eval compare` (point deltas, `--fail-on-regression`) |
| `relia.tracing.base` | **implemented (interface)** | `TraceRecorder` protocol; OTel exporter wiring not implemented |
| `relia.tracing.memory` | **implemented** | `InMemoryTraceRecorder`: spans, events, errors, JSON export; never raises into traced code |
| `relia.regression` | **implemented** | `bisect.py`: paired-delta bootstrap CIs over per-case outcomes, history bisection locating the first regression (CI-gated claims) |
| `relia.observability` | **implemented (core)** | `cost.py`: `CostLedger` (token/cost accumulation; unknown-cost calls honestly poison the total to None). OTel forwarding + logging presets planned |

## Remaining planned components (when applications need them)

1. **Fallback chains + real-key soak test** — both adapters run their full test coverage
   against mock transports; the first live runs wait for the owner's API keys in the
   worktree `.env` (`RELIA_ANTHROPIC_*` / `RELIA_GROK_*` / `RELIA_CUSTOM_*` / `RELIA_LLM_*`).
2. **LLM-as-judge runner** — separated from the deterministic runner by design; never mixed
   into deterministic metrics.
3. **Retrieval evaluation + groundedness** — retrieval metrics and evidence-validation checks
   feeding `EvidenceContract`s.
4. **Regression analysis + bisection** — the flagship capability: compare `EvalResult`s
   across prompt/config versions with bootstrap CIs, then bisect prompt/config history
   against recorded cassettes to locate the change that introduced a regression. The
   deterministic runner already records per-case `CaseResult`s and cassettes are strict, so
   the inputs exist; the analysis does not yet.
5. **Tracing exporter** — OpenTelemetry wiring behind `TraceRecorder`.

## Testing strategy

All tests run network-free and key-free: both adapters are exercised through
`httpx.MockTransport` with an injected sleep recorder (retry schedules asserted exactly), the
replay layer through recorded cassettes, and the CLI through scripted/cassette answer
sources. Covered: data-root resolution and failure modes, evidence-contract invariants,
interface schema validation and error hierarchy, both adapters' wire
format/auth/headers/timeouts/retries/backoff caps/error mapping/usage integrity/cost
accounting, structured-output validation (invalid JSON, schema violation, invalid schema,
non-object), Anthropic-specific behaviour (system extraction, `max_tokens` resolution,
529 retry, tool-role rejection), preset catalogue/env isolation/base-URL overrides, scripted
provider behaviour, cassette record/save/load/replay/mismatch/exhaustion, prompt registry
(version ordering, duplicate detection, strict render, TOML loading), deterministic checks,
runner aggregation and per-case error semantics, dataset loading, and the full
`eval run`/`eval compare` CLI surface including `--fail-under` gating. Planned:
live-endpoint conformance once keys exist, LLM-as-judge tests, regression bisection tests.

## What RELIA deliberately does not do

- No agent framework in the core; LangGraph stays in the applications where stateful
  orchestration is genuinely useful.
- No dashboard UI; reproducible CLI reports and versioned artifacts first.
- No SDK lock-in: the adapter speaks the OpenAI-compatible wire format over `httpx`
  directly (ADR-0005 staged dependencies); an SDK can still be added behind the protocol
  later if a specific endpoint demands it.
