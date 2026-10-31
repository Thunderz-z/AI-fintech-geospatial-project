"""Tests for provider/eval/replay interface foundations."""

import pytest
from pydantic import ValidationError

from relia.evaluations import EvalDataset, EvalMetric, EvalResult
from relia.providers.base import (
    CompletionRequest,
    MalformedStructuredOutputError,
    Message,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ReliaError,
)
from relia.replay import Cassette, RecordedInteraction, ReplayMismatchError


def test_error_hierarchy() -> None:
    for exc in (
        ProviderError,
        ProviderTimeoutError,
        ProviderRateLimitError,
        MalformedStructuredOutputError,
        ReplayMismatchError,
    ):
        assert issubclass(exc, ReliaError)
    assert issubclass(ProviderTimeoutError, ProviderError)
    assert issubclass(ProviderRateLimitError, ProviderError)


def test_completion_request_defaults() -> None:
    request = CompletionRequest(
        model="gpt-x",
        messages=[Message(role="user", content="hi")],
    )
    assert request.temperature == 0.0
    assert request.timeout_seconds == 60.0
    assert request.response_schema is None


def test_completion_request_rejects_empty_messages() -> None:
    with pytest.raises(ValidationError):
        CompletionRequest(model="gpt-x", messages=[])


def test_completion_request_rejects_bad_temperature() -> None:
    with pytest.raises(ValidationError):
        CompletionRequest(
            model="gpt-x",
            messages=[Message(role="user", content="hi")],
            temperature=3.0,
        )


def test_llm_provider_protocol_is_runtime_checkable() -> None:
    from relia.providers.base import LLMProvider

    class _FakeProvider:
        name = "fake"

        async def complete(self, request: CompletionRequest) -> None:  # type: ignore[override]
            return None

    assert isinstance(_FakeProvider(), LLMProvider)

    class _NotAProvider:
        pass

    assert isinstance(_NotAProvider(), LLMProvider) is False


def test_eval_dataset_requires_cases() -> None:
    with pytest.raises(ValidationError):
        EvalDataset(dataset_id="d", version="1", cases=[])


def test_eval_result_round_trip_and_ci_fields() -> None:
    result = EvalResult(
        dataset_id="groundedness",
        dataset_version="1.2.0",
        config_version="prompt-v7",
        metrics=[
            EvalMetric(name="exact_match", value=0.5, higher_is_better=True),
            EvalMetric(
                name="groundedness",
                value=0.82,
                sample_size=400,
                ci_lower=0.78,
                ci_upper=0.86,
            ),
        ],
    )
    restored = EvalResult.model_validate_json(result.model_dump_json())
    assert restored == result
    assert restored.metrics[1].ci_lower is not None


def test_cassette_round_trip() -> None:
    cassette = Cassette(
        cassette_id="c-1",
        provider="fake",
        model="fake-model",
        interactions=[
            RecordedInteraction(request={"prompt": "hi"}, response={"text": "hello"})
        ],
    )
    restored = Cassette.model_validate_json(cassette.model_dump_json())
    assert restored == cassette
    assert restored.interactions[0].recorded_at is not None
