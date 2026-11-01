"""Export EvidenceContract bundles for top-ranked fan-in alerts (M1.5/F2).

Re-runs the F1 ranking protocol (temporal split -> per-period detection ->
ranker trained on train-period alerts), takes the top alerts at the budget
from the TEST period and writes one ``EvidenceContract`` per alert as JSON
lines to ``<root>/finguard/processed/<id>_alert-evidence.jsonl``.

Reproduce with:

    uv run python projects/finguard/scripts/export_alert_evidence.py HI-Small

Each contract states only a *suspicious pattern* claim on SYNTHETIC data;
abstentions appear when evidence is thin or unresolvable.
"""

from __future__ import annotations

import argparse

import pandas as pd

from finguard.config import data_subdir
from finguard.evidence import alerts_to_evidence_contracts
from finguard.graph import detect_fan_in
from finguard.ingest import load_transaction_parquet
from finguard.patterns import parse_patterns_file
from finguard.ranking import fan_in_alert_features, score_alerts, train_alert_ranker
from finguard.splitting import temporal_split


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_id", default="HI-Small", nargs="?")
    parser.add_argument("--budget", type=float, default=0.001)
    args = parser.parse_args(argv)

    processed = data_subdir("processed", create=True)
    raw = data_subdir("raw")
    tx = load_transaction_parquet(processed / f"{args.dataset_id}_trans.parquet")
    patterns = parse_patterns_file(str(raw / f"{args.dataset_id}_Patterns.txt"))
    planted = patterns.loc[patterns["typology"] == "fan_in", "tx_keys"].tolist()
    parquet_path = str(processed / f"{args.dataset_id}_trans.parquet")

    split = temporal_split(tx, timestamp_col="timestamp")

    period_feats = {}
    for name, part in (("train", split.train), ("validation", split.validation)):
        alerts = detect_fan_in(part, min_senders=4, window=pd.Timedelta(days=3))
        period_feats[name] = fan_in_alert_features(part, alerts)
    # Label train/validation alerts for the ranker (ground truth, training only).
    tx_lookup = {
        int(r.tx_id): (r.from_account, r.to_account, r.timestamp)
        for r in tx[["tx_id", "from_account", "to_account", "timestamp"]].itertuples(index=False)
    }
    from finguard.ranking import label_alerts

    model, info = train_alert_ranker(
        label_alerts(period_feats["train"], planted, tx_lookup),
        label_alerts(period_feats["validation"], planted, tx_lookup),
    )

    test_alerts = detect_fan_in(
        split.test, min_senders=4, window=pd.Timedelta(days=3)
    )
    test_feats = fan_in_alert_features(split.test, test_alerts)
    scores = score_alerts(model, test_feats)
    order = scores.argsort(kind="mergesort")[::-1]
    n_flag = max(1, int(args.budget * len(test_feats)))
    top_idx = sorted(order[:n_flag].tolist())

    ranked_alerts = [test_alerts[i] for i in top_idx]
    ranks = {
        pos: {"score": float(scores[i]), "rank": pos + 1, "budget": args.budget}
        for pos, i in enumerate(top_idx)
    }
    contracts = alerts_to_evidence_contracts(
        ranked_alerts,
        split.test,
        dataset_id=args.dataset_id,
        parquet_path=parquet_path,
        ranks=ranks,
    )

    out_path = processed / f"{args.dataset_id}_alert-evidence.jsonl"
    with open(out_path, "w", encoding="utf-8") as handle:
        for contract in contracts:
            handle.write(contract.model_dump_json() + "\n")

    abstained = sum(1 for c in contracts if c.abstention.abstained)
    print(
        f"[{args.dataset_id}] exported {len(contracts)} EvidenceContract bundles "
        f"(top {args.budget:.2%} of {len(test_feats):,} test alerts) -> {out_path}"
    )
    print(f"  abstentions: {abstained}; ranker train alerts: {info['train_alerts']:,}")
    for contract in contracts[:3]:
        print(f"  [{contract.claim_id[:8]}] refs={len(contract.evidence)} "
              f"confidence={contract.confidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
