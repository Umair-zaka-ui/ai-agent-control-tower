"""Phase 4.4 tests — cost governance and FinOps.

The weight is on the two gates. **Gate D** is cost truth: real per-execution
spend, aggregated every way an enterprise allocates it, with actual and
estimated never added together. **Gate E** is the §35 budget race: concurrent
workers must not each spend the same remaining allowance, proven with **real
separate Postgres sessions** — never an in-process lock, which §11 forbids and
which the Phase 3.9 worker fleet would make worthless anyway.

Alongside those, the property this phase must not break: Phase 4.3 still owns
enforcement. A budget produces a *number*; the engine turns it into a decision.
There is no code in ``app/finops`` that stops an execution, and a test asserts
that structurally rather than trusting it.
"""

from __future__ import annotations

import ast
import json as jsonlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.finops.aggregation import CostAggregator, CostFilters
from app.finops.budgets import BudgetService, ExecutionScope
from app.finops.guard import BudgetGuard
from app.finops.reservations import (
    RECONCILED,
    RELEASED,
    RESERVED,
    ReservationService,
    period_key,
)
from app.models.rbac import AuthorizationAudit
from app.models.runtime import (
    AgentExecution,
    Budget,
    BudgetReservation,
    RuntimeGovernanceDecision,
)
from app.runtime.governance.contract import Checkpoint, Decision, ReasonCode
from app.runtime.providers.openai_compatible import OpenAICompatibleProvider
from app.runtime.services import PricingService
from app.runtime.tools import egress_guard

PASSWORD = "T3st!Passw0rd#Ok"
RT = "/api/v1/runtime"
BACKEND_ROOT = Path(__file__).resolve().parents[2]

# The legacy estimate lives at `/analytics/cost`, not under `/api/v1`: the
# Phase-3 analytics router is mounted through `api_router` with
# `settings.API_PREFIX`, which is the empty string. Worth naming here because
# the un-prefixed path is easy to assume away, and this phase deprecates the
# endpoint rather than moving it -- so the path is part of the contract.
LEGACY_COST_PATH = "/analytics/cost"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _patch_default_resolver(monkeypatch):
    monkeypatch.setattr(egress_guard, "_default_resolve", lambda host: ["127.0.0.1"])


@pytest.fixture(autouse=True)
def _quiesce_queue():
    """Terminalize other suites' abandoned QUEUED executions before each test.

    `ExecutionWorkerService.claim_next` picks the oldest QUEUED row **across
    every organization** -- that is correct for a shared worker fleet and wrong
    for a test that needs the eager inline worker to run *its own* execution.
    A single stale row left behind by an unrelated suite starves every
    execution this file creates, which surfaces as an execution stuck in
    QUEUED with no error at all: the most confusing possible symptom, because
    nothing failed.

    Phase 3.9 hit exactly this and answered it with `_quiesce`; this is the
    same discipline, narrowed to the queue. RUNNING rows are deliberately left
    alone -- several tests here hold reservations against live executions, and
    cancelling those would break the thing under test rather than the
    environment around it."""
    from sqlalchemy import update

    db = SessionLocal()
    try:
        db.execute(
            update(AgentExecution)
            .where(AgentExecution.status == "QUEUED")
            .values(status="CANCELLED", completed_at=datetime.now(timezone.utc))
        )
        db.commit()
    finally:
        db.close()


def _use_transport(monkeypatch, transport: httpx.MockTransport) -> None:
    monkeypatch.setattr(OpenAICompatibleProvider, "_build_default_transport", lambda self: transport)


def _final_answer(model: str = "llama3", tokens: int = 80) -> dict:
    return {
        "id": "chatcmpl-cost", "object": "chat.completion", "created": 1718000000, "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "Done."},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": tokens - 20, "completion_tokens": 20, "total_tokens": tokens},
    }


def _tool_call(name: str, args: dict, *, model: str = "llama3", tokens: int = 50) -> dict:
    return {
        "id": "chatcmpl-cost-tool", "object": "chat.completion", "created": 1718000000,
        "model": model,
        "choices": [{"index": 0, "message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": name, "arguments": jsonlib.dumps(args)}}]},
            "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": tokens - 10, "completion_tokens": 10, "total_tokens": tokens},
    }


def _static_transport(body: dict) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json=body, request=request))


def _register_org(client: TestClient, org_name: str = "FinOps Org") -> dict:
    email = f"finops_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": org_name, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"]}


def _ready_agent(client: TestClient, admin: dict, *, model: str = "llama3",
                 tool_ids: list[str] | None = None) -> dict:
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Cost Agent {uuid.uuid4().hex[:6]}", "agent_type": "ASSISTANT",
        "criticality": "MEDIUM", "description": "A test agent.",
        "business_purpose": "Exercise cost governance.", "owner_type": "USER",
        "owner_id": admin["user_id"], "technical_owner_id": admin["user_id"],
        "compliance_owner_id": admin["user_id"],
        "definition": {"name": "Definition", "framework": "CUSTOM",
                       "entrypoint_type": "FUNCTION", "entrypoint": "agents.handler:run"},
    })
    assert r.status_code == 201, r.text
    agent = r.json()
    for step in ("register", "validate"):
        assert client.post(f"{RT}/agents/{agent['id']}/{step}",
                           headers=admin["headers"]).status_code == 200
    assert client.post(f"{RT}/agents/{agent['id']}/identity/create-and-associate",
                       headers=admin["headers"],
                       json={"client_id": f"agent-identity-{uuid.uuid4().hex[:10]}"}).status_code == 200
    for step in ("submit-for-approval", "approve", "activate"):
        assert client.post(f"{RT}/agents/{agent['id']}/{step}",
                           headers=admin["headers"]).status_code == 200
    for tool_id in (tool_ids or []):
        assert client.post(f"{RT}/agents/{agent['id']}/tools", headers=admin["headers"],
                           json={"tool_id": tool_id,
                                 "allowed_actions": ["EXECUTE", "READ"]}).status_code == 201
    r = client.post(f"{RT}/agents/{agent['id']}/versions", headers=admin["headers"], json={
        "model_configuration": {"provider": "OPENAI_COMPATIBLE", "model": model},
        "tool_ids": tool_ids or [],
    })
    assert r.status_code == 201, r.text
    version = r.json()
    for step in ("validate", "approve", "publish"):
        assert client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/{step}",
                           headers=admin["headers"]).status_code == 200
    r = client.post(f"{RT}/deployments", headers=admin["headers"],
                    params={"agent_id": agent["id"]},
                    json={"agent_version_id": version["id"], "environment": "DEVELOPMENT"})
    assert r.status_code == 201, r.text
    deployment = r.json()
    assert client.post(f"{RT}/deployments/{deployment['id']}/deploy",
                       headers=admin["headers"]).status_code == 200
    return {"agent": agent, "version": version, "deployment": deployment}


def _run(client: TestClient, admin: dict, agent_id: str) -> dict:
    r = client.post(f"{RT}/executions", headers=admin["headers"], json={
        "agent_id": agent_id, "input_payload": {"q": "hello"}})
    assert r.status_code == 201, r.text
    return r.json()


def _unique_model(prefix: str = "cost") -> str:
    """`model_pricing` has no organization column, so a price seeded for a
    shared model name is global and permanent. Every test that needs a price
    uses a name no other test will."""
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _seed_price(db: Session, model: str, *, prompt: float, completion: float,
                version: str | None = None, effective_from: datetime | None = None) -> str:
    label = version or f"test-{uuid.uuid4().hex[:6]}"
    PricingService(db).set_price(
        provider="OPENAI_COMPATIBLE", model=model, prompt_cost_per_1k=prompt,
        completion_cost_per_1k=completion, pricing_version=label,
        effective_from=effective_from or datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    db.commit()
    return label


def _budget(db: Session, organization_id: str, *, mode: str = "HARD_LIMIT",
            limit: float = 1.0, period: str = "MONTHLY", scope_type: str = "ORGANIZATION",
            scope_id: uuid.UUID | None = None, scope_value: str | None = None,
            estimate: float | None = 0.25, threshold: int = 80,
            name: str = "test budget") -> Budget:
    row = Budget(
        organization_id=uuid.UUID(organization_id), name=name, scope_type=scope_type,
        scope_id=scope_id, scope_value=scope_value, mode=mode, period=period,
        limit_amount=limit, currency="USD", reservation_estimate=estimate,
        threshold_percent=threshold, enabled=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _make_execution(db: Session, setup: dict, org: dict, *, cost: float | None = None,
                    estimated: bool = False, created_at: datetime | None = None,
                    status: str = "SUCCEEDED", tokens: int = 100,
                    pricing_version: str | None = "test-v1") -> AgentExecution:
    """A committed execution row, written directly.

    Driving several thousand executions through the HTTP pipeline to test an
    aggregation would measure the pipeline, not the aggregation."""
    row = AgentExecution(
        organization_id=uuid.UUID(org["organization_id"]),
        agent_id=uuid.UUID(setup["agent"]["id"]),
        agent_version_id=uuid.UUID(setup["version"]["id"]),
        deployment_id=uuid.UUID(setup["deployment"]["id"]),
        trigger_type="API", input_payload={}, status=status,
        cost_amount=cost, cost_currency="USD", cost_is_estimated=estimated,
        pricing_version=pricing_version if cost is not None else None,
        prompt_tokens=tokens - 20 if cost is not None else None,
        completion_tokens=20 if cost is not None else None,
        total_tokens=tokens if cost is not None else None,
    )
    db.add(row)
    db.flush()
    if created_at is not None:
        db.execute(text("UPDATE agent_executions SET created_at = :t WHERE id = :i"),
                   {"t": created_at, "i": row.id})
    db.commit()
    db.refresh(row)
    return row


def _decisions(db: Session, execution_id: str) -> list[RuntimeGovernanceDecision]:
    return list(db.execute(
        select(RuntimeGovernanceDecision)
        .where(RuntimeGovernanceDecision.execution_id == uuid.UUID(execution_id))
        .order_by(RuntimeGovernanceDecision.evaluated_at, RuntimeGovernanceDecision.id)
    ).scalars())


# --------------------------------------------------------------------------- #
# AC-01 — Gate D: real cost, aggregated, honest about estimates
# --------------------------------------------------------------------------- #
def test_ac01_real_cost_aggregates_and_never_mixes_actual_with_estimated(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-01 (Gate D) — the two figures stay apart.

    ``cost_is_estimated`` exists because the platform sometimes cannot meter a
    call. Summing those into one number labelled "spend" would produce a figure
    an operator takes to their finance team, so actual, estimated and *unpriced*
    are three separate numbers all the way out to the wire."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)

    _make_execution(db_session, setup, org, cost=1.25)
    _make_execution(db_session, setup, org, cost=0.75)
    _make_execution(db_session, setup, org, cost=9.99, estimated=True)
    _make_execution(db_session, setup, org, cost=None)  # never priced at all

    summary = CostAggregator(db_session).summary(uuid.UUID(org["organization_id"]))
    assert summary.actual_amount == pytest.approx(2.0)
    assert summary.estimated_amount == pytest.approx(9.99)
    assert summary.unpriced_execution_count == 1
    assert summary.execution_count == 4


@pytest.mark.parametrize("dimension", [
    "agent", "agent_version", "environment", "provider", "model", "project",
    "department", "status",
])
def test_ac01_every_declared_dimension_aggregates(
        client: TestClient, db_session: Session, monkeypatch, dimension) -> None:
    """AC-01 — org / agent / version / environment / provider / model /
    project / department / time are all real breakdowns, not a documented
    intention."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    _make_execution(db_session, setup, org, cost=2.0)

    summary = CostAggregator(db_session).summary(
        uuid.UUID(org["organization_id"]), dimension=dimension)
    assert summary.dimension == dimension
    assert summary.actual_amount == pytest.approx(2.0)
    # project/department are legitimately NULL for an agent with neither, and a
    # bucket keyed on nothing is still a bucket -- the total must reconcile.
    assert sum(b.actual_amount for b in summary.buckets) == pytest.approx(2.0)


def test_ac01_an_unknown_dimension_is_refused_rather_than_ignored(
        client: TestClient, db_session: Session) -> None:
    """A dimension list is bounded on purpose: an open ``group_by`` over
    caller-supplied column names is a SQL-injection surface and an unbounded
    cardinality surface at once."""
    org = _register_org(client)
    r = client.get("/api/v1/cost/summary", headers=org["headers"],
                   params={"dimension": "; DROP TABLE agent_executions"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_ac01_the_cost_read_model_never_touches_the_legacy_estimate() -> None:
    """AC-01 / Ruling #2 — real cost is authoritative. The new read model does
    not import the legacy analytics service at all, so it cannot accidentally
    grow a dependency on placeholder constants."""
    for path in (BACKEND_ROOT / "app" / "finops").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert "analytics" not in (node.module or ""), f"{path.name} reads legacy analytics"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "analytics" not in alias.name, path.name


# --------------------------------------------------------------------------- #
# AC-02 — immutable pricing provenance (§10)
# --------------------------------------------------------------------------- #
def test_ac02_a_past_charge_is_reconstructable_from_its_pricing_version(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-02 / §10 — provenance is reconstructable after the fact."""
    model = _unique_model("prov")
    label = _seed_price(db_session, model, prompt=0.02, completion=0.02)
    _use_transport(monkeypatch, _static_transport(_final_answer(model=model)))
    org = _register_org(client)
    setup = _ready_agent(client, org, model=model)

    execution = _run(client, org, setup["agent"]["id"])
    assert execution["status"] == "SUCCEEDED"

    record = CostAggregator(db_session).provenance(
        uuid.UUID(org["organization_id"]), uuid.UUID(execution["id"]))
    assert record is not None
    assert record["pricing_version"] == label
    assert record["model"] == model
    assert record["provider"] == "OPENAI_COMPATIBLE"
    assert record["calculated_amount"] == pytest.approx(0.0016)  # 80 tokens @ 0.02/1k
    assert record["is_estimated"] is False
    assert record["total_tokens"] == 80


def test_ac02_changing_a_price_does_not_rewrite_a_historical_cost(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-02 / §10 — **the immutability property.**

    A price change today must not alter what a charge from last month says it
    was. That holds because ``PricingService.set_price`` closes the prior row
    and inserts a new one rather than mutating in place, and because the
    execution records the ``pricing_version`` that produced its amount. This
    test would fail loudly if either ever became an in-place update."""
    model = _unique_model("immutable")
    first_label = _seed_price(db_session, model, prompt=0.02, completion=0.02)
    _use_transport(monkeypatch, _static_transport(_final_answer(model=model)))
    org = _register_org(client)
    setup = _ready_agent(client, org, model=model)

    execution = _run(client, org, setup["agent"]["id"])
    before = CostAggregator(db_session).provenance(
        uuid.UUID(org["organization_id"]), uuid.UUID(execution["id"]))
    summary_before = CostAggregator(db_session).summary(uuid.UUID(org["organization_id"]))

    # Ten times the price, from now on.
    second_label = _seed_price(db_session, model, prompt=0.20, completion=0.20,
                               effective_from=datetime.now(timezone.utc))
    assert second_label != first_label

    after = CostAggregator(db_session).provenance(
        uuid.UUID(org["organization_id"]), uuid.UUID(execution["id"]))
    summary_after = CostAggregator(db_session).summary(uuid.UUID(org["organization_id"]))

    assert after["calculated_amount"] == before["calculated_amount"]
    assert after["pricing_version"] == first_label
    assert summary_after.actual_amount == pytest.approx(summary_before.actual_amount)


def test_ac02_the_cost_package_never_writes_a_cost_column() -> None:
    """AC-02 — Phase 5.7a.3 owns cost computation; 4.4 aggregates and governs
    it. Nothing in ``app/finops`` assigns a cost column or calls the pricing
    calculator, asserted over the AST because every module here *discusses*
    pricing at length and a text search could not tell an explanation from an
    assignment."""
    for path in (BACKEND_ROOT / "app" / "finops").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute):
                assert node.attr not in ("calculate_cost", "set_price"), \
                    f"{path.name} computes or changes a price"
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute):
                        assert target.attr not in ("cost_amount", "cost", "pricing_version",
                                                   "cost_is_estimated"), \
                            f"{path.name} writes a cost column"


# --------------------------------------------------------------------------- #
# AC-03 — deterministic anomaly
# --------------------------------------------------------------------------- #
def test_ac03_a_spend_spike_is_surfaced_with_its_own_arithmetic(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-03 — explainable, no ML. Every number that produced the verdict comes
    back with it, so an operator can check it by hand."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    now = datetime.now(timezone.utc)

    for days_ago in (5, 4, 3, 2):
        _make_execution(db_session, setup, org, cost=1.0,
                        created_at=now - timedelta(days=days_ago))
    _make_execution(db_session, setup, org, cost=10.0, created_at=now - timedelta(days=1))

    found = CostAggregator(db_session).anomalies(
        uuid.UUID(org["organization_id"]), threshold_ratio=3.0)
    assert len(found) == 1
    spike = found[0]
    assert spike.amount == pytest.approx(10.0)
    assert spike.baseline == pytest.approx(1.0)
    assert spike.ratio == pytest.approx(10.0)
    assert "10.0x the trailing mean" in spike.reason


def test_ac03_a_ratio_against_almost_nothing_is_not_an_anomaly(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-03 — ``min_baseline`` exists because ratios are meaningless against
    noise: $0.02 after a $0.001 day is a 20x "spike" and means nothing. Same
    reasoning as Phase 3.5's ``INSUFFICIENT_DATA`` floor."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    now = datetime.now(timezone.utc)
    for days_ago in (4, 3, 2):
        _make_execution(db_session, setup, org, cost=0.001,
                        created_at=now - timedelta(days=days_ago))
    _make_execution(db_session, setup, org, cost=0.02, created_at=now - timedelta(days=1))

    aggregator = CostAggregator(db_session)
    org_id = uuid.UUID(org["organization_id"])
    assert aggregator.anomalies(org_id, threshold_ratio=3.0)  # would fire
    assert aggregator.anomalies(org_id, threshold_ratio=3.0, min_baseline=0.01) == ()


def test_ac03_anomaly_detection_uses_no_model() -> None:
    """AC-03 — behavioural anomaly detection is Phase 4.5's, and it is a
    different kind of claim. Nothing here imports a numerical or ML library."""
    source = (BACKEND_ROOT / "app" / "finops" / "aggregation.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        for name in names:
            assert not name.startswith(("numpy", "scipy", "sklearn", "pandas", "torch")), name


# --------------------------------------------------------------------------- #
# AC-04 — budgets: scopes, modes, periods
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("scope_type,uses_id", [
    ("ORGANIZATION", False), ("AGENT", True), ("PROJECT", True),
    ("ENVIRONMENT", False), ("MODEL", False),
])
def test_ac04_every_scope_can_be_created_and_resolves(
        client: TestClient, db_session: Session, monkeypatch, scope_type, uses_id) -> None:
    """AC-04 — all five scopes exist and each actually resolves to an
    execution, rather than being a value the column accepts."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org, model="scoped-model")

    kwargs = {"scope_type": scope_type}
    if scope_type == "AGENT":
        kwargs["scope_id"] = uuid.UUID(setup["agent"]["id"])
    elif scope_type == "PROJECT":
        kwargs["scope_id"] = uuid.uuid4()
    elif scope_type == "ENVIRONMENT":
        kwargs["scope_value"] = "DEVELOPMENT"
    elif scope_type == "MODEL":
        kwargs["scope_value"] = "scoped-model"
    budget = _budget(db_session, org["organization_id"], **kwargs)

    scope = ExecutionScope(
        organization_id=uuid.UUID(org["organization_id"]),
        agent_id=uuid.UUID(setup["agent"]["id"]),
        project_id=kwargs.get("scope_id") if scope_type == "PROJECT" else None,
        environment="DEVELOPMENT", model="scoped-model",
    )
    resolved = BudgetService(db_session).resolve(scope)
    assert budget.id in [b.id for b in resolved], f"{scope_type} budget did not resolve"


@pytest.mark.parametrize("period,expected", [
    ("DAILY", "%Y-%m-%d"), ("MONTHLY", "%Y-%m"),
])
def test_ac04_period_bucketing(period, expected) -> None:
    """AC-04 — daily and monthly ceilings bucket by calendar; an
    execution-level ceiling makes each execution its own bucket, so one
    summation serves all three rather than three code paths."""
    moment = datetime(2026, 8, 28, 14, 30, tzinfo=timezone.utc)
    execution_id = uuid.uuid4()
    assert period_key(period, execution_id, at=moment) == moment.strftime(expected)
    assert period_key("EXECUTION", execution_id, at=moment) == str(execution_id)


def test_ac04_budget_resolution_returns_every_applicable_budget(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-04 — a list, not a winner. Picking one would let a narrow per-agent
    allowance silently switch off the organization ceiling above it."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    _budget(db_session, org["organization_id"], scope_type="ORGANIZATION", name="org wide")
    _budget(db_session, org["organization_id"], scope_type="AGENT",
            scope_id=uuid.UUID(setup["agent"]["id"]), name="agent specific")

    resolved = BudgetService(db_session).resolve(ExecutionScope(
        organization_id=uuid.UUID(org["organization_id"]),
        agent_id=uuid.UUID(setup["agent"]["id"])))
    assert [b.name for b in resolved] == ["agent specific", "org wide"]


def test_ac04_a_scope_that_names_nothing_is_refused(client: TestClient) -> None:
    """A budget scoped to an agent but naming no agent would govern nothing and
    look configured -- the failure Phase 4.3 refused for a misspelled
    constraint key, in a different table."""
    org = _register_org(client)
    r = client.post("/api/v1/budgets", headers=org["headers"], json={
        "name": "nowhere", "scope_type": "AGENT", "mode": "HARD_LIMIT", "limit_amount": 5.0})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "BUDGET_INVALID"


# --------------------------------------------------------------------------- #
# AC-05 — reserve then reconcile
# --------------------------------------------------------------------------- #
def test_ac05_a_reservation_is_held_then_reconciled_to_actual(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-05 — the core arithmetic. A hold of 0.25 that turns out to have cost
    0.10 leaves 0.10 committed, not 0.25: the over-reservation is released by
    the status change itself, because a RECONCILED row counts its actual."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    budget = _budget(db_session, org["organization_id"], limit=1.0, estimate=0.25)
    execution = _make_execution(db_session, setup, org, cost=None, status="RUNNING")

    service = ReservationService(db_session)
    held = service.reserve(budget, execution)
    assert held is not None and held.status == RESERVED
    key = period_key(budget.period, execution.id)
    assert service.state(budget, key=key).committed == pytest.approx(0.25)
    assert service.state(budget, key=key).remaining == pytest.approx(0.75)

    execution.cost_amount = Decimal("0.10")
    db_session.commit()
    BudgetGuard(db_session).settle(execution)
    db_session.commit()

    state = service.state(budget, key=key)
    assert state.reserved == pytest.approx(0.0)
    assert state.spent == pytest.approx(0.10)
    assert state.remaining == pytest.approx(0.90)


def test_ac05_under_reservation_is_charged_at_actual(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-05 — the unflattering direction, tested rather than glossed. An
    execution that cost more than it held is charged what it cost."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    budget = _budget(db_session, org["organization_id"], limit=1.0, estimate=0.10)
    execution = _make_execution(db_session, setup, org, cost=None, status="RUNNING")

    service = ReservationService(db_session)
    service.reserve(budget, execution)
    execution.cost_amount = Decimal("0.40")
    db_session.commit()
    BudgetGuard(db_session).settle(execution)
    db_session.commit()

    state = service.state(budget, key=period_key(budget.period, execution.id))
    assert state.spent == pytest.approx(0.40)
    assert state.remaining == pytest.approx(0.60)


def test_ac05_a_failed_executions_spend_is_still_charged(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-05 — ``cost_amount`` is only written on the success path, so a loop
    that burned tokens and then failed would look free if settlement trusted
    that column alone. It falls back to the transcript, where PricingService
    recorded each turn at the time."""
    model = _unique_model("failspend")
    _seed_price(db_session, model, prompt=0.5, completion=0.5)
    monkeypatch.setattr(settings, "TOOL_LOOP_MAX_ITERATIONS", 1)
    _use_transport(monkeypatch, _static_transport(
        _tool_call("get_weather", {"location": "Paris"}, model=model)))
    org = _register_org(client)
    tool = client.post(f"{RT}/tools", headers=org["headers"], json={
        "name": "get_weather", "display_name": "W", "tool_type": "FUNCTION",
        "description": "d", "input_schema": {"type": "object",
                                             "properties": {"location": {"type": "string"}}}}).json()
    setup = _ready_agent(client, org, model=model, tool_ids=[tool["id"]])
    budget = _budget(db_session, org["organization_id"], limit=10.0, estimate=1.0)

    execution = _run(client, org, setup["agent"]["id"])
    assert execution["status"] == "FAILED"
    row = db_session.get(AgentExecution, uuid.UUID(execution["id"]))
    db_session.refresh(row)
    assert row.cost_amount is None, "cost_amount is only written on the success path"

    state = ReservationService(db_session).state(
        budget, key=period_key(budget.period, uuid.UUID(execution["id"])))
    assert state.reserved == pytest.approx(0.0), "the hold must not still be held"
    assert state.spent > 0, "a failed execution that burned tokens still spent money"


# --------------------------------------------------------------------------- #
# AC-06 — §35 THE BUDGET RACE (Gate E)
# --------------------------------------------------------------------------- #
def test_ac06_concurrent_workers_cannot_collectively_exceed_a_budget(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-06 (Gate E) — **the §35 race proof, on real separate Postgres
    sessions.**

    Twelve workers, each on its own connection, race for a $1.00 budget that
    holds $0.25 per execution. Exactly four can fit. The other eight must be
    refused — not delayed, not silently allowed.

    The mechanism under test is ``SELECT ... FOR UPDATE`` on the budget row:
    every claimant queues in the *database*, so each one reads a balance that
    already includes the winners before it. An in-process lock would pass this
    test in one process and fail in production the moment a second worker
    started, which is why §11 forbids one and why every session here is real.
    """
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    budget = _budget(db_session, org["organization_id"], limit=1.0, estimate=0.25)
    budget_id = budget.id

    executions = [
        _make_execution(db_session, setup, org, cost=None, status="RUNNING").id
        for _ in range(12)
    ]

    def claim(execution_id: uuid.UUID) -> bool:
        db = SessionLocal()
        try:
            own_budget = db.get(Budget, budget_id)
            execution = db.get(AgentExecution, execution_id)
            return ReservationService(db).reserve(own_budget, execution) is not None
        finally:
            db.rollback()
            db.close()

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(claim, executions))

    granted = sum(1 for ok in results if ok)
    assert granted == 4, f"expected exactly 4 of 12 claims to fit $1.00 at $0.25, got {granted}"

    db_session.rollback()
    held = db_session.execute(
        select(func.coalesce(func.sum(BudgetReservation.reserved_amount), 0)).where(
            BudgetReservation.budget_id == budget_id,
            BudgetReservation.status == RESERVED)
    ).scalar_one()
    assert float(held) == pytest.approx(1.0)
    assert float(held) <= 1.0, "reserved must never exceed the limit -- the §35 property"


def test_ac06_the_documented_semantics_are_what_is_guaranteed(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-06 — **what is guaranteed, and what is honestly not.**

    Guaranteed: the sum of *reserved* never exceeds the limit. Not guaranteed:
    that *actual* never does — a model call's cost is unknowable until it
    returns, so an execution admitted with a $0.25 hold that costs $0.40
    overshoots. Claiming otherwise would require knowing a price before paying
    it, and the lie would be discovered in exactly the situation the budget was
    bought for.

    This test asserts the overshoot is real and bounded rather than pretending
    it does not exist, and it is why Phase 4.3's ``min_remaining_cost`` headroom
    rule exists to bound it per execution."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    budget = _budget(db_session, org["organization_id"], limit=1.0, estimate=0.25)
    service = ReservationService(db_session)
    guard = BudgetGuard(db_session)

    executions = []
    for _ in range(4):
        execution = _make_execution(db_session, setup, org, cost=None, status="RUNNING")
        assert service.reserve(budget, execution) is not None
        executions.append(execution)

    key = period_key(budget.period, executions[0].id)
    assert service.state(budget, key=key).reserved == pytest.approx(1.0)

    # Every one overruns its hold by 60%.
    for execution in executions:
        execution.cost_amount = Decimal("0.40")
        db_session.commit()
        guard.settle(execution)
        db_session.commit()

    state = service.state(budget, key=key)
    assert state.spent == pytest.approx(1.60)
    # The overshoot is exactly the sum of (actual - reserved) over admitted
    # executions -- bounded, explainable, and never a surprise.
    assert state.spent - 1.0 == pytest.approx(4 * (0.40 - 0.25))
    # And it closes the gate: nothing further can be admitted.
    blocked = _make_execution(db_session, setup, org, cost=None, status="RUNNING")
    assert service.reserve(budget, blocked) is None


def test_ac06_the_reservation_uses_no_in_process_lock() -> None:
    """AC-06 / §11 — a lock in this process would pass the race test above and
    fail in production the moment a second worker started."""
    for path in (BACKEND_ROOT / "app" / "finops").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in ("threading", "multiprocessing"), path.name
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in ("threading", "multiprocessing"), path.name
    reservations = (BACKEND_ROOT / "app" / "finops" / "reservations.py").read_text(encoding="utf-8")
    assert "with_for_update()" in reservations, "the claim must serialize in the database"


def test_ac06_the_budget_lock_is_not_held_across_the_execution(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-06 / §9 — commit-before-dispatch, applied to money.

    ``reserve`` commits, which releases the ``FOR UPDATE`` before the caller
    does anything slow. Proven from a second real connection: after a
    reservation, the budget row can be locked exclusively by someone else with
    ``NOWAIT``, which would fail immediately if the first session still held
    it."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    budget = _budget(db_session, org["organization_id"], limit=10.0, estimate=0.25)
    execution = _make_execution(db_session, setup, org, cost=None, status="RUNNING")

    main = SessionLocal()
    other = SessionLocal()
    try:
        assert ReservationService(main).reserve(
            main.get(Budget, budget.id), main.get(AgentExecution, execution.id)) is not None
        other.execute(text("SELECT id FROM budgets WHERE id = :i FOR UPDATE NOWAIT"),
                      {"i": str(budget.id)}).first()
    finally:
        main.rollback(); main.close()
        other.rollback(); other.close()


# --------------------------------------------------------------------------- #
# AC-07 / AC-08 — orphans and idempotency
# --------------------------------------------------------------------------- #
def test_ac07_an_abandoned_executions_reservation_is_released(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-07 — a leaked reservation would permanently shrink a tenant's budget
    every time a worker died, turning an availability incident into a financial
    one."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    budget = _budget(db_session, org["organization_id"], limit=1.0, estimate=0.5)
    execution = _make_execution(db_session, setup, org, cost=None, status="RUNNING")

    service = ReservationService(db_session)
    service.reserve(budget, execution)
    key = period_key(budget.period, execution.id)
    assert service.state(budget, key=key).remaining == pytest.approx(0.5)

    # The worker dies. Its execution is eventually marked terminal by recovery,
    # but nothing settled the hold.
    execution.status = "DEAD_LETTERED"
    db_session.commit()

    assert service.sweep_orphans(organization_id=uuid.UUID(org["organization_id"])) == 1
    assert service.state(budget, key=key).remaining == pytest.approx(1.0)


def test_ac07_the_sweeper_does_not_release_a_live_holds(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-07 — deliberately not time-based. A reservation is not orphaned
    because it is old; a long execution legitimately holds one for its whole
    run. Releasing on age would return live holds under exactly the load that
    made them slow."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    budget = _budget(db_session, org["organization_id"], limit=1.0, estimate=0.5)
    execution = _make_execution(db_session, setup, org, cost=None, status="RUNNING")

    service = ReservationService(db_session)
    service.reserve(budget, execution)
    db_session.execute(text("UPDATE budget_reservations SET reserved_at = :t WHERE execution_id = :i"),
                       {"t": datetime.now(timezone.utc) - timedelta(days=30), "i": execution.id})
    db_session.commit()

    assert service.sweep_orphans(organization_id=uuid.UUID(org["organization_id"])) == 0
    assert service.state(
        budget, key=period_key(budget.period, execution.id)).reserved == pytest.approx(0.5)


def test_ac08_a_retried_claim_does_not_double_reserve(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-08 — the partial unique index is the guarantee, not a promise the
    application remembers to keep."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    budget = _budget(db_session, org["organization_id"], limit=1.0, estimate=0.25)
    execution = _make_execution(db_session, setup, org, cost=None, status="RUNNING")

    service = ReservationService(db_session)
    first = service.reserve(budget, execution)
    second = service.reserve(budget, execution)
    assert first is not None and second is not None
    assert first.id == second.id, "a retry must return the existing hold, not a new one"
    key = period_key(budget.period, execution.id)
    assert service.state(budget, key=key).committed == pytest.approx(0.25)


def test_ac08_reconciliation_is_idempotent(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-08 — a retried worker must not charge a budget twice."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    budget = _budget(db_session, org["organization_id"], limit=1.0, estimate=0.25)
    execution = _make_execution(db_session, setup, org, cost=Decimal("0.20"), status="SUCCEEDED")

    service = ReservationService(db_session)
    service.reserve(budget, execution)
    guard = BudgetGuard(db_session)
    guard.settle(execution)
    guard.settle(execution)
    guard.settle(execution)
    db_session.commit()

    state = service.state(budget, key=period_key(budget.period, execution.id))
    assert state.spent == pytest.approx(0.20), "settling three times charged more than once"


def test_ac08_a_released_hold_lets_a_retry_claim_afresh(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-08 — the partial index excludes RELEASED rows precisely so a second
    attempt behaves like the first."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    budget = _budget(db_session, org["organization_id"], limit=1.0, estimate=0.25)
    execution = _make_execution(db_session, setup, org, cost=None, status="RUNNING")

    service = ReservationService(db_session)
    service.reserve(budget, execution)
    service.release(execution.id, reason="attempt failed")
    db_session.commit()

    again = service.reserve(budget, execution)
    assert again is not None and again.status == RESERVED
    live = db_session.execute(
        select(func.count(BudgetReservation.id)).where(
            BudgetReservation.execution_id == execution.id,
            BudgetReservation.status != RELEASED)
    ).scalar_one()
    assert live == 1


# --------------------------------------------------------------------------- #
# AC-09 / AC-10 / AC-11 — the 4.3 seam: one enforcement path
# --------------------------------------------------------------------------- #
def test_ac09_a_hard_limit_budget_stops_the_execution_through_the_43_engine(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-09 — **the seam.** Phase 4.4 refuses to *reserve*; Phase 4.3 decides
    to *stop*. The observable outcome is a stopped execution either way; the
    difference is that there is still only one thing that can stop one."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    budget = _budget(db_session, org["organization_id"], mode="HARD_LIMIT",
                     limit=0.0, estimate=0.25, name="exhausted")

    execution = _run(client, org, setup["agent"]["id"])
    assert execution["status"] == "FAILED"
    assert execution["error_code"] == "BUDGET_EXCEEDED"

    decisions = _decisions(db_session, execution["id"])
    stop = [d for d in decisions if d.decision == "STOP"]
    assert len(stop) == 1
    assert stop[0].reason_code == ReasonCode.BUDGET_EXCEEDED.value
    assert stop[0].checkpoint == Checkpoint.BEFORE_FIRST_MODEL_CALL.value
    assert stop[0].budget_id == budget.id, "the lineage must name the ceiling that decided"
    assert stop[0].policy_id is None, "a budget decision has no governance policy behind it"


def test_ac09_the_finops_package_cannot_stop_an_execution() -> None:
    """AC-09 / AC-16 — **the one-enforcement-path proof for Phase 4.4.**

    Nothing in ``app/finops`` writes an execution status, raises the governance
    stop exception, or calls the kill switch. Budget enforcement reaches an
    execution only as a number the 4.3 engine reads."""
    forbidden_calls = {"_set_execution_status", "activate", "activate_system", "enforce"}
    # Every terminal state an execution can be moved into. Checking the
    # assigned *value* rather than the attribute name is what makes this test
    # precise: `budget_reservations` legitimately has a `status` column of its
    # own (RESERVED/RECONCILED/RELEASED), and a test that could not tell the
    # two apart would have to be weakened until it stopped proving anything.
    execution_states = {
        "QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTERED",
        "TIMED_OUT", "BLOCKED", "DENIED", "REJECTED", "PENDING_APPROVAL", "SUSPENDED",
    }
    for path in (BACKEND_ROOT / "app" / "finops").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute):
                        assert target.attr not in ("cancel_requested", "lifecycle_status",
                                                   "termination_reason"), \
                            f"{path.name} writes execution lifecycle state"
                if isinstance(node.value, ast.Constant) and node.value.value in execution_states:
                    raise AssertionError(
                        f"{path.name} assigns the execution state {node.value.value!r}")
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                assert name not in forbidden_calls, f"{path.name} calls {name}"
            if isinstance(node, ast.Name):
                assert node.id not in ("GovernanceStopped", "KillSwitchService"), \
                    f"{path.name} reaches for an enforcement mechanism"


def test_ac10_an_approval_required_budget_challenges_through_the_existing_funnel(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-10 — a budget past its threshold raises a human obligation through
    the same ``RuntimeApproval`` funnel every other approval on this platform
    uses. No second approval mechanism."""
    from app.models.runtime import RuntimeApproval

    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    # Threshold 1%: the first reservation alone crosses it.
    _budget(db_session, org["organization_id"], mode="APPROVAL_REQUIRED",
            limit=10.0, estimate=1.0, threshold=1, name="needs approval")

    execution = _run(client, org, setup["agent"]["id"])
    assert execution["status"] == "PENDING_APPROVAL"
    assert execution["decision"] == "REQUIRE_APPROVAL"

    approvals = list(db_session.execute(
        select(RuntimeApproval).where(
            RuntimeApproval.execution_id == uuid.UUID(execution["id"]))).scalars())
    assert len(approvals) == 1
    assert approvals[0].status == "PENDING"

    challenge = _decisions(db_session, execution["id"])[-1]
    assert challenge.decision == "CHALLENGE"
    assert challenge.reason_code == ReasonCode.BUDGET_APPROVAL_REQUIRED.value


@pytest.mark.parametrize("mode", ["INFORMATIONAL", "WARNING"])
def test_ac11_informational_and_warning_budgets_never_block(
        client: TestClient, db_session: Session, monkeypatch, mode) -> None:
    """AC-11 — an exhausted INFORMATIONAL or WARNING budget observes and
    signals. It cannot block, and not because a branch says so: these modes
    take no reservation and never populate a checkpoint context, so there is no
    path from them to the engine at all."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    _budget(db_session, org["organization_id"], mode=mode, limit=0.0,
            estimate=1.0, threshold=1, name=f"{mode} budget")

    execution = _run(client, org, setup["agent"]["id"])
    assert execution["status"] == "SUCCEEDED", (
        f"a {mode} budget must never block; got {execution['status']} "
        f"{execution.get('error_code')} {execution.get('error_message')}")
    assert execution["error_code"] is None

    reservations = db_session.execute(
        select(func.count(BudgetReservation.id)).where(
            BudgetReservation.execution_id == uuid.UUID(execution["id"]))).scalar_one()
    assert reservations == 0, "a non-enforcing mode must not hold budget"


def test_ac11_a_threshold_crossing_is_recorded_as_a_signal(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-11 — a durable audit signal, not a notification. Slack and email
    delivery are explicitly out of scope, and an alerting system that quietly
    did half of itself would be worse than one that is honestly absent."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    _budget(db_session, org["organization_id"], mode="WARNING", limit=1.0,
            estimate=None, threshold=1, name="noisy")
    _make_execution(db_session, setup, org, cost=Decimal("0.90"))

    execution = _run(client, org, setup["agent"]["id"])
    assert execution["status"] == "SUCCEEDED"

    events = list(db_session.execute(
        select(AuthorizationAudit).where(
            AuthorizationAudit.organization_id == uuid.UUID(org["organization_id"]),
            AuthorizationAudit.event_type == "RUNTIME_BUDGET_THRESHOLD_REACHED")).scalars())
    assert events, "crossing a WARNING threshold must leave a durable record"
    assert set(events[0].meta) <= {
        "budget_id", "budget_name", "mode", "period_key", "utilization_percent",
        "threshold_percent"}


def test_ac16_the_43_one_enforcement_path_property_still_holds() -> None:
    """AC-16 — Phase 4.3's structural guarantee survives this phase: the
    orchestrator still contains no cap comparison of its own, and budgets
    reached the engine as a constraint tier rather than as a second path."""
    from app.runtime.governance import constraints as constraints_module

    # 4.3's exact cap ordering is untouched -- the budget tier was added
    # *beside* BUILTIN_CAPS precisely so this assertion did not have to be
    # weakened to make room.
    assert [c.__name__ for c in constraints_module.BUILTIN_CAPS[
        Checkpoint.BEFORE_NEXT_ITERATION]] == [
        "_cap_wall_clock", "_cap_token_budget", "_cap_max_iterations"]
    assert [c.__name__ for c in constraints_module.BUDGET_CONSTRAINTS[
        Checkpoint.BEFORE_FIRST_MODEL_CALL]] == ["_budget_constraint"]


# --------------------------------------------------------------------------- #
# AC-12 — legacy deprecation in place
# --------------------------------------------------------------------------- #
def test_ac12_the_legacy_cost_endpoint_still_works_and_says_it_is_deprecated(
        client: TestClient) -> None:
    """AC-12 — deprecated in place: still working, now marked, not rewired.

    The marker is in the response body rather than only a header or a doc note,
    because the consumers most in need of the warning are the ones reading
    ``total`` out of a JSON body."""
    org = _register_org(client)
    r = client.get(LEGACY_COST_PATH, headers=org["headers"])
    assert r.status_code == 200, r.text
    body = r.json()

    assert "total" in body and "items" in body, "the legacy shape must not change"
    assert body["estimated"] is True
    notice = body["deprecation"]
    assert notice["deprecated"] is True
    assert notice["replacement"] == "GET /api/v1/cost/summary"
    assert "agent_actions" in notice["reason"]


def test_ac12_the_legacy_estimate_and_the_real_cost_are_different_numbers(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-12 — the reason the legacy endpoint is deprecated rather than
    trusted: it reports a figure derived from ``agent_actions`` row counts,
    which has no relationship to what any model call cost. A tenant with real
    executions and no agent actions gets real spend from one endpoint and zero
    from the other."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    _make_execution(db_session, setup, org, cost=Decimal("42.00"))

    legacy = client.get(LEGACY_COST_PATH, headers=org["headers"]).json()
    real = client.get("/api/v1/cost/summary", headers=org["headers"]).json()

    assert real["actual_amount"] == pytest.approx(42.0)
    # The legacy figure is not zero -- it is derived from audit-row and
    # approval counts that any organization accrues just by existing -- but it
    # is unrelated to the $42 that was actually spent, which is the point.
    assert legacy["total"] != pytest.approx(real["actual_amount"])
    assert legacy["total"] < 1.0, "the legacy estimate knows nothing of real execution cost"


def test_ac12_the_legacy_service_was_not_rewired() -> None:
    """AC-12 — the Phase-3 dashboard that consumes it expects six synthetic
    categories (human review, policy evaluation, storage) that
    ``agent_executions`` knows nothing about. Pointing it at real data would
    have silently redefined every number on a dashboard this phase does not
    own. It still reads what it always read."""
    source = (BACKEND_ROOT / "app" / "services" / "analytics_service.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)
    function = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "cost_analytics")
    names = {n.id for n in ast.walk(function) if isinstance(n, ast.Name)}
    assert "AgentAction" in names, "the legacy estimate still reads agent_actions"
    assert "AgentExecution" not in names, "the legacy endpoint must not have been rewired"


# --------------------------------------------------------------------------- #
# AC-13 / AC-15 — isolation, authorization, idempotency
# --------------------------------------------------------------------------- #
def test_ac13_cost_data_never_crosses_a_tenant_boundary(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-13 — financial data is the last thing that should leak."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    owner = _register_org(client, "Owner Org")
    setup = _ready_agent(client, owner)
    _make_execution(db_session, setup, owner, cost=Decimal("99.00"))

    stranger = _register_org(client, "Stranger Org")
    theirs = client.get("/api/v1/cost/summary", headers=stranger["headers"]).json()
    assert theirs["actual_amount"] == pytest.approx(0.0)
    assert theirs["execution_count"] == 0

    mine = client.get("/api/v1/cost/summary", headers=owner["headers"]).json()
    assert mine["actual_amount"] == pytest.approx(99.0)


def test_ac13_a_cross_tenant_budget_is_not_found_rather_than_forbidden(
        client: TestClient) -> None:
    """AC-13 / §34 — distinguishing 403 from 404 would confirm the budget
    exists, and the existence of a financial record is itself information."""
    owner = _register_org(client, "Owner Org")
    created = client.post("/api/v1/budgets", headers=owner["headers"], json={
        "name": "private", "scope_type": "ORGANIZATION", "mode": "HARD_LIMIT",
        "limit_amount": 5.0})
    assert created.status_code == 201, created.text
    budget_id = created.json()["id"]

    stranger = _register_org(client, "Stranger Org")
    seen = client.get(f"/api/v1/budgets/{budget_id}", headers=stranger["headers"])
    assert seen.status_code == 404
    assert seen.json()["error"]["code"] == "BUDGET_NOT_FOUND"

    missing = client.get(f"/api/v1/budgets/{uuid.uuid4()}", headers=stranger["headers"])
    assert missing.json()["error"] == seen.json()["error"]

    listed = client.get("/api/v1/budgets", headers=stranger["headers"]).json()
    assert budget_id not in [b["id"] for b in listed]


def test_ac13_a_cross_tenant_utilization_read_is_rejected(client: TestClient) -> None:
    owner = _register_org(client, "Owner Org")
    budget_id = client.post("/api/v1/budgets", headers=owner["headers"], json={
        "name": "b", "scope_type": "ORGANIZATION", "mode": "HARD_LIMIT",
        "limit_amount": 5.0}).json()["id"]
    stranger = _register_org(client, "Stranger Org")
    assert client.get(f"/api/v1/budgets/{budget_id}/utilization",
                      headers=stranger["headers"]).status_code == 404


def test_ac15_cost_and_budget_endpoints_enforce_their_permissions(
        client: TestClient) -> None:
    """AC-15 — and the permissions exist in the catalog rather than being
    invented at the route."""
    from app.services.rbac_service import PERMISSION_CATALOG

    assert "runtime.cost.view" in PERMISSION_CATALOG      # pre-existing, reused
    assert "runtime.budget.view" in PERMISSION_CATALOG
    assert "runtime.budget.manage" in PERMISSION_CATALOG

    for path in ("/api/v1/cost/summary", "/api/v1/budgets"):
        assert client.get(path).status_code in (401, 403)
    assert client.post("/api/v1/budgets", json={
        "name": "x", "scope_type": "ORGANIZATION", "limit_amount": 1.0}).status_code in (401, 403)


def test_ac15_budget_creation_is_idempotent(client: TestClient) -> None:
    """AC-15 — a retried create must not leave two ceilings where the operator
    asked for one: both would evaluate, and the tighter would fire with no
    obvious explanation."""
    org = _register_org(client)
    key = str(uuid.uuid4())
    body = {"name": "once", "scope_type": "ORGANIZATION", "mode": "HARD_LIMIT",
            "limit_amount": 3.0}
    first = client.post("/api/v1/budgets", headers={**org["headers"], "Idempotency-Key": key},
                        json=body)
    second = client.post("/api/v1/budgets", headers={**org["headers"], "Idempotency-Key": key},
                         json=body)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


def test_ac15_deleting_a_budget_disables_it_rather_than_erasing_its_ledger(
        client: TestClient, db_session: Session) -> None:
    """A budget's reservations are the record of money actually spent under it;
    a cascading delete would erase that."""
    org = _register_org(client)
    budget_id = client.post("/api/v1/budgets", headers=org["headers"], json={
        "name": "temp", "scope_type": "ORGANIZATION", "mode": "HARD_LIMIT",
        "limit_amount": 1.0}).json()["id"]

    assert client.delete(f"/api/v1/budgets/{budget_id}",
                         headers=org["headers"]).status_code == 204
    row = db_session.get(Budget, uuid.UUID(budget_id))
    assert row is not None and row.enabled is False


def test_ac13_utilization_reports_spent_and_reserved_separately(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-04/AC-13 — two numbers because they answer different questions: one
    is money that is gone, the other money that might still be released."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    budget = _budget(db_session, org["organization_id"], limit=2.0, estimate=0.5)

    spent = _make_execution(db_session, setup, org, cost=Decimal("0.30"), status="SUCCEEDED")
    ReservationService(db_session).reserve(budget, spent)
    BudgetGuard(db_session).settle(spent)
    db_session.commit()

    held = _make_execution(db_session, setup, org, cost=None, status="RUNNING")
    ReservationService(db_session).reserve(budget, held)

    body = client.get(f"/api/v1/budgets/{budget.id}/utilization",
                      headers=org["headers"]).json()
    assert body["spent"] == pytest.approx(0.30)
    assert body["reserved"] == pytest.approx(0.50)
    assert body["remaining"] == pytest.approx(1.20)


# --------------------------------------------------------------------------- #
# AC-14 — bounded and indexed
# --------------------------------------------------------------------------- #
def test_ac14_the_cost_summary_reaches_its_rows_through_an_index(
        client: TestClient, db_session: Session) -> None:
    """AC-14 — no sequential scan of ``agent_executions``.

    The tenant predicate leads the plan, which is both the isolation property
    and the performance one: a query that cannot scan another tenant's rows
    also cannot scan the whole table."""
    busiest = db_session.execute(
        select(AgentExecution.organization_id, func.count(AgentExecution.id))
        .group_by(AgentExecution.organization_id)
        .order_by(func.count(AgentExecution.id).desc()).limit(1)
    ).first()
    assert busiest is not None and busiest[1] >= 50, "no tenant with enough rows to be meaningful"

    plan = "\n".join(row[0] for row in db_session.execute(text(
        "EXPLAIN (ANALYZE, BUFFERS) "
        "SELECT coalesce(sum(cost_amount),0), count(id) FROM agent_executions "
        "WHERE organization_id = :org AND created_at >= now() - interval '30 days'"
    ), {"org": busiest[0]}))

    assert "Seq Scan on agent_executions" not in plan, plan
    assert "ix_agent_executions_org" in plan, plan


def test_ac14_an_absent_time_range_does_not_mean_everything(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-14 — the default 30-day window is the bound. An aggregation over a
    tenant's whole history is inherently O(rows the tenant owns) and no index
    changes that; the window is what keeps the default query small."""
    _use_transport(monkeypatch, _static_transport(_final_answer()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    now = datetime.now(timezone.utc)
    _make_execution(db_session, setup, org, cost=Decimal("5.00"),
                    created_at=now - timedelta(days=2))
    _make_execution(db_session, setup, org, cost=Decimal("7.00"),
                    created_at=now - timedelta(days=200))

    aggregator = CostAggregator(db_session)
    org_id = uuid.UUID(org["organization_id"])
    assert aggregator.summary(org_id).actual_amount == pytest.approx(5.0)
    wide = CostFilters(started_after=now - timedelta(days=400))
    assert aggregator.summary(org_id, filters=wide).actual_amount == pytest.approx(12.0)


# --------------------------------------------------------------------------- #
# AC-19 — no placeholders
# --------------------------------------------------------------------------- #
def test_ac19_no_todo_fixme_or_skipped_work_in_this_phase() -> None:
    """AC-19. Markers are concatenated because this file is one of the files
    being scanned."""
    markers = ("TO" + "DO", "FIX" + "ME", "NotImplemented" + "Error",
               "pytest.mark." + "skip", "pytest.mark." + "xfail")
    paths = list((BACKEND_ROOT / "app" / "finops").rglob("*.py"))
    paths.append(BACKEND_ROOT / "migrations" / "versions" / "0048_cost_governance.py")
    paths.append(Path(__file__))
    for path in paths:
        source = path.read_text(encoding="utf-8")
        for marker in markers:
            assert marker not in source, f"{path.name} contains {marker}"


def test_ac19_chargeback_was_not_built() -> None:
    """Showback now; chargeback is future work (§4.4). Allocation views exist;
    nothing bills anyone."""
    for path in (BACKEND_ROOT / "app" / "finops").rglob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        assert "invoice" not in source, f"{path.name} looks like chargeback"
        assert "chargeback" not in source.replace("chargeback is", "").replace(
            "chargeback deferred", "").replace("chargeback)", ""), path.name
