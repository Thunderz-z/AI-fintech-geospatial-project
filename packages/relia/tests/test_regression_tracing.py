"""Tests for regression bisection, in-memory tracing and the cost ledger."""

import pytest

from relia.observability.cost import CostLedger
from relia.providers.base import CompletionResponse, Usage
from relia.regression.bisect import (
    VersionOutcome,
    bisect_history,
    compare_versions,
)
from relia.tracing.memory import InMemoryTraceRecorder


def _outcome(version: str, values: dict[str, float]) -> VersionOutcome:
    return VersionOutcome(config_version=version, case_values=values)


class TestCompareVersions:
    def test_clear_regression_flagged_by_ci(self) -> None:
        a = _outcome("v1", {f"c{i}": 1.0 for i in range(30)})
        b_values = {f"c{i}": (0.0 if i < 15 else 1.0) for i in range(30)}
        comparison = compare_versions(a, _outcome("v2", b_values))
        assert comparison.is_regression
        assert not comparison.is_improvement
        assert comparison.mean_delta == pytest.approx(-0.5)
        assert comparison.ci_high < 0.0
        assert len(comparison.regressed_cases) == 15

    def test_clear_improvement(self) -> None:
        a = _outcome("v1", {f"c{i}": 0.0 for i in range(30)})
        b = _outcome("v2", {f"c{i}": 1.0 for i in range(30)})
        comparison = compare_versions(a, b)
        assert comparison.is_improvement and not comparison.is_regression
        assert comparison.ci_low > 0.0

    def test_tiny_change_not_flagged(self) -> None:
        a = _outcome("v1", {f"c{i}": 1.0 for i in range(30)})
        b_values = dict.fromkeys((f"c{i}" for i in range(30)), 1.0)
        b_values["c0"] = 0.0  # one case flips: 1/30 drop, CI must include 0
        comparison = compare_versions(a, _outcome("v2", b_values))
        assert not comparison.is_regression and not comparison.is_improvement
        assert comparison.ci_low <= 0.0 <= comparison.ci_high

    def test_disjoint_cases_counted(self) -> None:
        a = _outcome("v1", {"c1": 1.0, "c2": 1.0, "only_a": 1.0})
        b = _outcome("v2", {"c1": 0.0, "c2": 0.0, "only_b": 1.0})
        comparison = compare_versions(a, b)
        assert comparison.cases_only_in_a == ["only_a"]
        assert comparison.cases_only_in_b == ["only_b"]
        assert comparison.n_paired_cases == 2

    def test_no_shared_cases_raises(self) -> None:
        with pytest.raises(ValueError, match="No shared cases"):
            compare_versions(_outcome("v1", {"a": 1.0}), _outcome("v2", {"b": 1.0}))

    def test_empty_version_rejected(self) -> None:
        with pytest.raises(ValueError, match="config_version"):
            _outcome("", {"a": 1.0})


class TestBisectHistory:
    def test_locates_first_regression(self) -> None:
        good = {f"c{i}": 1.0 for i in range(30)}
        broken = {f"c{i}": (0.0 if i < 10 else 1.0) for i in range(30)}
        history = [
            _outcome("v1", good),
            _outcome("v2", dict(good)),
            _outcome("v3", broken),  # regression appears here
            _outcome("v4", broken),
        ]
        report = bisect_history(history)
        assert report.first_regression_version == "v3"
        assert report.first_regression_step == 1
        assert len(report.steps) == 3
        assert report.total_delta == pytest.approx(-1 / 3, abs=1e-6)
        assert report.to_dict()["note"].startswith("statistical")

    def test_no_regression_reported(self) -> None:
        good = {f"c{i}": 1.0 for i in range(20)}
        report = bisect_history([_outcome("v1", good), _outcome("v2", dict(good))])
        assert report.first_regression_version is None

    def test_needs_two_versions(self) -> None:
        with pytest.raises(ValueError, match="at least two"):
            bisect_history([_outcome("v1", {"a": 1.0})])


class TestInMemoryTraceRecorder:
    def test_span_lifecycle_and_export(self) -> None:
        recorder = InMemoryTraceRecorder()
        span_id = recorder.start_span("answer", attributes={"case": "c1"})
        recorder.record_event(span_id, "retrieval", attributes={"k": 3})
        recorder.end_span(span_id)
        spans = recorder.to_json()
        assert len(spans) == 1
        assert spans[0]["name"] == "answer"
        assert spans[0]["end"] is not None
        assert spans[0]["events"][0]["name"] == "retrieval"

    def test_unknown_and_double_close_never_raise(self) -> None:
        recorder = InMemoryTraceRecorder()
        recorder.end_span("missing")
        recorder.record_event("missing", "x")
        span_id = recorder.start_span("s")
        recorder.end_span(span_id)
        recorder.end_span(span_id)  # double close is a no-op
        assert len(recorder.spans()) == 1
        assert recorder.spans()[0].end is not None


def _response(cost: float | None, provider: str = "fake", model: str = "m1") -> CompletionResponse:
    return CompletionResponse(
        text="ok",
        model=model,
        provider=provider,
        usage=Usage(input_tokens=10, output_tokens=5),
        cost_usd=cost,
    )


class TestCostLedger:
    def test_accumulates_tokens_and_cost(self) -> None:
        ledger = CostLedger()
        ledger.add(_response(0.01))
        ledger.add(_response(0.02))
        snapshot = ledger.snapshot()
        assert snapshot.calls == 2
        assert snapshot.input_tokens == 20 and snapshot.output_tokens == 10
        assert snapshot.cost_usd == pytest.approx(0.03)
        assert snapshot.by_model["fake/m1"]["calls"] == 2

    def test_unknown_cost_poisons_total_honestly(self) -> None:
        ledger = CostLedger()
        ledger.add(_response(0.01))
        ledger.add(_response(None))
        snapshot = ledger.snapshot()
        # Never invent a price: totals with unknowns are reported as None.
        assert snapshot.cost_usd is None
        assert snapshot.calls == 2
