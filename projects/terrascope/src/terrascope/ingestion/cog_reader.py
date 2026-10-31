"""AOI-bounded windowed reads from Cloud Optimized GeoTIFFs.

Two access patterns share this module:

* **Native window read** (:func:`read_asset_window`) — reads only the AOI
  window at the asset's own grid, exactly as served. Used by the download
  stage to persist as-acquired windows on the data root.
* **Grid-aligned read** (:func:`read_band_onto_grid` / :func:`read_scl_onto_grid`)
  — windowed read followed by reprojection onto a fixed
  :class:`CompositeGrid`, so every scene lands on identical pixels before
  stacking. Windowed reading happens *first*: only the AOI window is
  transferred from remote storage, never a full scene.

All remote access passes through the :class:`~terrascope.ingestion.gate.DownloadGate`.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import numpy as np
import rasterio
from affine import Affine
from pyproj import CRS as PyCRS
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.errors import WindowError
from rasterio.warp import reproject as rasterio_reproject
from rasterio.windows import Window, from_bounds
from rasterio.windows import transform as window_transform

from terrascope.ingestion.aoi import STUDY_CRS_EPSG, StudyAOI
from terrascope.ingestion.gate import DownloadGate

__all__ = [
    "CompositeGrid",
    "WindowRead",
    "read_asset_window",
    "read_band_onto_grid",
    "read_bounds_window",
    "read_scl_onto_grid",
]


@dataclass(frozen=True)
class CompositeGrid:
    """Fixed analysis grid (origin-snapped to the resolution, axis-aligned).

    Every scene window is reprojected onto this grid before stacking, so
    seasonal composites compare identical pixels across scenes.
    """

    crs_epsg: int
    transform: Affine
    width: int
    height: int
    resolution_m: float

    @classmethod
    def from_aoi(
        cls,
        aoi: StudyAOI,
        *,
        resolution_m: float,
        epsg: int = STUDY_CRS_EPSG,
    ) -> CompositeGrid:
        """Build a grid covering *aoi* with the origin snapped down to *resolution_m*."""
        geometry = aoi.geometry_in_crs(epsg)
        minx, miny, maxx, maxy = geometry.bounds
        snapped_minx = math.floor(minx / resolution_m) * resolution_m
        snapped_miny = math.floor(miny / resolution_m) * resolution_m
        snapped_maxx = math.ceil(maxx / resolution_m) * resolution_m
        snapped_maxy = math.ceil(maxy / resolution_m) * resolution_m
        width = int(round((snapped_maxx - snapped_minx) / resolution_m))
        height = int(round((snapped_maxy - snapped_miny) / resolution_m))
        if width <= 0 or height <= 0:
            msg = f"Degenerate grid for AOI bounds {(minx, miny, maxx, maxy)!r}"
            raise ValueError(msg)
        transform = Affine(resolution_m, 0, snapped_minx, 0, -resolution_m, snapped_maxy)
        return cls(
            crs_epsg=epsg,
            transform=transform,
            width=width,
            height=height,
            resolution_m=resolution_m,
        )

    def at_resolution(self, factor: int) -> CompositeGrid:
        """Coarsened grid (``factor=2`` turns the 10 m grid into the 20 m grid)."""
        if factor < 1:
            msg = f"factor must be >= 1, got {factor}"
            raise ValueError(msg)
        resolution = self.resolution_m * factor
        return CompositeGrid(
            crs_epsg=self.crs_epsg,
            transform=Affine(resolution, 0, self.transform.c, 0, -resolution, self.transform.f),
            width=int(math.ceil(self.width / factor)),
            height=int(math.ceil(self.height / factor)),
            resolution_m=resolution,
        )

    @property
    def shape(self) -> tuple[int, int]:
        """``(height, width)`` of grid-aligned arrays."""
        return (self.height, self.width)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """``(left, bottom, right, top)`` in the grid CRS."""
        left = self.transform.c
        top = self.transform.f
        bottom = top - self.height * self.resolution_m
        right = left + self.width * self.resolution_m
        return (left, bottom, right, top)


@dataclass(frozen=True)
class WindowRead:
    """One band window as served on the asset's native grid."""

    band: str
    array: np.ndarray  # 2D, native dtype
    transform: Affine
    crs_epsg: int
    nodata: float | None
    resolution_m: float


def _openable_href(href: str) -> str:
    """Normalise ``file://`` URIs to plain paths (GDAL mangles them on Windows);
    remote URIs and plain paths pass through unchanged."""
    parsed = urlparse(href)
    if parsed.scheme == "file":
        path = unquote(parsed.path)
        if parsed.netloc and parsed.netloc not in ("", "localhost"):
            path = f"//{parsed.netloc}{path}"  # UNC share
        return url2pathname(path) if os.name == "nt" else path
    return href


def _window_covering(
    dataset: rasterio.DatasetReader,
    bounds: tuple[float, float, float, float],
    bounds_epsg: int,
) -> Window:
    """Window of *dataset* covering *bounds* (reprojected if needed), clipped in-raster.

    Raises:
        ValueError: If the requested extent does not overlap the dataset — an
            upstream logic error (STAC search guarantees overlap).
    """
    left, bottom, right, top = bounds
    dataset_epsg = dataset.crs.to_epsg() if dataset.crs is not None else None
    if dataset_epsg is not None and dataset_epsg != bounds_epsg:
        transformer = Transformer.from_crs(bounds_epsg, dataset_epsg, always_xy=True)
        left, bottom, right, top = transformer.transform_bounds(left, bottom, right, top)
    window = from_bounds(left, bottom, right, top, transform=dataset.transform)
    full = Window(0, 0, dataset.width, dataset.height)
    try:
        clipped = window.intersection(full)
    except WindowError as exc:
        msg = (
            f"Requested extent {bounds!r} (EPSG:{bounds_epsg}) does not overlap "
            f"dataset {dataset.name!r} (EPSG:{dataset_epsg})"
        )
        raise ValueError(msg) from exc
    if clipped.width <= 0 or clipped.height <= 0:
        msg = (
            f"Requested extent {bounds!r} (EPSG:{bounds_epsg}) does not overlap "
            f"dataset {dataset.name!r} (EPSG:{dataset_epsg})"
        )
        raise ValueError(msg)
    return clipped


def read_bounds_window(
    href: str,
    band: str,
    bounds: tuple[float, float, float, float],
    bounds_epsg: int,
    gate: DownloadGate,
) -> WindowRead:
    """Read the window of one band asset covering *bounds* (native asset grid).

    Remote hrefs pass through *gate*; local files (cached windows, fixtures)
    are always allowed.
    """
    gate.require(href, f"windowed read of band {band}")
    with rasterio.open(_openable_href(href)) as dataset:
        # _window_covering reprojects *bounds* into the dataset CRS when
        # needed, then clips the window to the raster.
        window = _window_covering(dataset, bounds, bounds_epsg)
        array = dataset.read(1, window=window)
        read_transform = window_transform(window, dataset.transform)
        resolution = float(dataset.res[0])
        nodata = dataset.nodata
        crs_epsg = dataset.crs.to_epsg() or 4326
    return WindowRead(
        band=band,
        array=array,
        transform=read_transform,
        crs_epsg=crs_epsg,
        nodata=nodata,
        resolution_m=resolution,
    )


def read_asset_window(
    href: str, band: str, aoi: StudyAOI, gate: DownloadGate
) -> WindowRead:
    """Read the AOI window of one band asset at its native grid (as served)."""
    return read_bounds_window(href, band, aoi.geometry_wgs84.bounds, 4326, gate)


def _read_onto_grid(
    href: str,
    purpose: str,
    grid: CompositeGrid,
    gate: DownloadGate,
    *,
    resampling: Resampling,
    out_dtype: np.dtype | type,
    out_nodata: float,
) -> np.ndarray:
    """Windowed read of one asset, reprojected onto *grid* (shared engine)."""
    gate.require(href, purpose)
    grid_crs = PyCRS.from_epsg(grid.crs_epsg)
    destination = np.full(grid.shape, out_nodata, dtype=out_dtype)
    with rasterio.open(_openable_href(href)) as dataset:
        window = _window_covering(dataset, grid.bounds, grid.crs_epsg)
        source = dataset.read(1, window=window)
        source_transform = window_transform(window, dataset.transform)
        rasterio_reproject(
            source=source,
            destination=destination,
            src_transform=source_transform,
            src_crs=dataset.crs,
            src_nodata=dataset.nodata,
            dst_transform=grid.transform,
            dst_crs=grid_crs,
            dst_nodata=out_nodata,
            resampling=resampling,
        )
    return destination


def read_band_onto_grid(
    href: str, band: str, grid: CompositeGrid, gate: DownloadGate
) -> np.ndarray:
    """Reflectance band as float32 on *grid*, NaN where nodata.

    Bilinear resampling handles sub-pixel grid offsets between scenes; the
    seasonal median compositing then operates on valid observations only.
    """
    plane = _read_onto_grid(
        href,
        f"grid-aligned read of band {band}",
        grid,
        gate,
        resampling=Resampling.bilinear,
        out_dtype=np.float32,
        out_nodata=0.0,
    )
    plane[plane == 0.0] = np.nan  # L2A nodata is 0 DN; NaN is the compositing convention
    return plane


def read_scl_onto_grid(href: str, grid: CompositeGrid, gate: DownloadGate) -> np.ndarray:
    """SCL as uint8 on the (coarser) grid, nearest-neighbour resampling.

    SCL nodata is class 0, which the masking default excludes anyway, so no
    NaN conversion happens for the categorical layer.
    """
    return _read_onto_grid(
        href,
        "grid-aligned read of SCL",
        grid,
        gate,
        resampling=Resampling.nearest,
        out_dtype=np.uint8,
        out_nodata=0,
    )
