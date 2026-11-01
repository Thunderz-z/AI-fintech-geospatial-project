"""Tests for the Anthropic (Claude) Messages-API adapter — network-free."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from relia.providers.anthropic import ANTHROPIC_VERSION, AnthropicProvider
from relia.providers.base import (
    CompletionRequest,
    LLMProvider,
    MalformedStructuredOutputError,
    Message,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from relia.providers.openai_compat import ProviderConfig

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}, "confidence": {"type": "number"}},
    "required": ["answer"],
}


def run(coro):
    return asyncio.run(coro)


def make_config(**overrides) -> ProviderConfig:
    defaults: dict = {
        "api_key": "sk-ant-test",
        "base_url": "https://fake.anthropic/v1",
        "provider_name": "claude-test",
        "input_cost_per_mtok": 3.0,
        "output_cost_per_mtok": 15.0,
    }
    defaults.update(overrides)
    return ProviderConfig(**defaults)


def make_provider(
    handler,
    config: ProviderConfig | None = None,
    sleeps: list[float] | None = None,
) -> AnthropicProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def _sleep(delay: float) -> None:
        if sleeps is not None:
            sleeps.append(delay)

    return AnthropicProvider(config or make_config(), http_client=client, sleep=_sleep)


def make_request(**overrides) -> CompletionRequest:
    defaults: dict = {
        "model": "claude-test-model",
        "messages": [Message(role="user", content="hi")],
    }
    defaults.update(overrides)
    return CompletionRequest(**defaults)


def anthropic_response(
    text: str = "hello",
    input_tokens: int = 10,
    output_tokens: int = 5,
    model: str = "claude-test-model",
    request_id: str = "msg_1",
) -> dict:
    return {
        "id": request_id,
        "model": model,
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def test_success_parses_response_and_computes_cost() -> None:
    provider = make_provider(
        lambda req: httpx.Response(200, json=anthropic_response(), request=req)
    )

    response = run(provider.complete(make_request()))

    assert response.text == "hello"
    assert response.provider == "claude-test"
    assert response.model == "claude-test-model"
    assert response.request_id == "msg_1"
    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 5
    expected_cost = 10 / 1e6 * 3.0 + 5 / 1e6 * 15.0
    assert response.cost_usd == pytest.approx(expected_cost)
    assert provider.ledger.snapshot()["completions"] == 1


def test_wire_url_headers_and_system_extraction() -> None:
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["headers"] = dict(req.headers)
        captured["payload"] = json.loads(req.content.decode("utf-8"))
        return httpx.Response(200, json=anthropic_response(), request=req)

    provider = make_provider(handler)
    request = make_request(
        messages=[
            Message(role="system", content="Be terse."),
            Message(role="user", content="hi"),
        ],
        temperature=0.2,
    )
    run(provider.complete(request))

    assert captured["url"] == "https://fake.anthropic/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-ant-test"
    assert captured["headers"]["anthropic-version"] == ANTHROPIC_VERSION
    payload = captured["payload"]
    assert payload["model"] == "claude-test-model"
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert payload["system"] == "Be terse."
    assert payload["temperature"] == 0.2


def test_max_tokens_resolution_order() -> None:
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured.setdefault(
            "payloads", []
        ).append(json.loads(req.content.decode("utf-8")))
        return httpx.Response(200, json=anthropic_response(), request=req)

    # 1) request value wins
    provider = make_provider(handler, make_config(default_max_output_tokens=77))
    run(provider.complete(make_request(max_output_tokens=128)))
    # 2) config default next
    run(provider.complete(make_request()))
    # 3) documented 1024 fallback
    provider = make_provider(handler)
    run(provider.complete(make_request()))

    assert captured["payloads"][0]["max_tokens"] == 128
    assert captured["payloads"][1]["max_tokens"] == 77
    assert captured["payloads"][2]["max_tokens"] == 1024


def test_multiple_system_messages_join_and_text_blocks_concatenate() -> None:
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(req.content.decode("utf-8"))
        body = anthropic_response()
        body["content"] = [
            {"type": "text", "text": "part one "},
            {"type": "tool_use", "id": "t1", "name": "x", "input": {}},
            {"type": "text", "text": "part two"},
        ]
        return httpx.Response(200, json=body, request=req)

    provider = make_provider(handler)
    response = run(
        provider.complete(
            make_request(
                messages=[
                    Message(role="system", content="s1"),
                    Message(role="system", content="s2"),
                    Message(role="user", content="hi"),
                ]
            )
        )
    )

    assert captured["payload"]["system"] == "s1\n\ns2"
    assert response.text == "part one part two"


def test_tool_role_message_rejected() -> None:
    provider = make_provider(
        lambda req: httpx.Response(200, json=anthropic_response(), request=req)
    )

    with pytest.raises(ProviderError, match="not supported"):
        run(
            provider.complete(
                make_request(messages=[Message(role="tool", content="result")])
            )
        )


def test_system_only_messages_rejected() -> None:
    provider = make_provider(
        lambda req: httpx.Response(200, json=anthropic_response(), request=req)
    )

    with pytest.raises(ProviderError, match="at least one user/assistant"):
        run(
            provider.complete(
                make_request(messages=[Message(role="system", content="s")])
            )
        )


def test_structured_output_schema_sent_as_system_instruction() -> None:
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(req.content.decode("utf-8"))
        body = anthropic_response(text=json.dumps({"answer": "42", "confidence": 0.9}))
        return httpx.Response(200, json=body, request=req)

    provider = make_provider(handler)
    response = run(provider.complete(make_request(response_schema=ANSWER_SCHEMA)))

    assert response.structured == {"answer": "42", "confidence": 0.9}
    system_text = captured["payload"]["system"]
    assert "JSON Schema" in system_text
    assert '"required"' in system_text  # the schema itself is embedded


def test_structured_output_malformed_json_raises() -> None:
    provider = make_provider(
        lambda req: httpx.Response(
            200, json=anthropic_response(text="not json"), request=req
        )
    )

    with pytest.raises(MalformedStructuredOutputError, match="not valid JSON"):
        run(provider.complete(make_request(response_schema=ANSWER_SCHEMA)))


def test_structured_output_schema_violation_raises() -> None:
    body = anthropic_response(text=json.dumps({"confidence": 0.9}))
    provider = make_provider(lambda req: httpx.Response(200, json=body, request=req))

    with pytest.raises(MalformedStructuredOutputError, match="response_schema"):
        run(provider.complete(make_request(response_schema=ANSWER_SCHEMA)))


def test_retries_429_then_succeeds() -> None:
    calls = {"n": 0}
    sleeps: list[float] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": "rate_limited"}, request=req)
        return httpx.Response(200, json=anthropic_response(), request=req)

    provider = make_provider(
        handler, make_config(max_retries=2), sleeps=sleeps
    )

    response = run(provider.complete(make_request()))
    assert calls["n"] == 2
    assert sleeps == [1.0]
    assert response.text == "hello"


def test_retries_529_overloaded_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(529, json={"error": "overloaded"}, request=req)
        return httpx.Response(200, json=anthropic_response(), request=req)

    provider = make_provider(handler, make_config(max_retries=1))

    response = run(provider.complete(make_request()))
    assert calls["n"] == 2
    assert response.text == "hello"


def test_rate_limit_exhaustion_raises() -> None:
    provider = make_provider(
        lambda req: httpx.Response(429, text="slow down", request=req),
        make_config(max_retries=1),
    )

    with pytest.raises(ProviderRateLimitError):
        run(provider.complete(make_request()))


def test_4xx_not_retried() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": "bad key"}, request=req)

    provider = make_provider(handler, make_config(max_retries=3))

    with pytest.raises(ProviderError, match="401"):
        run(provider.complete(make_request()))
    assert calls["n"] == 1


def test_timeout_maps_to_provider_timeout_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("too slow", request=req)

    provider = make_provider(handler, make_config(max_retries=0))

    with pytest.raises(ProviderTimeoutError, match="timed out"):
        run(provider.complete(make_request()))


def test_response_integrity_errors() -> None:
    # no usage block
    body = anthropic_response()
    del body["usage"]
    provider = make_provider(lambda req: httpx.Response(200, json=body, request=req))
    with pytest.raises(ProviderError, match="usage"):
        run(provider.complete(make_request()))

    # only non-text blocks
    body = anthropic_response()
    body["content"] = [{"type": "tool_use", "id": "t", "name": "x", "input": {}}]
    provider = make_provider(lambda req: httpx.Response(200, json=body, request=req))
    with pytest.raises(ProviderError, match="no text content"):
        run(provider.complete(make_request()))

    # no content field at all
    body = anthropic_response()
    del body["content"]
    provider = make_provider(lambda req: httpx.Response(200, json=body, request=req))
    with pytest.raises(ProviderError, match="no content blocks"):
        run(provider.complete(make_request()))


def test_ledger_accumulates_and_protocol_conformance() -> None:
    provider = make_provider(
        lambda req: httpx.Response(200, json=anthropic_response(), request=req)
    )
    assert isinstance(provider, LLMProvider)

    run(provider.complete(make_request()))
    run(provider.complete(make_request()))

    snapshot = provider.ledger.snapshot()
    assert snapshot["completions"] == 2
    assert snapshot["input_tokens"] == 20
