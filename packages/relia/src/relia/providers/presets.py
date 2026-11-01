"""Named provider presets — one-liner construction from per-vendor .env vars.

Each preset pins a wire protocol, a default endpoint and its own
``RELIA_<VENDOR>_*`` environment prefix, so several vendors can be
configured side by side in one ``.env`` without key collisions:

============ ==========================  ==================  ==================================
Preset       Wire protocol               Default base URL    Env prefix
============ ==========================  ==================  ==================================
``claude``   Anthropic Messages API      api.anthropic.com   ``RELIA_ANTHROPIC_``
``grok``     OpenAI chat completions     api.x.ai            ``RELIA_GROK_``
``custom``   OpenAI chat completions     *required*          ``RELIA_CUSTOM_``
``openai-compatible`` OpenAI chat completions  api.openai.com ``RELIA_LLM_``
============ ==========================  ==================  ==================================

Keys go in the worktree's local ``.env`` only (never committed, never on
the command line — shell history). ``grok`` needs no protocol code: the xAI
API implements the OpenAI chat-completions format; the preset pins the
endpoint. ``custom`` accepts any OpenAI-compatible endpoint (vLLM, OpenRouter,
corporate gateways, ...) with ``BASE_URL`` mandatory.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict

from relia.providers.anthropic import AnthropicProvider
from relia.providers.base import ProviderError
from relia.providers.config import ENV_PREFIX, ProviderConfig
from relia.providers.openai_compat import OpenAICompatibleProvider

__all__ = ["PROVIDER_PRESETS", "ProviderPreset", "create_provider"]

Protocol = Literal["openai-compatible", "anthropic"]


class ProviderPreset(BaseModel):
    """One vendor's construction recipe (immutable)."""

    model_config = ConfigDict(frozen=True)

    preset_name: str
    protocol: Protocol
    env_prefix: str
    default_base_url: str | None = None  # None → BASE_URL required ("custom")


PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    "openai-compatible": ProviderPreset(
        preset_name="openai-compatible",
        protocol="openai-compatible",
        env_prefix=ENV_PREFIX,
        default_base_url="https://api.openai.com/v1",
    ),
    "claude": ProviderPreset(
        preset_name="claude",
        protocol="anthropic",
        env_prefix="RELIA_ANTHROPIC_",
        default_base_url="https://api.anthropic.com/v1",
    ),
    "grok": ProviderPreset(
        preset_name="grok",
        protocol="openai-compatible",
        env_prefix="RELIA_GROK_",
        default_base_url="https://api.x.ai/v1",
    ),
    "custom": ProviderPreset(
        preset_name="custom",
        protocol="openai-compatible",
        env_prefix="RELIA_CUSTOM_",
        default_base_url=None,
    ),
}


def create_provider(
    preset_name: str,
    *,
    config: ProviderConfig | None = None,
    start: Path | None = None,
    http_client: httpx.AsyncClient | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Any:
    """Build the provider for *preset_name* from its env prefix.

    Args:
        preset_name: One of :data:`PROVIDER_PRESETS`.
        config: Optional pre-built config (programmatic use — skips the
            environment entirely; the caller controls every field).
        start: Repository-discovery start directory for the ``.env`` fallback.
        http_client: Optional pre-built ``httpx.AsyncClient`` (mock transport
            for tests); when omitted the provider owns its client.
        sleep: Async sleep callable for retry-backoff tests.

    Raises:
        ProviderError: On an unknown preset name or a missing/invalid
            configuration for the preset's env prefix.
    """
    preset = PROVIDER_PRESETS.get(preset_name)
    if preset is None:
        raise ProviderError(
            f"Unknown provider preset {preset_name!r}; known presets: "
            f"{sorted(PROVIDER_PRESETS)}."
        )
    if config is None:
        config = ProviderConfig.from_env(
            prefix=preset.env_prefix,
            start=start,
            default_base_url=preset.default_base_url,
            default_provider_name=preset.preset_name,
            require_base_url=preset.default_base_url is None,
        )
    if preset.protocol == "anthropic":
        return AnthropicProvider(config, http_client=http_client, sleep=sleep)
    return OpenAICompatibleProvider(config, http_client=http_client, sleep=sleep)
