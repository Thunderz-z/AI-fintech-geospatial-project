"""Temporal split and leakage-assertion tests (ADR-0006 discipline)."""

from __future__ import annotations

import pandas as pd
import pytest

from finguard.splitting import (
    LeakageError,
    assert_no_post_event_information,
    assert_temporal_containment,
    temporal_split,
)
from finguard.synthetic import generate_synthetic_transactions


@pytest.fixture(scope="module")
def transactions() -> pd.DataFrame:
    tx, _ = generate_synthetic_transactions(n_normal=2000, seed=17)
    return tx


def test_split_respects_time_boundaries(transactions: pd.DataFrame) -> None:
    split = temporal_split(transactions)

    train_max = split.train["timestamp"].max()
    valid_min = split.validation["timestamp"].min()
    valid_max = split.validation["timestamp"].max()
    test_min = split.test["timestamp"].min()

    assert train_max < valid_min  # whole timestamps move together
    assert valid_max < test_min
    assert split.train_end == train_max
    assert split.validation_end == valid_max
    assert_temporal_containment(split)  # explicit gate must also pass


def test_split_conserves_rows_and_fractions(transactions: pd.DataFrame) -> None:
    split = temporal_split(transactions)

    assert len(split.train) + len(split.validation) + len(split.test) == len(transactions)
    fracs = split.fractions
    assert fracs[0] == pytest.approx(0.6, abs=0.1)
    assert fracs[1] == pytest.approx(0.2, abs=0.1)
    assert fracs[2] == pytest.approx(0.2, abs=0.1)


def test_split_is_deterministic(transactions: pd.DataFrame) -> None:
    a = temporal_split(transactions)
    b = temporal_split(transactions)

    pd.testing.assert_frame_equal(a.train, b.train)
    pd.testing.assert_frame_equal(a.validation, b.validation)
    pd.testing.assert_frame_equal(a.test, b.test)


def test_periods_are_disjoint(transactions: pd.DataFrame) -> None:
    split = temporal_split(transactions)

    train_ids = set(split.train["tx_id"])
    valid_ids = set(split.validation["tx_id"])
    test_ids = set(split.test["tx_id"])
    assert not train_ids & valid_ids
    assert not train_ids & test_ids
    assert not valid_ids & test_ids


def test_invalid_fractions_rejected(transactions: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="train_frac"):
        temporal_split(transactions, train_frac=0.0)
    with pytest.raises(ValueError, match="non-empty test"):
        temporal_split(transactions, train_frac=0.8, valid_frac=0.2)


def test_unparseable_timestamps_rejected(valid_transactions: pd.DataFrame) -> None:
    broken = valid_transactions.astype({"timestamp": "object"})
    broken.loc[broken.index[0], "timestamp"] = "not-a-time"
    with pytest.raises(ValueError, match="unparseable"):
        temporal_split(broken)


def test_missing_timestamp_column_rejected(valid_transactions: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="timestamp"):
        temporal_split(valid_transactions.drop(columns=["timestamp"]))


def test_containment_catches_crossing_boundary(valid_transactions: pd.DataFrame) -> None:
    split = temporal_split(valid_transactions)
    # Rebuild a split whose validation overlaps train — must be caught.
    swapped = split.train.tail(3)
    corrupted = type(split)(
        train=split.train,
        validation=swapped,
        test=split.test,
        train_end=split.train_end,
        validation_end=split.validation_end,
    )
    with pytest.raises(LeakageError, match="train extends"):
        assert_temporal_containment(corrupted)


def test_no_post_event_information_accepts_honest_features(
    transactions: pd.DataFrame,
) -> None:
    # Honest per-account rolling count: each event's feature is computed from
    # transactions strictly before the event time.
    tx = transactions.reset_index(drop=True)
    feature_time = tx["timestamp"] - pd.Timedelta(minutes=1)
    features = pd.DataFrame(
        {
            "event_time": tx["timestamp"],
            "feature_time": feature_time,
            "prior_count": [i for i in range(len(tx))],  # placeholder value
        }
    )
    assert_no_post_event_information(features)


def test_no_post_event_information_catches_future_feature() -> None:
    stamps = pd.date_range("2022-09-01", periods=10, freq="h")
    features = pd.DataFrame(
        {
            "event_time": stamps,
            "feature_time": stamps + pd.Timedelta(hours=1),  # leakage canary
        }
    )
    with pytest.raises(LeakageError, match="post-event|Leakage"):
        assert_no_post_event_information(features)


def test_no_post_event_information_requires_columns() -> None:
    with pytest.raises(LeakageError, match="feature_time"):
        assert_no_post_event_information(pd.DataFrame({"event_time": [pd.Timestamp(2022, 1, 1)]}))
    with pytest.raises(LeakageError, match="event_time"):
        assert_no_post_event_information(
            pd.DataFrame({"feature_time": [pd.Timestamp(2022, 1, 1)]})
        )
