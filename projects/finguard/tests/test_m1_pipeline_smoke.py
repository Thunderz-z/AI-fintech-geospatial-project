"""M1 pipeline smoke tests: features → model, detectors vs planted motifs."""

from __future__ import annotations

import pandas as pd

from finguard.features import build_baseline_features
from finguard.graph import detect_fan_in, detect_structuring
from finguard.model import train_fraud_baseline
from finguard.splitting import temporal_split
from finguard.synthetic import generate_synthetic_transactions


def _features(n_normal: int = 800, seed: int = 3) -> pd.DataFrame:
    tx, _ = generate_synthetic_transactions(
        n_normal=n_normal,
        typologies=("fan_in", "fan_out", "structuring", "cycle", "scatter_gather"),
        seed=seed,
    )
    return build_baseline_features(tx)


def test_features_pass_leakage_gate() -> None:
    features = _features()
    # build_baseline_features runs the gate itself; here we also assert the
    # structural property it guarantees: strictly-prior sender counts.
    first_tx_per_sender = features["sender_prior_count"] == 0
    assert first_tx_per_sender.any()
    assert (features["sender_prior_amount"] >= 0).all()


def test_model_trains_and_reports_operating_points() -> None:
    features = _features(n_normal=1500, seed=5)
    split = temporal_split(features, timestamp_col="timestamp")

    model, report = train_fraud_baseline(
        split.train,
        split.validation,
        split.test,
        feature_cols=[
            "log_amount_paid",
            "amount_ratio",
            "same_currency",
            "hour_of_day",
            "sender_prior_count",
            "receiver_prior_count",
        ],
        dataset_id="synthetic-smoke",
        seed=1,
    )

    assert 0.0 <= report.pr_auc <= 1.0
    assert 0.5 <= report.roc_auc <= 1.0
    assert set(report.test_operating_points) == {0.001, 0.005, 0.01, 0.05}
    for point in report.test_operating_points.values():
        assert 0.0 <= point["precision"] <= 1.0
        assert 0.0 <= point["recall"] <= 1.0


def test_fan_in_detector_finds_planted_fixture() -> None:
    tx, motifs = generate_synthetic_transactions(
        n_normal=400, typologies=("fan_in",), motif_degree=8, seed=11
    )
    alerts = detect_fan_in(tx, min_senders=6, window=pd.Timedelta(days=3))

    planted = next(m for m in motifs if m.typology == "fan_in")
    planted_ids = set(planted.tx_ids)
    assert any(planted_ids <= set(a.tx_ids) for a in alerts), (
        "planted fan-in not recovered by the detector"
    )


def test_structuring_detector_finds_planted_fixture() -> None:
    tx, motifs = generate_synthetic_transactions(
        n_normal=400,
        typologies=("structuring",),
        motif_degree=6,
        structuring_threshold=10_000.0,
        seed=13,
    )
    alerts = detect_structuring(tx, threshold=10_000.0, min_transactions=5,
                                window=pd.Timedelta(days=2))

    planted = next(m for m in motifs if m.typology == "structuring")
    planted_ids = set(planted.tx_ids)
    assert any(len(planted_ids & set(a.tx_ids)) >= 5 for a in alerts), (
        "planted structuring not recovered by the detector"
    )
    assert all(
        a.score["total_amount"] < 6 * 10_000.0 for a in alerts
    )
