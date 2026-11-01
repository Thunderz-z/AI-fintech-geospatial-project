"""In-memory trace recorder implementing the TraceRecorder protocol.

OTel-compatible in shape (spans with attributes, events, errors, timings);
export as JSON for OTel collector forwarding is planned — the in-memory
surface is what the services consume today. Recorder methods must never
raise into traced code (protocol contract, see ``tracing.base``), so all
methods swallow-and-log internal failures.
"""

from __future__ import annotations

import datetime as dt
import threading
from dataclasses import asdict, dataclass, field
from typing import Any

__all__ = ["InMemoryTraceRecorder", "Span"]

_UTC = dt.UTC


@dataclass
class Span:
    """One recorded span with its events."""

    span_id: str
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    start: str = field(default_factory=lambda: dt.datetime.now(_UTC).isoformat())
    end: str | None = None
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def open(self) -> bool:
        return self.end is None

    def to_dict(self) -> dict:
        return asdict(self)


class InMemoryTraceRecorder:
    """Thread-safe span/event recorder; safe to share across request paths."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._spans: dict[str, Span] = {}
        self._order: list[str] = []
        self._counter = 0

    def start_span(self, name: str, attributes: dict[str, Any] | None = None) -> str:
        with self._lock:
            self._counter += 1
            span_id = f"span-{self._counter:06d}"
            self._spans[span_id] = Span(
                span_id=span_id, name=name, attributes=dict(attributes or {})
            )
            self._order.append(span_id)
            return span_id

    def end_span(self, span_id: str, *, error: str | None = None) -> None:
        with self._lock:
            span = self._spans.get(span_id)
            if span is None or not span.open:
                return  # never raise into traced code
            span.end = dt.datetime.now(_UTC).isoformat()
            if error is not None:
                span.error = str(error)

    def record_event(
        self, span_id: str, name: str, attributes: dict[str, Any] | None = None
    ) -> None:
        with self._lock:
            span = self._spans.get(span_id)
            if span is None:
                return  # never raise into traced code
            span.events.append(
                {
                    "name": name,
                    "ts": dt.datetime.now(_UTC).isoformat(),
                    "attributes": dict(attributes or {}),
                }
            )

    def spans(self) -> list[Span]:
        """Snapshot of all spans in start order."""
        with self._lock:
            return [self._spans[span_id] for span_id in self._order]

    def to_json(self) -> list[dict[str, Any]]:
        """Exportable trace payload (one dict per span, start order)."""
        return [span.to_dict() for span in self.spans()]
