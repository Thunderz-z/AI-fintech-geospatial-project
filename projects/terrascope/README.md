# TerraScope

Geospatial environmental intelligence for the **Pallikaranai Marsh, Chennai** — satellite
ingestion, spectral-index analytics, land-cover classification, change detection and
evidence-grounded environmental reporting.

**Status: M1 running on real data.** Full Sentinel-2 record acquired (2019-04 → 2026-10,
219 scenes, 2.34 GB of the 10 GB budget) + authoritative Ramsar IN2481 boundary + ESA
WorldCover 2021 reference subset. Implemented: gated ingestion, compositing, spectral
indices, water-extent series **v1** (threshold calibrated against WorldCover permanent
water, mean κ = 0.45; QA points 7/12), random-forest classification under spatial block CV
(58.97% ± 3.22% agreement with weak labels), and bootstrap-CI seasonality (+9.1 pp NE-monsoon
vs dry, CI [4.0, 14.9]). Remaining: ground-truth QA, change detection, API. See:

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
