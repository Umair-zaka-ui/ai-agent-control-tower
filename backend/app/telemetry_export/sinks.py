"""Phase 4.6 -- the telemetry sink boundary (M4-4.6-FR-001, FR-003, §27, AC-02,
AC-03).

**Everything vendor-shaped is behind this door.** :class:`TelemetrySink` is the
whole contract the rest of the platform sees: give it export records, it gets
them to a collector, and it either succeeds or raises. The OpenTelemetry SDK is
imported *inside* :class:`OTLPHttpSink` and nowhere else in the codebase --
``test_otel_interop.py`` walks the AST of every other package to prove it. That
is the anti-lock-in guarantee made structural: an enterprise swapping Datadog
for Grafana for Splunk edits a config endpoint, because there is no vendor name
anywhere in our code to edit.

**Sinks are replaceable by name.** :func:`build_sink` is a registry keyed on the
protocol string. ``null`` is a real sink (it drops, successfully); ``otlp-http``
is the real one. A test double, or a future ``otlp-grpc``, registers here
without touching the dispatcher, the buffer, or the service.

**A sink never retries and never buffers.** Retry and backpressure are the
buffer's and dispatcher's job (bounded, §4.6). A sink does exactly one thing:
one attempt to hand one batch to the collector. Keeping it that thin is what
keeps the fail-open reasoning simple -- there is no place in a sink for an
unbounded queue to hide.
"""

from __future__ import annotations

import abc
from typing import Callable

from app.telemetry_export.mapping import ExportResource, ExportSpan


class SinkExportError(RuntimeError):
    """A sink's single attempt to reach the collector failed.

    Always caught by the dispatcher and turned into exporter-health state --
    it never propagates toward an execution (§9)."""


class TelemetrySink(abc.ABC):
    """The export boundary. No vendor or OTel type appears in this signature."""

    #: Stable identifier, matches the protocol string in config.
    name: str = "abstract"

    @abc.abstractmethod
    def export_spans(self, spans: list[ExportSpan], resource: ExportResource) -> None:
        """Make one attempt to deliver ``spans``. Return on success, raise
        :class:`SinkExportError` on failure. Must not retry, must not block
        beyond its configured timeout."""

    def shutdown(self) -> None:  # pragma: no cover - trivial default
        """Release any transport resources. Safe to call more than once."""


class NullSink(TelemetrySink):
    """Configured, inert. Every export 'succeeds' by going nowhere.

    Used when export is disabled or when a test wants the whole pipeline --
    buffer, dispatcher, health -- without a collector. It counts what it
    received so a test can assert the pipeline ran."""

    name = "null"

    def __init__(self) -> None:
        self.spans_received = 0
        self.batches_received = 0

    def export_spans(self, spans: list[ExportSpan], resource: ExportResource) -> None:
        self.spans_received += len(spans)
        self.batches_received += 1


class FailingSink(TelemetrySink):
    """A sink that always fails -- the 'collector is down' stand-in for tests
    that must not open a real socket. Not registered in :data:`_REGISTRY`;
    constructed directly by a test."""

    name = "failing"

    def __init__(self, message: str = "collector unreachable") -> None:
        self.message = message
        self.attempts = 0

    def export_spans(self, spans: list[ExportSpan], resource: ExportResource) -> None:
        self.attempts += 1
        raise SinkExportError(self.message)


class OTLPHttpSink(TelemetrySink):
    """OTLP over HTTP/protobuf, via the OpenTelemetry SDK.

    **The only place ``opentelemetry`` is imported in this codebase.** The
    import is inside ``__init__`` so that merely importing this module (which
    the registry does) does not pull the SDK -- and so the structural test's
    "no OTel import at module scope outside this package" holds without a
    special case.

    Builds a batch of :class:`opentelemetry.sdk.trace.ReadableSpan` from the
    neutral records and hands them to ``OTLPSpanExporter.export`` -- the same
    call path a normally-instrumented service uses, so what a real collector
    receives is ordinary OTLP that Datadog, Grafana, Splunk et al. already
    ingest."""

    name = "otlp-http"

    def __init__(self, *, endpoint: str, headers: dict[str, str] | None = None,
                 timeout_seconds: float = 5.0) -> None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        self._endpoint = endpoint
        self._exporter = OTLPSpanExporter(
            endpoint=endpoint,
            headers=headers or None,
            timeout=int(max(1, round(timeout_seconds))),
        )

    def export_spans(self, spans: list[ExportSpan], resource: ExportResource) -> None:
        from opentelemetry.sdk.trace.export import SpanExportResult

        readable = _to_readable_spans(spans, resource)
        try:
            result = self._exporter.export(readable)
        except Exception as exc:  # noqa: BLE001 -- normalized, then re-raised as our type
            raise SinkExportError(f"OTLP export raised: {exc!r}") from exc
        if result != SpanExportResult.SUCCESS:
            raise SinkExportError(f"OTLP exporter returned {result!r} for {self._endpoint}")

    def shutdown(self) -> None:
        try:
            self._exporter.shutdown()
        except Exception:  # noqa: BLE001 - shutdown must not raise
            pass


def _to_readable_spans(spans: list[ExportSpan], resource: ExportResource):
    """Neutral records -> OTel ReadableSpans. OTel types are local to this fn."""
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.trace import SpanContext, SpanKind, TraceFlags
    from opentelemetry.trace.status import Status, StatusCode

    otel_resource = Resource.create(resource.attributes)
    kind_map = {"CLIENT": SpanKind.CLIENT, "INTERNAL": SpanKind.INTERNAL}
    status_map = {
        "OK": StatusCode.OK,
        "ERROR": StatusCode.ERROR,
        "UNSET": StatusCode.UNSET,
    }
    flags = TraceFlags(TraceFlags.SAMPLED)
    out = []
    for span in spans:
        trace_id = int(span.trace_id_hex, 16)
        span_id = int(span.span_id_hex, 16)
        ctx = SpanContext(trace_id=trace_id, span_id=span_id, is_remote=False, trace_flags=flags)
        parent = None
        if span.parent_span_id_hex:
            parent = SpanContext(
                trace_id=trace_id, span_id=int(span.parent_span_id_hex, 16),
                is_remote=False, trace_flags=flags,
            )
        out.append(ReadableSpan(
            name=span.name,
            context=ctx,
            parent=parent,
            resource=otel_resource,
            attributes=dict(span.attributes),
            kind=kind_map.get(span.kind, SpanKind.INTERNAL),
            status=Status(status_map.get(span.status_code, StatusCode.UNSET),
                          span.status_message or None),
            start_time=span.start_unix_nano,
            end_time=span.end_unix_nano,
        ))
    return out


# --------------------------------------------------------------------------- #
# Registry (FR-003 / AC-03): protocol string -> sink factory
# --------------------------------------------------------------------------- #
_REGISTRY: dict[str, Callable[..., TelemetrySink]] = {
    "null": lambda **_: NullSink(),
    "otlp-http": lambda **kw: OTLPHttpSink(**kw),
}


def register_sink(protocol: str, factory: Callable[..., TelemetrySink]) -> None:
    """Add or replace a sink factory. Used by tests and by any future
    transport; the point of the registry is that this is all it takes."""
    _REGISTRY[protocol] = factory


def build_sink(config) -> TelemetrySink:
    """Construct the sink named by ``config.protocol``.

    A config that is not ``active`` (disabled, no endpoint, or ``null``) always
    yields a :class:`NullSink`, so the dispatcher can run unconditionally and
    the "is export on?" decision lives in exactly one place."""
    if not config.active:
        return NullSink()
    factory = _REGISTRY.get(config.protocol)
    if factory is None:  # pragma: no cover - config validation forbids this
        return NullSink()
    if config.protocol == "otlp-http":
        return factory(endpoint=config.endpoint, headers=config.headers,
                       timeout_seconds=config.timeout_seconds)
    return factory()
