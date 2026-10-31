"""FinGuard transaction schema and validation.

The canonical in-memory transaction schema mirrors the IBM AML synthetic
dataset columns (verified against the Kaggle listing's file metadata,
2026-10-31 — see ``docs/data-sources/finguard-datasets.md``) with snake_case
names and an added ``tx_id`` row identifier:

    timestamp, tx_id, from_bank, from_account, to_bank, to_account,
    amount_received, receiving_currency, amount_paid, payment_currency,
    payment_format, is_laundering

Every ingestion and generation path funnels through
:func:`validate_transactions`, so downstream feature/graph code can assume a
validated frame. Validation never silently drops rows: problems raise
:class:`SchemaValidationError`.
"""

from __future__ import annotations

import pandas as pd

__all__ = [
    "CANONICAL_COLUMNS",
    "IBM_AML_COLUMN_MAP",
    "SCHEMA_VERSION",
    "SchemaValidationError",
    "normalize_ibm_aml_columns",
    "validate_transactions",
]

SCHEMA_VERSION = "1.0.0"

#: Kaggle listing column name -> canonical name. ``Account.1`` is the receiver
#: account in the raw CSV (pandas-style de-duplication of the second Account).
IBM_AML_COLUMN_MAP: dict[str, str] = {
    "Timestamp": "timestamp",
    "From Bank": "from_bank",
    "Account": "from_account",
    "To Bank": "to_bank",
    "Account.1": "to_account",
    "Amount Received": "amount_received",
    "Receiving Currency": "receiving_currency",
    "Amount Paid": "amount_paid",
    "Payment Currency": "payment_currency",
    "Payment Format": "payment_format",
    "Is Laundering": "is_laundering",
}

#: Canonical column order; ``tx_id`` is added by ingestion/generation.
CANONICAL_COLUMNS: tuple[str, ...] = (
    "tx_id",
    "timestamp",
    "from_bank",
    "from_account",
    "to_bank",
    "to_account",
    "amount_received",
    "receiving_currency",
    "amount_paid",
    "payment_currency",
    "payment_format",
    "is_laundering",
)

_AMOUNT_COLUMNS = ("amount_received", "amount_paid")
_ACCOUNT_COLUMNS = ("from_account", "to_account")
_CURRENCY_COLUMNS = ("receiving_currency", "payment_currency", "payment_format")
_BANK_COLUMNS = ("from_bank", "to_bank")


class SchemaValidationError(ValueError):
    """Raised when transaction data does not conform to the canonical schema."""


def normalize_ibm_aml_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename raw IBM AML columns to the canonical schema.

    Raises:
        SchemaValidationError: If any raw IBM AML column is missing, or if the
            frame carries an unexpected extra column.
    """
    missing = [col for col in IBM_AML_COLUMN_MAP if col not in df.columns]
    if missing:
        raise SchemaValidationError(
            "Raw IBM AML frame is missing expected columns: " + ", ".join(missing)
        )
    extras = [
        col for col in df.columns if col not in IBM_AML_COLUMN_MAP and col != "tx_id"
    ]
    if extras:
        raise SchemaValidationError(
            "Raw IBM AML frame has unexpected columns: " + ", ".join(extras)
        )
    out = df.rename(columns=IBM_AML_COLUMN_MAP)
    return out[[c for c in CANONICAL_COLUMNS if c in out.columns]]


def validate_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """Validate and enforce the canonical transaction schema.

    Returns a validated copy with canonical column order and dtypes:

    * ``tx_id`` int64 (assigned sequentially when absent)
    * ``timestamp`` datetime64[ns]
    * ``from_bank``/``to_bank``/``is_laundering`` int64, amounts float64
    * account/currency/format columns as non-null strings

    Raises:
        SchemaValidationError: On missing columns, unparseable or missing
            timestamps, non-finite/negative amounts, laundering flags outside
            {0, 1}, negative bank codes, or null account/currency values.
    """
    missing = [col for col in CANONICAL_COLUMNS if col != "tx_id" and col not in df.columns]
    if missing:
        raise SchemaValidationError(
            "Transaction frame is missing required columns: " + ", ".join(missing)
        )

    out = df.loc[:, [c for c in CANONICAL_COLUMNS if c in df.columns]].copy()

    # Timestamps: parse once, then reject any failure explicitly.
    timestamps = pd.to_datetime(out["timestamp"], format="%Y/%m/%d %H:%M", errors="coerce")
    if timestamps.isna().any():
        bad = int(timestamps.isna().sum())
        raise SchemaValidationError(
            f"{bad} row(s) have unparseable 'timestamp' values "
            "(expected 'YYYY/MM/DD HH:MM')"
        )
    out["timestamp"] = timestamps

    for col in _AMOUNT_COLUMNS:
        amounts = pd.to_numeric(out[col], errors="coerce")
        if amounts.isna().any():
            raise SchemaValidationError(f"Column {col!r} contains non-numeric values")
        if (amounts < 0).any():
            raise SchemaValidationError(f"Column {col!r} contains negative amounts")
        out[col] = amounts.astype("float64")

    for col in _BANK_COLUMNS:
        banks = pd.to_numeric(out[col], errors="coerce")
        if banks.isna().any():
            raise SchemaValidationError(f"Column {col!r} contains non-numeric bank codes")
        if (banks < 0).any():
            raise SchemaValidationError(f"Column {col!r} contains negative bank codes")
        out[col] = banks.astype("int64")

    flags = pd.to_numeric(out["is_laundering"], errors="coerce")
    if flags.isna().any() or not flags.isin([0, 1]).all():
        raise SchemaValidationError(
            "Column 'is_laundering' must contain only 0 or 1"
        )
    out["is_laundering"] = flags.astype("int64")

    for col in (*_ACCOUNT_COLUMNS, *_CURRENCY_COLUMNS):
        values = out[col].astype("string").str.strip()
        if values.isna().any() or (values == "").any():
            raise SchemaValidationError(f"Column {col!r} contains null or empty values")
        out[col] = values

    if "tx_id" not in out.columns:
        out = out.assign(tx_id=pd.RangeIndex(len(out), dtype="int64"))
    else:
        out["tx_id"] = pd.to_numeric(out["tx_id"], errors="coerce").astype("int64")
        if out["tx_id"].duplicated().any():
            raise SchemaValidationError("Column 'tx_id' contains duplicate values")

    return out[list(CANONICAL_COLUMNS)]
