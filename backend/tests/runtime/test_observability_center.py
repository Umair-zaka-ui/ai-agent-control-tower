"""Phase 4.9 backend tests -- the two read-only aggregation endpoints for the
Observability Center.

The frontend is where 4.9's weight sits; these two endpoints are the only new
backend surface. The load-bearing assertions here: they are read-only (no
mutation call in the module), tenant-scoped, authorized, and the overview never
renders "no data" as "0% healthy".
"""

from __future__ import annotations

import ast
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.runtime.test_behavioral_signals import _agent_setup, _register_org, _seed

RT = "/api/v1/runtime"
APP_ROOT = Path(__file__).resolve().parents[2] / "app"
NOW = datetime.now(timezone.utc)


def _org_agent(client: TestClient):
    org = _register_org(client, f"Obs Center {uuid.uuid4().hex[:6]}")
    setup = _agent_setup(client, org)
    return org, setup


# --------------------------------------------------------------------------- #
def test_overview_returns_the_fleet_composite(client: TestClient, db_session: Session) -> None:
    org, setup = _org_agent(client)
    _seed(db_session, setup, org, count=25, at=NOW - timedelta(hours=2), status="SUCCEEDED")
    _seed(db_session, setup, org, count=5, at=NOW - timedelta(hours=2), status="FAILED",
          error_code="X")

    r = client.get(f"{RT}/overview", headers=org["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("executions", "spend", "alerts", "slos", "behavior", "workers", "capture"):
        assert key in body, key
    # exporter health is NOT in the composite -- it belongs to the 4.6 export
    # plane that app/runtime never imports (ruling #13/#14).
    assert "exporter" not in body
    assert body["executions"]["terminal"] >= 30
    assert body["executions"]["failed_24h"] >= 5
    # 30 terminal >= 20 floor -> a real rate
    assert body["executions"]["success_rate"] is not None
    assert 0.0 <= body["executions"]["success_rate"] <= 1.0
    assert body["capture"]["org_effective_mode"] == "METADATA_ONLY"


def test_overview_success_rate_is_insufficient_data_below_the_floor(
        client: TestClient, db_session: Session) -> None:
    org, setup = _org_agent(client)
    _seed(db_session, setup, org, count=5, at=NOW - timedelta(hours=1), status="SUCCEEDED")

    body = client.get(f"{RT}/overview", headers=org["headers"]).json()
    assert body["executions"]["success_rate"] is None
    assert body["executions"]["success_rate_insufficient_data"] is True


def test_overview_is_tenant_scoped(client: TestClient, db_session: Session) -> None:
    org_a, setup_a = _org_agent(client)
    _seed(db_session, setup_a, org_a, count=25, at=NOW - timedelta(hours=1))
    org_b = _register_org(client, "Obs Stranger")
    body = client.get(f"{RT}/overview", headers=org_b["headers"]).json()
    assert body["executions"]["terminal"] == 0


def test_overview_requires_a_permission(client: TestClient) -> None:
    assert client.get(f"{RT}/overview").status_code in (401, 403)


# --------------------------------------------------------------------------- #
def test_governance_decisions_list_is_tenant_scoped_and_filterable(
        client: TestClient, db_session: Session) -> None:
    from app.models.runtime import RuntimeGovernanceDecision

    org, setup = _org_agent(client)
    execs = _seed(db_session, setup, org, count=3, at=NOW - timedelta(hours=1))
    for i, ex in enumerate(execs):
        db_session.add(RuntimeGovernanceDecision(
            organization_id=uuid.UUID(org["organization_id"]),
            execution_id=ex.id, checkpoint="BEFORE_TOOL_EXECUTION",
            decision="STOP" if i == 0 else "ALLOW",
            reason_code="COST_CEILING_EXCEEDED" if i == 0 else "OK",
            reason="Cost ceiling of $5.00 exceeded."))
    db_session.commit()

    r = client.get(f"{RT}/governance/decisions", headers=org["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 3
    assert body["items"][0]["agent_name"] == setup["agent"]["name"]
    assert "decisions" in body["vocabulary"]

    stopped = client.get(f"{RT}/governance/decisions", headers=org["headers"],
                         params={"decision": "STOP"}).json()
    assert len(stopped["items"]) == 1
    assert stopped["items"][0]["reason_code"] == "COST_CEILING_EXCEEDED"

    org_b = _register_org(client, "Gov Stranger")
    assert client.get(f"{RT}/governance/decisions", headers=org_b["headers"]).json()["items"] == []


def test_governance_decisions_reason_is_a_templated_sentence_not_content(
        client: TestClient, db_session: Session) -> None:
    from app.models.runtime import RuntimeGovernanceDecision

    org, setup = _org_agent(client)
    ex = _seed(db_session, setup, org, count=1, at=NOW - timedelta(hours=1))[0]
    db_session.add(RuntimeGovernanceDecision(
        organization_id=uuid.UUID(org["organization_id"]), execution_id=ex.id,
        checkpoint="AFTER_MODEL_RESPONSE", decision="DENY",
        reason_code="RESTRICTED_MODEL", reason="Model 'gpt-4o' is not allowed in this environment."))
    db_session.commit()
    body = client.get(f"{RT}/governance/decisions", headers=org["headers"]).json()
    assert body["items"][0]["reason"] == "Model 'gpt-4o' is not allowed in this environment."


# --------------------------------------------------------------------------- #
def test_the_read_model_module_performs_no_mutation() -> None:
    """M4-4.9 -- read + trigger only. The 4.9 read-model module never adds,
    commits, deletes or flushes."""
    src = (APP_ROOT / "runtime" / "observability_center.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden = {"add", "add_all", "commit", "delete", "flush", "merge", "execute_write"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            # `.execute` is a read here; only the mutators are forbidden.
            raise AssertionError(f"observability_center.py calls .{node.attr}")


def test_the_read_model_does_not_reach_into_the_export_plane() -> None:
    """Ruling #13/#14 -- app/runtime never imports telemetry_export or reads
    exporter_health. The Observability Center screen fetches exporter health from
    4.6's own endpoint instead. (A 4.6 test asserts this for the whole
    app/runtime tree; kept here too so a regression in this module is obvious.)"""
    src = (APP_ROOT / "runtime" / "observability_center.py").read_text(encoding="utf-8")
    assert "exporter_health" not in src
    assert "telemetry_export" not in src
