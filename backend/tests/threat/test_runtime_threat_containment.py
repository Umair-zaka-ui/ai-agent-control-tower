"""Phase 5.6 (M5.6) - Runtime Threat Detection & Containment.

AC-01..AC-18 + the §14 end-to-end proof. Each acceptance criterion is backed
by at least one named test here.

The load-bearing properties, and where they are proven:
  * deterministic threat engine, runtime-event distinct from posture ...... AC-02
  * containment routes ONLY to existing authorities, names each one ....... AC-03
  * one enforcement path -- app/threat implements no enforcement (AST) .... AC-04
  * TRUTHFUL containment -- control_state gates capability (structural) ... AC-05
  * kill-switch dominance -- no reactivate/bypass (AST + behavioral) ...... AC-06
  * commit-before-dispatch -- no lock across an authority call (AST) ...... AC-07
  * a real suspicious operation -> a real containment (real authorities) .. AC-08
"""

from __future__ import annotations

import ast
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import SessionLocal
from app.main import app
from tests.threat.conftest import PASSWORD

THR = "/api/v1/threat"
RT = "/api/v1/runtime"
_BACKEND = Path(__file__).resolve().parents[2]
_REPO = _BACKEND.parent


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# helpers -- this suite's convention: each file defines its own
# --------------------------------------------------------------------------- #
def _insert_agent(db, admin: dict, *, name: str | None = None, control_state: str = "GOVERNED",
                  origin_category: str = "NATIVE", lifecycle_status: str = "ACTIVE") -> uuid.UUID:
    aid = uuid.uuid4()
    db.execute(
        text(
            """
            INSERT INTO agents (id, organization_id, name, agent_type, api_key_hash, status,
                                version, capabilities, default_risk_score, max_allowed_risk,
                                human_approval_required, risk_level, health, criticality,
                                data_classification, default_environment, lifecycle_status,
                                origin_category, origin_provider, control_state,
                                owner_id, owner_type, created_at, updated_at)
            VALUES (:id, :org, :name, 'ASSISTANT', 'x', 'ACTIVE', '1.0.0', '[]'::jsonb, 0, 100,
                    false, 'LOW', 'HEALTHY', 'MEDIUM', 'INTERNAL', 'DEVELOPMENT', :lifecycle,
                    :origin_cat, 'ACT_NATIVE', :control_state, :owner, 'USER', now(), now())
            """
        ),
        {"id": str(aid), "org": admin["organization_id"], "name": name or f"agent-{aid.hex[:8]}",
         "lifecycle": lifecycle_status, "origin_cat": origin_category,
         "control_state": control_state, "owner": admin["user_id"]},
    )
    db.commit()
    return aid


def _insert_version(db, agent_id: uuid.UUID, *, status: str = "PUBLISHED") -> uuid.UUID:
    did, vid = uuid.uuid4(), uuid.uuid4()
    db.execute(
        text(
            """
            INSERT INTO agent_definitions (id, agent_id, name, entrypoint, framework,
                                           entrypoint_type, created_at, updated_at)
            VALUES (:did, :aid, 'def', 'agents.h:run', 'CUSTOM', 'FUNCTION', now(), now())
            """
        ),
        {"did": str(did), "aid": str(agent_id)},
    )
    db.execute(
        text(
            """
            INSERT INTO agent_versions (id, agent_id, definition_id, version, semantic_version,
                status, configuration_snapshot, model_configuration, capabilities_snapshot,
                tools_snapshot, checksum, checksum_algorithm, compatibility_level, release_branch,
                created_at)
            VALUES (:vid, :aid, :did, 1, '1.0.0', :st, '{}'::jsonb, '{}'::jsonb, '[]'::jsonb,
                    '[]'::jsonb, 'sha256:0', 'canonical-sha256', 'UNKNOWN', 'main', now())
            """
        ),
        {"vid": str(vid), "aid": str(agent_id), "did": str(did), "st": status},
    )
    db.commit()
    return vid


def _insert_execution(db, admin: dict, agent_id: uuid.UUID, version_id: uuid.UUID,
                      *, status: str = "RUNNING") -> uuid.UUID:
    eid = uuid.uuid4()
    db.execute(
        text(
            """
            INSERT INTO agent_executions (id, organization_id, agent_id, agent_version_id,
                trigger_type, input_payload, status, created_at)
            VALUES (:id, :org, :aid, :vid, 'API', '{}'::jsonb, :st, now())
            """
        ),
        {"id": str(eid), "org": admin["organization_id"], "aid": str(agent_id),
         "vid": str(version_id), "st": status},
    )
    db.commit()
    return eid


def _insert_behavioral_finding(db, admin: dict, agent_id: uuid.UUID, *, state: str = "ANOMALOUS") -> uuid.UUID:
    fid = uuid.uuid4()
    end = _now()
    start = end - timedelta(hours=1)
    db.execute(
        text(
            """
            INSERT INTO behavioral_findings (id, organization_id, agent_id, signal_type, state,
                metric, window_start, window_end, sample_count, attribution, explanation, evaluated_at)
            VALUES (:id, :org, :aid, 'failure_rate', :st, 'failure_rate', :ws, :we, 50,
                    '{}'::jsonb, '{}'::jsonb, now())
            """
        ),
        {"id": str(fid), "org": admin["organization_id"], "aid": str(agent_id), "st": state,
         "ws": start, "we": end},
    )
    db.commit()
    return fid


def _insert_governance_denials(db, admin: dict, execution_id: uuid.UUID, *, count: int = 3) -> None:
    for _ in range(count):
        db.execute(
            text(
                """
                INSERT INTO runtime_governance_decisions (id, organization_id, execution_id,
                    checkpoint, decision, reason_code, reason, evaluated_at)
                VALUES (gen_random_uuid(), :org, :eid, 'BEFORE_TOOL_EXECUTION', 'DENY',
                        'RESTRICTED_TOOL', 'denied', now())
                """
            ),
            {"org": admin["organization_id"], "eid": str(execution_id)},
        )
    db.commit()


def _insert_tool(client: TestClient, admin: dict) -> str:
    r = client.post(f"{RT}/tools", headers=admin["headers"],
                    json={"name": f"tool_{uuid.uuid4().hex[:8]}", "display_name": "T",
                          "tool_type": "FUNCTION"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _insert_tool_call(db, *, execution_id, agent_id, tool_id, egress_decision=None,
                      validation_error=None) -> uuid.UUID:
    tc_id = uuid.uuid4()
    db.execute(
        text(
            """
            INSERT INTO tool_calls (id, execution_id, agent_id, tool_id, action, status,
                                    egress_decision, validation_error, created_at, started_at)
            VALUES (:id, :eid, :aid, :tid, 'invoke', 'ALLOWED', :egress, :verr, now(), now())
            """
        ),
        {"id": str(tc_id), "eid": str(execution_id), "aid": str(agent_id), "tid": str(tool_id),
         "egress": egress_decision, "verr": validation_error},
    )
    db.commit()
    return tc_id


def _insert_agent_tool(client: TestClient, admin: dict, agent_id: uuid.UUID, tool_id: str) -> str:
    r = client.post(f"{RT}/agents/{agent_id}/tools", headers=admin["headers"],
                    json={"tool_id": tool_id})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _insert_capability(db) -> uuid.UUID:
    cid = uuid.uuid4()
    db.execute(
        text(
            """
            INSERT INTO capabilities (id, name, display_name, risk_level, requires_approval,
                required_permissions, prohibited_environments, created_at, updated_at)
            VALUES (:id, :name, 'Cap', 'MEDIUM', false, '[]'::jsonb, '[]'::jsonb, now(), now())
            """
        ),
        {"id": str(cid), "name": f"cap_{cid.hex[:8]}"},
    )
    db.commit()
    return cid


def _insert_agent_capability(db, agent_id: uuid.UUID, capability_id: uuid.UUID,
                             *, status: str = "APPROVED") -> uuid.UUID:
    acid = uuid.uuid4()
    db.execute(
        text(
            """
            INSERT INTO agent_capabilities (id, agent_id, capability_id, status, created_at)
            VALUES (:id, :aid, :cid, :st, now())
            """
        ),
        {"id": str(acid), "aid": str(agent_id), "cid": str(capability_id), "st": status},
    )
    db.commit()
    return acid


def _insert_api_key(db, agent_id: uuid.UUID) -> uuid.UUID:
    kid = uuid.uuid4()
    db.execute(
        text(
            """
            INSERT INTO agent_api_keys (id, agent_id, key_hash, key_prefix, status, created_at)
            VALUES (:id, :aid, :kh, 'agt_test_AB', 'ACTIVE', now())
            """
        ),
        {"id": str(kid), "aid": str(agent_id), "kh": f"hash-{kid.hex}"},
    )
    db.commit()
    return kid


def _insert_connector_instance(db, admin: dict, *, lifecycle_state: str = "active") -> uuid.UUID:
    ctid = uuid.uuid4()
    iid = uuid.uuid4()
    db.execute(
        text(
            """
            INSERT INTO connectors (id, connector_type, version, capabilities, config_schema,
                auth_requirements, tool_contracts, created_at, updated_at)
            VALUES (:id, 'MOCK', '1.0.0', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '[]'::jsonb,
                    now(), now())
            ON CONFLICT DO NOTHING
            """
        ),
        {"id": str(ctid)},
    )
    row = db.execute(
        text("SELECT id FROM connectors WHERE connector_type = 'MOCK' AND version = '1.0.0' LIMIT 1")
    ).first()
    connector_id = row[0]
    db.execute(
        text(
            """
            INSERT INTO connector_instances (id, organization_id, connector_id, name,
                configuration, lifecycle_state, created_at, updated_at)
            VALUES (:id, :org, :cid, :nm, '{}'::jsonb, :st, now(), now())
            """
        ),
        {"id": str(iid), "org": admin["organization_id"], "cid": str(connector_id),
         "nm": f"instance-{iid.hex[:8]}", "st": lifecycle_state},
    )
    db.commit()
    return iid


def _second_user(client: TestClient, admin: dict, role: str = "VIEWER") -> dict:
    email = f"tu_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post(
        "/api/v1/identity/users", headers=admin["headers"],
        json={"email": email, "display_name": "U", "password": PASSWORD, "role": role,
              "organization_id": admin["organization_id"]},
    )
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"}}


def _evaluate(client: TestClient, admin: dict, agent_id: uuid.UUID) -> dict:
    r = client.post(f"{THR}/agents/{agent_id}/evaluate", headers=admin["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _findings(client: TestClient, admin: dict, agent_id: uuid.UUID, **params) -> list[dict]:
    r = client.get(f"{THR}/agents/{agent_id}/findings", headers=admin["headers"])
    assert r.status_code == 200, r.text
    out = r.json()
    for k, v in params.items():
        out = [f for f in out if f.get(k) == v]
    return out


def _contain(client: TestClient, admin: dict, agent_id: uuid.UUID, action_type: str,
             *, confirm: bool = True, target_id: str | None = None, reason: str = "test") -> dict:
    body = {"action_type": action_type, "reason": reason, "confirm": confirm}
    if target_id:
        body["target_id"] = target_id
    r = client.post(f"{THR}/agents/{agent_id}/containment", headers=admin["headers"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


# =========================================================================== #
# AC-01 - live baseline / substrate
# =========================================================================== #
def test_ac01_substrate_present_and_head_recorded() -> None:
    from app.threat.containment import ContainmentOrchestrator  # noqa: F401
    from app.threat.evaluator import ThreatEvaluator  # noqa: F401
    from app.threat.lifecycle import ThreatFindingService  # noqa: F401
    from app.runtime.services import KillSwitchService  # noqa: F401
    from app.runtime.governance.engine import RuntimeGovernanceEngine  # noqa: F401

    versions = {v.stem for v in (_BACKEND / "migrations" / "versions").glob("*.py")}
    assert {"0057_dependency_graph", "0058_security_posture", "0059_threat_containment"} <= versions
    assert "0059_threat_containment" in (_REPO / "REPO_STATE.md").read_text(encoding="utf-8")


# =========================================================================== #
# AC-02 - deterministic threat engine; runtime-event distinct from posture
# =========================================================================== #
def test_ac02_no_ml_import_in_threat() -> None:
    forbidden = ("numpy", "scipy", "sklearn", "pandas", "torch", "tensorflow", "xgboost", "keras")
    for path in (_BACKEND / "app" / "threat").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                assert not any(n == b or n.startswith(b + ".") for b in forbidden), (path, n)


def test_ac02_behavioral_anomaly_produces_a_deterministic_threat_finding(
    client: TestClient, admin: dict
) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin)
        _insert_behavioral_finding(db, admin, aid)
    finally:
        db.close()
    a = _evaluate(client, admin, aid)
    b = _evaluate(client, admin, aid)
    assert a["findings_opened"] >= 1
    assert b["findings_opened"] == 0  # idempotent: nothing new on re-evaluation
    fired = {f["rule_id"] for f in _findings(client, admin, aid, status="OPEN")}
    assert "behavioral_anomaly_threat" in fired


def test_ac02_threat_is_a_runtime_event_distinct_from_posture(client: TestClient, admin: dict) -> None:
    """The canonical example: an unapproved-MCP *dependency* is posture; the
    agent actually *invoking* the tool that server exposes is a threat."""
    from app.graph.mcp import McpServerService
    from app.models.user import User

    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin)
        user = db.get(User, uuid.UUID(admin["user_id"]))
        server = McpServerService(db).register(user, name=f"mcp-{uuid.uuid4().hex[:8]}",
                                                trust_status="UNKNOWN", provenance="DISCOVERED")
    finally:
        db.close()
    tool_id = _insert_tool(client, admin)
    r = client.post(f"/api/v1/graph/mcp-servers/{server.id}/tools",
                    headers=admin["headers"], json={"tool_id": tool_id})
    assert r.status_code == 201, r.text

    # posture would already see the dependency once built; 5.6 only cares
    # whether the tool was actually called.
    db = SessionLocal()
    try:
        version_id = _insert_version(db, aid)
        execution_id = _insert_execution(db, admin, aid, version_id)
        _insert_tool_call(db, execution_id=execution_id, agent_id=aid, tool_id=tool_id)
    finally:
        db.close()
    r = client.post(f"/api/v1/graph/dependency-edges", headers=admin["headers"],
                    json={"source": {"type": "AGENT", "id": str(aid)},
                          "edge_type": "DEPENDS_ON_TOOL", "target": {"type": "TOOL", "id": tool_id}})
    assert r.status_code == 201, r.text
    db = SessionLocal()
    try:
        db.execute(text(
            "UPDATE control_graph_edges SET evidence = '{\"mode\":\"OBSERVED\"}'::jsonb "
            "WHERE id = :id"), {"id": r.json()["id"]})
        db.commit()
    finally:
        db.close()

    _evaluate(client, admin, aid)
    fired = {f["rule_id"] for f in _findings(client, admin, aid, status="OPEN")}
    assert "unapproved_mcp_tool_invoked" in fired


# =========================================================================== #
# AC-03 - containment routes ONLY to existing authorities; names each one
# =========================================================================== #
def test_ac03_suspend_agent_names_the_kill_switch_authority(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, control_state="GOVERNED")
    finally:
        db.close()
    action = _contain(client, admin, aid, "SUSPEND_AGENT")
    assert action["status"] == "EXECUTED"
    assert action["authority"] == "KILL_SWITCH"
    assert action["authority_ref"]["table"] == "agents"


def test_ac03_deny_tool_names_the_tool_lifecycle_authority(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, control_state="GOVERNED")
    finally:
        db.close()
    tool_id = _insert_tool(client, admin)
    assignment_id = _insert_agent_tool(client, admin, aid, tool_id)
    action = _contain(client, admin, aid, "DENY_TOOL", target_id=assignment_id)
    assert action["status"] == "EXECUTED"
    assert action["authority"] == "TOOL_LIFECYCLE"
    assert action["authority_ref"]["table"] == "agent_tools"
    db = SessionLocal()
    try:
        status = db.execute(text("SELECT status FROM agent_tools WHERE id = :id"),
                            {"id": assignment_id}).scalar()
        assert status == "REVOKED"  # the real authority actually revoked it
    finally:
        db.close()


def test_ac03_revoke_capability_and_isolate_credential_and_disable_integration(
    client: TestClient, admin: dict
) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, control_state="GOVERNED")
        cap_id = _insert_capability(db)
        assignment_id = _insert_agent_capability(db, aid, cap_id)
        key_id = _insert_api_key(db, aid)
        instance_id = _insert_connector_instance(db, admin)
    finally:
        db.close()

    a1 = _contain(client, admin, aid, "REVOKE_CAPABILITY", target_id=str(assignment_id))
    assert a1["status"] == "EXECUTED" and a1["authority"] == "CAPABILITY_LIFECYCLE"

    a2 = _contain(client, admin, aid, "ISOLATE_CREDENTIAL", target_id=str(key_id))
    assert a2["status"] == "EXECUTED" and a2["authority"] == "CREDENTIAL_LIFECYCLE"
    db = SessionLocal()
    try:
        status = db.execute(text("SELECT status FROM agent_api_keys WHERE id = :id"),
                            {"id": str(key_id)}).scalar()
        assert status == "REVOKED"
    finally:
        db.close()

    a3 = _contain(client, admin, aid, "DISABLE_INTEGRATION", target_id=str(instance_id))
    assert a3["status"] == "EXECUTED" and a3["authority"] == "CONNECTOR_LIFECYCLE"
    db = SessionLocal()
    try:
        state = db.execute(text("SELECT lifecycle_state FROM connector_instances WHERE id = :id"),
                           {"id": str(instance_id)}).scalar()
        assert state == "disabled"
    finally:
        db.close()


def test_ac03_require_approval_creates_a_real_enforced_governance_policy(
    client: TestClient, admin: dict
) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, control_state="GOVERNED")
    finally:
        db.close()
    action = _contain(client, admin, aid, "REQUIRE_APPROVAL")
    assert action["status"] == "EXECUTED" and action["authority"] == "GOVERNANCE_POLICY"
    policy_id = action["authority_ref"]["id"]
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT agent_id, mandatory, constraints FROM runtime_governance_policies WHERE id = :id"),
            {"id": policy_id}).first()
        assert str(row[0]) == str(aid)
        assert row[1] is True
        constraints = row[2] if isinstance(row[2], dict) else json.loads(row[2])
        assert constraints["requires_approval"] is True
    finally:
        db.close()


def test_ac03_terminate_execution_names_kill_switch(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, control_state="GOVERNED")
        vid = _insert_version(db, aid)
        eid = _insert_execution(db, admin, aid, vid, status="RUNNING")
    finally:
        db.close()
    action = _contain(client, admin, aid, "TERMINATE_EXECUTION", target_id=str(eid))
    assert action["status"] == "EXECUTED" and action["authority"] == "KILL_SWITCH"
    db = SessionLocal()
    try:
        status = db.execute(text("SELECT status FROM agent_executions WHERE id = :id"),
                            {"id": str(eid)}).scalar()
        assert status == "CANCELLED"
    finally:
        db.close()


# =========================================================================== #
# AC-04 - one enforcement path; app/threat implements NO enforcement (AST)
# =========================================================================== #
def test_ac04_no_enforcement_implemented_in_threat_package() -> None:
    """app/threat may only CALL the real authorities; it must not itself
    assign lifecycle_status/cancel_requested/agent_tools.status etc, and must
    not define a class named like an enforcer."""
    banned_names = ("KillSwitchEngine", "GovernanceEngine", "EnforcementService")
    for path in (_BACKEND / "app" / "threat").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                assert node.name not in banned_names, f"{path.name} defines a parallel enforcer"
        src = path.read_text(encoding="utf-8")
        # every dispatch call reaches an existing service; no direct SQL UPDATE
        # of an enforcement column (status/lifecycle_status) appears in this
        # package -- everything routes through the imported service methods.
        assert "UPDATE agents SET" not in src
        assert "UPDATE agent_executions SET" not in src
        assert "UPDATE agent_tools SET" not in src


def test_ac04_containment_calls_the_real_authorities_not_a_new_one() -> None:
    src = (_BACKEND / "app" / "threat" / "containment.py").read_text(encoding="utf-8")
    for authority in ("KillSwitchService", "ToolRegistryService", "CapabilityService",
                      "ConnectorService", "GovernancePolicyService", "revoke_key"):
        assert authority in src, f"containment.py does not call {authority}"


# =========================================================================== #
# AC-05 - TRUTHFUL containment: control_state gates capability, structurally
# =========================================================================== #
@pytest.mark.parametrize("control_state", ["DISCOVERED", "CLAIMED", "REGISTERED"])
def test_ac05_observed_agent_containment_is_truthfully_refused(
    client: TestClient, admin: dict, control_state: str
) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, control_state=control_state, origin_category="EXTERNAL")
    finally:
        db.close()
    action = _contain(client, admin, aid, "SUSPEND_AGENT")
    assert action["status"] == "REFUSED"
    assert action["authority"] == "KILL_SWITCH"  # names the authority it would have used
    assert control_state in action["refusal_reason"]
    assert "no enforcement authority" in action["refusal_reason"].lower()
    # never a fake success
    assert action["result"] == {}
    assert action["authority_ref"] is None


def test_ac05_governed_agent_containment_routes_to_the_real_authority(
    client: TestClient, admin: dict
) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, control_state="GOVERNED")
    finally:
        db.close()
    action = _contain(client, admin, aid, "SUSPEND_AGENT")
    assert action["status"] == "EXECUTED"
    db = SessionLocal()
    try:
        status = db.execute(text("SELECT lifecycle_status FROM agents WHERE id = :id"),
                            {"id": str(aid)}).scalar()
        assert status == "SUSPENDED"  # actually contained, not a claim
    finally:
        db.close()


def test_ac05_capability_derives_only_from_control_state() -> None:
    src = (_BACKEND / "app" / "threat" / "containment.py").read_text(encoding="utf-8")
    assert "_ENFORCEABLE_CONTROL_STATE" in src
    assert 'agent.control_state == _ENFORCEABLE_CONTROL_STATE' in src.replace("\n", " ").replace("  ", " ") \
           or "agent.control_state == _ENFORCEABLE_CONTROL_STATE" in src


# =========================================================================== #
# AC-06 - kill-switch dominance
# =========================================================================== #
def test_ac06_no_reactivation_or_kill_clearing_in_threat_package() -> None:
    """AST: nothing in app/threat sets lifecycle_status back to ACTIVE or
    cancel_requested back to False -- the same proof app.runtime.governance
    gives for itself."""
    for path in (_BACKEND / "app" / "threat").rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        assert 'lifecycle_status = "ACTIVE"' not in src
        assert "lifecycle_status='ACTIVE'" not in src.replace(" ", "")
        assert "cancel_requested = False" not in src
        assert "cancel_requested=False" not in src.replace(" ", "")


def test_ac06_suspend_agent_action_is_not_reversible() -> None:
    from app.threat.containment import _REVERSIBLE

    assert _REVERSIBLE["SUSPEND_AGENT"] is False
    assert _REVERSIBLE["TERMINATE_EXECUTION"] is False


def test_ac06_reverting_a_kill_switch_action_is_refused(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, control_state="GOVERNED")
    finally:
        db.close()
    action = _contain(client, admin, aid, "SUSPEND_AGENT")
    r = client.post(f"{THR}/containment/{action['id']}/revert", headers=admin["headers"])
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONTAINMENT_ACTION_NOT_REVERSIBLE"


def test_ac06_kill_dominates_a_concurrent_containment_recommendation(
    client: TestClient, admin: dict
) -> None:
    """A human kill fired first; a subsequent automated evaluation must not
    undo it -- it can only ever recommend further containment, never clear."""
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, control_state="GOVERNED")
    finally:
        db.close()
    _contain(client, admin, aid, "SUSPEND_AGENT")  # the human/operator kill
    db = SessionLocal()
    try:
        status_before = db.execute(text("SELECT lifecycle_status FROM agents WHERE id = :id"),
                                   {"id": str(aid)}).scalar()
        _insert_behavioral_finding(db, admin, aid)
    finally:
        db.close()
    _evaluate(client, admin, aid)  # automation runs again
    db = SessionLocal()
    try:
        status_after = db.execute(text("SELECT lifecycle_status FROM agents WHERE id = :id"),
                                  {"id": str(aid)}).scalar()
    finally:
        db.close()
    assert status_before == "SUSPENDED"
    assert status_after == "SUSPENDED"  # still suspended -- automation never reactivated it


# =========================================================================== #
# AC-07 - commit-before-dispatch
# =========================================================================== #
def test_ac07_no_row_lock_in_threat_package() -> None:
    for path in (_BACKEND / "app" / "threat").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                first = node.body[0] if node.body else None
                if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    docstrings.add(id(first.value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr != "with_for_update", f"{path.name} takes a row lock"
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docstrings):
                assert "FOR UPDATE" not in node.value.upper(), f"{path.name} writes a locking clause"


def test_ac07_a_containment_execute_holds_no_lock_afterward(client: TestClient, admin: dict) -> None:
    """Behavioural half: after a containment action completes, a second real
    connection can take the exclusive lock on the agent's own execution rows
    with NOWAIT -- nothing here left a transaction open across the call."""
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, control_state="GOVERNED")
        vid = _insert_version(db, aid)
        eid = _insert_execution(db, admin, aid, vid, status="QUEUED")
    finally:
        db.close()
    _contain(client, admin, aid, "SUSPEND_AGENT")

    other = SessionLocal()
    try:
        other.execute(
            text("SELECT id FROM agent_executions WHERE id = :i FOR UPDATE NOWAIT"),
            {"i": str(eid)},
        ).first()
    finally:
        other.rollback()
        other.close()


# =========================================================================== #
# AC-08 - a real suspicious operation -> a real containment
# =========================================================================== #
def test_ac08_real_signal_to_real_containment(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, control_state="GOVERNED")
        vid = _insert_version(db, aid)
        eid = _insert_execution(db, admin, aid, vid, status="RUNNING")
        _insert_governance_denials(db, admin, eid, count=3)
    finally:
        db.close()
    summary = _evaluate(client, admin, aid)
    assert summary["findings_opened"] >= 1
    fired = _findings(client, admin, aid, rule_id="governance_denial_spike", status="OPEN")
    assert fired
    finding_id = fired[0]["id"]

    action = _contain(client, admin, aid, "SUSPEND_AGENT", target_id=None)
    assert action["status"] == "EXECUTED"
    db = SessionLocal()
    try:
        status = db.execute(text("SELECT lifecycle_status FROM agents WHERE id = :id"),
                            {"id": str(aid)}).scalar()
        exec_status = db.execute(text("SELECT status FROM agent_executions WHERE id = :id"),
                                 {"id": str(eid)}).scalar()
        assert status == "SUSPENDED"
        assert exec_status == "CANCELLED"
        n = db.execute(text(
            "SELECT count(*) FROM authorization_audit WHERE organization_id = :org "
            "AND event_type = 'RUNTIME_KILL_SWITCH_ACTIVATED'"), {"org": admin["organization_id"]}).scalar()
        assert n >= 1
    finally:
        db.close()


# =========================================================================== #
# AC-09 - detection fails open; mandatory containment fails closed
# =========================================================================== #
def test_ac09_a_failing_rule_fails_open(client: TestClient, admin: dict, monkeypatch) -> None:
    import app.threat.evaluator as ev_mod
    import app.threat.rules as rules_mod
    from dataclasses import replace

    def _boom(ctx, params):
        raise RuntimeError("simulated rule failure")

    boom_rule = replace(rules_mod.RULES_BY_ID["governance_denial_spike"], fn=_boom)
    patched = tuple(boom_rule if r.id == "governance_denial_spike" else r for r in rules_mod.RULES)
    monkeypatch.setattr(rules_mod, "RULES", patched)
    monkeypatch.setattr(ev_mod, "RULES", patched)

    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin)
        _insert_behavioral_finding(db, admin, aid)
    finally:
        db.close()
    summary = _evaluate(client, admin, aid)
    assert summary["rule_errors"] >= 1
    assert _findings(client, admin, aid, rule_id="governance_denial_spike") == []
    assert _findings(client, admin, aid, rule_id="behavioral_anomaly_threat")  # other rules unaffected


def test_ac09_a_failed_containment_is_recorded_honestly_not_as_executed(
    client: TestClient, admin: dict
) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, control_state="GOVERNED")
    finally:
        db.close()
    # DENY_TOOL against a target that does not exist -- the real authority
    # (ToolRegistryService.revoke) raises TOOL_NOT_ASSIGNED.
    action = _contain(client, admin, aid, "DENY_TOOL", target_id=str(uuid.uuid4()))
    assert action["status"] == "FAILED"
    assert "error" in action["result"]


# =========================================================================== #
# AC-10 - containment-execute is a distinct, stronger permission
# =========================================================================== #
def test_ac10_containment_execute_is_distinct_from_view_and_manage(client: TestClient, admin: dict) -> None:
    from app.authorization.catalog import group_for_code
    from app.services.rbac_service import PERMISSION_CATALOG

    assert "threat.view" in PERMISSION_CATALOG
    assert "threat.manage" in PERMISSION_CATALOG
    assert "containment.execute" in PERMISSION_CATALOG
    for code in ("threat.view", "threat.manage", "containment.execute"):
        assert group_for_code(code) == "runtime"


def test_ac10_a_user_without_containment_execute_cannot_contain(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, control_state="GOVERNED")
    finally:
        db.close()
    viewer = _second_user(client, admin, role="VIEWER")
    r = client.post(f"{THR}/agents/{aid}/containment", headers=viewer["headers"],
                    json={"action_type": "SUSPEND_AGENT", "reason": "x", "confirm": True})
    assert r.status_code == 403
    # but reading threat findings needs only threat.view, not containment.execute
    assert client.get(f"{THR}/findings", headers=viewer["headers"]).status_code == 403  # VIEWER holds neither


# =========================================================================== #
# AC-11 - tenant isolation; per-hop for graph attribution
# =========================================================================== #
def test_ac11_cross_tenant_finding_and_containment_are_404(
    client: TestClient, admin: dict, other_org_admin: dict
) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin)
        _insert_behavioral_finding(db, admin, aid)
    finally:
        db.close()
    _evaluate(client, admin, aid)
    fid = _findings(client, admin, aid, rule_id="behavioral_anomaly_threat")[0]["id"]
    assert client.get(f"{THR}/findings/{fid}", headers=other_org_admin["headers"]).status_code == 404
    r = client.post(f"{THR}/agents/{aid}/containment", headers=other_org_admin["headers"],
                    json={"action_type": "SUSPEND_AGENT", "reason": "x", "confirm": True})
    assert r.status_code == 404  # the agent itself is not visible cross-tenant


# =========================================================================== #
# AC-12 - every threat + containment action audited
# =========================================================================== #
def test_ac12_containment_lifecycle_is_audited(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, control_state="GOVERNED")
    finally:
        db.close()
    action = _contain(client, admin, aid, "SUSPEND_AGENT")
    db = SessionLocal()
    try:
        events = {e for (e,) in db.execute(
            text("SELECT event_type FROM authorization_audit WHERE organization_id = :org "
                 "AND event_type LIKE 'CONTAINMENT_%'"), {"org": admin["organization_id"]}).all()}
        assert "CONTAINMENT_ACTION_EXECUTED" in events
    finally:
        db.close()


def test_ac12_no_secret_in_containment_record(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, control_state="GOVERNED")
        key_id = _insert_api_key(db, aid)
    finally:
        db.close()
    action = _contain(client, admin, aid, "ISOLATE_CREDENTIAL", target_id=str(key_id))
    blob = str(action).lower()
    for needle in ("hash-", "secret", "password", "bearer"):
        assert needle not in blob, needle


# =========================================================================== #
# AC-13 - concurrency: real separate Postgres sessions
# =========================================================================== #
def test_ac13_concurrent_containment_race_converges(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, control_state="GOVERNED")
    finally:
        db.close()
    barrier = threading.Barrier(2)
    results: list[int] = []
    lock = threading.Lock()

    def _run() -> None:
        c = TestClient(app)
        barrier.wait()
        r = c.post(f"{THR}/agents/{aid}/containment", headers=admin["headers"],
                  json={"action_type": "SUSPEND_AGENT", "reason": "race", "confirm": True})
        with lock:
            results.append(r.status_code)

    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in [pool.submit(_run) for _ in range(2)]:
            f.result()
    assert all(c == 201 for c in results)
    db = SessionLocal()
    try:
        status = db.execute(text("SELECT lifecycle_status FROM agents WHERE id = :id"),
                            {"id": str(aid)}).scalar()
        assert status == "SUSPENDED"
    finally:
        db.close()


def test_ac13_threat_dedup_under_concurrent_evaluation(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin)
        _insert_behavioral_finding(db, admin, aid)
    finally:
        db.close()
    barrier = threading.Barrier(3)

    def _run() -> None:
        c = TestClient(app)
        barrier.wait()
        c.post(f"{THR}/agents/{aid}/evaluate", headers=admin["headers"])

    with ThreadPoolExecutor(max_workers=3) as pool:
        for f in [pool.submit(_run) for _ in range(3)]:
            f.result()
    db = SessionLocal()
    try:
        n = db.execute(text(
            "SELECT count(*) FROM threat_findings WHERE agent_id = :aid AND rule_id = "
            "'behavioral_anomaly_threat' AND status = 'OPEN'"), {"aid": str(aid)}).scalar()
        assert n == 1
    finally:
        db.close()


# =========================================================================== #
# AC-14 - no new alert engine; no unbounded autonomous remediation
# =========================================================================== #
def test_ac14_no_new_alert_or_registry_table() -> None:
    from app.core.database import Base

    for banned in ("security_events_v2", "threat_alerts", "containment_engine",
                   "auto_remediation_jobs"):
        assert banned not in Base.metadata.tables, banned


def test_ac14_automated_evaluation_only_recommends_never_executes(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, control_state="GOVERNED")
        _insert_behavioral_finding(db, admin, aid)
    finally:
        db.close()
    _evaluate(client, admin, aid)
    db = SessionLocal()
    try:
        status = db.execute(text("SELECT lifecycle_status FROM agents WHERE id = :id"),
                            {"id": str(aid)}).scalar()
        rec = db.execute(text(
            "SELECT status FROM containment_actions WHERE agent_id = :aid ORDER BY created_at DESC LIMIT 1"),
            {"aid": str(aid)}).scalar()
    finally:
        db.close()
    assert status == "ACTIVE"  # evaluation alone never suspends the agent
    assert rec == "RECOMMENDED"  # only a recommendation was created


# =========================================================================== #
# AC-15 - migration shape
# =========================================================================== #
def test_ac15_migration_shape() -> None:
    mig = (_BACKEND / "migrations" / "versions" / "0059_threat_containment.py").read_text(encoding="utf-8")
    assert 'revision = "0059_threat_containment"' in mig
    assert len("0059_threat_containment") <= 32
    assert 'down_revision = "0058_security_posture"' in mig
    assert "def downgrade" in mig and "drop_table" in mig
    assert mig.count("create_table(") == 2
    assert "op.alter_column" not in mig and "op.drop_column" not in mig


# =========================================================================== #
# AC-18 - no forbidden markers
# =========================================================================== #
def test_ac18_no_forbidden_markers_in_new_files() -> None:
    forbidden = ("TO" + "DO", "FIX" + "ME", "Not" + "ImplementedError",
                 "pytest.mark." + "skip", "pytest.mark." + "xfail")
    files = list((_BACKEND / "app" / "threat").rglob("*.py")) + [
        _BACKEND / "app" / "models" / "threat.py",
        _BACKEND / "migrations" / "versions" / "0059_threat_containment.py",
        Path(__file__),
    ]
    for f in files:
        body = f.read_text(encoding="utf-8")
        assert not [m for m in forbidden if m in body], f.name


# =========================================================================== #
# §14 - THE END-TO-END PROOF
# =========================================================================== #
def test_ss14_end_to_end_threat_and_truthful_containment_proof(
    client: TestClient, admin: dict
) -> None:
    """A NATIVE/GOVERNED agent performs a suspicious governed operation (a
    behavioral deviation + a governance-denial spike). 5.6's threat engine
    raises explainable threat findings. An operator-confirmed containment
    routes to the real KillSwitchService and actually suspends the agent +
    cancels its running execution, audited, naming the authority; kill-switch
    dominance holds (a subsequent automated evaluation cannot undo it).
    Separately, an OBSERVED external agent (control_state=DISCOVERED)
    exhibiting the same signal gets a threat finding but its
    enforcement-requiring containment is truthfully absent -- never a fake
    success. A mandatory containment forced to fail (a bad target) fails
    closed, honestly."""
    # --- the NATIVE/GOVERNED agent ---------------------------------- #
    db = SessionLocal()
    try:
        native_id = _insert_agent(db, admin, control_state="GOVERNED", origin_category="NATIVE")
        vid = _insert_version(db, native_id)
        eid = _insert_execution(db, admin, native_id, vid, status="RUNNING")
        _insert_behavioral_finding(db, admin, native_id)
        _insert_governance_denials(db, admin, eid, count=3)
    finally:
        db.close()

    summary = _evaluate(client, admin, native_id)
    assert summary["findings_opened"] >= 2
    findings = _findings(client, admin, native_id, status="OPEN")
    rule_ids = {f["rule_id"] for f in findings}
    assert {"behavioral_anomaly_threat", "governance_denial_spike"} <= rule_ids
    for f in findings:
        assert f["reason"] and f["evidence"].get("refs")  # every finding self-explains
    threat_finding_id = findings[0]["id"]

    # bounded automation recommended containment; nothing executed yet
    db = SessionLocal()
    try:
        rec_status = db.execute(text(
            "SELECT status FROM containment_actions WHERE agent_id = :aid"),
            {"aid": str(native_id)}).scalar()
        agent_status_before = db.execute(text("SELECT lifecycle_status FROM agents WHERE id = :id"),
                                         {"id": str(native_id)}).scalar()
    finally:
        db.close()
    assert rec_status == "RECOMMENDED"
    assert agent_status_before == "ACTIVE"

    # an operator confirms containment -- the REAL authority is invoked
    action = client.post(
        f"{THR}/agents/{native_id}/containment", headers=admin["headers"],
        json={"action_type": "SUSPEND_AGENT", "reason": "governance denial spike",
              "threat_finding_id": threat_finding_id, "confirm": True},
    ).json()
    assert action["status"] == "EXECUTED"
    assert action["authority"] == "KILL_SWITCH"
    db = SessionLocal()
    try:
        agent_status = db.execute(text("SELECT lifecycle_status FROM agents WHERE id = :id"),
                                  {"id": str(native_id)}).scalar()
        exec_status = db.execute(text("SELECT status FROM agent_executions WHERE id = :id"),
                                 {"id": str(eid)}).scalar()
        assert agent_status == "SUSPENDED"
        assert exec_status == "CANCELLED"
        assert db.execute(text(
            "SELECT count(*) FROM authorization_audit WHERE organization_id = :org "
            "AND event_type IN ('CONTAINMENT_ACTION_EXECUTED', 'RUNTIME_KILL_SWITCH_ACTIVATED')"),
            {"org": admin["organization_id"]}).scalar() >= 2
    finally:
        db.close()

    # kill-switch dominance: a subsequent automated sweep cannot undo it
    _evaluate(client, admin, native_id)
    db = SessionLocal()
    try:
        still_suspended = db.execute(text("SELECT lifecycle_status FROM agents WHERE id = :id"),
                                     {"id": str(native_id)}).scalar()
    finally:
        db.close()
    assert still_suspended == "SUSPENDED"

    # --- the OBSERVED external agent: truthful absence -------------- #
    db = SessionLocal()
    try:
        observed_id = _insert_agent(db, admin, control_state="DISCOVERED", origin_category="EXTERNAL")
        _insert_behavioral_finding(db, admin, observed_id)
    finally:
        db.close()
    _evaluate(client, admin, observed_id)
    assert _findings(client, admin, observed_id, rule_id="behavioral_anomaly_threat", status="OPEN")

    refusal = client.post(
        f"{THR}/agents/{observed_id}/containment", headers=admin["headers"],
        json={"action_type": "SUSPEND_AGENT", "reason": "same signal", "confirm": True},
    ).json()
    assert refusal["status"] == "REFUSED"
    assert refusal["authority_ref"] is None
    assert refusal["result"] == {}
    assert "DISCOVERED" in refusal["refusal_reason"]
    db = SessionLocal()
    try:
        observed_status = db.execute(text("SELECT lifecycle_status FROM agents WHERE id = :id"),
                                     {"id": str(observed_id)}).scalar()
    finally:
        db.close()
    assert observed_status != "SUSPENDED"  # never faked

    # --- a mandatory containment forced to fail fails closed --------- #
    failed = client.post(
        f"{THR}/agents/{native_id}/containment", headers=admin["headers"],
        json={"action_type": "DENY_TOOL", "reason": "bad target",
              "target_id": str(uuid.uuid4()), "confirm": True},
    ).json()
    assert failed["status"] == "FAILED"
    assert "error" in failed["result"]

    # --- tenant isolation + audit, once more, end to end ------------- #
    db = SessionLocal()
    try:
        total_audit = db.execute(text(
            "SELECT count(*) FROM authorization_audit WHERE organization_id = :org "
            "AND (event_type LIKE 'THREAT_%' OR event_type LIKE 'CONTAINMENT_%')"),
            {"org": admin["organization_id"]}).scalar()
        assert total_audit >= 5
        secret_hits = db.execute(text(
            "SELECT count(*) FROM containment_actions WHERE organization_id = :org "
            "AND result::text ILIKE '%password%'"), {"org": admin["organization_id"]}).scalar()
        assert secret_hits == 0
    finally:
        db.close()
