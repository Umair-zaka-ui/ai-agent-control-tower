"""Phase 4.5 tests — behavioral signals and runtime anomaly detection.

The weight is on the constraints rather than the features. **Gate L** is
deterministic, explainable behavioral monitoring — so the load-bearing tests are
the ones asserting that the same data always yields the same finding, that every
finding explains itself from its own record, that a thin window is never
anomalous, and that nothing here can stop an execution.

Executions are written directly rather than driven through the HTTP pipeline:
these tests need dozens of rows at controlled timestamps across two windows, and
driving that through the pipeline would measure the pipeline.
"""

from __future__ import annotations

import ast
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.behavior.engine import (
    DEFAULT_WINDOW,
    TERMINAL_FOR_BEHAVIOR,
    BehavioralEvaluator,
)
from app.behavior.signals import (
    CAP_TERMINATIONS,
    DEFAULT_THRESHOLDS,
    RULES,
    SIGNAL_TYPES,
    WindowMetrics,
    thresholds_for,
)
from app.behavior.states import (
    REPORTABLE_STATES,
    SHARED_WITH_HEALTH_STATES,
    SignalState,
)
from app.models.agent import Agent
from app.models.runtime import AgentExecution, BehavioralFinding, Tool, ToolCall

PASSWORD = "T3st!Passw0rd#Ok"
RT = "/api/v1/runtime"
BACKEND_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _register_org(client: TestClient, org_name: str = "Behavior Org") -> dict:
    email = f"behav_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": org_name, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"],
            "organization_id": me["user"]["organization_id"]}


def _agent_setup(client: TestClient, admin: dict, *, model: str = "llama3") -> dict:
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Behavior Agent {uuid.uuid4().hex[:6]}", "agent_type": "ASSISTANT",
        "criticality": "MEDIUM", "description": "A test agent.",
        "business_purpose": "Exercise behavioral signals.", "owner_type": "USER",
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
                       json={"client_id": f"agent-identity-{uuid.uuid4().hex[:10]}"}
                       ).status_code == 200
    for step in ("submit-for-approval", "approve", "activate"):
        assert client.post(f"{RT}/agents/{agent['id']}/{step}",
                           headers=admin["headers"]).status_code == 200
    r = client.post(f"{RT}/agents/{agent['id']}/versions", headers=admin["headers"], json={
        "model_configuration": {"provider": "OPENAI_COMPATIBLE", "model": model},
        "tool_ids": [],
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


def _seed(db: Session, setup: dict, org: dict, *, count: int, at: datetime,
          status: str = "SUCCEEDED", duration_ms: int | None = 100,
          cost: float | None = 0.01, error_code: str | None = None,
          termination_reason: str | None = "COMPLETED",
          loop_iterations: int = 1) -> list[AgentExecution]:
    """``count`` executions all stamped at ``at``.

    ``created_at`` is a server-default column, so it is set with an explicit
    UPDATE after the insert rather than in the constructor."""
    rows = []
    for _ in range(count):
        row = AgentExecution(
            organization_id=uuid.UUID(org["organization_id"]),
            agent_id=uuid.UUID(setup["agent"]["id"]),
            agent_version_id=uuid.UUID(setup["version"]["id"]),
            deployment_id=uuid.UUID(setup["deployment"]["id"]),
            trigger_type="API", input_payload={}, status=status,
            duration_ms=duration_ms,
            cost_amount=Decimal(str(cost)) if cost is not None else None,
            cost_currency="USD", error_code=error_code,
            termination_reason=termination_reason, loop_iterations=loop_iterations,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    db.execute(text("UPDATE agent_executions SET created_at = :t WHERE id = ANY(:ids)"),
               {"t": at, "ids": [r.id for r in rows]})
    db.commit()
    return rows


def _tool(client: TestClient, org: dict, name: str) -> dict:
    r = client.post(f"{RT}/tools", headers=org["headers"], json={
        "name": name, "display_name": name, "tool_type": "FUNCTION",
        "description": "d", "input_schema": {"type": "object", "properties": {}}})
    assert r.status_code == 201, r.text
    return r.json()


def _seed_tool_calls(db: Session, setup: dict, tool: dict, executions: list[AgentExecution],
                     *, failures: int, at: datetime) -> None:
    rows = []
    for index, execution in enumerate(executions):
        failed = index < failures
        row = ToolCall(
            execution_id=execution.id, agent_id=uuid.UUID(setup["agent"]["id"]),
            tool_id=uuid.UUID(tool["id"]), action="EXECUTE",
            status="FAILED" if failed else "ALLOWED",
            error_code="TOOL_EXECUTION_FAILED" if failed else None,
            duration_ms=50,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    db.execute(text("UPDATE tool_calls SET created_at = :t WHERE id = ANY(:ids)"),
               {"t": at, "ids": [r.id for r in rows]})
    db.commit()


def _evaluate(db: Session, org: dict, setup: dict, *, persist: bool = True,
              window_end: datetime | None = None):
    agent = db.get(Agent, uuid.UUID(setup["agent"]["id"]))
    db.refresh(agent)
    return BehavioralEvaluator(db).evaluate(
        organization_id=uuid.UUID(org["organization_id"]), agent=agent,
        window_end=window_end, persist=persist)


def _signal(result, signal_type: str):
    return next(s for s in result.results if s.signal_type == signal_type)


def _findings(db: Session, setup: dict) -> list[BehavioralFinding]:
    return list(db.execute(
        select(BehavioralFinding)
        .where(BehavioralFinding.agent_id == uuid.UUID(setup["agent"]["id"]))
        .order_by(BehavioralFinding.signal_type)
    ).scalars())


NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
IN_WINDOW = NOW - timedelta(days=2)
IN_BASELINE = NOW - timedelta(days=9)


# --------------------------------------------------------------------------- #
# AC-01 — the signal set
# --------------------------------------------------------------------------- #
def test_ac01_every_declared_signal_is_computed_over_a_real_window(
        client: TestClient, db_session: Session) -> None:
    """AC-01 — all seven signals in §4.1 are computed, not merely declared."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    _seed(db_session, setup, org, count=40, at=IN_WINDOW)
    _seed(db_session, setup, org, count=40, at=IN_BASELINE)

    result = _evaluate(db_session, org, setup, window_end=NOW, persist=False)
    assert {s.signal_type for s in result.results} == set(SIGNAL_TYPES)
    assert len(SIGNAL_TYPES) == 7
    for signal in result.results:
        assert signal.reason, f"{signal.signal_type} produced no reason"


def test_ac01_error_rate_shift_fires_on_a_real_error_spike(
        client: TestClient, db_session: Session) -> None:
    org = _register_org(client)
    setup = _agent_setup(client, org)
    _seed(db_session, setup, org, count=30, at=IN_BASELINE)              # clean baseline
    _seed(db_session, setup, org, count=15, at=IN_WINDOW)
    _seed(db_session, setup, org, count=15, at=IN_WINDOW, status="FAILED",
          error_code="MODEL_PROVIDER_UNAVAILABLE", termination_reason=None)

    signal = _signal(_evaluate(db_session, org, setup, window_end=NOW, persist=False),
                     "error_rate_shift")
    assert signal.state is SignalState.ANOMALOUS
    assert signal.observed == pytest.approx(0.5)
    assert signal.baseline == pytest.approx(0.0)
    assert signal.attribution["error_code"]["dominant"] == "MODEL_PROVIDER_UNAVAILABLE"


def test_ac01_policy_denial_surge_is_separate_from_the_error_rate(
        client: TestClient, db_session: Session) -> None:
    """A denied execution is not an erroring one: it is being refused, which is
    a different behavioral fact and has its own signal — the same distinction
    Phase 3.5 drew between failure rate and denial rate."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    _seed(db_session, setup, org, count=30, at=IN_BASELINE)
    _seed(db_session, setup, org, count=20, at=IN_WINDOW)
    _seed(db_session, setup, org, count=20, at=IN_WINDOW, status="DENIED",
          termination_reason=None)

    result = _evaluate(db_session, org, setup, window_end=NOW, persist=False)
    assert _signal(result, "policy_denial_surge").state is SignalState.ANOMALOUS
    assert _signal(result, "error_rate_shift").state is SignalState.NORMAL


def test_ac01_latency_drift_reports_a_slowdown_and_names_the_model(
        client: TestClient, db_session: Session) -> None:
    org = _register_org(client)
    setup = _agent_setup(client, org, model="slow-model")
    _seed(db_session, setup, org, count=30, at=IN_BASELINE, duration_ms=100)
    _seed(db_session, setup, org, count=30, at=IN_WINDOW, duration_ms=1000)

    signal = _signal(_evaluate(db_session, org, setup, window_end=NOW, persist=False),
                     "latency_drift")
    assert signal.state is SignalState.ANOMALOUS
    assert signal.observed == pytest.approx(1000.0)
    assert signal.baseline == pytest.approx(100.0)
    assert signal.attribution["model"]["dominant"] == "slow-model"


def test_ac01_latency_drift_also_reports_a_sudden_speedup(
        client: TestClient, db_session: Session) -> None:
    """**A behavioral signal is not a health signal**, and this is where they
    part company. A p95 that collapses by 90% overnight is not good news to be
    filtered out — it usually means the agent stopped doing something it used
    to do. Phase 3.5 would call that healthy; this calls it a change."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    _seed(db_session, setup, org, count=30, at=IN_BASELINE, duration_ms=1000)
    _seed(db_session, setup, org, count=30, at=IN_WINDOW, duration_ms=80)

    signal = _signal(_evaluate(db_session, org, setup, window_end=NOW, persist=False),
                     "latency_drift")
    assert signal.state is SignalState.ANOMALOUS
    assert "decreased" in signal.reason


def test_ac01_tool_failure_spike_names_the_failing_tool(
        client: TestClient, db_session: Session) -> None:
    """AC-01/AC-06 — per tool, not aggregated. One broken integration among
    several healthy ones barely moves an average, which is exactly the case an
    operator needs surfaced."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    healthy = _tool(client, org, "search_docs")
    broken = _tool(client, org, "send_email")

    base = _seed(db_session, setup, org, count=30, at=IN_BASELINE)
    now = _seed(db_session, setup, org, count=30, at=IN_WINDOW)
    _seed_tool_calls(db_session, setup, healthy, base, failures=0, at=IN_BASELINE)
    _seed_tool_calls(db_session, setup, broken, base, failures=0, at=IN_BASELINE)
    _seed_tool_calls(db_session, setup, healthy, now, failures=0, at=IN_WINDOW)
    _seed_tool_calls(db_session, setup, broken, now, failures=24, at=IN_WINDOW)

    signal = _signal(_evaluate(db_session, org, setup, window_end=NOW, persist=False),
                     "tool_failure_spike")
    assert signal.state is SignalState.ANOMALOUS
    assert signal.attribution["tool_name"] == "send_email"
    assert signal.observed == pytest.approx(0.8)
    assert signal.evidence == {"calls": 30, "failures": 24}


def test_ac01_tool_pattern_shift_detects_a_changed_tool_mix(
        client: TestClient, db_session: Session) -> None:
    """Which tools an agent reaches for, independent of whether they fail."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    old_tool = _tool(client, org, "search_docs")
    new_tool = _tool(client, org, "delete_records")

    base = _seed(db_session, setup, org, count=30, at=IN_BASELINE)
    now = _seed(db_session, setup, org, count=30, at=IN_WINDOW)
    _seed_tool_calls(db_session, setup, old_tool, base, failures=0, at=IN_BASELINE)
    _seed_tool_calls(db_session, setup, new_tool, now, failures=0, at=IN_WINDOW)

    signal = _signal(_evaluate(db_session, org, setup, window_end=NOW, persist=False),
                     "tool_pattern_shift")
    assert signal.state is SignalState.ANOMALOUS
    assert signal.observed == pytest.approx(1.0)  # completely disjoint mixes
    assert "delete_records" in signal.evidence["new_tools"]


def test_ac01_loop_termination_anomaly_fires_when_caps_start_absorbing(
        client: TestClient, db_session: Session) -> None:
    """**The signal that is invisible in the error rate.** A model that has
    started looping is stopped by Phase 5.6a.3's caps working exactly as
    designed — so nothing errors from the caller's point of view, and only the
    termination mix shows the change."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    _seed(db_session, setup, org, count=30, at=IN_BASELINE)
    _seed(db_session, setup, org, count=20, at=IN_WINDOW)
    _seed(db_session, setup, org, count=20, at=IN_WINDOW,
          termination_reason="MAX_ITERATIONS", loop_iterations=10)

    result = _evaluate(db_session, org, setup, window_end=NOW, persist=False)
    signal = _signal(result, "loop_termination_anomaly")
    assert signal.state is SignalState.ANOMALOUS
    assert signal.observed == pytest.approx(0.5)
    assert signal.attribution["dominant"] == "MAX_ITERATIONS"
    # The point: the error rate saw nothing.
    assert _signal(result, "error_rate_shift").state is SignalState.NORMAL


# --------------------------------------------------------------------------- #
# AC-02 — deterministic, no ML
# --------------------------------------------------------------------------- #
def test_ac02_the_same_data_always_yields_the_same_finding(
        client: TestClient, db_session: Session) -> None:
    """AC-02 — determinism, asserted by running the whole evaluation twice over
    unchanged data and comparing every field of every signal."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    _seed(db_session, setup, org, count=30, at=IN_BASELINE, duration_ms=100)
    _seed(db_session, setup, org, count=20, at=IN_WINDOW, duration_ms=900)
    _seed(db_session, setup, org, count=10, at=IN_WINDOW, status="FAILED",
          error_code="X", termination_reason=None)

    def snapshot():
        result = _evaluate(db_session, org, setup, window_end=NOW, persist=False)
        return [(s.signal_type, s.state, s.reason, s.observed, s.threshold, s.baseline)
                for s in result.results]

    first, second, third = snapshot(), snapshot(), snapshot()
    assert first == second == third


def test_ac02_no_model_library_is_imported_anywhere_in_the_package() -> None:
    """AC-02 — the no-ML line, asserted structurally.

    §4.5 forbids opaque scoring because it is unauditable: a regulated tenant
    cannot act on "0.87 anomalous", dispute it, or show a regulator why it
    fired. The rules here are arithmetic, and nothing that could hide a model
    is importable."""
    forbidden = ("numpy", "scipy", "sklearn", "pandas", "torch", "tensorflow",
                 "statsmodels", "xgboost", "lightgbm", "random")
    for path in (BACKEND_ROOT / "app" / "behavior").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                assert not any(name == f or name.startswith(f + ".") for f in forbidden), \
                    f"{path.name} imports {name}"


def test_ac02_the_rules_are_pure_functions_of_their_arguments() -> None:
    """AC-02 — a rule that read a clock or a session could not be deterministic.
    None of them takes one, and none reaches for one."""
    import inspect

    from app.behavior import signals as signals_module

    for rule in RULES:
        parameters = list(inspect.signature(rule).parameters)
        assert parameters == ["candidate", "baseline", "thresholds"], \
            f"{rule.__name__} takes {parameters}"

    source = (BACKEND_ROOT / "app" / "behavior" / "signals.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in ("datetime", "time"), \
                    "a rule module that reads a clock cannot be deterministic"
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "") not in ("datetime", "time"), node.module
    assert signals_module.DEFAULT_THRESHOLDS  # the knobs are declared, not learned


# --------------------------------------------------------------------------- #
# AC-03 — explainability
# --------------------------------------------------------------------------- #
def test_ac03_every_persisted_finding_explains_itself_from_its_own_record(
        client: TestClient, db_session: Session) -> None:
    """AC-03 — **the phase's defining property.** A finding must state, from
    its own row, what was measured, over which window, against what, and what
    crossed. No external context, no lookup, no join."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    _seed(db_session, setup, org, count=30, at=IN_BASELINE, duration_ms=100)
    _seed(db_session, setup, org, count=15, at=IN_WINDOW, duration_ms=2000)
    _seed(db_session, setup, org, count=15, at=IN_WINDOW, status="FAILED",
          error_code="BOOM", termination_reason=None, duration_ms=2000)

    _evaluate(db_session, org, setup, window_end=NOW)
    findings = _findings(db_session, setup)
    assert findings, "a changed agent produced no finding"

    for finding in findings:
        explanation = finding.explanation
        assert explanation["metric"] == finding.metric
        assert explanation["crossing"], f"{finding.signal_type} has no stated crossing"
        assert explanation["window"]["start"] and explanation["window"]["end"]
        assert explanation["window"]["sample_count"] == finding.sample_count
        assert "baseline_window" in explanation
        assert explanation["rule"].startswith("deterministic")
        # An operator must be able to recompute the verdict: for anything that
        # crossed a bound, the bound and the observation are both present.
        if finding.state in ("DEGRADED", "ANOMALOUS"):
            assert finding.observed_value is not None
            assert (finding.threshold_value is not None
                    or finding.baseline_value is not None)


def test_ac03_the_explanation_states_the_numbers_not_just_a_verdict(
        client: TestClient, db_session: Session) -> None:
    """AC-03 — the difference between an auditable finding and a score."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    tool = _tool(client, org, "send_email")
    base = _seed(db_session, setup, org, count=30, at=IN_BASELINE)
    now = _seed(db_session, setup, org, count=30, at=IN_WINDOW)
    _seed_tool_calls(db_session, setup, tool, base, failures=1, at=IN_BASELINE)
    _seed_tool_calls(db_session, setup, tool, now, failures=18, at=IN_WINDOW)

    _evaluate(db_session, org, setup, window_end=NOW)
    finding = next(f for f in _findings(db_session, setup)
                   if f.signal_type == "tool_failure_spike")

    assert "send_email" in finding.explanation["crossing"]
    assert "60.0%" in finding.explanation["crossing"]
    assert finding.explanation["evidence"] == {"calls": 30, "failures": 18}
    assert finding.attribution["tool_name"] == "send_email"


# --------------------------------------------------------------------------- #
# AC-04 — INSUFFICIENT_DATA first-class
# --------------------------------------------------------------------------- #
def test_ac04_a_thin_window_is_insufficient_data_not_anomalous(
        client: TestClient, db_session: Session) -> None:
    """AC-04 — **the single most dangerous thing this engine could get wrong.**
    Three catastrophic executions are not evidence of a behavioral change, and
    three perfect ones are not evidence of health. Phase 3.5's discipline,
    applied to a broader signal set."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    _seed(db_session, setup, org, count=3, at=IN_WINDOW, status="FAILED",
          error_code="BOOM", termination_reason=None)

    result = _evaluate(db_session, org, setup, window_end=NOW, persist=False)
    assert {s.state for s in result.results} == {SignalState.INSUFFICIENT_DATA}
    for signal in result.results:
        assert "at least" in signal.reason
        assert "thin sample is not evidence" in signal.reason


def test_ac04_insufficient_data_is_recorded_not_silently_dropped(
        client: TestClient, db_session: Session) -> None:
    """AC-04/AC-09 — "we could not tell" is an answer an operator asking "why
    is there no signal here?" needs to be able to find."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    _seed(db_session, setup, org, count=2, at=IN_WINDOW)

    _evaluate(db_session, org, setup, window_end=NOW)
    findings = _findings(db_session, setup)
    assert len(findings) == len(SIGNAL_TYPES)
    assert {f.state for f in findings} == {"INSUFFICIENT_DATA"}


def test_ac04_a_thin_baseline_disables_comparison_without_disabling_the_signal(
        client: TestClient, db_session: Session) -> None:
    """AC-04 — a baseline of three executions would manufacture drift out of
    noise, so it is treated as *no baseline* rather than a weak one. Absolute
    thresholds still apply, so the signal is still evaluated."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    _seed(db_session, setup, org, count=2, at=IN_BASELINE)                # too thin
    _seed(db_session, setup, org, count=20, at=IN_WINDOW)
    _seed(db_session, setup, org, count=20, at=IN_WINDOW, status="FAILED",
          error_code="BOOM", termination_reason=None)

    result = _evaluate(db_session, org, setup, window_end=NOW, persist=False)
    assert result.baseline is None
    error = _signal(result, "error_rate_shift")
    assert error.state is SignalState.ANOMALOUS      # absolute rule still fired
    assert error.baseline is None
    # ...but a purely relative signal has nothing to say.
    assert _signal(result, "latency_drift").state is SignalState.NORMAL
    assert "No baseline" in _signal(result, "latency_drift").reason


# --------------------------------------------------------------------------- #
# AC-05 — the 3.5 engine shape, reused not forked
# --------------------------------------------------------------------------- #
def test_ac05_the_shared_state_values_are_identical_to_35() -> None:
    """AC-05 — three of the five states are byte-identical to Phase 3.5's, and
    a rename on either side breaks this rather than silently diverging.

    The two endpoints differ on purpose: 3.5 asks "is this version fit for more
    traffic" (HEALTHY/UNHEALTHY, a fitness judgement); this asks "has this
    agent's behavior changed" (NORMAL/ANOMALOUS, a deviation judgement). A p95
    that halves is anomalous and not unhealthy; a steady 30% failure rate is
    unhealthy and not anomalous."""
    health_source = (BACKEND_ROOT / "app" / "runtime" / "deployment" / "health.py").read_text(
        encoding="utf-8")
    for shared in SHARED_WITH_HEALTH_STATES:
        assert f'"{shared}"' in health_source, f"3.5 no longer uses {shared}"
        assert shared in {s.value for s in SignalState}
    assert SHARED_WITH_HEALTH_STATES == {"DEGRADED", "INSUFFICIENT_DATA", "UNKNOWN"}


def test_ac05_the_terminal_status_set_matches_35() -> None:
    """AC-05 — what counts as an observed outcome is the same question in both
    engines, so it must have the same answer. Asserted rather than copied and
    hoped for."""
    from app.runtime.deployment.health import (
        DENIAL_STATUSES,
        FAILURE_STATUSES,
        TERMINAL_FOR_HEALTH,
        TIMEOUT_STATUSES,
    )
    from app.behavior import engine as behavior_engine

    assert behavior_engine.TERMINAL_FOR_BEHAVIOR == TERMINAL_FOR_HEALTH
    assert behavior_engine.FAILURE_STATUSES == FAILURE_STATUSES
    assert behavior_engine.TIMEOUT_STATUSES == TIMEOUT_STATUSES
    assert behavior_engine.DENIAL_STATUSES == DENIAL_STATUSES


def test_ac05_the_veto_comes_before_any_aggregation(
        client: TestClient, db_session: Session) -> None:
    """AC-05 — step 1 of the 3.5 order, with a reason of its own: a suspended
    agent's recent executions describe the *intervention*, not the agent.
    Reporting the resulting cancellation spike as ANOMALOUS would raise an
    alarm about the kill switch at the moment an operator is already using it."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    _seed(db_session, setup, org, count=40, at=IN_WINDOW, status="CANCELLED",
          termination_reason=None)

    agent = db_session.get(Agent, uuid.UUID(setup["agent"]["id"]))
    agent.lifecycle_status = "SUSPENDED"
    db_session.commit()

    result = _evaluate(db_session, org, setup, window_end=NOW, persist=False)
    assert {s.state for s in result.results} == {SignalState.UNKNOWN}
    assert result.candidate.sample_count == 0, "aggregation ran despite the veto"
    assert "suspended" in result.results[0].reason


def test_ac05_the_cap_termination_vocabulary_is_the_loops_own() -> None:
    """AC-05 — the cap names come from Phase 5.6a.3's loop, not a parallel
    list that could drift from it."""
    loop_source = (BACKEND_ROOT / "app" / "runtime" / "governance" / "constraints.py").read_text(
        encoding="utf-8")
    for reason in CAP_TERMINATIONS:
        assert f'"{reason}"' in loop_source, f"{reason} is not a termination the loop writes"


def test_ac05_thresholds_come_from_environment_policy_not_a_new_mechanism() -> None:
    """AC-05 — overrides ride on ``Environment.policy``, the same carrier Phase
    3.3 used for preflight and 3.5 for canary health. A misspelled key is
    ignored rather than accepted, so a control nobody configured cannot look
    configured."""
    assert thresholds_for(None) == DEFAULT_THRESHOLDS
    tuned = thresholds_for({"behavioral_thresholds": {"anomalous_error_rate": 0.9}})
    assert tuned["anomalous_error_rate"] == 0.9
    assert tuned["degraded_error_rate"] == DEFAULT_THRESHOLDS["degraded_error_rate"]
    assert thresholds_for({"behavioral_thresholds": {"anomlous_error_rate": 0.1}}) == \
        DEFAULT_THRESHOLDS


# --------------------------------------------------------------------------- #
# AC-06 — attribution, and the connector gap
# --------------------------------------------------------------------------- #
def test_ac06_provider_model_and_tool_attribution_are_present(
        client: TestClient, db_session: Session) -> None:
    org = _register_org(client)
    setup = _agent_setup(client, org, model="claude-opus-5")
    _seed(db_session, setup, org, count=30, at=IN_BASELINE, duration_ms=100)
    _seed(db_session, setup, org, count=30, at=IN_WINDOW, duration_ms=1500)

    signal = _signal(_evaluate(db_session, org, setup, window_end=NOW, persist=False),
                     "latency_drift")
    assert signal.attribution["model"]["dominant"] == "claude-opus-5"
    assert signal.attribution["provider"]["dominant"] == "OPENAI_COMPATIBLE"


def test_ac06_connector_attribution_is_declared_unavailable_not_omitted(
        client: TestClient, db_session: Session) -> None:
    """AC-06 — **the honest gap.** The runtime has no record of which external
    system a version depends on (ACT-INT-FR-006, the runtime-never-knows
    boundary Phases 3.2, 3.3 and 3.5 each reported in turn), so "which
    connector caused today's failures" cannot be answered without inventing a
    dependency link.

    Every finding therefore carries ``connector: null`` **with a reason**.
    Naming the gap in the record is more useful than omitting the key and
    letting a reader assume it was never considered."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    _seed(db_session, setup, org, count=30, at=IN_BASELINE)
    _seed(db_session, setup, org, count=15, at=IN_WINDOW)
    _seed(db_session, setup, org, count=15, at=IN_WINDOW, status="FAILED",
          error_code="BOOM", termination_reason=None)

    _evaluate(db_session, org, setup, window_end=NOW)
    for finding in _findings(db_session, setup):
        assert finding.attribution["connector"] is None
        assert "no runtime-to-integration dependency link" in \
            finding.attribution["connector_attribution"]


def test_ac06_the_behavior_package_never_reaches_for_integration_data() -> None:
    """AC-06 — the gap is not worked around. Nothing here imports the
    integration domain, which is what keeps the runtime-never-knows boundary
    intact rather than merely respected."""
    for path in (BACKEND_ROOT / "app" / "behavior").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("app.integration"), path.name
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("app.integration"), path.name


# --------------------------------------------------------------------------- #
# AC-07 / AC-08 — signal, not enforcement; non-gating
# --------------------------------------------------------------------------- #
def test_ac07_the_behavior_package_cannot_stop_an_execution() -> None:
    """AC-07 — **the one-enforcement-path proof for Phase 4.5**, the same shape
    Phase 4.4 gave for budgets. A finding is a signal; 4.3's engine remains the
    only thing that can halt a running agent."""
    execution_states = {
        "QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTERED",
        "TIMED_OUT", "BLOCKED", "DENIED", "REJECTED", "PENDING_APPROVAL",
    }
    forbidden_calls = {"_set_execution_status", "activate", "activate_system", "enforce"}
    for path in (BACKEND_ROOT / "app" / "behavior").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute):
                        assert target.attr not in ("status", "cancel_requested",
                                                   "lifecycle_status", "termination_reason"), \
                            f"{path.name} writes execution lifecycle state"
                if isinstance(node.value, ast.Constant) and node.value.value in execution_states:
                    raise AssertionError(f"{path.name} assigns execution state "
                                         f"{node.value.value!r}")
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                assert name not in forbidden_calls, f"{path.name} calls {name}"
            if isinstance(node, ast.Name):
                assert node.id not in ("GovernanceStopped", "KillSwitchService",
                                       "RuntimeGovernanceEngine"), \
                    f"{path.name} reaches for an enforcement mechanism"


def test_ac07_an_anomalous_finding_leaves_the_execution_stream_untouched(
        client: TestClient, db_session: Session) -> None:
    """AC-07 — behaviourally, not just structurally: evaluating an agent whose
    behavior is wildly anomalous changes nothing about its executions."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    _seed(db_session, setup, org, count=30, at=IN_BASELINE)
    rows = _seed(db_session, setup, org, count=30, at=IN_WINDOW, status="FAILED",
                 error_code="BOOM", termination_reason=None)

    before = db_session.execute(
        select(AgentExecution.id, AgentExecution.status, AgentExecution.updated_at,
               AgentExecution.termination_reason)
        .where(AgentExecution.agent_id == uuid.UUID(setup["agent"]["id"]))
        .order_by(AgentExecution.id)).all()

    result = _evaluate(db_session, org, setup, window_end=NOW)
    assert any(s.state is SignalState.ANOMALOUS for s in result.results)

    db_session.expire_all()
    after = db_session.execute(
        select(AgentExecution.id, AgentExecution.status, AgentExecution.updated_at,
               AgentExecution.termination_reason)
        .where(AgentExecution.agent_id == uuid.UUID(setup["agent"]["id"]))
        .order_by(AgentExecution.id)).all()
    assert before == after
    assert len(rows) == 30


def test_ac08_an_evaluation_failure_produces_no_finding_and_stops_nothing(
        client: TestClient, db_session: Session, monkeypatch) -> None:
    """AC-08 — non-gating (§9). Behavioral signals are telemetry-plane, and the
    telemetry plane fails **open**: a broken evaluation loses a signal, never an
    execution. The deliberate inverse of Phase 4.3's governance plane."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    _seed(db_session, setup, org, count=30, at=IN_BASELINE)
    _seed(db_session, setup, org, count=30, at=IN_WINDOW)

    from app.behavior import engine as engine_module

    def _explode(self, *a, **k):
        raise RuntimeError("the aggregation dependency is unreachable")

    monkeypatch.setattr(engine_module.BehavioralEvaluator, "_aggregate", _explode)

    agent = db_session.get(Agent, uuid.UUID(setup["agent"]["id"]))
    with pytest.raises(RuntimeError):
        BehavioralEvaluator(db_session).evaluate(
            organization_id=uuid.UUID(org["organization_id"]), agent=agent, window_end=NOW)
    db_session.rollback()

    assert _findings(db_session, setup) == []
    # The executions are untouched: a failed evaluation is not an execution
    # event at all.
    remaining = db_session.execute(
        select(func.count(AgentExecution.id)).where(
            AgentExecution.agent_id == uuid.UUID(setup["agent"]["id"]))).scalar_one()
    assert remaining == 60


def test_ac08_the_evaluate_route_never_touches_an_execution() -> None:
    """AC-08 — no route in this package can reach the execution path."""
    source = (BACKEND_ROOT / "app" / "behavior" / "routes.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            assert node.id not in ("ExecutionWorkerService", "ToolLoopOrchestrator"), \
                "a behavior route reaches the execution path"


# --------------------------------------------------------------------------- #
# AC-09 / AC-10 — persistence and idempotency
# --------------------------------------------------------------------------- #
def test_ac09_normal_windows_produce_no_finding(
        client: TestClient, db_session: Session) -> None:
    """AC-09 — recording every quiet window would bury the ones that matter,
    the materiality reasoning Phase 4.3 applied to governance decisions."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    _seed(db_session, setup, org, count=30, at=IN_BASELINE, duration_ms=100, cost=0.01)
    _seed(db_session, setup, org, count=30, at=IN_WINDOW, duration_ms=105, cost=0.011)

    result = _evaluate(db_session, org, setup, window_end=NOW)
    assert {s.state for s in result.results} == {SignalState.NORMAL}
    assert _findings(db_session, setup) == []


def test_ac10_re_running_the_same_window_produces_one_finding(
        client: TestClient, db_session: Session) -> None:
    """AC-10 — the Phase 3.8 scheduler will re-run overlapping windows and
    retry failed runs. The dedup key is enforced by a unique constraint rather
    than by checking first, the same reasoning Phase 4.4 used for reservations."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    _seed(db_session, setup, org, count=30, at=IN_BASELINE)
    _seed(db_session, setup, org, count=15, at=IN_WINDOW)
    _seed(db_session, setup, org, count=15, at=IN_WINDOW, status="FAILED",
          error_code="BOOM", termination_reason=None)

    for _ in range(4):
        _evaluate(db_session, org, setup, window_end=NOW)

    findings = _findings(db_session, setup)
    keys = [(f.signal_type, f.window_start, f.window_end) for f in findings]
    assert len(keys) == len(set(keys)), "the same window produced duplicate findings"


def test_ac10_the_dedup_key_is_enforced_by_the_database(
        client: TestClient, db_session: Session) -> None:
    """AC-10 — a promise the application could forget vs a constraint it
    cannot."""
    from sqlalchemy.exc import IntegrityError

    org = _register_org(client)
    setup = _agent_setup(client, org)
    common = dict(
        organization_id=uuid.UUID(org["organization_id"]),
        agent_id=uuid.UUID(setup["agent"]["id"]),
        signal_type="error_rate_shift", state="ANOMALOUS", metric="error_rate",
        window_start=IN_WINDOW, window_end=NOW, sample_count=10,
        attribution={}, explanation={},
    )
    db_session.add(BehavioralFinding(**common))
    db_session.commit()
    db_session.add(BehavioralFinding(**common))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


# --------------------------------------------------------------------------- #
# AC-11 / AC-13 — isolation and authorization
# --------------------------------------------------------------------------- #
def test_ac11_findings_are_tenant_isolated(
        client: TestClient, db_session: Session) -> None:
    org = _register_org(client, "Owner Org")
    setup = _agent_setup(client, org)
    _seed(db_session, setup, org, count=30, at=IN_BASELINE)
    _seed(db_session, setup, org, count=15, at=IN_WINDOW)
    _seed(db_session, setup, org, count=15, at=IN_WINDOW, status="FAILED",
          error_code="BOOM", termination_reason=None)
    _evaluate(db_session, org, setup, window_end=NOW)

    mine = client.get(f"{RT}/behavior/findings", headers=org["headers"]).json()
    assert mine, "the owner cannot see their own findings"

    stranger = _register_org(client, "Stranger Org")
    theirs = client.get(f"{RT}/behavior/findings", headers=stranger["headers"]).json()
    assert theirs == []


def test_ac11_no_signal_aggregates_across_tenants(
        client: TestClient, db_session: Session) -> None:
    """AC-11 — the tenant predicate is part of the aggregation, not a filter
    applied afterwards, so a colliding agent id could not pull in another
    tenant's rows."""
    org = _register_org(client, "Owner Org")
    setup = _agent_setup(client, org)
    _seed(db_session, setup, org, count=30, at=IN_WINDOW)

    other = _register_org(client, "Other Org")
    result = BehavioralEvaluator(db_session).evaluate(
        organization_id=uuid.UUID(other["organization_id"]),
        agent=db_session.get(Agent, uuid.UUID(setup["agent"]["id"])),
        window_end=NOW, persist=False)
    assert result.candidate.sample_count == 0


def test_ac13_behavior_endpoints_require_their_permission(client: TestClient) -> None:
    """AC-13 — and the permission is the pre-existing one, reused rather than
    shadowed by a synonym (the reasoning Phases 4.2 and 4.4 both applied)."""
    from app.services.rbac_service import PERMISSION_CATALOG

    assert "runtime.telemetry.view" in PERMISSION_CATALOG
    assert "runtime.behavior.view" not in PERMISSION_CATALOG, \
        "a synonym permission was registered for a capability that already had one"

    assert client.get(f"{RT}/behavior/findings").status_code in (401, 403)
    assert client.post(f"{RT}/behavior/evaluate",
                       json={"agent_id": str(uuid.uuid4())}).status_code in (401, 403)


def test_ac13_a_cross_tenant_agent_is_not_found(
        client: TestClient, db_session: Session) -> None:
    """AC-13/§34 — refusing to confirm existence, not merely to read."""
    owner = _register_org(client, "Owner Org")
    setup = _agent_setup(client, owner)
    stranger = _register_org(client, "Stranger Org")

    seen = client.get(f"{RT}/agents/{setup['agent']['id']}/behavior",
                      headers=stranger["headers"])
    assert seen.status_code == 404
    missing = client.get(f"{RT}/agents/{uuid.uuid4()}/behavior", headers=stranger["headers"])
    assert missing.json()["error"]["code"] == seen.json()["error"]["code"]

    evaluated = client.post(f"{RT}/behavior/evaluate", headers=stranger["headers"],
                            json={"agent_id": setup["agent"]["id"]})
    assert evaluated.status_code == 404


def test_ac13_the_evaluate_route_is_idempotent(
        client: TestClient, db_session: Session) -> None:
    """AC-10/AC-13 — idempotent at the request layer too, so the Phase 3.8
    scheduler can adopt it as a registration rather than a rewrite."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    _seed(db_session, setup, org, count=30, at=IN_WINDOW)

    key = str(uuid.uuid4())
    body = {"agent_id": setup["agent"]["id"]}
    first = client.post(f"{RT}/behavior/evaluate",
                        headers={**org["headers"], "Idempotency-Key": key}, json=body)
    second = client.post(f"{RT}/behavior/evaluate",
                         headers={**org["headers"], "Idempotency-Key": key}, json=body)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["window_start"] == second.json()["window_start"]


def test_ac09_an_unknown_signal_filter_is_refused(client: TestClient) -> None:
    org = _register_org(client)
    r = client.get(f"{RT}/behavior/findings", headers=org["headers"],
                   params={"signal_type": "vibes"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


# --------------------------------------------------------------------------- #
# AC-12 — bounded and indexed
# --------------------------------------------------------------------------- #
def test_ac12_the_window_aggregate_reaches_its_rows_through_indexes(
        client: TestClient, db_session: Session) -> None:
    """AC-12 — no sequential scan of ``agent_executions``.

    The interesting part is *which* indexes: no composite covers
    ``(organization_id, agent_id, created_at)``, and Postgres does not need one
    — it combines Phase 4.2's tenant+recency index with Milestone 1's
    ``agent_id`` index via ``BitmapAnd``. That measurement is why this phase
    added no index."""
    busiest = db_session.execute(
        select(AgentExecution.organization_id, AgentExecution.agent_id,
               func.count(AgentExecution.id))
        .group_by(AgentExecution.organization_id, AgentExecution.agent_id)
        .order_by(func.count(AgentExecution.id).desc()).limit(1)
    ).first()
    assert busiest is not None and busiest[2] >= 50

    plan = "\n".join(row[0] for row in db_session.execute(text(
        "EXPLAIN (ANALYZE, BUFFERS) "
        "SELECT count(id), avg(duration_ms) FROM agent_executions "
        "WHERE organization_id = :org AND agent_id = :agent "
        "AND created_at >= now() - interval '7 days'"
    ), {"org": busiest[0], "agent": busiest[1]}))

    assert "Seq Scan on agent_executions" not in plan, plan
    assert "Index Scan" in plan or "Bitmap Index Scan" in plan, plan


def test_ac12_the_window_is_bounded(client: TestClient, db_session: Session) -> None:
    """AC-12 — an evaluation cannot be asked to scan an agent's whole history."""
    org = _register_org(client)
    setup = _agent_setup(client, org)
    r = client.post(f"{RT}/behavior/evaluate", headers=org["headers"],
                    json={"agent_id": setup["agent"]["id"], "window_days": 900})
    assert r.status_code == 422  # rejected at the schema

    result = _evaluate(db_session, org, setup, window_end=NOW, persist=False)
    assert result.window_end - result.window_start == DEFAULT_WINDOW


# --------------------------------------------------------------------------- #
# AC-14 — the 4.4 / 4.5 boundary
# --------------------------------------------------------------------------- #
def test_ac14_cost_drift_and_spend_anomaly_are_orthogonal(
        client: TestClient, db_session: Session) -> None:
    """AC-14 — **the boundary, demonstrated in both directions.**

    Phase 4.4 asks *"did this tenant spend more money this period than usual?"*
    — absolute dollars, tenant-scoped, a FinOps question. This asks *"did this
    agent start costing more per run?"* — normalized per unit of work,
    agent-scoped, a behavioral question. They are not the same question, and
    each fires where the other is silent:

    **Case A** — per-execution cost doubles while traffic halves. Total spend
    is flat, so 4.4 sees nothing; the agent got twice as expensive per run, so
    4.5 does.
    """
    from app.finops.aggregation import CostAggregator, CostFilters

    org = _register_org(client)
    setup = _agent_setup(client, org)
    # Baseline: 40 executions at 0.01 = 0.40 total.
    _seed(db_session, setup, org, count=40, at=IN_BASELINE, cost=0.01)
    # Candidate: 20 executions at 0.02 = 0.40 total. Same money, double the rate.
    _seed(db_session, setup, org, count=20, at=IN_WINDOW, cost=0.02)

    drift = _signal(_evaluate(db_session, org, setup, window_end=NOW, persist=False),
                    "cost_drift")
    assert drift.observed == pytest.approx(0.02)
    assert drift.baseline == pytest.approx(0.01)
    assert drift.state is SignalState.DEGRADED, "4.5 must see the per-run change"

    anomalies = CostAggregator(db_session).anomalies(
        uuid.UUID(org["organization_id"]),
        filters=CostFilters(started_after=NOW - timedelta(days=30), started_before=NOW),
        threshold_ratio=1.5)
    assert anomalies == (), "4.4 must see no spend anomaly -- the total did not move"


def test_ac14_a_traffic_spike_is_a_spend_anomaly_but_not_a_cost_drift(
        client: TestClient, db_session: Session) -> None:
    """AC-14 — **Case B**, the mirror image. Traffic multiplies at an unchanged
    per-execution cost: 4.4 sees the spend spike, 4.5 correctly sees no
    behavioral change, because the agent is behaving exactly as it always did —
    there is just more of it."""
    from app.finops.aggregation import CostAggregator, CostFilters

    org = _register_org(client)
    setup = _agent_setup(client, org)
    for days_ago in (12, 11, 10, 9):
        _seed(db_session, setup, org, count=10, at=NOW - timedelta(days=days_ago), cost=0.01)
    _seed(db_session, setup, org, count=200, at=NOW - timedelta(days=2), cost=0.01)

    drift = _signal(_evaluate(db_session, org, setup, window_end=NOW, persist=False),
                    "cost_drift")
    assert drift.state is SignalState.NORMAL, "per-execution cost did not change"

    anomalies = CostAggregator(db_session).anomalies(
        uuid.UUID(org["organization_id"]),
        filters=CostFilters(started_after=NOW - timedelta(days=30), started_before=NOW),
        threshold_ratio=3.0)
    assert anomalies, "4.4 must see the spend spike"


def test_ac14_the_behavior_package_does_not_reimplement_cost_aggregation() -> None:
    """AC-14 — complementary, not duplicated. The behavioral cost metric is an
    average over the same authoritative column, computed in the window
    aggregate this engine already runs; it does not import 4.4's read model and
    4.4 does not import this one."""
    for path in (BACKEND_ROOT / "app" / "behavior").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("app.finops"), \
                    f"{path.name} imports the FinOps read model"
    for path in (BACKEND_ROOT / "app" / "finops").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("app.behavior"), path.name


# --------------------------------------------------------------------------- #
# AC-18 — no placeholders
# --------------------------------------------------------------------------- #
def test_ac18_no_todo_fixme_or_skipped_work_in_this_phase() -> None:
    """AC-18. Markers are concatenated because this file is one of the files
    being scanned."""
    markers = ("TO" + "DO", "FIX" + "ME", "NotImplemented" + "Error",
               "pytest.mark." + "skip", "pytest.mark." + "xfail")
    paths = list((BACKEND_ROOT / "app" / "behavior").rglob("*.py"))
    paths.append(BACKEND_ROOT / "migrations" / "versions" / "0049_behavioral_signals.py")
    paths.append(Path(__file__))
    for path in paths:
        source = path.read_text(encoding="utf-8")
        for marker in markers:
            assert marker not in source, f"{path.name} contains {marker}"


def test_ac18_the_states_module_imports_no_database_layer() -> None:
    """The vocabulary is readable and testable without a database — the
    discipline Phase 4.1 applied to ``observability.trace`` and 4.3 to
    ``governance.contract``."""
    source = (BACKEND_ROOT / "app" / "behavior" / "states.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "") in ("enum", "__future__"), node.module
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name == "enum", alias.name


def test_reportable_states_exclude_normal_only() -> None:
    assert SignalState.NORMAL not in REPORTABLE_STATES
    assert REPORTABLE_STATES == {
        SignalState.DEGRADED, SignalState.ANOMALOUS,
        SignalState.INSUFFICIENT_DATA, SignalState.UNKNOWN}


def test_window_metrics_rates_are_zero_safe() -> None:
    """An empty window divides by nothing rather than raising — a metric that
    crashed on a quiet agent would make the whole evaluation fail closed, which
    is the wrong posture for a telemetry-plane signal."""
    empty = WindowMetrics()
    assert empty.error_rate == 0.0
    assert empty.denial_rate == 0.0
    assert empty.cap_termination_rate == 0.0
    assert empty.tool_call_count == 0
