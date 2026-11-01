# TerraScope Dataset Research

Status: research complete; **first approved acquisitions done (2026-11-01)** — Ramsar boundary
polygon + 14 Sentinel-2 L2A scenes (2023-10 → 2024-03), 261 MB total (see manifest for checksums
and derived products). Sizes marked *(approx.)* require verification at acquisition time.
Machine-readable manifest:
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

## Study-area boundary — investigation result (2026-10-31) and ACQUISITION (2026-11-01, approved)

**Result: the authoritative machine-readable boundary source was verified and then acquired —
the Ramsar Sites Information Service (RSIS).** The polygon is downloaded and checksummed in the
manifest (`raw/boundaries/ramsar_in2481.geojson`; MultiPolygon, valid, measured area
1,246.76 ha vs declared 1,247.54 ha). The original verification findings:

- Site: **Pallikaranai Marsh Reserve Forest, Ramsar Site No. 2481**, designated **8 April 2022**,
  listed area **1,247.54 ha** (shown as 1,247.5 ha on the sheet), centroid 12°55'40"N 80°13'13"E
  (~12.928 N, 80.220 E — consistent with the documented study bbox 80.18–80.28 E, 12.86–12.99 N)
- Site information sheet: https://rsis.ramsar.org/ris/2481 (site map JPG: `IN2481_map220527.jpg`)
- Machine-readable boundary: the sheet's "Site boundaries (GIS file)" link is a WFS GetFeature
  request against the RSIS GeoServer (SHAPE-ZIP output; **GeoJSON also available** — WFS
  GetCapabilities advertises KML/GML2/GML3/SHAPE-ZIP/CSV/JSON):
  `https://rsis.ramsar.org/geoserver/wfs?request=GetFeature&service=wfs&version=1.0.0&typename=ramsar_sdi:features_param_idrvis&viewparams=idrvis:42511262&outputformat=SHAPE-ZIP`
  (use `outputformat=JSON` for GeoJSON). Server reports `Fees: NONE`, `AccessConstraints: NONE`.
- License: **CC BY 4.0** (https://www.ramsar.org/licence-information). Attribution: "Ramsar
  Sites Information Service (rsis.ramsar.org) — Convention on Wetlands (Ramsar Secretariat) /
  Wetlands International (Ramsar Sites Database)".
- To verify at acquisition: geometry type (polygon expected — the link is labelled "Site
  boundaries"; RSIS also distributes centroid points for some sites) and vertex quality.

**Scope caveat (kept permanently in evidence limitations):** the Ramsar polygon is the boundary
of the **Ramsar-listed Reserve Forest only (1,247.54 ha)** — not the full historical marsh
ecosystem (reported historical extent ≈ 80 km², much of it built up today). Consequences:

- All primary measurements and any claim about the Ramsar site use the **authoritative RSIS
  polygon** (once downloaded: status, checksum, acquisition date in the manifest).
- The explicitly labelled **approximate study polygon** stays in use only for broader-marsh
  contextual views; it is never presented as an official or legal wetland boundary, and any
  claim computed with it carries that limitation in `EvidenceContract.limitations`.

Secondary sources (cross-checks, not primary): Protected Planet/WDPA lists the site as
Wetland of International Importance, WDPA ID 555795362 (machine-readable via free
non-commercial registration — backup if RSIS WFS is unavailable). Tamil Nadu State Wetland
Authority publishes no open machine-readable boundary (it references ISRO SAC NWIA/decadal
wetland atlases, distributed as PDF); the TN Forest Department / Care Earth Trust eco-restoration
management plan has boundary and zonation maps in report form only.

## Acquisition order

1. Study-area boundary: Ramsar RSIS WFS polygon (source verified — see caveat section;
   approximate polygon remains the fallback for broader-marsh context)
2. Sentinel-2 L2A (AOI, cloud-filtered, seasonal composites)
3. WorldCover 2021 v200 subset
4. OSM roads/buildings (AOI)
5. Optional later: Dynamic World, JRC GSW subsets

## Storage discipline

- Budget: ≤ 10 GB total for TerraScope initially; no single download > 500 MB without approval
- Structure: `raw/` (as-acquired) → `interim/` → `processed/` → `exports/`; models in `models/`
- Checksums + acquisition dates recorded in the manifest at download time; duplicates avoided
  by hashing before persisting
