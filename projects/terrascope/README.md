# TerraScope

Geospatial environmental intelligence for the **Pallikaranai Marsh, Chennai** — satellite
ingestion, spectral-index analytics, land-cover classification, change detection and
evidence-grounded environmental reporting.

**Status: M0 ingestion implemented; first retrieval pending approval.** The ingestion module
(STAC search → AOI-bounded windowed reads → SCL masking → seasonal median compositing) is
implemented and tested offline; **no satellite data has been downloaded** — every network
access is blocked by an explicit approval gate until the portfolio owner approves the first
retrieval. Indices, classification and change detection remain planned. See:

- Ingestion module: [`ingestion/README.md`](ingestion/README.md) (code: `src/terrascope/ingestion/`)
- Architecture: [`../../docs/architecture/terrascope.md`](../../docs/architecture/terrascope.md)
- Dataset research: [`../../docs/data-sources/terrascope-datasets.md`](../../docs/data-sources/terrascope-datasets.md)
- Manifest: [`../../data/manifests/terrascope-manifest.yaml`](../../data/manifests/terrascope-manifest.yaml)
- Roadmap: [`../../docs/implementation-plans/roadmap.md`](../../docs/implementation-plans/roadmap.md)

## Layout

```
src/terrascope/    core package: config + ingestion (STAC search, windowed reads,
                   masking, compositing — implemented, downloads approval-gated)
pipelines/         end-to-end pipeline orchestration (planned)
ingestion/         README + docs pointer for the ingestion stage (implemented)
features/          spectral indices (NDVI, NDWI, MNDWI, NDBI) (planned)
models/            land-cover classification + spatial block CV (planned)
evaluation/        validation, uncertainty, change-detection metrics (planned)
evidence/          evidence-contract production for environmental claims (planned)
api/               FastAPI surface (planned)
frontend/          MapLibre map UI (planned)
configs/           reproducible processing configuration (template present)
tests/             unit + ingestion tests on synthetic fixtures (working)
```

## Non-negotiables

- Spatial block cross-validation; random pixel splits are leakage
- Every environmental claim carries an `EvidenceContract` — or an explicit abstention
- AOI-bounded data access only; ≤ 10 GB budget; datasets live on the external drive,
  resolved via `PORTFOLIO_DATA_ROOT` (never the repo)
- The authoritative boundary source is **verified** (Ramsar RSIS site IN2481, WFS polygon,
  CC BY 4.0 — machine-readable); until it is downloaded, the explicitly labelled
  **approximate** bbox stays the default study boundary and is never presented as legal
