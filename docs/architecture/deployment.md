# Deployment Architecture

Status: documented (implemented for CI builds; no cloud deployment executed —
cost decisions deliberately precede any infrastructure spend).

## Current, verified locally

Two FastAPI services, no database, datasets external:

| Service | Run locally | Surface |
|---|---|---|
| TerraScope API | `uv run uvicorn terrascope.api.app:app --port 8801` | read-only analysis artefacts + MapLibre client |
| FinGuard API | `uv run uvicorn finguard.api.app:app --port 8802` | investigation queue + audited decisions + client |

Both resolve datasets exclusively through `PORTFOLIO_DATA_ROOT`. The
frontends are static files served by the same apps (`static_dir` mount;
ADR-0007).

## Containerization (CI-built, not locally run)

`infrastructure/docker/{terrascope,finguard}.Dockerfile` — python:3.13-slim +
uv, `uv sync --locked --frozen --no-dev --package <name>`, dataset root
mounted at `/data` at runtime (never baked in). CI builds both images on
every push (the `docker` job in ci.yml); the owner's machine has no Docker
(ADR-0007). Compose file mirrors the mount layout for any Docker-capable host.

## Target cloud shape (when deployed)

| Concern | Choice | Rationale / cost note |
|---|---|---|
| Source | GitHub | already the CI trigger; repo creation is the owner's step |
| API hosting | Any container platform (Render/Fly/Cloud Run) | free/low tiers suffice for a portfolio demo; images come from CI |
| Data root | Mounted volume → object storage for rasters | the data-path utility only needs the env var repointed (ADR-0003); raw Sentinel-2 is ~2.3 GB — object storage pennies/month |
| Databases | **None today** | honest: queue state is append-only JSONL + JSON on disk; Postgres/PostGIS only when a multi-writer need exists (documented, not speculative) |
| Frontend | Served by the APIs (static mount) | no separate hosting until a React SPA exists (ADR-0007) |
| LLM | Hosted provider APIs via RELIA | keys in platform secret store (`RELIA_*`), never in images |

## Secrets and configuration

`.env` locally; platform env vars in deployment; `PORTFOLIO_DATA_ROOT` +
`RELIA_*` are the only runtime secrets/configuration. No credentials in the
repo or images (AGENTS.md rule 8).

## Deliberately not done

No Kubernetes, no Terraform, no managed PostGIS, no CDN — nothing is
provisioned before a real deployment need exists; this document is the plan
that keeps that honest.
