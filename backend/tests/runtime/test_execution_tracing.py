"""Phase 4.2 (ACT-SRS-M4 §6, §13, §15, §26, §28, §34) -- the unified execution
trace: assembly, the explorer, and the ADR-0008 measurement.

Two kinds of test carry most of the weight here.

The **boundary** tests prove absence: no content is served, no span store was
added, no query full-scans, no tenant sees another. Absence is what this phase
promises and what silently stops being true.

The **measurement** test is unusual and deliberate: ADR-0008 named this phase as
the point to revisit the derived-spans decision *with real numbers*. The
benchmark is therefore a recorded test rather than a note in a commit message,
so that the claim "assembly is fast enough" keeps being checked rather than
being true once in August 2026.
"""

from __future__ import annotations

import ast
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from app.models.runtime import AgentExecution
from app.observability import explorer as explorer_module
from app.observability.assembly import TraceAssembler
from app.observability.explorer import (
    MAX_PAGE_SIZE,
    TraceExplorer,
    TraceFilters,
)
from app.observability.trace import SpanKind

RT = "/api/v1/runtime"
OBS = "/api/v1/observability"
BACKEND_ROOT = Path(__file__).resolve().parents[2]

#: The latency ceiling this phase commits to for a tenant-scoped explorer page
#: and a single trace assembly. Chosen an order of magnitude above what was
#: measured (sub-millisecond) so the test detects a *structural* regression --
#: an index dropped, a filter compiled into a scan, an N+1 introduced -- rather
#: than failing on a noisy laptop.
LATENCY_BUDGET_MS = 250.0


# --------------------------------------------------------------------------- #
# Setup helpers (this suite's convention: each file defines its own)
# --------------------------------------------------------------------------- #
def _ready_agent(client: TestClient, admin: dict) -> dict:
    nonce = uuid.uuid4().hex[:8]
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Trace Agent {nonce}", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "description": f"Test agent {nonce}.",
        "business_purpose": f"Exercise the trace explorer {nonce} in tests.",
        "owner_type": "USER", "owner_id": admin["user_id"], "technical_owner_id": admin["user_id"],
        "compliance_owner_id": admin["user_id"],
        "definition": {"name": "Definition", "framework": "CUSTOM", "entrypoint_type": "FUNCTION",
                      "entrypoint": "agents.handler:run"},
    })
    assert r.status_code == 201, r.text
    agent = r.json()
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


def _execute(client: TestClient, admin: dict, setup: dict, **kwargs) -> dict:
    body = {"agent_id": setup["agent"]["id"], "input_payload": {}, **kwargs}
    r = client.post(f"{RT}/executions", headers=admin["headers"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _second_org(client: TestClient) -> dict:
    from tests.runtime.conftest import PASSWORD

    email = f"trace2_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": "Other Trace Org", "name": "Owner",
        "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login",
                         json={"email": email, "password": PASSWORD}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"}}


def _wide_window() -> dict:
    """The explorer defaults to a 30-day window; test data is `now`, but being
    explicit keeps these tests independent of when they run."""
    return {"started_after": (datetime.now(timezone.utc) - timedelta(days=3650)).isoformat()}


def _kinds(trace: dict) -> list[str]:
    return [span["kind"] for span in trace["spans"]]


# =========================================================================== #
# AC-01 -- the trace reconstructs with the §8-4.2 node categories
# =========================================================================== #
def test_ac01_the_trace_has_the_expected_node_categories(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    execution = _execute(client, admin, setup)

    r = client.get(f"{OBS}/executions/{execution['id']}/trace", headers=admin["headers"])
    assert r.status_code == 200, r.text
    trace = r.json()

    kinds = set(_kinds(trace))
    # The phases every execution passes through, whatever it does.
    assert {SpanKind.EXECUTION.value, SpanKind.AUTHORIZATION.value,
            SpanKind.RUNTIME_POLICY.value} <= kinds, kinds
    # A completed execution finalizes.
    if execution["status"] in ("SUCCEEDED", "FAILED"):
        assert SpanKind.FINALIZATION.value in kinds, kinds


def test_ac01_the_root_span_envelopes_every_child(client: TestClient, admin: dict) -> None:
    """A trace root that started *after* one of its children is incoherent on a
    timeline -- and it was the real 4.1 modelling bug this phase found: the root
    began at `started_at`, so the gate nodes 4.2 added rendered outside their
    own parent."""
    setup = _ready_agent(client, admin)
    execution = _execute(client, admin, setup)
    trace = client.get(f"{OBS}/executions/{execution['id']}/trace",
                       headers=admin["headers"]).json()

    root = trace["spans"][0]
    assert root["kind"] == SpanKind.EXECUTION.value, "root must lead the timeline"
    assert root["parent_span_id"] is None

    for span in trace["spans"][1:]:
        if span["started_at"] and root["started_at"]:
            assert span["started_at"] >= root["started_at"], span


def test_ac01_spans_are_ordered_chronologically(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    execution = _execute(client, admin, setup)
    trace = client.get(f"{OBS}/executions/{execution['id']}/trace",
                       headers=admin["headers"]).json()

    starts = [s["started_at"] for s in trace["spans"][1:] if s["started_at"]]
    assert starts == sorted(starts), starts


def test_ac01_each_node_carries_timing_status_and_identity(
    client: TestClient, admin: dict,
) -> None:
    setup = _ready_agent(client, admin)
    execution = _execute(client, admin, setup)
    trace = client.get(f"{OBS}/executions/{execution['id']}/trace",
                       headers=admin["headers"]).json()

    for span in trace["spans"]:
        assert span["span_id"] and span["kind"] and span["name"]
        assert "started_at" in span and "duration_ms" in span
        assert "status" in span and "error_code" in span
        assert isinstance(span["attributes"], dict)


# =========================================================================== #
# AC-02 -- cost/tokens and the governing decision
# =========================================================================== #
def test_ac02_finalization_surfaces_cost_and_tokens(client: TestClient, admin: dict) -> None:
    """Read from the existing `cost_amount`/token columns. This phase *shows*
    cost; 4.4 governs it."""
    setup = _ready_agent(client, admin)
    execution = _execute(client, admin, setup)
    trace = client.get(f"{OBS}/executions/{execution['id']}/trace",
                       headers=admin["headers"]).json()

    final = [s for s in trace["spans"] if s["kind"] == SpanKind.FINALIZATION.value]
    if not final:
        pytest.skip("execution had not completed")
    attributes = final[0]["attributes"]
    assert "cost_currency" in attributes
    assert "loop_iterations" in attributes


def test_ac02_a_gate_node_surfaces_its_governing_decision(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """Where the domain already recorded *why* something was refused, the node
    shows it. 4.3 will author richer decisions; 4.2 authors none."""
    from app.observability.assembly import _decision_attributes

    execution = AgentExecution(
        id=uuid.uuid4(), status="BLOCKED", decision="DENY",
        error_code="RUNTIME_POLICY_DENIED", error_message="Concurrency limit reached.",
        risk_score=42,
    )
    attributes = _decision_attributes(execution)
    assert attributes["decision"] == "DENY"
    assert attributes["error_code"] == "RUNTIME_POLICY_DENIED"
    assert attributes["risk_score"] == "42"
    assert "Concurrency" in attributes["reason"]


def test_ac02_the_queue_node_is_a_computed_gap_not_a_row(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """Nothing records "the queue" as an entity and 4.1 added no table for one,
    but `queued_at`->`started_at` is a real interval and is frequently the
    largest one in a slow trace. It is reported as a phase with no
    `source_table`, which is how a reader tells derived nodes from row-backed
    ones."""
    now = datetime.now(timezone.utc)
    execution = AgentExecution(
        id=uuid.uuid4(), status="SUCCEEDED", correlation_id=None,
        created_at=now, queued_at=now, started_at=now + timedelta(milliseconds=1500),
        completed_at=now + timedelta(seconds=2), priority="NORMAL",
    )
    trace = TraceAssembler(db_session).assemble.__wrapped__ if False else None  # noqa: F841
    from app.observability.trace import TraceContext

    root = TraceContext.for_execution(execution).root_span(SpanKind.EXECUTION, execution.id)
    span = TraceAssembler._queue_span(execution, root)
    assert span is not None
    assert span.kind is SpanKind.QUEUE
    assert span.source_table is None, "the queue is a computed gap, not a row"
    assert span.duration_ms == 1500


def test_ac02_no_queue_node_when_the_wait_is_still_open(db_session: Session) -> None:
    """An open-ended wait is not a measured duration. Reporting one would
    misrepresent an in-flight execution."""
    from app.observability.trace import TraceContext

    execution = AgentExecution(id=uuid.uuid4(), status="QUEUED",
                               queued_at=datetime.now(timezone.utc), started_at=None)
    root = TraceContext.for_execution(execution).root_span(SpanKind.EXECUTION, execution.id)
    assert TraceAssembler._queue_span(execution, root) is None


# =========================================================================== #
# AC-03 -- links, not a duplicated span store (§13 / ADR-0008)
# =========================================================================== #
def test_ac03_no_span_store_was_added() -> None:
    from app.core.database import Base

    forbidden = {"runtime_trace_spans", "trace_spans", "spans", "runtime_spans",
                 "telemetry_spans", "otel_spans", "runtime_trace_index",
                 "trace_projection", "execution_trace_summary"}
    assert not (forbidden & set(Base.metadata.tables)), forbidden & set(Base.metadata.tables)


def test_ac03_phase_42_added_one_index_and_no_table() -> None:
    """Reads 4.2's own migration, so this asserts what *this phase* did and
    stays true as later phases add their own."""
    source = (BACKEND_ROOT / "migrations" / "versions"
              / "0046_trace_explorer_index.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

    def ops(name: str) -> list[str]:
        return [n.func.attr for n in ast.walk(functions[name])
                if isinstance(n, ast.Call) and hasattr(n.func, "attr")]

    up, down = ops("upgrade"), ops("downgrade")
    assert "create_table" not in up, "4.2 must add no table (SRS §13, ADR-0008)"
    assert "add_column" not in up, "4.2 must add no column"
    assert up.count("create_index") == 1
    assert down.count("drop_index") == 1


def test_ac03_row_backed_spans_name_their_source_row(client: TestClient, admin: dict) -> None:
    """A span is a *view* of an authoritative row and says which one; a derived
    phase says it has none. Those are the only two options -- an invented
    source table would mean the trace had started storing things."""
    setup = _ready_agent(client, admin)
    execution = _execute(client, admin, setup)
    trace = client.get(f"{OBS}/executions/{execution['id']}/trace",
                       headers=admin["headers"]).json()

    allowed = {None, "agent_executions", "execution_attempts", "execution_messages",
               "tool_calls", "runtime_approvals"}
    for span in trace["spans"]:
        assert span["source_table"] in allowed, span
        if span["source_table"] is not None:
            assert span["source_id"], span


def test_ac03_the_assembler_and_explorer_only_read() -> None:
    """Structural, over the AST. Checked as *calls*, not as words: both modules'
    docstrings necessarily discuss writing while explaining they never do."""
    for module in (
        BACKEND_ROOT / "app" / "observability" / "assembly.py",
        BACKEND_ROOT / "app" / "observability" / "explorer.py",
        BACKEND_ROOT / "app" / "observability" / "routes.py",
    ):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        called = {n.func.attr for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for forbidden in ("add", "add_all", "commit", "delete", "flush", "merge"):
            assert forbidden not in called, f"{module.name} calls {forbidden}()"


# =========================================================================== #
# AC-04 -- metadata only. The hard line.
# =========================================================================== #
def test_ac04_no_content_is_returned_by_the_trace(client: TestClient, admin: dict) -> None:
    """A real execution with a distinctive marker in its input; the marker must
    appear nowhere in the trace."""
    setup = _ready_agent(client, admin)
    marker = f"CONFIDENTIAL-{uuid.uuid4().hex[:10]}"
    execution = _execute(client, admin, setup, input_payload={"question": marker})

    body = client.get(f"{OBS}/executions/{execution['id']}/trace",
                      headers=admin["headers"]).text
    assert marker not in body


def test_ac04_no_content_is_returned_by_the_explorer(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    marker = f"CONFIDENTIAL-{uuid.uuid4().hex[:10]}"
    _execute(client, admin, setup, input_payload={"question": marker})

    body = client.get(f"{OBS}/traces", headers=admin["headers"], params=_wide_window()).text
    assert marker not in body


def test_ac04_the_read_models_never_touch_a_content_column() -> None:
    """Enforced upstream of the routes, so it cannot be undone by a route change
    alone. Asserted over the AST as *attribute reads*, because the modules'
    comments legitimately name these columns while explaining they are skipped."""
    content_columns = {"input_payload", "output_payload", "input_summary",
                       "output_summary", "content", "tool_calls_requested",
                       "decision_comment", "request_summary"}
    for module in (BACKEND_ROOT / "app" / "observability" / "assembly.py",
                   BACKEND_ROOT / "app" / "observability" / "explorer.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        read = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        leaked = content_columns & read
        assert not leaked, f"{module.name} reads content column(s): {leaked}"


def test_ac04_the_content_permission_is_not_registered() -> None:
    """It is named in code so the boundary has a visible owner, but registering
    it would create a grantable permission that guards nothing (4.1's reasoning,
    carried forward)."""
    from app.services.rbac_service import PERMISSION_CATALOG

    assert "runtime.trace.content.view" not in PERMISSION_CATALOG
    # And the permission this phase *does* use already existed -- 4.2 registered
    # no synonym for a capability the catalog already described.
    assert PERMISSION_CATALOG["runtime.telemetry.view"] == (
        "View runtime telemetry and execution traces")


# =========================================================================== #
# AC-05 -- the explorer filters
# =========================================================================== #
def test_ac05_explorer_returns_this_tenants_executions(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    execution = _execute(client, admin, setup)

    r = client.get(f"{OBS}/traces", headers=admin["headers"], params=_wide_window())
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(item["execution_id"] == execution["id"] for item in body["items"])
    assert body["limit"] and "has_more" in body


@pytest.mark.parametrize("dimension", [
    "agent_id", "agent_version_id", "deployment_id", "status", "environment",
    "model", "provider", "trace_id", "execution_id",
])
def test_ac05_each_filter_dimension_narrows(client: TestClient, admin: dict,
                                            dimension: str) -> None:
    """Parametrized over the §4.2 dimension list, so a filter that stops working
    fails by name rather than being lost in one composite assertion."""
    setup = _ready_agent(client, admin)
    correlation = f"trace-{uuid.uuid4().hex[:10]}"
    r = client.post(f"{RT}/executions",
                    headers={**admin["headers"], "x-correlation-id": correlation},
                    json={"agent_id": setup["agent"]["id"], "input_payload": {}})
    assert r.status_code == 201, r.text
    execution = r.json()

    values = {
        "agent_id": setup["agent"]["id"],
        "agent_version_id": setup["version"]["id"],
        "deployment_id": setup["deployment"]["id"],
        "status": execution["status"],
        "environment": "DEVELOPMENT",
        "model": "mock-model",
        "provider": "MOCK",
        "trace_id": correlation,
        "execution_id": execution["id"],
    }
    params = {**_wide_window(), dimension: values[dimension]}
    body = client.get(f"{OBS}/traces", headers=admin["headers"], params=params).json()
    assert any(i["execution_id"] == execution["id"] for i in body["items"]), \
        f"{dimension}={values[dimension]} did not match its own execution"
    assert dimension in body["filters_applied"] or dimension in ("status",), body["filters_applied"]


def test_ac05_a_non_matching_filter_returns_nothing(client: TestClient, admin: dict) -> None:
    """The other half of a filter test, and the half that catches a predicate
    silently compiled as a no-op."""
    setup = _ready_agent(client, admin)
    _execute(client, admin, setup)
    body = client.get(f"{OBS}/traces", headers=admin["headers"],
                      params={**_wide_window(), "agent_id": str(uuid.uuid4())}).json()
    assert body["items"] == []


def test_ac05_an_unknown_status_is_rejected_not_silently_empty(
    client: TestClient, admin: dict,
) -> None:
    r = client.get(f"{OBS}/traces", headers=admin["headers"],
                   params={"status": "NOT_A_REAL_STATUS"})
    assert r.status_code == 422, r.text


def test_ac05_lookup_by_trace_id_returns_the_assembled_trace(
    client: TestClient, admin: dict,
) -> None:
    setup = _ready_agent(client, admin)
    correlation = f"trace-{uuid.uuid4().hex[:10]}"
    r = client.post(f"{RT}/executions",
                    headers={**admin["headers"], "x-correlation-id": correlation},
                    json={"agent_id": setup["agent"]["id"], "input_payload": {}})
    assert r.status_code == 201

    body = client.get(f"{OBS}/traces/{correlation}", headers=admin["headers"]).json()
    assert body["trace_id"] == correlation
    assert body["executions"] >= 1
    assert body["traces"][0]["spans"]


def test_ac05_a_correlation_can_span_several_executions(
    client: TestClient, admin: dict,
) -> None:
    """The reason `GET /traces/{id}` returns a list rather than one object: a
    caller-supplied correlation legitimately covers a whole workflow."""
    setup = _ready_agent(client, admin)
    correlation = f"workflow-{uuid.uuid4().hex[:10]}"
    for _ in range(2):
        r = client.post(f"{RT}/executions",
                        headers={**admin["headers"], "x-correlation-id": correlation},
                        json={"agent_id": setup["agent"]["id"], "input_payload": {}})
        assert r.status_code == 201

    body = client.get(f"{OBS}/traces/{correlation}", headers=admin["headers"]).json()
    assert body["executions"] == 2


def test_ac05_pagination_is_bounded(client: TestClient, admin: dict) -> None:
    r = client.get(f"{OBS}/traces", headers=admin["headers"],
                   params={**_wide_window(), "limit": 10_000})
    assert r.status_code == 422, "an out-of-range limit is rejected at the schema"

    page = TraceExplorer  # the service clamps rather than rejects
    assert MAX_PAGE_SIZE <= 500
    assert page is not None


def test_ac05_the_service_clamps_an_oversized_limit(db_session: Session, admin: dict) -> None:
    """The route bounds `limit` at the schema; the service clamps independently
    so a future internal caller cannot bypass it."""
    page = TraceExplorer(db_session).search(
        uuid.UUID(admin["organization_id"]), TraceFilters(), limit=99_999)
    assert page.limit == MAX_PAGE_SIZE


# =========================================================================== #
# AC-06 -- bounded, index-backed queries
# =========================================================================== #
def test_ac06_the_explorer_query_uses_the_index_and_does_not_scan(
    db_session: Session, admin: dict,
) -> None:
    """Asserted against the real query plan, not inferred from timing.

    **What this asserts and what it deliberately does not.** The invariant that
    must hold for every tenant is that the query reaches its rows through
    ``ix_agent_executions_org_created`` and never sequentially scans
    ``agent_executions``. That is checked here.

    It does *not* assert the absence of a ``Sort`` node, and the reason is worth
    recording rather than quietly dropping. For a tenant owning almost nothing --
    which a freshly-registered test organization is -- Postgres correctly
    prefers a bitmap index scan plus a trivial top-N sort over walking the index
    in order, because sorting fourteen estimated rows is cheaper than an ordered
    traversal. Asserting "no Sort" here would demand a plan that is *worse* for
    the case being tested, and would fail against a correct planner.

    The sort elision is a property of the query at *volume*, and it was measured
    there: on the development database's busiest real tenant the same query
    plans as ``Index Scan ... rows=50`` with no Sort node at all, against
    ``Bitmap Heap Scan -> rows=500 -> top-N heapsort`` before migration 0046.
    Both plans are recorded in ADR-0008, which is where a claim backed by a
    measurement belongs."""
    org = uuid.UUID(admin["organization_id"])
    sql = ("SELECT id FROM agent_executions WHERE organization_id = :o "
           "ORDER BY created_at DESC LIMIT 50")
    plan = "\n".join(r[0] for r in db_session.execute(
        text("EXPLAIN (ANALYZE) " + sql), {"o": org}))

    assert "Seq Scan on agent_executions" not in plan, plan
    assert "ix_agent_executions_org_created" in plan, plan


def test_ac06_at_volume_the_index_elides_the_sort(db_session: Session) -> None:
    """The other half: the O(limit) property the 0046 index exists to give.

    Runs against whichever tenant in this database owns the most executions,
    because the planner only chooses the ordered scan once there are enough rows
    for it to pay. The precondition is asserted rather than skipped past, so
    this cannot pass vacuously against an empty database -- if there is no
    tenant with meaningful volume, that is a broken fixture and the test says
    so."""
    row = db_session.execute(text(
        "SELECT organization_id, count(*) c FROM agent_executions "
        "GROUP BY 1 ORDER BY c DESC LIMIT 1")).first()
    assert row is not None, "no executions at all -- the measurement is meaningless"
    org, count = row
    assert count >= 50, (
        f"busiest tenant owns {count} executions; too few to exercise the ordered "
        f"scan this index exists for")

    plan = "\n".join(r[0] for r in db_session.execute(
        text("EXPLAIN (ANALYZE) SELECT id FROM agent_executions "
             "WHERE organization_id = :o ORDER BY created_at DESC LIMIT 50"), {"o": org}))

    assert "Seq Scan on agent_executions" not in plan, plan
    assert "ix_agent_executions_org_created" in plan, plan
    assert "Sort Key" not in plan, (
        f"at {count} rows the 0046 index should be walked in order, not sorted:\n{plan}")


def test_ac06_the_0046_index_exists_with_descending_order(db_session: Session) -> None:
    """`DESC` is not cosmetic: the index order must match the query's ORDER BY
    for the sort to be elided at all."""
    definition = db_session.execute(text(
        "select indexdef from pg_indexes where indexname = 'ix_agent_executions_org_created'"
    )).scalar()
    assert definition, "migration 0046's index is missing"
    assert "organization_id" in definition and "created_at DESC" in definition


def test_ac06_trace_assembly_does_not_issue_a_query_per_span(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """The N+1 guard. Assembly must cost a fixed number of queries regardless of
    how many spans a trace has, or a busy execution becomes a query storm."""
    setup = _ready_agent(client, admin)
    execution = _execute(client, admin, setup)
    execution_row = db_session.get(AgentExecution, uuid.UUID(execution["id"]))

    counter = {"n": 0}

    def _count(*args, **kwargs):
        counter["n"] += 1

    event.listen(db_session.get_bind(), "before_cursor_execute", _count)
    try:
        trace = TraceAssembler(db_session).assemble(execution_row)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", _count)

    # execution children: attempts, messages, tool_calls, approvals. Flat.
    assert counter["n"] <= 6, f"{counter['n']} queries for {len(trace.spans)} spans"


def test_ac06_the_explorer_defaults_to_a_bounded_window(db_session: Session,
                                                        admin: dict) -> None:
    """An unbounded default is the one shape that is cheap on a small tenant and
    a table scan on a large one."""
    page = TraceExplorer(db_session).search(uuid.UUID(admin["organization_id"]),
                                            TraceFilters())
    assert page.window_start is not None and page.window_end is not None
    assert (page.window_end - page.window_start) <= explorer_module.DEFAULT_WINDOW


# =========================================================================== #
# AC-07 / AC-08 -- the ADR-0008 measurement
# =========================================================================== #
def test_ac07_adr0008_assembly_meets_the_latency_budget(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    """**The ADR-0008 measurement, kept as a test rather than a note.**

    ADR-0008 named this phase as the point to revisit the derived-spans decision
    with real numbers. Measured against the development database at 90,695
    executions / 355,377 runtime_events, assembly ran at 0.74ms p50 / 1.08ms
    p95 -- three orders of magnitude inside budget -- so no projection was
    added. Keeping the benchmark executable is what stops that conclusion from
    quietly expiring."""
    setup = _ready_agent(client, admin)
    execution = _execute(client, admin, setup)
    row = db_session.get(AgentExecution, uuid.UUID(execution["id"]))

    assembler = TraceAssembler(db_session)
    assembler.assemble(row)  # warm

    samples = []
    for _ in range(10):
        start = time.perf_counter()
        assembler.assemble(row)
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    p95 = samples[-1]
    assert p95 < LATENCY_BUDGET_MS, f"assembly p95 {p95:.2f}ms exceeds {LATENCY_BUDGET_MS}ms"


def test_ac07_adr0008_explorer_meets_the_latency_budget(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    org = uuid.UUID(admin["organization_id"])
    explorer = TraceExplorer(db_session)
    explorer.search(org, TraceFilters())  # warm

    samples = []
    for _ in range(10):
        start = time.perf_counter()
        explorer.search(org, TraceFilters(), limit=50)
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    p95 = samples[-1]
    assert p95 < LATENCY_BUDGET_MS, f"explorer p95 {p95:.2f}ms exceeds {LATENCY_BUDGET_MS}ms"


def test_ac08_the_restraint_decision_is_recorded_in_adr0008() -> None:
    """AC-08's "if not, the restraint numbers are recorded" branch. The numbers
    live in the ADR because that is where the decision they justify lives."""
    adr = (BACKEND_ROOT.parent / "docs" / "architecture" / "adr"
           / "0008-telemetry-as-a-derived-plane.md").read_text(encoding="utf-8")
    assert "## Measurement outcome" in adr
    assert "90,695" in adr, "the measured volume must be recorded"
    assert "0046" in adr, "the one index the measurement did justify"


# =========================================================================== #
# AC-09 -- tenant isolation (§34)
# =========================================================================== #
def test_ac09_another_tenant_cannot_fetch_a_trace_by_execution_id(
    client: TestClient, admin: dict,
) -> None:
    setup = _ready_agent(client, admin)
    execution = _execute(client, admin, setup)
    other = _second_org(client)

    r = client.get(f"{OBS}/executions/{execution['id']}/trace", headers=other["headers"])
    assert r.status_code in (403, 404), r.text


def test_ac09_another_tenant_cannot_fetch_a_trace_by_trace_id(
    client: TestClient, admin: dict,
) -> None:
    setup = _ready_agent(client, admin)
    correlation = f"secret-trace-{uuid.uuid4().hex[:10]}"
    r = client.post(f"{RT}/executions",
                    headers={**admin["headers"], "x-correlation-id": correlation},
                    json={"agent_id": setup["agent"]["id"], "input_payload": {}})
    assert r.status_code == 201
    other = _second_org(client)

    r = client.get(f"{OBS}/traces/{correlation}", headers=other["headers"])
    assert r.status_code in (403, 404), r.text


def test_ac09_a_known_id_is_indistinguishable_from_a_nonexistent_one(
    client: TestClient, admin: dict,
) -> None:
    """§34's actual requirement: not merely refusing to read another tenant's
    data, but refusing to *confirm it exists*. The two responses must be
    byte-identical, or the difference is an oracle."""
    setup = _ready_agent(client, admin)
    real = _execute(client, admin, setup)
    other = _second_org(client)

    theirs = client.get(f"{OBS}/executions/{real['id']}/trace", headers=other["headers"])
    absent = client.get(f"{OBS}/executions/{uuid.uuid4()}/trace", headers=other["headers"])

    assert theirs.status_code == absent.status_code
    # Compared on the error payload rather than the whole body: the envelope's
    # `meta` carries a per-request id and timestamp, which differ between any
    # two requests and reveal nothing about either tenant. The part that would
    # leak -- the code and the message -- must be identical.
    assert theirs.json()["error"] == absent.json()["error"]
    assert theirs.json()["success"] == absent.json()["success"] is False


def test_ac09_the_explorer_never_returns_another_tenants_rows(
    client: TestClient, admin: dict,
) -> None:
    setup = _ready_agent(client, admin)
    mine = _execute(client, admin, setup)
    other = _second_org(client)

    body = client.get(f"{OBS}/traces", headers=other["headers"], params=_wide_window()).json()
    assert all(i["execution_id"] != mine["id"] for i in body["items"])


def test_ac09_every_explorer_statement_filters_on_the_tenant() -> None:
    """Structural: there must be no code path in the explorer that builds a
    statement without an organization predicate -- not a helper, not an admin
    variant, not a "count all" for a total."""
    source = (BACKEND_ROOT / "app" / "observability" / "explorer.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ("search", "find_by_trace_id",
                                                               "_build"):
            body = ast.dump(node)
            assert "organization_id" in body, f"{node.name} builds a query without a tenant filter"


# =========================================================================== #
# AC-10 / AC-11 -- non-gating, and in-flight consistency
# =========================================================================== #
def test_ac10_reading_a_trace_does_not_change_the_execution(
    client: TestClient, admin: dict, db_session: Session,
) -> None:
    setup = _ready_agent(client, admin)
    execution = _execute(client, admin, setup)
    row = db_session.get(AgentExecution, uuid.UUID(execution["id"]))
    db_session.refresh(row)
    before = (row.status, row.updated_at, row.cost_amount, row.attempt_count)

    for _ in range(3):
        assert client.get(f"{OBS}/executions/{execution['id']}/trace",
                          headers=admin["headers"]).status_code == 200
        assert client.get(f"{OBS}/traces", headers=admin["headers"],
                          params=_wide_window()).status_code == 200

    db_session.refresh(row)
    assert (row.status, row.updated_at, row.cost_amount, row.attempt_count) == before


def test_ac11_an_in_flight_execution_renders_a_partial_trace(db_session: Session) -> None:
    """No torn read: a running execution shows the nodes that have happened and
    omits the ones that have not, rather than inventing a terminal state."""
    from app.observability.trace import TraceContext

    now = datetime.now(timezone.utc)
    running = AgentExecution(
        id=uuid.uuid4(), status="RUNNING", correlation_id=None,
        created_at=now, queued_at=now, started_at=now, completed_at=None,
    )
    root = TraceContext.for_execution(running).root_span(SpanKind.EXECUTION, running.id)
    assert TraceAssembler._finalization_span(running, root) is None, \
        "a running execution must not show a finalization node"


def test_ac11_a_denied_execution_shows_no_policy_node(db_session: Session) -> None:
    """The policy gate only ran if authorization allowed. Emitting it for a
    DENIED execution would show a phase that never executed."""
    from app.observability.trace import TraceContext

    denied = AgentExecution(
        id=uuid.uuid4(), status="DENIED", decision="DENY", correlation_id=None,
        error_code="RUNTIME_POLICY_DENIED", created_at=datetime.now(timezone.utc),
    )
    root = TraceContext.for_execution(denied).root_span(SpanKind.EXECUTION, denied.id)
    kinds = [s.kind for s in TraceAssembler(db_session)._gate_spans(denied, root)]
    assert SpanKind.AUTHORIZATION in kinds
    assert SpanKind.RUNTIME_POLICY not in kinds


# =========================================================================== #
# AC-12 / AC-13 -- permissions and route surface
# =========================================================================== #
def test_ac12_the_trace_endpoints_require_authentication(client: TestClient,
                                                         admin: dict) -> None:
    setup = _ready_agent(client, admin)
    execution = _execute(client, admin, setup)
    for path in (f"{OBS}/traces", f"{OBS}/traces/anything",
                 f"{OBS}/executions/{execution['id']}/trace"):
        assert client.get(path).status_code in (401, 403), path


def test_ac13_the_observability_prefix_does_not_collide(client: TestClient) -> None:
    """This is the new governed-observability surface, distinct from the legacy
    analytics dashboards (which aggregate the Phase 3 `agent_actions` table and
    know nothing of AgentExecution)."""
    import app.main as main_module
    from fastapi.routing import APIRoute

    paths = [r.path for r in main_module.app.routes if isinstance(r, APIRoute)]
    observability = [p for p in paths if p.startswith("/api/v1/observability")]
    assert len(observability) == 3, observability
    assert not [p for p in observability if "analytics" in p]
    # And no duplicate path anywhere in the app.
    assert len(paths) == len(set((p, tuple(sorted(r.methods)))
                                 for p, r in zip(paths, [r for r in main_module.app.routes
                                                         if isinstance(r, APIRoute)])))


def test_ac13_the_41_route_still_works_and_agrees(client: TestClient, admin: dict) -> None:
    """4.1's route is retained and delegates to the same assembler, so the two
    paths cannot diverge."""
    setup = _ready_agent(client, admin)
    execution = _execute(client, admin, setup)

    old = client.get(f"{RT}/executions/{execution['id']}/trace", headers=admin["headers"])
    new = client.get(f"{OBS}/executions/{execution['id']}/trace", headers=admin["headers"])
    assert old.status_code == new.status_code == 200
    assert old.json() == new.json()


# =========================================================================== #
# AC-16 -- no placeholder markers
# =========================================================================== #
def test_ac16_no_placeholder_markers_in_the_new_code() -> None:
    """Built by concatenation so this list does not match itself."""
    markers = ("TO" + "DO", "FIX" + "ME", "NotImplemented" + "Error",
               "@pytest.mark." + "skip", "@pytest.mark." + "xfail")
    sources = [
        BACKEND_ROOT / "app" / "observability" / "explorer.py",
        BACKEND_ROOT / "app" / "observability" / "routes.py",
        BACKEND_ROOT / "app" / "observability" / "assembly.py",
        BACKEND_ROOT / "migrations" / "versions" / "0046_trace_explorer_index.py",
    ]
    for path in sources:
        source = path.read_text(encoding="utf-8")
        for marker in markers:
            assert marker not in source, f"{path.name} contains {marker}"
