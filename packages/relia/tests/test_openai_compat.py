"""Tests for the OpenAI-compatible provider adapter — all network-free.

The adapter is exercised through ``httpx.MockTransport`` and an injected
sleep recorder, so timeouts, retries, backoff schedules and error mapping
are tested without any real endpoint or API key.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from relia.providers.base import (
    CompletionRequest,
    LLMProvider,
    MalformedStructuredOutputError,
    Message,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from relia.providers.fake import ScriptedProvider
from relia.providers.openai_compat import OpenAICompatibleProvider, ProviderConfig

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}, "confidence": {"type": "number"}},
    "required": ["answer"],
}


def run(coro):
    """Drive one coroutine to completion on a fresh event loop."""
    return asyncio.run(coro)


def make_config(**overrides) -> ProviderConfig:
    defaults: dict = {
        "api_key": "test-key-123",
        "base_url": "https://fake.endpoint/v1",
        "provider_name": "fake-compatible",
        "input_cost_per_mtok": 1.0,
        "output_cost_per_mtok": 2.0,
    }
    defaults.update(overrides)
    return ProviderConfig(**defaults)


def make_provider(
    handler,
    config: ProviderConfig | None = None,
    sleeps: list[float] | None = None,
) -> OpenAICompatibleProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def _sleep(delay: float) -> None:
        if sleeps is not None:
            sleeps.append(delay)

    return OpenAICompatibleProvider(config or make_config(), http_client=client, sleep=_sleep)


def make_request(**overrides) -> CompletionRequest:
    defaults: dict = {
        "model": "test-model",
        "messages": [Message(role="user", content="hi")],
    }
    defaults.update(overrides)
    return CompletionRequest(**defaults)


def chat_response(
    text: str = "hello",
    input_tokens: int = 10,
    output_tokens: int = 5,
    model: str = "test-model",
    request_id: str = "req-1",
) -> dict:
    return {
        "id": request_id,
        "model": model,
        "choices": [
            {
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens},
    }


# --- happy path -----------------------------------------------------------


def test_success_parses_response_and_computes_cost() -> None:
    provider = make_provider(
        lambda req: httpx.Response(200, json=chat_response(), request=req)
    )

    response = run(provider.complete(make_request()))

    assert response.text == "hello"
    assert response.model == "test-model"
    assert response.provider == "fake-compatible"
    assert response.request_id == "req-1"
    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 5
    assert response.structured is None
    expected_cost = 10 / 1e6 * 1.0 + 5 / 1e6 * 2.0
    assert response.cost_usd == pytest.approx(expected_cost)
    snapshot = provider.ledger.snapshot()
    assert snapshot["completions"] == 1


def test_cost_is_none_without_price_sheet() -> None:
    provider = make_provider(
        lambda req: httpx.Response(200, json=chat_response(), request=req),
        make_config(input_cost_per_mtok=None),
    )

    response = run(provider.complete(make_request()))

    assert response.cost_usd is None
    snapshot = provider.ledger.snapshot()
    assert snapshot["total_cost_usd"] == 0.0
    assert snapshot["cost_known_for"] == 0
    assert snapshot["input_tokens"] == 10


def test_ledger_accumulates_across_calls() -> None:
    provider = make_provider(
        lambda req: httpx.Response(200, json=chat_response(), request=req)
    )

    run(provider.complete(make_request()))
    run(provider.complete(make_request()))

    snapshot = provider.ledger.snapshot()
    assert snapshot["completions"] == 2
    assert snapshot["input_tokens"] == 20
    assert snapshot["output_tokens"] == 10
    assert snapshot["cost_known_for"] == 2
    assert snapshot["total_cost_usd"] == pytest.approx(4e-5)


def test_wire_payload_and_auth_header() -> None:
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["auth"] = req.headers.get("Authorization")
        captured["payload"] = json.loads(req.content.decode("utf-8"))
        return httpx.Response(200, json=chat_response(), request=req)

    provider = make_provider(handler)
    run(provider.complete(make_request(temperature=0.4, max_output_tokens=128)))

    assert captured["url"] == "https://fake.endpoint/v1/chat/completions"
    assert captured["auth"] == "Bearer test-key-123"
    payload = captured["payload"]
    assert payload["model"] == "test-model"
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert payload["temperature"] == 0.4
    assert payload["max_tokens"] == 128
    assert "response_format" not in payload


def test_response_format_sent_for_schema_requests() -> None:
    captured: dict = {}
    text = json.dumps({"answer": "ok"})

    def handler(req: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(req.content.decode("utf-8"))
        return httpx.Response(200, json=chat_response(text=text), request=req)

    provider = make_provider(handler)
    run(provider.complete(make_request(response_schema=ANSWER_SCHEMA)))

    response_format = captured["payload"]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["schema"] == ANSWER_SCHEMA


def test_adapters_satisfy_llm_provider_protocol() -> None:
    provider = make_provider(
        lambda req: httpx.Response(200, json=chat_response(), request=req)
    )
    assert isinstance(provider, LLMProvider)
    assert isinstance(ScriptedProvider.text("hi"), LLMProvider)


# --- structured output validation -----------------------------------------


def test_structured_output_validated_and_returned() -> None:
    text = json.dumps({"answer": "42", "confidence": 0.9})
    provider = make_provider(
        lambda req: httpx.Response(200, json=chat_response(text=text), request=req)
    )

    response = run(provider.complete(make_request(response_schema=ANSWER_SCHEMA)))

    assert response.structured == {"answer": "42", "confidence": 0.9}
    assert response.text == text


def test_malformed_json_raises_malformed_structured_output() -> None:
    provider = make_provider(
        lambda req: httpx.Response(
            200, json=chat_response(text="not json at all"), request=req
        )
    )

    with pytest.raises(MalformedStructuredOutputError, match="not valid JSON"):
        run(provider.complete(make_request(response_schema=ANSWER_SCHEMA)))


def test_schema_violation_raises_malformed_structured_output() -> None:
    text = json.dumps({"confidence": 0.9})  # missing required "answer"
    provider = make_provider(
        lambda req: httpx.Response(200, json=chat_response(text=text), request=req)
    )

    with pytest.raises(MalformedStructuredOutputError, match="response_schema"):
        run(provider.complete(make_request(response_schema=ANSWER_SCHEMA)))


def test_non_object_structured_response_rejected() -> None:
    # Schema-valid JSON array, but CompletionResponse.structured is
    # object-typed by design — must fail loudly, not silently coerce.
    text = json.dumps(["an", "array"])
    provider = make_provider(
        lambda req: httpx.Response(200, json=chat_response(text=text), request=req)
    )

    with pytest.raises(MalformedStructuredOutputError, match="JSON object"):
        run(provider.complete(make_request(response_schema={"type": "array"})))


def test_invalid_request_schema_is_provider_error_not_malformed() -> None:
    text = json.dumps({"answer": "x"})
    provider = make_provider(
        lambda req: httpx.Response(200, json=chat_response(text=text), request=req)
    )

    with pytest.raises(ProviderError, match="response_schema is itself invalid"):
        run(provider.complete(make_request(response_schema={"type": "no-such-type"})))


# --- retries, backoff and error mapping ------------------------------------


def test_retries_429_with_exponential_backoff_then_succeeds() -> None:
    calls = {"n": 0}
    sleeps: list[float] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(429, json={"error": "slow down"}, request=req)
        return httpx.Response(200, json=chat_response(), request=req)

    config = make_config(max_retries=3, retry_backoff_seconds=1.0)
    provider = make_provider(handler, config, sleeps=sleeps)

    response = run(provider.complete(make_request()))

    assert calls["n"] == 3
    assert sleeps == [1.0, 2.0]  # exponential, no jitter
    assert response.text == "hello"


def test_rate_limit_exhaustion_raises_rate_limit_error() -> None:
    sleeps: list[float] = []

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "slow down"}, request=req)

    config = make_config(max_retries=2, retry_backoff_seconds=1.0)
    provider = make_provider(handler, config, sleeps=sleeps)

    with pytest.raises(ProviderRateLimitError, match="429"):
        run(provider.complete(make_request()))
    assert provider.config.max_retries == 2


def test_5xx_is_retried_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="overloaded", request=req)
        return httpx.Response(200, json=chat_response(), request=req)

    provider = make_provider(handler, make_config(max_retries=2))

    response = run(provider.complete(make_request()))
    assert calls["n"] == 2
    assert response.text == "hello"


def test_4xx_client_errors_are_not_retried() -> None:
    calls = {"n": 0}
    sleeps: list[float] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": "bad key"}, request=req)

    provider = make_provider(handler, make_config(max_retries=3), sleeps=sleeps)

    with pytest.raises(ProviderError, match="401"):
        run(provider.complete(make_request()))
    assert calls["n"] == 1
    assert sleeps == []


def test_timeout_maps_to_provider_timeout_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("too slow", request=req)

    provider = make_provider(handler, make_config(max_retries=0))

    with pytest.raises(ProviderTimeoutError, match="timed out"):
        run(provider.complete(make_request()))


def test_transport_errors_are_retried() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection reset", request=req)
        return httpx.Response(200, json=chat_response(), request=req)

    provider = make_provider(handler, make_config(max_retries=1))

    response = run(provider.complete(make_request()))
    assert calls["n"] == 2
    assert response.text == "hello"


def test_backoff_schedule_is_capped() -> None:
    sleeps: list[float] = []

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="slow down", request=req)

    config = make_config(
        max_retries=4, retry_backoff_seconds=1.0, retry_backoff_max_seconds=1.5
    )
    provider = make_provider(handler, config, sleeps=sleeps)

    with pytest.raises(ProviderRateLimitError):
        run(provider.complete(make_request()))
    assert sleeps == [1.0, 1.5, 1.5, 1.5]


# --- response integrity -----------------------------------------------------


def test_missing_usage_block_raises_provider_error() -> None:
    body = chat_response()
    del body["usage"]
    provider = make_provider(lambda req: httpx.Response(200, json=body, request=req))

    with pytest.raises(ProviderError, match="usage"):
        run(provider.complete(make_request()))


def test_malformed_usage_raises_provider_error() -> None:
    body = chat_response()
    body["usage"] = {"prompt_tokens": "ten"}
    provider = make_provider(lambda req: httpx.Response(200, json=body, request=req))

    with pytest.raises(ProviderError, match="malformed"):
        run(provider.complete(make_request()))


def test_empty_choices_raises_provider_error() -> None:
    provider = make_provider(
        lambda req: httpx.Response(200, json={"choices": []}, request=req)
    )

    with pytest.raises(ProviderError, match="no choices"):
        run(provider.complete(make_request()))


def test_non_json_body_raises_provider_error() -> None:
    provider = make_provider(
        lambda req: httpx.Response(200, text="<html>oops</html>", request=req)
    )

    with pytest.raises(ProviderError, match="non-JSON"):
        run(provider.complete(make_request()))


# --- configuration -----------------------------------------------------------


def test_from_env_reads_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELIA_LLM_API_KEY", "env-key")
    monkeypatch.setenv("RELIA_LLM_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("RELIA_LLM_PROVIDER_NAME", "env-provider")
    monkeypatch.setenv("RELIA_LLM_DEFAULT_MODEL", "env-model")
    monkeypatch.setenv("RELIA_LLM_INPUT_COST_PER_MTOK", "0.5")
    monkeypatch.setenv("RELIA_LLM_OUTPUT_COST_PER_MTOK", "1.5")

    config = ProviderConfig.from_env()

    assert config.api_key.get_secret_value() == "env-key"
    assert config.base_url == "https://env.example/v1"
    assert config.provider_name == "env-provider"
    assert config.default_model == "env-model"
    assert config.input_cost_per_mtok == 0.5
    assert config.output_cost_per_mtok == 1.5


def test_from_env_falls_back_to_repo_dotenv(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".python-version").write_text("3.13")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / ".env").write_text('RELIA_LLM_API_KEY="dotenv-key"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RELIA_LLM_API_KEY", raising=False)

    config = ProviderConfig.from_env()

    assert config.api_key.get_secret_value() == "dotenv-key"


def test_from_env_prefers_environment_over_dotenv(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".python-version").write_text("3.13")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / ".env").write_text("RELIA_LLM_API_KEY=dotenv-key\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RELIA_LLM_API_KEY", "env-key")

    config = ProviderConfig.from_env()

    assert config.api_key.get_secret_value() == "env-key"


def test_from_env_missing_key_raises_with_instructions(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # no repo markers, no .env
    monkeypatch.delenv("RELIA_LLM_API_KEY", raising=False)

    with pytest.raises(ProviderError, match="RELIA_LLM_API_KEY"):
        ProviderConfig.from_env()


def test_from_env_invalid_cost_raises_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RELIA_LLM_API_KEY", "k")
    monkeypatch.setenv("RELIA_LLM_INPUT_COST_PER_MTOK", "cheap")

    with pytest.raises(ProviderError, match="not a valid number"):
        ProviderConfig.from_env()


def test_config_repr_and_json_do_not_leak_api_key() -> None:
    config = make_config()

    assert "test-key-123" not in repr(config)
    assert "test-key-123" not in config.model_dump_json()


def test_build_request_uses_default_model_and_tuple_messages() -> None:
    provider = OpenAICompatibleProvider(
        make_config(default_model="default-model"),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json=chat_response(), request=req)
        )),
    )

    req = provider.build_request([("user", "hi")], max_output_tokens=16)

    assert req.model == "default-model"
    assert req.messages == [Message(role="user", content="hi")]
    assert req.max_output_tokens == 16


def test_build_request_requires_model_when_no_default() -> None:
    provider = OpenAICompatibleProvider(
        make_config(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json=chat_response(), request=req)
        )),
    )

    with pytest.raises(ProviderError, match="default_model"):
        provider.build_request([("user", "hi")])
