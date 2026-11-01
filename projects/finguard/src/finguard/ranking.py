"""Alert ranking for fan-in detection (M1.5/F1 — the precision problem).

The v0 fan-in detector reaches ~100% recall on detectable planted attempts
but fires tens of thousands of alerts against legitimate convergence traffic
(salaries, merchants), giving precision ~0.001. This module adds the second
stage: interpretable per-alert features and a learned ranker so a fixed
analyst budget (top-k% of alerts) can be spent on the most plant-like
alerts.

Ranking features (all computable from transaction data alone — no labels):

* ``n_senders`` / ``window_edges`` / ``window_hours`` — alert shape
* ``receiver_age_days`` — age of the receiver account at window start
  (planted collectors are typically fresh; 0 = first-ever activity)
* ``receiver_prior_edges`` — receiver's edges strictly before the window
* ``receiver_activity_share`` — share of the receiver's total activity that
  falls inside the alert window (burst isolation)
* ``fresh_sender_share`` — share of senders whose first-ever transaction is
  inside the window
* ``sender_exclusivity`` — share of senders whose only outgoing edges go to
  this receiver
* ``amount_cv`` / ``median_amount`` — amount statistics

Discipline: the ranker is trained on TRAIN-period alerts only and evaluated
on later periods (ADR-0006); labels come from the synthetic planted ground
truth and never enter the feature columns.
"""

from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd

from finguard.graph import MotifAlert

__all__ = [
    "RANKING_FEATURE_COLUMNS",
    "fan_in_alert_features",
    "label_alerts",
    "train_alert_ranker",
    "score_alerts",
]

RANKING_FEATURE_COLUMNS: tuple[str, ...] = (
    "n_senders",
    "window_edges",
    "window_hours",
    "receiver_age_days",
    "receiver_prior_edges",
    "receiver_activity_share",
    "fresh_sender_share",
    "sender_exclusivity",
    "amount_cv",
    "median_amount",
)


def fan_in_alert_features(
    tx: pd.DataFrame, alerts: list[MotifAlert]
) -> pd.DataFrame:
    """Build one feature row per fan-in alert.

    Args:
        tx: Canonical transactions (the frame the alerts were detected on).
        alerts: Alerts from :func:`finguard.graph.detect_fan_in`.

    Returns:
        Frame with ``account`` (receiver), ``window_start``, ``window_end``,
        ``tx_ids`` (tuple), the :data:`RANKING_FEATURE_COLUMNS` columns and
        ``label`` (0/1, filled by :func:`label_alerts` — 0 until labelled).
    """
    if not alerts:
        return pd.DataFrame(
            {col: pd.Series(dtype="float64") for col in RANKING_FEATURE_COLUMNS}
            | {
                "account": pd.Series(dtype="string"),
                "window_start": pd.Series(dtype="datetime64[us]"),
                "window_end": pd.Series(dtype="datetime64[us]"),
                "tx_ids": pd.Series(dtype="object"),
                "label": pd.Series(dtype="int8"),
            }
        )

    by_id = tx.set_index("tx_id", drop=False)
    receiver_first = tx.groupby("to_account", observed=True)["timestamp"].min()
    receiver_last = tx.groupby("to_account", observed=True)["timestamp"].max()
    receiver_sorted_times: dict[str, np.ndarray] = {
        str(name): np.sort(group.to_numpy())
        for name, group in tx.groupby("to_account", observed=True)["timestamp"]
    }
    sender_first = tx.groupby("from_account", observed=True)["timestamp"].min()
    sender_receivers = tx.groupby("from_account", observed=True)["to_account"].nunique()

    rows: list[dict] = []
    for alert in alerts:
        receiver = alert.account
        txs = by_id.loc[list(alert.tx_ids)]
        window_start = pd.Timestamp(alert.score["window_start"])
        window_end = pd.Timestamp(alert.score["window_end"])
        window_edges = len(txs)
        senders = txs["from_account"].astype("string")
        amounts = txs["amount_paid"].to_numpy(dtype="float64")

        r_times = receiver_sorted_times.get(receiver)
        prior_edges = int((r_times < window_start.to_numpy()).sum()) if r_times is not None else 0
        r_first = receiver_first.get(receiver)
        receiver_age = (
            max(0.0, (window_start - r_first).total_seconds() / 86400.0)
            if r_first is not None
            else 0.0
        )
        r_last = receiver_last.get(receiver)
        activity_span = max(1e-9, (r_last - r_first).total_seconds()) if (
            r_first is not None and r_last is not None
        ) else 1e-9
        activity_share = min(
            1.0, (window_end - window_start).total_seconds() / activity_span
        )

        firsts = sender_first.reindex(senders).to_numpy()
        fresh_sender_share = float(np.mean(firsts >= window_start.to_numpy()))
        exclusivity = sender_receivers.reindex(senders).fillna(0).to_numpy()
        sender_exclusivity = float(np.mean(exclusivity == 1))

        mean_amount = float(np.mean(amounts)) if len(amounts) else 0.0
        amount_cv = (
            float(np.std(amounts) / mean_amount) if mean_amount > 0 else 0.0
        )

        rows.append(
            {
                "account": receiver,
                "window_start": window_start,
                "window_end": window_end,
                "tx_ids": tuple(int(t) for t in alert.tx_ids),
                "n_senders": int(senders.nunique()),
                "window_edges": window_edges,
                "window_hours": (window_end - window_start).total_seconds() / 3600.0,
                "receiver_age_days": receiver_age,
                "receiver_prior_edges": prior_edges,
                "receiver_activity_share": activity_share,
                "fresh_sender_share": fresh_sender_share,
                "sender_exclusivity": sender_exclusivity,
                "amount_cv": amount_cv,
                "median_amount": float(np.median(amounts)) if len(amounts) else 0.0,
                "label": 0,
            }
        )

    return pd.DataFrame(rows)


def label_alerts(
    features: pd.DataFrame,
    planted_key_sets: list[set],
    tx_lookup: dict[int, tuple[str, str, pd.Timestamp]],
) -> pd.DataFrame:
    """Set ``label=1`` for alerts whose transactions overlap a planted attempt.

    Labels are ground truth for training/evaluation only (synthetic data);
    they are never a feature input.
    """
    out = features.copy()
    labels = np.zeros(len(out), dtype="int8")
    for i, tx_ids in enumerate(out["tx_ids"]):
        keys = {tx_lookup[t] for t in tx_ids if t in tx_lookup}
        if keys and any(keys & planted for planted in planted_key_sets):
            labels[i] = 1
    out["label"] = labels
    return out


def train_alert_ranker(
    train_features: pd.DataFrame,
    validation_features: pd.DataFrame,
    *,
    feature_cols: list[str] | tuple[str, ...] = RANKING_FEATURE_COLUMNS,
    label_col: str = "label",
    n_estimators: int = 60,
    learning_rate: float = 0.05,
    num_leaves: int = 15,
    min_child_samples: int = 100,
    scale_pos_weight_cap: float = 100.0,
    seed: int = 42,
) -> tuple[lgb.LGBMClassifier, dict]:
    """Train the alert ranker on TRAIN-period alerts.

    Design notes from the first tuning pass (recorded for honesty):

    * Early stopping with a few dozen positive alerts is unstable (it
      stopped at iteration 1 and generalized; 100 unregularized trees with
      the raw ``neg/pos`` weight (~2685) memorized the training positives
      and collapsed on test). Fixed tree count, capped
      ``scale_pos_weight`` and shallow regularized trees are the compromise.
    * The validation frame is used for reported ranking quality and model
      selection only — never for training (ADR-0006 temporal discipline).
    """
    pos = int(train_features[label_col].sum())
    neg = len(train_features) - pos
    spw = min(neg / max(1, pos), scale_pos_weight_cap)
    params = {
        "objective": "binary",
        "n_estimators": n_estimators,
        "learning_rate": learning_rate,
        "num_leaves": num_leaves,
        "min_child_samples": min_child_samples,
        "scale_pos_weight": spw,
        "reg_lambda": 1.0,
        "random_state": seed,
        "n_jobs": -1,
        "verbosity": -1,
    }
    model = lgb.LGBMClassifier(**params)
    model.fit(
        train_features[list(feature_cols)],
        train_features[label_col],
        eval_set=[(validation_features[list(feature_cols)], validation_features[label_col])],
        eval_metric="average_precision",
        callbacks=[lgb.log_evaluation(0)],
    )
    valid_ap = float(model.best_score_["valid_0"]["average_precision"])
    info = {
        "train_alerts": len(train_features),
        "train_positives": pos,
        "validation_alerts": len(validation_features),
        "validation_positives": int(validation_features[label_col].sum()),
        "validation_average_precision": round(valid_ap, 6),
        "n_estimators": n_estimators,
        "scale_pos_weight": spw,
        "feature_importance": {
            col: int(gain)
            for col, gain in sorted(
                zip(feature_cols, model.booster_.feature_importance("gain"), strict=True),
                key=lambda kv: -kv[1],
            )
        },
        "params": params,
    }
    return model, info


def score_alerts(
    model: lgb.LGBMClassifier,
    features: pd.DataFrame,
    *,
    feature_cols: list[str] | tuple[str, ...] = RANKING_FEATURE_COLUMNS,
) -> np.ndarray:
    """Rank-score alerts with the trained ranker (higher = review first)."""
    return model.predict_proba(features[list(feature_cols)])[:, 1]
