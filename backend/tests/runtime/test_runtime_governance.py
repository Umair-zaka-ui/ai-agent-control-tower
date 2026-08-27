"""Phase 4.3 tests — the Runtime Governance Enforcement Engine.

This phase modifies the execution path, so the tests are weighted accordingly:
the proofs that matter most are not "the new feature works" but **"the loop
still behaves exactly as it did"** (AC-15), **"there is only one enforcement
path"** (AC-02), **"the M1 deadlock cannot recur"** (AC-10) and **"governance
fails closed while telemetry fails open"** (AC-06/AC-07).

Conventions match ``test_tool_loop.py``: every model turn replays an inline
body through ``httpx.MockTransport`` (never a socket); no test waits on a real
clock; pricing is seeded against a model name unique to each test so no test
can leave a global price behind for another to trip over.
"""

from __future__ import annotations

import ast
import json as jsonlib
import statistics
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.rbac import AuthorizationAudit
from app.models.agent import Agent
from app.models.runtime import (
    AgentExecution,
    ExecutionMessage,
    RuntimeApproval,
    RuntimeGovernanceDecision,
    RuntimeGovernancePolicy,
    Tool,
    ToolCall,
)
from app.runtime import services as services_module
from app.runtime.governance import constraints as constraints_module
from app.runtime.governance import engine as engine_module
from app.runtime.governance.contract import (
    Checkpoint,
    CheckpointContext,
    Decision,
    GovernanceChallenged,
    GovernanceStopped,
    ReasonCode,
    StopAction,
)
from app.runtime.governance.engine import RuntimeGovernanceEngine
from app.runtime.governance.policies import GovernancePolicyService
from app.runtime.providers.openai_compatible import OpenAICompatibleProvider
from app.runtime.services import KillSwitchService, PricingService
from app.runtime.tools import egress_guard

PASSWORD = "T3st!Passw0rd#Ok"
RT = "/api/v1/runtime"
BACKEND_ROOT = Path(__file__).resolve().parents[2]

# The measured ceiling for one checkpoint evaluation (AC-16). Generous
# relative to what is actually observed (see the test's own report) because a
# CI box under load is not a benchmark rig -- the assertion exists to catch a
# checkpoint that started issuing a query per constraint, not to police
# microseconds.
CHECKPOINT_BUDGET_MS = 25.0


# --------------------------------------------------------------------------- #
# Transport / fixture helpers (local copies of test_tool_loop.py's convention)
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _patch_default_resolver(monkeypatch):
    monkeypatch.setattr(egress_guard, "_default_resolve", lambda host: ["127.0.0.1"])


def _use_transport(monkeypatch, transport: httpx.MockTransport) -> None:
    monkeypatch.setattr(OpenAICompatibleProvider, "_build_default_transport", lambda self: transport)


def _sequenced_transport(*responses):
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        index = min(state["n"], len(responses) - 1)
        state["n"] += 1
        return httpx.Response(200, json=responses[index], request=request)

    return httpx.MockTransport(handler)


def _tool_call_response(pairs, *, model: str = "llama3", tokens: int = 50) -> dict:
    return {
        "id": "chatcmpl-gov", "object": "chat.completion", "created": 1718000000, "model": model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant", "content": None,
                "tool_calls": [
                    {"id": call_id, "type": "function",
                     "function": {"name": name, "arguments": jsonlib.dumps(args)}}
                    for call_id, name, args in pairs
                ],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": tokens - 10, "completion_tokens": 10, "total_tokens": tokens},
    }


def _final_answer_response(content: str = "Final answer.", *, model: str = "llama3") -> dict:
    return {
        "id": "chatcmpl-gov-final", "object": "chat.completion", "created": 1718000099, "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 60, "completion_tokens": 20, "total_tokens": 80},
    }


# --------------------------------------------------------------------------- #
# Org / agent / execution helpers
# --------------------------------------------------------------------------- #
def _register_org(client: TestClient, org_name: str = "Governance Org") -> dict:
    email = f"gov_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": org_name, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"]}


def _register_agent(client: TestClient, admin: dict) -> dict:
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Gov Agent {uuid.uuid4().hex[:6]}", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "description": "A test agent.", "business_purpose": "Exercise runtime governance.",
        "owner_type": "USER", "owner_id": admin["user_id"], "technical_owner_id": admin["user_id"],
        "compliance_owner_id": admin["user_id"],
        "definition": {"name": "Definition", "framework": "CUSTOM", "entrypoint_type": "FUNCTION",
                       "entrypoint": "agents.handler:run"},
    })
    assert r.status_code == 201, r.text
    return r.json()


def _activate_agent(client: TestClient, admin: dict, agent_id: str) -> None:
    for step in ("register", "validate"):
        assert client.post(f"{RT}/agents/{agent_id}/{step}", headers=admin["headers"]).status_code == 200
    assert client.post(f"{RT}/agents/{agent_id}/identity/create-and-associate",
                       headers=admin["headers"],
                       json={"client_id": f"agent-identity-{uuid.uuid4().hex[:10]}"}).status_code == 200
    for step in ("submit-for-approval", "approve", "activate"):
        assert client.post(f"{RT}/agents/{agent_id}/{step}", headers=admin["headers"]).status_code == 200


def _create_function_tool(client: TestClient, admin: dict, *, name: str = "get_weather",
                          data_classification: str | None = None) -> dict:
    body = {
        "name": name, "display_name": "Get Weather", "tool_type": "FUNCTION",
        "description": "Look up the current weather for a location.",
        "input_schema": {"type": "object", "required": ["location"],
                         "properties": {"location": {"type": "string"}}},
    }
    if data_classification is not None:
        body["data_classification"] = data_classification
    r = client.post(f"{RT}/tools", headers=admin["headers"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _ready_agent(client: TestClient, admin: dict, *, tool_ids: list[str] | None = None,
                 model: str = "llama3") -> dict:
    agent = _register_agent(client, admin)
    _activate_agent(client, admin, agent["id"])
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
    r = client.post(f"{RT}/deployments", headers=admin["headers"], params={"agent_id": agent["id"]},
                    json={"agent_version_id": version["id"], "environment": "DEVELOPMENT"})
    assert r.status_code == 201, r.text
    deployment = r.json()
    assert client.post(f"{RT}/deployments/{deployment['id']}/deploy",
                       headers=admin["headers"]).status_code == 200
    return {"agent": agent, "version": version, "deployment": deployment}


def _run_execution(client: TestClient, admin: dict, agent_id: str) -> dict:
    r = client.post(f"{RT}/executions", headers=admin["headers"], json={
        "agent_id": agent_id, "input_payload": {"question": "What's the weather?"},
    })
    assert r.status_code == 201, r.text
    return r.json()


def _policy(db: Session, organization_id: str, constraints: dict, *, mandatory: bool = False,
            agent_id: str | None = None, name: str = "test policy") -> RuntimeGovernancePolicy:
    """Writes a governance policy straight to the database and commits, so the
    execution path (which runs on its own session) sees it."""
    row = RuntimeGovernancePolicy(
        organization_id=uuid.UUID(organization_id), name=name, constraints=constraints,
        mandatory=mandatory, enabled=True,
        agent_id=uuid.UUID(agent_id) if agent_id else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _decisions(db: Session, execution_id: str) -> list[RuntimeGovernanceDecision]:
    return list(db.execute(
        select(RuntimeGovernanceDecision)
        .where(RuntimeGovernanceDecision.execution_id == uuid.UUID(execution_id))
        .order_by(RuntimeGovernanceDecision.evaluated_at, RuntimeGovernanceDecision.id)
    ).scalars())


def _unique_model(prefix: str = "gov") -> str:
    """A model name no other test uses, so seeding a price for it cannot leak
    into another test's cost expectations. ``model_pricing`` has no
    organization column -- a row written for ``llama3`` would be global and
    permanent, exactly the shared-state hazard this directory's signing-key
    fixture exists to avoid."""
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _seed_price(db: Session, model: str, *, prompt_per_1k: float, completion_per_1k: float) -> None:
    PricingService(db).set_price(
        provider="OPENAI_COMPATIBLE", model=model, prompt_cost_per_1k=prompt_per_1k,
        completion_cost_per_1k=completion_per_1k, pricing_version=f"test-{uuid.uuid4().hex[:6]}",
        effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    db.commit()


def _ctx(execution: AgentExecution, **overrides) -> CheckpointContext:
    fields = dict(
        execution_id=execution.id, organization_id=execution.organization_id,
        agent_id=execution.agent_id, iteration=1, completed_iterations=0,
        elapsed_seconds=0.0, max_iterations=10, max_wall_clock_seconds=120.0,
        max_total_tokens=50_000, trace_id=str(execution.id),
    )
    fields.update(overrides)
    return CheckpointContext(**fields)


def _engine(db: Session, execution: AgentExecution) -> RuntimeGovernanceEngine:
    return RuntimeGovernanceEngine(db).bind(execution, environment_id=None,
                                            agent_id=execution.agent_id)


def _an_execution(client: TestClient, db_session: Session, monkeypatch) -> AgentExecution:
    """One completed execution, used as a real, committed row for the unit
    tests that drive the engine directly."""
    _use_transport(monkeypatch, _sequenced_transport(_final_answer_response()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    execution = _run_execution(client, org, setup["agent"]["id"])
    row = db_session.get(AgentExecution, uuid.UUID(execution["id"]))
    return row


# --------------------------------------------------------------------------- #
# AC-01 — one engine, four decisions, six checkpoints
# --------------------------------------------------------------------------- #
def test_ac01_engine_returns_a_structured_decision_at_every_checkpoint(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-01 — every one of the six checkpoints is a real insertion point into
    the *same* ``evaluate()``, and every one returns a structured decision
    with a reason code, not a bare boolean."""
    execution = _an_execution(client, db_session, monkeypatch)
    engine = _engine(db_session, execution)

    assert len(list(Checkpoint)) == 6
    for checkpoint in Checkpoint:
        decision = engine.evaluate(checkpoint, _ctx(execution))
        assert decision.checkpoint is checkpoint
        assert decision.decision is Decision.ALLOW
        assert decision.reason_code is ReasonCode.ALLOWED
        assert decision.reason


def test_ac01_all_four_decision_kinds_are_producible(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-01 — ALLOW / DENY / CHALLENGE / STOP are all reachable, each from a
    real constraint rather than a constructed object."""
    execution = _an_execution(client, db_session, monkeypatch)
    org_id = str(execution.organization_id)

    # STOP -- a built-in cap, no policy involved.
    stop = _engine(db_session, execution).evaluate(
        Checkpoint.BEFORE_NEXT_ITERATION, _ctx(execution, iteration=11, max_iterations=10))
    assert stop.decision is Decision.STOP
    assert stop.reason_code is ReasonCode.LOOP_MAX_ITERATIONS

    _policy(db_session, org_id, {"restricted_tools": ["dangerous"]}, name="deny policy")
    deny = _engine(db_session, execution).evaluate(
        Checkpoint.BEFORE_TOOL_EXECUTION, _ctx(execution, tool_name="dangerous"))
    assert deny.decision is Decision.DENY
    assert deny.reason_code is ReasonCode.RESTRICTED_TOOL_CLASS

    _policy(db_session, org_id, {"high_risk_actions": ["send_email"]}, name="challenge policy")
    challenge = _engine(db_session, execution).evaluate(
        Checkpoint.BEFORE_TOOL_EXECUTION, _ctx(execution, tool_name="send_email"))
    assert challenge.decision is Decision.CHALLENGE
    assert challenge.obligation and challenge.obligation["type"] == "APPROVAL"

    allowed = _engine(db_session, execution).evaluate(
        Checkpoint.BEFORE_TOOL_EXECUTION, _ctx(execution, tool_name="harmless"))
    assert allowed.decision is Decision.ALLOW


# --------------------------------------------------------------------------- #
# AC-02 — ONE ENFORCEMENT PATH (the phase's central structural claim)
# --------------------------------------------------------------------------- #
_LOOP_SOURCE = (BACKEND_ROOT / "app" / "runtime" / "services.py").read_text(encoding="utf-8")


def _orchestrator_ast() -> ast.ClassDef:
    tree = ast.parse(_LOOP_SOURCE)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ToolLoopOrchestrator":
            return node
    raise AssertionError("ToolLoopOrchestrator not found")


def test_ac02_the_loop_contains_no_cap_comparison_of_its_own() -> None:
    """AC-02 — **the one-path proof.**

    Before this phase ``ToolLoopOrchestrator.run`` compared against four caps
    inline. Those comparisons are gone: the orchestrator no longer names
    ``TOOL_LOOP_MAX_WALL_CLOCK_SECONDS``, ``TOOL_LOOP_MAX_TOTAL_TOKENS`` or
    ``max_iterations`` in any comparison, and never raises
    ``TOOL_LOOP_LIMIT_EXCEEDED`` itself.

    Asserted over the AST rather than by grep so that a comparison
    reintroduced in a helper method, a comprehension or a nested function is
    caught too — the failure mode this guards against is not someone restoring
    the old lines verbatim, it is someone adding "just one quick check" beside
    the engine."""
    orchestrator = _orchestrator_ast()
    forbidden_names = {"TOOL_LOOP_MAX_WALL_CLOCK_SECONDS", "TOOL_LOOP_MAX_TOTAL_TOKENS"}

    for node in ast.walk(orchestrator):
        if isinstance(node, ast.Compare):
            names = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
            names |= {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            overlap = names & forbidden_names
            assert not overlap, (
                f"ToolLoopOrchestrator compares against {overlap} directly; the loop-safety "
                "caps must be reached only through RuntimeGovernanceEngine (AC-02)")
        if isinstance(node, ast.Attribute) and node.attr == "TOOL_LOOP_LIMIT_EXCEEDED":
            raise AssertionError(
                "ToolLoopOrchestrator names TOOL_LOOP_LIMIT_EXCEEDED directly; a cap breach "
                "must reach the caller through the engine's decision (AC-02)")


def test_ac02_every_checkpoint_goes_through_the_single_enforce_call() -> None:
    """AC-02 — the six sites all call one local ``check`` helper, and that
    helper's only action is ``governance.enforce``. There is no second way to
    reach a decision, and no way to reach one without recording it."""
    orchestrator = _orchestrator_ast()
    run = next(n for n in orchestrator.body if isinstance(n, ast.FunctionDef) and n.name == "run")
    check = next(n for n in ast.walk(run) if isinstance(n, ast.FunctionDef) and n.name == "check")

    calls_in_check = {
        node.func.attr for node in ast.walk(check)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert calls_in_check <= {"enforce", "update", "monotonic", "get"}, calls_in_check
    assert "enforce" in calls_in_check

    checkpoints_used = {
        node.attr for node in ast.walk(run)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        and node.value.id == "Checkpoint"
    }
    assert checkpoints_used == {c.name for c in Checkpoint}, (
        f"the loop reaches {checkpoints_used}, not all six checkpoints")


def test_ac02_no_second_enforcement_module_exists() -> None:
    """AC-02 — the caps are defined in exactly one place. If a second module
    ever grows its own ``TOOL_LOOP_MAX_*`` comparison, this fails."""
    app_root = BACKEND_ROOT / "app"
    offenders = []
    for path in app_root.rglob("*.py"):
        if path.parts[-3:-1] == ("runtime", "governance"):
            continue  # the one legitimate home
        source = path.read_text(encoding="utf-8")
        if "TOOL_LOOP_MAX_TOTAL_TOKENS" in source or "TOOL_LOOP_MAX_WALL_CLOCK_SECONDS" in source:
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Compare):
                    names = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
                    if names & {"TOOL_LOOP_MAX_TOTAL_TOKENS", "TOOL_LOOP_MAX_WALL_CLOCK_SECONDS"}:
                        offenders.append(str(path.relative_to(app_root)))
    assert not offenders, f"a second enforcement path compares the caps: {offenders}"


# --------------------------------------------------------------------------- #
# AC-15 — the four caps still terminate identically (through the engine)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "setting_name,setting_value,expected_reason",
    [
        ("TOOL_LOOP_MAX_ITERATIONS", 2, "MAX_ITERATIONS"),
        ("TOOL_LOOP_MAX_TOTAL_TOKENS", 10, "TOKEN_BUDGET"),
    ],
)
def test_ac15_the_existing_caps_terminate_with_their_original_reasons(
        client: TestClient, db_session: Session, monkeypatch,
        setting_name, setting_value, expected_reason) -> None:
    """AC-15 — behaviour preservation, the thing that matters most in a phase
    that touches the execution path. Same ``termination_reason``, same
    ``error_code``, same terminal status as before 4.3 — now decided by the
    engine."""
    monkeypatch.setattr(settings, setting_name, setting_value)
    responses = [_tool_call_response([(f"c{i}", "get_weather", {"location": f"City {i}"})])
                 for i in range(6)]
    _use_transport(monkeypatch, _sequenced_transport(*responses))
    org = _register_org(client)
    tool = _create_function_tool(client, org)
    setup = _ready_agent(client, org, tool_ids=[tool["id"]])

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["status"] == "FAILED"
    assert execution["error_code"] == "TOOL_LOOP_LIMIT_EXCEEDED"
    assert execution["termination_reason"] == expected_reason


def test_ac15_repeated_call_still_terminates_before_the_duplicate_runs(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-15 — ``REPEATED_CALL`` still fires *before* the duplicate is issued.
    A cap that has become a governance constraint must not have become a
    governance constraint evaluated one step too late."""
    call = _tool_call_response([("c1", "get_weather", {"location": "Paris"})])
    _use_transport(monkeypatch, _sequenced_transport(call, call))
    org = _register_org(client)
    tool = _create_function_tool(client, org)
    setup = _ready_agent(client, org, tool_ids=[tool["id"]])

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["termination_reason"] == "REPEATED_CALL"
    assert execution["error_code"] == "TOOL_LOOP_LIMIT_EXCEEDED"

    rows = list(db_session.execute(
        select(ToolCall).where(ToolCall.execution_id == uuid.UUID(execution["id"]))).scalars())
    assert len(rows) == 1, "the repeated call must never have been executed"


def test_ac15_unbound_tool_still_denied_with_tool_denied(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-15 — the frozen-snapshot scope check keeps its original outcome."""
    _use_transport(monkeypatch, _sequenced_transport(
        _tool_call_response([("c1", "not_a_real_tool", {"x": 1})])))
    org = _register_org(client)
    tool = _create_function_tool(client, org)
    setup = _ready_agent(client, org, tool_ids=[tool["id"]])

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["error_code"] == "TOOL_NOT_BOUND_TO_VERSION"
    assert execution["termination_reason"] == "TOOL_DENIED"


def test_ac15_a_governed_execution_with_no_policy_behaves_exactly_as_before(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-15 — the common case: no policy configured. The engine runs at every
    checkpoint and changes nothing. A tenant that configures nothing keeps the
    execution behaviour Phase 5.6a.3 gave them, which is what makes shipping an
    engine on this path survivable."""
    _use_transport(monkeypatch, _sequenced_transport(_final_answer_response()))
    org = _register_org(client)
    setup = _ready_agent(client, org)

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["status"] == "SUCCEEDED"
    assert execution["termination_reason"] == "COMPLETED"
    assert execution["loop_iterations"] == 1
    assert execution["error_code"] is None


def test_ac15_cap_evaluation_order_matches_the_pre_43_loop() -> None:
    """AC-15 — the corner case a refactor silently inverts.

    When wall-clock and token budget could both fire on the same turn, the
    pre-4.3 loop reported ``WALL_CLOCK``, because the bottom-of-body check
    tested it first. Folding both into ``BEFORE_NEXT_ITERATION`` preserves
    that only if the order is preserved, so the order is asserted rather than
    trusted."""
    names = [cap.__name__ for cap in constraints_module.BUILTIN_CAPS[Checkpoint.BEFORE_NEXT_ITERATION]]
    assert names == ["_cap_wall_clock", "_cap_token_budget", "_cap_max_iterations"]
    first = [cap.__name__ for cap in
             constraints_module.BUILTIN_CAPS[Checkpoint.BEFORE_FIRST_MODEL_CALL]]
    assert first == ["_cap_max_iterations", "_cap_wall_clock"]
    tool = [cap.__name__ for cap in
            constraints_module.BUILTIN_CAPS[Checkpoint.BEFORE_TOOL_EXECUTION]]
    assert tool == ["_cap_tool_bound", "_cap_repeated_call"]


# --------------------------------------------------------------------------- #
# AC-03 — a cost ceiling stops the loop mid-flight
# --------------------------------------------------------------------------- #
def _turn_cost_total(db: Session, execution_id: str) -> float:
    """What this execution actually spent, summed from the per-turn figures
    the loop recorded. Read from the transcript rather than from
    ``agent_executions.cost_amount`` because that column is written by the
    *success* path, and a governed stop is not one -- so the transcript is the
    only honest record of spend for a stopped execution."""
    rows = db.execute(
        select(ExecutionMessage.cost_amount).where(
            ExecutionMessage.execution_id == uuid.UUID(execution_id),
            ExecutionMessage.cost_amount.is_not(None))
    ).scalars().all()
    return float(sum(rows))


def test_ac03_cost_ceiling_stops_the_loop_mid_flight_with_a_governance_reason(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-03 — a real priced model, a real ceiling, a real mid-flight stop.

    Each turn costs 0.001 (50 tokens against a 0.02/1k price) and the ceiling
    is 0.0025, so the loop stops on the turn that reaches it: three turns
    spending 0.003.

    **That is an overshoot, and it is stated rather than hidden.** A bare
    ceiling can only ever notice spend after the iteration that caused it has
    been paid for, because the cost of a model call is unknowable until it
    returns. Keeping spend genuinely *within* a bound needs the headroom rule,
    which the next test exercises. What this test proves is the other half: the
    loop stops the moment the ceiling is reached, with an explicit governance
    reason, and issues no further model call."""
    model = _unique_model("cost")
    _seed_price(db_session, model, prompt_per_1k=0.02, completion_per_1k=0.02)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_tool_call_response(
            [(f"c{calls['n']}", "get_weather", {"location": f"City {calls['n']}"})],
            model=model), request=request)

    _use_transport(monkeypatch, httpx.MockTransport(handler))
    org = _register_org(client)
    tool = _create_function_tool(client, org)
    setup = _ready_agent(client, org, tool_ids=[tool["id"]], model=model)
    _policy(db_session, org["organization_id"], {"max_execution_cost": 0.0025},
            name="cost ceiling")

    execution = _run_execution(client, org, setup["agent"]["id"])

    assert execution["status"] == "FAILED"
    assert execution["error_code"] == "GOVERNANCE_EXECUTION_STOPPED"
    assert "ceiling" in execution["error_message"]
    assert execution["loop_iterations"] == 3
    assert calls["n"] == 3, "no model call may be issued after the ceiling is reached"
    assert _turn_cost_total(db_session, execution["id"]) == pytest.approx(0.003)

    stop = [d for d in _decisions(db_session, execution["id"]) if d.decision == "STOP"]
    assert len(stop) == 1
    assert stop[0].reason_code == ReasonCode.MAX_EXECUTION_COST.value
    assert stop[0].checkpoint == Checkpoint.AFTER_MODEL_RESPONSE.value


def test_ac03_headroom_keeps_spend_within_the_configured_bound(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-03 — **"cost stays within the configured bound"**, which is the
    headroom rule's job rather than the ceiling's.

    Same 0.0025 ceiling, plus ``min_remaining_cost: 0.0015``. After two turns
    the remaining headroom is 0.0005, less than one turn could cost, so the
    loop stops *before* dispatching a third. Total spend 0.002 — inside the
    bound, not merely near it."""
    model = _unique_model("headroom")
    _seed_price(db_session, model, prompt_per_1k=0.02, completion_per_1k=0.02)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_tool_call_response(
            [(f"c{calls['n']}", "get_weather", {"location": f"City {calls['n']}"})],
            model=model), request=request)

    _use_transport(monkeypatch, httpx.MockTransport(handler))
    org = _register_org(client)
    tool = _create_function_tool(client, org)
    setup = _ready_agent(client, org, tool_ids=[tool["id"]], model=model)
    _policy(db_session, org["organization_id"],
            {"max_execution_cost": 0.0025, "min_remaining_cost": 0.0015}, name="headroom")

    execution = _run_execution(client, org, setup["agent"]["id"])

    assert execution["status"] == "FAILED"
    assert execution["error_code"] == "GOVERNANCE_EXECUTION_STOPPED"
    spent = _turn_cost_total(db_session, execution["id"])
    assert spent == pytest.approx(0.002)
    assert spent <= 0.0025, "spend must stay within the configured ceiling"

    stop = [d for d in _decisions(db_session, execution["id"]) if d.decision == "STOP"]
    assert stop[-1].reason_code == ReasonCode.MIN_REMAINING_COST.value


def test_ac03_min_remaining_cost_stops_before_headroom_runs_out(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-03 — the headroom rule, which is what actually keeps spend inside a
    ceiling rather than reporting an overshoot after the fact."""
    execution = _an_execution(client, db_session, monkeypatch)
    _policy(db_session, str(execution.organization_id),
            {"max_execution_cost": 1.0, "min_remaining_cost": 0.5}, name="headroom")

    engine = _engine(db_session, execution)
    ok = engine.evaluate(Checkpoint.BEFORE_NEXT_ITERATION, _ctx(execution, cost_amount=0.4))
    assert ok.decision is Decision.ALLOW

    stopped = engine.evaluate(Checkpoint.BEFORE_NEXT_ITERATION, _ctx(execution, cost_amount=0.6))
    assert stopped.decision is Decision.STOP
    assert stopped.reason_code is ReasonCode.MIN_REMAINING_COST


def test_ac03_the_engine_computes_no_new_cost_and_reserves_no_budget() -> None:
    """AC-03 / M4-4.3-FR-011 — the engine reads existing cost. Budgets and
    reservations are Phase 4.4's, and nothing here anticipates them: the
    governance package never calls ``PricingService`` and never writes a cost
    column."""
    for path in (BACKEND_ROOT / "app" / "runtime" / "governance").rglob("*.py"):
        # Over the AST, not the text: every module here *discusses* pricing in
        # its docstrings, and a test that cannot tell an explanation from a
        # call would have to be weakened until it stopped proving anything.
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Name):
                assert node.id != "PricingService", f"{path.name} computes cost"
            if isinstance(node, ast.Attribute):
                assert node.attr not in ("calculate_cost", "resolve_price"), \
                    f"{path.name} computes cost"
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute):
                        assert target.attr not in ("cost_amount", "cost"), \
                            f"{path.name} writes a cost column"


# --------------------------------------------------------------------------- #
# AC-04 — restricted model / tool, enforced around the model
# --------------------------------------------------------------------------- #
def test_ac04_restricted_model_stops_before_the_call_is_made(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-04 — a restricted model is refused at ``BEFORE_FIRST_MODEL_CALL``,
    so the provider is never contacted at all. Enforcement around the model,
    not a request that the model behave."""
    model = _unique_model("restricted")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_final_answer_response(model=model), request=request)

    _use_transport(monkeypatch, httpx.MockTransport(handler))
    org = _register_org(client)
    setup = _ready_agent(client, org, model=model)
    _policy(db_session, org["organization_id"], {"restricted_models": [model]},
            name="model restriction")

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["status"] == "FAILED"
    assert execution["error_code"] == "GOVERNANCE_EXECUTION_STOPPED"
    assert calls["n"] == 0, "the restricted model must never have been called"

    stop = _decisions(db_session, execution["id"])[-1]
    assert stop.reason_code == ReasonCode.RESTRICTED_MODEL.value
    assert stop.checkpoint == Checkpoint.BEFORE_FIRST_MODEL_CALL.value


def test_ac04_restricted_tool_is_denied_at_the_tool_checkpoint_regardless_of_model_intent(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-04 — the model asks for the tool insistently; the platform refuses.
    The tool row is never written, which is the difference between refusing an
    action and logging that it happened."""
    _use_transport(monkeypatch, _sequenced_transport(
        _tool_call_response([("c1", "get_weather", {"location": "Paris"})])))
    org = _register_org(client)
    tool = _create_function_tool(client, org)
    setup = _ready_agent(client, org, tool_ids=[tool["id"]])
    _policy(db_session, org["organization_id"], {"restricted_tools": ["get_weather"]},
            name="tool restriction")

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["error_code"] == "GOVERNANCE_EXECUTION_STOPPED"

    rows = list(db_session.execute(
        select(ToolCall).where(ToolCall.execution_id == uuid.UUID(execution["id"]))).scalars())
    assert rows == [], "a denied tool must not execute"

    deny = _decisions(db_session, execution["id"])[-1]
    assert deny.decision == "DENY"
    assert deny.checkpoint == Checkpoint.BEFORE_TOOL_EXECUTION.value


def test_ac04_data_sensitivity_reuses_the_existing_tool_classification(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-04 / M4-4.3-FR-013 — the runtime constraint reads
    ``Tool.data_classification``, the same column Phase 3.2 checks at deploy
    time. No new taxonomy."""
    _use_transport(monkeypatch, _sequenced_transport(
        _tool_call_response([("c1", "get_weather", {"location": "Paris"})])))
    org = _register_org(client)
    tool = _create_function_tool(client, org, data_classification="RESTRICTED")
    assert db_session.get(Tool, uuid.UUID(tool["id"])).data_classification == "RESTRICTED"
    setup = _ready_agent(client, org, tool_ids=[tool["id"]])
    _policy(db_session, org["organization_id"],
            {"restricted_data_classifications": ["RESTRICTED"]}, name="sensitivity")

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["error_code"] == "GOVERNANCE_EXECUTION_STOPPED"
    assert _decisions(db_session, execution["id"])[-1].reason_code == ReasonCode.DATA_SENSITIVITY.value


# --------------------------------------------------------------------------- #
# AC-05 — CHALLENGE raises an obligation through the existing funnel
# --------------------------------------------------------------------------- #
def test_ac05_challenge_raises_an_approval_through_the_existing_funnel(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-05 — a ``RuntimeApproval`` row in the existing table, reviewable
    through the existing endpoint. No second approval mechanism was built."""
    _use_transport(monkeypatch, _sequenced_transport(_final_answer_response()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    _policy(db_session, org["organization_id"], {"requires_approval": True}, name="approval")

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["status"] == "PENDING_APPROVAL"
    assert execution["decision"] == "REQUIRE_APPROVAL"

    approvals = list(db_session.execute(
        select(RuntimeApproval).where(
            RuntimeApproval.execution_id == uuid.UUID(execution["id"]),
            RuntimeApproval.requested_action == "EXECUTION")).scalars())
    assert len(approvals) == 1
    assert approvals[0].status == "PENDING"
    assert approvals[0].request_summary["resumable"] is True

    listed = client.get(f"{RT}/approvals", headers=org["headers"], params={"status": "PENDING"})
    assert listed.status_code == 200
    assert str(approvals[0].id) in [a["id"] for a in listed.json()]


def test_ac05_a_mid_loop_challenge_terminates_rather_than_stranding_the_execution(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-05 — the honest half. A challenge raised after work has been
    dispatched cannot be resumed (no mechanism re-enters a partially-run
    loop), so it terminates in ``BLOCKED`` with the obligation standing,
    rather than parking in a state nothing could move it out of."""
    _use_transport(monkeypatch, _sequenced_transport(
        _tool_call_response([("c1", "get_weather", {"location": "Paris"})])))
    org = _register_org(client)
    tool = _create_function_tool(client, org)
    setup = _ready_agent(client, org, tool_ids=[tool["id"]])
    _policy(db_session, org["organization_id"], {"high_risk_actions": ["get_weather"]},
            name="high risk")

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["status"] == "BLOCKED"
    assert execution["error_code"] == "RUNTIME_APPROVAL_REQUIRED"

    approvals = list(db_session.execute(
        select(RuntimeApproval).where(
            RuntimeApproval.execution_id == uuid.UUID(execution["id"]))).scalars())
    assert len(approvals) == 1
    assert approvals[0].requested_action == "POLICY_EXCEPTION"
    assert approvals[0].request_summary["resumable"] is False

    challenge = _decisions(db_session, execution["id"])[-1]
    assert challenge.decision == "CHALLENGE"
    assert challenge.obligation["type"] == "APPROVAL"


def test_ac05_approving_a_challenge_lets_the_execution_actually_run(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-05 — the obligation is honoured, and honouring it *ends*.

    The existing funnel re-queues an approved execution, which puts it straight
    back through the checkpoint that challenged it. Without the engine knowing
    an approval had been granted, that checkpoint would challenge again and the
    operator would approve forever — an approval loop rather than an approval.
    So the engine resolves "has a human already approved an obligation for this
    execution" once per attempt, and the second pass runs."""
    _use_transport(monkeypatch, _sequenced_transport(_final_answer_response()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    _policy(db_session, org["organization_id"], {"requires_approval": True}, name="approval")

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["status"] == "PENDING_APPROVAL"

    approval = db_session.execute(
        select(RuntimeApproval).where(
            RuntimeApproval.execution_id == uuid.UUID(execution["id"]))).scalars().one()
    decided = client.post(f"{RT}/approvals/{approval.id}/decide", headers=org["headers"],
                          json={"decision": "APPROVED"})
    assert decided.status_code == 200, decided.text

    after = client.get(f"{RT}/executions/{execution['id']}", headers=org["headers"]).json()
    assert after["status"] == "SUCCEEDED", "an approved execution must actually run"

    pending = db_session.execute(
        select(RuntimeApproval).where(
            RuntimeApproval.execution_id == uuid.UUID(execution["id"]),
            RuntimeApproval.status == "PENDING")).scalars().all()
    assert pending == [], "approving must not raise a fresh obligation for the same execution"


def test_ac05_a_challenge_is_never_automatically_retried(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-05 — an automatic retry of something the platform just said needs a
    human would be the platform overruling the obligation it raised. Exactly
    one attempt exists."""
    _use_transport(monkeypatch, _sequenced_transport(_final_answer_response()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    _policy(db_session, org["organization_id"], {"requires_approval": True}, name="approval")

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["attempt_count"] == 1


# --------------------------------------------------------------------------- #
# AC-06 — FAIL CLOSED
# --------------------------------------------------------------------------- #
def test_ac06_a_mandatory_policy_that_cannot_be_evaluated_stops_the_execution(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-06 — **the governance plane's defining property.**

    A mandatory policy whose constraint raises is not "we could not check, so
    carry on". It is a STOP, with a reason code that says the evaluation
    failed rather than naming a rule the operator would go looking for and
    never find."""
    execution = _an_execution(client, db_session, monkeypatch)
    _policy(db_session, str(execution.organization_id), {"max_execution_cost": 5.0},
            mandatory=True, name="mandatory")

    def _explode(ctx, spec):
        raise RuntimeError("the dependency this constraint needs is unreachable")

    monkeypatch.setattr(engine_module, "POLICY_CONSTRAINTS", {
        **constraints_module.POLICY_CONSTRAINTS,
        Checkpoint.BEFORE_NEXT_ITERATION: (_explode,),
    })

    decision = _engine(db_session, execution).evaluate(
        Checkpoint.BEFORE_NEXT_ITERATION, _ctx(execution))
    assert decision.decision is Decision.STOP
    assert decision.reason_code is ReasonCode.CHECKPOINT_UNEVALUABLE
    assert decision.error_code == "GOVERNANCE_CHECKPOINT_UNEVALUABLE"


def test_ac06_a_non_mandatory_policy_that_cannot_be_evaluated_is_skipped(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-06 / M4-4.3-FR-021 — the asymmetry is the design. An advisory rule
    that halted production the moment it misbehaved would be a worse control
    than no rule at all."""
    execution = _an_execution(client, db_session, monkeypatch)
    _policy(db_session, str(execution.organization_id), {"max_execution_cost": 5.0},
            mandatory=False, name="advisory")

    def _explode(ctx, spec):
        raise RuntimeError("boom")

    monkeypatch.setattr(engine_module, "POLICY_CONSTRAINTS", {
        **constraints_module.POLICY_CONSTRAINTS,
        Checkpoint.BEFORE_NEXT_ITERATION: (_explode,),
    })

    decision = _engine(db_session, execution).evaluate(
        Checkpoint.BEFORE_NEXT_ITERATION, _ctx(execution))
    assert decision.decision is Decision.ALLOW


def test_ac06_unresolvable_policy_set_fails_closed_at_the_first_checkpoint(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-06 — the strongest form of unevaluable: policy *resolution* failed,
    so the platform does not merely not know what the rules say — it does not
    know whether a mandatory one applies. That fails closed."""
    execution = _an_execution(client, db_session, monkeypatch)

    def _explode(self, organization_id, *, environment_id, agent_id):
        raise RuntimeError("the policy store is unreachable")

    monkeypatch.setattr(GovernancePolicyService, "resolve", _explode)
    decision = _engine(db_session, execution).evaluate(
        Checkpoint.BEFORE_FIRST_MODEL_CALL, _ctx(execution))
    assert decision.decision is Decision.STOP
    assert decision.reason_code is ReasonCode.CHECKPOINT_UNEVALUABLE


def test_ac06_fail_closed_is_the_documented_inverse_of_telemetry() -> None:
    """AC-06 / AC-07 — the two planes' opposite postures are visible in the
    code, not only in prose. The telemetry emitter swallows and returns; the
    governance engine's equivalent handler produces a STOP."""
    telemetry = (BACKEND_ROOT / "app" / "observability" / "events.py").read_text(encoding="utf-8")
    assert "never gates execution" in telemetry

    engine = (BACKEND_ROOT / "app" / "runtime" / "governance" / "engine.py").read_text(encoding="utf-8")
    assert engine.count("governance fails CLOSED") >= 2
    assert "_unevaluable_decision" in engine


# --------------------------------------------------------------------------- #
# AC-07 — PLANE SEPARATION, both directions
# --------------------------------------------------------------------------- #
def test_ac07_a_telemetry_failure_does_not_stop_execution_or_change_the_decision(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-07 — direction one. Telemetry is broken for the whole run; the
    execution still succeeds and the governance decision is byte-identical to
    the one taken with telemetry healthy."""
    _use_transport(monkeypatch, _sequenced_transport(_final_answer_response()))
    org = _register_org(client)
    setup = _ready_agent(client, org)

    healthy = _run_execution(client, org, setup["agent"]["id"])
    healthy_decisions = [(d.checkpoint, d.decision, d.reason_code)
                         for d in _decisions(db_session, healthy["id"])]

    from app.observability import events as events_module

    def _broken_emit(db, record):
        raise RuntimeError("the telemetry store is on fire")

    monkeypatch.setattr(events_module, "emit", _broken_emit)
    monkeypatch.setattr(events_module, "emit_event",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("on fire")))

    _use_transport(monkeypatch, _sequenced_transport(_final_answer_response()))
    broken = _run_execution(client, org, setup["agent"]["id"])

    assert broken["status"] == "SUCCEEDED", "a telemetry failure must not gate execution"
    assert broken["error_code"] is None
    broken_decisions = [(d.checkpoint, d.decision, d.reason_code)
                        for d in _decisions(db_session, broken["id"])]
    assert broken_decisions == healthy_decisions, (
        "the governance decision changed when telemetry failed")


def test_ac07_a_governance_stop_still_happens_when_telemetry_is_broken(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-07 — the inverse of the above and the more dangerous direction: a
    broken telemetry plane must not be able to *suppress* a governance stop
    either. Fail-open must not become fail-open-for-governance-too."""
    from app.observability import events as events_module

    monkeypatch.setattr(events_module, "emit_event",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("on fire")))
    model = _unique_model("plane")
    _use_transport(monkeypatch, _sequenced_transport(_final_answer_response(model=model)))
    org = _register_org(client)
    setup = _ready_agent(client, org, model=model)
    _policy(db_session, org["organization_id"], {"restricted_models": [model]}, name="restricted")

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["error_code"] == "GOVERNANCE_EXECUTION_STOPPED"
    assert _decisions(db_session, execution["id"])[-1].reason_code == ReasonCode.RESTRICTED_MODEL.value


def test_ac07_the_engine_never_reads_the_telemetry_plane() -> None:
    """AC-07 — a metric can never become an enforcement input, because the
    governance package does not import the telemetry plane's read models at
    all. Asserted over the AST rather than by string search, so an aliased
    import is caught too."""
    forbidden = {"app.observability.events", "app.observability.assembly",
                 "app.observability.explorer", "app.observability.capture"}
    for path in (BACKEND_ROOT / "app" / "runtime" / "governance").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module in forbidden:
                raise AssertionError(f"{path.name} imports the telemetry plane ({node.module})")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden, f"{path.name} imports {alias.name}"


def test_ac07_the_checkpoint_context_carries_no_telemetry_handle() -> None:
    """AC-07 — structural: there is nothing in a checkpoint's input that a
    constraint *could* read a metric from. Plane separation by construction,
    not by discipline."""
    fields = set(CheckpointContext.__dataclass_fields__)
    assert not any(name.startswith(("metric", "telemetry", "span", "event")) for name in fields), fields
    assert "trace_id" in fields  # a correlation identifier, not a measurement


# --------------------------------------------------------------------------- #
# AC-08 / AC-09 — kill switch (§19)
# --------------------------------------------------------------------------- #
def test_ac08_a_governance_stop_triggers_the_existing_kill_switch(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-08 — the STOP delegates to ``KillSwitchService``. Verified by the
    outcome the existing service produces (a CANCELLED execution and its own
    ``RUNTIME_KILL_SWITCH_ACTIVATED`` audit event), not by asserting that a
    method was called."""
    execution = _an_execution(client, db_session, monkeypatch)
    _policy(db_session, str(execution.organization_id),
            {"max_execution_cost": 0.001, "stop_action": "KILL_EXECUTION"}, name="kill on stop")

    # Put the execution back into a non-terminal state so the kill has work to
    # do -- the executions this helper produces have already SUCCEEDED.
    execution.status = "RUNNING"
    db_session.commit()

    engine = _engine(db_session, execution)
    with pytest.raises(GovernanceStopped):
        engine.enforce(Checkpoint.BEFORE_NEXT_ITERATION, _ctx(execution, cost_amount=5.0))
    db_session.commit()

    db_session.refresh(execution)
    assert execution.status == "CANCELLED"
    assert execution.cancel_requested is True

    events = list(db_session.execute(
        select(AuthorizationAudit).where(
            AuthorizationAudit.event_type == "RUNTIME_KILL_SWITCH_ACTIVATED",
            AuthorizationAudit.organization_id == execution.organization_id)).scalars())
    assert events, "the existing kill-switch audit event must have been written"
    assert any((e.meta or {}).get("origin") == "runtime_governance" for e in events)


def test_ac08_automation_cannot_reach_the_project_org_or_platform_scopes(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-08 — a governance policy misconfigured by one tenant must not be
    able to halt a project, an organization, or the platform. Those scopes stay
    behind a human holding the permission to use them."""
    from app.identity.errors import IdentityError

    execution = _an_execution(client, db_session, monkeypatch)
    for scope in ("PROJECT", "ORGANIZATION", "PLATFORM"):
        with pytest.raises(IdentityError) as exc:
            KillSwitchService(db_session).activate_system(
                organization_id=execution.organization_id, scope=scope,
                target_id=execution.id, reason="test")
        assert "requires an operator" in exc.value.message


def test_ac08_the_engine_never_clears_a_kill() -> None:
    """AC-08 / §19 — kill-switch dominance, asserted structurally. No
    assignment anywhere in the governance package moves state *away* from
    stopped."""
    for path in (BACKEND_ROOT / "app" / "runtime" / "governance").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr in (
                        "lifecycle_status", "cancel_requested", "status"):
                    raise AssertionError(
                        f"{path.name} assigns {target.attr}; the engine decides, "
                        "it does not clear or set lifecycle state (AC-08)")


def test_ac08_the_engine_implements_no_suspension_of_its_own() -> None:
    """AC-08 — no parallel suspend. The only route to a kill is
    ``KillSwitchService``."""
    engine_source = (BACKEND_ROOT / "app" / "runtime" / "governance" / "engine.py").read_text(
        encoding="utf-8")
    assert "KillSwitchService" in engine_source
    assert "SUSPENDED" not in engine_source.replace(
        'lifecycle_status == "SUSPENDED"', ""), "the engine must not set a suspended state itself"


def test_ac09_a_kill_during_evaluation_dominates_every_other_decision(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-09 — the kill is checked *first*, before caps and before policy, and
    it is read fresh from the database on every checkpoint. A kill fired by an
    operator arrives on a different connection, so the session's cached copy
    of the row cannot see it; this reads through."""
    execution = _an_execution(client, db_session, monkeypatch)
    _policy(db_session, str(execution.organization_id), {"max_execution_cost": 0.001},
            mandatory=True, name="would also stop")
    engine = _engine(db_session, execution)

    # A second, genuinely separate connection fires the kill.
    other = SessionLocal()
    try:
        row = other.get(AgentExecution, execution.id)
        row.cancel_requested = True
        other.commit()
    finally:
        other.close()

    decision = engine.evaluate(Checkpoint.BEFORE_TOOL_EXECUTION, _ctx(execution, cost_amount=99.0))
    assert decision.decision is Decision.STOP
    assert decision.reason_code is ReasonCode.KILL_SWITCH_ACTIVE, (
        "the kill must dominate the cost ceiling that would also have stopped this")


def test_ac09_a_governance_stop_after_a_kill_is_never_retried(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-09 — an automatic retry past a kill would be automation overruling
    an operator. ``KILL_SWITCH_ACTIVE`` is non-retryable for that reason and
    not merely because retrying is wasteful."""
    from app.identity.errors import ErrorCode

    source = (BACKEND_ROOT / "app" / "runtime" / "services.py").read_text(encoding="utf-8")
    assert "ErrorCode.GOVERNANCE_EXECUTION_STOPPED, ErrorCode.KILL_SWITCH_ACTIVE," in source
    assert ErrorCode.KILL_SWITCH_ACTIVE == "KILL_SWITCH_ACTIVE"


# --------------------------------------------------------------------------- #
# AC-10 — COMMIT-BEFORE-DISPATCH / the M1 deadlock cannot recur
# --------------------------------------------------------------------------- #
def test_ac10_no_checkpoint_query_takes_a_row_lock() -> None:
    """AC-10 — structural half. Nothing in the governance package uses
    ``with_for_update`` or writes ``FOR UPDATE`` into raw SQL, so no checkpoint
    can acquire the exclusive lock the M1 deadlock required."""
    for path in (BACKEND_ROOT / "app" / "runtime" / "governance").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # Docstrings explain the locking discipline at length, so they are
        # excluded by identity -- a test that could not tell an explanation
        # from a statement would have to be weakened until it proved nothing.
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                first = node.body[0] if node.body else None
                if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    docstrings.add(id(first.value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr != "with_for_update", \
                    f"{path.name} takes a row lock at a checkpoint"
            # Raw SQL is the other way a lock could sneak in. No checkpoint
            # issues any: every read here goes through the ORM.
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docstrings):
                assert "FOR UPDATE" not in node.value.upper(), \
                    f"{path.name} writes a locking clause into raw SQL"


def test_ac10_a_tool_thread_can_insert_while_the_loop_sits_at_a_checkpoint(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-10 — **the behavioural deadlock proof**, and the shape that actually
    bit this codebase in M1.

    The deadlock was: the main session held ``FOR UPDATE`` on the
    ``agent_executions`` row while a tool thread's fresh session needed
    ``FOR KEY SHARE`` on that same row to insert its ``tool_calls`` FK — and
    the main thread was meanwhile blocked joining that worker.

    Here the main session evaluates a checkpoint that *writes* a decision row
    (the heaviest thing a checkpoint can do) and does not commit. A second,
    real connection then takes exactly the lock a tool insert needs, with
    ``NOWAIT`` so a conflict fails immediately rather than hanging the suite.
    It succeeds, because a foreign-key ``KEY SHARE`` is compatible with
    another ``KEY SHARE`` — which is precisely why the checkpoint is safe and
    the old ``FOR UPDATE`` was not."""
    execution = _an_execution(client, db_session, monkeypatch)
    _policy(db_session, str(execution.organization_id), {"restricted_tools": ["x"]}, name="denies")

    main = SessionLocal()
    other = SessionLocal()
    try:
        row = main.get(AgentExecution, execution.id)
        engine = RuntimeGovernanceEngine(main).bind(row, environment_id=None, agent_id=row.agent_id)
        decision = engine.evaluate(Checkpoint.BEFORE_TOOL_EXECUTION, _ctx(row, tool_name="x"))
        assert decision.decision is Decision.DENY  # a decision row was written, uncommitted

        other.execute(
            text("SELECT id FROM agent_executions WHERE id = :i FOR KEY SHARE NOWAIT"),
            {"i": str(execution.id)},
        ).first()
    finally:
        main.rollback()
        main.close()
        other.rollback()
        other.close()


def test_ac10_an_allowing_checkpoint_holds_no_lock_at_all(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-10 — the common case is even cleaner than the above. An ALLOW writes
    nothing (it is not material), so after it the session holds no lock on the
    execution row whatsoever — provable by taking the *exclusive* lock from
    another connection with ``NOWAIT``."""
    execution = _an_execution(client, db_session, monkeypatch)

    main = SessionLocal()
    other = SessionLocal()
    try:
        row = main.get(AgentExecution, execution.id)
        engine = RuntimeGovernanceEngine(main).bind(row, environment_id=None, agent_id=row.agent_id)
        assert engine.evaluate(Checkpoint.AFTER_TOOL_EXECUTION, _ctx(row)).decision is Decision.ALLOW

        other.execute(
            text("SELECT id FROM agent_executions WHERE id = :i FOR UPDATE NOWAIT"),
            {"i": str(execution.id)},
        ).first()
    finally:
        main.rollback()
        main.close()
        other.rollback()
        other.close()


def test_ac10_a_parallel_tool_batch_still_completes_under_governance(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-10 — end to end: the real parallel path (two idempotent tools in one
    batch, each on its own session and thread) runs to completion with
    checkpoints on both sides of it. If a checkpoint held a conflicting lock,
    this hangs rather than fails."""
    _use_transport(monkeypatch, _sequenced_transport(
        _tool_call_response([("c1", "get_weather", {"location": "Paris"}),
                             ("c2", "get_tide", {"location": "Nice"})]),
        _final_answer_response(),
    ))
    org = _register_org(client)
    weather = _create_function_tool(client, org, name="get_weather")
    tide = _create_function_tool(client, org, name="get_tide")
    setup = _ready_agent(client, org, tool_ids=[weather["id"], tide["id"]])

    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["status"] == "SUCCEEDED"
    rows = list(db_session.execute(
        select(ToolCall).where(ToolCall.execution_id == uuid.UUID(execution["id"]))).scalars())
    assert len(rows) == 2


# --------------------------------------------------------------------------- #
# AC-11 — decision lineage, append-only
# --------------------------------------------------------------------------- #
def test_ac11_a_successful_execution_records_that_it_was_governed(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-11 — the terminal ALLOW is persisted so an empty decision history is
    distinguishable from an engine that never ran. Sixty rows saying "nothing
    happened" would bury the ones that matter, so only material decisions are
    kept."""
    _use_transport(monkeypatch, _sequenced_transport(_final_answer_response()))
    org = _register_org(client)
    setup = _ready_agent(client, org)

    execution = _run_execution(client, org, setup["agent"]["id"])
    decisions = _decisions(db_session, execution["id"])
    assert len(decisions) == 1
    assert decisions[0].checkpoint == Checkpoint.BEFORE_FINAL_OUTPUT.value
    assert decisions[0].decision == "ALLOW"
    assert decisions[0].trace_id
    assert decisions[0].iteration == 1


def test_ac11_the_lineage_explains_why_an_execution_stopped(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-11 / FR-042 — the decision row is the source of truth for *why*, and
    it complements rather than duplicates ``termination_reason``, which stays
    the record of *what terminal state* the execution reached."""
    model = _unique_model("lineage")
    _use_transport(monkeypatch, _sequenced_transport(_final_answer_response(model=model)))
    org = _register_org(client)
    setup = _ready_agent(client, org, model=model)
    policy = _policy(db_session, org["organization_id"], {"restricted_models": [model]},
                     name="why it stopped")

    execution = _run_execution(client, org, setup["agent"]["id"])
    row = db_session.get(AgentExecution, uuid.UUID(execution["id"]))
    assert row.termination_reason == "GOVERNANCE_STOP"  # what state it reached

    decision = _decisions(db_session, execution["id"])[-1]
    assert decision.reason_code == ReasonCode.RESTRICTED_MODEL.value  # why
    assert decision.policy_id == policy.id
    assert decision.checkpoint == Checkpoint.BEFORE_FIRST_MODEL_CALL.value
    assert model in decision.reason


def test_ac11_decisions_are_append_only_at_the_database_level(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-11 — no service updates or deletes a decision, and the migration
    revokes both from PUBLIC. Evidence that could be edited after the fact is
    not evidence."""
    grants = db_session.execute(text(
        "SELECT privilege_type FROM information_schema.role_table_grants "
        "WHERE table_name = 'runtime_governance_decisions' AND grantee = 'PUBLIC'"
    )).scalars().all()
    assert "UPDATE" not in grants
    assert "DELETE" not in grants

    for path in (BACKEND_ROOT / "app" / "runtime" / "governance").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "db.delete" not in source, f"{path.name} deletes rows"


def test_ac11_the_decision_table_rejects_a_decision_the_engine_cannot_produce(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-11 — the check constraints are real. A row claiming a decision or a
    checkpoint outside the contract would be indistinguishable from a genuine
    one, so the database refuses it."""
    from sqlalchemy.exc import IntegrityError

    execution = _an_execution(client, db_session, monkeypatch)
    db_session.add(RuntimeGovernanceDecision(
        organization_id=execution.organization_id, execution_id=execution.id,
        checkpoint="BEFORE_FINAL_OUTPUT", decision="MAYBE", reason_code="ALLOWED"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


# --------------------------------------------------------------------------- #
# AC-12 — audit
# --------------------------------------------------------------------------- #
def test_ac12_material_governance_actions_are_audited_without_secrets(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-12 — both events are written, and ``meta`` carries codes only: no
    payload, no tool argument, no model output, so no secret can reach the
    audit record through this path."""
    model = _unique_model("audit")
    _use_transport(monkeypatch, _sequenced_transport(_final_answer_response(model=model)))
    org = _register_org(client)
    setup = _ready_agent(client, org, model=model)
    _policy(db_session, org["organization_id"], {"restricted_models": [model]}, name="audited")

    _run_execution(client, org, setup["agent"]["id"])

    events = list(db_session.execute(
        select(AuthorizationAudit).where(
            AuthorizationAudit.organization_id == uuid.UUID(org["organization_id"]),
            AuthorizationAudit.event_type.in_(
                ["RUNTIME_POLICY_EVALUATED", "RUNTIME_EXECUTION_STOPPED"]))).scalars())
    kinds = {e.event_type for e in events}
    assert kinds == {"RUNTIME_POLICY_EVALUATED", "RUNTIME_EXECUTION_STOPPED"}

    allowed_keys = {"checkpoint", "decision", "reason_code", "policy_id", "iteration"}
    for event in events:
        assert set(event.meta or {}) <= allowed_keys, event.meta


def test_ac12_an_ungoverned_execution_does_not_flood_the_audit_trail(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-12 — materiality keeps the audit trail readable. Six checkpoints per
    iteration would otherwise write dozens of rows per execution to say
    nothing happened."""
    _use_transport(monkeypatch, _sequenced_transport(_final_answer_response()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    _run_execution(client, org, setup["agent"]["id"])

    events = list(db_session.execute(
        select(AuthorizationAudit).where(
            AuthorizationAudit.organization_id == uuid.UUID(org["organization_id"]),
            AuthorizationAudit.event_type == "RUNTIME_POLICY_EVALUATED")).scalars())
    assert len(events) == 1


# --------------------------------------------------------------------------- #
# AC-13 — policy scoping, permissions, tenant isolation
# --------------------------------------------------------------------------- #
def test_ac13_policies_resolve_most_specific_first_and_accumulate(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-13 — a per-agent policy does not silently switch off the
    organization-wide one above it. Constraints accumulate; specificity only
    decides which message an operator sees first."""
    execution = _an_execution(client, db_session, monkeypatch)
    org_id = str(execution.organization_id)
    _policy(db_session, org_id, {"max_execution_cost": 10.0}, name="org wide")
    _policy(db_session, org_id, {"max_execution_cost": 100.0},
            agent_id=str(execution.agent_id), name="agent specific")

    resolved = GovernancePolicyService(db_session).resolve(
        execution.organization_id, environment_id=None, agent_id=execution.agent_id)
    assert [p.name for p in resolved] == ["agent specific", "org wide"]

    # The organization ceiling still bites even though a looser agent policy
    # exists and is evaluated first.
    decision = _engine(db_session, execution).evaluate(
        Checkpoint.BEFORE_NEXT_ITERATION, _ctx(execution, cost_amount=50.0))
    assert decision.decision is Decision.STOP
    assert decision.reason_code is ReasonCode.MAX_EXECUTION_COST


def test_ac13_a_policy_for_another_agent_does_not_apply(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    _use_transport(monkeypatch, _sequenced_transport(_final_answer_response()))
    org = _register_org(client)
    governed = _ready_agent(client, org)
    other_agent = _register_agent(client, org)

    execution_id = _run_execution(client, org, governed["agent"]["id"])["id"]
    execution = db_session.get(AgentExecution, uuid.UUID(execution_id))
    _policy(db_session, org["organization_id"], {"max_execution_cost": 0.0001},
            agent_id=other_agent["id"], name="a different agent's policy")

    decision = _engine(db_session, execution).evaluate(
        Checkpoint.BEFORE_NEXT_ITERATION, _ctx(execution, cost_amount=5.0))
    assert decision.decision is Decision.ALLOW


def test_ac13_policy_writes_require_the_governance_permission(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-13 — the endpoint is gated, and by a permission that exists in the
    catalog rather than one invented at the route."""
    from app.services.rbac_service import PERMISSION_CATALOG

    assert "runtime.governance.manage" in PERMISSION_CATALOG

    org = _register_org(client)
    r = client.post(f"{RT}/governance/policies", headers=org["headers"], json={
        "name": "ceiling", "constraints": {"max_execution_cost": 1.0}, "mandatory": True,
    })
    assert r.status_code == 201, r.text
    assert r.json()["organization_id"] == org["organization_id"]

    anonymous = client.post(f"{RT}/governance/policies", json={"name": "x", "constraints": {}})
    assert anonymous.status_code in (401, 403)


def test_ac13_a_misspelled_constraint_is_rejected_rather_than_stored(
        client: TestClient, db_session: Session) -> None:
    """AC-13 — a governance control that silently never fires is worse than
    one that is absent, because someone believes it works."""
    org = _register_org(client)
    r = client.post(f"{RT}/governance/policies", headers=org["headers"], json={
        "name": "typo", "constraints": {"max_execution_costs": 1.0},
    })
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "GOVERNANCE_POLICY_INVALID"
    assert "max_execution_costs" in r.json()["error"]["message"]


def test_ac13_cross_tenant_policy_access_is_rejected(client: TestClient) -> None:
    """AC-13 / §34 — another tenant's policy is *not found*, never forbidden:
    telling the two apart would confirm the row exists."""
    owner = _register_org(client, "Owner Org")
    created = client.post(f"{RT}/governance/policies", headers=owner["headers"], json={
        "name": "private", "constraints": {"max_execution_cost": 1.0},
    })
    assert created.status_code == 201
    policy_id = created.json()["id"]

    stranger = _register_org(client, "Stranger Org")
    seen = client.get(f"{RT}/governance/policies/{policy_id}", headers=stranger["headers"])
    assert seen.status_code == 404
    assert seen.json()["error"]["code"] == "GOVERNANCE_POLICY_NOT_FOUND"

    missing = client.get(f"{RT}/governance/policies/{uuid.uuid4()}", headers=stranger["headers"])
    assert missing.json()["error"] == seen.json()["error"]

    listed = client.get(f"{RT}/governance/policies", headers=stranger["headers"])
    assert policy_id not in [p["id"] for p in listed.json()]


def test_ac13_a_tenant_cannot_author_a_platform_default(client: TestClient) -> None:
    """AC-13 — a row with a null organization governs every tenant. No
    per-tenant permission reaches that far, so the service stamps the actor's
    own organization regardless of what was sent."""
    org = _register_org(client)
    r = client.post(f"{RT}/governance/policies", headers=org["headers"], json={
        "name": "sneaky", "constraints": {}, "organization_id": None,
    })
    assert r.status_code == 201
    assert r.json()["organization_id"] == org["organization_id"]


def test_ac13_the_decision_endpoint_is_tenant_scoped(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    _use_transport(monkeypatch, _sequenced_transport(_final_answer_response()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    execution = _run_execution(client, org, setup["agent"]["id"])

    mine = client.get(f"{RT}/executions/{execution['id']}/governance-decisions",
                      headers=org["headers"])
    assert mine.status_code == 200
    assert len(mine.json()) == 1

    stranger = _register_org(client, "Stranger Org")
    theirs = client.get(f"{RT}/executions/{execution['id']}/governance-decisions",
                        headers=stranger["headers"])
    assert theirs.status_code == 404


def test_ac13_policy_creation_is_idempotent(client: TestClient) -> None:
    """AC-13 / §6 — two overlapping ceilings created by a retried request
    would both evaluate, and the operator would see the tighter one fire with
    no obvious explanation."""
    org = _register_org(client)
    key = str(uuid.uuid4())
    body = {"name": "once", "constraints": {"max_execution_cost": 2.0}}
    first = client.post(f"{RT}/governance/policies", headers={**org["headers"],
                                                              "Idempotency-Key": key}, json=body)
    second = client.post(f"{RT}/governance/policies", headers={**org["headers"],
                                                               "Idempotency-Key": key}, json=body)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


# --------------------------------------------------------------------------- #
# AC-14 — the engine is runtime policy, not a second authorization system
# --------------------------------------------------------------------------- #
def test_ac14_the_engine_is_not_a_second_authorization_system() -> None:
    """AC-14 — ``AuthorizationGateway`` stays authoritative. The governance
    package never imports it, never calls it, and never grants anything: it
    answers *may this execution continue*, inside a request that gateway
    already authorized."""
    for path in (BACKEND_ROOT / "app" / "runtime" / "governance").rglob("*.py"):
        if path.name == "routes.py":
            continue  # routes are gated by require_permission, as every route is
        # Over the AST: the package docstring explains at length that
        # AuthorizationGateway stays authoritative, and a text search cannot
        # tell that sentence from a call to it.
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Name):
                assert node.id != "AuthorizationGateway", f"{path.name} calls the gateway"
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("app.authorization"):
                    # The audit-event enum is a shared vocabulary, not the gateway.
                    assert module == "app.authorization.enums", module
                for alias in node.names:
                    assert alias.name != "AuthorizationGateway", f"{path.name} imports the gateway"


def test_ac14_the_engine_never_bypasses_authorization_on_the_execution_path(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-14 — an execution still goes through the pre-existing authorization
    and admission gates before the loop (and therefore the engine) is ever
    reached. Governance is downstream of authorization, never instead of it."""
    _use_transport(monkeypatch, _sequenced_transport(_final_answer_response()))
    org = _register_org(client)
    setup = _ready_agent(client, org)
    execution = _run_execution(client, org, setup["agent"]["id"])

    row = db_session.get(AgentExecution, uuid.UUID(execution["id"]))
    assert row.decision == "ALLOW"       # written by the admission path, pre-loop
    assert row.risk_score is not None    # ditto

    stranger = _register_org(client, "Stranger Org")
    denied = client.post(f"{RT}/executions", headers=stranger["headers"], json={
        "agent_id": setup["agent"]["id"], "input_payload": {}})
    assert denied.status_code in (403, 404)


# --------------------------------------------------------------------------- #
# AC-16 — per-iteration checkpoint overhead (§25)
# --------------------------------------------------------------------------- #
def test_ac16_checkpoint_evaluation_overhead_is_bounded_and_reported(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-16 — the measurement, recorded as a test rather than as a note in a
    commit message so it keeps being checked.

    What is measured is one full ``evaluate()``: the kill-state read, the
    built-in caps and the policy constraints. This is the per-checkpoint cost;
    a loop iteration reaches four of them (five when a tool is called), so the
    per-iteration overhead is roughly four times the number below."""
    execution = _an_execution(client, db_session, monkeypatch)
    _policy(db_session, str(execution.organization_id),
            {"max_execution_cost": 100.0, "max_total_tokens": 1_000_000,
             "restricted_models": ["nothing"], "max_model_calls": 1000},
            name="realistic policy")
    engine = _engine(db_session, execution)
    ctx = _ctx(execution)

    for _ in range(20):  # warm the plan cache
        engine.evaluate(Checkpoint.BEFORE_NEXT_ITERATION, ctx)

    samples = []
    for _ in range(200):
        start = time.perf_counter()
        engine.evaluate(Checkpoint.BEFORE_NEXT_ITERATION, ctx)
        samples.append((time.perf_counter() - start) * 1000)

    p50 = statistics.median(samples)
    p95 = sorted(samples)[int(len(samples) * 0.95)]
    print(f"\n[AC-16] checkpoint evaluation: p50={p50:.3f}ms p95={p95:.3f}ms "
          f"(one policy, {len(samples)} samples)")
    assert p50 < CHECKPOINT_BUDGET_MS, f"checkpoint p50 {p50:.3f}ms exceeds the budget"


def test_ac16_policy_resolution_happens_once_per_execution_not_per_checkpoint(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-16 — the design decision that keeps the hot path off the query path,
    and simultaneously the stated consistency rule: an execution is governed by
    the policy set in force when its loop began, so a mid-flight edit cannot
    tear one execution's evaluation across checkpoints."""
    execution = _an_execution(client, db_session, monkeypatch)
    _policy(db_session, str(execution.organization_id), {"max_execution_cost": 100.0},
            name="original")
    engine = _engine(db_session, execution)
    assert len(engine.policies) == 1

    calls = {"n": 0}
    original = GovernancePolicyService.resolve

    def counting(self, *a, **k):
        calls["n"] += 1
        return original(self, *a, **k)

    monkeypatch.setattr(GovernancePolicyService, "resolve", counting)
    for checkpoint in Checkpoint:
        engine.evaluate(checkpoint, _ctx(execution))
    assert calls["n"] == 0, "policies were re-resolved on the hot path"

    # A policy added mid-flight does not join this execution's snapshot.
    _policy(db_session, str(execution.organization_id), {"max_execution_cost": 0.0001},
            name="added mid-flight")
    assert engine.evaluate(
        Checkpoint.BEFORE_NEXT_ITERATION, _ctx(execution, cost_amount=5.0)).decision is Decision.ALLOW


# --------------------------------------------------------------------------- #
# AC-19 — no placeholders
# --------------------------------------------------------------------------- #
def test_ac19_no_todo_fixme_or_skipped_work_in_this_phase() -> None:
    """AC-19."""
    # Built by concatenation rather than spelled out: this file is one of the
    # files being scanned, so a literal would make the test fail on itself.
    markers = ("TO" + "DO", "FIX" + "ME", "NotImplemented" + "Error",
               "pytest.mark." + "skip", "pytest.mark." + "xfail")
    paths = list((BACKEND_ROOT / "app" / "runtime" / "governance").rglob("*.py"))
    paths.append(BACKEND_ROOT / "migrations" / "versions" / "0047_runtime_governance.py")
    paths.append(Path(__file__))
    for path in paths:
        source = path.read_text(encoding="utf-8")
        for marker in markers:
            assert marker not in source, f"{path.name} contains {marker}"


def test_ac19_the_governance_contract_imports_no_database_layer() -> None:
    """The checkpoint vocabulary is reasoned about — and tested — without a
    database, the same discipline Phase 4.1 applied to ``observability.trace``."""
    source = (BACKEND_ROOT / "app" / "runtime" / "governance" / "contract.py").read_text(
        encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("sqlalchemy"), node.module
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("sqlalchemy"), alias.name


# --------------------------------------------------------------------------- #
# Constraint unit coverage — every constraint type (§11)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("spec,ctx_kwargs,expected", [
    ({"max_execution_cost": 1.0}, {"cost_amount": 1.5}, ReasonCode.MAX_EXECUTION_COST),
    ({"max_total_tokens": 100}, {"total_tokens": 150}, ReasonCode.MAX_TOTAL_TOKENS),
    ({"max_model_calls": 3}, {"model_calls": 3}, ReasonCode.MAX_MODEL_CALLS),
    ({"max_execution_duration_seconds": 5}, {"elapsed_seconds": 6.0},
     ReasonCode.MAX_EXECUTION_DURATION),
    ({"allowed_models": ["safe"]}, {"configured_model": "unsafe"}, ReasonCode.RESTRICTED_MODEL),
])
def test_iteration_boundary_constraints_each_fire(
        client: TestClient, db_session: Session, monkeypatch, spec, ctx_kwargs, expected) -> None:
    execution = _an_execution(client, db_session, monkeypatch)
    _policy(db_session, str(execution.organization_id), spec, name=f"unit {expected.value}")
    decision = _engine(db_session, execution).evaluate(
        Checkpoint.BEFORE_NEXT_ITERATION, _ctx(execution, **ctx_kwargs))
    assert decision.reason_code is expected, decision


@pytest.mark.parametrize("spec,ctx_kwargs,expected", [
    ({"max_tool_calls": 2}, {"tool_calls": 2, "tool_name": "t"}, ReasonCode.MAX_TOOL_CALLS),
    ({"max_calls_per_tool": {"t": 1}}, {"tool_name": "t", "calls_per_tool": {"t": 1}},
     ReasonCode.MAX_CALLS_PER_TOOL),
    ({"max_calls_per_tool": 1}, {"tool_name": "t", "calls_per_tool": {"t": 1}},
     ReasonCode.MAX_CALLS_PER_TOOL),
    ({"restricted_tool_classes": ["HTTP"]}, {"tool_name": "t", "tool_class": "HTTP"},
     ReasonCode.RESTRICTED_TOOL_CLASS),
    ({"allowed_data_classifications": ["PUBLIC"]},
     {"tool_name": "t", "tool_data_classification": "SECRET"}, ReasonCode.DATA_SENSITIVITY),
    ({"high_risk_actions": ["t"]}, {"tool_name": "t"}, ReasonCode.HIGH_RISK_ACTION),
])
def test_tool_checkpoint_constraints_each_fire(
        client: TestClient, db_session: Session, monkeypatch, spec, ctx_kwargs, expected) -> None:
    execution = _an_execution(client, db_session, monkeypatch)
    _policy(db_session, str(execution.organization_id), spec, name=f"unit {expected.value}")
    decision = _engine(db_session, execution).evaluate(
        Checkpoint.BEFORE_TOOL_EXECUTION, _ctx(execution, **ctx_kwargs))
    assert decision.reason_code is expected, decision


def test_environment_policy_is_evaluated_once_at_the_start_of_the_loop(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """``prohibited_environments`` is checked at ``BEFORE_FIRST_MODEL_CALL``
    and nowhere else, deliberately: an execution's environment is fixed by its
    deployment and cannot change mid-loop, so re-evaluating it at every
    checkpoint would spend work to re-derive a constant. It reuses the same
    policy key ``RuntimePolicyService.evaluate`` and Phase 3.2's
    ``check_prohibited`` already read (M4-4.3-FR-013)."""
    execution = _an_execution(client, db_session, monkeypatch)
    _policy(db_session, str(execution.organization_id),
            {"prohibited_environments": ["PRODUCTION"]}, name="env")
    engine = _engine(db_session, execution)

    stopped = engine.evaluate(Checkpoint.BEFORE_FIRST_MODEL_CALL,
                              _ctx(execution, environment="PRODUCTION"))
    assert stopped.reason_code is ReasonCode.ENVIRONMENT_POLICY

    allowed = engine.evaluate(Checkpoint.BEFORE_FIRST_MODEL_CALL,
                              _ctx(execution, environment="DEVELOPMENT"))
    assert allowed.decision is Decision.ALLOW


def test_criticality_can_require_approval(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    execution = _an_execution(client, db_session, monkeypatch)
    _policy(db_session, str(execution.organization_id),
            {"requires_approval_criticality": ["MISSION_CRITICAL"]}, name="criticality")
    decision = _engine(db_session, execution).evaluate(
        Checkpoint.BEFORE_FIRST_MODEL_CALL, _ctx(execution, criticality="MISSION_CRITICAL"))
    assert decision.decision is Decision.CHALLENGE
    assert decision.reason_code is ReasonCode.APPROVAL_REQUIRED


def test_constraint_validation_rejects_every_malformed_shape() -> None:
    from app.runtime.governance.constraints import validate_constraints

    assert validate_constraints({}) == []
    assert validate_constraints({"max_execution_cost": 1.0}) == []
    assert validate_constraints({"max_execution_cost": -1}) != []
    assert validate_constraints({"max_execution_cost": "cheap"}) != []
    assert validate_constraints({"restricted_models": "gpt-4o"}) != []
    assert validate_constraints({"requires_approval": "yes"}) != []
    assert validate_constraints({"max_calls_per_tool": {"t": -1}}) != []
    assert validate_constraints({"stop_action": "DESTROY"}) != []
    assert validate_constraints({"nonsense": 1}) != []
    assert validate_constraints("not an object") != []


def test_stop_action_defaults_to_doing_nothing_beyond_halting(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """A STOP halts the loop. Suspending an agent is a separate, explicit
    choice an operator has to make in the policy — automation does not escalate
    on its own."""
    execution = _an_execution(client, db_session, monkeypatch)
    _policy(db_session, str(execution.organization_id), {"max_execution_cost": 0.001},
            name="plain stop")
    decision = _engine(db_session, execution).evaluate(
        Checkpoint.BEFORE_NEXT_ITERATION, _ctx(execution, cost_amount=1.0))
    assert decision.decision is Decision.STOP
    assert decision.stop_action is StopAction.NONE


def test_a_disabled_policy_does_not_govern(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    execution = _an_execution(client, db_session, monkeypatch)
    policy = _policy(db_session, str(execution.organization_id), {"max_execution_cost": 0.001},
                     name="switched off")
    policy.enabled = False
    db_session.commit()
    decision = _engine(db_session, execution).evaluate(
        Checkpoint.BEFORE_NEXT_ITERATION, _ctx(execution, cost_amount=5.0))
    assert decision.decision is Decision.ALLOW


def test_the_engine_reads_kill_state_through_the_agent_lifecycle_too(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """An AGENT-scope kill expresses itself as ``lifecycle_status =
    'SUSPENDED'``. A loop running under a suspended agent stops."""
    execution = _an_execution(client, db_session, monkeypatch)
    agent = db_session.get(Agent, execution.agent_id)
    agent.lifecycle_status = "SUSPENDED"
    db_session.commit()

    decision = _engine(db_session, execution).evaluate(
        Checkpoint.AFTER_MODEL_RESPONSE, _ctx(execution))
    assert decision.reason_code is ReasonCode.KILL_SWITCH_ACTIVE
