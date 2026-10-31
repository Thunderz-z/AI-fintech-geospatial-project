"""Seasonal grouping and median compositing.

Compositing convention: band planes arrive as float32 with NaN marking invalid
observations (see ``terrascope.ingestion.masking``). The composite median is
taken over valid observations only, and a per-pixel ``valid_count`` plane is
returned alongside so downstream abstention logic (M0 step 5) knows how many
observations support each value.

Season mapping (documented default, total over the calendar — every month maps
to exactly one season so no observation is silently dropped):

* ``winter``       — Dec, Jan, Feb (dry/cool)
* ``summer``       — Mar, Apr, May (hot, pre-monsoon)
* ``monsoon-post`` — Jun–Nov (SW monsoon through the NE monsoon/post-monsoon)

This is a coarse starting point for the Pallikaranai rainfall regime (the NE
monsoon, Oct–Dec, brings most rain) and is flagged for revisit at the first
real-data visual QA; the mapping is data-driven so it can be reconfigured
without code changes.
"""

from __future__ import annotations

import datetime as dt
import warnings
from collections.abc import Mapping, Sequence

import numpy as np

__all__ = [
    "DEFAULT_SEASON_MONTHS",
    "group_by_season",
    "median_composite",
    "season_for_date",
]

DEFAULT_SEASON_MONTHS: dict[str, frozenset[int]] = {
    "winter": frozenset({12, 1, 2}),
    "summer": frozenset({3, 4, 5}),
    "monsoon-post": frozenset({6, 7, 8, 9, 10, 11}),
}


def season_for_date(
    date: dt.date, mapping: Mapping[str, frozenset[int] | set[int]] = DEFAULT_SEASON_MONTHS
) -> str:
    """Return the season name for *date* under *mapping*.

    Raises:
        ValueError: If the date's month is unmapped (never with the default).
    """
    for season, months in mapping.items():
        if date.month in months:
            return season
    msg = f"Month {date.month} is not mapped to any season in {sorted(mapping)}"
    raise ValueError(msg)


def group_by_season(
    dates: Sequence[dt.date],
    mapping: Mapping[str, frozenset[int] | set[int]] = DEFAULT_SEASON_MONTHS,
) -> dict[str, list[int]]:
    """Group sequence indices by season.

    Returns:
        Mapping of season name -> sorted list of indices into *dates*.
    """
    groups: dict[str, list[int]] = {season: [] for season in mapping}
    for index, date in enumerate(dates):
        groups.setdefault(season_for_date(date, mapping), []).append(index)
    return {season: sorted(indices) for season, indices in groups.items()}


def median_composite(
    stack: np.ndarray, *, fill: float = np.nan
) -> tuple[np.ndarray, np.ndarray]:
    """Pixel-wise median over the leading axis of *stack*, ignoring NaN.

    Args:
        stack: ``(n, h, w)`` float32 array; NaN = invalid observation.
        fill: Value used for pixels with zero valid observations (default NaN).

    Returns:
        ``(median, valid_count)``: the ``(h, w)`` float32 median (NaN where
        no valid observation exists) and the ``(h, w)`` uint16 count of valid
        observations per pixel. For an even count the median is the mean of
        the two middle values (numpy convention).
    """
    stack = np.asarray(stack, dtype=np.float32)
    if stack.ndim != 3 or stack.shape[0] == 0:
        msg = f"Expected a non-empty (n, h, w) stack, got shape {stack.shape}"
        raise ValueError(msg)
    valid_count = np.count_nonzero(~np.isnan(stack), axis=0).astype(np.uint16)
    with warnings.catch_warnings():
        # All-NaN pixels are intentional here (no valid observations); the
        # count plane reports them, so the numpy warning is not useful noise.
        warnings.simplefilter("ignore", category=RuntimeWarning)
        median = np.nanmedian(stack, axis=0).astype(np.float32)
    median = np.where(valid_count > 0, median, np.float32(fill)).astype(np.float32)
    return median, valid_count
