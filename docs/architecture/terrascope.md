# TerraScope — Architecture

Status: M0 steps 1–6 started and largely implemented on real data — ingestion (gated retrieval,
windowed COG reads, SCL masking, seasonal compositing), features (NDVI/NDWI/MNDWI/NDBI on
composites; per-scene MNDWI water-extent series with valid-fraction gating and abstention) and
the first evidence contract. First acquisitions: Ramsar IN2481 boundary + 14 Sentinel-2 L2A
scenes (2023-10 → 2024-03), 261 MB of the 10 GB budget. Remaining: index/threshold calibration
QA, spatial block CV scaffolding, classification, change detection, API and frontend.

## Research problem

Measure and explain environmental and land-cover change in the Pallikaranai Marsh, Chennai,
Tamil Nadu, India, using satellite imagery and supporting spatial datasets — with every claim
traceable to its underlying data and every numerical claim abstained when data quality is
insufficient.

## Pipeline (target)

```
STAC search → scene filtering → AOI selection → band retrieval (COG windows)
  → cloud/shadow masking (SCL) → seasonal compositing
  → spectral indices (NDVI, NDWI, MNDWI, NDBI)
  → land-cover classification → temporal comparison / change detection
  → validation (spatial block CV) → uncertainty quantification
  → stored analysis outputs + evidence contracts
  → FastAPI → MapLibre map → evidence-grounded narrative (via RELIA)
```

## Processing configuration (reproducibility)

`configs/processing.example.yaml` is the template. Every run records: scene IDs, observation
dates, bands, resolutions, CRS, cloud thresholds, masking method, compositing strategy, model
version, validation metrics — and stores them alongside outputs and inside evidence contracts.

Key defaults (to be verified against real scenes at ingestion):

- Collection `sentinel-2-l2a` (Microsoft Planetary Computer), cloud cover filter ≤ 20%
- Bands B02/B03/B04/B08 (10 m), B11/B12/SCL (20 m; resampled where analysis requires)
- SCL classes excluded from composites: 0, 1, 3, 8, 9, 10, 11 (nodata, saturated, cloud
  medium/high, thin cirrus, shadow); class 2 (dark pixels) retained pending visual QA
- Seasonal median compositing over the available record (2019→present)

## ML methodology

- Classical models first (Random Forest, LightGBM) where justified; no deep learning for
  prestige.
- **Spatial block cross-validation** for classification accuracy — random pixel splits are
  leakage (ADR-0006).
- Change detection reports observed change, classification uncertainty and validation error
  separately; observed change is never presented as caused by a specific activity without
  additional evidence.
- Abstention: numerical claims require minimum cloud-free coverage and sufficient valid
  observations; otherwise the evidence contract records an explicit abstention with the reason.

## Data architecture

- Datasets live under `PORTFOLIO_DATA_ROOT/terrascope/{raw,interim,processed,models,exports}`.
- AOI-bounded access only: STAC windowed COG reads; no full-scene or global downloads;
  ≤ 10 GB initial budget (dataset research: [../data-sources/terrascope-datasets.md](../data-sources/terrascope-datasets.md)).
- Study-area boundary: the authoritative machine-readable source is **verified** — Ramsar
  Sites Information Service, site no. 2481 (Pallikaranai Marsh Reserve Forest, WFS polygon,
  CC BY 4.0; covers the 1,247.54 ha Reserve Forest, not the full historical marsh). Until that
  polygon is downloaded (approval-gated), the explicitly labelled **approximate** bbox is the
  default study boundary; provenance and status travel with the AOI object and into outputs.

## API + frontend (planned)

FastAPI serving analysis outputs, change summaries and evidence contracts; MapLibre-based map
with layers per index/composite/epoch; every displayed number links to its evidence.

## Testing

Unit tests for masking, compositing, index math and classification on tiny synthetic rasters;
geometry/motif-level fixtures for change detection; API tests; no raw data required (ADR-0005
gates the heavy geo dependencies until ingestion lands).
