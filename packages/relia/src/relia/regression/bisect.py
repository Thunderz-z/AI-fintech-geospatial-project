"""Regression comparison and bisection across prompt/configuration history.

The flagship RELIA capability. Given the per-case outcomes of an evaluation
metric across consecutive configuration versions, this module:

1. **Compares** two versions with a *paired* bootstrap CI over per-case
   deltas (the cases are the sampling units — the same principle as the
   TerraScope seasonality analysis).
2. **Bisects** a full version history to locate the first transition where a
   metric regressed (CI of the paired delta excludes zero on the bad side).

Honesty rules encoded here: LLM evaluation is **not deterministic** —
comparisons are statistical and reported with intervals, never as bare
point estimates; a regression claim requires the CI to exclude zero; cases
present in only one version are excluded from the paired comparison and
counted separately.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

__all__ = [
    "BisectReport",
    "VersionComparison",
    "VersionOutcome",
    "bisect_history",
    "compare_versions",
]

_N_BOOTSTRAP = 10_000
_DEFAULT_SEED = 42


@dataclass(frozen=True)
class VersionOutcome:
    """Per-case metric outcomes for one configuration version.

    ``case_values`` maps case id -> metric value (e.g. a 0/1 pass flag, a
    groundedness score). Values must be comparable across versions; the
    caller owns the metric definition.
    """

    config_version: str
    case_values: dict[str, float]

    def __post_init__(self) -> None:
        if not self.config_version:
            msg = "config_version must be non-empty"
            raise ValueError(msg)


@dataclass
class VersionComparison:
    """Paired-delta comparison between two consecutive versions."""

    config_a: str = ""
    config_b: str = ""
    n_paired_cases: int = 0
    cases_only_in_a: list[str] = field(default_factory=list)
    cases_only_in_b: list[str] = field(default_factory=list)
    mean_delta: float | None = None  # b - a (negative = regression)
    ci_low: float | None = None
    ci_high: float | None = None
    is_regression: bool = False
    is_improvement: bool = False
    regressed_cases: list[str] = field(default_factory=list)
    improved_cases: list[str] = field(default_factory=list)
    n_bootstrap: int = _N_BOOTSTRAP

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BisectReport:
    """Result of walking a version history end to end."""

    baseline_version: str = ""
    final_version: str = ""
    steps: list[VersionComparison] = field(default_factory=list)
    first_regression_version: str | None = None
    first_regression_step: int | None = None
    baseline_mean: float | None = None
    final_mean: float | None = None
    total_delta: float | None = None
    n_bootstrap: int = _N_BOOTSTRAP

    def to_dict(self) -> dict:
        return {
            "note": (
                "statistical comparison of non-deterministic LLM evaluation; "
                "regression claims require the paired-delta CI to exclude zero"
            ),
            **asdict(self),
        }


def _bootstrap_ci(deltas: np.ndarray, n_bootstrap: int, seed: int) -> tuple[float, float]:
    """Percentile bootstrap CI of the mean, resampling cases with replacement."""
    rng = np.random.default_rng(seed)
    n = deltas.size
    means = np.empty(n_bootstrap, dtype=np.float64)
    for i in range(n_bootstrap):
        sample = deltas[rng.integers(0, n, size=n)]
        means[i] = sample.mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _paired_deltas(
    a: VersionOutcome, b: VersionOutcome
) -> tuple[np.ndarray, list[str], list[str]]:
    shared = sorted(set(a.case_values) & set(b.case_values))
    only_a = sorted(set(a.case_values) - set(b.case_values))
    only_b = sorted(set(b.case_values) - set(a.case_values))
    if not shared:
        msg = (
            f"No shared cases between {a.config_version!r} and {b.config_version!r}; "
            "a paired comparison is impossible."
        )
        raise ValueError(msg)
    deltas = np.array(
        [b.case_values[case] - a.case_values[case] for case in shared], dtype=np.float64
    )
    return deltas, only_a, only_b


def compare_versions(
    a: VersionOutcome,
    b: VersionOutcome,
    *,
    n_bootstrap: int = _N_BOOTSTRAP,
    seed: int = _DEFAULT_SEED,
) -> VersionComparison:
    """Paired comparison of two versions; flags regression/improvement by CI.

    ``is_regression`` requires the 95% CI of the mean paired delta to lie
    strictly below zero; ``is_improvement`` strictly above.
    """
    deltas, only_a, only_b = _paired_deltas(a, b)
    ci_low, ci_high = _bootstrap_ci(deltas, n_bootstrap, seed)
    mean_delta = float(deltas.mean())
    return VersionComparison(
        config_a=a.config_version,
        config_b=b.config_version,
        n_paired_cases=int(deltas.size),
        cases_only_in_a=only_a,
        cases_only_in_b=only_b,
        mean_delta=round(mean_delta, 6),
        ci_low=round(ci_low, 6),
        ci_high=round(ci_high, 6),
        is_regression=ci_high < 0.0,
        is_improvement=ci_low > 0.0,
        regressed_cases=sorted(
            case for case in (set(a.case_values) & set(b.case_values))
            if b.case_values[case] < a.case_values[case]
        ),
        improved_cases=sorted(
            case for case in (set(a.case_values) & set(b.case_values))
            if b.case_values[case] > a.case_values[case]
        ),
        n_bootstrap=n_bootstrap,
    )


def bisect_history(
    history: list[VersionOutcome],
    *,
    n_bootstrap: int = _N_BOOTSTRAP,
    seed: int = _DEFAULT_SEED,
) -> BisectReport:
    """Walk consecutive version pairs and locate the first regression.

    Args:
        history: Chronologically ordered version outcomes (index 0 = baseline).

    Raises:
        ValueError: Fewer than two versions.
    """
    if len(history) < 2:
        msg = "Bisection needs at least two configuration versions."
        raise ValueError(msg)

    report = BisectReport(
        baseline_version=history[0].config_version,
        final_version=history[-1].config_version,
        baseline_mean=round(float(np.mean(list(history[0].case_values.values()))), 6),
        final_mean=round(float(np.mean(list(history[-1].case_values.values()))), 6),
        n_bootstrap=n_bootstrap,
    )
    report.total_delta = round(report.final_mean - report.baseline_mean, 6)

    for index in range(len(history) - 1):
        a, b = history[index], history[index + 1]
        comparison = compare_versions(a, b, n_bootstrap=n_bootstrap, seed=seed + index)
        report.steps.append(comparison)
        if comparison.is_regression and report.first_regression_version is None:
            report.first_regression_version = b.config_version
            report.first_regression_step = index
    return report
