# TerraScope

Geospatial environmental intelligence for the **Pallikaranai Marsh, Chennai** — satellite
ingestion, spectral-index analytics, land-cover classification, change detection and
evidence-grounded environmental reporting.

TerraScope runs end-to-end on real data. The full Sentinel-2 L2A record 2019-04 → 2026-10 is
acquired (219 scenes, 2.34 GB of the 10 GB budget) together with the **authoritative Ramsar
IN2481 boundary** (1,246.76 ha measured vs 1,247.54 ha declared). Implemented and running:
gated ingestion, SCL masking, seasonal composites, spectral indices, the MNDWI water-extent
series **v1** (threshold calibrated against WorldCover permanent water, mean κ = 0.45; QA
points 7/12), random-forest classification under spatial block CV (58.97% ± 3.22% vs weak
labels), bootstrap-CI seasonality (+9.1 pp NE-monsoon vs dry, CI [4.0, 14.9]), **epoch change
detection** (winter 2019-20 vs 2023-24: water 25.05% → 24.74%, with per-pixel uncertainty
maps), and a **read-only FastAPI surface + MapLibre client**. On the roadmap next:
ground-truth QA points, multi-class change detection, RELIA-written narrative reports (awaits
API keys). See:

- Ingestion module: [`ingestion/README.md`](ingestion/README.md) (code: `src/terrascope/ingestion/`)
- Architecture: [`../../docs/architecture/terrascope.md`](../../docs/architecture/terrascope.md)
- Dataset research: [`../../docs/data-sources/terrascope-datasets.md`](../../docs/data-sources/terrascope-datasets.md)
- Manifest: [`../../data/manifests/terrascope-manifest.yaml`](../../data/manifests/terrascope-manifest.yaml)
- Roadmap: [`../../docs/implementation-plans/roadmap.md`](../../docs/implementation-plans/roadmap.md)

## Layout

```
src/terrascope/
  ingestion/       gate (approval-gated downloads) | aoi | stac_search | scenes | cog_reader
                   | masking | composite | pipeline | __main__ (CLI: status/download/composite/water/analyse)
  features/        indices (NDVI/NDWI/MNDWI/NDBI) | water_extent (series + abstention)
                   | calibration (MNDWI vs WorldCover) | change (epoch transitions + uncertainty)
  models/          classification (RF + spatial block CV) | classification_labels
  evaluation/      spatial_cv (deterministic disjoint block folds + invariant validator)
  evidence/        water (EvidenceContract builders)
  api/             FastAPI read-only surface + optional static frontend mount
frontend/          index.html (MapLibre + analysis cards + evidence viewer, no build step)
scripts/           acquire_worldcover | calibrate_water_threshold | run_classification
                   | run_change_detection | seasonality_analysis | water_threshold_sensitivity
                   | render_quicklooks
configs/           reproducible processing configuration (template)
tests/             126 offline tests on synthetic fixtures (no network, no data root)
```

## Non-negotiables

- Spatial block cross-validation; random pixel splits are leakage
- Every environmental claim carries an `EvidenceContract` — or an explicit abstention
- Observed change is never attributed to a cause
- AOI-bounded data access only; ≤ 10 GB budget; datasets resolved via `PORTFOLIO_DATA_ROOT`,
  never the repo
- Absolute water levels are threshold-dependent — the calibrated threshold is stated everywhere

## Key numbers (reproducible; artefacts on the data root)

| Result | Value | Artefact |
|---|---|---|
| Water seasonality (2019–2026) | NE-monsoon 19.5% vs dry 10.4%; Δ +9.1 pp, CI [4.0, 14.9] | `processed/water-extent/*_v1.json`, `exports/seasonality/` |
| Usable dates | 137 of 195 (58 abstained on the 80% gate) | water-extent series JSON |
| Epoch change (winter) | water 25.05% → 24.74%; gained 0.94% / lost 1.24% | `processed/change-detection/` |
| Classification (block CV) | 58.97% ± 3.22% vs weak WorldCover labels | `processed/classification/` |
