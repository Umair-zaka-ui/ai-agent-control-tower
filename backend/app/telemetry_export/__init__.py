"""Phase 4.6 -- OpenTelemetry & metrics interoperability (ACT-SRS-M4 §4.6, §9,
§12, §27, §36).

**This package is the adapter boundary, and the boundary is the product.** An
enterprise that wants its execution traces in Datadog, its metrics in Grafana,
or both in Splunk points a collector endpoint at this platform and changes
nothing else. The way that stays true -- the way the customer never becomes
locked into our visualization layer -- is that the OpenTelemetry SDK and every
vendor concept live *here*, behind :class:`~app.telemetry_export.sinks.TelemetrySink`,
and nowhere else. ``app/runtime`` imports no ``opentelemetry`` module; neither
does ``app/observability``. Only this package does, and a test asserts it by
walking the AST of every other package (``test_otel_interop.py``).

**Export is fail-open telemetry, and that is not a slogan -- it is the gate**
(§9, §36). Everything on the execution path fails closed: authorization denies,
governance stops, a budget blocks. Export is the deliberate inverse. A collector
that is unreachable, slow, or returning 500s must not stop, block, or measurably
slow an agent execution, because **export is not the business transaction**. The
proof is a real execution that runs to completion with the collector down, with
bounded memory, with the exporter errors visible, and with the domain and audit
records untouched.

**Buffering is bounded. Always.** The naive "buffer and retry" design is an
unbounded queue wearing a disguise: a collector down for an hour accumulates an
hour of telemetry until the process OOMs, and an *observability* outage becomes
an *execution* outage -- the exact §9 violation this phase exists to prevent. So
:class:`~app.telemetry_export.buffer.BoundedSpanBuffer` has a hard maximum and a
declared policy when full (drop-oldest), and the buffer lock is never held
across the network export.

**Where export runs:** off the hot path, entirely. Nothing in the model->tool
loop, in the worker's execution code, or in the runtime services calls into this
package. A background dispatcher (:class:`~app.telemetry_export.dispatcher.
ExportDispatcher`) reads *already-terminal* executions, assembles their traces
through the existing 4.2 read model, converts them to OTLP, and hands them to
the sink. The runtime is not instrumented; it is observed after the fact. That
placement is what makes the fail-open guarantee structural rather than careful.
"""

from __future__ import annotations

from app.telemetry_export.config import (
    ExportConfig,
    ExportConfigError,
    resolve_export_config,
)
from app.telemetry_export.health import ExporterHealth, exporter_health
from app.telemetry_export.service import TelemetryExportService

__all__ = [
    "ExportConfig",
    "ExportConfigError",
    "resolve_export_config",
    "ExporterHealth",
    "exporter_health",
    "TelemetryExportService",
]
