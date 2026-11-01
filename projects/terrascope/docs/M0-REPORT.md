# TerraScope M0 — Close-out Report

Status: **M0 complete** (steps 1–6, real data). Owner: Agent 2 (TerraScope).
Date: 2026-11-01. Branch: `feature/terrascope-m0`. Machine-readable facts live in
[`data/manifests/terrascope-manifest.yaml`](../../data/manifests/terrascope-manifest.yaml);
every numeric claim in this report traces to a JSON artefact listed in §5.

## 1. Roadmap outcome

| M0 step | Outcome | Evidence |
|---|---|---|
| 1. Authoritative boundary | **Ramsar RSIS site IN2481 verified + acquired** (WFS GeoJSON, CC BY 4.0, 13,913 B, sha256 `a797ed7e…`); measured area 1,246.76 ha vs declared 1,247.54 ha (−0.06%) | manifest `pallikaranai-study-boundary` (status: acquired) |
| 2. Geospatial dependencies | 10 packages, prebuilt cp313 wheels (ADR-0005 gate), COG driver verified | commit `da7c063`; manifest |
| 3. Ingestion module | Implemented: gated STAC search → AOI-bounded windowed COG reads → SCL masking → seasonal median compositing; 100% offline-tested | `src/terrascope/ingestion/`; commit `4c35f1e` |
| 4. Compositing + visual QA | Winter/summer/monsoon-post composites built; quicklooks rendered and inspected (PASS — registration to the Ramsar boundary correct) | `exports/qa/*_quicklook.png` (data root) |
| 5. Indices + water extent | NDVI/NDWI/MNDWI/NDBI on composites; per-scene MNDWI water-extent series v0 with 80% valid-fraction gate and explicit abstentions | `src/terrascope/features/`; §4 |
| 6. Evidence + block CV | First `EvidenceContract`s issued (water-extent series, valid status); spatial block CV scaffolding implemented and tested (random splits structurally impossible in the split path) | `src/terrascope/evidence/`, `src/terrascope/evaluation/spatial_cv.py` |

## 2. Data acquired (all on the external data root; nothing in the repo)

- **Boundary**: `raw/boundaries/ramsar_in2481.geojson` — MultiPolygon, valid; bbox
  80.2082–80.24309 E, 12.8767–12.9683 N.
- **Sentinel-2 L2A** (Microsoft Planetary Computer, tile T44PMV, `eo:cloud_cover` < 20,
  windowed to composite-grid bounds — never full scenes): full available record
  2019-04 → 2026-10 acquired in quarterly batches; per-file SHA-256 in
  `raw/sentinel-2-l2a/acquisition_log.jsonl`.
- **Deduplication**: scene IDs can repeat a sensing date across processing baselines
  (observed for 2023-10-22, reprocessed 2024-09-17); `iter_cached_scenes` keeps the
  latest processing per sensing timestamp for all analysis.

## 3. Methods (implemented)

- **Ingestion** (`terrascope.ingestion`): approval-gated retrieval (code-level
  `DownloadGate`; CLI refuses without `--approve`), windowed COG reads onto a fixed
  resolution-snapped composite grid (EPSG:32644, 10 m / 20 m), SCL masking
  (excluded classes 0, 1, 3, 8, 9, 10, 11; dark-pixel class 2 retained), seasonal
  median compositing with per-pixel valid-count planes. SCL class table corrected
  against ESA documentation: **no dedicated shadow class exists** (3 and 8 are both
  "cloud medium probability").
- **Features** (`terrascope.features`): NDVI/NDWI at 10 m, MNDWI/NDBI at 20 m
  (SWIR1-native; green bilinearly re-projected), per-scene water extent =
  SCL-masked MNDWI > 0 fraction over the approximate-AOI grid **and** inside the
  authoritative Ramsar polygon (rasterized), abstention below 80% valid pixels.
- **Evidence** (`terrascope.evidence`): water-extent claims packaged as RELIA
  `EvidenceContract`s (methodology parameters, per-date uncertainties, abstained
  dates, limitations; valid status requires evidence refs).
- **Evaluation** (`terrascope.evaluation`): `SpatialBlockSplitter` — deterministic
  spatially disjoint block folds (diagonal `(row+col) % n_folds` assignment), with
  `validate_splits` re-checking partition invariants (each pixel a test pixel
  exactly once; train∩test empty per fold; no partial blocks). Random pixel splits
  never enter the path (ADR-0006).

## 4. Results

### 4.1 Visual QA (composites)

- Registration of the imagery to the Ramsar polygon is correct (marsh complex
  inside the boundary; coastline at the expected grid position).
- Sea/surf zone: elevated NIR (1026–4852 DN) is sediment-rich water, not nodata;
  no zero-observation edge artifacts (cache windows are clipped to the composite
  grid bounds).
- The 2-scene monsoon composite has cloud holes — expected; the per-scene series
  with abstention is the primary instrument.

### 4.2 First-window water extent (2023-10-01 → 2024-03-31)

5 of 13 unique dates passed the 80% gate (8 abstained: 41–77% valid):

| Date | water % of AOI (approx. bbox) | water % of Ramsar RF | valid |
|---|---|---|---|
| 2023-10-07 | 27.9% | **13.9%** | 89% |
| 2024-02-29 | 24.8% | 8.8% | 98% |
| 2024-03-10 | 24.5% | 8.5% | 98% |
| 2024-03-25 | 24.8% | 5.6% | 90% |
| 2024-03-30 | 23.5% | 6.2% | 100% |

Monsoon onset shows the highest water fraction; the dry season the lowest.

### 4.3 Threshold calibration QA (MNDWI sweep, Ramsar polygon)

Within the Ramsar RF the median MNDWI is **−0.17 to −0.26** — the Reserve Forest
is mostly *vegetated* wetland, not open water, so absolute "water" fractions are
strongly threshold-dependent:

| threshold | −0.20 | −0.10 | 0.00 (v0) | +0.10 | +0.20 |
|---|---|---|---|---|---|
| water fraction range over the 5 usable dates | 29–64% | 14–30% | **5.6–13.9%** | 2.1–3.6% | 0.1–0.3% |

The **date ordering is stable across all thresholds** (monsoon date always highest,
dry dates lowest), so the seasonal signal is robust while absolute levels must be
reported with the threshold stated. Artefact:
`processed/water-extent/threshold_sensitivity_2023-10-01_2024-03-31.json`.

### 4.4 Full-record water-extent series (2019-04 → 2026-10)

- **195 unique sensing dates** (2019-04-01 → 2026-10-11); **137 usable** (70%), **58 abstained**
  (30%) on the 80% valid-fraction gate — the abstention rate concentrates in the cloudy
  NE-monsoon quarters, which is exactly where the gate should bite.
- Water fraction within the Ramsar RF (MNDWI > 0): **min 0.2%** (2025-07-08), **max 48.1%**
  (2021-12-16, post-NE-monsoon peak), **mean 11.1%**.
- Seasonal contrast (the robust signal, stable across thresholds per §4.3):
  **NE-monsoon (Oct–Dec) mean 19.5%** (n=20) vs **dry-season (Feb–Apr) mean 10.4%** (n=68) —
  roughly a 2× seasonal cycle over 7.5 years.
- AOI-bbox fractions (with the ocean sliver, see §6) ranged 3.6–36.0% and are reported as
  context only; the Ramsar-polygon series is primary.
- Absolute levels are threshold-dependent (§4.3) and the series is uncalibrated — the
  seasonal *pattern* is the M0-grade result; absolute calibration is the M1 follow-up.

## 5. Evidence artefacts (data root, `processed/water-extent/`)

- `water_extent_2023-10-01_2024-03-31.json` + `.evidence.json` — first window
  (contract status: **valid**; 8 abstained dates recorded in uncertainty).
- `water_extent_2019-04-01_2026-10-31.json` + `.evidence.json` — full record
  (contract status: **valid**; per-date abstentions recorded).
- `threshold_sensitivity_*.json` — QA artefact backing §4.3.

## 6. Limitations (carried into every contract)

1. MNDWI > 0 threshold is **uncalibrated** against reference labels (§4.3
   quantifies the sensitivity); calibration is the first M1 task.
2. AOI fractions use the **approximate** bbox and include a coastal-ocean sliver
   (MNDWI-positive) — the **Ramsar-polygon series is the primary measurement**.
3. Single-scene snapshots per date; no tidal correction; SCL has no dedicated
   shadow class (residual shadow possible).
4. Observation only — **no causal attribution** for any change (ADR-0006);
   abstention is issued whenever coverage/quality is insufficient.

## 7. Reproducibility

```bash
# retrieval (approval-gated; the full record was acquired in quarterly batches)
uv run --project projects/terrascope python -m terrascope.ingestion download \
    --start <YYYY-MM-DD> --end <YYYY-MM-DD> --approve
# water-extent series + evidence contract (offline from cache)
uv run --project projects/terrascope python -m terrascope.ingestion water \
    --start 2019-04-01 --end 2026-10-31
# composites + indices + series + contract
uv run --project projects/terrascope python -m terrascope.ingestion analyse \
    --start <window>
# QA quicklooks / threshold sweep
uv run --project projects/terrascope python projects/terrascope/scripts/render_quicklooks.py \
    <season_dir> <boundary.geojson> <out_prefix>
uv run --project projects/terrascope python projects/terrascope/scripts/water_threshold_sensitivity.py \
    --start 2023-10-01 --end 2024-03-31
# checks
uv run pytest && uv run ruff check .
```

## 8. Storage (data root; budget 10 GB)

| Area | Size |
|---|---|
| `raw/` (as-acquired windows + boundary; 219 scenes, 1,533 checksummed files) | 2,226 MB |
| `processed/` (composites + indices for the QA window, water-extent series + contracts) | 113 MB |
| `exports/` (QA quicklooks) | 5 MB |
| **Total** | **~2.34 GB (23% of the 10 GB budget)** — free space on the data drive: ~213 GB |

## 9. Next steps (M1 candidates)

1. **Threshold calibration** against reference labels (ESA WorldCover 2021 water
   class as a first cross-check; manual QA polygons for marsh-specific classes).
2. First land-cover classification on the winter composite **using the spatial
   block CV scaffolding** (block size 2000 m starting point; variogram check when
   labels exist).
3. Water-extent seasonality analysis with uncertainty (bootstrap over dates),
   plotted against the NE-monsoon record.
4. Broader-marsh context boundary: keep the approximate bbox for context maps only.

## 10. Module map

```
src/terrascope/
  ingestion/   gate | aoi | stac_search | scenes | cog_reader | masking
               | composite | pipeline | __main__ (CLI: status/download/composite/water/analyse)
  features/    indices (NDVI/NDWI/MNDWI/NDBI + seasonal builder)
               | water_extent (series, Ramsar mask, abstention)
  evidence/    water (EvidenceContract builder + writer)
  evaluation/  spatial_cv (SpatialBlockSplitter, validate_splits)
scripts/       render_quicklooks.py | water_threshold_sensitivity.py
tests/         114 offline tests (synthetic fixtures; no network, no data root)
```
