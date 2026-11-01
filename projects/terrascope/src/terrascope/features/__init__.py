"""TerraScope features: spectral indices and water-extent analytics.

Status: implemented for M0 step 5 (indices on seasonal composites; per-scene
water-extent time series v0 with cloud-fraction gating and abstention).
"""

from __future__ import annotations

from terrascope.features.indices import mndwi, ndbi, ndvi, ndwi, normalized_difference
from terrascope.features.water_extent import (
    DEFAULT_MNDWI_WATER_THRESHOLD,
    WaterExtentObservation,
    ramsar_mask_on_grid,
    scene_water_extent,
    water_extent_time_series,
)

__all__ = [
    "DEFAULT_MNDWI_WATER_THRESHOLD",
    "WaterExtentObservation",
    "mndwi",
    "ndbi",
    "ndvi",
    "ndwi",
    "normalized_difference",
    "ramsar_mask_on_grid",
    "scene_water_extent",
    "water_extent_time_series",
]
