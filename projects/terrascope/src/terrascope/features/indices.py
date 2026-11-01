"""Normalized-difference spectral indices (Sentinel-2 L2A bands).

All functions take float32 arrays with the NaN-invalid convention used across
TerraScope (see ``terrascope.ingestion.masking``) and return float32 with NaN
where the index is undefined (invalid inputs or near-zero denominator).

Indices (band pairs at native pair resolution):

* NDVI  = (B08 - B04) / (B08 + B04)   vegetation @ 10 m
* NDWI  = (B03 - B08) / (B03 + B08)   open water (McFeeters) @ 10 m
* MNDWI = (B03 - B11) / (B03 + B11)   water incl. built-up suppression
  (Xu 2006) — computed at 20 m (B11 resolution)
* NDBI  = (B11 - B08) / (B11 + B08)   built-up (Zha 2003) @ 20 m
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

__all__ = ["build_season_indices", "mndwi", "ndbi", "ndvi", "ndwi", "normalized_difference"]

_DENOM_EPS = 1e-6


def normalized_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """``(a - b) / (a + b)`` with NaN propagation and zero-denominator guard."""
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    if a.shape != b.shape:
        msg = f"Band shape mismatch: {a.shape} vs {b.shape}"
        raise ValueError(msg)
    denominator = a + b
    with np.errstate(invalid="ignore", divide="ignore"):
        index = (a - b) / denominator
    index[np.abs(denominator) < _DENOM_EPS] = np.nan
    return index.astype(np.float32)


def ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    """NDVI = (NIR - Red) / (NIR + Red) — Sentinel-2 B08 / B04."""
    return normalized_difference(nir, red)


def ndwi(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """NDWI = (Green - NIR) / (Green + NIR) — Sentinel-2 B03 / B08."""
    return normalized_difference(green, nir)


def mndwi(green: np.ndarray, swir1: np.ndarray) -> np.ndarray:
    """MNDWI = (Green - SWIR1) / (Green + SWIR1) — Sentinel-2 B03 / B11."""
    return normalized_difference(green, swir1)


def ndbi(swir1: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """NDBI = (SWIR1 - NIR) / (SWIR1 + NIR) — Sentinel-2 B11 / B08."""
    return normalized_difference(swir1, nir)


def build_season_indices(season_dir: Path) -> dict[str, Path]:
    """Compute and persist index rasters for one seasonal composite directory.

    Reads the median composites written by ``run_composite`` (``<band>_median.tif``
    plus ``provenance.json`` for the grid), computes NDVI/NDWI at 10 m and
    MNDWI/NDBI at 20 m (SWIR1 resolution; the 10 m bands are bilinearly
    re-projected onto the 20 m grid by the grid-aligned readers), and writes
    ``<index>_median.tif`` next to the composites.
    """
    import rasterio
    from affine import Affine

    from terrascope.ingestion.cog_reader import CompositeGrid, read_band_onto_grid
    from terrascope.ingestion.gate import DownloadGate

    provenance = json.loads((season_dir / "provenance.json").read_text(encoding="utf-8"))
    grid_info = provenance["grid"]
    grid10 = CompositeGrid(
        crs_epsg=int(grid_info["crs"].split(":")[1]),
        transform=Affine(*grid_info["transform"][:6]),
        width=grid_info["width"],
        height=grid_info["height"],
        resolution_m=grid_info["resolution_m"],
    )
    grid20 = grid10.at_resolution(2)
    gate = DownloadGate()  # local composite files only

    def _median(band: str, grid: CompositeGrid) -> np.ndarray:
        path = season_dir / f"{band}_median.tif"
        return read_band_onto_grid(str(path), band, grid, gate)

    red, green, nir = _median("B04", grid10), _median("B03", grid10), _median("B08", grid10)
    green20, swir120, nir20 = _median("B03", grid20), _median("B11", grid20), _median("B08", grid20)

    products = {
        "ndvi": (ndvi(nir, red), grid10),
        "ndwi": (ndwi(green, nir), grid10),
        "mndwi": (mndwi(green20, swir120), grid20),
        "ndbi": (ndbi(swir120, nir20), grid20),
    }
    out_paths: dict[str, Path] = {}
    for name, (array, grid) in products.items():
        out_path = season_dir / f"{name}_median.tif"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(
            out_path,
            "w",
            driver="COG",
            height=grid.height,
            width=grid.width,
            count=1,
            dtype="float32",
            crs=f"EPSG:{grid.crs_epsg}",
            transform=grid.transform,
            nodata=float("nan"),
            compress="deflate",
            blocksize=512,
        ) as dst:
            dst.write(array, 1)
        out_paths[name] = out_path
    return out_paths
