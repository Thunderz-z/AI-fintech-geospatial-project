# AI Engineering Portfolio — FinTech + Climate/Geospatial AI

A production-oriented AI engineering portfolio built as a single monorepo with three connected
assets sharing one architectural theme: **machine-verifiable evidence**. Every claim produced by
these systems — an environmental finding, a suspicious-activity alert, an evaluation answer —
carries its evidence, methodology, uncertainty and limitations, or the system explicitly abstains.

## Projects and current status

| Project | What it is | Status |
|---|---|---|
| **[RELIA](packages/relia/)** | Shared AI reliability infrastructure: evidence contracts, provider adapters, cassettes, prompt registry, evaluation runner, regression bisection, tracing, cost ledger | **Implemented** (153+ tests); real-provider activation pending an API key |
| **[TerraScope](projects/terrascope/)** | Geospatial environmental intelligence for the Pallikaranai Marsh (authoritative Ramsar IN2481 boundary): Sentinel-2 ingestion → SCL masking → seasonal composites → spectral indices → calibrated water-extent series → block-CV land-cover classification → epoch change detection → evidence contracts → API + MapLibre map | **End-to-end on real data** (219 scenes, 2019–2026; every number traceable to an artefact) |
| **[FinGuard](projects/finguard/)** | Fraud/AML intelligence on synthetic IBM AML data: temporal splits → LightGBM baseline → 4 graph-motif detectors → alert ranking → evidence bundles → human-in-the-loop investigation queue with an immutable audit log → API + investigation client | **End-to-end on real acquired data**; every metric labelled synthetic |

**335 tests green** across the workspace; ruff and mypy clean. No fabricated metrics anywhere —
each number in the READMEs traces to a reproducible command and a JSON artefact on the data root.

## Headline results (all reproducible; artefacts on the data root)

- **TerraScope water seasonality**: NE-monsoon water +9.1 pp over dry season, bootstrap 95% CI
  [4.0, 14.9] (10,000 resamples over 137 usable dates; 58 of 195 abstained on the coverage gate).
  The three highest-water dates fall in Nov–Dec 2021 — the December 2021 Chennai floods.
- **TerraScope epoch change**: winter water 25.05% → 24.74% between 2019-20 and 2023-24
  (gained 0.94% / lost 1.24% of 392,861 compared pixels), with per-pixel uncertainty maps.
- **TerraScope classification**: 58.97% ± 3.22% spatial-block-CV agreement with WorldCover-derived
  labels — explicitly *not* real-world map accuracy.
- **FinGuard fraud baseline**: HI-Small test PR-AUC 0.0159 (15.6× base rate), 92% precision at a
  0.1% alert budget (rank-based operating points; synthetic data).
- **FinGuard alert ranking**: fan-in precision on detectable planted attempts 0.0 → 0.667 at the
  0.1% budget (test-period, ranker trained on train-period alerts only).

## Shared architecture

```
                 ┌──────────────────────────────┐
                 │  RELIA (packages/relia)      │
                 │  contracts · providers ·     │
                 │  replay · prompts ·          │
                 │  evaluations · regression ·  │
                 │  tracing · observability     │
                 └──────────┬───────────────────┘
                            │ evidence contracts,
                            │ provider + eval interfaces
              ┌─────────────┴─────────────┐
   ┌──────────┴──────────┐     ┌──────────┴──────────┐
   │ TerraScope          │     │ FinGuard            │
   │ pipeline → evidence │     │ pipeline → evidence │
   │ → FastAPI + map     │     │ → queue → FastAPI   │
   └─────────────────────┘     └─────────────────────┘
```

`relia.contracts.evidence.EvidenceContract` is the shared verification envelope: claim text,
typed evidence references, methodology, confidence/uncertainty, validation status, limitations
and explicit abstention — enforced invariants (abstained ⇒ reason; `VALID` ⇒ ≥ 1 evidence ref).
Design: [docs/decisions/0002-evidence-contracts.md](docs/decisions/0002-evidence-contracts.md).

## Technology stack

- **Python 3.13** via **uv** (workspace + lockfile); pytest, ruff, mypy
- **Pydantic v2** schemas; **scikit-learn / LightGBM** (CPU-first; spatial block CV / temporal
  splits only — ADR-0006); **rasterio / GeoPandas / pystac-client** (AOI-bounded COG access)
- **FastAPI** services with static, build-less frontends (MapLibre via CDN — ADR-0007)
- **Docker**: CI-built images only (no local Docker — ADR-0007); datasets mounted, never baked in

## Repository layout

```
├── AGENTS.md                  # multi-agent ownership and engineering rules
├── packages/relia/            # shared reliability infrastructure
├── projects/terrascope/       # geospatial environmental intelligence
├── projects/finguard/         # fraud/AML intelligence
├── infrastructure/docker/     # service containers (CI-built) + compose
├── infrastructure/scripts/    # environment audit
├── data/manifests/            # dataset manifests (licensing, sizes, checksums)
├── docs/
│   ├── architecture/          # system + per-project design, deployment
│   ├── decisions/             # ADRs 0001–0007
│   ├── data-sources/          # dataset research (licensing, access, sizes)
│   ├── evaluations/           # evaluation reports (as they exist)
│   └── implementation-plans/  # roadmap, round plans, setup reports
└── .github/workflows/ci.yml   # lint + tests + docker builds
```

## Data storage

Substantial datasets live **outside the repository** on an external drive, resolved exclusively
through `PORTFOLIO_DATA_ROOT` (deployed value: `D:\GITHUB\AI-Portfolio\Portfolio data`; fallback:
the local, gitignored `.env`). Code fails loudly — no silent fallback to the internal drive.

```powershell
setx PORTFOLIO_DATA_ROOT "D:\GITHUB\AI-Portfolio\Portfolio data"   # persistent
uv run relia check-data-root                                       # verify
```

Budgets and the per-download approval gate are enforced per [AGENTS.md](AGENTS.md); manifests
with licensing, sizes and checksums live in [`data/manifests/`](data/manifests/).

## Running and reproducing

```powershell
uv sync                                        # Python 3.13 venv from uv.lock
uv run pytest && uv run ruff check .           # 335 tests, lint
uv run relia check-data-root                   # dataset root health

# TerraScope service (read-only analysis + map): http://127.0.0.1:8801
uv run uvicorn terrascope.api.app:app --port 8801
# FinGuard investigation service (queue + audit): http://127.0.0.1:8802
uv run uvicorn finguard.api.app:app --port 8802

# Reproduce TerraScope's numbers (offline from the cached record):
uv run --project projects/terrascope python -m terrascope.ingestion water --start 2019-04-01 --end 2026-10-31
uv run --project projects/terrascope python projects/terrascope/scripts/seasonality_analysis.py
uv run --project projects/terrascope python projects/terrascope/scripts/run_change_detection.py --epoch-a winter_2019-20 --epoch-b winter

# Reproduce FinGuard's numbers (requires the acquired datasets; see manifests):
uv run --project projects/finguard python projects/finguard/scripts/run_fraud_baseline.py
uv run --project projects/finguard python projects/finguard/scripts/evaluate_alert_ranking.py
```

RELIA evaluations: `uv run relia eval run --help` (deterministic checks; LLM answer sources need
`RELIA_*` keys in `.env` — see [docs/architecture/relia.md](docs/architecture/relia.md)).

## Engineering standards

- Validation discipline: spatial block CV (TerraScope), temporal splits (FinGuard); random splits
  are leakage (ADR-0006)
- Deterministic checks separated from LLM-as-judge; regression claims require bootstrap CIs to
  exclude zero (relia.regression)
- Suspicious pattern ≠ proven laundering; observed change ≠ causation; abstention when evidence
  is insufficient
- No fabricated metrics, findings or user numbers — anywhere; unverified facts are marked as such
- Heavy dependencies added only when their feature lands (ADR-0005)

## Known limitations (honest)

- RELIA's hosted-provider adapters are implemented and tested against scripted providers; real
  API activation awaits owner keys (RAG explanations and groundedness eval light up then)
- FinGuard's fan-out/cycle alerts are not yet ranked (only fan-in is); structuring and
  rapid-movement are validated on synthetic fixtures only (no planted ground truth in HI/LI-Small)
- TerraScope's absolute water levels depend on the calibrated MNDWI threshold (stated in every
  contract); the classification measures weak-label agreement, not map accuracy
- No database: queue state is append-only JSONL on the data root; Postgres/PostGIS is planned but
  intentionally not provisioned (deployment doc)
- CI's first real run happens on the first push (GitHub repo creation pending)
