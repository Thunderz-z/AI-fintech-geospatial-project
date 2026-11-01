"""Seed the FinGuard investigation queue for the demo UI.

Two idempotent sources, both real (synthetic IBM AML) data:

1. ``--from-evidence``: enqueue every alert already exported as an
   ``EvidenceContract`` bundle (``processed/HI-Small_alert-evidence.jsonl``).
   These carry their claim id, so the UI's evidence view works end to end.
2. ``--detect N``: run the fan-in detector on the TEST period of the cached
   HI-Small parquet (same parameters as the ranking evaluation) and enqueue
   the N strongest alerts by distinct-sender count. These are detector-score
   orderings, not the trained ranker — the ``score.note`` says so.

Existing enqueues are never duplicated: evidence contracts are matched by
claim id, detector alerts by (typology, account, first tx id).

    uv run --project projects/finguard python \
        projects/finguard/scripts/seed_investigation_queue.py --from-evidence --detect 10
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from finguard.config import data_dir
from finguard.graph import detect_fan_in
from finguard.investigation import InvestigationQueue


def _existing_claim_ids(queue: InvestigationQueue) -> set[str]:
    return {
        record.evidence_claim_id
        for record in queue.list_all()
        if record.evidence_claim_id
    }


def _existing_detector_keys(queue: InvestigationQueue) -> set[tuple[str, str, int]]:
    return {
        (record.typology, record.account, record.tx_ids[0] if record.tx_ids else -1)
        for record in queue.list_all()
    }


def seed_from_evidence(queue: InvestigationQueue, root: Path) -> int:
    path = root / "processed" / "HI-Small_alert-evidence.jsonl"
    if not path.is_file():
        print(f"Evidence bundle missing: {path} (run scripts/export_alert_evidence.py first)")
        return 0
    seen = _existing_claim_ids(queue)
    added = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        contract = json.loads(line)
        claim_id = contract.get("claim_id")
        if not claim_id or claim_id in seen:
            continue
        methodology = contract.get("methodology") or {}
        typology = str(methodology.get("name", "unknown")).removesuffix("_detector")
        # The focal account is the receiver in the first transaction evidence
        # ref ("tx SENDER -> RECEIVER at ...") — robust, unlike claim text.
        account = "unknown"
        for ref in contract.get("evidence", []):
            if str(ref.get("evidence_type")) != "transaction_record":
                continue
            match = re.search(r"tx\s+\S+\s*->\s*(\S+)", str(ref.get("description", "")))
            if match:
                account = match.group(1)
                break
        parameters = dict(methodology.get("parameters") or {})
        parameters.pop("window", None)
        tx_ids = []
        for ref in contract.get("evidence", []):
            if str(ref.get("evidence_type")) != "transaction_record":
                continue
            raw = ref.get("metadata", {}).get("tx_id")
            try:
                tx_ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        queue.enqueue(
            typology=typology,
            account=account,
            tx_ids=tuple(tx_ids) or (0,),
            score={
                **{
                    key: value
                    for key, value in parameters.items()
                    if not str(key).startswith("window")
                },
                "total_in": parameters.get("total_amount"),
                "note": "exported evidence-contract alert (see claim id)",
            },
            rank=None,
            evidence_claim_id=claim_id,
            actor="seed-script",
        )
        added += 1
    return added


def seed_from_detection(queue: InvestigationQueue, root: Path, limit: int) -> int:
    import pandas as pd

    from finguard.splitting import temporal_split

    parquet = root / "processed" / "HI-Small_trans.parquet"
    if not parquet.is_file():
        print(f"Parquet missing: {parquet} (run scripts/ingest_raw.py first)")
        return 0
    tx = pd.read_parquet(parquet)
    # The project's own temporal split (same boundaries as every evaluation).
    split = temporal_split(tx, timestamp_col="timestamp")
    test_period = split.test
    print(f"fan-in detection on test period ({len(test_period):,} rows)...")
    alerts = detect_fan_in(test_period, min_senders=4, window=pd.Timedelta(days=3))
    alerts.sort(key=lambda a: -a.score.get("distinct_senders", 0))

    seen = _existing_detector_keys(queue)
    added = 0
    for alert in alerts:
        if added >= limit:
            break
        key = (alert.typology, alert.account, alert.tx_ids[0] if alert.tx_ids else -1)
        if key in seen:
            continue
        seen.add(key)
        queue.enqueue(
            typology=alert.typology,
            account=alert.account,
            tx_ids=alert.tx_ids,
            score={**alert.score, "note": "detector-score order (not the trained ranker)"},
            rank=None,
            evidence_claim_id=None,
            actor="seed-script",
        )
        added += 1
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-evidence", action="store_true", help="enqueue exported contracts")
    parser.add_argument(
        "--detect", type=int, default=0, metavar="N",
        help="enqueue N fresh fan-in alerts",
    )
    args = parser.parse_args()
    if not args.from_evidence and not args.detect:
        parser.error("choose at least one source: --from-evidence and/or --detect N")

    queue = InvestigationQueue()
    root = data_dir()
    added = 0
    if args.from_evidence:
        count = seed_from_evidence(queue, root)
        print(f"evidence contracts enqueued: {count}")
        added += count
    if args.detect:
        count = seed_from_detection(queue, root, args.detect)
        print(f"detector alerts enqueued: {count}")
        added += count
    print(f"queue now holds {len(queue.list_all())} alerts "
          f"({len(queue.list_all(status='open'))} open)")
    return 0 if added or queue.list_all() else 1


if __name__ == "__main__":
    sys.exit(main())
