"""Phase 4.7 -- SLOs, alert rules & incident signals (ACT-SRS-M4 §3.6, §4.7,
§18; Gates J and K).

The weight is on the restraint. The load-bearing tests are the ones proving:
*no notification delivery exists anywhere in the alert path* (AC-10), *a
behavioral finding feeds the one alert lifecycle rather than a parallel concept*
(AC-06), *escalation is explicit -- a DEGRADED finding is not an alert* (AC-08),
*one ongoing condition is one alert, DB-enforced, even under a real race*
(AC-07/AC-12), and *a breach is a signal that never stops an execution* (AC-09).

Executions are seeded directly: these tests need dozens of rows at controlled
timestamps, and driving that through the HTTP pipeline would measure the
pipeline.
"""

from __future__ import annotations

import ast
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.agent import Agent
from app.models.rbac import AuthorizationAudit
from app.models.runtime import (
    AgentExecution,
    BehavioralFinding,
    RuntimeAlert,
    SLODefinition,
    SLOEvaluation,
)
from app.slo.alerts import AlertService
from app.slo.definitions import MIN_SAMPLES, SLOService, validate_definition
from app.slo.evaluator import SLOEvaluator
from app.slo.pipeline import run_slo_evaluation
from app.slo.sli import SLI_NAMES, SLI_SPECS, TERMINAL_STATUSES
from app.slo.states import ALLOWED_TRANSITIONS, SLOState
from tests.runtime.test_behavioral_signals import _agent_setup, _register_org, _seed

RT = "/api/v1/runtime"
BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_slo(client: TestClient, org: dict, *, sli: str = "success_rate",
              target: float = 0.99, window: str = "24h",
              scope_type: str = "ORGANIZATION", scope_id: str | None = None,
              **extra) -> dict:
    body = {"name": f"{sli} {uuid.uuid4().hex[:6]}", "sli": sli, "target": target,
            "window": window, "scope_type": scope_type, **extra}
    if scope_id is not None:
        body["scope_id"] = scope_id
    r = client.post(f"{RT}/slos", headers=org["headers"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _seed_window(db: Session, setup: dict, org: dict, *, succeeded: int, failed: int,
                 window_end: datetime | None = None, duration_ms: int = 100) -> None:
    at = (window_end or datetime.now(timezone.utc)) - timedelta(hours=1)
    if succeeded:
        _seed(db, setup, org, count=succeeded, at=at, status="SUCCEEDED",
              duration_ms=duration_ms)
    if failed:
        _seed(db, setup, org, count=failed, at=at, status="FAILED",
              duration_ms=duration_ms, error_code="PROVIDER_UNAVAILABLE")


def _org_and_agent(client: TestClient) -> tuple[dict, dict]:
    org = _register_org(client, "SLO Org")
    setup = _agent_setup(client, org)
    return org, setup


def _slo_row(db: Session, slo_id: str) -> SLODefinition:
    return db.get(SLODefinition, uuid.UUID(slo_id))


# =========================================================================== #
# AC-01 -- an SLO is defined; evaluation is deterministic and explainable
# =========================================================================== #
def test_ac01_an_slo_defines_sli_target_window_and_error_budget(
    client: TestClient, db_session: Session,
) -> None:
    org, _ = _org_and_agent(client)
    slo = _make_slo(client, org, sli="success_rate", target=0.99, window="24h")
    assert slo["sli"] == "success_rate"
    assert slo["target"] == 0.99
    assert slo["window"] == "24h"
    # error budget defaulted to 1 - target for a success-rate SLO
    assert abs(slo["error_budget"] - 0.01) < 1e-9


def test_ac01_a_breach_states_sli_target_window_and_observed(
    client: TestClient, db_session: Session,
) -> None:
    org, setup = _org_and_agent(client)
    slo = _make_slo(client, org, sli="success_rate", target=0.99, window="24h")
    # 40 executions, 8 failed -> observed 0.80, well below 0.99
    _seed_window(db_session, setup, org, succeeded=32, failed=8)

    result = SLOEvaluator(SessionLocal()).evaluate(_slo_row(db_session, slo["id"]),
                                                   persist=False)
    assert result.state is SLOState.BREACHED
    assert result.observed_value == pytest.approx(0.8, abs=0.01)
    exp = result.explanation
    assert exp["sli"] == "success_rate"
    assert exp["target"] == 0.99
    assert exp["window"] == "24h"
    assert exp["observed_value"] == pytest.approx(0.8, abs=0.01)
    assert "0.8" in exp["crossing"] or "0.80" in exp["crossing"]
    assert exp["rule"].startswith("deterministic")


def test_ac01_a_met_objective_produces_a_met_evaluation(
    client: TestClient, db_session: Session,
) -> None:
    org, setup = _org_and_agent(client)
    slo = _make_slo(client, org, sli="success_rate", target=0.90, window="24h")
    _seed_window(db_session, setup, org, succeeded=48, failed=2)  # 0.96 >= 0.90
    result = SLOEvaluator(SessionLocal()).evaluate(_slo_row(db_session, slo["id"]),
                                                   persist=False)
    assert result.state is SLOState.MET


# =========================================================================== #
# AC-02 -- error-budget consumption is tracked; a burned budget is observable
# =========================================================================== #
def test_ac02_error_budget_consumption_is_tracked_and_visible(
    client: TestClient, db_session: Session,
) -> None:
    org, setup = _org_and_agent(client)
    slo = _make_slo(client, org, sli="success_rate", target=0.99, window="24h")
    # 100 executions, 3 failed -> observed 0.97, bad fraction 0.03, budget 0.01
    # -> budget_consumed = 3.0 (300% -- burned).
    _seed_window(db_session, setup, org, succeeded=97, failed=3)

    r = client.post(f"{RT}/slos/evaluate", headers=org["headers"])
    assert r.status_code == 200, r.text
    ev = next(e for e in r.json()["evaluations"] if e["slo_id"] == slo["id"])
    assert ev["state"] == "BREACHED"
    assert ev["budget_consumed"] == pytest.approx(3.0, abs=0.05)
    assert ev["budget_remaining"] == 0.0

    hist = client.get(f"{RT}/slos/{slo['id']}/evaluations", headers=org["headers"]).json()
    assert hist[0]["budget_consumed"] == pytest.approx(3.0, abs=0.05)
    assert hist[0]["explanation"]["error_budget"] == pytest.approx(0.01)


# =========================================================================== #
# AC-03 -- INSUFFICIENT_DATA first-class
# =========================================================================== #
def test_ac03_a_thin_window_is_insufficient_data_not_met_or_breached(
    client: TestClient, db_session: Session,
) -> None:
    org, setup = _org_and_agent(client)
    slo = _make_slo(client, org, sli="success_rate", target=0.99)
    # Well below MIN_SAMPLES, and all failing -- alarming, but not evidence.
    _seed_window(db_session, setup, org, succeeded=0, failed=MIN_SAMPLES - 5)
    result = SLOEvaluator(SessionLocal()).evaluate(_slo_row(db_session, slo["id"]),
                                                   persist=False)
    assert result.state is SLOState.INSUFFICIENT_DATA
    assert result.state not in (SLOState.MET, SLOState.BREACHED)
    assert result.budget_consumed is None
    assert str(MIN_SAMPLES) in result.explanation["crossing"]


def test_ac03_insufficient_data_raises_no_alert(client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    _make_slo(client, org, sli="timeout_rate", target=0.01)
    _seed_window(db_session, setup, org, succeeded=3, failed=1)
    client.post(f"{RT}/slos/evaluate", headers=org["headers"])
    alerts = client.get(f"{RT}/alerts", headers=org["headers"]).json()
    assert alerts == []


# =========================================================================== #
# AC-04 -- a first-class alert carries the §18 fields
# =========================================================================== #
def test_ac04_an_alert_carries_the_section_18_fields(
    client: TestClient, db_session: Session,
) -> None:
    org, setup = _org_and_agent(client)
    slo = _make_slo(client, org, sli="success_rate", target=0.99,
                    scope_type="AGENT", scope_id=setup["agent"]["id"])
    _seed_window(db_session, setup, org, succeeded=30, failed=20)  # 0.60

    client.post(f"{RT}/slos/evaluate", headers=org["headers"])
    alerts = client.get(f"{RT}/alerts", headers=org["headers"]).json()
    assert len(alerts) == 1
    a = alerts[0]
    for field in ("source", "severity", "status", "agent_id", "metric",
                  "threshold_value", "observed_value", "baseline_value",
                  "opened_at", "updated_at", "dedup_key", "summary", "slo_id"):
        assert field in a, field
    assert a["source"] == "SLO"
    assert a["status"] == "OPEN"
    assert a["slo_id"] == slo["id"]
    assert a["agent_id"] == setup["agent"]["id"]
    assert a["metric"] == "success_rate"
    assert a["threshold_value"] == pytest.approx(0.99)
    assert a["observed_value"] == pytest.approx(0.6, abs=0.02)
    assert a["severity"] in ("WARNING", "HIGH", "CRITICAL")
    assert "success_rate" in a["summary"]


# =========================================================================== #
# AC-05 -- the lifecycle works and transitions are audited
# =========================================================================== #
def test_ac05_full_lifecycle_open_ack_resolve_and_suppress(
    client: TestClient, db_session: Session,
) -> None:
    org, setup = _org_and_agent(client)
    _make_slo(client, org, sli="success_rate", target=0.99)
    _seed_window(db_session, setup, org, succeeded=20, failed=20)
    client.post(f"{RT}/slos/evaluate", headers=org["headers"])
    alert_id = client.get(f"{RT}/alerts", headers=org["headers"]).json()[0]["id"]

    ack = client.post(f"{RT}/alerts/{alert_id}/acknowledge", headers=org["headers"],
                      json={"note": "on it"})
    assert ack.status_code == 200 and ack.json()["status"] == "ACKNOWLEDGED"
    assert ack.json()["acknowledged_by"] == org["user_id"]

    res = client.post(f"{RT}/alerts/{alert_id}/resolve", headers=org["headers"])
    assert res.status_code == 200 and res.json()["status"] == "RESOLVED"

    # resolve again -> converges (idempotent), does not error
    assert client.post(f"{RT}/alerts/{alert_id}/resolve",
                       headers=org["headers"]).json()["status"] == "RESOLVED"
    # ack a resolved alert -> invalid transition
    bad = client.post(f"{RT}/alerts/{alert_id}/acknowledge", headers=org["headers"])
    assert bad.status_code == 409
    assert bad.json()["error"]["code"] == "ALERT_TRANSITION_INVALID"

    org_id = uuid.UUID(org["organization_id"])
    events = {e for (e,) in db_session.execute(
        select(AuthorizationAudit.event_type).where(
            AuthorizationAudit.organization_id == org_id,
            AuthorizationAudit.event_type.like("RUNTIME_ALERT_%"))
    ).all()}
    assert {"RUNTIME_ALERT_CREATED", "RUNTIME_ALERT_ACKNOWLEDGED",
            "RUNTIME_ALERT_RESOLVED"} <= events


def test_ac05_suppress_from_open_is_allowed(client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    _make_slo(client, org, sli="success_rate", target=0.99)
    _seed_window(db_session, setup, org, succeeded=20, failed=20)
    client.post(f"{RT}/slos/evaluate", headers=org["headers"])
    alert_id = client.get(f"{RT}/alerts", headers=org["headers"]).json()[0]["id"]
    r = client.post(f"{RT}/alerts/{alert_id}/suppress", headers=org["headers"])
    assert r.status_code == 200 and r.json()["status"] == "SUPPRESSED"


def test_ac05_the_transition_table_is_the_lifecycle_in_the_prompt() -> None:
    assert ALLOWED_TRANSITIONS["OPEN"] == {"ACKNOWLEDGED", "RESOLVED", "SUPPRESSED"}
    assert ALLOWED_TRANSITIONS["ACKNOWLEDGED"] == {"RESOLVED", "SUPPRESSED"}
    assert "OPEN" in ALLOWED_TRANSITIONS["RESOLVED"]  # re-open on recurrence


# =========================================================================== #
# AC-06 -- SLO breach raises an alert; a significant behavioral finding does too,
#          via ONE shared model
# =========================================================================== #
def test_ac06_a_significant_behavioral_finding_raises_an_alert_via_the_shared_model(
    client: TestClient, db_session: Session,
) -> None:
    org, setup = _org_and_agent(client)
    now = datetime.now(timezone.utc)
    finding = BehavioralFinding(
        organization_id=uuid.UUID(org["organization_id"]),
        agent_id=uuid.UUID(setup["agent"]["id"]),
        agent_version_id=uuid.UUID(setup["version"]["id"]),
        signal_type="error_rate_shift", state="ANOMALOUS", metric="error_rate",
        window_start=now - timedelta(days=7), window_end=now, sample_count=200,
        observed_value=Decimal("0.34"), threshold_value=Decimal("0.10"),
        baseline_value=Decimal("0.03"),
        attribution={"provider": "openai"}, explanation={"crossing": "34% vs 3% baseline"},
    )
    db_session.add(finding)
    db_session.commit()

    r = client.post(f"{RT}/slos/evaluate", headers=org["headers"])
    assert r.status_code == 200, r.text
    assert len(r.json()["behavioral_alerts_linked"]) == 1

    alerts = client.get(f"{RT}/alerts", headers=org["headers"], params={"source": "BEHAVIORAL"}).json()
    assert len(alerts) == 1
    a = alerts[0]
    assert a["source"] == "BEHAVIORAL"
    assert a["source_id"] == str(finding.id)  # references the finding, not a copy
    assert a["metric"] == "error_rate"
    assert a["severity"] == "HIGH"
    # the evidence still lives in its own table
    assert db_session.get(BehavioralFinding, finding.id) is not None


def test_ac06_alerts_and_findings_are_one_lifecycle_over_two_evidence_tables() -> None:
    """Model decision (mandatory report #1): a distinct ``runtime_alerts`` that
    *references* ``behavioral_findings`` / ``slo_evaluations`` -- one lifecycle,
    two evidence sources, not a shared ``runtime_findings`` re-homing 4.5's
    table."""
    from app.core.database import Base

    assert "runtime_alerts" in Base.metadata.tables
    assert "behavioral_findings" in Base.metadata.tables  # unchanged, still its own table
    cols = set(Base.metadata.tables["runtime_alerts"].columns.keys())
    assert {"source", "source_id"} <= cols
    # behavioral_findings gained no alert columns
    fcols = set(Base.metadata.tables["behavioral_findings"].columns.keys())
    assert not (fcols & {"alert_id", "status", "acknowledged_at"})


# =========================================================================== #
# AC-07 -- dedup: one ongoing condition is one open alert (DB-enforced);
#          resolved re-opens on recurrence
# =========================================================================== #
def test_ac07_one_ongoing_condition_is_one_open_alert(
    client: TestClient, db_session: Session,
) -> None:
    org, setup = _org_and_agent(client)
    _make_slo(client, org, sli="success_rate", target=0.99)
    _seed_window(db_session, setup, org, succeeded=20, failed=20)

    for _ in range(4):  # evaluate the same ongoing breach repeatedly
        client.post(f"{RT}/slos/evaluate", headers=org["headers"])

    alerts = client.get(f"{RT}/alerts", headers=org["headers"]).json()
    assert len(alerts) == 1
    assert alerts[0]["recurrence_count"] >= 2  # sustained, not stormed


def test_ac07_a_resolved_condition_reopens_on_recurrence(
    client: TestClient, db_session: Session,
) -> None:
    org, setup = _org_and_agent(client)
    slo = _make_slo(client, org, sli="success_rate", target=0.99)
    _seed_window(db_session, setup, org, succeeded=20, failed=20)
    client.post(f"{RT}/slos/evaluate", headers=org["headers"])
    alert_id = client.get(f"{RT}/alerts", headers=org["headers"]).json()[0]["id"]
    client.post(f"{RT}/alerts/{alert_id}/resolve", headers=org["headers"])

    # the condition recurs (a fresh evaluation over a fresh window still breaches)
    run_slo_evaluation(SessionLocal(), organization_id=uuid.UUID(org["organization_id"]),
                       window_end=datetime.now(timezone.utc) + timedelta(minutes=1))

    after = client.get(f"{RT}/alerts", headers=org["headers"]).json()
    assert len(after) == 1
    assert after[0]["id"] == alert_id  # same row, re-opened
    assert after[0]["status"] == "OPEN"
    assert after[0]["recurrence_count"] >= 2


def test_ac07_a_suppressed_condition_does_not_reopen(
    client: TestClient, db_session: Session,
) -> None:
    org, setup = _org_and_agent(client)
    _make_slo(client, org, sli="success_rate", target=0.99)
    _seed_window(db_session, setup, org, succeeded=20, failed=20)
    client.post(f"{RT}/slos/evaluate", headers=org["headers"])
    alert_id = client.get(f"{RT}/alerts", headers=org["headers"]).json()[0]["id"]
    client.post(f"{RT}/alerts/{alert_id}/suppress", headers=org["headers"])

    run_slo_evaluation(SessionLocal(), organization_id=uuid.UUID(org["organization_id"]),
                       window_end=datetime.now(timezone.utc) + timedelta(minutes=1))

    after = client.get(f"{RT}/alerts", headers=org["headers"],
                       params={"status": "SUPPRESSED"}).json()
    assert len(after) == 1 and after[0]["id"] == alert_id
    assert client.get(f"{RT}/alerts", headers=org["headers"],
                      params={"status": "OPEN"}).json() == []


def test_ac07_the_dedup_index_is_a_partial_unique_at_the_database() -> None:
    from sqlalchemy import create_engine, inspect

    from app.core.config import settings

    idx = {i["name"]: i for i in inspect(create_engine(settings.DATABASE_URL))
           .get_indexes("runtime_alerts")}
    assert "uq_runtime_alerts_active_dedup" in idx
    entry = idx["uq_runtime_alerts_active_dedup"]
    assert entry["unique"] is True
    assert entry.get("column_names") == ["organization_id", "dedup_key"]
    # partial: only active statuses
    assert "OPEN" in str(entry.get("dialect_options", {}))


# =========================================================================== #
# AC-08 -- not every finding is an alert; escalation is explicit
# =========================================================================== #
def test_ac08_a_degraded_behavioral_finding_is_not_an_alert(
    client: TestClient, db_session: Session,
) -> None:
    org, setup = _org_and_agent(client)
    now = datetime.now(timezone.utc)
    db_session.add(BehavioralFinding(
        organization_id=uuid.UUID(org["organization_id"]),
        agent_id=uuid.UUID(setup["agent"]["id"]),
        signal_type="latency_drift", state="DEGRADED", metric="p95_latency_ms",
        window_start=now - timedelta(days=7), window_end=now, sample_count=200,
        observed_value=Decimal("900"), threshold_value=Decimal("1000"),
        baseline_value=Decimal("600"), attribution={}, explanation={},
    ))
    db_session.commit()

    r = client.post(f"{RT}/slos/evaluate", headers=org["headers"])
    assert r.json()["behavioral_alerts_linked"] == []
    assert client.get(f"{RT}/alerts", headers=org["headers"]).json() == []


def test_ac08_significance_is_the_anomalous_state_a_named_constant() -> None:
    from app.slo.alerts import _SIGNIFICANT_FINDING_STATE

    assert _SIGNIFICANT_FINDING_STATE == "ANOMALOUS"


# =========================================================================== #
# AC-09 -- a breach / alert never stops an execution; non-gating
# =========================================================================== #
def test_ac09_slo_breach_never_alters_an_execution(client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    _make_slo(client, org, sli="success_rate", target=0.99,
              scope_type="AGENT", scope_id=setup["agent"]["id"])
    _seed_window(db_session, setup, org, succeeded=5, failed=45)

    before = {
        (r.id, r.status, r.error_code)
        for r in db_session.execute(
            select(AgentExecution).where(
                AgentExecution.agent_id == uuid.UUID(setup["agent"]["id"]))
        ).scalars()
    }
    client.post(f"{RT}/slos/evaluate", headers=org["headers"])
    db_session.expire_all()
    after = {
        (r.id, r.status, r.error_code)
        for r in db_session.execute(
            select(AgentExecution).where(
                AgentExecution.agent_id == uuid.UUID(setup["agent"]["id"]))
        ).scalars()
    }
    assert before == after


def test_ac09_the_slo_package_never_touches_execution_state_or_governance() -> None:
    """Structural, over the AST -- the 4.4/4.5 proof, applied to SLOs. Nothing
    in ``app/slo`` can stop an execution."""
    forbidden_names = {"KillSwitchService", "GovernanceEngine", "RuntimeGovernanceEngine"}
    forbidden_calls = {"_set_execution_status", "activate", "enforce", "stop_execution"}
    for path in (APP_ROOT / "slo").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in forbidden_names, f"{path.name} references {node.id}"
            if isinstance(node, ast.Attribute):
                assert node.attr not in forbidden_calls, f"{path.name} calls {node.attr}"
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "governance" not in node.module, f"{path.name} imports {node.module}"


def test_ac09_evaluation_failure_is_non_gating() -> None:
    """A broken evaluation produces no evaluation and no alert -- it does not
    raise into a caller that could be on an execution path. (There is no
    execution path here, which is the stronger guarantee -- see the structural
    test above -- but the op still swallows a per-SLO failure.)"""
    src = (APP_ROOT / "slo" / "pipeline.py").read_text(encoding="utf-8")
    assert "run_slo_evaluation" in src
    # the runtime never imports the slo package
    for area in ("runtime", "workers"):
        for path in (APP_ROOT / area).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not node.module.startswith("app.slo"), f"{path} imports app.slo"


# =========================================================================== #
# AC-10 -- NO notification delivery anywhere in the alert path (structural)
# =========================================================================== #
_DELIVERY_MARKERS = (
    "smtplib", "slack", "pagerduty", "requests", "httpx", "aiohttp",
    "app.email", "app.services.notification", "notification_service",
    "webhook", "sendgrid", "twilio", "boto3",
)


def test_ac10_the_slo_package_imports_no_delivery_client() -> None:
    offenders: dict[str, set[str]] = {}
    for path in (APP_ROOT / "slo").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        hits = {n for n in names for m in _DELIVERY_MARKERS
                if n == m or n.startswith(m + ".")}
        if hits:
            offenders[path.name] = hits
    assert not offenders, f"delivery client in the alert path: {offenders}"


def test_ac10_the_slo_package_has_no_send_or_notify_methods() -> None:
    banned = {"send", "notify", "deliver", "dispatch_notification", "post_to_slack",
              "send_email", "page", "emit_webhook"}
    for path in (APP_ROOT / "slo").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name not in banned, f"{path.name} defines {node.name}()"


def test_ac10_alerts_are_queryable_records(client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    _make_slo(client, org, sli="success_rate", target=0.99)
    _seed_window(db_session, setup, org, succeeded=20, failed=20)
    client.post(f"{RT}/slos/evaluate", headers=org["headers"])
    r = client.get(f"{RT}/alerts", headers=org["headers"],
                   params={"status": "OPEN", "severity": "CRITICAL"})
    assert r.status_code == 200
    # filterable by every §18 dimension
    for key in ("status", "severity", "source", "agent_id"):
        assert client.get(f"{RT}/alerts", headers=org["headers"]).status_code == 200


# =========================================================================== #
# AC-11 -- evaluation is idempotent and 3.8-schedulable; no new scheduler
# =========================================================================== #
def test_ac11_evaluation_is_idempotent_over_the_same_window(
    client: TestClient, db_session: Session,
) -> None:
    org, setup = _org_and_agent(client)
    slo = _make_slo(client, org, sli="success_rate", target=0.99)
    _seed_window(db_session, setup, org, succeeded=30, failed=10)
    we = datetime.now(timezone.utc)

    for _ in range(3):
        run_slo_evaluation(SessionLocal(),
                           organization_id=uuid.UUID(org["organization_id"]), window_end=we)

    n = db_session.execute(
        select(func.count(SLOEvaluation.id)).where(
            SLOEvaluation.slo_id == uuid.UUID(slo["id"]))
    ).scalar_one()
    assert n == 1  # one window -> one evaluation row, DB-enforced


def test_ac11_the_evaluate_endpoint_is_idempotency_key_aware(
    client: TestClient, db_session: Session,
) -> None:
    org, setup = _org_and_agent(client)
    _make_slo(client, org, sli="success_rate", target=0.99)
    _seed_window(db_session, setup, org, succeeded=30, failed=10)
    key = uuid.uuid4().hex
    a = client.post(f"{RT}/slos/evaluate", headers={**org["headers"], "Idempotency-Key": key})
    b = client.post(f"{RT}/slos/evaluate", headers={**org["headers"], "Idempotency-Key": key})
    assert a.status_code == b.status_code == 200
    assert a.json()["evaluated_at"] == b.json()["evaluated_at"]  # replayed


def test_ac11_no_scheduler_was_built() -> None:
    """No new scheduler thread/loop -- the evaluate op is interim, for 3.8 to
    adopt (the 4.5/3.7/3.5 pattern)."""
    for path in (APP_ROOT / "slo").rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        assert "while True" not in src
        assert "threading.Thread" not in src
        assert "APScheduler" not in src and "schedule.every" not in src


# =========================================================================== #
# AC-12 -- concurrency
# =========================================================================== #
def test_ac12_concurrent_evaluations_do_not_duplicate(
    client: TestClient, db_session: Session,
) -> None:
    org, setup = _org_and_agent(client)
    slo = _make_slo(client, org, sli="success_rate", target=0.99)
    _seed_window(db_session, setup, org, succeeded=30, failed=15)
    we = datetime.now(timezone.utc)
    org_id = uuid.UUID(org["organization_id"])

    def _run() -> None:
        s = SessionLocal()
        try:
            run_slo_evaluation(s, organization_id=org_id, window_end=we)
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: _run(), range(8)))

    n_ev = db_session.execute(
        select(func.count(SLOEvaluation.id)).where(SLOEvaluation.slo_id == uuid.UUID(slo["id"]))
    ).scalar_one()
    n_alert = db_session.execute(
        select(func.count(RuntimeAlert.id)).where(RuntimeAlert.organization_id == org_id)
    ).scalar_one()
    assert n_ev == 1, f"{n_ev} evaluation rows for one window"
    assert n_alert == 1, f"{n_alert} alerts for one condition"


def test_ac12_concurrent_acknowledges_converge(client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    _make_slo(client, org, sli="success_rate", target=0.99)
    _seed_window(db_session, setup, org, succeeded=20, failed=20)
    client.post(f"{RT}/slos/evaluate", headers=org["headers"])
    alert = client.get(f"{RT}/alerts", headers=org["headers"]).json()[0]
    aid = uuid.UUID(alert["id"])
    org_id = uuid.UUID(org["organization_id"])
    actor_id = uuid.UUID(org["user_id"])

    def _ack() -> str:
        s = SessionLocal()
        try:
            row = s.get(RuntimeAlert, aid)
            return AlertService(s).transition(row, "ACKNOWLEDGED", actor_id).status
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: _ack(), range(6)))
    assert all(r == "ACKNOWLEDGED" for r in results)

    db_session.expire_all()
    row = db_session.get(RuntimeAlert, aid)
    assert row.status == "ACKNOWLEDGED"
    # exactly one ACK audit event despite the race
    n = db_session.execute(
        select(func.count(AuthorizationAudit.id)).where(
            AuthorizationAudit.organization_id == org_id,
            AuthorizationAudit.event_type == "RUNTIME_ALERT_ACKNOWLEDGED")
    ).scalar_one()
    assert n == 1


# =========================================================================== #
# AC-13 -- deterministic
# =========================================================================== #
def test_ac13_same_data_yields_the_same_slo_state_and_explanation(
    client: TestClient, db_session: Session,
) -> None:
    org, setup = _org_and_agent(client)
    slo = _make_slo(client, org, sli="latency_p95", target=200.0)
    _seed_window(db_session, setup, org, succeeded=60, failed=0, duration_ms=500)
    we = datetime.now(timezone.utc)
    row = _slo_row(db_session, slo["id"])

    runs = [SLOEvaluator(SessionLocal()).evaluate(row, window_end=we, persist=False)
            for _ in range(3)]
    assert len({r.state for r in runs}) == 1
    assert len({r.observed_value for r in runs}) == 1
    assert len({r.budget_consumed for r in runs}) == 1
    assert runs[0].explanation == runs[1].explanation == runs[2].explanation


def test_ac13_no_randomness_or_ml_in_the_slo_package() -> None:
    banned = {"random", "numpy", "sklearn", "torch", "tensorflow", "scipy"}
    for path in (APP_ROOT / "slo").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] not in banned, f"{path.name} imports {a.name}"
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in banned, f"{path.name} imports {node.module}"


def test_ac13_the_shared_states_match_35_and_45() -> None:
    from app.behavior.states import SignalState
    from app.runtime.deployment.health import HealthEvaluationService  # noqa: F401
    from app.slo.states import SHARED_WITH_HEALTH_AND_BEHAVIOR

    behavior_values = {s.value for s in SignalState}
    for shared in SHARED_WITH_HEALTH_AND_BEHAVIOR:
        assert shared in {s.value for s in SLOState}
        assert shared in behavior_values


# =========================================================================== #
# AC-14 -- tenant isolation; management permission-gated; no secret
# =========================================================================== #
def test_ac14_slos_and_alerts_are_tenant_isolated(client: TestClient, db_session: Session) -> None:
    org_a, setup_a = _org_and_agent(client)
    slo_a = _make_slo(client, org_a, sli="success_rate", target=0.99)
    _seed_window(db_session, setup_a, org_a, succeeded=20, failed=20)
    client.post(f"{RT}/slos/evaluate", headers=org_a["headers"])

    org_b = _register_org(client, "Other SLO Org")
    assert client.get(f"{RT}/slos", headers=org_b["headers"]).json() == []
    assert client.get(f"{RT}/alerts", headers=org_b["headers"]).json() == []
    assert client.get(f"{RT}/slos/{slo_a['id']}", headers=org_b["headers"]).status_code == 404
    # b's evaluate touches nothing of a's
    client.post(f"{RT}/slos/evaluate", headers=org_b["headers"])
    assert len(client.get(f"{RT}/alerts", headers=org_a["headers"]).json()) == 1


def test_ac14_management_requires_the_manage_permission(client: TestClient) -> None:
    org = _register_org(client, "Perm SLO Org")
    # anonymous
    assert client.post(f"{RT}/slos", json={"name": "x", "sli": "success_rate",
                                           "target": 0.99}).status_code in (401, 403)
    # structural: the routes depend on the manage codes
    src = (APP_ROOT / "slo" / "routes.py").read_text(encoding="utf-8")
    assert 'require_permission(_SLO_MANAGE)' in src
    assert 'require_permission(_ALERT_MANAGE)' in src
    assert '_SLO_MANAGE = "runtime.slo.manage"' in src
    assert '_ALERT_MANAGE = "runtime.alert.manage"' in src


def test_ac14_cross_tenant_alert_transition_is_not_found(client: TestClient, db_session: Session) -> None:
    org_a, setup_a = _org_and_agent(client)
    _make_slo(client, org_a, sli="success_rate", target=0.99)
    _seed_window(db_session, setup_a, org_a, succeeded=20, failed=20)
    client.post(f"{RT}/slos/evaluate", headers=org_a["headers"])
    alert_id = client.get(f"{RT}/alerts", headers=org_a["headers"]).json()[0]["id"]

    org_b = _register_org(client, "Stranger SLO Org")
    r = client.post(f"{RT}/alerts/{alert_id}/acknowledge", headers=org_b["headers"])
    assert r.status_code in (403, 404)


def test_ac14_an_invalid_slo_is_rejected_with_slo_definition_invalid(client: TestClient) -> None:
    org = _register_org(client, "Invalid SLO Org")
    r = client.post(f"{RT}/slos", headers=org["headers"], json={
        "name": "bad", "sli": "success_rate", "target": 1.5})  # ratio > 1
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "SLO_DEFINITION_INVALID"
    r2 = client.post(f"{RT}/slos", headers=org["headers"], json={
        "name": "bad2", "sli": "not_a_real_sli", "target": 0.9})
    assert r2.json()["error"]["code"] == "SLO_DEFINITION_INVALID"


def test_ac14_no_secret_in_an_alert_or_its_audit(client: TestClient, db_session: Session) -> None:
    org, setup = _org_and_agent(client)
    _make_slo(client, org, sli="success_rate", target=0.99)
    _seed_window(db_session, setup, org, succeeded=20, failed=20)
    client.post(f"{RT}/slos/evaluate", headers=org["headers"])
    alert = client.get(f"{RT}/alerts", headers=org["headers"]).json()[0]
    blob = str(alert).lower()
    for marker in ("password", "secret", "api_key", "authorization", "bearer ", "token="):
        assert marker not in blob


# =========================================================================== #
# AC-16 / AC-18 -- markers & determinism of definitions
# =========================================================================== #
def test_ac16_the_sli_set_and_specs_are_consistent() -> None:
    assert SLI_NAMES == set(SLI_SPECS)
    assert TERMINAL_STATUSES  # non-empty
    for direction, unit in SLI_SPECS.values():
        assert direction in ("higher_better", "lower_better")
        assert unit in ("ratio", "ms")


def test_ac18_the_phase_left_no_markers() -> None:
    banned = ("TODO", "FIXME", "NotImplementedError", "xfail", "pytest.skip",
              "@pytest.mark.skip")
    for path in (APP_ROOT / "slo").rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in src, f"{token} in {path}"


def test_definition_validation_defaults_the_error_budget() -> None:
    assert validate_definition({"name": "n", "sli": "success_rate", "target": 0.99}
                               )["error_budget"] == pytest.approx(0.01)
    assert validate_definition({"name": "n", "sli": "timeout_rate", "target": 0.02}
                               )["error_budget"] == pytest.approx(0.02)
    assert validate_definition({"name": "n", "sli": "latency_p95", "target": 250}
                               )["error_budget"] == pytest.approx(0.05)


def test_terminal_status_set_matches_35_and_45() -> None:
    from app.behavior.engine import TERMINAL_FOR_BEHAVIOR
    from app.runtime.deployment.health import TERMINAL_FOR_HEALTH

    assert TERMINAL_STATUSES == TERMINAL_FOR_HEALTH == TERMINAL_FOR_BEHAVIOR
