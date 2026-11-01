"""TerraScope evaluation: validation, uncertainty and change-detection metrics.

Status: spatial block CV scaffolding implemented (M0 step 6). Classification
accuracy evaluation and uncertainty quantification build on this module.
"""

from __future__ import annotations

from terrascope.evaluation.spatial_cv import (
    BlockSplit,
    SpatialBlockSplitter,
    block_id_raster,
    validate_splits,
)

__all__ = ["BlockSplit", "SpatialBlockSplitter", "block_id_raster", "validate_splits"]
