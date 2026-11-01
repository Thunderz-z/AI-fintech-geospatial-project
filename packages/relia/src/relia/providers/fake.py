"""Scripted test-double provider — explicitly a fake, never a real backend.

``ScriptedProvider`` serves pre-arranged responses (or raises pre-arranged
exceptions) and records every request it receives. It exists so RELIA and
the applications can test provider-consuming code paths without network
access or API keys. It implements :class:`relia.providers.base.LLMProvider`
so it can stand in anywhere a provider is expected.
"""

from __future__ import annotations

from relia.providers.base import (
    CompletionRequest,
    CompletionResponse,
    ProviderError,
    Usage,
)

__all__ = ["ScriptedProvider"]


def scripted_response(
    text: str,
    *,
    model: str = "scripted-model",
    provider: str = "scripted",
    input_tokens: int = 1,
    output_tokens: int = 1,
    structured: dict | None = None,
    request_id: str | None = "scripted-req-0",
    cost_usd: float | None = None,
) -> CompletionResponse:
    """Build one canned :class:`CompletionResponse` for use with a scripted provider."""
    return CompletionResponse(
        text=text,
        structured=structured,
        model=model,
        provider=provider,
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
        request_id=request_id,
        cost_usd=cost_usd,
    )


class ScriptedProvider:
    """Replays a fixed queue of responses; records requests for assertions.

    Entries in *responses* may be :class:`CompletionResponse` objects
    (returned as-is) or :class:`Exception` instances (raised as-is) so tests
    can script failure paths too. A call past the end of the queue raises
    :class:`ProviderError` — silently reusing the last response would hide
    call-count bugs.

    This is a test double by design, not a stub awaiting implementation.
    """

    def __init__(
        self,
        *responses: CompletionResponse | Exception,
        name: str = "scripted",
    ) -> None:
        self._responses = list(responses)
        self.name = name
        self.requests: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.requests.append(request)
        index = len(self.requests) - 1
        if index >= len(self._responses):
            raise ProviderError(
                f"ScriptedProvider {self.name!r} exhausted: "
                f"{len(self._responses)} scripted response(s) configured but "
                f"call {index + 1} arrived."
            )
        item = self._responses[index]
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def calls(self) -> int:
        return len(self.requests)

    @classmethod
    def text(
        cls, *texts: str, name: str = "scripted", model: str = "scripted-model"
    ) -> ScriptedProvider:
        """Convenience: one canned plain-text response per *texts* entry."""
        return cls(
            *(
                scripted_response(text, model=model, provider=name)
                for text in texts
            ),
            name=name,
        )
