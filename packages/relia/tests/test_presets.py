"""Tests for provider presets (claude / grok / custom / openai-compatible)."""

from __future__ import annotations

import httpx
import pytest

from relia.providers.anthropic import AnthropicProvider
from relia.providers.base import LLMProvider, ProviderError
from relia.providers.openai_compat import OpenAICompatibleProvider
from relia.providers.presets import PROVIDER_PRESETS, create_provider


def mock_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={}, request=req)
        )
    )


def test_preset_catalogue_shapes() -> None:
    assert set(PROVIDER_PRESETS) == {
        "openai-compatible",
        "claude",
        "grok",
        "custom",
    }
    assert PROVIDER_PRESETS["claude"].protocol == "anthropic"
    assert PROVIDER_PRESETS["grok"].protocol == "openai-compatible"
    assert PROVIDER_PRESETS["custom"].default_base_url is None


def test_unknown_preset_raises_with_known_list() -> None:
    with pytest.raises(ProviderError, match="claude.*grok|grok.*claude"):
        create_provider("chatgpt", http_client=mock_client())


def test_claude_preset_builds_anthropic_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RELIA_ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.setenv("RELIA_ANTHROPIC_DEFAULT_MODEL", "claude-sonnet-4-5")

    provider = create_provider("claude", http_client=mock_client())

    assert isinstance(provider, AnthropicProvider)
    assert isinstance(provider, LLMProvider)
    assert provider.name == "claude"
    assert provider.config.base_url == "https://api.anthropic.com/v1"
    assert provider.config.default_model == "claude-sonnet-4-5"


def test_grok_preset_builds_openai_compatible_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RELIA_GROK_API_KEY", "xai-x")

    provider = create_provider("grok", http_client=mock_client())

    assert isinstance(provider, OpenAICompatibleProvider)
    assert isinstance(provider, LLMProvider)
    assert provider.name == "grok"
    assert provider.config.base_url == "https://api.x.ai/v1"


def test_preset_env_prefixes_are_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only the Grok key is configured: the claude preset must not find it.
    monkeypatch.setenv("RELIA_GROK_API_KEY", "xai-x")

    with pytest.raises(ProviderError, match="RELIA_ANTHROPIC_API_KEY"):
        create_provider("claude", http_client=mock_client())


def test_custom_preset_requires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELIA_CUSTOM_API_KEY", "custom-x")

    with pytest.raises(ProviderError, match="RELIA_CUSTOM_BASE_URL"):
        create_provider("custom", http_client=mock_client())


def test_custom_preset_with_gateway_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RELIA_CUSTOM_API_KEY", "custom-x")
    monkeypatch.setenv("RELIA_CUSTOM_BASE_URL", "https://my.gateway/v1")
    monkeypatch.setenv("RELIA_CUSTOM_DEFAULT_MODEL", "my-model-7b")

    provider = create_provider("custom", http_client=mock_client())

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.name == "custom"
    assert provider.config.base_url == "https://my.gateway/v1"
    assert provider.config.default_model == "my-model-7b"


def test_openai_compatible_preset_uses_generic_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RELIA_LLM_API_KEY", "llm-x")

    provider = create_provider("openai-compatible", http_client=mock_client())

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.name == "openai-compatible"
    assert provider.config.base_url == "https://api.openai.com/v1"


def test_preset_base_url_override_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # A preset's default endpoint can be replaced (proxy/region endpoints).
    monkeypatch.setenv("RELIA_GROK_API_KEY", "xai-x")
    monkeypatch.setenv("RELIA_GROK_BASE_URL", "https://grok.proxy.corp/v1")

    provider = create_provider("grok", http_client=mock_client())

    assert provider.config.base_url == "https://grok.proxy.corp/v1"


def test_explicit_config_skips_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from relia.providers.openai_compat import ProviderConfig

    monkeypatch.delenv("RELIA_GROK_API_KEY", raising=False)
    config = ProviderConfig(
        api_key="explicit-key",
        base_url="https://api.x.ai/v1",
        provider_name="grok",
    )

    provider = create_provider("grok", config=config, http_client=mock_client())

    assert provider.config.api_key.get_secret_value() == "explicit-key"
