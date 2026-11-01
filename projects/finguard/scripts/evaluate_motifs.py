"""Evaluate motif detectors against real planted ground truth (v2, M1.5/F3).

Usage:

    uv run python projects/finguard/scripts/evaluate_motifs.py HI-Small

Runs the fan-in / fan-out / cycle / structuring detectors on
``<root>/finguard/processed/<id>_trans.parquet`` and scores them against the
AMLSim pattern attempts in ``<root>/finguard/raw/<id>_Patterns.txt``:

* alert precision — fraction of detector alerts whose transaction keys
  overlap a planted attempt of the SAME typology
* attempt recall — fraction of planted attempts whose keys are covered
  (>= 50% overlap) by some detector alert, overall and against *detectable*
  attempts only (those the detector configuration could in principle catch)

v2 adds fan-out and cycle (M1.5/F3) and writes
``<id>_motif-evaluation-v2.json`` (the v0 file is kept for the record).
A detected motif is a suspicious pattern, not a laundering finding; the
ground truth labels *planted patterns* in SYNTHETIC data.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable

import pandas as pd

from finguard.config import data_subdir
from finguard.graph import detect_cycle, detect_fan_in, detect_fan_out, detect_structuring
from finguard.patterns import parse_patterns_file


def _alert_keys(alert, tx_lookup: dict[int, tuple[str, str, object]]) -> set:
    return {tx_lookup[t] for t in alert.tx_ids if t in tx_lookup}


def _evaluate(
    alerts,
    planted: list[set],
    tx_lookup: dict[int, tuple[str, str, object]],
    *,
    detectable_filter: Callable[[set], bool] | None = None,
    min_cover: float = 0.5,
) -> dict:
    """Score alerts against planted attempts.

    ``detectable_filter`` marks attempts the detector configuration could in
    principle catch (e.g. distinct senders >= min_senders for fan-in, ring
    length within [min_length, max_length] for cycle); recall against that
    subset is the fair ceiling-adjusted figure.
    """
    planted_sets = [set(p) for p in planted]
    alert_key_sets = [_alert_keys(a, tx_lookup) for a in alerts]

    tp = sum(1 for keys in alert_key_sets if any(keys & p for p in planted_sets))
    recall_hits = sum(
        1
        for p in planted_sets
        if any(len(keys & p) >= min_cover * len(p) for keys in alert_key_sets)
    )
    detectable_hits = 0
    detectable = 0
    if detectable_filter is not None:
        for p in planted_sets:
            if detectable_filter(p):
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
        "detectable_attempts": detectable if detectable_filter else None,
        "detectable_attempt_recall": (
            round(detectable_hits / detectable, 4) if detectable_filter and detectable else None
        ),
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
        for typology in ("fan_in", "fan_out", "cycle", "structuring")
    }

    def _run_grid(name, detector, grid, planted, detectable_filter, note=None):
        results[name] = []
        for params in grid:
            t0 = time.perf_counter()
            alerts = detector(tx, **params)
            elapsed = time.perf_counter() - t0
            row = _evaluate(
                alerts, planted, tx_lookup, detectable_filter=detectable_filter
            )
            row.update(
                {
                    "params": {k: str(v) for k, v in params.items()},
                    "runtime_seconds": round(elapsed, 1),
                }
            )
            if note:
                row["note"] = note
            results[name].append(row)
            print(
                f"[{name} {params}] {row['alerts']} alerts, "
                f"precision={row['alert_precision']}, recall={row['attempt_recall']}"
                + (
                    f" (detectable-only: {row['detectable_attempt_recall']} of "
                    f"{row['detectable_attempts']})"
                    if row["detectable_attempts"]
                    else ""
                )
                + f" in {elapsed:.1f}s",
                flush=True,
            )

    # Fan-in: real plants range from 1-degree to 16-degree, hours to days.
    _run_grid(
        "fan_in",
        detect_fan_in,
        [
            {"min_senders": s, "window": pd.Timedelta(days=3)}
            for s in (4, 5, 6)
        ],
        planted_all["fan_in"],
        lambda p: len({k[0] for k in p}) >= 4,
    )

    # Fan-out (M1.5/F3): mirror protocol.
    _run_grid(
        "fan_out",
        detect_fan_out,
        [
            {"min_receivers": r, "window": pd.Timedelta(days=3)}
            for r in (4, 5, 6)
        ],
        planted_all["fan_out"],
        lambda p: len({k[1] for k in p}) >= 4,
    )

    # Cycle (M1.5/F3): rings are currency-converting with unequal amounts.
    # The degree cap is the sensitivity knob: 30 is conservative (precise,
    # low recall); 100 recovers most detectable rings. Detectable = ring
    # length <= 10 (the loosest max_length in this grid).
    _run_grid(
        "cycle",
        detect_cycle,
        [
            {"min_length": 3, "max_length": 8, "window": pd.Timedelta(days=3), "degree_cap": 30},
            {"min_length": 3, "max_length": 10, "window": pd.Timedelta(days=5), "degree_cap": 30},
            {"min_length": 3, "max_length": 10, "window": pd.Timedelta(days=5), "degree_cap": 100},
            {"min_length": 3, "max_length": 10, "window": pd.Timedelta(days=5), "degree_cap": 200},
        ],
        planted_all["cycle"],
        lambda p: 3 <= len(p) <= 10,
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

    out_path = processed / f"{args.dataset_id}_motif-evaluation-v2.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"results -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
