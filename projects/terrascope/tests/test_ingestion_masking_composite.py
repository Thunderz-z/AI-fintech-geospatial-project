"""Tests for SCL masking and seasonal median compositing (pure numpy)."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from terrascope.ingestion.composite import (
    DEFAULT_SEASON_MONTHS,
    group_by_season,
    median_composite,
    season_for_date,
)
from terrascope.ingestion.masking import (
    SCL_EXCLUDE_DEFAULT,
    apply_mask,
    scl_valid_mask,
    upscale_mask_nearest,
    valid_fraction,
)


class TestSclMask:
    def test_excluded_classes(self) -> None:
        scl = np.array([[4, 8], [0, 6]], dtype=np.uint8)
        mask = scl_valid_mask(scl)
        assert mask.tolist() == [[True, False], [False, True]]

    def test_full_default_exclusion_set(self) -> None:
        scl = np.arange(12, dtype=np.uint8).reshape(3, 4)
        mask = scl_valid_mask(scl)
        expected_valid = {2, 4, 5, 6, 7}  # dark, vegetation, not-vegetated, water, unclassified
        for value in range(12):
            row, col = divmod(value, 4)
            assert mask[row, col] == (value in expected_valid)

    def test_valid_fraction(self) -> None:
        scl = np.full((10, 10), 4, dtype=np.uint8)
        assert valid_fraction(scl) == 1.0
        scl[:2, :] = 8  # 20% cloud
        assert valid_fraction(scl) == pytest.approx(0.8)

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            valid_fraction(np.empty((0, 0), dtype=np.uint8))

    def test_3d_input_rejected(self) -> None:
        with pytest.raises(ValueError, match="2D"):
            scl_valid_mask(np.zeros((2, 2, 2), dtype=np.uint8))

    def test_upscale_mask_nearest(self) -> None:
        mask = np.array([[True, False]], dtype=bool)
        upscaled = upscale_mask_nearest(mask, 2)
        assert upscaled.shape == (2, 4)
        assert upscaled.tolist() == [
            [True, True, False, False],
            [True, True, False, False],
        ]

    def test_upscale_rejects_non_integer(self) -> None:
        with pytest.raises(ValueError, match="factor"):
            upscale_mask_nearest(np.zeros((2, 2), dtype=bool), 1.5)

    def test_apply_mask(self) -> None:
        array = np.array([[10, 20], [30, 40]], dtype=np.uint16)
        valid = np.array([[True, False], [True, True]])
        masked = apply_mask(array, valid)
        assert np.isnan(masked[0, 1])
        assert masked[0, 0] == 10
        assert masked.dtype == np.float32


class TestSeasons:
    def test_month_mapping_is_total(self) -> None:
        covered: set[int] = set()
        for months in DEFAULT_SEASON_MONTHS.values():
            covered |= set(months)
        assert covered == set(range(1, 13))

    def test_season_for_date(self) -> None:
        assert season_for_date(dt.date(2024, 1, 15)) == "winter"
        assert season_for_date(dt.date(2024, 5, 10)) == "summer"
        assert season_for_date(dt.date(2024, 10, 3)) == "monsoon-post"

    def test_group_by_season(self) -> None:
        dates = [
            dt.date(2024, 1, 5),
            dt.date(2024, 2, 20),
            dt.date(2024, 4, 1),
            dt.date(2024, 7, 8),
        ]
        groups = group_by_season(dates)
        assert groups["winter"] == [0, 1]
        assert groups["summer"] == [2]
        assert groups["monsoon-post"] == [3]


class TestMedianComposite:
    def test_median_ignores_nan(self) -> None:
        stack = np.array(
            [
                [[10, 100], [np.nan, 30]],
                [[20, 200], [40, np.nan]],
                [[30, 300], [50, 70]],
            ],
            dtype=np.float32,
        )
        median, count = median_composite(stack)
        assert median[0, 0] == pytest.approx(20.0)
        assert median[0, 1] == pytest.approx(200.0)  # NaNs excluded from the median
        assert median[1, 0] == pytest.approx(45.0)  # NaN in the first plane
        assert median[1, 1] == pytest.approx(50.0)
        assert count.tolist() == [[3, 3], [2, 2]]

    def test_all_nan_pixel_reports_count_zero(self) -> None:
        stack = np.full((2, 2, 2), np.nan, dtype=np.float32)
        median, count = median_composite(stack)
        assert np.isnan(median).all()
        assert (count == 0).all()

    def test_empty_stack_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            median_composite(np.zeros((0, 4, 4), dtype=np.float32))

    def test_default_scl_exclude_matches_config(self) -> None:
        assert SCL_EXCLUDE_DEFAULT == frozenset({0, 1, 3, 8, 9, 10, 11})
