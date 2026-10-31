# ADR-0005: Staged Dependency Strategy (Lean Now, Heavy When Needed)

- Status: Accepted
- Date: 2026-10-31
- Deciders: portfolio owner, initialization run

## Context

The internal SSD has ~60 GB free. The geospatial stack (rasterio, GeoPandas, xarray, pyproj),
ML stack (scikit-learn, LightGBM, torch) and web stack (FastAPI, SQLAlchemy) total hundreds of
megabytes plus compiled dependencies — and Python 3.13 wheel availability must be verified for
each. Installing everything upfront would violate the storage budget and hide version
compatibility problems until late.

## Decision

**Lean initial lock**: pydantic v2 (runtime) + pytest, pytest-cov, ruff, mypy (dev). Heavy
dependency groups are added **when their feature lands**, one project at a time:

| When | Add | Verify first |
|---|---|---|
| TerraScope ingestion | pystac-client, planetary-computer, rasterio, rioxarray, geopandas, shapely, pyproj, numpy, pandas | 3.13 Windows wheels; disk budget |
| TerraScope modelling | scikit-learn, lightgbm | CPU-only builds; no CUDA without GPU check + approval |
| FinGuard pipelines | pandas, pyarrow, lightgbm, networkx (or igraph) | same |
| First API | fastapi, uvicorn, sqlalchemy, asyncpg/psycopg | PostGIS provisioning plan |
| LLM adapters | provider SDKs (behind RELIA abstraction) | key handling via `.env` only |

Constraints carried forward: no CUDA/GPU packages without checking the 4 GB-VRAM GPU and
getting approval; CPU-first design; no unrestricted downloads.

## Consequences

- `uv.lock` stays reviewable; disk stays within budget.
- Dependency additions are visible commits (AGENTS.md protection on root `pyproject.toml`).
- Synthetic fixtures keep tests runnable without heavy stacks, so tests never justify early
  installs.
