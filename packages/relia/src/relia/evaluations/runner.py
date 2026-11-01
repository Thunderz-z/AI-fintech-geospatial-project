"""Deterministic evaluation runner.

Executes an :class:`EvalDataset` against an answer function and scores every
case with :class:`~relia.evaluations.checks.DeterministicCheck` functions —
pure, reproducible, no model-based judging. LLM-as-judge evaluation stays a
separate planned runner by design; the two are never merged into one metric.

Aggregation rules (stated so results cannot be misread):

* Each check contributes one :class:`EvalMetric` = mean score over the cases
  that produced an answer (full population, so ``sample_size`` stays None —
  these metrics are exact, not sampled estimates). A check with zero scored
  cases is omitted, never reported as 0.0.
* A case whose answer function raised is recorded in ``case_results`` with
  its error and excluded from check metrics; the run-level
  ``case_success_rate`` metric makes that exclusion visible in the numbers,
  not only in the notes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from relia.evaluations.base import (
    CaseResult,
    EvalCase,
    EvalDataset,
    EvalMetric,
    EvalResult,
)
from relia.evaluations.checks import DeterministicCheck

__all__ = ["AnswerFn", "EvalRunner"]

#: Produces the answer for one case (e.g. a prompt-render + provider call).
AnswerFn = Callable[[EvalCase], Awaitable[str]]


class EvalRunner:
    """Run deterministic checks over a dataset with an injected answer function."""

    def __init__(self, answer_fn: AnswerFn) -> None:
        self._answer_fn = answer_fn

    async def run(
        self,
        dataset: EvalDataset,
        config_version: str,
        checks: Sequence[DeterministicCheck],
        *,
        notes: str | None = None,
    ) -> EvalResult:
        """Execute every case once, score, aggregate and return the result."""
        if not checks:
            raise ValueError("EvalRunner.run requires at least one check.")
        _validate_expected_availability(dataset, checks)

        case_results: list[CaseResult] = []
        for case in dataset.cases:
            case_results.append(await self._run_case(case, checks))

        scored = [result for result in case_results if result.error is None]
        metrics: list[EvalMetric] = []
        for check in checks:
            values = [result.check_scores[check.name] for result in scored]
            if not values:
                # Zero scored cases: omit the metric rather than report a
                # misleading 0.0 ("all wrong") when nothing was measured.
                continue
            metrics.append(
                EvalMetric(name=check.name, value=_mean(values), higher_is_better=True)
            )
        metrics.append(
            EvalMetric(
                name="case_success_rate",
                value=len(scored) / len(dataset.cases),
                higher_is_better=True,
            )
        )

        errored_ids = [
            result.case_id for result in case_results if result.error is not None
        ]
        if errored_ids:
            summary = (
                f"{len(errored_ids)}/{len(dataset.cases)} cases errored and are "
                f"excluded from check metrics: {errored_ids}."
            )
            notes = f"{notes} {summary}" if notes else summary

        return EvalResult(
            dataset_id=dataset.dataset_id,
            dataset_version=dataset.version,
            config_version=config_version,
            metrics=metrics,
            case_results=case_results,
            notes=notes,
        )

    async def _run_case(
        self, case: EvalCase, checks: Sequence[DeterministicCheck]
    ) -> CaseResult:
        try:
            answer = await self._answer_fn(case)
        except Exception as exc:  # record and continue; metric coverage shows it
            return CaseResult(case_id=case.case_id, answer="", error=str(exc))
        scores = {check.name: check.score(case, answer) for check in checks}
        return CaseResult(case_id=case.case_id, answer=answer, check_scores=scores)


def _validate_expected_availability(
    dataset: EvalDataset, checks: Sequence[DeterministicCheck]
) -> None:
    failing = [
        check.name
        for check in checks
        if getattr(check, "requires_expected", False)
    ]
    if not failing:
        return
    missing = [case.case_id for case in dataset.cases if case.expected is None]
    if missing:
        raise ValueError(
            f"Checks {failing} need case.expected but cases without it: "
            f"{missing}."
        )


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
