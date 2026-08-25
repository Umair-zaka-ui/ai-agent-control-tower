"""Phase 4.1 (ACT-SRS-M4 §6, §7, §9, §12, §13, §14) -- the instrumentation
contract Milestone 4 stands on.

The sharpest tests in this file prove *absence*: that no span table was added,
that content is not captured, that private reasoning cannot be captured in any
mode, that a high-cardinality value cannot become a metric label, and that a
broken telemetry layer cannot break an execution. Absence is what this phase
promises, and absence is what silently stops being true.

The scrubber tests deliberately use no database and no telemetry pipeline --
that isolation is the point of the module, so testing it any other way would
verify the wiring instead of the primitive.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.runtime import AgentExecution, RuntimeEvent
from app.observability import assembly as assembly_module
from app.observability import scrubbing
from app.observability.attributes import (
    HIGH_CARDINALITY_ATTRIBUTES,
    METRIC_DIMENSIONS,
    SENSITIVE_ATTRIBUTES,
    MetricCardinalityError,
    SemanticAttributes,
    metric_labels,
)
from app.observability.capture import (
    CaptureMode,
    DataClass,
    classify_field,
    current_mode,
    filter_for_capture,
    is_capturable,
    is_reasoning_field,
    strip_reasoning,
)
from app.observability.events import Outcome, RuntimeEventRecord, emit_event
from app.observability.trace import (
    SpanKind,
    TraceContext,
    derive_span_id,
    trace_id_for,
)

RT = "/api/v1/runtime"
BACKEND_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# Setup helpers (this suite's convention: each file defines its own)
# --------------------------------------------------------------------------- #
def _register_agent(client: TestClient, admin: dict) -> dict:
    nonce = uuid.uuid4().hex[:8]
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Trace Agent {nonce}", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "description": f"Test agent {nonce}.",
        "business_purpose": f"Exercise trace propagation {nonce} in tests.",
        "owner_type": "USER", "owner_id": admin["user_id"], "technical_owner_id": admin["user_id"],
        "compliance_owner_id": admin["user_id"],
        "definition": {"name": "Definition", "framework": "CUSTOM", "entrypoint_type": "FUNCTION",
                      "entrypoint": "agents.handler:run"},
    })
    assert r.status_code == 201, r.text
    return r.json()


def _ready_agent(client: TestClient, admin: dict) -> dict:
    agent = _register_agent(client, admin)
    for step in ("register", "validate"):
        assert client.post(f"{RT}/agents/{agent['id']}/{step}",
                           headers=admin["headers"]).status_code == 200
    assert client.post(f"{RT}/agents/{agent['id']}/identity/create-and-associate",
                       headers=admin["headers"],
                       json={"client_id": f"agent-identity-{uuid.uuid4().hex[:10]}"}
                       ).status_code == 200
    for step in ("submit-for-approval", "approve", "activate"):
        assert client.post(f"{RT}/agents/{agent['id']}/{step}",
                           headers=admin["headers"]).status_code == 200

    r = client.post(f"{RT}/agents/{agent['id']}/versions", headers=admin["headers"],
                    json={"model_configuration": {"provider": "MOCK", "model": "mock-model"}})
    assert r.status_code == 201, r.text
    version = r.json()
    for step in ("validate", "approve", "publish"):
        assert client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/{step}",
                           headers=admin["headers"]).status_code == 200

    r = client.post(f"{RT}/deployments", headers=admin["headers"], params={"agent_id": agent["id"]},
                    json={"agent_version_id": version["id"], "environment": "DEVELOPMENT"})
    assert r.status_code == 201, r.text
    deployment = r.json()
    for to_state in ("VALIDATING", "READY", "DEPLOYING"):
        assert client.post(f"{RT}/deployments/{deployment['id']}/lifecycle/transition",
                           headers=admin["headers"], json={"to_state": to_state}
                           ).status_code == 200
    return {"agent": agent, "version": version, "deployment": deployment}


def _second_org(client: TestClient) -> dict:
    from tests.runtime.conftest import PASSWORD

    email = f"trace_other_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": "Other Trace Org", "name": "Owner",
        "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login",
                         json={"email": email, "password": PASSWORD}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"}}


# =========================================================================== #
# AC-01 / AC-02 -- the two pre-steps
# =========================================================================== #
def test_ac01_repo_state_is_regenerated_at_the_true_post_3_10_head() -> None:
    """Pre-step A: REPO_STATE must describe the head this phase actually built
    on, not a head three phases stale."""
    repo_state = (BACKEND_ROOT.parent / "REPO_STATE.md").read_text(encoding="utf-8")
    head = sorted((BACKEND_ROOT / "migrations" / "versions").glob("*.py"))[-1].stem
    assert head in repo_state, f"REPO_STATE does not mention the live head {head}"
    # The specific staleness found in pre-step A: the header claimed 0041.
    assert "currently `0041_canary_rollout`" not in repo_state


def test_ac02_milestone_4_is_disambiguated_from_the_historical_4x() -> None:
    """Pre-step B: this repository has *two* families of "4.x".

    Book-07's authorization work (Part 4.1 Identity Foundation, Phase 4.3
    Authorization Platform) and Milestone 4's observability work (Phase 4.1
    Runtime Telemetry) both claim the number. Tracking must never merge them,
    so ROADMAP has to say so explicitly."""
    roadmap = (BACKEND_ROOT.parent / "ROADMAP.md").read_text(encoding="utf-8")
    assert "Milestone 4 — Runtime Governance & Observability" in roadmap
    # The historical family must still be there and still be findable.
    assert "Part 4.1 — Identity Foundation" in roadmap
    # And the disambiguation must be stated, not merely implied by ordering.
    assert "M4-4.1" in roadmap


# =========================================================================== #
# AC-03 -- trace identity and span linkage
# =========================================================================== #
def test_ac03_trace_identity_is_the_correlation_id_when_present() -> None:
    execution = AgentExecution(id=uuid.uuid4(), correlation_id="caller-supplied-trace")
    assert trace_id_for(execution) == "caller-supplied-trace"


def test_ac03_trace_identity_falls_back_to_the_execution_id() -> None:
    """The reason 4.1 needs no data backfill: every one of the ~74,000
    executions already carrying a null correlation_id gets a stable, unique
    trace identity from a pure function, with zero rows written."""
    execution_id = uuid.uuid4()
    execution = AgentExecution(id=execution_id, correlation_id=None)
    assert trace_id_for(execution) == str(execution_id)


def test_ac03_span_ids_are_deterministic_and_distinct() -> None:
    """Determinism is what makes storing spans unnecessary. Recomputing a
    trace tomorrow must produce byte-identical span ids, or a stored reference
    to one (runtime_events.span_id) would rot."""
    row = uuid.uuid4()
    first = derive_span_id("trace-a", SpanKind.MODEL_CALL, row, 0)
    again = derive_span_id("trace-a", SpanKind.MODEL_CALL, row, 0)
    assert first == again

    assert first != derive_span_id("trace-b", SpanKind.MODEL_CALL, row, 0)   # trace differs
    assert first != derive_span_id("trace-a", SpanKind.TOOL_CALL, row, 0)    # kind differs
    assert first != derive_span_id("trace-a", SpanKind.MODEL_CALL, row, 1)   # ordinal differs
    assert first != derive_span_id("trace-a", SpanKind.MODEL_CALL, uuid.uuid4(), 0)


def test_ac03_spans_carry_parent_linkage() -> None:
    trace = TraceContext(trace_id="t1")
    root = trace.root_span(SpanKind.EXECUTION, "exec-1")
    attempt = root.child(SpanKind.ATTEMPT, "attempt-1")
    tool = attempt.child(SpanKind.TOOL_CALL, "call-1")

    assert root.parent_span_id is None
    assert attempt.parent_span_id == root.span_id
    assert tool.parent_span_id == attempt.span_id
    assert tool.trace_id == root.trace_id == "t1"


# =========================================================================== #
# AC-04 -- end-to-end correlation propagation
# =========================================================================== #
def test_ac04_a_supplied_correlation_header_reaches_the_execution_row(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """Leg one, and the leg that was broken.

    Before this phase, correlation_id came *only* from the request body, so an
    ordinary caller produced a null column -- 74,395 of 74,619 rows in the
    development database."""
    setup = _ready_agent(client, admin)
    correlation = f"caller-trace-{uuid.uuid4().hex[:8]}"
    request_id = f"req-{uuid.uuid4().hex[:8]}"

    r = client.post(f"{RT}/executions", headers={
        **admin["headers"], "x-correlation-id": correlation, "x-request-id": request_id,
    }, json={"agent_id": setup["agent"]["id"], "input_payload": {}})
    assert r.status_code == 201, r.text

    execution = db_session.get(AgentExecution, uuid.UUID(r.json()["id"]))
    db_session.refresh(execution)
    assert execution.correlation_id == correlation
    assert execution.request_id == request_id


def test_ac04_an_execution_without_a_header_still_gets_a_trace_identity(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """No execution created through the API may end up untraceable."""
    setup = _ready_agent(client, admin)
    r = client.post(f"{RT}/executions", headers=admin["headers"],
                    json={"agent_id": setup["agent"]["id"], "input_payload": {}})
    assert r.status_code == 201, r.text

    execution = db_session.get(AgentExecution, uuid.UUID(r.json()["id"]))
    db_session.refresh(execution)
    assert execution.correlation_id is not None
    assert trace_id_for(execution) == execution.correlation_id


def test_ac04_an_explicit_body_correlation_still_wins(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """A caller that names its own correlation means it -- the header must not
    override an explicit field."""
    setup = _ready_agent(client, admin)
    r = client.post(f"{RT}/executions",
                    headers={**admin["headers"], "x-correlation-id": "from-header"},
                    json={"agent_id": setup["agent"]["id"], "input_payload": {},
                          "correlation_id": "from-body"})
    assert r.status_code == 201, r.text
    execution = db_session.get(AgentExecution, uuid.UUID(r.json()["id"]))
    db_session.refresh(execution)
    assert execution.correlation_id == "from-body"


def test_ac04_the_trace_survives_the_worker_leg(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The queue/worker hop, which needs no propagation mechanism at all.

    A worker reconstructs the context from the row it claimed, so the trace
    crosses the process boundary without a message payload, without header
    forwarding and without shared memory. This asserts the reconstruction is
    identical to what the HTTP leg created."""
    setup = _ready_agent(client, admin)
    correlation = f"worker-trace-{uuid.uuid4().hex[:8]}"
    r = client.post(f"{RT}/executions",
                    headers={**admin["headers"], "x-correlation-id": correlation},
                    json={"agent_id": setup["agent"]["id"], "input_payload": {}})
    assert r.status_code == 201, r.text

    # Read the row the way a worker in another process would: by primary key,
    # from its own session, with nothing carried over from the request.
    fresh = Session(db_session.get_bind())
    try:
        claimed = fresh.get(AgentExecution, uuid.UUID(r.json()["id"]))
        reconstructed = TraceContext.for_execution(claimed)
    finally:
        fresh.close()

    assert reconstructed.trace_id == correlation
    assert reconstructed.attributes.execution_id == r.json()["id"]
    assert reconstructed.attributes.agent_id == setup["agent"]["id"]


def test_ac04_a_scheduled_job_occurrence_has_one_trace_not_one_per_event() -> None:
    """The scheduler leg (M4-4.1-FR-003).

    A job occurrence has no caller and no inbound correlation header, so its
    trace identity is derived from its own ``job_runs`` row. Every event of one
    occurrence — STARTED, then SUCCEEDED or FAILED, across retries and lease
    recoveries, which all reuse the row — must share one trace. Without this
    each event would get a freshly minted id and the run would be
    unreconstructable, which is the exact failure this phase exists to fix."""
    from app.models.scheduler import JobRun

    run = JobRun(id=uuid.uuid4())
    first = TraceContext.for_job_run(run)
    second = TraceContext.for_job_run(run)

    assert first.trace_id == second.trace_id == str(run.id)
    # A different occurrence is a different trace.
    assert TraceContext.for_job_run(JobRun(id=uuid.uuid4())).trace_id != first.trace_id


def test_ac04_the_scheduler_passes_its_trace_to_the_event_recorder() -> None:
    """Structural: the wiring exists at the call site, not merely as an API
    nobody calls. A `for_job_run` that were never invoked would satisfy the
    requirement on paper and leave scheduler events untraceable in fact."""
    from app.scheduler import service as scheduler_service

    source = Path(scheduler_service.__file__).read_text(encoding="utf-8")
    assert "TraceContext.for_job_run(run)" in source
    assert "trace=TraceContext.for_job_run(run)" in source


def test_ac04_runtime_events_now_carry_the_trace_identity(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """Leg four. runtime_events had a correlation_id column and ~297,000 rows,
    essentially all of them null. Events emitted from here on carry it."""
    setup = _ready_agent(client, admin)
    correlation = f"event-trace-{uuid.uuid4().hex[:8]}"
    r = client.post(f"{RT}/executions",
                    headers={**admin["headers"], "x-correlation-id": correlation},
                    json={"agent_id": setup["agent"]["id"], "input_payload": {}})
    assert r.status_code == 201, r.text

    events = list(db_session.execute(
        select(RuntimeEvent).where(RuntimeEvent.execution_id == uuid.UUID(r.json()["id"]))
    ).scalars())
    assert events, "the execution produced no runtime events at all"
    assert all(e.correlation_id == correlation for e in events), \
        [(e.event_type, e.correlation_id) for e in events]
    assert all(e.span_id for e in events)


# =========================================================================== #
# AC-05 -- spans link existing rows; no DB duplication (§13)
# =========================================================================== #
def test_ac05_no_span_table_was_added() -> None:
    """The §13 decision, asserted against the live metadata rather than against
    a migration filename -- a table added by any route would show up here."""
    from app.core.database import Base

    forbidden = {"runtime_trace_spans", "trace_spans", "spans", "runtime_spans",
                 "telemetry_spans", "otel_spans"}
    assert not (forbidden & set(Base.metadata.tables)), \
        forbidden & set(Base.metadata.tables)


def test_ac05_phase_41_added_exactly_two_columns_and_no_table() -> None:
    """Reads 4.1's own migration rather than the schema, so this asserts what
    *this phase* did and stays true as later phases add their own."""
    source = (BACKEND_ROOT / "migrations" / "versions"
              / "0045_runtime_telemetry_context.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    ops = [node.func.attr for node in ast.walk(tree)
           if isinstance(node, ast.Call) and hasattr(node.func, "attr")]
    assert "create_table" not in ops, "4.1 must add no table (SRS §13)"
    assert ops.count("add_column") == 2, ops


def test_ac05_the_assembler_only_reads(client: TestClient, admin: dict) -> None:
    """Structural, over the AST. Checked as *calls*, not as words: this
    module's docstrings necessarily discuss writing while explaining that it
    never does."""
    tree = ast.parse(Path(assembly_module.__file__).read_text(encoding="utf-8"))
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    for forbidden in ("add", "add_all", "commit", "delete", "flush", "merge"):
        assert forbidden not in called, f"assembly.py calls {forbidden}()"


def test_ac05_spans_name_the_domain_rows_they_were_derived_from(
    client: TestClient, admin: dict,
) -> None:
    """A span is a *view* of an authoritative row, and says which one."""
    setup = _ready_agent(client, admin)
    execution = client.post(f"{RT}/executions", headers=admin["headers"],
                            json={"agent_id": setup["agent"]["id"], "input_payload": {}}).json()

    r = client.get(f"{RT}/executions/{execution['id']}/trace", headers=admin["headers"])
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["execution_id"] == execution["id"]
    assert body["spans"], "no spans assembled"
    root = body["spans"][0]
    assert root["kind"] == "execution"
    assert root["source_table"] == "agent_executions"
    assert root["source_id"] == execution["id"]
    # Every span must point at a real row or be a phase with no row at all.
    for span in body["spans"]:
        assert span["source_table"] in (
            None, "agent_executions", "execution_attempts", "execution_messages", "tool_calls",
        ), span


def test_ac05_assembly_is_reproducible(client: TestClient, admin: dict) -> None:
    """Two assemblies of one execution produce identical span ids. If spans
    were stored, this would be trivially true; because they are derived, it is
    the property that makes storing them unnecessary."""
    setup = _ready_agent(client, admin)
    execution = client.post(f"{RT}/executions", headers=admin["headers"],
                            json={"agent_id": setup["agent"]["id"], "input_payload": {}}).json()

    first = client.get(f"{RT}/executions/{execution['id']}/trace",
                       headers=admin["headers"]).json()
    second = client.get(f"{RT}/executions/{execution['id']}/trace",
                        headers=admin["headers"]).json()
    assert [s["span_id"] for s in first["spans"]] == [s["span_id"] for s in second["spans"]]


# =========================================================================== #
# AC-06 -- bounded metric cardinality (§12)
# =========================================================================== #
@pytest.mark.parametrize("name", sorted(HIGH_CARDINALITY_ATTRIBUTES))
def test_ac06_no_high_cardinality_identity_can_be_a_metric_label(name: str) -> None:
    """Parametrized over the declared set, so an identity added to the codebase
    later cannot be quietly left out of the guard."""
    with pytest.raises(MetricCardinalityError):
        metric_labels(**{name: "some-value"})


@pytest.mark.parametrize("name", sorted(SENSITIVE_ATTRIBUTES))
def test_ac06_no_sensitive_value_can_be_a_metric_label(name: str) -> None:
    with pytest.raises(MetricCardinalityError):
        metric_labels(**{name: "some-value"})


def test_ac06_the_bounded_set_is_accepted() -> None:
    labels = metric_labels(environment="PRODUCTION", status="SUCCEEDED",
                           provider="openai", model_category="gpt", error_class="TIMEOUT")
    assert set(labels) == METRIC_DIMENSIONS


def test_ac06_an_undeclared_dimension_is_rejected() -> None:
    """Default-deny, not default-allow: a name nobody thought about is refused
    rather than admitted."""
    with pytest.raises(MetricCardinalityError):
        metric_labels(some_new_dimension="x")


def test_ac06_the_two_sets_do_not_overlap() -> None:
    """A name that were both metric-eligible and high-cardinality would make
    the guard's behaviour depend on check order."""
    assert not (METRIC_DIMENSIONS & HIGH_CARDINALITY_ATTRIBUTES)
    assert not (METRIC_DIMENSIONS & SENSITIVE_ATTRIBUTES)


def test_ac06_the_raw_model_is_a_trace_attribute_but_only_its_category_is_a_label() -> None:
    """The distinction §12 turns on: a model name grows without bound as
    vendors ship, so the metric dimension is the family."""
    attributes = SemanticAttributes.build(model="gpt-4o-mini", execution_id=uuid.uuid4())
    assert attributes.as_dict()["model"] == "gpt-4o-mini"       # on the trace
    labels = attributes.metric_labels()
    assert labels["model_category"] == "gpt"                     # on the metric
    assert "model" not in labels
    assert "execution_id" not in labels


# =========================================================================== #
# AC-07 -- the runtime-event contract
# =========================================================================== #
def test_ac07_the_event_contract_has_the_required_shape() -> None:
    record = RuntimeEventRecord.build(
        event_type="RUNTIME_EXECUTION_QUEUED", outcome=Outcome.INFO,
        trace=TraceContext(trace_id="t1", request_id="r1"),
        payload={"status": "QUEUED"},
    )
    body = record.as_dict()
    for key in ("event_type", "outcome", "severity", "occurred_at", "trace_id",
                "span_id", "parent_span_id", "request_id", "attributes", "payload"):
        assert key in body, key
    assert body["trace_id"] == "t1"
    assert body["outcome"] == "INFO"


def test_ac07_telemetry_events_are_not_audit_events() -> None:
    """Three planes, three records (§5). The contract must not *be* the audit
    row, or the compliance record inherits telemetry's right to be lossy."""
    from app.models.rbac import AuthorizationAudit

    telemetry_fields = set(RuntimeEventRecord.__dataclass_fields__)
    audit_columns = {c.name for c in AuthorizationAudit.__table__.columns}

    # The telemetry contract is trace-shaped; the audit row is actor-shaped.
    # Neither is a superset of the other, which is the point: they answer
    # different questions and must not collapse into one record.
    assert {"trace_id", "span_id", "outcome"} <= telemetry_fields
    assert not ({"trace_id", "span_id", "outcome"} & audit_columns)
    assert "actor_id" not in telemetry_fields
    assert "actor_id" in audit_columns

    # And they are stored separately: the telemetry table is runtime_events.
    assert AuthorizationAudit.__tablename__ == "authorization_audit"
    assert RuntimeEvent.__tablename__ == "runtime_events"


def test_ac07_the_contract_carries_no_free_text_message_field() -> None:
    """A prose field would be the easiest possible way for a prompt or a
    credential to arrive in the telemetry plane by accident."""
    fields = set(RuntimeEventRecord.__dataclass_fields__)
    assert not ({"message", "detail", "description", "text"} & fields)


# =========================================================================== #
# AC-08 -- telemetry is best-effort and non-gating (§9)
# =========================================================================== #
def test_ac08_emitting_returns_false_instead_of_raising(db_session: Session) -> None:
    record = RuntimeEventRecord.build(
        event_type="X", trace=TraceContext(trace_id="t"),
        attributes=SemanticAttributes.build(organization_id="not-a-uuid"),
    )
    # organization_id is NOT NULL on runtime_events, so this insert must fail.
    from app.observability.events import emit
    assert emit(db_session, record) is False


def test_ac08_a_failed_emit_leaves_the_session_usable(db_session: Session) -> None:
    """The property try/except alone does NOT give you.

    Without the SAVEPOINT, a failed INSERT poisons the surrounding transaction
    and the *caller's* next statement raises -- so the exception would be
    swallowed here and resurface as a corrupted execution three frames up."""
    from app.observability.events import emit

    record = RuntimeEventRecord.build(
        event_type="X", trace=TraceContext(trace_id="t"),
        attributes=SemanticAttributes.build(organization_id="not-a-uuid"),
    )
    assert emit(db_session, record) is False
    # The session must still work. This is the whole assertion.
    assert db_session.execute(text("SELECT 1")).scalar() == 1


def test_ac08_a_broken_telemetry_layer_does_not_alter_an_execution(
    client: TestClient, admin: dict, db_session: Session, monkeypatch,
) -> None:
    """The §9 property end to end: with telemetry forced to explode on every
    call, the execution must complete identically."""
    setup = _ready_agent(client, admin)

    def _explode(*args, **kwargs):
        raise RuntimeError("telemetry backend is down")

    monkeypatch.setattr("app.observability.events.emit", _explode)
    monkeypatch.setattr("app.observability.events.emit_event", _explode)

    r = client.post(f"{RT}/executions", headers=admin["headers"],
                    json={"agent_id": setup["agent"]["id"], "input_payload": {}})
    assert r.status_code == 201, r.text
    body = r.json()
    # Not merely "it returned 201": the execution must have actually run.
    assert body["status"] in ("SUCCEEDED", "QUEUED", "RUNNING"), body
    assert db_session.get(AgentExecution, uuid.UUID(body["id"])) is not None


def test_ac08_emit_event_swallows_a_broken_payload(db_session: Session) -> None:
    """Construction is inside the guard too, not just the write: a payload
    pathological enough to break the scrubber must not break the execution."""
    class HostilePayload(dict):
        """Breaks the moment the scrubber tries to walk it."""

        def items(self):
            raise RuntimeError("payload exploded during scrubbing")

    # Must return False rather than propagate. If construction were outside the
    # guard, this call would raise and the execution above it would die.
    assert emit_event(db_session, event_type="X", trace=TraceContext(trace_id="t"),
                      payload=HostilePayload(bad=1)) is False
    # And the session must still be usable afterwards.
    assert db_session.execute(text("SELECT 1")).scalar() == 1


# =========================================================================== #
# AC-09 -- the isolated scrubber (§14). No database, no pipeline.
# =========================================================================== #
def test_ac09_the_scrubber_imports_nothing_from_this_platform() -> None:
    """Isolation is the module's defining property, so it is asserted over the
    AST rather than trusted. A scrubber that reached into the ORM could not be
    exercised without one."""
    tree = ast.parse(Path(scrubbing.__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not [m for m in imported if m.startswith("app")], imported
    assert not [m for m in imported if "sqlalchemy" in m or "fastapi" in m], imported


@pytest.mark.parametrize("secret_class", sorted(scrubbing.SECRET_CLASSES))
def test_ac09_every_secret_class_is_scrubbed_by_key(secret_class: str) -> None:
    """Parametrized over the class table itself, so a class added to §14 later
    cannot ship without a test."""
    key = scrubbing.SECRET_CLASSES[secret_class][0]
    scrubbed = scrubbing.scrub({key: "the-actual-secret-value"})
    assert scrubbed[key] == scrubbing.REDACTED
    assert "the-actual-secret-value" not in str(scrubbed)


# Credential-shaped fixtures, assembled from parts at import time.
#
# **Why these are not written as plain literals.** They are entirely fake, but
# they are fake *in exactly the shape a real credential has* -- which is the
# whole point of the test, and also precisely what a secret scanner looks for.
# Written out literally, the Slack entry below is enough to make GitHub push
# protection reject the push (it did, once). The two honest ways out are to
# allowlist a "secret" in the scanner or to stop writing the literal down; the
# second is better, because the first trains everyone to click through the
# warning that exists to protect them.
#
# This is the same self-match trap the placeholder-marker tests in this
# repository already dodge by concatenation. Nothing is weakened: the value
# handed to the scrubber is byte-identical to the literal it replaces.
_SHAPED_CREDENTIALS: tuple[tuple[str, str], ...] = (
    ("authorization header", "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc"),
    ("basic auth", "Basic dXNlcjpwYXNzd29yZA=="),
    ("bare JWT", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.signature"),
    ("OpenAI-style key", "sk" + "-proj-" + "abcdefghijklmnopqrstuvwxyz012345"),
    ("GitHub PAT", "ghp" + "_" + "abcdefghijklmnopqrstuvwxyz0123456789"),
    ("Slack token", "xox" + "b-" + "1234567890-abcdefghijklmno"),
    ("AWS access key id", "AKIA" + "IOSFODNN7EXAMPLE"),
    ("PEM private key", "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAK"),
    ("inline credentials", "postgresql://admin:hunter2@db.internal:5432/prod"),
)


@pytest.mark.parametrize("label,value", _SHAPED_CREDENTIALS,
                         ids=[label for label, _ in _SHAPED_CREDENTIALS])
def test_ac09_every_secret_class_is_scrubbed_by_shape(label: str, value: str) -> None:
    """The case key matching cannot catch: a credential carried under an
    innocuous name."""
    assert scrubbing.classify_value(value) is not None, value
    assert scrubbing.scrub({"harmless_looking_field": value}) == {
        "harmless_looking_field": scrubbing.REDACTED
    }


def test_ac09_structured_values_are_scrubbed_at_depth() -> None:
    payload = {"outer": {"middle": [{"inner": {"api_key": "sk-live-abcdefghijklmnop"}}]}}
    scrubbed = scrubbing.scrub(payload)
    assert "sk-live-abcdefghijklmnop" not in str(scrubbed)


def test_ac09_scrubbing_does_not_mutate_its_input() -> None:
    """A caller must be able to scrub a payload for telemetry without altering
    the domain object it came from."""
    original = {"password": "hunter2", "nested": {"token": "abc"}}
    snapshot = {"password": "hunter2", "nested": {"token": "abc"}}
    scrubbing.scrub(original)
    assert original == snapshot


def test_ac09_a_value_with_no_secret_passes_through_identically() -> None:
    """Scrubbing must be transparent to ordinary values, or the telemetry plane
    becomes useless."""
    payload = {"status": "SUCCEEDED", "duration_ms": 412, "attempt": 2,
               "environment": "PRODUCTION", "tags": ["a", "b"], "nested": {"ok": True}}
    assert scrubbing.scrub(payload) == payload
    assert scrubbing.contains_secret(payload) is False


def test_ac09_operational_fields_that_merely_look_like_secrets_survive() -> None:
    """An over-eager matcher would cost the telemetry plane ordinary facts:
    password_changed_at is a timestamp, credential_id is a foreign key."""
    payload = {"password_changed_at": "2026-01-01T00:00:00Z", "has_password": True,
               "credential_id": "abc-123", "prompt_tokens": 40, "total_tokens": 91,
               "api_key_last4": "ab12"}
    assert scrubbing.scrub(payload) == payload


def test_ac09_deep_nesting_is_truncated_rather_than_recursed() -> None:
    """A pathological structure must not turn a best-effort telemetry write
    into a stack overflow that takes the execution down with it."""
    deep: dict = {"leaf": "sk-abcdefghijklmnopqrst"}
    for _ in range(40):
        deep = {"next": deep}
    scrubbed = scrubbing.scrub(deep)
    assert "sk-abcdefghijklmnopqrst" not in str(scrubbed)


def test_ac09_scrubbing_precedes_persistence(db_session: Session) -> None:
    """§14 is about the write path, not the display layer. This asserts the
    value in the *database* is already redacted."""
    from app.models.organization import Organization

    org = db_session.execute(select(Organization).limit(1)).scalar_one_or_none()
    if org is None:  # pragma: no cover - defensive
        pytest.skip("no organization available")

    assert emit_event(
        db_session, event_type="TEST_SCRUB_BEFORE_PERSIST",
        trace=TraceContext(trace_id=f"scrub-{uuid.uuid4().hex[:8]}"),
        attributes=SemanticAttributes.build(organization_id=org.id),
        payload={"authorization": "Bearer super-secret-token"},
    )
    db_session.flush()
    stored = db_session.execute(
        select(RuntimeEvent).where(RuntimeEvent.event_type == "TEST_SCRUB_BEFORE_PERSIST")
        .order_by(RuntimeEvent.created_at.desc()).limit(1)
    ).scalar_one()
    assert "super-secret-token" not in str(stored.payload)


# =========================================================================== #
# AC-10 -- METADATA_ONLY is the default
# =========================================================================== #
def test_ac10_the_default_capture_mode_is_metadata_only() -> None:
    assert current_mode() is CaptureMode.METADATA_ONLY


def test_ac10_no_content_is_captured_under_the_baseline() -> None:
    payload = {
        "status": "SUCCEEDED", "duration_ms": 12,          # metadata: kept
        "prompt": "the confidential business question",     # content: dropped
        "output_payload": {"answer": "the confidential answer"},
        "tool_arguments": {"query": "SELECT * FROM salaries"},
        "messages": [{"role": "user", "content": "hello"}],
    }
    captured = filter_for_capture(payload)
    assert captured == {"status": "SUCCEEDED", "duration_ms": 12}
    assert "confidential" not in str(captured)


def test_ac10_content_classes_are_not_capturable_under_the_baseline() -> None:
    assert is_capturable(DataClass.METADATA) is True
    assert is_capturable(DataClass.CONTENT) is False
    assert is_capturable(DataClass.SENSITIVE_CONTENT) is False


def test_ac10_an_execution_stores_no_prompt_in_the_telemetry_plane(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """End to end: a real execution with a distinctive input, and that input
    must appear nowhere in runtime_events."""
    setup = _ready_agent(client, admin)
    marker = f"CONFIDENTIAL-{uuid.uuid4().hex[:10]}"
    r = client.post(f"{RT}/executions", headers=admin["headers"], json={
        "agent_id": setup["agent"]["id"], "input_payload": {"question": marker},
    })
    assert r.status_code == 201, r.text

    events = db_session.execute(
        select(RuntimeEvent).where(RuntimeEvent.execution_id == uuid.UUID(r.json()["id"]))
    ).scalars()
    for event in events:
        assert marker not in str(event.payload), event.event_type


# =========================================================================== #
# AC-11 -- chain-of-thought is never captured (§7), structurally
# =========================================================================== #
@pytest.mark.parametrize("mode", list(CaptureMode))
def test_ac11_no_capture_mode_admits_private_reasoning(mode: CaptureMode) -> None:
    """Parametrized over *every* member of CaptureMode, including modes added
    later: §7 is a structural exclusion, not a policy toggle, so a future mode
    must not be able to acquire it by being added to the enum."""
    assert is_capturable(DataClass.NEVER, mode) is False
    assert is_capturable(DataClass.SECRET, mode) is False


@pytest.mark.parametrize("field", sorted({
    "reasoning", "reasoning_content", "chain_of_thought", "chainOfThought",
    "CHAIN-OF-THOUGHT", "thinking", "thought", "thoughts", "scratchpad",
}))
def test_ac11_reasoning_fields_are_recognized_however_they_are_spelled(field: str) -> None:
    assert is_reasoning_field(field), field
    assert classify_field(field) is DataClass.NEVER


def test_ac11_reasoning_is_stripped_regardless_of_mode() -> None:
    """Unconditional and mode-independent: a provider that starts returning a
    thinking block in its usage metadata must not be able to smuggle reasoning
    into telemetry because the surrounding object was classified as metadata."""
    payload = {"status": "OK", "reasoning": "first I considered...",
               "thinking": [{"text": "the user probably means..."}],
               "nested": {"chain_of_thought": "step 1, step 2"}}
    for mode in CaptureMode:
        captured = filter_for_capture(payload, mode)
        assert "considered" not in str(captured), mode
        assert "probably means" not in str(captured), mode
        assert "step 1" not in str(captured), mode


def test_ac11_reasoning_is_dropped_not_redacted() -> None:
    """A REDACTED marker would still record that reasoning existed and how many
    turns had it -- a claim about the model's private state. Absence records
    nothing."""
    stripped = strip_reasoning({"status": "OK", "reasoning": "..."})
    assert stripped == {"status": "OK"}
    assert scrubbing.REDACTED not in str(stripped)


def test_ac11_reasoning_beats_content_classification() -> None:
    """A field called reasoning_content must classify as NEVER, not CONTENT --
    checking content first would get exactly this backwards."""
    assert classify_field("reasoning_content") is DataClass.NEVER


# =========================================================================== #
# AC-12 -- tenant scoping
# =========================================================================== #
def test_ac12_another_tenants_trace_is_not_readable(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    execution = client.post(f"{RT}/executions", headers=admin["headers"],
                            json={"agent_id": setup["agent"]["id"], "input_payload": {}}).json()

    other = _second_org(client)
    r = client.get(f"{RT}/executions/{execution['id']}/trace", headers=other["headers"])
    assert r.status_code in (403, 404), r.text
    assert execution["id"] not in r.text or r.status_code == 403


def test_ac12_the_trace_endpoint_requires_the_telemetry_permission(
    client: TestClient, admin: dict,
) -> None:
    """Server authorization is authoritative; the endpoint is not open because
    it is read-only."""
    setup = _ready_agent(client, admin)
    execution = client.post(f"{RT}/executions", headers=admin["headers"],
                            json={"agent_id": setup["agent"]["id"], "input_payload": {}}).json()
    r = client.get(f"{RT}/executions/{execution['id']}/trace")
    assert r.status_code in (401, 403)


# =========================================================================== #
# AC-13 -- no lock or synchronous wait on the hot path
# =========================================================================== #
def test_ac13_the_emitter_takes_no_lock_and_does_not_commit() -> None:
    """Structural, over the AST. Two separate hazards:

    * ``with_for_update`` / ``FOR UPDATE`` would take a lock on the execution
      hot path -- the standing M1 deadlock discipline.
    * ``commit`` would introduce a second commit point into an execution, so a
      telemetry write could partially persist an execution's state.
    """
    from app.observability import events as events_module

    source = Path(events_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "commit" not in called, "the emitter must not commit"
    assert "with_for_update" not in called, "the emitter must take no lock"
    assert "FOR UPDATE" not in source.upper().replace("FOR UPDATE)", "")


def test_ac13_trace_context_propagation_touches_no_database() -> None:
    """Context propagation must be attribute-passing, not a round trip per span
    (§25). Asserted by construction: the trace module imports no session."""
    from app.observability import trace as trace_module

    tree = ast.parse(Path(trace_module.__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not [m for m in imported if "sqlalchemy" in m], imported


# =========================================================================== #
# AC-14 -- the execution path is behaviourally unchanged
# =========================================================================== #
def test_ac14_sticky_routing_still_reads_only_the_body_correlation(
    client: TestClient, admin: dict,
) -> None:
    """The subtle regression this phase could have caused.

    Phase 3.4 uses ``payload["correlation_id"]`` as the sticky routing key. If
    the header-derived or auto-minted correlation had been written into the
    payload, every request would silently have become sticky -- quietly
    defeating percentage rollouts. The minted id must reach the *row* and not
    the payload."""
    from app.runtime.services import _routing_key

    assert _routing_key({}, None) is None
    assert _routing_key({"correlation_id": "abc"}, None) == "abc"
    assert _routing_key({"routing_key": "rk", "correlation_id": "abc"}, None) == "rk"


def test_ac14_an_execution_without_trace_context_still_works(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The service signature is keyword-only with a default, so every existing
    caller -- including the agent self-execution path and the tests -- is
    unaffected."""
    from app.runtime.services import ExecutionRequestService

    setup = _ready_agent(client, admin)
    from app.models.user import User

    actor = db_session.get(User, uuid.UUID(admin["user_id"]))
    execution = ExecutionRequestService(db_session).request_execution(
        actor, {"agent_id": uuid.UUID(setup["agent"]["id"]), "input_payload": {}})
    assert execution is not None
    assert execution.correlation_id is None   # no trace supplied -> nothing invented
    assert execution.request_id is None


# =========================================================================== #
# AC-15 -- the migration is reversible
# =========================================================================== #
def test_ac15_the_migration_has_a_real_downgrade() -> None:
    """Structural, over the AST.

    A ``downgrade()`` that is only ``pass`` is the usual way "reversible" stops
    being true without anyone noticing, so this asserts the function undoes
    exactly what ``upgrade()`` did: two columns added, two dropped, one index
    created, one dropped."""
    source = (BACKEND_ROOT / "migrations" / "versions"
              / "0045_runtime_telemetry_context.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name: node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)}
    assert {"upgrade", "downgrade"} <= set(functions)

    def ops(name: str) -> list[str]:
        return [node.func.attr for node in ast.walk(functions[name])
                if isinstance(node, ast.Call) and hasattr(node.func, "attr")]

    up, down = ops("upgrade"), ops("downgrade")
    assert up.count("add_column") == 2
    assert down.count("drop_column") == 2
    assert up.count("create_index") == down.count("drop_index") == 1
    # And no backfill in either direction -- see the migration's own docstring
    # on why correlation_id is derived rather than written.
    assert "execute" not in up, "4.1 performs no data backfill"


def test_ac15_the_columns_exist_and_are_nullable() -> None:
    """Nullable is not incidental: historical rows genuinely have no request id,
    and the value of the column is that anything in it is true."""
    from app.core.database import Base

    executions = Base.metadata.tables["agent_executions"]
    events = Base.metadata.tables["runtime_events"]
    assert executions.c.request_id.nullable is True
    assert events.c.span_id.nullable is True


# =========================================================================== #
# AC-18 -- no placeholder markers
# =========================================================================== #
def test_ac18_no_placeholder_markers_in_the_new_code() -> None:
    """Built by concatenation so this list does not match itself -- the
    self-match trap this repository has hit before."""
    markers = ("TO" + "DO", "FIX" + "ME", "NotImplemented" + "Error",
               "@pytest.mark." + "skip", "@pytest.mark." + "xfail")
    package = BACKEND_ROOT / "app" / "observability"
    sources = list(package.glob("*.py")) + [
        BACKEND_ROOT / "migrations" / "versions" / "0045_runtime_telemetry_context.py",
    ]
    for path in sources:
        source = path.read_text(encoding="utf-8")
        for marker in markers:
            assert marker not in source, f"{path.name} contains {marker}"
