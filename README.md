# AI Engineering Portfolio — FinTech + Climate/Geospatial AI

A production-oriented AI engineering portfolio built as a single monorepo with three connected
assets that share one architectural theme: **machine-verifiable evidence**.

This is not a tutorial repository or a collection of generic AI demos. Every claim produced by
these systems — an environmental finding, a suspicious-activity narrative, an evaluation answer —
is packaged with its underlying evidence, methodology, uncertainty and limitations, or the system
explicitly abstains.

## Projects

| Project | Purpose | Status |
|---|---|---|
| **[RELIA](packages/relia/)** | Shared AI reliability infrastructure: provider abstraction, tracing, evaluation, record/replay, regression analysis, evidence contracts | Foundation implemented; adapters and runners planned |
| **[TerraScope](projects/terrascope/)** | Geospatial environmental intelligence for the Pallikaranai Marsh, Chennai — satellite ingestion, land-cover analytics, change detection, evidence-grounded reporting | Architecture designed; no pipeline code yet |
| **[FinGuard](projects/finguard/)** | Financial fraud and AML intelligence — transaction features, graph motifs, evidence-grounded explanations, human-in-the-loop investigation | Architecture designed; no pipeline code yet |

**Implemented today** (verified by the test suite): Python 3.13 uv workspace, the typed evidence
contracts (`relia.contracts`), the portfolio data-path utility with external-drive validation
(`relia.config.paths`), RELIA's core interface definitions, and the `relia check-data-root` CLI.
Nothing beyond this list is implemented; project READMEs and `docs/` mark what is designed vs.
built.

## Shared architecture

```
                 ┌──────────────────────────────┐
                 │  RELIA (packages/relia)      │
                 │  providers · tracing ·       │
                 │  evaluations · replay ·      │
                 │  contracts (evidence) ·      │
                 │  regression · observability  │
                 └──────────┬───────────────────┘
                            │ typed evidence contracts,
                            │ provider + eval interfaces
              ┌─────────────┴─────────────┐
   ┌──────────┴──────────┐     ┌──────────┴──────────┐
   │ TerraScope          │     │ FinGuard            │
   │ satellite imagery → │     │ transactions →      │
   │ indices → classify →│     │ features → model →  │
   │ change → evidence → │     │ graph motifs →      │
   │ API + map           │     │ RAG → investigation │
   └─────────────────────┘     └─────────────────────┘
```

Every important generated claim is a `relia.contracts.EvidenceContract`: claim text, typed
evidence references, methodology, confidence/uncertainty, validation status, limitations and
explicit abstention. See [docs/decisions/0002-evidence-contracts.md](docs/decisions/0002-evidence-contracts.md).

## Technology stack

- **Python 3.13** managed by **uv** (workspace + lockfile); pytest, ruff, mypy
- **Pydantic v2** for schemas and evidence contracts
- Geospatial (TerraScope, planned): pystac-client, planetary-computer, rasterio, GeoPandas,
  xarray — AOI-bounded COG access only
- ML (planned): scikit-learn, LightGBM (CPU-first; spatial block CV / temporal splits)
- Backend (planned): FastAPI, PostgreSQL/PostGIS; Frontend (planned): React + TypeScript,
  MapLibre for TerraScope
- LLM orchestration (planned): provider-agnostic adapters behind RELIA; LangGraph only where
  stateful orchestration is justified

## Repository layout

```
├── AGENTS.md                  # multi-agent ownership and engineering rules
├── packages/relia/            # shared reliability infrastructure
├── projects/terrascope/       # geospatial environmental intelligence
├── projects/finguard/         # fraud/AML intelligence
├── infrastructure/            # docker, scripts, database, CI assets
├── data/                      # manifests + samples (never raw datasets)
├── docs/
│   ├── architecture/          # system + per-project design
│   ├── decisions/             # architecture decision records (ADRs)
│   ├── data-sources/          # dataset research: licensing, sizes, access
│   ├── evaluations/           # evaluation reports (as they exist)
│   └── implementation-plans/  # roadmap and setup reports
└── .github/workflows/         # CI
```

Sub-package layout inside each project follows the project's `pyproject.toml` (`src/` core
package plus pipeline directories); see ADR-0001.

## Data storage

Substantial datasets live **outside the repository** on an external drive:

- Root: `PORTFOLIO_DATA_ROOT` (deployed value: `D:\GITHUB\AI-Portfolio\Portfolio data`)
- Layout: `terrascope/{raw,interim,processed,models,exports}`, `finguard/{raw,interim,processed,models}`,
  `shared/{caches,temporary}`
- No raw datasets, rasters or model binaries are committed; manifests with licensing, sizes and
  checksums live in [`data/manifests/`](data/manifests/)

The single source of truth is the `PORTFOLIO_DATA_ROOT` environment variable (fallback: the
local, gitignored `.env`). Code fails loudly — with no silent fallback to the internal drive —
when the root is missing, unusable or not writable.

```powershell
# persistent (user-level)
setx PORTFOLIO_DATA_ROOT "D:\GITHUB\AI-Portfolio\Portfolio data"
# session-only
$env:PORTFOLIO_DATA_ROOT = "D:\GITHUB\AI-Portfolio\Portfolio data"
```

Verify at any time:

```powershell
uv run relia check-data-root
uv run python infrastructure/scripts/check_env.py
```

## Running and reproducing

```powershell
# 1. Install uv (https://docs.astral.sh/uv/), then from the repo root:
uv sync                     # creates .venv (Python 3.13) from uv.lock

# 2. Run tests, lint and the data-root check
uv run pytest
uv run ruff check .
uv run relia check-data-root
```

CI (`.github/workflows/ci.yml`) runs the same three steps on every push/PR.
Evaluation reproduction commands will be documented alongside actual evaluations in
[`docs/evaluations/`](docs/evaluations/) as they exist — no evaluation results are reported
before they are reproducible from a real run.

## Engineering standards

- Every meaningful module has tests; heavy dependencies are added only when their feature lands
  (ADR-0005)
- Deterministic checks are separated from LLM-as-judge evaluation; confidence intervals only
  where statistically justified
- No fabricated metrics, findings or user numbers — anywhere
- Spatial block cross-validation (TerraScope) and temporal splits (FinGuard) are mandatory;
  random splits are treated as leakage (ADR-0006)
- Suspicious-pattern detection is never conflated with proof of criminal activity (FinGuard);
  observed change is never conflated with causation (TerraScope)
- Unknown or unverified facts are documented as such, including in dataset manifests

## Known limitations (current phase)

- No pipeline, API or frontend code exists yet — see the
  [roadmap](docs/implementation-plans/roadmap.md)
- RELIA provider adapters, evaluation runners, tracing exporters and regression bisection are
  interface-only or planned
- Docker is not installed on the development machine; database/infrastructure work is deferred
  until the core pipelines exist
