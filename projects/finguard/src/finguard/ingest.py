"""CSV ingestion and Parquet conversion for IBM AML transaction files.

The Kaggle transaction CSVs reach ~475-650 MB uncompressed, so conversion is
streamed in chunks: read -> normalize -> validate -> append to a single
Parquet writer. The Parquet copy is the pipeline's working format; raw CSVs
are never modified.

All *paths* are caller-supplied; dataset-root resolution stays in
:mod:`finguard.config` (ADR-0003 — no hardcoded dataset locations here).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from finguard.schema import (
    CANONICAL_COLUMNS,
    SchemaValidationError,
    normalize_ibm_aml_columns,
    validate_transactions,
)

__all__ = [
    "ConversionReport",
    "convert_ibm_aml_csv_to_parquet",
    "ingest_ibm_aml_csv",
    "load_transaction_parquet",
]

#: Chunk size (rows) for streaming CSV reads; ~1 M rows keeps memory in the
#: low hundreds of MB for the IBM AML column profile.
DEFAULT_CHUNK_ROWS = 1_000_000

_RAW_DTYPES: dict[str, str] = {
    "From Bank": "int64",
    "Account": "string",
    "To Bank": "int64",
    "Account.1": "string",
    "Amount Received": "float64",
    "Receiving Currency": "string",
    "Amount Paid": "float64",
    "Payment Currency": "string",
    "Payment Format": "string",
    "Is Laundering": "int64",
}


@dataclass(frozen=True)
class ConversionReport:
    """Facts recorded for the manifest when a CSV is converted."""

    csv_path: Path
    parquet_path: Path
    rows: int
    laundering_rows: int
    csv_bytes: int
    parquet_bytes: int


def _normalized_chunks(csv_path: Path, chunk_rows: int) -> Iterator[pd.DataFrame]:
    """Yield validated, canonically-named chunks of the raw IBM AML CSV."""
    for chunk in pd.read_csv(
        csv_path,
        dtype=_RAW_DTYPES,
        chunksize=chunk_rows,
    ):
        yield validate_transactions(normalize_ibm_aml_columns(chunk))


def ingest_ibm_aml_csv(
    csv_path: str | Path, *, chunk_rows: int = DEFAULT_CHUNK_ROWS
) -> pd.DataFrame:
    """Read a raw IBM AML transaction CSV into a validated canonical frame.

    Rows are assigned sequential ``tx_id`` values across the whole file, in
    file order (which for IBM AML is *not* globally time-ordered).

    Raises:
        FileNotFoundError: If *csv_path* does not exist.
        SchemaValidationError: If any chunk fails validation.
    """
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Transaction CSV not found: {path}")

    parts: list[pd.DataFrame] = []
    offset = 0
    for chunk in _normalized_chunks(path, chunk_rows):
        chunk = chunk.assign(tx_id=pd.RangeIndex(offset, offset + len(chunk), dtype="int64"))
        offset += len(chunk)
        parts.append(chunk)

    if not parts:  # header-only CSV
        return pd.DataFrame(
            {
                "tx_id": pd.Series(dtype="int64"),
                "timestamp": pd.Series(dtype="datetime64[ns]"),
                "from_bank": pd.Series(dtype="int64"),
                "from_account": pd.Series(dtype="string"),
                "to_bank": pd.Series(dtype="int64"),
                "to_account": pd.Series(dtype="string"),
                "amount_received": pd.Series(dtype="float64"),
                "receiving_currency": pd.Series(dtype="string"),
                "amount_paid": pd.Series(dtype="float64"),
                "payment_currency": pd.Series(dtype="string"),
                "payment_format": pd.Series(dtype="string"),
                "is_laundering": pd.Series(dtype="int64"),
            }
        )
    return pd.concat(parts, ignore_index=True)[list(CANONICAL_COLUMNS)]


def convert_ibm_aml_csv_to_parquet(
    csv_path: str | Path,
    parquet_path: str | Path,
    *,
    chunk_rows: int = DEFAULT_CHUNK_ROWS,
) -> ConversionReport:
    """Stream-convert a raw IBM AML CSV to Parquet (snappy, validated).

    The Parquet file stores the canonical schema in ``timestamp`` order (a
    stable total order for deterministic downstream splits) with sequential
    ``tx_id`` renumbered after sorting.

    Raises:
        FileNotFoundError: If *csv_path* does not exist.
        SchemaValidationError: If any chunk fails validation.
    """
    src = Path(csv_path)
    dst = Path(parquet_path)
    if not src.is_file():
        raise FileNotFoundError(f"Transaction CSV not found: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)

    schema = pa.schema(
        [
            ("tx_id", pa.int64()),
            # pandas 3 default resolution; keeps dtype stable end to end.
            ("timestamp", pa.timestamp("us")),
            ("from_bank", pa.int64()),
            ("from_account", pa.string()),
            ("to_bank", pa.int64()),
            ("to_account", pa.string()),
            ("amount_received", pa.float64()),
            ("receiving_currency", pa.string()),
            ("amount_paid", pa.float64()),
            ("payment_currency", pa.string()),
            ("payment_format", pa.string()),
            ("is_laundering", pa.int64()),
        ]
    )

    # Chunks are read, normalized and validated one at a time (bounded memory
    # for the read/validate step), collected, then sorted by timestamp once
    # and written. Peak memory is roughly one validated copy of the data —
    # acceptable for the ≤650 MB Small variants, which are the only files in
    # initial scope (Medium/Large would need a spill-to-disk merge first).
    parts: list[pd.DataFrame] = []
    for chunk in _normalized_chunks(src, chunk_rows):
        parts.append(chunk)
    rows = sum(len(p) for p in parts)
    if rows == 0:
        raise SchemaValidationError(f"Transaction CSV is empty: {src}")

    combined = (
        pd.concat(parts, ignore_index=True)
        .sort_values("timestamp", kind="mergesort")
        .reset_index(drop=True)
    )
    combined["tx_id"] = pd.RangeIndex(rows, dtype="int64")
    combined = combined[list(CANONICAL_COLUMNS)]

    table = pa.Table.from_pandas(combined, schema=schema, preserve_index=False)
    pq.write_table(table, dst, compression="snappy")

    return ConversionReport(
        csv_path=src,
        parquet_path=dst,
        rows=rows,
        laundering_rows=int(combined["is_laundering"].sum()),
        csv_bytes=src.stat().st_size,
        parquet_bytes=dst.stat().st_size,
    )


def load_transaction_parquet(parquet_path: str | Path) -> pd.DataFrame:
    """Load a canonical transaction Parquet file produced by this package.

    Raises:
        FileNotFoundError: If *parquet_path* does not exist.
        SchemaValidationError: If the file's columns do not match the
            canonical schema.
    """
    path = Path(parquet_path)
    if not path.is_file():
        raise FileNotFoundError(f"Transaction Parquet not found: {path}")
    df = pq.read_table(path).to_pandas()
    missing = [c for c in CANONICAL_COLUMNS if c not in df.columns]
    if missing:
        raise SchemaValidationError(
            "Parquet file is missing canonical columns: " + ", ".join(missing)
        )
    return df[list(CANONICAL_COLUMNS)]
