"""Spatial block cross-validation (ADR-0006).

Random pixel splits are leakage under spatial autocorrelation: neighbouring
pixels share calibration conditions, so random folds fabricate accuracy. Every
TerraScope classification evaluation must use spatially **disjoint block
folds** produced by :class:`SpatialBlockSplitter` — a random split in
evaluation code is a blocking review defect.

Design:

* Pixels are partitioned into square blocks (``block_size_px`` on a side);
  block IDs are deterministic (row-major).
* Blocks are assigned to folds by ``(block_row + block_col) % n_folds`` — a
  fixed diagonal pattern that spreads every fold across the scene without any
  randomness (two runs give identical folds; a seed is deliberately absent).
* Each pixel is a test pixel in exactly one fold; a fold's training pixels are
  never in its test blocks.
* :func:`validate_splits` re-checks the partition invariants and raises on any
  violation — including folds constructed by hand (guards against future code
  bypassing the splitter).

Block size choice (``configs/processing.example.yaml``: 2000 m starting point)
should be revisited via a variogram check when labelled data exists; larger
blocks are more conservative.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "BlockSplit",
    "SpatialBlockSplitter",
    "block_id_raster",
    "block_size_pixels",
    "validate_splits",
]


def block_size_pixels(block_size_m: float, resolution_m: float) -> int:
    """Convert a block edge length in metres to whole pixels (rounded up)."""
    if block_size_m <= 0 or resolution_m <= 0:
        msg = "block_size_m and resolution_m must be positive"
        raise ValueError(msg)
    return max(1, int(np.ceil(block_size_m / resolution_m)))


def block_id_raster(height: int, width: int, block_size_px: int) -> np.ndarray:
    """Deterministic row-major block IDs for an ``(height, width)`` pixel grid.

    Every ``block_size_px x block_size_px`` square shares one ID; edge blocks
    may be smaller. ID = ``block_row * n_block_cols + block_col``.
    """
    if block_size_px < 1:
        msg = f"block_size_px must be >= 1, got {block_size_px}"
        raise ValueError(msg)
    block_rows = np.arange(height) // block_size_px
    block_cols = np.arange(width) // block_size_px
    return (block_rows[:, None] * int(np.ceil(width / block_size_px)) + block_cols[None, :]).astype(
        np.int64
    )


@dataclass(frozen=True)
class BlockSplit:
    """One fold: the test blocks and the flattened pixel index arrays."""

    fold: int
    test_block_ids: tuple[int, ...]
    train_indices: np.ndarray  # int64, flattened row-major indices
    test_indices: np.ndarray


class SpatialBlockSplitter:
    """Deterministic spatially disjoint block folds over a pixel grid."""

    def __init__(self, *, height: int, width: int, block_size_px: int, n_folds: int):
        if height < 1 or width < 1:
            msg = f"Grid must be non-empty, got {height}x{width}"
            raise ValueError(msg)
        if n_folds < 2:
            msg = f"n_folds must be >= 2, got {n_folds}"
            raise ValueError(msg)
        self.height = height
        self.width = width
        self.block_size_px = block_size_px
        self.n_folds = n_folds
        self._block_raster = block_id_raster(height, width, block_size_px)

    @property
    def block_raster(self) -> np.ndarray:
        """Block ID per pixel (deterministic)."""
        return self._block_raster

    def splits(self) -> list[BlockSplit]:
        """All folds, deterministically assigned via ``(row + col) % n_folds``."""
        block_ids = np.unique(self._block_raster)
        n_block_cols = int(np.ceil(self.width / self.block_size_px))
        splits: list[BlockSplit] = []
        for fold in range(self.n_folds):
            test_blocks = tuple(
                int(block_id)
                for block_id in block_ids
                if (block_id // n_block_cols + block_id % n_block_cols) % self.n_folds == fold
            )
            if not test_blocks:
                msg = (
                    f"Fold {fold} received no blocks (n_folds={self.n_folds} too large "
                    f"for {len(block_ids)} blocks); reduce n_folds or shrink blocks."
                )
                raise ValueError(msg)
            test_mask = np.isin(self._block_raster, test_blocks)
            test_indices = np.flatnonzero(test_mask)
            train_indices = np.flatnonzero(~test_mask)
            splits.append(
                BlockSplit(
                    fold=fold,
                    test_block_ids=test_blocks,
                    train_indices=train_indices,
                    test_indices=test_indices,
                )
            )
        return splits


def validate_splits(splits: list[BlockSplit], block_raster: np.ndarray) -> None:
    """Re-check the spatial-CV invariants; raise :class:`ValueError` on violation.

    Invariants:

    1. Each pixel appears in exactly one fold's test set.
    2. Within a fold, train and test indices are disjoint.
    3. Within a fold, the test set is block-contiguous (all pixels of any
       block it touches belong to the test set — no partial blocks).
    """
    if not splits:
        msg = "No folds to validate"
        raise ValueError(msg)
    n_pixels = block_raster.size
    seen_test = np.zeros(n_pixels, dtype=bool)
    for split in splits:
        if np.any(seen_test[split.test_indices]):
            msg = f"Fold {split.fold}: a pixel is in more than one fold's test set"
            raise ValueError(msg)
        seen_test[split.test_indices] = True
        overlap = np.intersect1d(
            split.train_indices, split.test_indices, assume_unique=True
        )
        if overlap.size:
            msg = f"Fold {split.fold}: train and test indices overlap"
            raise ValueError(msg)
        touched_blocks = np.unique(block_raster.flat[split.test_indices])
        for block_id in touched_blocks:
            block_pixels = np.flatnonzero(block_raster == block_id)
            if not np.all(np.isin(block_pixels, split.test_indices)):
                msg = f"Fold {split.fold}: block {int(block_id)} is partially in the test set"
                raise ValueError(msg)
    if not np.all(seen_test):
        msg = "Some pixels are in no fold's test set; folds do not cover the grid"
        raise ValueError(msg)
