"""Ingest raw IBM AML CSVs from the data root into Parquet (M1 step 3/4 run).

Usage (from the repository root):

    uv run python projects/finguard/scripts/ingest_raw.py HI-Small LI-Small

Each ``<id>_Trans.csv`` must exist under ``<PORTFOLIO_DATA_ROOT>/finguard/raw``.
Outputs (under ``<PORTFOLIO_DATA_ROOT>/finguard/processed``):

* ``<id>_trans.parquet`` — validated canonical frame, timestamp-ordered
* ``<id>_ingest-report.json`` — ConversionReport facts for the manifest
"""

from __future__ import annotations

import argparse
import json
import sys

from finguard.config import data_subdir
from finguard.ingest import convert_ibm_aml_csv_to_parquet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dataset_ids",
        nargs="+",
        help="Dataset ids, e.g. HI-Small (expects <id>_Trans.csv in raw/)",
    )
    args = parser.parse_args(argv)

    raw_dir = data_subdir("raw")
    processed_dir = data_subdir("processed", create=True)

    exit_code = 0
    for dataset_id in args.dataset_ids:
        csv_path = raw_dir / f"{dataset_id}_Trans.csv"
        parquet_path = processed_dir / f"{dataset_id}_trans.parquet"
        print(f"[{dataset_id}] converting {csv_path} ...", flush=True)
        try:
            report = convert_ibm_aml_csv_to_parquet(csv_path, parquet_path)
        except FileNotFoundError:
            print(f"[{dataset_id}] MISSING: {csv_path}", file=sys.stderr)
            exit_code = 1
            continue
        report_payload = {
            "dataset_id": dataset_id,
            "csv_path": str(report.csv_path),
            "parquet_path": str(report.parquet_path),
            "rows": report.rows,
            "laundering_rows": report.laundering_rows,
            "laundering_rate": round(report.laundering_rows / report.rows, 6),
            "csv_bytes": report.csv_bytes,
            "parquet_bytes": report.parquet_bytes,
        }
        report_path = processed_dir / f"{dataset_id}_ingest-report.json"
        report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
        print(
            f"[{dataset_id}] rows={report.rows:,} "
            f"laundering={report.laundering_rows:,} "
            f"csv={report.csv_bytes / 1e6:.1f} MB parquet={report.parquet_bytes / 1e6:.1f} MB "
            f"-> {report_path}",
            flush=True,
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
