# TerraScope

Geospatial environmental intelligence for the **Pallikaranai Marsh, Chennai** — satellite
ingestion, spectral-index analytics, land-cover classification, change detection and
evidence-grounded environmental reporting.

**Status: designed, not implemented.** The package skeleton, configuration integration and
tests exist; the pipeline does not. See:

- Architecture: [`../../docs/architecture/terrascope.md`](../../docs/architecture/terrascope.md)
- Dataset research: [`../../docs/data-sources/terrascope-datasets.md`](../../docs/data-sources/terrascope-datasets.md)
- Manifest: [`../../data/manifests/terrascope-manifest.yaml`](../../data/manifests/terrascope-manifest.yaml)
- Roadmap: [`../../docs/implementation-plans/roadmap.md`](../../docs/implementation-plans/roadmap.md)

## Layout

```
src/terrascope/    core package (config: validated dataset-dir resolution via relia)
pipelines/         end-to-end pipeline orchestration (planned)
ingestion/         STAC search, AOI retrieval, masking, compositing (planned)
features/          spectral indices (NDVI, NDWI, MNDWI, NDBI) (planned)
models/            land-cover classification + spatial block CV (planned)
evaluation/        validation, uncertainty, change-detection metrics (planned)
evidence/          evidence-contract production for environmental claims (planned)
api/               FastAPI surface (planned)
frontend/          MapLibre map UI (planned)
configs/           reproducible processing configuration (template present)
tests/             unit + smoke tests (working)
```

## Non-negotiables

- Spatial block cross-validation; random pixel splits are leakage
- Every environmental claim carries an `EvidenceContract` — or an explicit abstention
- AOI-bounded data access only; ≤ 10 GB budget; datasets live on the external drive,
  resolved via `PORTFOLIO_DATA_ROOT` (never the repo)
- The study boundary is **approximate** until an authoritative source is verified
