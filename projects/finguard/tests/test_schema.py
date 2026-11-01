"""Schema validation tests (synthetic frames only)."""

from __future__ import annotations

import pandas as pd
import pytest

from finguard.schema import (
    CANONICAL_COLUMNS,
    IBM_AML_COLUMN_MAP,
    SchemaValidationError,
    normalize_ibm_aml_columns,
    validate_transactions,
)


def test_valid_frame_passes_and_normalizes_dtypes(valid_transactions: pd.DataFrame) -> None:
    out = validate_transactions(valid_transactions)

    assert list(out.columns) == list(CANONICAL_COLUMNS)
    # pandas 3 defaults to datetime64[us]; any datetime64 resolution is fine.
    assert pd.api.types.is_datetime64_any_dtype(out["timestamp"])
    assert str(out["from_bank"].dtype) == "int64"
    assert str(out["amount_received"].dtype) == "float64"
    assert str(out["is_laundering"].dtype) == "int64"
    assert str(out["from_account"].dtype) == "string"
    assert len(out) == len(valid_transactions)
    assert (out["tx_id"] == pd.RangeIndex(len(out))).all()


def test_missing_column_raises(valid_transactions: pd.DataFrame) -> None:
    broken = valid_transactions.drop(columns=["amount_paid"])
    with pytest.raises(SchemaValidationError, match="amount_paid"):
        validate_transactions(broken)


def test_invalid_laundering_flag_raises(valid_transactions: pd.DataFrame) -> None:
    broken = valid_transactions.assign(is_laundering=2)
    with pytest.raises(SchemaValidationError, match="is_laundering"):
        validate_transactions(broken)


def test_negative_amount_raises(valid_transactions: pd.DataFrame) -> None:
    broken = valid_transactions.copy()
    broken.loc[broken.index[0], "amount_paid"] = -1.0
    with pytest.raises(SchemaValidationError, match="negative"):
        validate_transactions(broken)


def test_non_numeric_amount_raises(valid_transactions: pd.DataFrame) -> None:
    broken = valid_transactions.astype({"amount_received": "object"})
    broken.loc[broken.index[0], "amount_received"] = "many dollars"
    with pytest.raises(SchemaValidationError, match="non-numeric"):
        validate_transactions(broken)


def test_unparseable_timestamp_raises(valid_transactions: pd.DataFrame) -> None:
    broken = valid_transactions.astype({"timestamp": "object"})
    broken.loc[broken.index[0], "timestamp"] = "2022-45-99 99:99"
    with pytest.raises(SchemaValidationError, match="unparseable"):
        validate_transactions(broken)


def test_empty_account_raises(valid_transactions: pd.DataFrame) -> None:
    broken = valid_transactions.copy()
    broken.loc[broken.index[1], "to_account"] = "  "
    with pytest.raises(SchemaValidationError, match="to_account"):
        validate_transactions(broken)


def test_duplicate_tx_id_raises(valid_transactions: pd.DataFrame) -> None:
    with_tx = validate_transactions(valid_transactions)
    duplicated = pd.concat([with_tx, with_tx.head(1)], ignore_index=True)
    with pytest.raises(SchemaValidationError, match="duplicate"):
        validate_transactions(duplicated)


def test_normalize_ibm_columns(ibm_raw_transactions: pd.DataFrame) -> None:
    out = normalize_ibm_aml_columns(ibm_raw_transactions)

    # tx_id is added later by validation/ingestion, not by renaming.
    assert list(out.columns) == [c for c in CANONICAL_COLUMNS if c != "tx_id"]
    assert "Account.1" not in out.columns
    assert "from_account" in out.columns


def test_normalize_rejects_missing_raw_column() -> None:
    almost = pd.DataFrame({k: [1] for k in list(IBM_AML_COLUMN_MAP)[:-1]})
    with pytest.raises(SchemaValidationError, match="missing"):
        normalize_ibm_aml_columns(almost)


def test_normalize_rejects_extra_column(ibm_raw_transactions: pd.DataFrame) -> None:
    polluted = ibm_raw_transactions.assign(Surprise="x")
    with pytest.raises(SchemaValidationError, match="unexpected"):
        normalize_ibm_aml_columns(polluted)
