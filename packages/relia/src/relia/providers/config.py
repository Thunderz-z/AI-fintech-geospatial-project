"""Provider configuration, usage ledger and shared validation helpers.

Split out of ``openai_compat`` so the shared HTTP base class and the
presets factory can depend on configuration without importing a specific
wire protocol. ``ProviderConfig`` and ``UsageLedger`` remain importable
from ``relia.providers.openai_compat`` for backward compatibility.

``ProviderConfig.from_env()`` reads ``<PREFIX>API_KEY`` (required) plus
optional ``BASE_URL``, ``PROVIDER_NAME``, ``DEFAULT_MODEL``,
``MAX_OUTPUT_TOKENS``, ``INPUT_COST_PER_MTOK`` and ``OUTPUT_COST_PER_MTOK``
variables from the process environment with a repository-``.env`` fallback.
Each provider preset passes its own prefix (e.g. ``RELIA_ANTHROPIC_``) so
multiple vendors can be configured side by side without collisions.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import jsonschema
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from relia.config.paths import find_repo_root, read_dotenv
from relia.providers.base import (
    CompletionResponse,
    MalformedStructuredOutputError,
    ProviderError,
    Usage,
)

ENV_PREFIX = "RELIA_LLM_"

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
    default_max_output_tokens: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Fallback output-token cap for protocols that require max_tokens "
            "(the Anthropic Messages API); used when the request sets none."
        ),
    )
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
        cls,
        *,
        prefix: str = ENV_PREFIX,
        start: Path | None = None,
        default_base_url: str | None = None,
        default_provider_name: str | None = None,
        require_base_url: bool = False,
    ) -> ProviderConfig:
        """Build a config from ``<PREFIX>``-suffixed environment variables.

        Resolution order per variable: process environment first, then the
        repository's local ``.env`` (never committed), located by walking up
        from *start* (default: cwd).

        ``default_base_url`` / ``default_provider_name`` let presets inject
        their vendor defaults; with ``require_base_url`` the caller declares
        that no default endpoint exists and ``BASE_URL`` must be configured.

        Raises:
            ProviderError: If no API key is configured, the base URL is
                required but missing, or a numeric variable is malformed.
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
                f"(never committed) as e.g. {prefix}API_KEY=... or export it in "
                "the shell. Tests must not need it: use scripted providers or "
                "a mock transport instead."
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

        default_max_output_tokens: int | None = None
        max_output_raw = lookup("MAX_OUTPUT_TOKENS")
        if max_output_raw is not None:
            try:
                default_max_output_tokens = int(max_output_raw)
            except ValueError as exc:
                raise ProviderError(
                    f"{prefix}MAX_OUTPUT_TOKENS={max_output_raw!r} is not a "
                    "valid integer."
                ) from exc

        base_url = lookup("BASE_URL")
        if base_url is None:
            if require_base_url:
                raise ProviderError(
                    f"{prefix}BASE_URL is required for this provider (it has "
                    f"no default endpoint), e.g. {prefix}BASE_URL="
                    "https://your-endpoint/v1."
                )
            base_url = (
                default_base_url
                if default_base_url is not None
                else cls.model_fields["base_url"].default
            )
        provider_name = (
            lookup("PROVIDER_NAME")
            or default_provider_name
            or cls.model_fields["provider_name"].default
        )

        return cls(
            api_key=api_key,
            base_url=base_url,
            provider_name=provider_name,
            default_model=lookup("DEFAULT_MODEL"),
            default_max_output_tokens=default_max_output_tokens,
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
