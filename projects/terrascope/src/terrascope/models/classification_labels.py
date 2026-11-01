"""Weak label generation from a WorldCover-style class raster (M1 T3).

A 20 m cell receives the **dominant class** when a single class covers at
least half of its native-resolution pixels (per-class fraction via average
resampling of one-hot masks, then argmax). Mixed cells (no majority) and
cells the raster does not cover are unlabelled and excluded from training.

These labels are explicitly weak: single-epoch product, native 10 m grid,
"classes" from a global mapping product — not ground truth.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject as rasterio_reproject
from rasterio.windows import transform as window_transform

from terrascope.ingestion.cog_reader import CompositeGrid, window_covering_bounds

__all__ = ["dominant_class_raster"]

_UNCLASSIFIED = -1


def dominant_class_raster(
    class_raster_path: Path,
    grid: CompositeGrid,
    class_codes: tuple[int, ...],
    *,
    min_majority_fraction: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(labels, labelled)`` on *grid*.

    ``labels`` holds the winning class code per cell (``_UNCLASSIFIED`` where
    no majority) and ``labelled`` marks cells usable for training (covered by
    the raster AND carrying a majority class).
    """
    fractions = np.empty((len(class_codes), *grid.shape), dtype=np.float32)
    covered = np.zeros(grid.shape, dtype=bool)
    with rasterio.open(class_raster_path) as dataset:
        window = window_covering_bounds(dataset, grid.bounds, grid.crs_epsg)
        source = dataset.read(1, window=window)
        src_transform = window_transform(window, dataset.transform)
        for index, code in enumerate(class_codes):
            destination = np.full(grid.shape, -1.0, dtype=np.float32)
            rasterio_reproject(
                source=(source == code).astype(np.float32),
                destination=destination,
                src_transform=src_transform,
                src_crs=dataset.crs,
                src_nodata=None,
                dst_transform=grid.transform,
                dst_crs=f"EPSG:{grid.crs_epsg}",
                dst_nodata=-1.0,
                resampling=Resampling.average,
            )
            fractions[index] = destination
            covered |= destination >= 0.0

    valid = covered & np.isfinite(fractions).all(axis=0)
    winner = np.argmax(fractions, axis=0)
    winner_fraction = np.max(fractions, axis=0)
    labels = np.full(grid.shape, _UNCLASSIFIED, dtype=np.int16)
    majority = valid & (winner_fraction >= min_majority_fraction)
    labels[majority] = np.array(class_codes, dtype=np.int16)[winner[majority]]
    return labels, majority
