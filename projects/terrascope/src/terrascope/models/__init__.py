"""TerraScope models: land-cover classification (spatial block CV only).

Status: implemented for M1 task T3 — random-forest classification of the
winter composite with WorldCover-derived labels and
:class:`terrascope.evaluation.spatial_cv.SpatialBlockSplitter` folds.
"""

from __future__ import annotations

from terrascope.models.classification import (
    ClassificationConfig,
    ClassificationReport,
    classify_composite,
)

__all__ = ["ClassificationConfig", "ClassificationReport", "classify_composite"]
