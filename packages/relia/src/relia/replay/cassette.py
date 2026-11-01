"""Cassette recorder and replayer behind the provider interface.

Both classes implement :class:`relia.providers.base.LLMProvider`, so tests
and evaluations can swap a real provider for tape without call-site changes:

* :class:`RecordingProvider` wraps any provider and appends every
  request/response pair to a :class:`~relia.replay.base.Cassette`.
* :class:`ReplayProvider` serves the recorded responses back, strictly and
  in order. Any divergence — a request that differs from what was recorded,
  more calls than recorded, or a corrupt recording — raises
  :class:`~relia.replay.base.ReplayMismatchError`. Replay mismatch is an
  error by design: silent divergence would hide regressions.

Request matching is exact dict equality on the serialized request
(``mode="json"``), including model, messages, temperature, token limits,
timeout and response schema — any change in what is sent invalidates the
tape. After replaying, call :meth:`ReplayProvider.verify_complete` to catch
recorded-but-never-replayed interactions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from relia.providers.base import CompletionRequest, CompletionResponse
from relia.replay.base import Cassette, RecordedInteraction, ReplayMismatchError

__all__ = [
    "RecordingProvider",
    "ReplayProvider",
    "load_cassette",
    "save_cassette",
]

_TRUNCATE = 120


def _request_key(request: CompletionRequest) -> dict[str, Any]:
    """Canonical serialized request used for recording and matching."""
    return request.model_dump(mode="json")


def _short(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= _TRUNCATE else text[: _TRUNCATE - 3] + "..."


def _describe_divergence(
    expected: dict[str, Any], actual: dict[str, Any]
) -> str:
    differing = sorted(
        key for key in set(expected) | set(actual)
        if expected.get(key) != actual.get(key)
    )
    return "; ".join(
        f"{key}: recorded {_short(expected.get(key))} vs sent {_short(actual.get(key))}"
        for key in differing
    )


class RecordingProvider:
    """Wrap a provider, recording every interaction into a cassette."""

    def __init__(self, inner: Any, cassette_id: str) -> None:
        self._inner = inner
        self.cassette = Cassette(
            cassette_id=cassette_id,
            provider=inner.name,
            model="recorded-per-request",
        )

    @property
    def name(self) -> str:
        return self._inner.name

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        response = await self._inner.complete(request)
        self.cassette.interactions.append(
            RecordedInteraction(
                request=_request_key(request),
                response=response.model_dump(mode="json"),
            )
        )
        return response

    def save(self, path: str | Path) -> Path:
        """Write the cassette to *path* as JSON and return the resolved path."""
        return save_cassette(self.cassette, path)


class ReplayProvider:
    """Serve pre-recorded responses; raise on any divergence."""

    def __init__(self, cassette: Cassette) -> None:
        self._cassette = cassette
        self._cursor = 0

    @property
    def name(self) -> str:
        return self._cassette.provider

    @property
    def cassette_id(self) -> str:
        return self._cassette.cassette_id

    @property
    def consumed(self) -> int:
        return self._cursor

    @property
    def remaining(self) -> int:
        return len(self._cassette.interactions) - self._cursor

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        cassette_id = self._cassette.cassette_id
        index = self._cursor
        if index >= len(self._cassette.interactions):
            raise ReplayMismatchError(
                f"Cassette {cassette_id!r} exhausted: call {index + 1} has no "
                f"recorded interaction (cassette holds "
                f"{len(self._cassette.interactions)})."
            )
        recorded = self._cassette.interactions[index]
        divergence = _describe_divergence(recorded.request, _request_key(request))
        if divergence:
            raise ReplayMismatchError(
                f"Cassette {cassette_id!r} interaction {index + 1} does not "
                f"match the outgoing request — {divergence}. Re-record the "
                "cassette if this request change is intentional."
            )
        try:
            response = CompletionResponse.model_validate(recorded.response)
        except ValidationError as exc:
            raise ReplayMismatchError(
                f"Cassette {cassette_id!r} interaction {index + 1} holds a "
                f"response that is not a valid CompletionResponse: {exc}"
            ) from exc
        self._cursor += 1
        return response

    def verify_complete(self) -> None:
        """Raise unless every recorded interaction was replayed."""
        if self.remaining:
            raise ReplayMismatchError(
                f"Cassette {self.cassette_id!r} has {self.remaining} recorded "
                f"interaction(s) that were never replayed."
            )


def save_cassette(cassette: Cassette, path: str | Path) -> Path:
    """Write *cassette* to *path* as JSON (parents created as needed)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cassette.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_cassette(path: str | Path) -> Cassette:
    """Load a cassette previously written by :func:`save_cassette`."""
    return Cassette.model_validate_json(Path(path).read_text(encoding="utf-8"))
