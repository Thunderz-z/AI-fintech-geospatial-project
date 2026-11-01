"""M1.5 smoke tests: alert ranking, evidence bundles, fan-out/cycle detectors."""

from __future__ import annotations

import pandas as pd
import pytest

from finguard.evidence import alert_to_evidence_contract
from finguard.graph import detect_cycle, detect_fan_in, detect_fan_out
from finguard.ranking import (
    RANKING_FEATURE_COLUMNS,
    fan_in_alert_features,
    label_alerts,
    train_alert_ranker,
)
from finguard.synthetic import generate_synthetic_transactions
from relia.contracts import ValidationStatus


@pytest.fixture(scope="module")
def synthetic_tx():
    tx, motifs = generate_synthetic_transactions(
        n_normal=600,
        typologies=("fan_in", "fan_out", "cycle"),
        motif_degree=7,
        seed=21,
    )
    return tx, motifs


def test_fan_out_detector_recovers_planted_fixture(synthetic_tx) -> None:
    tx, motifs = synthetic_tx
    planted = next(m for m in motifs if m.typology == "fan_out")

    alerts = detect_fan_out(tx, min_receivers=5, window=pd.Timedelta(days=3))
    assert any(set(planted.tx_ids) <= set(a.tx_ids) for a in alerts)
    assert all("distinct_receivers" in a.score for a in alerts)


def test_cycle_detector_recovers_planted_fixture(synthetic_tx) -> None:
    tx, motifs = synthetic_tx
    planted = next(m for m in motifs if m.typology == "cycle")

    alerts = detect_cycle(tx, min_length=3, max_length=8, window=pd.Timedelta(days=5))
    assert any(set(planted.tx_ids) <= set(a.tx_ids) for a in alerts)
    # Rings are simple: each tx appears once, ring closes back to origin.
    for alert in alerts:
        ring = tx.loc[tx["tx_id"].isin(alert.tx_ids)]
        assert len(ring) == alert.score["ring_length"]
        assert set(ring["from_account"]) == set(ring["to_account"])


def test_ranking_features_and_ranker_train(synthetic_tx) -> None:
    tx, motifs = synthetic_tx
    alerts = detect_fan_in(tx, min_senders=4, window=pd.Timedelta(days=3))
    features = fan_in_alert_features(tx, alerts)

    assert list(features.columns)[:5] == [
        "account", "window_start", "window_end", "tx_ids", "n_senders",
    ]
    assert set(RANKING_FEATURE_COLUMNS).issubset(features.columns)
    assert (features["n_senders"] >= 4).all()
    assert (features["receiver_age_days"] >= 0).all()

    tx_lookup = {
        int(r.tx_id): (r.from_account, r.to_account, r.timestamp)
        for r in tx[["tx_id", "from_account", "to_account", "timestamp"]].itertuples(index=False)
    }
    planted = [set(m.tx_ids and {
        (tx.loc[tx["tx_id"] == t, "from_account"].iloc[0],
         tx.loc[tx["tx_id"] == t, "to_account"].iloc[0],
         tx.loc[tx["tx_id"] == t, "timestamp"].iloc[0])
        for t in m.tx_ids
    }) for m in motifs if m.typology == "fan_in"]
    labeled = label_alerts(features, planted, tx_lookup)
    assert labeled["label"].sum() >= 1  # the planted fan-in must be labelled

    model, info = train_alert_ranker(labeled, labeled)
    assert model is not None
    assert info["train_positives"] >= 1


def test_evidence_contract_bundle_and_abstention(synthetic_tx) -> None:
    tx, _ = synthetic_tx
    alerts = detect_fan_in(tx, min_senders=4, window=pd.Timedelta(days=3))
    assert alerts

    contract = alert_to_evidence_contract(
        alerts[0], tx, dataset_id="SYNTH", parquet_path="synth.parquet",
        rank={"score": 0.9, "rank": 1, "budget": 0.001},
    )
    assert contract.validation_status == ValidationStatus.UNVALIDATED
    assert not contract.abstention.abstained
    assert contract.confidence == pytest.approx(0.9)
    types = {ref.evidence_type.value for ref in contract.evidence}
    assert {"transaction_record", "graph_motif", "model_result"} <= types
    assert "SYNTH" in contract.claim_text
    assert "not a finding of money laundering" in contract.claim_text

    # Thin evidence: an alert whose tx_ids do not resolve -> explicit abstention.
    from finguard.graph import MotifAlert

    orphan = MotifAlert(
        typology="fan_in", account="NOPE", counter_account=None,
        tx_ids=(10_000_000, 10_000_001),
        score={"window_start": "2022-09-01", "window_end": "2022-09-02"},
    )
    abstained = alert_to_evidence_contract(orphan, tx, dataset_id="SYNTH")
    assert abstained.abstention.abstained
    assert abstained.validation_status == ValidationStatus.ABSTAINED
    assert abstained.abstention.reason
