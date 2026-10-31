# AGENTS.md — Multi-Agent Ownership and Engineering Rules

Operating rules for coding agents working in this repository. The goal is parallel velocity
without agents overwriting each other's work or the shared foundations.

## Agent ownership

| Agent | Owns | Responsibilities |
|---|---|---|
| **Agent 1 — RELIA** | `packages/relia/` | Core architecture, provider adapters, evidence contracts, evaluation framework, tracing, replay, regression, tests, docs for the package |
| **Agent 2 — TerraScope** | `projects/terrascope/` | Geospatial architecture, dataset research, STAC ingestion, raster processing, features, ML + spatial validation, evidence generation, API, tests |
| **Agent 3 — FinGuard** | `projects/finguard/` | Transaction data research, fraud models, temporal features, graph analytics, AML typologies, RAG, investigation workflows, API, tests |
| **Agent 4 — Architecture & QA** | `docs/`, `.github/`, `infrastructure/`, root `README.md`, this file | Architecture documentation, integration testing, cross-project interface review, dependency/security/reproducibility review, final audit |

Agent 4 reviews but must not casually rewrite files owned by Agents 1–3; propose changes to the
owning agent or in review comments instead.

## Protected shared files — never modify in parallel

These files are modified only by a single agent at a time, and changes to them are announced in
the PR description:

- Root `pyproject.toml` and `uv.lock` (dependency changes: add the dependency to the *owning*
  package's `pyproject.toml` first; a human or Agent 4 arbitrates lock conflicts)
- `packages/relia/src/relia/contracts/` (shared evidence schemas — versioned, additive changes
  only; schema bump requires ADR)
- `packages/relia/src/relia/providers/base.py`, `tracing/base.py`, `evaluations/base.py`,
  `replay/base.py` (shared interfaces)
- `packages/relia/src/relia/config/paths.py` (data-path utility)
- `.github/workflows/`, `infrastructure/`, `docker-compose*.yml`
- `.env.example`, `.gitignore`, `AGENTS.md`, root `README.md`

Define shared interfaces **before** parallel integration work starts. If an owned interface no
longer fits, file the mismatch with Agent 4 rather than working around it locally.

## Branch and commit strategy

- `main` is the integration branch; keep it green (tests + `ruff check .` must pass)
- Parallel agent work happens on feature branches:
  `feature/relia-*`, `feature/terrascope-*`, `feature/finguard-*`, `feature/integration-*`
- Shared-directory work (Agent 4) branches from `main` immediately after the owning agents'
  branches do, to minimize drift
- Prefer small, logical commits with descriptive messages; never commit datasets, `.env`,
  or generated artifacts (see `.gitignore`)

## Non-negotiable engineering rules

1. **Environment**: Python 3.13 via uv only. Always run code through `uv run` inside this repo;
   never touch the system Python 3.11 installation or other projects' venvs.
2. **Data paths**: all dataset access goes through `relia.config.paths`
   (`PORTFOLIO_DATA_ROOT`); no hardcoded dataset paths, no silent fallback to the internal
   drive. Datasets live only under the data root — never in the repo.
3. **Storage budgets**: TerraScope ≤ 10 GB, FinGuard ≤ 5 GB initially; no download > 500 MB
   without explicit human approval; check free space before downloading; manifests + checksums
   required (`data/manifests/`).
4. **No fake implementations**: a stub is clearly labelled as such; never claim a feature is
   implemented when only a placeholder exists.
5. **No fabricated results**: every reported metric must be reproducible from an actual
   experiment. Deterministic checks are separated from LLM-as-judge evaluation. Never report
   invented performance, business impact or environmental findings.
6. **Validation discipline**: TerraScope uses spatial block cross-validation; FinGuard uses
   temporal train/validation/test splits. Random splits are leakage — do not merge code that
   relies on them (ADR-0006).
7. **Domain honesty**: a suspicious pattern ≠ proven laundering; observed land-cover change ≠
   attributed causation. Abstain when evidence is insufficient — `EvidenceContract.abstention`
   exists for exactly this.
8. **Security**: no secrets in the repo (`.env` only, gitignored); no committed API keys;
   inputs validated; safe file handling.
9. **Testing**: every meaningful module gets tests; tests must run without raw datasets
   (synthetic fixtures); `uv run pytest` and `uv run ruff check .` must be green before merge.
10. **Documentation honesty**: docs distinguish *implemented*, *designed*, *planned* and
    *blocked*; unverified facts (dataset sizes, licenses, tile IDs) are marked "to verify".

## Agent reporting requirements

Each agent reports on completion of a task:

- Files created or changed
- Dependencies introduced (and why)
- Tests executed and results
- Assumptions made
- Unresolved questions
- Storage implications (if any data was written)
- Integration requirements (shared interfaces touched or needed)

## Codebase Memory (codebase-memory-mcp)

The repository is indexed by the Codebase Memory MCP server (git-watcher strategy, ~5 s poll).
Rules:

- Structural questions ("who calls X", "where is Y defined") go to the MCP tools, not manual
  grep, when the index covers them
- After substantial structural changes, check `index_status` / `check_index_coverage`; re-index
  if coverage lags
- Never commit `.codebase-memory/` local artifacts (already gitignored)

Setup details: [docs/architecture/codebase-memory.md](docs/architecture/codebase-memory.md).

## Model/token discipline

Prefer the strongest model for architecture, ML methodology, leakage audits, debugging hard
data pipelines, security review and cross-project interface decisions; prefer faster models for
scaffolding, boilerplate, routine tests and documentation. Useful engineering output and
verified correctness are the metric — not token consumption.
