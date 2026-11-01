"""Temporal train/validation/test splitting and leakage assertions.

FinGuard's evaluation discipline (ADR-0006): splits are aligned to
transaction time, whole timestamps move together (a cutoff never bisects a
timestamp value), and feature engineering must not see post-event
information. Random splitting is leakage — any evaluation code that
randomizes across time is a blocking defect.

The IBM AML data has a documented quirk this module handles by *documented
behaviour* rather than silent correction: some transactions fall after the
listing's stated activity window and they are all laundering. Splitting is
purely by timestamp cutoffs, so those rows land in the test tail naturally.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

__all__ = [
    "LeakageError",
    "TemporalSplit",
    "assert_no_post_event_information",
    "assert_temporal_containment",
    "temporal_split",
]


class LeakageError(AssertionError):
    """Raised when a temporal-leakage invariant is violated."""


@dataclass(frozen=True)
class TemporalSplit:
    """Contiguous-in-time train/validation/test frames plus cutoffs."""

    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    train_end: pd.Timestamp
    validation_end: pd.Timestamp

    @property
    def fractions(self) -> tuple[float, float, float]:
        total = len(self.train) + len(self.validation) + len(self.test)
        if total == 0:
            return (0.0, 0.0, 0.0)
        return (
            len(self.train) / total,
            len(self.validation) / total,
            len(self.test) / total,
        )


def temporal_split(
    df: pd.DataFrame,
    *,
    timestamp_col: str = "timestamp",
    train_frac: float = 0.6,
    valid_frac: float = 0.2,
) -> TemporalSplit:
    """Split *df* into contiguous train/validation/test periods.

    Rows are ordered by ``timestamp_col``; the train/validation and
    validation/test boundaries are placed at *unique timestamp values*, so a
    single timestamp is never split across periods. Rows sharing the boundary
    timestamp belong to the earlier period (train ends at its last full
    timestamp, etc.).

    Args:
        df: Transactions with a parseable ``timestamp_col``.
        timestamp_col: Ordering column.
        train_frac: Target share of the training period (unique timestamps).
        valid_frac: Target share of the validation period; the remainder is
            the test period.

    Returns:
        :class:`TemporalSplit` with frames sorted by ``timestamp_col``.

    Raises:
        ValueError: If fractions are non-positive/overfull or timestamps
            cannot be parsed.
        LeakageError: If the split does not satisfy temporal containment
            (never, by construction — the self-check guards regressions).
    """
    if not (0.0 < train_frac < 1.0) or not (0.0 < valid_frac < 1.0):
        raise ValueError("train_frac and valid_frac must be in (0, 1)")
    if train_frac + valid_frac >= 1.0:
        raise ValueError("train_frac + valid_frac must leave a non-empty test period")

    if timestamp_col not in df.columns:
        raise ValueError(f"Missing timestamp column {timestamp_col!r}")
    if pd.api.types.is_datetime64_any_dtype(df[timestamp_col]):
        timestamps = df[timestamp_col]
    else:
        timestamps = pd.to_datetime(df[timestamp_col], errors="coerce")
    if timestamps.isna().any():
        raise ValueError(f"Column {timestamp_col!r} contains unparseable timestamps")

    order = timestamps.sort_values(kind="mergesort").index
    unique_ts = timestamps.loc[order].drop_duplicates().to_numpy()
    n_unique = len(unique_ts)
    train_idx = max(1, int(round(n_unique * train_frac)))
    valid_idx = train_idx + max(1, int(round(n_unique * valid_frac)))
    if valid_idx >= n_unique:
        raise ValueError("Fractions leave an empty test period for this many timestamps")

    train_end = pd.Timestamp(unique_ts[train_idx - 1])
    validation_end = pd.Timestamp(unique_ts[valid_idx - 1])

    sorted_df = df.loc[order]
    sorted_ts = timestamps.loc[order]
    split = TemporalSplit(
        train=sorted_df.loc[sorted_ts <= train_end],
        validation=sorted_df.loc[(sorted_ts > train_end) & (sorted_ts <= validation_end)],
        test=sorted_df.loc[sorted_ts > validation_end],
        train_end=train_end,
        validation_end=validation_end,
    )

    # Row conservation guards any indexing refactor mistake.
    if len(split.train) + len(split.validation) + len(split.test) != len(df):
        raise LeakageError("Split periods do not conserve the input row count")

    assert_temporal_containment(split, timestamp_col=timestamp_col)
    return split


def assert_temporal_containment(
    split: TemporalSplit, *, timestamp_col: str = "timestamp"
) -> None:
    """Assert train ends before validation starts, validation before test.

    Raises:
        LeakageError: On any boundary violation or empty-period surprise.
    """
    for name, part in (
        ("train", split.train),
        ("validation", split.validation),
        ("test", split.test),
    ):
        if part.empty:
            raise LeakageError(f"Temporal split produced an empty {name!r} period")

    train_max = split.train[timestamp_col].max()
    valid_min = split.validation[timestamp_col].min()
    valid_max = split.validation[timestamp_col].max()
    test_min = split.test[timestamp_col].min()

    if train_max > valid_min:
        raise LeakageError(
            f"Leakage: train extends to {train_max} beyond validation start {valid_min}"
        )
    if valid_max > test_min:
        raise LeakageError(
            f"Leakage: validation extends to {valid_max} beyond test start {test_min}"
        )


def assert_no_post_event_information(
    features: pd.DataFrame,
    *,
    feature_time_col: str = "feature_time",
    event_time_col: str = "event_time",
) -> None:
    """Assert every feature row was computed strictly at/before its event.

    The reusable M1 leakage gate: when feature engineering lands (M1 step 5),
    each feature row must carry ``feature_time`` = the last transaction time
    that influenced it and ``event_time`` = the prediction target time.
    Anything after the event time is post-event information and is leakage —
    this assertion is what the leakage tests (and later CI) run on synthetic
    data where the truth is known.

    Raises:
        LeakageError: If any feature row has ``feature_time > event_time``
            or the required columns/values are missing.
    """
    for col in (feature_time_col, event_time_col):
        if col not in features.columns:
            raise LeakageError(f"Features frame is missing required column {col!r}")
    feature_time = pd.to_datetime(features[feature_time_col], errors="coerce")
    event_time = pd.to_datetime(features[event_time_col], errors="coerce")
    if feature_time.isna().any() or event_time.isna().any():
        raise LeakageError("feature_time/event_time contain unparseable timestamps")

    leaky = feature_time > event_time
    if leaky.any():
        n = int(leaky.sum())
        worst = (feature_time - event_time)[leaky].max()
        raise LeakageError(
            f"Leakage: {n} feature row(s) use information after the event "
            f"(worst feature_time exceeds event_time by {worst})"
        )
