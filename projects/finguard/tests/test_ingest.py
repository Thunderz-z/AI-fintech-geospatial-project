"""Ingestion + Parquet conversion tests (synthetic CSVs, no real datasets)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from finguard.config import DATA_SUBDIRS, data_subdir
from finguard.ingest import (
    convert_ibm_aml_csv_to_parquet,
    ingest_ibm_aml_csv,
    load_transaction_parquet,
)
from finguard.schema import (
    CANONICAL_COLUMNS,
    IBM_AML_COLUMN_MAP,
    SchemaValidationError,
)
from finguard.synthetic import generate_synthetic_transactions


@pytest.fixture
def ibm_style_csv(tmp_path: Path, ibm_raw_transactions: pd.DataFrame) -> Path:
    csv_path = tmp_path / "Synthetic_Trans.csv"
    ibm_raw_transactions.to_csv(csv_path, index=False)
    return csv_path


def test_ingest_assigns_sequential_ids_and_validates(
    ibm_style_csv: Path, valid_transactions: pd.DataFrame
) -> None:
    ingested = ingest_ibm_aml_csv(ibm_style_csv)

    assert list(ingested.columns) == list(CANONICAL_COLUMNS)
    assert len(ingested) == len(valid_transactions)
    assert ingested["tx_id"].is_unique
    assert (ingested["tx_id"] == pd.RangeIndex(len(ingested))).all()
    # Rows must match the source content (order preserved from the CSV).
    assert_frame_equal(
        ingested.drop(columns=["tx_id"]).reset_index(drop=True),
        valid_transactions.drop(columns=["tx_id"], errors="ignore").reset_index(drop=True),
        check_dtype=False,
    )


def test_ingest_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ingest_ibm_aml_csv(tmp_path / "nope.csv")


def test_ingest_rejects_schema_violation(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    pd.DataFrame({"From Bank": [1], "Account": ["ABC"]}).to_csv(bad, index=False)
    with pytest.raises(SchemaValidationError, match="missing"):
        ingest_ibm_aml_csv(bad)


def test_convert_to_parquet_report_and_ordering(
    tmp_path: Path, ibm_raw_transactions: pd.DataFrame
) -> None:
    csv_path = tmp_path / "Synthetic_Trans.csv"
    ibm_raw_transactions.to_csv(csv_path, index=False)
    parquet_path = tmp_path / "processed" / "synthetic.parquet"

    report = convert_ibm_aml_csv_to_parquet(csv_path, parquet_path)

    assert report.rows == len(ibm_raw_transactions)
    assert report.laundering_rows == int(ibm_raw_transactions["Is Laundering"].sum())
    assert report.csv_bytes == csv_path.stat().st_size
    assert report.parquet_bytes > 0
    assert report.parquet_path == parquet_path

    loaded = load_transaction_parquet(parquet_path)
    assert loaded["timestamp"].is_monotonic_increasing  # conversion sorts by time
    assert loaded["tx_id"].is_unique
    assert list(loaded.columns) == list(CANONICAL_COLUMNS)
    # Same content, reordered by time; amounts/flags survive the roundtrip.
    assert sorted(loaded["amount_paid"].round(2)) == sorted(
        ibm_raw_transactions["Amount Paid"].round(2)
    )
    assert int(loaded["is_laundering"].sum()) == int(
        ibm_raw_transactions["Is Laundering"].sum()
    )


def test_parquet_roundtrip_preserves_synthetic_fixtures(tmp_path: Path) -> None:
    transactions, motifs = generate_synthetic_transactions(n_normal=300, seed=5)
    inverse = {v: k for k, v in IBM_AML_COLUMN_MAP.items()}
    raw = transactions.drop(columns=["tx_id"]).rename(columns=inverse)
    raw["Timestamp"] = raw["Timestamp"].dt.strftime("%Y/%m/%d %H:%M")

    csv_path = tmp_path / "gen.csv"
    parquet_path = tmp_path / "gen.parquet"
    raw.to_csv(csv_path, index=False)
    report = convert_ibm_aml_csv_to_parquet(csv_path, parquet_path)

    assert report.rows == len(transactions)
    loaded = load_transaction_parquet(parquet_path)
    # Planted motifs survive conversion: same flagged tx count, same motif
    # membership by (from, to, timestamp) keys.
    assert int(loaded["is_laundering"].sum()) == int(transactions["is_laundering"].sum())
    keyed_real = {
        (r.from_account, r.to_account, r.timestamp)
        for r in transactions.loc[transactions["is_laundering"] == 1].itertuples()
    }
    keyed_loaded = {
        (r.from_account, r.to_account, r.timestamp)
        for r in loaded.loc[loaded["is_laundering"] == 1].itertuples()
    }
    assert keyed_real == keyed_loaded
    assert sum(len(m.tx_ids) for m in motifs) == len(keyed_real)


def test_load_rejects_foreign_parquet(tmp_path: Path) -> None:
    foreign = tmp_path / "foreign.parquet"
    pd.DataFrame({"a": [1]}).to_parquet(foreign)
    with pytest.raises(SchemaValidationError, match="missing"):
        load_transaction_parquet(foreign)


def test_load_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_transaction_parquet(tmp_path / "nope.parquet")


def test_data_subdirs_resolve_under_data_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PORTFOLIO_DATA_ROOT", str(tmp_path))

    for name in DATA_SUBDIRS:
        resolved = data_subdir(name, create=True)
        assert resolved.parent == (tmp_path / "finguard").resolve()
        assert resolved.is_dir()

    with pytest.raises(ValueError, match="Unknown data subdirectory"):
        data_subdir("../escape")
