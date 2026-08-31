"""Phase 4.6 -- exporter health (M4-4.6-FR-022, AC-08).

**Exporter errors are visible, not swallowed to nothing.** Fail-open does not
mean silent: an operator whose collector has been rejecting spans for an hour
needs to see that, even though not one agent execution was affected. This module
is the "visible" half of the fail-open contract -- the counterpart to
:mod:`app.telemetry_export.dispatcher` catching every exception.

**It is deliberately in-process and ephemeral.** The buffer is ephemeral (it is
dropped on restart -- see ``RECOVERY.md``), so a health record that outlived it
would describe a buffer that no longer exists. Export config is the durable
part and lives in ``Environment.policy``; export *runtime state* -- last error,
buffer depth, throughput -- is a property of this process and resets when the
process does. That is honest: after a restart, export is flowing again (or
failing again) and the fresh counters say which. No table, therefore no
migration, therefore no phantom.

The health surface also feeds a metric (``act_telemetry_export_*``), so a
Prometheus-based operator sees exporter degradation on the same dashboard as
everything else without calling the health endpoint.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ExporterHealth:
    """Process-local counters describing whether export is flowing.

    Every mutator is cheap and lock-guarded; the dispatcher calls them once per
    cycle and once per batch, never on the hot path (there is no hot path here
    at all)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at = _now()
        self._last_success_at: datetime | None = None
        self._last_attempt_at: datetime | None = None
        self._last_error: str | None = None
        self._last_error_at: datetime | None = None
        self._consecutive_failures = 0
        self._spans_exported = 0
        self._spans_dropped = 0
        self._batches_exported = 0
        self._batches_failed = 0
        self._cycles = 0

    def record_cycle(self) -> None:
        with self._lock:
            self._cycles += 1

    def record_success(self, *, spans: int, batches: int = 1) -> None:
        with self._lock:
            self._last_attempt_at = _now()
            self._last_success_at = self._last_attempt_at
            self._consecutive_failures = 0
            self._last_error = None
            self._spans_exported += spans
            self._batches_exported += batches

    def record_failure(self, error: str) -> None:
        with self._lock:
            self._last_attempt_at = _now()
            self._last_error = _clip(error)
            self._last_error_at = self._last_attempt_at
            self._consecutive_failures += 1
            self._batches_failed += 1

    def record_drop(self, count: int) -> None:
        if count <= 0:
            return
        with self._lock:
            self._spans_dropped += count

    @property
    def degraded(self) -> bool:
        with self._lock:
            return self._consecutive_failures > 0

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "started_at": self._started_at.isoformat(),
                "degraded": self._consecutive_failures > 0,
                "last_success_at": _iso(self._last_success_at),
                "last_attempt_at": _iso(self._last_attempt_at),
                "last_error": self._last_error,
                "last_error_at": _iso(self._last_error_at),
                "consecutive_failures": self._consecutive_failures,
                "spans_exported_total": self._spans_exported,
                "spans_dropped_total": self._spans_dropped,
                "batches_exported_total": self._batches_exported,
                "batches_failed_total": self._batches_failed,
                "dispatch_cycles_total": self._cycles,
            }

    def reset(self) -> None:
        """Test hook -- start each test with a clean process-local record."""
        self.__init__()


def _clip(text: str, limit: int = 500) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


#: The single process-wide health record. One per process, like the circuit
#: breakers in ``app.runtime.services`` -- and, like them, not shared across a
#: worker fleet (each process reports its own export health).
exporter_health = ExporterHealth()
