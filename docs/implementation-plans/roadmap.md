# Implementation Roadmap

Status: prioritized plan produced at initialization (2026-10-31). Phases 1–6 of the master
initialization plan are complete; everything below is planned. Owners: Agent 1 = RELIA,
Agent 2 = TerraScope, Agent 3 = FinGuard, Agent 4 = Architecture & QA (ownership in
[`AGENTS.md`](../../AGENTS.md)).

## Completed (initialization, verified)

- Python 3.13 uv workspace, lockfile, lint + test toolchain (38 tests green, ruff clean)
- Monorepo skeleton for all three packages; evidence contracts; data-path utility + CLI
- External dataset root configured (.env + persistent setx) and validated
- Codebase Memory MCP watcher active; ADRs 0001–0006; dataset research + manifests
- README / AGENTS / architecture docs; CI workflow

## M0 — TerraScope first data pipeline (Agent 2, lead focus)

1. Verify authoritative Pallikaranai boundary sources (TN Wetlands Authority, Ramsar RSIS);
   else finalize documented approximate boundary (blocks all spatial claims)
2. Add geospatial dependencies (ADR-0005 gate: 3.13 Windows wheels, disk check)
3. STAC search + AOI windowed retrieval for Sentinel-2 L2A (manifest: `sentinel-2-l2a-aoi`)
4. SCL masking + seasonal median compositing on a 2–3 date sample; visual QA
5. NDVI/NDWI/MNDWI/NDBI on composites; water-extent time series v0 with cloud-fraction
   gating and abstention
6. Evidence contracts for every numeric claim; spatial block CV scaffolding

## M1 — FinGuard baseline (Agent 3, lead focus, parallel with M0)

1. Verify IBM AML Kaggle listing/terms; acquire LI-Small (manifest gate, checksum)
2. Add data-science dependencies (pandas/pyarrow/lightgbm/networkx per ADR-0005)
3. Ingestion + schema validation; Parquet conversion; synthetic typology fixtures
4. Temporal split utility + leakage tests (assert no post-event features)
5. LightGBM fraud baseline: PR-AUC/precision/recall at alert-budget operating points
6. Transaction graph build + 2 motif detectors (fan-in, structuring) validated on planted
   synthetic fixtures

## M2 — RELIA service layer (Agent 1, interleaved when M0/M1 need it)

1. First provider adapter implementing `LLMProvider` (timeout/retry/backoff, usage + cost,
   structured-output validation)
2. Cassette record/replay adapter (network-free tests)
3. Prompt registry (versioned) + evaluation runner (deterministic checks first)
4. When TerraScope/FinGuard generate their first LLM explanations: groundedness evaluation +
   retrieval metrics; regression comparison CLI (`relia eval compare`)

## M3 — APIs and surfaces (Agents 2+3, Agent 4 reviews)

1. TerraScope FastAPI (analysis outputs, evidence links) + MapLibre frontend v0
2. FinGuard FastAPI (alert queue, evidence bundles, audited dispositions) + investigation UI v0
3. PostgreSQL/PostGIS via Docker Compose when the first persistent store is required
   (Docker Desktop installation requires owner approval — currently not installed)

## M4 — Evaluation depth (Agent 1 + Agent 4)

1. Evaluation datasets versioned in-repo; reports in `docs/evaluations/`
2. Bootstrap CIs on sampled metrics; failure categorization
3. Regression bisection across prompt/config history (recorded cassettes)

## M5 — Hardening and audit (Agent 4)

1. Cross-project interface review; dependency audit; security review (secrets, input handling)
2. Reproducibility audit (fresh clone → uv sync → pytest → documented commands)
3. Final technical audit + README status refresh (implemented vs designed vs planned)

## Storage checkpoints

Before each acquisition: free-space check, manifest update (size + checksum + date), budget
check (TerraScope ≤ 10 GB, FinGuard ≤ 5 GB, per-file 500 MB gate).

## Explicitly deferred

Docker/PostGIS provisioning (Docker absent on this machine — owner decision), IEEE-CIS
acquisition, Dynamic World/JRC GSW subsets, frontend polish beyond v0, deployment
infrastructure (documented first, then implemented).
