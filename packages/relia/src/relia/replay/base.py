"""Record/replay cassettes for deterministic provider interactions.

A cassette captures request/response pairs so tests and evaluations can
replay them without network access. Replay mismatches are errors by
design — silent divergence hides regressions. Tape/recorder adapters are
planned; see ``docs/architecture/relia.md``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from relia.providers.base import ReliaError


class ReplayMismatchError(ReliaError):
    """A replayed interaction did not match the recorded cassette."""


class RecordedInteraction(BaseModel):
    """One recorded request/response exchange."""

    request: dict[str, Any]
    response: dict[str, Any]
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Cassette(BaseModel):
    """A replayable recording of provider interactions."""

    cassette_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    interactions: list[RecordedInteraction] = Field(default_factory=list)
