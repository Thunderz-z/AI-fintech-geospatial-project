"""Regression analysis and bisection across prompt/configuration history.

Implemented (:mod:`relia.regression.bisect`): paired-delta comparison of
per-case outcomes between two configuration versions with bootstrap CIs,
and bisection of a full version history to locate the first regression.
LLM evaluation is non-deterministic — every claim here is statistical and
CI-gated, never a bare point estimate.

Planned: cassette-backed case replay for regressed cases and failure
categorization reports (see ``docs/architecture/relia.md``).
"""

from relia.regression.bisect import (
    BisectReport,
    VersionComparison,
    VersionOutcome,
    bisect_history,
    compare_versions,
)

__all__ = [
    "BisectReport",
    "VersionComparison",
    "VersionOutcome",
    "bisect_history",
    "compare_versions",
]
