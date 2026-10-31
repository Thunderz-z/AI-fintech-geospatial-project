# Architecture Overview

Status: designed (Phase 4 of the initialization plan). This document defines the system-level
architecture; per-project designs live in [relia.md](relia.md), [terrascope.md](terrascope.md)
and [finguard.md](finguard.md). Decisions are recorded as ADRs in [`docs/decisions/`](../decisions/).

## Goals

Three connected, production-oriented assets demonstrating: reliability engineering (RELIA),
geospatial/environmental ML (TerraScope) and financial-crime analytics (FinGuard) — with one
shared theme: **machine-verifiable evidence**. Every important claim a system makes carries its
evidence, methodology, uncertainty and limitations, or the system abstains explicitly.

## Monorepo and workspace

Single Git repository, uv workspace, three installable packages:

| Package | Path | Depends on |
|---|---|---|
| `relia` | `packages/relia` | pydantic |
| `terrascope` | `projects/terrascope` | relia |
| `finguard` | `projects/finguard` | relia |

Each project has a `src/` core package (importable, installed editable by the workspace) plus
pipeline directories that the core package and future services build on (ADR-0001). The root
project is virtual and pins the shared dev toolchain (pytest, ruff, mypy).

## Cross-project dependency rules

```
terrascope ──▶ relia ◀── finguard
```

- Applications depend on RELIA, never on each other.
- RELIA depends on no application; its scope grows only when applications expose real needs
  (ADR-0005).
- Shared evidence contracts live in RELIA and are consumed everywhere; domain data structures
  stay in the applications.
- The data-path utility (`relia.config.paths`) is the only sanctioned way to reach datasets.

## Evidence contracts (the shared innovation)

`relia.contracts.evidence.EvidenceContract` binds a generated claim to:

- typed `EvidenceRef`s (satellite observation, raster statistic, transaction record, graph
  motif, model result, document excerpt, evaluation result, execution trace)
- methodology (name, version, parameters)
- observation period, confidence, free-form uncertainty statement
- validation status, limitations, explicit `AbstentionInfo`

Enforced invariants: abstained claims state a reason; `VALID` claims reference at least one
evidence item; confidence is a probability. Versioned via `schema_version` (ADR-0002).

## Runtime architecture (planned, per project)

Both applications converge on the same shape: reproducible batch pipelines producing analysis
outputs + evidence, an API layer exposing them, and an LLM explanation layer grounded through
RELIA (retrieval + evidence contracts + abstention).

- **TerraScope**: STAC search → scene filter → AOI band retrieval (COG windows) → SCL masking →
  seasonal compositing → spectral indices → classification (spatial block CV) → change
  detection → uncertainty → stored outputs + evidence → FastAPI → MapLibre UI → grounded
  narrative.
- **FinGuard**: transaction ingestion → validation → temporal features → temporal split →
  LightGBM fraud model → transaction graph → AML motif detection → investigation workflow →
  evidence validation → RAG explanation → human review → audit log.

Databases (PostgreSQL/PostGIS, pgvector where justified) and Docker Compose are introduced when
the first persistent store / API needs them — not before (ADR-0005).

## Configuration and reproducibility

- Processing configurations are versioned files (`projects/*/configs/`); every analysis output
  records the resolved configuration, scene IDs, dates, versions and validation metrics that
  produced it.
- Environments: `uv.lock` pins everything; `.python-version` pins 3.13.
- Secrets: environment variables / `.env` only (never committed); `.env.example` documents keys.

## Validation methodology (summary; ADR-0006)

| Concern | Rule |
|---|---|
| TerraScope model evaluation | Spatial block cross-validation; random pixel splits forbidden |
| FinGuard model evaluation | Temporal train/validation/test; random splits forbidden |
| LLM evaluation | Deterministic checks separated from LLM-as-judge; bootstrap CIs where sampling justifies; never fabricated |
| Environmental causality | Observed change ≠ attributed cause; distinguish observation, uncertainty, causation |
| Financial suspicion | Pattern detection ≠ proof of crime; human approval for consequential decisions |

## Deployment strategy (target, not built)

GitHub → Actions CI/CD → containerized FastAPI (Render or similar) + managed PostgreSQL/PostGIS
+ object storage for raster assets + frontend hosting (Vercel). External dataset paths stay
configurable so production can swap the drive for object storage. Documented before implemented;
no expensive infrastructure until the core applications work.

## Multi-agent workflow

Four agents with strict ownership (RELIA / TerraScope / FinGuard / Architecture-QA), protected
shared files, feature-branch strategy and reporting requirements: [AGENTS.md](../../AGENTS.md).

## Unresolved technical risks

1. **Windows geospatial toolchain on 3.13** — rasterio/geopandas wheels must be verified at
   ingestion time (first heavy-dependency install; ADR-0005 gates it).
2. **No verified machine-readable Pallikaranai wetland boundary** — an explicitly labelled
   approximate study polygon is used until an authoritative source is found.
3. **LLM evaluation nondeterminism** — mitigated by cassettes, versioned datasets, CIs and
   honest reporting, never eliminated.
4. **Single-machine disk budget** — external-drive-first design plus AOI-bounded access keep
   growth bounded; the 500 MB/download gate is enforced socially via AGENTS.md today.
