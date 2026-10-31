"""Tracing abstractions.

The concrete OpenTelemetry exporter, span model and request/agent
trajectory logging are planned (see ``docs/architecture/relia.md``). The
protocol below is the minimum contract the applications can code against
today; OTel-compatible exporters plug in behind it without call-site
changes.
"""

from __future__ import annotations

from typing import Any, Protocol


class TraceRecorder(Protocol):
    """Minimal span-recording surface.

    Implementations must be safe to call from concurrent request paths
    and must never raise into the traced code path: observability
    failures must not fail the operation being observed.
    """

    def start_span(self, name: str, attributes: dict[str, Any] | None = None) -> str:
        """Open a span and return its identifier."""
        ...

    def end_span(self, span_id: str, *, error: str | None = None) -> None:
        """Close a previously opened span, optionally recording an error."""
        ...

    def record_event(
        self, span_id: str, name: str, attributes: dict[str, Any] | None = None
    ) -> None:
        """Attach a point-in-time event to a span."""
        ...
