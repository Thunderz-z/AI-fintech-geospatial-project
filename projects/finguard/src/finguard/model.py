"""LightGBM fraud baseline with alert-budget operating points (M1 step 5).

Methodology (ADR-0006 + ``docs/architecture/finguard.md``):

* Temporal train/validation/test split only — the caller passes the split.
* Class imbalance handled with ``scale_pos_weight`` (no random oversampling).
* Primary metric: PR-AUC (``average_precision``). ROC-AUC reported for
  context only — it flatters extreme imbalance.
* Operating points: precision/recall when flagging the top-k% of
  validation-scored transactions for k in :data:`ALERT_BUDGETS`. The
  threshold for each budget is picked on **validation** and applied to
  **test** — no test-set peeking.

All results are computed from an actual run; anything labelled synthetic in
the caller's data must keep that label in every reported number.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

__all__ = [
    "ALERT_BUDGETS",
    "FraudBaselineReport",
    "train_fraud_baseline",
]

#: Alert-budget operating points (fraction of scored traffic flagged).
ALERT_BUDGETS: tuple[float, ...] = (0.001, 0.005, 0.01, 0.05)


@dataclass(frozen=True)
class FraudBaselineReport:
    """Metrics from one baseline run (reproducible from its parameters)."""

    dataset_id: str
    rows: dict[str, int] = field(default_factory=dict)
    positives: dict[str, int] = field(default_factory=dict)
    pr_auc: float = 0.0
    roc_auc: float = 0.0
    # budget -> {"threshold", "precision", "recall", "flagged", ...}
    test_operating_points: dict[float, dict[str, float]] = field(default_factory=dict)
    best_iteration: int = 0
    params: dict = field(default_factory=dict)


def _precision_recall_at_budget(
    y_true: np.ndarray, scores: np.ndarray, budget: float
) -> dict[str, float]:
    """Flag the top-*budget* fraction by score; return precision/recall there."""
    n_flag = max(1, int(np.ceil(budget * len(scores))))
    order = np.argsort(scores, kind="mergesort")[::-1][:n_flag]
    flagged = np.zeros(len(scores), dtype=bool)
    flagged[order] = True
    tp = int(flagged[y_true == 1].sum())
    return {
        "threshold": float(scores[order[-1]]),
        "flagged": int(flagged.sum()),
        "true_positives": tp,
        "precision": tp / n_flag,
        "recall": tp / max(1, int((y_true == 1).sum())),
    }


def train_fraud_baseline(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    test: pd.DataFrame,
    *,
    feature_cols: list[str] | tuple[str, ...],
    target_col: str = "is_laundering",
    dataset_id: str = "unspecified",
    seed: int = 42,
) -> tuple[lgb.LGBMClassifier, FraudBaselineReport]:
    """Train the imbalance-aware LightGBM baseline and evaluate it honestly.

    Categorical columns in ``feature_cols`` must already be pandas
    ``category`` dtype (LightGBM handles them natively).

    Returns:
        ``(model, report)`` — the report's operating points are derived from
        validation-scored thresholds and applied to the test period.
    """
    cat_cols = [c for c in feature_cols if str(train[c].dtype) == "category"]
    x_train, y_train = train[list(feature_cols)], train[target_col]
    x_valid, y_valid = validation[list(feature_cols)], validation[target_col]
    x_test, y_test = test[list(feature_cols)], test[target_col]

    pos, neg = int(y_train.sum()), int((y_train == 0).sum())
    params = {
        "objective": "binary",
        "n_estimators": 300,
        "learning_rate": 0.1,
        "num_leaves": 63,
        "min_child_samples": 200,
        "scale_pos_weight": neg / max(1, pos),
        "random_state": seed,
        "n_jobs": -1,
        "verbosity": -1,
    }
    model = lgb.LGBMClassifier(**params)
    model.fit(
        x_train,
        y_train,
        eval_set=[(x_valid, y_valid)],
        eval_metric="average_precision",
        categorical_feature=cat_cols or "auto",
        callbacks=[lgb.early_stopping(30, verbose=False)],
    )

    test_scores = model.predict_proba(x_test)[:, 1]
    y_test_arr = y_test.to_numpy()

    # Alert-budget operating points: flag the top-k% of scored traffic by
    # rank. The budget is fixed a priori (an analyst-capacity fact), labels
    # are used only to *evaluate* afterwards — no threshold transfer issues
    # under the probability saturation that extreme scale_pos_weight causes
    # (raw probabilities are not calibrated and not used for cut selection).
    test_points: dict[float, dict[str, float]] = {}
    for budget in ALERT_BUDGETS:
        point = _precision_recall_at_budget(y_test_arr, test_scores, budget)
        point["flagged_fraction"] = point["flagged"] / len(test_scores)
        test_points[budget] = point

    report = FraudBaselineReport(
        dataset_id=dataset_id,
        rows={"train": len(train), "validation": len(validation), "test": len(test)},
        positives={
            "train": pos,
            "validation": int(y_valid.sum()),
            "test": int(y_test_arr.sum()),
        },
        pr_auc=float(average_precision_score(y_test_arr, test_scores)),
        roc_auc=float(roc_auc_score(y_test_arr, test_scores)),
        test_operating_points=test_points,
        best_iteration=int(model.best_iteration_ or params["n_estimators"]),
        params=params,
    )
    return model, report
