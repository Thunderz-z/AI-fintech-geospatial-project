"""Leakage-safe baseline feature engineering for transaction fraud modelling.

Design (ADR-0006): every feature is computable *at* the transaction's event
time from (a) the transaction's own attributes and (b) the strictly-prior
history of the involved accounts. No future rows are read. The temporal
leakage gate (``finguard.splitting.assert_no_post_event_information``) can
be applied to the output directly; ``feature_time == event_time`` for every
row.

Prior-history semantics, stated precisely:

* ``*_prior_count`` counts the account's earlier transactions with
  **strictly smaller timestamps** (ties excluded, via ``rank(method="min")``).
* ``*_prior_sum`` sums amounts of earlier transactions with strictly smaller
  timestamps (group cumulative sum minus the equal-timestamp block).
* Amount aggregates never touch the ``is_laundering`` column — labels are
  never a feature input.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from finguard.splitting import assert_no_post_event_information

__all__ = [
    "FEATURE_COLUMNS",
    "build_baseline_features",
]

#: Model-ready feature columns (categoricals + numerics) produced by
#: :func:`build_baseline_features`.
FEATURE_COLUMNS: tuple[str, ...] = (
    "log_amount_received",
    "log_amount_paid",
    "amount_ratio",
    "same_currency",
    "hour_of_day",
    "payment_format",
    "receiving_currency",
    "payment_currency",
    "from_bank",
    "to_bank",
    "sender_prior_count",
    "sender_prior_amount",
    "receiver_prior_count",
    "receiver_prior_received",
)


def _strictly_prior_aggregates(
    tx: pd.DataFrame, group_col: str, value_col: str, name: str
) -> pd.Series:
    """Sum of *value_col* over same-group rows with strictly smaller timestamps."""
    total = tx.groupby(group_col, observed=True, sort=False)[value_col].cumsum()
    tie_block = tx.groupby(
        [group_col, "timestamp"], observed=True, sort=False
    )[value_col].transform("sum")
    return (total - tie_block).rename(name)


def build_baseline_features(tx: pd.DataFrame) -> pd.DataFrame:
    """Build the M1 baseline feature frame for validated canonical transactions.

    Args:
        tx: Canonical transactions (see :mod:`finguard.schema`); the frame is
            sorted by ``timestamp`` internally.

    Returns:
        A frame with ``tx_id``/``timestamp``/``is_laundering`` passthrough
        plus :data:`FEATURE_COLUMNS`, row-aligned with the *sorted* input.
        Categorical columns use pandas nullable ``category`` dtype so the
        frame is LightGBM-ready after ``pd.get_dummies`` or native categorical
        handling.

    Raises:
        LeakageError: If the leakage gate fails (defensive; by construction
            it cannot, which is exactly what the smoke test asserts).
    """
    tx = tx.sort_values("timestamp", kind="mergesort").reset_index(drop=True)

    features = pd.DataFrame(
        {
            "tx_id": tx["tx_id"],
            "timestamp": tx["timestamp"],
            "is_laundering": tx["is_laundering"],
            "log_amount_received": np.log1p(tx["amount_received"]),
            "log_amount_paid": np.log1p(tx["amount_paid"]),
            "amount_ratio": (
                tx["amount_paid"] / tx["amount_received"].replace(0, np.nan)
            ).fillna(0.0),
            "same_currency": (
                tx["receiving_currency"] == tx["payment_currency"]
            ).astype("int8"),
            "hour_of_day": tx["timestamp"].dt.hour.astype("int8"),
            "payment_format": tx["payment_format"].astype("category"),
            "receiving_currency": tx["receiving_currency"].astype("category"),
            "payment_currency": tx["payment_currency"].astype("category"),
            "from_bank": tx["from_bank"].astype("category"),
            "to_bank": tx["to_bank"].astype("category"),
        }
    )

    # Strictly-prior account history (sender side, amounts paid out).
    sender_rank = tx.groupby("from_account", observed=True, sort=False)[
        "timestamp"
    ].rank(method="min")
    features["sender_prior_count"] = (sender_rank - 1).astype("int64")
    features["sender_prior_amount"] = _strictly_prior_aggregates(
        tx, "from_account", "amount_paid", "sender_prior_amount"
    ).fillna(0.0)

    # Receiver side, amounts received.
    receiver_rank = tx.groupby("to_account", observed=True, sort=False)[
        "timestamp"
    ].rank(method="min")
    features["receiver_prior_count"] = (receiver_rank - 1).astype("int64")
    features["receiver_prior_received"] = _strictly_prior_aggregates(
        tx, "to_account", "amount_received", "receiver_prior_received"
    ).fillna(0.0)

    assert_no_post_event_information(
        features, feature_time_col="timestamp", event_time_col="timestamp"
    )
    return features
