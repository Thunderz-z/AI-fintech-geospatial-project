"""Tests for spatial block CV scaffolding (ADR-0006; offline, no data)."""

from __future__ import annotations

import numpy as np
import pytest

from terrascope.evaluation.spatial_cv import (
    SpatialBlockSplitter,
    block_id_raster,
    block_size_pixels,
    validate_splits,
)


class TestBlockRaster:
    def test_deterministic_squares(self) -> None:
        raster = block_id_raster(10, 10, 4)
        assert raster.shape == (10, 10)
        assert raster[0, 0] == raster[3, 3]  # same 4x4 block
        assert raster[0, 0] != raster[4, 4]  # different block
        assert raster[0, 0] != raster[0, 4]  # different block (cols)

    def test_edge_blocks(self) -> None:
        raster = block_id_raster(5, 5, 4)  # 2x2 blocks, last ones smaller
        assert int(raster.max()) == 3
        # The three corner-adjacent cells sit in three different edge blocks.
        assert raster[4, 4] != raster[4, 0]
        assert raster[4, 4] != raster[0, 4]
        assert raster[4, 0] != raster[0, 4]

    def test_invalid_block_size(self) -> None:
        with pytest.raises(ValueError, match="block_size_px"):
            block_id_raster(4, 4, 0)


class TestSplitter:
    def test_folds_partition_the_grid(self) -> None:
        splitter = SpatialBlockSplitter(height=40, width=40, block_size_px=10, n_folds=4)
        splits = splitter.splits()
        validate_splits(splits, splitter.block_raster)  # must not raise

    def test_train_test_disjoint_per_fold(self) -> None:
        splitter = SpatialBlockSplitter(height=30, width=50, block_size_px=10, n_folds=3)
        for split in splitter.splits():
            assert not np.intersect1d(split.train_indices, split.test_indices).size

    def test_deterministic(self) -> None:
        first = SpatialBlockSplitter(
            height=20, width=20, block_size_px=5, n_folds=4
        ).splits()
        second = SpatialBlockSplitter(
            height=20, width=20, block_size_px=5, n_folds=4
        ).splits()
        for a, b in zip(first, second, strict=True):
            assert np.array_equal(a.train_indices, b.train_indices)
            assert np.array_equal(a.test_indices, b.test_indices)

    def test_folds_spread_across_the_scene(self) -> None:
        """Each fold's test blocks must not be one contiguous corner."""
        splitter = SpatialBlockSplitter(height=60, width=60, block_size_px=10, n_folds=4)
        for split in splitter.splits():
            rows = split.test_indices // 60
            cols = split.test_indices % 60
            assert rows.min() < 30 < rows.max()
            assert cols.min() < 30 < cols.max()

    def test_too_many_folds_raises(self) -> None:
        splitter = SpatialBlockSplitter(height=10, width=10, block_size_px=10, n_folds=8)
        with pytest.raises(ValueError, match="no blocks"):
            splitter.splits()

    def test_block_size_pixels(self) -> None:
        assert block_size_pixels(2000, 10) == 200  # the config default at 10 m
        assert block_size_pixels(15, 20) == 1
        with pytest.raises(ValueError, match="positive"):
            block_size_pixels(0, 10)


class TestValidator:
    def test_rejects_overlapping_train_test(self) -> None:
        splitter = SpatialBlockSplitter(height=20, width=20, block_size_px=10, n_folds=2)
        splits = splitter.splits()
        broken = [
            type(splits[0])(
                fold=0,
                test_block_ids=splits[0].test_block_ids,
                train_indices=np.concatenate([splits[0].train_indices, splits[0].test_indices[:5]]),
                test_indices=splits[0].test_indices,
            ),
            *splits[1:],
        ]
        with pytest.raises(ValueError, match="overlap"):
            validate_splits(broken, splitter.block_raster)

    def test_rejects_partial_block_in_test(self) -> None:
        splitter = SpatialBlockSplitter(height=20, width=20, block_size_px=10, n_folds=2)
        splits = splitter.splits()
        broken = [
            type(splits[0])(
                fold=0,
                test_block_ids=splits[0].test_block_ids,
                train_indices=splits[0].train_indices,
                test_indices=splits[0].test_indices[:-3],  # drop pixels of the test block
            ),
            *splits[1:],
        ]
        with pytest.raises(ValueError, match="partially"):
            validate_splits(broken, splitter.block_raster)

    def test_rejects_pixel_in_two_folds(self) -> None:
        splitter = SpatialBlockSplitter(height=20, width=20, block_size_px=10, n_folds=2)
        splits = splitter.splits()
        stolen = splits[1].test_indices[:5]
        broken = [
            type(splits[0])(
                fold=0,
                test_block_ids=splits[0].test_block_ids,
                train_indices=np.setdiff1d(splits[0].train_indices, stolen),
                test_indices=np.concatenate([splits[0].test_indices, stolen]),
            ),
            *splits[1:],
        ]
        # The corrupted test set violates two invariants (double-counted
        # pixels AND a partial block); either detection is a pass.
        with pytest.raises(ValueError, match="more than one fold|partially"):
            validate_splits(broken, splitter.block_raster)
