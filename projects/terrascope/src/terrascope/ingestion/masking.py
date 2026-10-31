"""Scene Classification Layer (SCL) masking for Sentinel-2 L2A.

Sen2Cor SCL classes (official ESA Sentinel-2 table):

===  ==========================
0    No data
1    Saturated / defective
2    Dark area pixels
3    Cloud medium probability
4    Vegetation
5    Not vegetated
6    Water
7    Unclassified
8    Cloud medium probability
9    Cloud high probability
10   Thin cirrus
11   Snow / ice
===  ==========================

There is **no dedicated cloud-shadow class**: shadow pixels typically classify
as 2 (dark area pixels). The processing default (``configs/processing.example.yaml``
+ architecture doc) excludes ``0, 1, 3, 8, 9, 10, 11`` — nodata, saturated,
cloud medium/high probability, thin cirrus, snow — and retains class 2 pending
visual QA at first real-data ingestion (to be revisited there: retaining class
2 keeps some shadows; excluding it would also drop wet/dark marsh pixels).
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "SCL_EXCLUDE_DEFAULT",
    "apply_mask",
    "scl_valid_mask",
    "upscale_mask_nearest",
    "valid_fraction",
]

#: SCL classes excluded from composites (nodata, saturated, cloud shadow,
#: cloud medium/high, thin cirrus, snow).
SCL_EXCLUDE_DEFAULT = frozenset({0, 1, 3, 8, 9, 10, 11})


def scl_valid_mask(
    scl: np.ndarray, exclude: frozenset[int] | set[int] = SCL_EXCLUDE_DEFAULT
) -> np.ndarray:
    """Return a boolean mask: True where the SCL pixel is *valid* for analysis.

    Args:
        scl: 2D uint8 SCL array.
        exclude: SCL classes treated as invalid (cloud, shadow, nodata, ...).

    Returns:
        Boolean array of the same shape; True = keep the observation.
    """
    scl = np.asarray(scl)
    if scl.ndim != 2:
        msg = f"Expected a 2D SCL array, got shape {scl.shape}"
        raise ValueError(msg)
    excluded = np.isin(scl, list(exclude))
    return ~excluded


def upscale_mask_nearest(mask: np.ndarray, factor: int) -> np.ndarray:
    """Upscale a boolean mask by integer *factor* using nearest-neighbour repeat.

    Used to apply the 20 m SCL mask to 10 m band arrays (each 20 m mask pixel
    covers exactly 2x2 = 4 ten-metre pixels). Documented processing default;
    revisit if sub-pixel cloud edges become an issue at visual QA.
    """
    if factor < 1 or factor != int(factor):
        msg = f"factor must be a positive integer, got {factor!r}"
        raise ValueError(msg)
    return np.repeat(np.repeat(mask, factor, axis=0), factor, axis=1)


def apply_mask(
    array: np.ndarray, valid_mask: np.ndarray, *, fill: float = np.nan
) -> np.ndarray:
    """Return *array* as float32 with invalid pixels set to *fill* (default NaN).

    The float32 + NaN convention is the internal compositing representation;
    raw DN values are preserved where valid.
    """
    array = np.asarray(array)
    if array.shape != valid_mask.shape:
        msg = f"Array shape {array.shape} does not match mask shape {valid_mask.shape}"
        raise ValueError(msg)
    return np.where(valid_mask, array.astype(np.float32), np.float32(fill))


def valid_fraction(
    scl: np.ndarray, exclude: frozenset[int] | set[int] = SCL_EXCLUDE_DEFAULT
) -> float:
    """Fraction of SCL pixels that are valid (not in *exclude*) — scene QA metric.

    The pipeline records this per scene; pixels below the configured
    ``min_cloud_free_fraction`` trigger abstention in downstream evidence
    (M0 step 5 wires that into the evidence contracts).
    """
    mask = scl_valid_mask(scl, exclude)
    if mask.size == 0:
        msg = "Cannot compute valid_fraction of an empty array"
        raise ValueError(msg)
    return float(np.count_nonzero(mask)) / float(mask.size)
