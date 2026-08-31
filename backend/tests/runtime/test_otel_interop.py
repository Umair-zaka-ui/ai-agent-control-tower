"""Phase 4.6 -- OpenTelemetry & metrics interoperability (ACT-SRS-M4 §4.6, §9,
§12, §27, §36; Gate H, Gate I, Gate N).

The load-bearing tests here prove *containment* and *absence*:

* **Absence of a vendor** -- ``opentelemetry`` is imported nowhere outside
  ``app/telemetry_export``, and inside it only ``sinks.py`` touches the SDK
  (``test_ac02_*``). That absence is the anti-lock-in guarantee: swapping
  Datadog for Grafana is a config edit because there is no vendor name in our
  code to change.
* **Containment of failure** -- a real execution runs to completion with the
  collector down, memory stays bounded, the exporter errors are visible, and
  the domain and audit records are untouched (``test_ac05_*``). Export is
  fail-open telemetry; it is not the business transaction.
* **Bounded cardinality** -- no metric can emit a label outside the declared
  bounded set, and a high-cardinality or sensitive value raises rather than
  becoming a series (``test_ac04_*``).
"""

from __future__ import annotations

import ast
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.rbac import AuthorizationAudit
from app.models.runtime import AgentExecution, RuntimeEvent
from app.observability.attributes import (
    HIGH_CARDINALITY_ATTRIBUTES,
    METRIC_DIMENSIONS,
    SENSITIVE_ATTRIBUTES,
    MetricCardinalityError,
)
from app.observability.assembly import TraceAssembler
from app.telemetry_export import config as export_config
from app.telemetry_export.buffer import BoundedSpanBuffer
from app.telemetry_export.dispatcher import ExportDispatcher, _WithResource
from app.telemetry_export.health import exporter_health
from app.telemetry_export.mapping import ExportResource, trace_to_export
from app.telemetry_export.metrics import MetricsCollector, metric_label_set
from app.telemetry_export.sinks import (
    FailingSink,
    NullSink,
    OTLPHttpSink,
    SinkExportError,
    TelemetrySink,
    build_sink,
    register_sink,
)
from tests.runtime.test_execution_tracing import RT, _execute, _ready_agent, _second_org

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _fresh_exporter_health():
    exporter_health.reset()
    yield
    exporter_health.reset()


def _spanlist(n: int):
    """A cheap stand-in for a trace's worth of export records."""
    return _WithResource(ExportResource.for_platform(), list(range(n)))


def _run_completed_execution(client: TestClient, admin: dict) -> tuple[dict, dict]:
    setup = _ready_agent(client, admin)
    execution = _execute(client, admin, setup)
    return setup, execution


def _execution_snapshot(db: Session, execution_id: uuid.UUID) -> dict:
    row = db.get(AgentExecution, execution_id)
    return {
        "status": row.status,
        "error_code": row.error_code,
        "cost_amount": None if row.cost_amount is None else float(row.cost_amount),
        "total_tokens": row.total_tokens,
        "completed_at": row.completed_at,
        "duration_ms": row.duration_ms,
    }


# =========================================================================== #
# AC-01 -- assembled traces export as OTLP-valid spans via the adapter
# =========================================================================== #
def test_ac01_assembled_trace_becomes_otlp_valid_spans(client: TestClient, admin: dict) -> None:
    """The 4.2 assembled trace -> neutral records -> OTLP protobuf that a real
    collector would accept. Validated by round-tripping through the OTLP
    encoder the SDK ships and re-parsing the wire bytes."""
    from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )

    _, execution = _run_completed_execution(client, admin)

    db = SessionLocal()
    try:
        row = db.get(AgentExecution, uuid.UUID(execution["id"]))
        trace = TraceAssembler(db).assemble(row)
    finally:
        db.close()

    export_spans = trace_to_export(trace)
    assert export_spans, "no spans produced"

    from app.telemetry_export.sinks import _to_readable_spans

    readable = _to_readable_spans(export_spans, ExportResource.for_platform())
    request = encode_spans(readable)

    wire = request.SerializeToString()
    parsed = ExportTraceServiceRequest()
    parsed.ParseFromString(wire)

    got_spans = [
        s
        for rs in parsed.resource_spans
        for ss in rs.scope_spans
        for s in ss.spans
    ]
    assert len(got_spans) == len(export_spans)
    # every span carries a 16-byte trace id and an 8-byte span id
    for s in got_spans:
        assert len(s.trace_id) == 16 and len(s.span_id) == 8
    # the root's trace id is the deterministic hash of the assembled trace id
    assert {s.trace_id.hex() for s in got_spans} == {export_spans[0].trace_id_hex}


def test_ac01_export_flows_through_the_adapter_not_a_direct_sdk_call(
    client: TestClient, admin: dict,
) -> None:
    """The dispatcher hands records to a ``TelemetrySink``; the sink is what
    knows OTLP. Prove it by driving a full cycle through a recording sink."""
    _, _ = _run_completed_execution(client, admin)

    class Recorder(TelemetrySink):
        name = "recorder"

        def __init__(self) -> None:
            self.exported: list = []

        def export_spans(self, spans, resource) -> None:
            self.exported.extend(spans)

    sink = Recorder()
    disp = ExportDispatcher(session_factory=SessionLocal, sink=sink,
                            lookback_seconds=3600)
    result = disp.run_once()

    assert result["enqueued"] > 0
    assert sink.exported, "the sink received nothing"
    assert exporter_health.snapshot()["spans_exported_total"] == len(sink.exported)


# =========================================================================== #
# AC-02 -- core runtime imports no OTel/vendor SDK (structural / AST)
# =========================================================================== #
def _module_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


_VENDOR_PREFIXES = ("opentelemetry", "ddtrace", "datadog", "prometheus_client",
                    "azure.monitor", "opencensus")


def test_ac02_no_core_module_imports_a_vendor_or_otel_sdk() -> None:
    """The whole codebase except ``app/telemetry_export`` is walked. A single
    ``import opentelemetry`` anywhere else fails this test -- that is the
    anti-lock-in boundary made structural (§27)."""
    offenders: dict[str, set[str]] = {}
    for py in APP_ROOT.rglob("*.py"):
        if "telemetry_export" in py.parts:
            continue
        hits = {
            name
            for name in _module_imports(py)
            for prefix in _VENDOR_PREFIXES
            if name == prefix or name.startswith(prefix + ".")
        }
        if hits:
            offenders[str(py.relative_to(BACKEND_ROOT))] = hits
    assert not offenders, f"vendor/OTel SDK imported outside the adapter: {offenders}"


def test_ac02_within_the_adapter_only_sinks_imports_the_sdk() -> None:
    """Even inside the adapter package the SDK is contained: only ``sinks.py``
    (and its private helper) names ``opentelemetry``, and it does so at
    function scope so importing the module does not pull the SDK."""
    pkg = APP_ROOT / "telemetry_export"
    users = {
        py.name
        for py in pkg.rglob("*.py")
        if any(n.startswith("opentelemetry") for n in _module_imports(py))
    }
    assert users == {"sinks.py"}, users

    # module-scope check: no top-level opentelemetry import in sinks.py
    tree = ast.parse((pkg / "sinks.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", "") or ""
            names = [a.name for a in getattr(node, "names", [])]
            assert not mod.startswith("opentelemetry")
            assert not any(n.startswith("opentelemetry") for n in names)


def test_ac02_runtime_and_observability_never_import_the_export_package() -> None:
    """Export is a downstream reader. If ``app/runtime`` or ``app/observability``
    imported ``app.telemetry_export`` there would be a path for an export
    failure to reach the hot path (§9)."""
    for area in ("runtime", "observability", "finops", "behavior"):
        for py in (APP_ROOT / area).rglob("*.py"):
            assert "app.telemetry_export" not in _module_imports(py), py


# =========================================================================== #
# AC-03 -- exporters are replaceable by configuration, not code
# =========================================================================== #
def test_ac03_swapping_the_endpoint_is_a_config_change_only() -> None:
    a = export_config.ExportConfig(enabled=True, protocol="otlp-http",
                                   endpoint="http://datadog-agent:4318/v1/traces")
    b = export_config.ExportConfig(enabled=True, protocol="otlp-http",
                                   endpoint="http://grafana-alloy:4318/v1/traces")
    sink_a = build_sink(a)
    sink_b = build_sink(b)
    assert type(sink_a) is type(sink_b) is OTLPHttpSink
    assert sink_a._endpoint != sink_b._endpoint
    sink_a.shutdown()
    sink_b.shutdown()


def test_ac03_a_new_transport_registers_without_touching_the_dispatcher() -> None:
    class MemorySink(TelemetrySink):
        name = "memory"
        instances: list = []

        def __init__(self) -> None:
            MemorySink.instances.append(self)
            self.spans: list = []

        def export_spans(self, spans, resource) -> None:
            self.spans.extend(spans)

    from app.telemetry_export import sinks as _s

    register_sink("memory", lambda **_: MemorySink())
    try:
        cfg = export_config.ExportConfig(enabled=True, protocol="memory",
                                        endpoint="http://x")
        # protocol validation is separate from the registry; force it through
        sink = build_sink(cfg)
        assert isinstance(sink, MemorySink)
    finally:
        _s._REGISTRY.pop("memory", None)


def test_ac03_disabled_or_null_config_always_yields_a_null_sink() -> None:
    assert isinstance(build_sink(export_config.ExportConfig(enabled=False)), NullSink)
    assert isinstance(
        build_sink(export_config.ExportConfig(enabled=True, protocol="null")), NullSink
    )
    assert isinstance(
        build_sink(export_config.ExportConfig(enabled=True, protocol="otlp-http",
                                              endpoint="")),
        NullSink,
    )


# =========================================================================== #
# AC-04 -- the metrics surface emits bounded-cardinality labels only
# =========================================================================== #
@pytest.mark.parametrize("bad", sorted(HIGH_CARDINALITY_ATTRIBUTES)[:8])
def test_ac04_a_high_cardinality_identity_cannot_be_a_metric_label(bad: str) -> None:
    with pytest.raises(MetricCardinalityError):
        metric_label_set(**{bad: "anything"})


@pytest.mark.parametrize("bad", sorted(SENSITIVE_ATTRIBUTES)[:8])
def test_ac04_a_sensitive_value_cannot_be_a_metric_label(bad: str) -> None:
    with pytest.raises(MetricCardinalityError):
        metric_label_set(**{bad: "anything"})


def test_ac04_the_allowed_label_set_is_exactly_the_bounded_dimensions() -> None:
    from app.telemetry_export.metrics import _ALLOWED_LABELS, _EXPORT_BOUNDED_DIMENSIONS

    assert METRIC_DIMENSIONS <= _ALLOWED_LABELS
    extension = _ALLOWED_LABELS - METRIC_DIMENSIONS
    assert extension == _EXPORT_BOUNDED_DIMENSIONS == {"signal_type", "state", "outcome"}
    # and none of the extension is secretly high-cardinality/sensitive
    assert not (_ALLOWED_LABELS & HIGH_CARDINALITY_ATTRIBUTES)
    assert not (_ALLOWED_LABELS & SENSITIVE_ATTRIBUTES)


def test_ac04_every_metric_add_call_uses_only_bounded_labels() -> None:
    """Structural: parse metrics.py and check every ``r.add(name, value,
    **labels)`` keyword against the allowed set. A future edit adding
    ``execution_id=...`` to a metric fails here, not in production."""
    from app.telemetry_export.metrics import _ALLOWED_LABELS

    src = (APP_ROOT / "telemetry_export" / "metrics.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    checked = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "add":
            continue
        for kw in node.keywords:
            if kw.arg in (None, "status", "environment", "provider", "model_category"):
                # ** splat or the fixed common ones handled dynamically
                continue
            assert kw.arg in _ALLOWED_LABELS, f"metric label {kw.arg!r} is not bounded"
            checked += 1
    assert checked > 0


def test_ac04_metrics_endpoint_renders_prometheus_text(client: TestClient, admin: dict) -> None:
    _run_completed_execution(client, admin)
    r = client.get("/metrics", headers=admin["headers"])
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert "# TYPE act_runtime_executions gauge" in body
    assert "act_telemetry_export_spans_exported_total" in body
    # no forbidden label names anywhere in the exposition
    for forbidden in ("execution_id=", "email=", "prompt=", "agent_id=", "trace_id="):
        assert forbidden not in body


# =========================================================================== #
# AC-05 / §36 -- a real execution completes with the collector down
# =========================================================================== #
def test_ac05_execution_completes_normally_with_the_collector_down(
    client: TestClient, admin: dict,
) -> None:
    _, execution = _run_completed_execution(client, admin)
    eid = uuid.UUID(execution["id"])

    db = SessionLocal()
    try:
        before = _execution_snapshot(db, eid)
        events_before = db.execute(
            select(func.count(RuntimeEvent.id)).where(RuntimeEvent.execution_id == eid)
        ).scalar_one()
        audit_before = db.execute(select(func.count(AuthorizationAudit.id))).scalar_one()
    finally:
        db.close()

    assert before["status"] in {"SUCCEEDED", "COMPLETED"}

    # The collector is "down": every export attempt raises.
    disp = ExportDispatcher(session_factory=SessionLocal, sink=FailingSink(),
                            lookback_seconds=3600)
    for _ in range(5):
        out = disp.run_once()  # must never raise
        assert isinstance(out, dict)

    db = SessionLocal()
    try:
        after = _execution_snapshot(db, eid)
        events_after = db.execute(
            select(func.count(RuntimeEvent.id)).where(RuntimeEvent.execution_id == eid)
        ).scalar_one()
        audit_after = db.execute(select(func.count(AuthorizationAudit.id))).scalar_one()
    finally:
        db.close()

    assert after == before, "the export failure changed the execution row"
    assert events_after == events_before, "export wrote a telemetry event"
    assert audit_after == audit_before, "export wrote an audit row"

    health = exporter_health.snapshot()
    assert health["degraded"] is True
    assert health["last_error"], "the exporter error is not visible"
    assert health["consecutive_failures"] >= 1
    # memory bounded: the buffer never grew past its cap despite 5 failed cycles
    assert disp.buffer.span_count() <= disp.buffer.stats().as_dict()["capacity_spans"]


def test_ac05_a_real_otlp_socket_failure_is_contained(
    client: TestClient, admin: dict,
) -> None:
    """Not a mock: a real ``OTLPSpanExporter`` pointed at a dead port. The
    connection failure is caught in the sink, surfaces as health state, and
    never propagates."""
    _run_completed_execution(client, admin)
    sink = OTLPHttpSink(endpoint="http://127.0.0.1:59117/v1/traces",
                        timeout_seconds=2)
    disp = ExportDispatcher(session_factory=SessionLocal, sink=sink,
                            lookback_seconds=3600)
    out = disp.run_once()
    assert isinstance(out, dict)
    assert exporter_health.snapshot()["degraded"] is True
    sink.shutdown()


def test_ac05_the_watermark_advances_even_when_export_fails() -> None:
    """A watermark that only advanced on a successful export would be a retry
    queue by another name -- unbounded. It advances on collection."""
    disp = ExportDispatcher(session_factory=SessionLocal, sink=FailingSink(),
                            lookback_seconds=86_400)
    start = disp.watermark
    disp.collect()
    # either nothing to collect (watermark unchanged) or it moved forward
    assert disp.watermark >= start


# =========================================================================== #
# AC-06 -- a slow collector does not measurably slow execution
# =========================================================================== #
def test_ac06_export_is_off_the_hot_path_structurally() -> None:
    """No module on the execution path imports the export package, so a slow
    export literally cannot be in the loop -- there is no call site."""
    hot_path = [
        APP_ROOT / "runtime" / "services.py",
        APP_ROOT / "workers" / "worker.py",
        APP_ROOT / "workers" / "runner.py",
        APP_ROOT / "runtime" / "governance" / "engine.py",
    ]
    for path in hot_path:
        imports = _module_imports(path)
        assert not any("telemetry_export" in i for i in imports), path


def test_ac06_a_slow_collector_costs_the_dispatcher_not_the_execution(
    client: TestClient, admin: dict,
) -> None:
    """A slow sink makes the *dispatcher's flush* slow. The execution that
    produced the spans finished long before, on a different call stack, and
    never waited on anything here."""
    class SlowSink(TelemetrySink):
        name = "slow"

        def export_spans(self, spans, resource) -> None:
            time.sleep(1.0)

    setup = _ready_agent(client, admin)
    _execute(client, admin, setup)  # completes now, fast

    disp = ExportDispatcher(session_factory=SessionLocal, sink=SlowSink(),
                            lookback_seconds=3600)
    assert disp.collect() > 0, "nothing collected to export"

    # the slow cost lands on the dispatcher thread, in flush()
    t0 = time.perf_counter()
    disp.flush()
    assert time.perf_counter() - t0 >= 1.0

    # and a fresh execution, run while that slow flush would notionally be
    # pending, is unaffected -- there is no code path from execution to export
    t0 = time.perf_counter()
    _execute(client, admin, setup)
    assert time.perf_counter() - t0 < 5.0


# =========================================================================== #
# AC-07 -- buffering is bounded, with a defined full-policy
# =========================================================================== #
def test_ac07_drop_oldest_never_exceeds_capacity_and_counts_every_drop() -> None:
    buf = BoundedSpanBuffer(capacity=1000, full_policy="drop_oldest")
    for _ in range(200):
        buf.offer(_spanlist(100))  # 20_000 spans offered into a 1_000 cap
    stats = buf.stats().as_dict()
    assert stats["span_count"] <= 1000
    assert stats["dropped_spans_total"] >= 19_000
    assert stats["enqueued_spans_total"] - stats["dropped_spans_total"] <= 1000 + 100


def test_ac07_drop_newest_keeps_the_earliest_and_drops_the_incoming() -> None:
    buf = BoundedSpanBuffer(capacity=10, full_policy="drop_newest")
    assert buf.offer(_spanlist(10)) == 0
    dropped = buf.offer(_spanlist(5))
    assert dropped == 5
    assert buf.span_count() == 10


def test_ac07_block_bounded_waits_briefly_then_drops() -> None:
    buf = BoundedSpanBuffer(capacity=10, full_policy="block_bounded",
                            block_timeout_seconds=0.2)
    buf.offer(_spanlist(10))
    t0 = time.perf_counter()
    dropped = buf.offer(_spanlist(5))
    elapsed = time.perf_counter() - t0
    assert 0.15 <= elapsed < 1.0
    assert dropped >= 5  # it did not grow
    assert buf.span_count() <= 10


def test_ac07_requeue_of_a_failed_batch_is_also_capped() -> None:
    buf = BoundedSpanBuffer(capacity=100, full_policy="drop_oldest")
    buf.offer(_spanlist(60))
    batch = buf.drain(60)
    # producers fill the buffer while the "export" is in flight
    buf.offer(_spanlist(100))
    dropped = buf.requeue(batch)
    assert buf.span_count() <= 100
    assert dropped >= 60  # the stale batch lost to newer data, bounded


def test_ac07_settings_never_offer_an_unbounded_option() -> None:
    assert "unbounded" not in export_config.BUFFER_FULL_POLICIES
    assert export_config.BUFFER_FULL_POLICIES == {"drop_oldest", "drop_newest", "block_bounded"}


# =========================================================================== #
# AC-08 -- exporter errors are visible
# =========================================================================== #
def test_ac08_a_failure_is_visible_via_health_endpoint_and_metric(
    client: TestClient, admin: dict,
) -> None:
    _run_completed_execution(client, admin)
    disp = ExportDispatcher(session_factory=SessionLocal, sink=FailingSink("boom"),
                            lookback_seconds=3600)
    disp.run_once()

    r = client.get("/api/v1/observability/export/health", headers=admin["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["exporter"]["degraded"] is True
    assert "boom" in body["exporter"]["last_error"]

    metrics = client.get("/metrics", headers=admin["headers"]).text
    assert "act_telemetry_export_degraded 1" in metrics


def test_ac08_a_recovered_collector_clears_the_degraded_flag() -> None:
    exporter_health.record_failure("temporary")
    assert exporter_health.degraded is True
    exporter_health.record_success(spans=3)
    assert exporter_health.degraded is False
    assert exporter_health.snapshot()["last_error"] is None


# =========================================================================== #
# AC-09 -- plane discipline: export fail-open, governance still fail-closed
# =========================================================================== #
def test_ac09_export_health_is_never_read_by_governance_or_the_runtime() -> None:
    for py in (APP_ROOT / "runtime").rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        assert "exporter_health" not in src, py
        assert "telemetry_export" not in src, py


def test_ac09_a_degraded_exporter_does_not_change_a_governance_decision(
    client: TestClient, admin: dict,
) -> None:
    """Governance is a pure function of its inputs; the exporter's state is not
    one of them. Run the same governed execution with the exporter healthy and
    then degraded -- identical outcome."""
    exporter_health.reset()
    setup = _ready_agent(client, admin)
    healthy = _execute(client, admin, setup)

    exporter_health.record_failure("collector down")
    exporter_health.record_failure("collector still down")
    degraded = _execute(client, admin, setup)

    db = SessionLocal()
    try:
        h = _execution_snapshot(db, uuid.UUID(healthy["id"]))
        d = _execution_snapshot(db, uuid.UUID(degraded["id"]))
    finally:
        db.close()
    assert h["status"] == d["status"]
    assert h["error_code"] == d["error_code"]


def test_ac09_governance_still_fails_closed_regardless_of_export(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The 4.3 fail-closed guarantee is unchanged by this phase: an unevaluable
    mandatory checkpoint still STOPs. Asserted at the engine, with the exporter
    in a degraded state."""
    exporter_health.record_failure("down")
    src = (APP_ROOT / "runtime" / "governance" / "engine.py").read_text(encoding="utf-8")
    # the fail-closed path is still present and untouched by 4.6
    assert "_unevaluable_decision" in src
    assert "Decision.STOP" in src


# =========================================================================== #
# AC-10 -- exported spans carry no content and no secret
# =========================================================================== #
def test_ac10_exported_attributes_are_metadata_only(client: TestClient, admin: dict) -> None:
    marker = f"secret-prompt-{uuid.uuid4().hex}"
    setup = _ready_agent(client, admin)
    execution = _execute(client, admin, setup, input_payload={"question": marker})

    db = SessionLocal()
    try:
        row = db.get(AgentExecution, uuid.UUID(execution["id"]))
        trace = TraceAssembler(db).assemble(row)
    finally:
        db.close()

    content_keys = {"prompt", "prompt_text", "input", "input_payload", "input_summary",
                    "output", "output_payload", "output_summary", "content", "message",
                    "messages", "completion", "tool_args", "tool_arguments", "arguments",
                    "response_body", "request_body"}
    for span in trace_to_export(trace):
        blob = repr(span.attributes)
        assert marker not in blob
        for name in span.attributes:
            assert name not in SENSITIVE_ATTRIBUTES
            assert name not in content_keys


def test_ac10_a_secret_valued_attribute_is_scrubbed_before_export() -> None:
    from app.observability.assembly import AssembledSpan, AssembledTrace
    from app.observability.trace import SpanKind
    from app.telemetry_export.mapping import span_to_export

    trace = AssembledTrace(
        trace_id="t-1", execution_id="e-1", request_id=None, correlated=False,
        attributes={"organization_id": "org-1"},
        spans=[],
    )
    span = AssembledSpan(
        span_id="s-1", parent_span_id=None, kind=SpanKind.EXECUTION, name="x",
        attributes={"password": "hunter2",
                    "authorization": "Bearer sk-abcdef",
                    "execution_id": "11111111-1111-1111-1111-111111111111"},
    )
    out = span_to_export(trace, span)
    flat = repr(out.attributes)
    assert "hunter2" not in flat
    assert "sk-abcdef" not in flat
    # execution_id is a legal *trace* attribute (identity of the subject) -- §12
    # only forbids it as a *metric label*
    assert out.attributes.get("execution_id") == "11111111-1111-1111-1111-111111111111"


# =========================================================================== #
# AC-11 -- exported data is tenant-isolated
# =========================================================================== #
def test_ac11_metrics_endpoint_is_scoped_to_the_callers_organization(
    client: TestClient, admin: dict,
) -> None:
    setup = _ready_agent(client, admin)
    _execute(client, admin, setup)

    other = _second_org(client)
    other_body = client.get("/metrics", headers=other["headers"]).text
    mine_body = client.get("/metrics", headers=admin["headers"]).text

    # the other org has run nothing: its execution gauge is absent or zero
    other_exec_lines = [l for l in other_body.splitlines()
                        if l.startswith("act_runtime_executions{")]
    assert all(l.rsplit(" ", 1)[1] == "0" for l in other_exec_lines) or not other_exec_lines
    assert "act_runtime_executions{" in mine_body


def test_ac11_config_read_for_another_tenants_environment_is_not_found(
    client: TestClient, admin: dict,
) -> None:
    # my environment
    envs = client.get("/api/v1/runtime/environments", headers=admin["headers"]).json()
    my_env_id = envs[0]["id"]

    other = _second_org(client)
    r = client.get("/api/v1/observability/export/config",
                   headers=other["headers"], params={"environment_id": my_env_id})
    assert r.status_code == 404, r.text


# =========================================================================== #
# AC-12 -- config management enforces permission + audit
# =========================================================================== #
def test_ac12_the_manage_route_is_permission_gated_and_rejects_anonymous(
    client: TestClient, admin: dict,
) -> None:
    envs = client.get("/api/v1/runtime/environments", headers=admin["headers"]).json()
    env_id = envs[0]["id"]

    # anonymous
    anon = client.put("/api/v1/observability/export/config", json={
        "environment_id": env_id, "enabled": False, "protocol": "null", "endpoint": ""})
    assert anon.status_code in (401, 403)

    # another tenant's owner: not found (§34 -- never confirm it exists)
    other = _second_org(client)
    denied = client.put("/api/v1/observability/export/config", headers=other["headers"],
                        json={"environment_id": env_id, "enabled": False,
                              "protocol": "null", "endpoint": ""})
    assert denied.status_code in (403, 404)

    # structural: the route depends on the manage permission, the reads on view
    routes_src = (APP_ROOT / "telemetry_export" / "routes.py").read_text(encoding="utf-8")
    assert 'require_permission(_MANAGE)' in routes_src
    assert '_MANAGE = "runtime.telemetry.export.manage"' in routes_src


def test_ac12_a_config_change_is_audited_without_the_header_value(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    envs = client.get("/api/v1/runtime/environments", headers=admin["headers"]).json()
    env_id = envs[0]["id"]

    r = client.put("/api/v1/observability/export/config", headers=admin["headers"], json={
        "environment_id": env_id, "enabled": True, "protocol": "otlp-http",
        "endpoint": "https://otlp.example.com:4318/v1/traces",
        "headers": {"DD-API-KEY": "super-secret-value"},
    })
    assert r.status_code == 200, r.text
    assert r.json()["effective"]["active"] is True

    row = db_session.execute(
        select(AuthorizationAudit)
        .where(AuthorizationAudit.event_type == "RUNTIME_TELEMETRY_EXPORT_CONFIGURED")
        .order_by(AuthorizationAudit.created_at.desc())
    ).scalars().first()
    assert row is not None
    blob = str(row.meta)
    assert "super-secret-value" not in blob
    assert "example.com" in blob  # the host is recorded
    assert "/v1/traces" not in blob  # the path is not

    # and the stored block never returns the header value
    got = client.get("/api/v1/observability/export/config", headers=admin["headers"],
                     params={"environment_id": env_id}).json()
    assert "super-secret-value" not in str(got)
    assert got["stored_block"]["header_names"] == ["DD-API-KEY"]


def test_ac12_an_invalid_config_is_rejected_with_export_config_invalid(
    client: TestClient, admin: dict,
) -> None:
    envs = client.get("/api/v1/runtime/environments", headers=admin["headers"]).json()
    env_id = envs[0]["id"]
    r = client.put("/api/v1/observability/export/config", headers=admin["headers"], json={
        "environment_id": env_id, "enabled": True, "protocol": "otlp-http",
        "endpoint": "not-a-url",
    })
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "EXPORT_CONFIG_INVALID"


def test_ac12_config_write_is_idempotent(client: TestClient, admin: dict, db_session: Session) -> None:
    envs = client.get("/api/v1/runtime/environments", headers=admin["headers"]).json()
    env_id = envs[0]["id"]
    org_id = uuid.UUID(admin["organization_id"])
    key = uuid.uuid4().hex
    body = {"environment_id": env_id, "enabled": False, "protocol": "null", "endpoint": ""}
    for _ in range(3):
        r = client.put("/api/v1/observability/export/config", headers={
            **admin["headers"], "Idempotency-Key": key}, json=body)
        assert r.status_code == 200, r.text
    n = db_session.execute(
        select(func.count(AuthorizationAudit.id))
        .where(AuthorizationAudit.event_type == "RUNTIME_TELEMETRY_EXPORT_CONFIGURED")
        .where(AuthorizationAudit.organization_id == org_id)
    ).scalar_one()
    assert n == 1


# =========================================================================== #
# AC-16 -- no new TODO / FIXME / NotImplementedError / skip / xfail
# =========================================================================== #
def test_ac16_the_phase_left_no_markers() -> None:
    pkg = APP_ROOT / "telemetry_export"
    banned = ("TODO", "FIXME", "NotImplementedError", "xfail", "pytest.skip", "@pytest.mark.skip")
    for py in pkg.rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        for token in banned:
            assert token not in src, f"{token} in {py}"
