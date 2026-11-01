"""Tests for deterministic checks, the eval runner and dataset loading."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from relia.evaluations import (
    CaseResult,
    ContainsCheck,
    EvalCase,
    EvalDataset,
    EvalResult,
    EvalRunner,
    ExactMatch,
    RegexCheck,
    ValidJsonCheck,
    load_eval_dataset,
)
from relia.evaluations.datasets import EvalDatasetError


def run(coro):
    return asyncio.run(coro)


def make_case(expected: str | None = "42", **overrides) -> EvalCase:
    defaults: dict = {"input": "what is the answer?", "expected": expected}
    defaults.update(overrides)
    return EvalCase(**defaults)


# --- checks ----------------------------------------------------------------


def test_exact_match_is_whitespace_insensitive() -> None:
    check = ExactMatch()
    assert check.score(make_case(expected="42"), "  42 \n") == 1.0
    assert check.score(make_case(expected="42"), "41") == 0.0


def test_contains_check_case_handling() -> None:
    check = ContainsCheck("Ramsar")
    assert check.score(make_case(), "The RAMSAR site grew.") == 1.0
    strict = ContainsCheck("Ramsar", case_sensitive=True)
    assert strict.score(make_case(), "The RAMSAR site grew.") == 0.0
    assert strict.score(make_case(), "The Ramsar site grew.") == 1.0


def test_regex_check_uses_search() -> None:
    check = RegexCheck(r"\b\d{4}-\d{2}-\d{2}\b")
    assert check.score(make_case(), "Observed on 2026-03-15 clearly.") == 1.0
    assert check.score(make_case(), "no date here") == 0.0


def test_valid_json_check() -> None:
    check = ValidJsonCheck()
    assert check.score(make_case(), '{"answer": 1}') == 1.0
    assert check.score(make_case(), "{not json}") == 0.0


# --- runner ----------------------------------------------------------------


def build_dataset() -> EvalDataset:
    return EvalDataset(
        dataset_id="smoke",
        version="1.0.0",
        cases=[
            make_case(case_id="c1", expected="42"),
            make_case(case_id="c2", expected="The answer"),
        ],
    )


def test_runner_aggregates_metrics_and_records_cases() -> None:
    async def answer_fn(case: EvalCase) -> str:
        return "42" if case.case_id == "c1" else "The answer!"

    result = run(
        EvalRunner(answer_fn).run(
            build_dataset(), "prompt@1", [ExactMatch(), ValidJsonCheck()]
        )
    )

    by_name = {metric.name: metric.value for metric in result.metrics}
    assert by_name["exact_match"] == pytest.approx(0.5)
    # "42" parses as a JSON number; "The answer!" does not.
    assert by_name["valid_json"] == pytest.approx(0.5)
    assert by_name["case_success_rate"] == 1.0
    assert result.dataset_id == "smoke"
    assert result.config_version == "prompt@1"
    assert [c.case_id for c in result.case_results] == ["c1", "c2"]
    assert result.case_results[0].answer == "42"
    assert result.case_results[1].check_scores["exact_match"] == 0.0


def test_runner_case_error_is_excluded_from_metrics_and_reported() -> None:
    async def answer_fn(case: EvalCase) -> str:
        if case.case_id == "c2":
            raise RuntimeError("provider exploded")
        return "42"

    result = run(
        EvalRunner(answer_fn).run(build_dataset(), "prompt@1", [ExactMatch()])
    )

    by_name = {metric.name: metric.value for metric in result.metrics}
    assert by_name["exact_match"] == 1.0  # only the successful case counts
    assert by_name["case_success_rate"] == pytest.approx(0.5)
    errored = result.case_results[1]
    assert errored.error == "provider exploded"
    assert errored.check_scores == {}
    assert result.notes is not None and "c2" in result.notes


def test_runner_all_cases_errored_still_yields_success_rate_metric() -> None:
    async def answer_fn(case: EvalCase) -> str:
        raise RuntimeError("down")

    result = run(EvalRunner(answer_fn).run(build_dataset(), "v", [ExactMatch()]))

    assert {m.name for m in result.metrics} == {"case_success_rate"}
    assert result.metrics[0].value == 0.0


def test_runner_requires_checks() -> None:
    with pytest.raises(ValueError, match="at least one check"):
        run(EvalRunner(None).run(build_dataset(), "v", []))


def test_runner_rejects_expected_based_check_on_unexpected_dataset() -> None:
    dataset = EvalDataset(
        dataset_id="d",
        version="1",
        cases=[make_case(case_id="c1", expected=None)],
    )
    with pytest.raises(ValueError, match="case.expected"):
        run(EvalRunner(None).run(dataset, "v", [ExactMatch()]))


def test_eval_result_round_trip_with_case_results_and_backward_compat() -> None:
    result = EvalResult(
        dataset_id="d",
        dataset_version="1",
        config_version="prompt@2",
        metrics=[{"name": "exact_match", "value": 1.0}],
        case_results=[
            CaseResult(case_id="c1", answer="42", check_scores={"exact_match": 1.0})
        ],
    )
    restored = EvalResult.model_validate_json(result.model_dump_json())
    assert restored == result

    # Additive schema: an old aggregate-only payload still validates.
    legacy = """
    {"dataset_id": "d", "dataset_version": "1", "config_version": "old",
     "metrics": [{"name": "exact_match", "value": 0.5}]}
    """
    assert EvalResult.model_validate_json(legacy).case_results == []


# --- dataset loading ---------------------------------------------------------


DATASET_TOML = """
dataset_id = "water-summary-smoke"
version = "1.0.0"

[[cases]]
case_id = "w-1"
input = "Summarize the winter composite."
expected = "Water expanded."

[cases.context]
region = "Ramsar IN2481"
year = 2026
"""


def test_load_eval_dataset_from_toml(tmp_path) -> None:
    path = tmp_path / "dataset.toml"
    path.write_text(DATASET_TOML, encoding="utf-8")

    dataset = load_eval_dataset(path)

    assert dataset.dataset_id == "water-summary-smoke"
    assert dataset.version == "1.0.0"
    assert len(dataset.cases) == 1
    case = dataset.cases[0]
    assert case.case_id == "w-1"
    assert case.expected == "Water expanded."
    assert case.context == {"region": "Ramsar IN2481", "year": 2026}


def test_load_eval_dataset_generates_missing_ids(tmp_path) -> None:
    path = tmp_path / "dataset.toml"
    path.write_text(
        'dataset_id = "d"\nversion = "1"\n[[cases]]\ninput = "q"\nexpected = "a"\n',
        encoding="utf-8",
    )

    dataset = load_eval_dataset(path)

    assert len(dataset.cases[0].case_id) >= 8


def test_load_eval_dataset_missing_key_raises(tmp_path) -> None:
    path = tmp_path / "dataset.toml"
    path.write_text('dataset_id = "d"\n[[cases]]\ninput = "q"\n', encoding="utf-8")

    with pytest.raises(EvalDatasetError, match="'version'"):
        load_eval_dataset(path)


def test_load_eval_dataset_unreadable_raises(tmp_path) -> None:
    with pytest.raises(EvalDatasetError, match="Cannot read eval dataset"):
        load_eval_dataset(tmp_path / "missing.toml")


def test_eval_dataset_requires_cases() -> None:
    with pytest.raises(ValidationError):
        EvalDataset(dataset_id="d", version="1", cases=[])
