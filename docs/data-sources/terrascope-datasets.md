# TerraScope Dataset Research

Status: research complete for prioritization; **nothing downloaded yet**. Sizes marked
*(approx.)* require verification at acquisition time. Machine-readable manifest:
[`data/manifests/terrascope-manifest.yaml`](../../data/manifests/terrascope-manifest.yaml).

Study area: **Pallikaranai Marsh, Chennai, Tamil Nadu, India** — approx. bbox
80.18–80.28 E, 12.86–12.99 N (EPSG:4326). UTM zone 44N. Exact MGRS tiles covering the AOI are
to be confirmed via the first STAC search (do not assume a tile ID).

## Priority 1 — Sentinel-2 Level-2A (Microsoft Planetary Computer)

- Provider/collection: `sentinel-2-l2a` on Microsoft Planetary Computer STAC
- License: CC-BY-4.0 (attribution: ESA / Copernicus; via MPC terms — confirm exact attribution
  string at acquisition)
- Content: surface reflectance + Scene Classification Layer (SCL), COGs on Azure blob storage;
  band-by-band assets, so **windowed reads retrieve only the AOI**
- Tooling: `pystac-client` (search: bbox + datetime + `eo:cloud_cover` query), `planetary-computer`
  (request signing), `rasterio` (windowed COG reads), GeoPandas/Shapely (AOI), xarray where useful
- Bands: B02, B03, B04, B08 (10 m), B11, B12, SCL (20 m — account for resolution differences)
- Method: cloud-cover filter (≤ 20% target) → SCL masking (exclude 0,1,3,8,9,10,11) → seasonal
  median composites
- Size estimate: Pallikaranai window ≈ 15×15 km. Per scene per band: 10 m band ≈ 1500×1500 px
  ≈ 4–9 MB uncompressed uint16; 20 m bands ≈ 1–3 MB. With ~6–10 scenes per season after
  filtering across 2019→present, **storage ≈ 1–3 GB (approx.)** — well inside the 10 GB budget
- Known limitations: L2A availability/backfill varies by region; SCL misclassification at
  shadow/cirrus boundaries; reprocessing baselines change products over time (record baseline
  per scene)

## Priority 2 — ESA WorldCover 2021 v200

- Source: https://esa-worldcover.org/en/data-access (also on Planetary Computer as
  `esa-worldcover` — verify which access path at acquisition)
- License: CC-BY-4.0 (ESA)
- Content: 10 m global land cover, 11 classes, tiles of 3×3°; retrieve **AOI subset only** —
  never the global map
- Size estimate: AOI crop ≈ 10–50 MB (approx.)
- Limitations: single epoch (2021); v100 (2020) exists but uses different versions of the
  algorithm — cross-product comparisons must document version differences; useful as reference
  labels / sanity checks, not as a change-measurement instrument

## Priority 3 — OpenStreetMap (roads + building footprints)

- Source: Overpass API (AOI query) or Geofabrik extract clipped locally; avoid downloading the
  full India extract (~1–2 GB) — prefer AOI-bounded Overpass queries
- License: ODbL 1.0, attribution "© OpenStreetMap contributors" (must appear in products)
- Use: built-up context for classification validation; proximity features
- Size estimate: AOI extract < 50 MB (approx.)
- Limitations: completeness varies; OSM is not a land-cover source

## Priority 4 — Dynamic World (optional)

- Source: Google Earth Engine (`GOOGLE/DYNAMICWORLD/V1`), 10 m near-real-time LULC
- Access requirement: **GEE account + authenticated `ee` Python session** — treat as an
  optional extension, not a dependency of the first working pipeline
- License: CC-BY-4.0
- Use: probability surfaces as a comparison layer for our own classification
- Limitations: GEE auth/config is an external dependency; export via GEE, not bulk download

## Priority 5 — JRC Global Surface Water

- Source: https://global-surface-water.appspot.com / JRC GSW v1.4 (also via GEE and direct
  GeoTIFF tiles — verify access path at acquisition)
- License: free/open (citation: Pekel et al., Nature 2016)
- Content: water occurrence/change intensity 1984→present, 30 m — retrieve only the AOI tiles
- Use: historical water-context baseline for water-extent analysis
- Limitations: 30 m resolution is coarse vs Sentinel-2's 10 m; product epochs are periodic, not
  continuous

## Study-area boundary (important caveat)

No authoritative machine-readable Pallikaranai wetland boundary has been verified yet.
Action item (first ingestion task): investigate Tamil Nadu Wetlands Authority / Tamil Nadu
Forest Department / Ramsar Sites Information Service (Pallikaranai is reported as a Ramsar site
since 2022 — verify at rsis.ramsar.org). Until then:

- Use an explicitly labelled **approximate study boundary** (digitized from referenced
  open sources; provenance + method recorded in the manifest)
- **Never** present the approximate polygon as an official legal wetland boundary
- Any claim computed with the approximate boundary carries that limitation in its
  `EvidenceContract.limitations`

## Acquisition order

1. Study-area boundary (investigate authoritative sources; else approximate polygon)
2. Sentinel-2 L2A (AOI, cloud-filtered, seasonal composites)
3. WorldCover 2021 v200 subset
4. OSM roads/buildings (AOI)
5. Optional later: Dynamic World, JRC GSW subsets

## Storage discipline

- Budget: ≤ 10 GB total for TerraScope initially; no single download > 500 MB without approval
- Structure: `raw/` (as-acquired) → `interim/` → `processed/` → `exports/`; models in `models/`
- Checksums + acquisition dates recorded in the manifest at download time; duplicates avoided
  by hashing before persisting
