"""Phase 4.6 -- the export dispatcher (M4-4.6-FR-020, FR-023, §25, §36, AC-05,
AC-06).

**Nothing on the execution path calls this.** The dispatcher is a reader: it
polls for executions that have *already reached a terminal state*, assembles
their traces through 4.2's existing read model, converts them to neutral export
records, buffers them, and flushes the buffer to the sink. The runtime is never
instrumented and never blocked -- it is observed after the fact. That placement
is the whole fail-open argument: an execution cannot be slowed by an export it
does not participate in, and a collector outage cannot corrupt a trace that is
assembled from committed domain rows.

**Two phases, both fail-open:**

* :meth:`collect` -- read terminal executions since a watermark, assemble,
  convert, ``buffer.offer``. Advances the watermark regardless of whether the
  buffer accepted everything: telemetry is best-effort (§9), and a watermark
  that only advanced on a successful export would be a retry queue with extra
  steps -- unbounded by another name.
* :meth:`flush` -- drain a batch, hand it to the sink, once. On success, health
  records throughput. On failure, the batch is re-queued *under the buffer cap*
  and health records the error (visible, FR-022). No retry loop here -- "try
  again next cycle, drop the oldest if producers have moved on" is the bounded
  retry.

Every public method catches ``Exception`` and returns rather than raises. The
dispatcher runs on its own thread (:meth:`run_forever`) or is driven a cycle at
a time by a test or an operator (:meth:`run_once`). The scheduler that owns the
thread in a real deployment is opt-in (``TELEMETRY_EXPORT_SCHEDULER_ENABLED``),
exactly like the connector-health scheduler -- the API process does not grow a
background thread just by starting.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.runtime import AgentExecution, Environment
from app.observability.assembly import TraceAssembler
from app.telemetry_export.buffer import BoundedSpanBuffer
from app.telemetry_export.config import ExportConfig, resolve_export_config
from app.telemetry_export.health import exporter_health
from app.telemetry_export.mapping import ExportResource, trace_to_export
from app.telemetry_export.sinks import TelemetrySink, build_sink

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ExportDispatcher:
    """Owns the buffer, the watermark and the flush loop for one process."""

    def __init__(self, *, session_factory=SessionLocal, sink: TelemetrySink | None = None,
                 config: ExportConfig | None = None, lookback_seconds: float | None = None) -> None:
        self._session_factory = session_factory
        self._config = config or resolve_export_config(None)
        self._sink = sink if sink is not None else build_sink(self._config)
        self._buffer = BoundedSpanBuffer(
            capacity=self._config.buffer_max_spans,
            full_policy=self._config.full_policy,
        )
        # The watermark starts in the recent past, not at epoch: a fresh process
        # exports the last few minutes of terminal executions and no more. The
        # buffer would otherwise absorb the entire backlog on first cycle.
        lb = lookback_seconds if lookback_seconds is not None \
            else settings.TELEMETRY_EXPORT_SCHEDULER_LOOKBACK_SECONDS
        self._watermark = _now() - timedelta(seconds=max(0.0, lb))
        self._stop = threading.Event()

    # ------------------------------------------------------------------ #
    @property
    def buffer(self) -> BoundedSpanBuffer:
        return self._buffer

    @property
    def sink(self) -> TelemetrySink:
        return self._sink

    @property
    def watermark(self) -> datetime:
        return self._watermark

    # ------------------------------------------------------------------ #
    # Phase 1: collect
    # ------------------------------------------------------------------ #
    def collect(self, *, limit: int = 500) -> int:
        """Assemble and buffer terminal executions since the watermark.

        Returns the number of spans enqueued. Never raises."""
        try:
            return self._collect(limit=limit)
        except Exception:  # noqa: BLE001 -- §9: collection must not raise into a caller
            logger.warning("telemetry-export: collect cycle failed", exc_info=True)
            return 0

    def _collect(self, *, limit: int) -> int:
        db = self._session_factory()
        enqueued = 0
        dropped = 0
        try:
            rows = list(db.execute(
                select(AgentExecution)
                .where(AgentExecution.completed_at.is_not(None))
                .where(AgentExecution.completed_at > self._watermark)
                .order_by(AgentExecution.completed_at)
                .limit(limit)
            ).scalars())
            if not rows:
                return 0
            assembler = TraceAssembler(db)
            for execution in rows:
                trace = assembler.assemble(execution)
                resource = ExportResource.for_platform(
                    environment=trace.attributes.get("environment"),
                )
                spans = trace_to_export(trace)
                if spans:
                    dropped += self._buffer.offer(_WithResource(resource, spans))
                    enqueued += len(spans)
                if execution.completed_at and execution.completed_at > self._watermark:
                    self._watermark = execution.completed_at
        finally:
            db.close()
        if dropped:
            exporter_health.record_drop(dropped)
        return enqueued

    # ------------------------------------------------------------------ #
    # Phase 2: flush
    # ------------------------------------------------------------------ #
    def flush(self, *, max_batches: int = 4) -> int:
        """Export up to ``max_batches`` batches from the buffer. Never raises.

        Returns spans successfully exported this call."""
        exporter_health.record_cycle()
        exported = 0
        for _ in range(max_batches):
            batch = self._buffer.drain(self._config.batch_size)
            if not batch:
                break
            if not self._export_batch(batch):
                break  # collector is unhappy; stop hammering it this cycle
            exported += sum(len(item.spans) for item in batch)
        return exported

    def _export_batch(self, batch: list) -> bool:
        """One sink attempt for one drained batch. Returns success. Never raises.

        A batch can span several traces/resources; group by resource so each
        OTLP request carries one Resource (what a collector expects)."""
        try:
            groups: dict = {}
            for item in batch:
                key = tuple(sorted(item.resource.attributes.items()))
                groups.setdefault(key, (item.resource, []))[1].extend(item.spans)
            total = 0
            for resource, spans in groups.values():
                self._sink.export_spans(spans, resource)
                total += len(spans)
            exporter_health.record_success(spans=total, batches=len(groups))
            return True
        except Exception as exc:  # noqa: BLE001 -- §9/§36: export failure is contained here
            dropped = self._buffer.requeue(batch)
            exporter_health.record_failure(str(exc))
            if dropped:
                exporter_health.record_drop(dropped)
            logger.warning("telemetry-export: batch export failed: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Driving the dispatcher
    # ------------------------------------------------------------------ #
    def run_once(self, *, collect_limit: int = 500) -> dict:
        """One full cycle: collect, then flush. The unit a test drives."""
        self.refresh_config()
        enqueued = self.collect(limit=collect_limit)
        exported = self.flush()
        return {"enqueued": enqueued, "exported": exported,
                "buffer": self._buffer.stats().as_dict()}

    def refresh_config(self) -> None:
        """Re-resolve config so an operator's change takes effect next cycle
        without a restart. A protocol/endpoint change rebuilds the sink; buffer
        sizing is fixed for the life of the process (documented)."""
        try:
            fresh = self._resolve_effective_config()
        except Exception:  # noqa: BLE001
            return
        if (fresh.protocol, fresh.endpoint, tuple(sorted(fresh.headers.items())),
                fresh.active) != (self._config.protocol, self._config.endpoint,
                                  tuple(sorted(self._config.headers.items())), self._config.active):
            old, self._sink = self._sink, build_sink(fresh)
            try:
                old.shutdown()
            except Exception:  # noqa: BLE001
                pass
        self._config = fresh

    def _resolve_effective_config(self) -> ExportConfig:
        """The platform config, overlaid with the PRODUCTION-class environment's
        ``telemetry_export`` block if one exists.

        One dispatcher, one destination: a process exports to one collector, not
        one per environment. The production environment's policy is the one that
        wins because that is the traffic an enterprise most wants in its own
        tooling; a deployment that needs true per-environment fan-out runs a
        dispatcher per environment (documented, out of scope to build)."""
        db = self._session_factory()
        try:
            env = db.execute(
                select(Environment)
                .where(Environment.is_production.is_(True))
                .order_by(Environment.created_at)
                .limit(1)
            ).scalar_one_or_none()
            policy = env.policy if env is not None else None
        finally:
            db.close()
        return resolve_export_config(policy)

    def run_forever(self, *, interval_seconds: float | None = None) -> None:  # pragma: no cover - thread loop
        interval = interval_seconds or settings.TELEMETRY_EXPORT_SCHEDULER_INTERVAL_SECONDS
        logger.info("telemetry-export dispatcher started (interval=%.1fs)", interval)
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 -- one bad cycle must not end the loop
                logger.warning("telemetry-export: dispatch cycle failed", exc_info=True)
            self._stop.wait(interval)

    def stop(self) -> None:
        self._stop.set()
        try:
            self._sink.shutdown()
        except Exception:  # noqa: BLE001
            pass


class _WithResource:
    """A drained-buffer item: the spans of one trace plus their OTLP Resource.

    A plain class, not a dataclass, because the resource must be hashable for
    the flush-time grouping and :class:`~app.telemetry_export.mapping.
    ExportResource` is frozen but carries a dict; this wrapper keeps the pair
    together and defers hashing to identity, which is all the grouping needs."""

    __slots__ = ("resource", "spans")

    def __init__(self, resource: ExportResource, spans: list) -> None:
        self.resource = resource
        self.spans = spans

    def __len__(self) -> int:
        return len(self.spans)
