# Initial Setup Report (Phases 1–6)

Date: 2026-10-31 · Branch: `main` · Commits: `d34bf80` (foundation), `09cba0c` (docs),
setup report commit. Statuses: **Completed** / **Partially completed** / **Planned** / **Blocked**.

## A. Environment

| Item | Value | Status |
|---|---|---|
| Python (repo) | 3.13.18, `C:\...\AI-fintech-geospatial-project\.venv\Scripts\python.exe` (uv-managed CPython) | Completed |
| Python 3.11.5 (legacy) | `AppData\Local\Programs\Python\Python311` — untouched | Completed |
| uv | 0.13.6 | Completed |
| Git | 2.47.1.windows.2, identity ThunderzZ | Completed |
| Docker | **not installed** (`docker: command not found`) | Blocked (owner decision to install; nothing needs it yet) |
| Node.js | v22.13.1 | Completed |
| Disk C: | 58.9 GiB free (94% used) | Completed |
| Disk D: | 215.8 GiB free | Completed |
| `PORTFOLIO_DATA_ROOT` | persistent user var (registry-verified) + repo `.env` | Completed |

## B. Repository

- uv workspace: root (virtual, dev toolchain) + members `relia`, `terrascope`, `finguard`
  (editable installs, workspace sources). One `uv.lock`.
- Monorepo skeleton per ADR-0001 (incl. documented `src/` adaptation); 26 `.gitkeep` placeholders
- Git: `main` branch, 2 commits + this report, clean tree; `.env`/`.venv`/`.zcode`/`.codebase-memory` ignored
- Files: ~90 (63 code/foundation + 21 docs + report)

## C. Data storage

- Root `D:\GITHUB\AI-Portfolio\Portfolio data` exists with full 11-subtree layout (pre-created, verified)
- Resolution: `PORTFOLIO_DATA_ROOT` env → repo `.env` fallback; typed errors; writability probe; no silent fallback (ADR-0003)
- CLI verification: `uv run relia check-data-root` → healthy, 215.8 GiB free, all project dirs present
- Test coverage: env-var priority, dotenv fallback, missing/bad/unwritable roots, spaces-in-path,
  project whitelisting, create-on-demand (38 tests total, 1 Windows-skipped POSIX chmod test)

## D. Codebase Memory

- MCP server reachable; project registered; config keys `auto_index`/`auto_watch`/`watcher_enabled` all `true` (verified via CLI)
- Full re-index after scaffolding: **succeeded** — 494 nodes, 1214 edges (was 2 nodes)
- Watcher: active, git strategy, 5 s poll, last scan post-commit
- Coverage: 10/10 key source files `no_recorded_issue`; only by-design exclusions unindexed
  (`.git`, `.venv`, caches, `.env`); `parse_partial`: `.env.example` only (non-Python, harmless)
- Setup documented in `docs/architecture/codebase-memory.md`

## E. Architecture

- RELIA: module map + planned components in `docs/architecture/relia.md`; implemented surface:
  config/paths, contracts, provider/tracing/eval/replay interfaces, CLI
- TerraScope: pipeline design (STAC→mask→composite→indices→classify→change→evidence→API→map)
- FinGuard: pipeline design (ingest→features→temporal split→model→graph motifs→investigation)
- Evidence contracts: `relia.contracts.evidence` v1.0.0 — shared verification envelope (ADR-0002)
- ADRs 0001–0006 recorded; cross-project dependency rule: apps → RELIA only

## F. Dataset strategy

- Research docs: `docs/data-sources/terrascope-datasets.md`, `finguard-datasets.md`
- Manifests: `data/manifests/{terrascope,finguard}-manifest.yaml` — status `planned`, checksums/acquisition dates pending
- Licensing: Sentinel-2/WorldCover/Dynamic World CC-BY-4.0; OSM ODbL; IBM AML + PaySim "verify terms at download"; IEEE-CIS deferred (Kaggle rules acceptance)
- Sizes marked (approx.) — verification required at acquisition; budgets 10 GB / 5 GB; 500 MB per-file gate
- **Unresolved access requirements**: IBM AML + PaySim Kaggle terms acceptance (owner); GEE auth for Dynamic World (optional); authoritative Pallikaranai boundary source (investigation task M0.1)

## G. Agent coordination

- Ownership, protected files, branch strategy, reporting requirements: `AGENTS.md`
- Feature branches at parallel work: `feature/relia-*`, `feature/terrascope-*`, `feature/finguard-*`, `feature/integration-*`
- Shared interfaces (contracts, provider/tracing/eval/replay protocols, paths utility) defined before parallel integration
- Conflict risks: root `pyproject.toml` + `uv.lock` (dependency additions), evidence schema changes — protected

## H. Validation

- `uv run pytest` → **38 passed, 1 skipped** (POSIX chmod test skipped on Windows — documented)
- `uv run ruff check .` → **clean**; `uv run mypy` → **Success: no issues in 20 source files**
- `uv run relia check-data-root` → healthy; `infrastructure/scripts/check_env.py` runs (honest exit-1 when env var absent from current process, with guidance)
- CI workflow (ubuntu: uv sync --locked → ruff → pytest) — first run will occur on first push (no remote configured yet: **Planned**)
- Dependency resolution: uv.lock pinned; heavy stacks deliberately deferred (ADR-0005)

## I. Next steps (first tasks per agent — detail in `roadmap.md`)

- **Agent 2 (TerraScope)** M0: boundary source investigation → geo deps (wheel gate) → STAC retrieval → SCL masking/compositing → indices → water-extent v0 with abstention + evidence
- **Agent 3 (FinGuard)** M1: Kaggle terms verification → LI-Small acquisition → ingestion + temporal split + leakage tests → LightGBM baseline → 2 motif detectors on planted fixtures
- **Agent 1 (RELIA)** M2 (interleaved): first provider adapter → cassettes → prompt registry + eval runner
- **Agent 4 (QA)**: review interface fit after M0/M1 first increments; set up remote + first CI run when the owner creates the GitHub repository

## Explicitly not done (per master-prompt stop condition §18)

No dataset downloads; no CUDA/GPU packages; no Docker/PostGIS provisioning; no frontend code; no agent dispatch; Python 3.11 untouched.
