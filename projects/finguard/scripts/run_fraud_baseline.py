"""Run the M1 fraud baseline on a real IBM AML dataset (M1 step 5).

Usage:

    uv run python projects/finguard/scripts/run_fraud_baseline.py HI-Small

Reads ``<root>/finguard/processed/<id>_trans.parquet`` (produced by
``ingest_raw.py``), builds leakage-safe features, applies the temporal
60/20/20 split, trains the imbalance-aware LightGBM baseline and writes a
metrics JSON + a human-readable summary next to the data. All numbers are
computed from this run; the data is SYNTHETIC and every reported metric is
about recovering planted typologies, not catching real criminals.
"""

from __future__ import annotations

import argparse
import json
import time

from finguard.config import data_subdir
from finguard.features import FEATURE_COLUMNS, build_baseline_features
from finguard.model import train_fraud_baseline
from finguard.splitting import temporal_split


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_id", help="e.g. HI-Small")
    args = parser.parse_args(argv)

    processed = data_subdir("processed", create=True)
    parquet_path = processed / f"{args.dataset_id}_trans.parquet"
    if not parquet_path.is_file():
        raise SystemExit(f"Missing {parquet_path}; run ingest_raw.py first")

    from finguard.ingest import load_transaction_parquet

    t0 = time.perf_counter()
    tx = load_transaction_parquet(parquet_path)
    print(f"[{args.dataset_id}] loaded {len(tx):,} transactions "
          f"({time.perf_counter() - t0:.1f}s)", flush=True)

    t0 = time.perf_counter()
    features = build_baseline_features(tx)
    print(f"[{args.dataset_id}] features built ({time.perf_counter() - t0:.1f}s)",
          flush=True)

    split = temporal_split(features, timestamp_col="timestamp")
    print(
        f"[{args.dataset_id}] split rows train={len(split.train):,} "
        f"valid={len(split.validation):,} test={len(split.test):,} "
        f"boundaries={split.train_end} | {split.validation_end}",
        flush=True,
    )

    model, report = train_fraud_baseline(
        split.train,
        split.validation,
        split.test,
        feature_cols=list(FEATURE_COLUMNS),
        dataset_id=args.dataset_id,
    )

    payload = {
        "dataset_id": report.dataset_id,
        "data_kind": "synthetic (IBM AML planted typologies); NOT real-world performance",
        "rows": report.rows,
        "positives": report.positives,
        "pr_auc_test": report.pr_auc,
        "roc_auc_test": report.roc_auc,
        "best_iteration": report.best_iteration,
        "operating_point_semantics": (
            "top-k% of test scores by rank (budget fixed a priori; "
            "labels used only for evaluation)"
        ),
        "test_operating_points": {
            str(k): v for k, v in report.test_operating_points.items()
        },
        "params": {k: str(v) for k, v in report.params.items()},
        "split_boundaries": {
            "train_end": str(split.train_end),
            "validation_end": str(split.validation_end),
        },
    }
    out_path = processed / f"{args.dataset_id}_baseline-metrics.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\n=== {args.dataset_id} fraud baseline (SYNTHETIC DATA) ===")
    print(f"PR-AUC (test): {report.pr_auc:.4f}   ROC-AUC (test): {report.roc_auc:.4f}")
    print(f"{'budget':>8} | {'flagged':>9} | {'flag frac':>9} | {'precision':>9} | {'recall':>7}")
    for budget, point in report.test_operating_points.items():
        print(
            f"{budget:>8.3%} | {point['flagged']:>9,} | "
            f"{point['flagged_fraction']:>9.4%} | {point['precision']:>9.4f} | "
            f"{point['recall']:>7.4f}"
        )
    print(f"metrics -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
