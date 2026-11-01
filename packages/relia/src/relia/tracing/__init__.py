"""Tracing abstractions (OpenTelemetry-compatible by design)."""

from relia.tracing.base import TraceRecorder
from relia.tracing.memory import InMemoryTraceRecorder, Span

__all__ = ["InMemoryTraceRecorder", "Span", "TraceRecorder"]
