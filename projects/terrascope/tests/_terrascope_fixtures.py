"""Synthetic scene builders for TerraScope ingestion tests (offline helpers).

Uniquely named (``_terrascope_fixtures``) so it can be imported top-level by
the TerraScope test modules without colliding with other packages' test
helpers in the monorepo. Everything is offline: scenes are tiny local GeoTIFFs
written with rasterio; STAC items are real ``pystac`` objects in memory whose
asset hrefs point at those local files.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pystac
import rasterio
from affine import Affine
from pyproj import Transformer

from terrascope.ingestion.aoi import StudyAOI

UTC = dt.UTC

# Synthetic scene geometry: a 1000 m x 1000 m extent at EPSG:32644.
SCENE_LEFT = 500_000.0
SCENE_TOP = 1_430_000.0
RES_10M = 10.0
RES_20M = 20.0
DIMS_10M = 100  # 100 x 100 px at 10 m
DIMS_20M = 50  # 50 x 50 px at 20 m (same extent)

CRS = "EPSG:32644"
TRANSFORM_10M = Affine(RES_10M, 0, SCENE_LEFT, 0, -RES_10M, SCENE_TOP)
TRANSFORM_20M = Affine(RES_20M, 0, SCENE_LEFT, 0, -RES_20M, SCENE_TOP)

#: Deterministic DN per band name (``hash()`` is salted per process — never
#: use it for fixture data; tests must be reproducible run to run).
BAND_BASE_VALUES: dict[str, float] = {
    "B02": 1000.0,
    "B03": 1500.0,
    "B04": 2000.0,
    "B08": 4000.0,
    "B11": 2500.0,
    "B12": 1800.0,
}


def write_band(path: Path, array: np.ndarray, transform: Affine, *, nodata: int = 0) -> Path:
    """Write a single-band GeoTIFF fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=array.dtype,
        crs=CRS,
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(array, 1)
    return path


def make_scl(shapes: list[tuple[int, int, int]], dims: int = DIMS_20M) -> np.ndarray:
    """SCL raster: background class 4 (vegetation) with (value, row, col) 4x4 patches."""
    scl = np.full((dims, dims), 4, dtype=np.uint8)
    for value, row, col in shapes:
        scl[row : row + 4, col : col + 4] = value
    return scl


def make_scene_fixture(
    scene_dir: Path,
    *,
    scl_classes: list[tuple[int, int, int]] | None = None,
    band_values: dict[str, float] | None = None,
    band_patches: dict[str, tuple[int, int, int, int, float]] | None = None,
    grid_offset_m: float = 0.0,
) -> dict[str, str]:
    """Write one synthetic scene (6 bands + SCL) and return band -> file URI.

    ``grid_offset_m`` shifts the raster origin so grid-alignment code paths
    are exercised (a half-pixel offset mimics scene-to-scene drift).
    ``band_patches`` overrides a constant band inside one rectangle:
    ``{band: (row, col, height_px, width_px, value)}`` in the band's own
    resolution — used to plant e.g. a dark-SWIR water block aligned to the
    20 m grid (rows/cols must be multiples of 2 for 10 m bands).
    """
    band_values = band_values or {}
    band_patches = band_patches or {}
    offset = Affine(1, 0, grid_offset_m, 0, 1, -grid_offset_m)
    hrefs: dict[str, str] = {}

    scl = make_scl(scl_classes or [])
    hrefs["SCL"] = write_band(scene_dir / "SCL.tif", scl, TRANSFORM_20M @ offset).as_uri()

    for band, dims, transform in (
        ("B02", DIMS_10M, TRANSFORM_10M),
        ("B03", DIMS_10M, TRANSFORM_10M),
        ("B04", DIMS_10M, TRANSFORM_10M),
        ("B08", DIMS_10M, TRANSFORM_10M),
        ("B11", DIMS_20M, TRANSFORM_20M),
        ("B12", DIMS_20M, TRANSFORM_20M),
    ):
        value = band_values.get(band, BAND_BASE_VALUES[band])
        array = np.full((dims, dims), value, dtype=np.uint16)
        if band in band_patches:
            row, col, height_px, width_px, patch_value = band_patches[band]
            array[row : row + height_px, col : col + width_px] = np.uint16(patch_value)
        hrefs[band] = write_band(scene_dir / f"{band}.tif", array, transform @ offset).as_uri()
    return hrefs


def make_stac_item(
    scene_id: str,
    acquired: dt.datetime,
    band_hrefs: dict[str, str],
    *,
    cloud_cover: float = 5.0,
    aoi_bbox: tuple[float, float, float, float] = (80.18, 12.86, 80.28, 12.99),
) -> pystac.Item:
    """Build a real in-memory ``pystac.Item`` (offline) with band assets."""
    item = pystac.Item(
        id=scene_id,
        geometry={
            "type": "Polygon",
            "coordinates": [
                [
                    [aoi_bbox[0], aoi_bbox[1]],
                    [aoi_bbox[2], aoi_bbox[1]],
                    [aoi_bbox[2], aoi_bbox[3]],
                    [aoi_bbox[0], aoi_bbox[3]],
                    [aoi_bbox[0], aoi_bbox[1]],
                ]
            ],
        },
        bbox=list(aoi_bbox),
        datetime=acquired,
        properties={
            "eo:cloud_cover": cloud_cover,
            "proj:epsg": 32644,
            "grid:code": "MGRS-44QPH",
        },
    )
    for band, href in band_hrefs.items():
        item.add_asset(band, pystac.Asset(href=href))
    return item


def central_aoi() -> StudyAOI:
    """AOI covering the central 400 m x 400 m of the synthetic scene extent."""
    from terrascope.ingestion.aoi import aoi_from_bbox

    transformer = Transformer.from_crs(32644, 4326, always_xy=True)
    left, bottom, right, top = (
        SCENE_LEFT + 300,
        SCENE_TOP - 700,
        SCENE_LEFT + 700,
        SCENE_TOP - 300,
    )
    (lon_min, lon_max), (lat_min, lat_max) = transformer.transform([left, right], [bottom, top])
    return aoi_from_bbox((lon_min, lat_min, lon_max, lat_max), name="synthetic central AOI")
