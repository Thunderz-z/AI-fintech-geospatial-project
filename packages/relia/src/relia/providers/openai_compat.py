"""OpenAI-compatible provider adapter — the first concrete ``LLMProvider``.

Implements the :class:`relia.providers.base.LLMProvider` protocol against any
OpenAI-compatible chat-completions endpoint (OpenAI, Azure OpenAI, Groq,
DeepSeek, vLLM, OpenRouter, ...). Wire details, retry policy and cost
accounting live here; callers only see :class:`CompletionRequest` /
:class:`CompletionResponse`.

Credentials: the adapter is built from a :class:`ProviderConfig`;
``ProviderConfig.from_env()`` reads ``RELIA_LLM_*`` variables from the
environment with a repository-``.env`` fallback. No API key is required for
tests — inject an ``httpx.MockTransport``-backed client or use the scripted
provider in :mod:`relia.providers.fake` to exercise everything network-free.

Stated limitations (not hidden):

* The wire format sends ``max_tokens`` (widest compatibility across
  OpenAI-compatible servers). Servers that only accept
  ``max_completion_tokens`` for newer models need a config switch once a real
  key/endpoint exists — deliberately not built ahead of that.
* A 2xx response without a ``usage`` block raises :class:`ProviderError`
  instead of silently zeroing the accounting; usage integrity beats
  tolerance here.
* Structured outputs are validated client-side with ``jsonschema`` even when
  the server also enforces ``response_format``: the client-side check is the
  contract, server enforcement is only an optimization.
* Retries use exponential backoff **without jitter** — the schedule is
  deterministic and the sleep callable is injectable, which keeps tests
  fast and reproducible. Jitter would help under thundering-herd load; add
  it only when a real endpoint shows that problem.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
import jsonschema
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from relia.config.paths import find_repo_root, read_dotenv
from relia.providers.base import (
    CompletionRequest,
    CompletionResponse,
    MalformedStructuredOutputError,
    Message,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    Usage,
)

__all__ = [
    "ProviderConfig",
    "OpenAICompatibleProvider",
    "UsageLedger",
]

ENV_PREFIX = "RELIA_LLM_"

#: HTTP statuses considered transient and safe to retry with backoff.
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})

_MILLION = 1_000_000


class ProviderConfig(BaseModel):
    """Connection, retry and price configuration for one provider endpoint.

    ``api_key`` is a :class:`~pydantic.SecretStr` so it never appears in
    reprs, logs or serialized dumps.
    """

    model_config = ConfigDict(frozen=True)

    api_key: SecretStr
    base_url: str = "https://api.openai.com/v1"
    provider_name: str = "openai-compatible"
    default_model: str | None = None
    request_timeout_seconds: float = Field(default=60.0, gt=0.0)
    max_retries: int = Field(default=2, ge=0)
    retry_backoff_seconds: float = Field(default=1.0, gt=0.0)
    retry_backoff_max_seconds: float = Field(default=30.0, gt=0.0)
    input_cost_per_mtok: float | None = Field(default=None, ge=0.0)
    output_cost_per_mtok: float | None = Field(default=None, ge=0.0)

    @property
    def prices_configured(self) -> bool:
        return (
            self.input_cost_per_mtok is not None
            and self.output_cost_per_mtok is not None
        )

    @classmethod
    def from_env(
        cls, *, prefix: str = ENV_PREFIX, start: Path | None = None
    ) -> ProviderConfig:
        """Build a config from ``RELIA_LLM_*`` environment variables.

        Resolution order per variable: process environment first, then the
        repository's local ``.env`` (never committed), located by walking up
        from *start* (default: cwd).

        Required: ``API_KEY``. Optional: ``BASE_URL``, ``PROVIDER_NAME``,
        ``DEFAULT_MODEL``, ``INPUT_COST_PER_MTOK``, ``OUTPUT_COST_PER_MTOK``.

        Raises:
            ProviderError: If no API key is configured or a cost variable is
                not a valid number.
        """
        dotenv_values: dict[str, str] = {}
        repo_root = find_repo_root(start)
        if repo_root is not None:
            dotenv_path = repo_root / ".env"
            if dotenv_path.is_file():
                dotenv_values = read_dotenv(dotenv_path)

        def lookup(suffix: str) -> str | None:
            for source in (os.environ, dotenv_values):
                value = source.get(prefix + suffix, "").strip()
                if value:
                    return value
            return None

        api_key = lookup("API_KEY")
        if api_key is None:
            raise ProviderError(
                f"{prefix}API_KEY is not configured. Add it to your local .env "
                "(never committed) as e.g. "
                f"{prefix}API_KEY=sk-... or export it in the shell. "
                "Tests must not need it: use scripted providers or a mock "
                "transport instead."
            )

        cost_rates: dict[str, float] = {}
        for suffix in ("INPUT_COST_PER_MTOK", "OUTPUT_COST_PER_MTOK"):
            raw = lookup(suffix)
            if raw is None:
                continue
            try:
                cost_rates[suffix.lower()] = float(raw)
            except ValueError as exc:
                raise ProviderError(
                    f"{prefix}{suffix}={raw!r} is not a valid number."
                ) from exc

        return cls(
            api_key=api_key,
            base_url=lookup("BASE_URL") or cls.model_fields["base_url"].default,
            provider_name=lookup("PROVIDER_NAME")
            or cls.model_fields["provider_name"].default,
            default_model=lookup("DEFAULT_MODEL"),
            input_cost_per_mtok=cost_rates.get("input_cost_per_mtok"),
            output_cost_per_mtok=cost_rates.get("output_cost_per_mtok"),
        )


class UsageLedger:
    """Cumulative token and cost accounting across completions.

    Records only what the provider actually reported. ``cost_known_for``
    counts completions whose price could be computed — when it is lower than
    ``completions``, ``total_cost_usd`` is a partial sum and callers must
    treat it as such.
    """

    def __init__(self) -> None:
        self.completions = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_known_for = 0
        self.total_cost_usd = 0.0

    def record(self, response: CompletionResponse) -> None:
        self.completions += 1
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens
        if response.cost_usd is not None:
            self.cost_known_for += 1
            self.total_cost_usd += response.cost_usd

    def snapshot(self) -> dict[str, int | float]:
        """Return the accumulated totals as a plain dict (JSON-safe)."""
        return {
            "completions": self.completions,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_known_for": self.cost_known_for,
            "total_cost_usd": self.total_cost_usd,
        }


def _compute_cost_usd(config: ProviderConfig, usage: Usage) -> float | None:
    if not config.prices_configured:
        return None
    assert config.input_cost_per_mtok is not None  # narrowed by prices_configured
    assert config.output_cost_per_mtok is not None
    return (
        usage.input_tokens / _MILLION * config.input_cost_per_mtok
        + usage.output_tokens / _MILLION * config.output_cost_per_mtok
    )


class OpenAICompatibleProvider:
    """Adapter for OpenAI-compatible chat-completions endpoints.

    Args:
        config: Endpoint, retry and price configuration.
        http_client: Optional pre-built ``httpx.AsyncClient``. Pass one with
            an ``httpx.MockTransport`` for network-free tests. When omitted,
            a client is created and owned by the adapter (close it via
            :meth:`aclose`).
        sleep: Async sleep callable used between retries; inject a recorder
            in tests to assert the backoff schedule without real waiting.
    """

    def __init__(
        self,
        config: ProviderConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._config = config
        self._sleep = sleep
        self._client = http_client or httpx.AsyncClient(
            timeout=config.request_timeout_seconds
        )
        self._owns_client = http_client is None
        self.ledger = UsageLedger()

    @property
    def name(self) -> str:
        return self._config.provider_name

    @property
    def config(self) -> ProviderConfig:
        return self._config

    async def aclose(self) -> None:
        """Close the internally owned HTTP client (injected clients are not closed)."""
        if self._owns_client:
            await self._client.aclose()

    def build_request(
        self,
        messages: Sequence[Message | tuple[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
        response_schema: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> CompletionRequest:
        """Build a :class:`CompletionRequest` using the configured defaults.

        ``messages`` accepts :class:`Message` objects or ``(role, content)``
        tuples. The model comes from the explicit argument or the configured
        ``default_model``; with neither, construction fails loudly.
        """
        resolved_model = model or self._config.default_model
        if not resolved_model:
            raise ProviderError(
                "No model given and no default_model configured for provider "
                f"{self.name!r}."
            )
        return CompletionRequest(
            model=resolved_model,
            messages=[
                m if isinstance(m, Message) else Message(role=m[0], content=m[1])
                for m in messages
            ],
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_schema=response_schema,
            timeout_seconds=timeout_seconds
            or self._config.request_timeout_seconds,
        )

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Execute one completion with retries on transient failures."""
        payload = self._build_payload(request)
        url = f"{self._config.base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {self._config.api_key.get_secret_value()}"}

        last_error: ProviderError | None = None
        for attempt in range(self._config.max_retries + 1):
            if attempt > 0:
                await self._sleep(self._backoff_delay(attempt - 1))
            result = await self._attempt(url, headers, payload, request)
            if isinstance(result, CompletionResponse):
                return result
            last_error = result
        assert last_error is not None
        raise last_error

    def _backoff_delay(self, retry_index: int) -> float:
        """Exponential backoff, capped; no jitter (see module docstring)."""
        delay = self._config.retry_backoff_seconds * (2**retry_index)
        return min(delay, self._config.retry_backoff_max_seconds)

    async def _attempt(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        request: CompletionRequest,
    ) -> CompletionResponse | ProviderError:
        """One HTTP attempt. Returns the parsed response or the error to retry/raise."""
        try:
            response = await self._client.post(
                url,
                json=payload,
                headers=headers,
                timeout=request.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            return ProviderTimeoutError(
                f"Provider timed out after {request.timeout_seconds}s: {exc}"
            )
        except httpx.TransportError as exc:
            return ProviderError(f"Transport failure talking to provider: {exc}")

        if response.status_code in _RETRYABLE_STATUS_CODES:
            return self._error_for_status(response)
        if response.status_code >= 400:
            raise self._error_for_status(response)  # non-retryable client error
        return self._parse_response(response, request)

    def _error_for_status(self, response: httpx.Response) -> ProviderError:
        body = response.text[:500]
        if response.status_code == 429:
            return ProviderRateLimitError(
                f"Provider rate limit hit (HTTP 429): {body}"
            )
        return ProviderError(
            f"Provider returned HTTP {response.status_code}: {body}"
        )

    def _build_payload(self, request: CompletionRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "temperature": request.temperature,
        }
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        if request.response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": request.response_schema,
                },
            }
        return payload

    def _parse_response(
        self, response: httpx.Response, request: CompletionRequest
    ) -> CompletionResponse:
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                f"Provider returned non-JSON body (HTTP {response.status_code})."
            ) from exc

        choices = data.get("choices")
        if not choices or not isinstance(choices, list):
            raise ProviderError("Provider response contains no choices.")
        content = (choices[0].get("message") or {}).get("content")
        if not isinstance(content, str):
            raise ProviderError(
                "Provider response has no text content (tool-call or empty "
                "responses are not supported by this adapter)."
            )

        usage_raw = data.get("usage")
        if not isinstance(usage_raw, dict):
            raise ProviderError(
                "Provider response does not report usage; refusing to record "
                "a completion with unknown token consumption."
            )
        try:
            usage = Usage(
                input_tokens=int(usage_raw["prompt_tokens"]),
                output_tokens=int(usage_raw["completion_tokens"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(
                f"Provider usage block is malformed: {usage_raw!r}"
            ) from exc

        structured = None
        if request.response_schema is not None:
            structured = _validate_structured(content, request.response_schema)

        completion = CompletionResponse(
            text=content,
            structured=structured,
            model=str(data.get("model", request.model)),
            provider=self.name,
            usage=usage,
            request_id=data.get("id"),
            cost_usd=_compute_cost_usd(self._config, usage),
        )
        self.ledger.record(completion)
        return completion


def _validate_structured(text: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate *text* against *schema*; raise on any violation."""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedStructuredOutputError(
            f"Structured response is not valid JSON: {exc}"
        ) from exc
    try:
        jsonschema.validate(instance=parsed, schema=schema)
    except jsonschema.SchemaError as exc:
        raise ProviderError(
            f"request.response_schema is itself invalid: {exc.message}"
        ) from exc
    except jsonschema.ValidationError as exc:
        raise MalformedStructuredOutputError(
            f"Structured response violates response_schema: {exc.message}"
        ) from exc
    if not isinstance(parsed, dict):
        raise MalformedStructuredOutputError(
            "Structured response must be a JSON object; got "
            f"{type(parsed).__name__} (CompletionResponse.structured is "
            "object-typed by design)."
        )
    return parsed
