"""Evaluate fan-in alert ranking at a fixed alert budget (M1.5/F1).

Protocol (temporal discipline, ADR-0006):

1. Load HI-Small transactions; parse planted fan-in ground truth.
2. Split transactions temporally 60/20/20 (unique-timestamp cutoffs).
3. Run the v0 fan-in detector separately per period.
4. Build ranking features per alert; label alerts by overlap with planted
   attempts (labels are ground truth for training/evaluation only).
5. Train the LightGBM ranker on TRAIN-period alerts (early stopping on
   VALIDATION-period alerts); evaluate on TEST-period alerts.
6. At the 0.1% alert budget (top 0.1% of test-period alerts by score),
   report precision against detectable planted attempts (distinct senders
   >= min_senders) and recall over them, for three modes:
     a) v0 unranked — detector output order over all test alerts
     b) heuristic — sort by receiver_age_days ascending (freshest first)
     c) ranker — learned scores

Reproduce with:

    uv run python projects/finguard/scripts/evaluate_alert_ranking.py HI-Small

All data is SYNTHETIC IBM AML; a matched alert is a recovered *planted
pattern*, not a laundering finding.
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd

from finguard.config import data_subdir
from finguard.graph import detect_fan_in
from finguard.ingest import load_transaction_parquet
from finguard.patterns import parse_patterns_file
from finguard.ranking import (
    RANKING_FEATURE_COLUMNS,
    fan_in_alert_features,
    label_alerts,
    score_alerts,
    train_alert_ranker,
)
from finguard.splitting import temporal_split


def _attempts_touching(
    planted: list[set], lo: pd.Timestamp, hi: pd.Timestamp
) -> list[set]:
    """Attempts with at least one transaction in the (lo, hi] time range."""
    return [
        p
        for p in planted
        if any(lo < ts <= hi for (_, _, ts) in p)
    ]


def _period_metrics(
    features: pd.DataFrame,
    scores: np.ndarray | None,
    planted_in_period: list[set],
    tx_lookup: dict[int, tuple],
    min_senders: int,
    budget: float,
) -> dict:
    """Precision/recall at a top-budget cut of alerts (by score when given).

    ``planted_in_period`` must already be restricted to attempts that touch
    the evaluation period — attempts living entirely in earlier periods can
    never be caught here and would only inflate the recall denominator.
    Reports precision two ways: against any planted overlap (``precision``)
    and against detectable attempts only (``precision_on_detectable``) —
    the latter is the F1 headline because the detector can never match
    sub-threshold plants.
    """
    labels = features["label"].to_numpy()
    n = len(features)
    n_flag = max(1, int(np.ceil(budget * n)))
    if scores is None:
        order = np.arange(n)  # v0: detector output order, unranked
    else:
        order = np.argsort(scores, kind="mergesort")[::-1]
    top = order[:n_flag]
    tp = int(labels[top].sum())

    detectable = [
        planted
        for planted in planted_in_period
        if len({k[0] for k in planted}) >= min_senders
    ]
    detectable_keys: set = set()
    for planted in detectable:
        detectable_keys |= planted
    tp_detectable = 0
    for i in top:
        keys = {tx_lookup[t] for t in features.iloc[i]["tx_ids"] if t in tx_lookup}
        if keys & detectable_keys:
            tp_detectable += 1

    caught = 0
    for planted in detectable:
        if any(
            len({tx_lookup[t] for t in features.iloc[i]["tx_ids"] if t in tx_lookup} & planted)
            >= 0.5 * len(planted)
            for i in top
        ):
            caught += 1
    return {
        "alerts_total": n,
        "budget": budget,
        "flagged": n_flag,
        "true_positives": tp,
        "precision": round(tp / n_flag, 4),
        "precision_on_detectable": round(tp_detectable / n_flag, 4),
        "planted_attempts_in_period": len(planted_in_period),
        "detectable_attempts": len(detectable),
        "detectable_recall_at_budget": round(caught / len(detectable), 4) if detectable else None,
        "detectable_caught": caught,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_id", default="HI-Small", nargs="?")
    parser.add_argument("--min-senders", type=int, default=4)
    parser.add_argument("--window-days", type=int, default=3)
    parser.add_argument("--budget", type=float, default=0.001)
    args = parser.parse_args(argv)

    processed = data_subdir("processed", create=True)
    tx = load_transaction_parquet(processed / f"{args.dataset_id}_trans.parquet")
    patterns = parse_patterns_file(str(data_subdir("raw") / f"{args.dataset_id}_Patterns.txt"))
    planted = patterns.loc[patterns["typology"] == "fan_in", "tx_keys"].tolist()
    tx_lookup = {
        int(r.tx_id): (r.from_account, r.to_account, r.timestamp)
        for r in tx[["tx_id", "from_account", "to_account", "timestamp"]].itertuples(index=False)
    }
    window = pd.Timedelta(days=args.window_days)
    split = temporal_split(tx, timestamp_col="timestamp")
    print(
        f"[{args.dataset_id}] {len(tx):,} tx; {len(planted)} planted fan-in attempts; "
        f"split {len(split.train):,}/{len(split.validation):,}/{len(split.test):,}",
        flush=True,
    )

    period_frames: dict[str, pd.DataFrame] = {}
    period_features: dict[str, pd.DataFrame] = {}
    t0 = time.perf_counter()
    for name, part in (
        ("train", split.train),
        ("validation", split.validation),
        ("test", split.test),
    ):
        alerts = detect_fan_in(part, min_senders=args.min_senders, window=window)
        feats = fan_in_alert_features(part, alerts)
        feats = label_alerts(feats, planted, tx_lookup)
        period_frames[name] = part
        period_features[name] = feats
        print(
            f"[{name}] {len(part):,} tx -> {len(feats):,} alerts, "
            f"{int(feats['label'].sum())} planted-overlapping",
            flush=True,
        )

    model, ranker_info = train_alert_ranker(
        period_features["train"], period_features["validation"]
    )
    print(
        f"ranker trained: {ranker_info['train_alerts']:,} train alerts "
        f"({ranker_info['train_positives']} positive), "
        f"n_estimators={ranker_info['n_estimators']}",
        flush=True,
    )
    elapsed = time.perf_counter() - t0

    test_feats = period_features["test"]
    ranker_scores = score_alerts(model, test_feats)
    # Heuristic: freshest receiver first (younger account = more plant-like).
    heuristic_scores = -test_feats["receiver_age_days"].to_numpy(dtype="float64")

    # Recall denominator: attempts touching the test period only.
    planted_test = _attempts_touching(
        planted, split.validation_end, pd.Timestamp.max
    )
    budgets = sorted({0.001, 0.005, 0.01, args.budget})
    mode_scores = {
        "v0_unranked": None,
        "heuristic_receiver_age": heuristic_scores,
        "learned_ranker": ranker_scores,
    }
    grid: dict[str, list[dict]] = {}
    for mode, scores in mode_scores.items():
        grid[mode] = [
            _period_metrics(
                test_feats, scores, planted_test, tx_lookup, args.min_senders, b
            )
            for b in budgets
        ]
    primary = 0.001
    v0 = grid["v0_unranked"][budgets.index(primary)]
    heuristic = grid["heuristic_receiver_age"][budgets.index(primary)]
    ranker = grid["learned_ranker"][budgets.index(primary)]

    payload = {
        "dataset_id": args.dataset_id,
        "data_kind": "SYNTHETIC IBM AML planted-pattern evaluation; not real-world performance",
        "protocol": {
            "detector": f"fan_in min_senders={args.min_senders}, window={window}",
            "split": "temporal 60/20/20 on unique timestamps",
            "ranker_training": "TRAIN-period alerts only; early stopping on VALIDATION",
            "evaluation_period": "TEST-period alerts",
            "budget_semantics": f"top {args.budget:.2%} of test-period alerts by score",
            "precision_denominator": "flagged alerts",
            "recall_denominator": (
                "detectable planted attempts in the test period "
                "(distinct senders >= min_senders)"
            ),
            "min_senders": args.min_senders,
            "window_days": args.window_days,
            "budget": args.budget,
        },
        "ranker": {
            "train_alerts": ranker_info["train_alerts"],
            "train_positives": ranker_info["train_positives"],
            "validation_alerts": ranker_info["validation_alerts"],
            "validation_positives": ranker_info["validation_positives"],
            "n_estimators": ranker_info["n_estimators"],
            "feature_importance_gain": ranker_info["feature_importance"],
            "feature_columns": list(RANKING_FEATURE_COLUMNS),
        },
        "test_period": {
            "planted_attempts_in_period": len(planted_test),
            "primary_budget": primary,
            "v0_unranked": v0,
            "heuristic_receiver_age": heuristic,
            "learned_ranker": ranker,
            "budget_grid": {
                str(b): {mode: grid[mode][i] for mode in grid}
                for i, b in enumerate(budgets)
            },
        },
        "runtime_seconds": round(elapsed, 1),
    }
    out_path = processed / f"{args.dataset_id}_fanin-ranking-metrics.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\n=== {args.dataset_id} fan-in alert ranking (SYNTHETIC DATA) ===")
    print(f"primary budget {primary:.2%} of {v0['alerts_total']:,} test alerts; "
          f"detectable planted attempts: {v0['detectable_attempts']}")
    for name, row in (
        ("v0 unranked        ", v0),
        ("heuristic (age)    ", heuristic),
        ("learned ranker     ", ranker),
    ):
        print(
            f"{name} flagged={row['flagged']:>4} "
            f"precision_on_detectable={row['precision_on_detectable']:.4f} "
            f"detectable_recall={row['detectable_recall_at_budget']} "
            f"({row['detectable_caught']}/{row['detectable_attempts']})"
        )
    print("budget grid (precision_on_detectable / detectable_recall):")
    for mode, rows in grid.items():
        cells = "  ".join(
            f"{b:.2%}: {r['precision_on_detectable']:.3f}/{r['detectable_recall_at_budget']}"
            for b, r in zip(budgets, rows, strict=True)
        )
        print(f"  {mode:<24} {cells}")
    print(f"feature importance (gain): {ranker_info['feature_importance']}")
    print(f"metrics -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
