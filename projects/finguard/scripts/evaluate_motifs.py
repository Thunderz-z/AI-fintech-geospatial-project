"""Evaluate fan-in / structuring detectors against real planted ground truth.

Usage:

    uv run python projects/finguard/scripts/evaluate_motifs.py HI-Small

Runs :func:`finguard.graph.detect_fan_in` and :func:`detect_structuring` on
``<root>/finguard/processed/<id>_trans.parquet`` and scores them against the
AMLSim pattern attempts in ``<root>/finguard/raw/<id>_Patterns.txt``:

* alert precision — fraction of detector alerts whose transaction keys
  overlap a planted attempt of the SAME typology
* attempt recall — fraction of planted attempts whose keys are covered
  (>= 50% overlap) by some detector alert

A detected motif is a suspicious pattern, not a laundering finding; the
ground truth here labels *planted patterns* in SYNTHETIC data.
"""

from __future__ import annotations

import argparse
import json
import time

import pandas as pd

from finguard.config import data_subdir
from finguard.graph import detect_fan_in, detect_structuring
from finguard.patterns import parse_patterns_file


def _alert_keys(alert, tx_lookup: dict[int, tuple[str, str, object]]) -> set:
    return {tx_lookup[t] for t in alert.tx_ids if t in tx_lookup}


def _evaluate(
    alerts,
    planted: list[set],
    tx_lookup: dict[int, tuple[str, str, object]],
    *,
    min_senders: int = 0,
    min_cover: float = 0.5,
) -> dict:
    """Score alerts against planted attempts.

    Recall is reported against ALL attempts and against *detectable* attempts
    (attempts whose distinct sender count >= min_senders — a degree-based
    detector cannot catch smaller plants, so the detectable-only recall is
    the fair ceiling-adjusted figure).
    """
    planted_sets = [set(p) for p in planted]
    alert_key_sets = [_alert_keys(a, tx_lookup) for a in alerts]

    tp = sum(1 for keys in alert_key_sets if any(keys & p for p in planted_sets))
    recall_hits = sum(
        1
        for p in planted_sets
        if any(len(keys & p) >= min_cover * len(p) for keys in alert_key_sets)
    )
    detectable = 0
    detectable_hits = 0
    if min_senders > 0:
        for p in planted_sets:
            distinct = len({k[0] for k in p})
            if distinct >= min_senders:
                detectable += 1
                if any(
                    len(keys & p) >= min_cover * len(p) for keys in alert_key_sets
                ):
                    detectable_hits += 1
    return {
        "alerts": len(alerts),
        "alert_precision": round(tp / len(alerts), 4) if alerts else None,
        "planted_attempts": len(planted_sets),
        "attempt_recall": round(recall_hits / len(planted_sets), 4) if planted_sets else None,
        "detectable_attempts": detectable,
        "detectable_attempt_recall": round(detectable_hits / detectable, 4) if detectable else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_id", help="e.g. HI-Small")
    args = parser.parse_args(argv)

    processed = data_subdir("processed", create=True)
    parquet_path = processed / f"{args.dataset_id}_trans.parquet"
    patterns_path = data_subdir("raw") / f"{args.dataset_id}_Patterns.txt"
    if not parquet_path.is_file():
        raise SystemExit(f"Missing {parquet_path}; run ingest_raw.py first")

    from finguard.ingest import load_transaction_parquet

    tx = load_transaction_parquet(parquet_path)
    patterns = parse_patterns_file(str(patterns_path))
    print(
        f"[{args.dataset_id}] {len(tx):,} transactions; "
        f"{len(patterns)} planted attempts across {patterns['typology'].nunique()} types",
        flush=True,
    )

    tx_lookup = {
        int(r.tx_id): (r.from_account, r.to_account, r.timestamp)
        for r in tx[["tx_id", "from_account", "to_account", "timestamp"]].itertuples(index=False)
    }

    results: dict = {
        "dataset_id": args.dataset_id,
        "data_kind": "synthetic planted-pattern evaluation",
        "note": "detected motifs are suspicious patterns, never laundering findings",
    }

    planted_all = {
        typology: patterns.loc[patterns["typology"] == typology, "tx_keys"].tolist()
        for typology in ("fan_in", "structuring")
    }

    # Fan-in: small parameter grid — real plants range from 1-degree to
    # 16-degree and span hours to days (verified against the Patterns file).
    fan_in_grid = [
        {"min_senders": 4, "window": pd.Timedelta(days=3)},
        {"min_senders": 5, "window": pd.Timedelta(days=3)},
        {"min_senders": 6, "window": pd.Timedelta(days=3)},
    ]
    results["fan_in"] = []
    for params in fan_in_grid:
        t0 = time.perf_counter()
        alerts = detect_fan_in(tx, **params)
        elapsed = time.perf_counter() - t0
        row = _evaluate(
            alerts, planted_all["fan_in"], tx_lookup, min_senders=params["min_senders"]
        )
        row.update({"params": {k: str(v) for k, v in params.items()},
                    "runtime_seconds": round(elapsed, 1)})
        results["fan_in"].append(row)
        print(
            f"[fan_in {params['min_senders']} senders / {params['window']}] "
            f"{row['alerts']} alerts, precision={row['alert_precision']}, "
            f"recall={row['attempt_recall']} "
            f"(detectable-only: {row['detectable_attempt_recall']} of "
            f"{row['detectable_attempts']}) in {elapsed:.1f}s",
            flush=True,
        )

    # Structuring: single default configuration; HI-Small/LI-Small plant no
    # structuring attempts, so ground-truth precision is n/a here — the
    # detector is validated on synthetic fixtures instead.
    t0 = time.perf_counter()
    alerts = detect_structuring(tx)
    elapsed = time.perf_counter() - t0
    row = _evaluate(alerts, planted_all["structuring"], tx_lookup)
    row["runtime_seconds"] = round(elapsed, 1)
    row["note"] = (
        "no planted structuring attempts in this dataset; alert count shows "
        "how often the pattern fires on legitimate traffic (analyst load)"
    )
    results["structuring"] = row
    print(
        f"[structuring] {row['alerts']} alerts; planted ground truth n/a "
        f"(validated on synthetic fixtures)",
        flush=True,
    )

    out_path = processed / f"{args.dataset_id}_motif-evaluation.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"results -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
