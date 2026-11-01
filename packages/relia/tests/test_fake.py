"""Tests for the scripted test-double provider."""

from __future__ import annotations

import asyncio

import pytest

from relia.providers.base import (
    CompletionRequest,
    LLMProvider,
    Message,
    ProviderError,
    ProviderTimeoutError,
)
from relia.providers.fake import ScriptedProvider, scripted_response


def run(coro):
    return asyncio.run(coro)


def make_request(content: str = "hi") -> CompletionRequest:
    return CompletionRequest(
        model="m", messages=[Message(role="user", content=content)]
    )


def test_scripted_provider_returns_responses_in_order_and_records_requests() -> None:
    provider = ScriptedProvider.text("first", "second")

    first = run(provider.complete(make_request("q1")))
    second = run(provider.complete(make_request("q2")))

    assert first.text == "first"
    assert second.text == "second"
    assert provider.calls == 2
    assert provider.requests[0].messages[0].content == "q1"
    assert provider.requests[1].messages[0].content == "q2"


def test_scripted_provider_raises_scripted_exceptions() -> None:
    boom = ProviderTimeoutError("scripted timeout")
    provider = ScriptedProvider(boom, scripted_response("recovered"))

    with pytest.raises(ProviderTimeoutError, match="scripted timeout"):
        run(provider.complete(make_request()))

    response = run(provider.complete(make_request()))
    assert response.text == "recovered"


def test_scripted_provider_exhaustion_raises_provider_error() -> None:
    provider = ScriptedProvider(scripted_response("only one"))

    run(provider.complete(make_request()))
    with pytest.raises(ProviderError, match="exhausted"):
        run(provider.complete(make_request()))


def test_scripted_provider_is_protocol_conformant() -> None:
    assert isinstance(ScriptedProvider(), LLMProvider)


def test_scripted_response_defaults_are_cleared_labelled() -> None:
    response = scripted_response("hi")

    assert response.provider == "scripted"
    assert response.model == "scripted-model"
    assert response.request_id == "scripted-req-0"
