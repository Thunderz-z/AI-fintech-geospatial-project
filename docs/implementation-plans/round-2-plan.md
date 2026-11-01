# Round 2 Plan — M0/M1 Closed; Calibration, Alert Ranking, RELIA M2

Date: 2026-11-01 · Coordinator: main chat (Agent 4 role) · Status of round 1: **verified and
closed**. Branches stay as parallel worktrees per owner decision — merge happens at round end.

## 1. Verified state (independently checked by coordinator, not just reported)

| Item | TerraScope (`feature/terrascope-m0`) | FinGuard (`feature/finguard-m1`) |
|---|---|---|
| Head | `6881150` — 7 commits | `5341b12` — 8 commits |
| Tests / lint (re-run by coordinator) | **114 passed**, 1 skipped, ruff clean | **79 passed**, 1 skipped, ruff clean |
| Milestone | **M0 complete** (report: `projects/terrascope/docs/M0-REPORT.md`) | **M1 steps 1–6 complete** (status: `projects/finguard/README.md`) |
| Data on external root | 2.34 GB / 10 GB budget (219 scenes, 1,533 checksummed files, Ramsar IN2481 boundary) | 1.5 GB / 5 GB budget (HI-Small + LI-Small, checksums verified in manifest) |
| Key results | Full-record water series 2019→2026: 137/195 dates usable, 58 abstained; Ramsar water 0.2–48.1%; NE-monsoon 19.5% vs dry 10.4% (threshold-ordering robust, absolute levels uncalibrated) | HI-Small test PR-AUC 0.0159 (15.6× base rate), 92% precision @ 0.1% alert budget; fan-in 100% detectable-attempt recall, precision ~0.001 = the open problem |
| Evidence | `EvidenceContract`s verified well-formed on disk (schema v1.0.0, real refs, abstentions recorded) | Metrics JSONs verified: values match the report exactly, honest "synthetic" labelling |

Boundary win: the approximate-bbox limitation from initialization is **resolved** — the
authoritative Ramsar RSIS IN2481 polygon (1,246.76 ha measured vs 1,247.54 ha declared) is now
the primary study boundary.

Known doc issue: FinGuard's README "Layout" section still lists `features/models/graph` as
"planned" although `src/finguard/{features,graph,model,patterns}.py` exist and are tested —
stale-honesty fix assigned as **F0** below.

## 2. TerraScope — M1 tasks (Agent 2, worktree `AI-fintech-terrascope`)

Continues on the same branch (`feature/terrascope-m0` carries the project line).

- **T1 — WorldCover reference subset**: add manifest entry `esa-worldcover-2021-v200-aoi`
  acquisition; owner approval gate for the download (~10–50 MB).
- **T2 — MNDWI threshold calibration** (the M0 follow-up): calibrate the water threshold
  against the WorldCover 2021 water class + manual QA points; emit water-series **v1** with the
  calibrated threshold; update evidence contracts to state calibration + reference. Keep the
  threshold-sensitivity artefact as the honesty record.
- **T3 — First land-cover classification** on the winter composite using
  `evaluation/spatial_cv.SpatialBlockSplitter` (RF first; LightGBM optional). Labels are
  WorldCover-derived (weak) — the label-quality limitation goes in the contract and the report.
  Block size 2000 m start; variogram check only if labels justify it.
- **T4 — Seasonality analysis**: bootstrap CI over dates for the seasonal contrast
  (NE-monsoon vs dry), plot to `exports/`, short evaluation note in `docs/evaluations/`.

## 3. FinGuard — M1.5 tasks (Agent 3, worktree `AI-fintech-finguard`)

- **F0 — README honesty refresh**: layout section must reflect implemented modules.
- **F1 — Alert ranking** (the open problem): ranking features for fan-in alerts (account
  degree/age, burst isolation, amount stats), two-stage filter; re-evaluate **precision at the
  0.1% alert budget on detectable planted attempts** vs the v0 baseline (~0.001); new metrics
  JSON; no metric reported without the reproducible command.
- **F2 — Evidence-contract wiring**: alert → `relia.contracts.EvidenceContract` bundle
  (transaction refs, motif params, model rank, abstention when evidence thin).
- **F3 — Fan-out + cycle detectors**: same protocol as fan-in — synthetic planted fixtures for
  detector validation, then HI-Small evaluation; report recall vs alert precision trade-off.

## 4. RELIA — M2 service layer (Agent 1, **new worktree needed**)

Both apps hit LLM-explanation needs next (TerraScope narrative reports, FinGuard alert RAG).

```powershell
cd "C:\Github\My portfolio and resume projects\AI-fintech-geospatial-project"
git worktree add ..\AI-fintech-relia -b feature/relia-m2
# then: copy .env into the worktree and uv sync (coordinator or the agent's setup step)
```

- **R1 — First provider adapter** implementing `relia.providers.base.LLMProvider`:
  config-driven model/params, timeouts, retry/backoff, `Usage` + cost accounting, structured-
  output validation (`MalformedStructuredOutputError`). **Credential gate**: adapter is
  implemented and tested against a fake provider; the real API key goes in the worktree `.env`
  only when the owner supplies it.
- **R2 — Cassette recorder/replayer** behind the provider interface (network-free tests;
  `ReplayMismatchError` on divergence).
- **R3 — Prompt registry + deterministic eval runner** + `relia eval` CLI skeleton (versioned
  prompts, `EvalResult` outputs to `docs/evaluations/`).

## 5. Integration & coordination (this chat)

- **I1 — Merge cadence**: branches merge to `main` at round end. Expected conflict:
  `docs/implementation-plans/roadmap.md` (TerraScope's branch already marked M0 complete);
  coordinator resolves, keeping both projects' status updates.
- **I2 — GitHub remote**: still not created (owner decision). CI runs on first push.
- **I3 — Codebase Memory**: re-index after each merge; watcher already active.
- **Budgets**: TerraScope 7.66 GB / FinGuard 3.5 GB remaining; per-file 500 MB gate; every
  acquisition needs a manifest entry + owner approval.
- **Worktrees stay** until the owner says everything is done; then `git worktree remove`.

## Appendix — Round-2 kickoff prompts (paste-ready)

### Agent 2 — TerraScope M1

```text
You are Agent 2 (TerraScope). Read AGENTS.md first — you own projects/terrascope/ ONLY.

WORKTREE: C:\Github\My portfolio and resume projects\AI-fintech-terrascope (branch
feature/terrascope-m0 — verify with git branch --show-current). The main repo folder and the
AI-fintech-finguard / AI-fintech-relia worktrees are OFF-LIMITS. The .venv exists; do not
re-sync unless you change dependencies. Coordination doc: read
docs/implementation-plans/round-2-plan.md (§2 defines your tasks T1–T4).

TASK — TerraScope M1, in order:
T1 WorldCover 2021 v200 AOI subset: add the manifest entry; STOP and ask for my approval
   before downloading (~10–50 MB). While waiting, prepare the calibration code offline.
T2 MNDWI threshold calibration vs WorldCover water class + manual QA points; water-series v1
   with calibrated threshold; update evidence contracts (calibration + reference stated;
   keep the threshold-sensitivity artefact).
T3 First land-cover classification on the winter composite using
   terrascope.evaluation.spatial_cv.SpatialBlockSplitter (RF first). Labels are
   WorldCover-derived (weak) — state that limitation in the contract and report.
T4 Seasonality analysis with bootstrap CI over dates + plot + short note in docs/evaluations/.

RULES (AGENTS.md, binding): never edit packages/relia or other projects; report needed RELIA
interface changes back instead. Datasets only via PORTFOLIO_DATA_ROOT; no acquisition without
manifest entry + my approval; ≤ 10 GB total (7.66 GB remaining). MNDWI results: observation
only, no causal attribution; abstain when coverage/quality is insufficient. Spatial block CV
only — random splits are leakage. No placeholder implementations presented as done. Keep green:
uv run pytest && uv run ruff check . Commit small, logical commits to YOUR branch; never merge
to main. Use the Codebase Memory MCP tools for structural questions.

REPORT per AGENTS.md when T1–T4 are done: files, deps, test results, assumptions, questions,
storage used, and the reproducible commands for every number you report.
```

### Agent 3 — FinGuard M1.5

```text
You are Agent 3 (FinGuard). Read AGENTS.md first — you own projects/finguard/ ONLY.

WORKTREE: C:\Github\My portfolio and resume projects\AI-fintech-finguard (branch
feature/finguard-m1 — verify with git branch --show-current). The main repo folder and the
AI-fintech-terrascope / AI-fintech-relia worktrees are OFF-LIMITS. The .venv exists; do not
re-sync unless you change dependencies. Coordination doc: read
docs/implementation-plans/round-2-plan.md (§3 defines your tasks F0–F3).

TASK — FinGuard M1.5, in order:
F0 Refresh projects/finguard/README.md layout: features/model/graph/patterns modules exist —
   the "planned" labels are stale.
F1 Alert ranking for fan-in (the open problem: precision ~0.001 at 100% detectable-attempt
   recall): add ranking features (account degree/age, burst isolation, amount stats) and/or a
   two-stage filter; re-evaluate precision at the 0.1% alert budget ON DETECTABLE PLANTED
   ATTEMPTS vs v0; write a new metrics JSON + the exact reproduction command.
F2 Wire alerts to relia.contracts.EvidenceContract bundles (transaction refs, motif params,
   model rank; abstention when evidence is thin). Do not modify packages/relia — the contract
   API in relia.contracts is sufficient.
F3 Fan-out and cycle detectors: validate on synthetic planted fixtures first, then evaluate on
   HI-Small with the same protocol as fan-in; report the recall/precision trade-off.

RULES (AGENTS.md, binding): never edit packages/relia or projects/terrascope. Datasets only via
PORTFOLIO_DATA_ROOT (worktree .env already configured); ≤ 5 GB total (3.5 GB remaining); no new
downloads without manifest + approval. All data is SYNTHETIC IBM AML — label it so everywhere; a
detected motif is a suspicious pattern, never a laundering finding. Temporal splits only;
random splits are leakage. Metrics only from reproducible runs. Keep green: uv run pytest &&
uv run ruff check . Commit small, logical commits to YOUR branch; never merge to main.

REPORT per AGENTS.md when F0–F3 are done: files, deps, test results, assumptions, questions,
storage, and the reproducible commands for every metric (especially the new fan-in precision).
```

### Agent 1 — RELIA M2 (start only after the worktree exists)

```text
You are Agent 1 (RELIA). Read AGENTS.md first — you own packages/relia/ ONLY.

WORKTREE: C:\Github\My portfolio and resume projects\AI-fintech-relia (branch feature/relia-m2
— verify with git branch --show-current). The main repo folder and the other worktrees are
OFF-LIMITS. If .venv is missing: uv sync, and copy .env from the main repo folder.

TASK — RELIA M2 per docs/implementation-plans/round-2-plan.md §4:
R1 First provider adapter implementing relia.providers.base.LLMProvider (timeouts, retry/
   backoff, Usage + cost accounting, structured-output validation). NO real API key: implement
   and test against a fake provider; the key goes in the worktree .env only when I provide it.
R2 Cassette recorder/replayer behind the provider interface; ReplayMismatchError on divergence;
   network-free tests.
R3 Versioned prompt registry + deterministic evaluation runner + `relia eval` CLI skeleton
   (EvalResult outputs; deterministic checks separated from LLM-as-judge).

RULES (AGENTS.md, binding): you own packages/relia — protected shared files within it
(contracts/, */base.py, config/paths.py) change only additively with schema care; providers/
adapters are yours to build. Tests must not require network or real keys. Keep green:
uv run pytest && uv run ruff check . Commit small, logical commits to YOUR branch; never merge
to main. Use the Codebase Memory MCP tools for structural questions.

REPORT per AGENTS.md when R1–R3 are done: files, deps (keep them minimal — ADR-0005), test
results, assumptions, questions, and exactly what I must put in .env to activate the real
provider.
```
