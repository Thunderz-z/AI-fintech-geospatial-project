"""Alert → evidence-contract wiring (M1.5/F2).

Every alert that leaves the detection/ranking stages is packaged as a
``relia.contracts.EvidenceContract``: the claim states only that a
*suspicious pattern* was observed (never a laundering finding — AGENTS.md
rule 7), transaction refs point at concrete rows in the processed Parquet,
the motif parameters and (when present) the ranking stage's score are
recorded, and thin evidence produces an explicit abstention.

This module only consumes the shared contract API in
``relia.contracts`` (no RELIA modifications).
"""

from __future__ import annotations

import pandas as pd

from finguard.graph import MotifAlert
from relia.contracts import (
    AbstentionInfo,
    EvidenceContract,
    EvidenceRef,
    EvidenceType,
    MethodologyInfo,
    ValidationStatus,
)

__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "alert_to_evidence_contract",
    "alerts_to_evidence_contracts",
]

EVIDENCE_SCHEMA_VERSION = "1.0.0"

#: Caps / thresholds for bundle size and the thin-evidence abstention.
MAX_TRANSACTION_REFS = 25
MIN_SUPPORTING_TRANSACTIONS = 3

_TYPLOGY_CLAIMS = {
    "fan_in": "distinct senders converged on the focal account",
    "fan_out": "the focal account dispersed funds to distinct receivers",
    "structuring": "repeated just-below-threshold transfers between a fixed pair",
    "cycle": "funds circulated through a ring of accounts back to origin",
}


def alert_to_evidence_contract(
    alert: MotifAlert,
    tx: pd.DataFrame,
    *,
    dataset_id: str,
    parquet_path: str | None = None,
    rank: dict | None = None,
    detector_version: str = "1.0.0",
) -> EvidenceContract:
    """Package one detector alert as an :class:`EvidenceContract`.

    Args:
        alert: The detector alert (typology, focal account, tx_ids, score).
        tx: The transaction frame the alert was detected on (used to resolve
            transaction refs; ``is_laundering`` is deliberately excluded
            from evidence metadata — it is a dataset label, not evidence an
            analyst should see).
        dataset_id: e.g. ``HI-Small`` (provenance).
        parquet_path: Location of the processed Parquet for ref ``location``.
        rank: Optional ranking-stage output, ``{"score", "rank", "budget"}``;
            when present a MODEL_RESULT ref is added and ``confidence``
            carries the ranker's positive-class probability.
        detector_version: Detector version string for the methodology block.

    Returns:
        A contract with transaction + motif (+ optional model) refs. Thin
        evidence (fewer than :data:`MIN_SUPPORTING_TRANSACTIONS` resolvable
        transactions) yields an explicit abstention; unresolvable tx ids
        yield an abstention with the missing ids listed.
    """
    typology = alert.typology
    pattern_phrase = _TYPLOGY_CLAIMS.get(typology, typology)
    claim = (
        f"Suspicious pattern observed ({typology}, SYNTHETIC IBM AML data): "
        f"{pattern_phrase} around account {alert.account}. A detected motif "
        "is a suspicious pattern, not a finding of money laundering."
    )

    by_id = tx.set_index("tx_id", drop=False)
    resolved = by_id.loc[[t for t in alert.tx_ids if t in by_id.index]]
    missing = [int(t) for t in alert.tx_ids if t not in by_id.index]

    limitations = [
        "synthetic data (IBM AML planted typologies); no real-world performance claim",
        "a detected motif is a suspicious pattern pending human review",
    ]

    # --- Thin / broken evidence -> abstain ---------------------------------
    if len(resolved) < MIN_SUPPORTING_TRANSACTIONS or missing:
        reason = (
            f"insufficient resolvable evidence: {len(resolved)} of "
            f"{len(alert.tx_ids)} alert transactions present in the frame"
            + (f"; missing tx_ids {missing[:10]}" if missing else "")
        )
        return EvidenceContract(
            claim_text=claim,
            evidence=[],
            methodology=MethodologyInfo(
                name=f"{typology}_detector",
                version=detector_version,
                parameters=dict(alert.score),
            ),
            validation_status=ValidationStatus.ABSTAINED,
            limitations=limitations,
            abstention=AbstentionInfo(
                abstained=True,
                reason=reason,
                missing_requirements=[
                    "resolved transaction records for every alert tx_id",
                    f"at least {MIN_SUPPORTING_TRANSACTIONS} supporting transactions",
                ],
            ),
        )

    # --- Evidence refs ------------------------------------------------------
    source = f"finguard.ingest ({dataset_id})"
    location_base = parquet_path or f"{dataset_id}_trans.parquet"
    truncated = len(resolved) > MAX_TRANSACTION_REFS
    refs: list[EvidenceRef] = []
    for row in resolved.head(MAX_TRANSACTION_REFS).itertuples(index=False):
        refs.append(
            EvidenceRef(
                evidence_type=EvidenceType.TRANSACTION_RECORD,
                description=(
                    f"tx {row.from_account} -> {row.to_account} at {row.timestamp}, "
                    f"amount {row.amount_paid:.2f} {row.payment_currency} "
                    f"({row.payment_format})"
                ),
                location=f"{location_base}#tx_id={int(row.tx_id)}",
                source=source,
                observation_period=str(row.timestamp),
                metadata={
                    "tx_id": int(row.tx_id),
                    "from_bank": int(row.from_bank),
                    "to_bank": int(row.to_bank),
                },
            )
        )
    if truncated:
        limitations.append(
            f"transaction refs truncated to the first {MAX_TRANSACTION_REFS} of "
            f"{len(resolved)} supporting transactions"
        )

    refs.append(
        EvidenceRef(
            evidence_type=EvidenceType.GRAPH_MOTIF,
            description=(
                f"{typology} motif parameters for account {alert.account} "
                f"({len(resolved)} supporting transactions)"
            ),
            location=f"motif://{typology}/{alert.account}",
            source=f"finguard.graph v{detector_version}",
            observation_period=(
                f"{alert.score.get('window_start', '')}/{alert.score.get('window_end', '')}"
            ),
            metadata=dict(alert.score),
        )
    )
    if rank is not None:
        refs.append(
            EvidenceRef(
                evidence_type=EvidenceType.MODEL_RESULT,
                description=(
                    "alert rank-score from the fan-in ranking stage "
                    "(LightGBM, trained on train-period alerts only)"
                ),
                location=f"ranking://{typology}/{alert.account}",
                source="finguard.ranking",
                metadata={k: rank[k] for k in ("score", "rank", "budget") if k in rank},
            )
        )

    confidence = float(rank["score"]) if rank is not None and "score" in rank else None

    return EvidenceContract(
        claim_text=claim,
        evidence=refs,
        methodology=MethodologyInfo(
            name=f"{typology}_detector",
            version=detector_version,
            parameters=dict(alert.score),
        ),
        observation_period=(
            f"{alert.score.get('window_start', '')}/{alert.score.get('window_end', '')}"
        ),
        confidence=confidence,
        validation_status=ValidationStatus.UNVALIDATED,
        limitations=limitations,
        abstention=AbstentionInfo(abstained=False),
    )


def alerts_to_evidence_contracts(
    alerts: list[MotifAlert],
    tx: pd.DataFrame,
    *,
    dataset_id: str,
    parquet_path: str | None = None,
    ranks: dict[int, dict] | None = None,
    detector_version: str = "1.0.0",
) -> list[EvidenceContract]:
    """Package a batch of alerts; ``ranks`` keys by the alert's index."""
    ranks = ranks or {}
    return [
        alert_to_evidence_contract(
            alert,
            tx,
            dataset_id=dataset_id,
            parquet_path=parquet_path,
            rank=ranks.get(i),
            detector_version=detector_version,
        )
        for i, alert in enumerate(alerts)
    ]
