"""Shared fixtures for FinGuard tests (synthetic data only, no datasets)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from finguard.schema import CANONICAL_COLUMNS, IBM_AML_COLUMN_MAP


@pytest.fixture
def valid_transactions() -> pd.DataFrame:
    """A small, hand-built frame in the canonical schema (mix of flags)."""
    rng = np.random.default_rng(7)
    n = 60
    stamps = pd.date_range("2022-09-01 00:00", periods=n, freq="37min")
    frame = pd.DataFrame(
        {
            "timestamp": stamps,
            "from_bank": rng.integers(1, 20, size=n),
            "from_account": [f"{i:08X}" for i in rng.integers(16**7, 16**8, size=n)],
            "to_bank": rng.integers(1, 20, size=n),
            "to_account": [f"{i:08X}" for i in rng.integers(16**7, 16**8, size=n)],
            "amount_received": np.round(rng.uniform(10, 5000, size=n), 2),
            "receiving_currency": "US Dollar",
            "amount_paid": np.round(rng.uniform(10, 5000, size=n), 2),
            "payment_currency": "US Dollar",
            "payment_format": "ACH",
            "is_laundering": np.zeros(n, dtype="int64"),
        }
    )
    frame.loc[frame.index[:3], "is_laundering"] = 1
    return frame


@pytest.fixture
def ibm_raw_transactions(valid_transactions: pd.DataFrame) -> pd.DataFrame:
    """The same data as a raw IBM AML listing CSV would provide it."""
    inverse = {v: k for k, v in IBM_AML_COLUMN_MAP.items()}
    raw = valid_transactions.drop(columns=["tx_id"], errors="ignore").rename(
        columns=inverse
    )
    raw["Timestamp"] = pd.to_datetime(raw["Timestamp"]).dt.strftime("%Y/%m/%d %H:%M")
    return raw[list(IBM_AML_COLUMN_MAP)]


def canonical_columns() -> list[str]:
    return list(CANONICAL_COLUMNS)
