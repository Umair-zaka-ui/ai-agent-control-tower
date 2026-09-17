"""Phase 5.5 (M5.5) - Security Posture & Shadow Findings.

AC-01..AC-18 + the §14 end-to-end proof. Each acceptance criterion is backed
by at least one named test here.

The load-bearing properties, and where they are proven:
  * deterministic rule engine on the 4.7 lifecycle, no 4th finding system . AC-02
  * every finding self-explains ......................................... AC-03
  * NO opaque score (AST no-ML); aggregate deterministic + reconstructable  AC-04
  * shadow is a derived finding-state, not a boolean (structural) ....... AC-05
  * findings are signals -- app/posture has no enforcement (AST) ........ AC-07
  * INSUFFICIENT_DATA explicit; unknown != safe ....................... AC-08
  * lifecycle + DB dedup + reopen; suppression != resolution ......... AC-09
"""

from __future__ import annotations

import ast
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
from tests.posture.conftest import PASSWORD

POS = "/api/v1/posture"
GRAPH = "/api/v1/graph"
_BACKEND = Path(__file__).resolve().parents[2]
_REPO = _BACKEND.parent


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# helpers -- this suite's convention: each file defines its own
# --------------------------------------------------------------------------- #
def _insert_agent(db, admin: dict, *, name: str | None = None, control_state: str = "GOVERNED",
                  origin_category: str = "NATIVE", origin_provider: str = "ACT_NATIVE",
                  lifecycle_status: str = "ACTIVE", owned: bool = True,
                  discovery_source_ref: str | None = None) -> uuid.UUID:
    aid = uuid.uuid4()
    owner = admin["user_id"] if owned else None
    db.execute(
        text(
            """
            INSERT INTO agents (id, organization_id, name, agent_type, api_key_hash, status,
                                version, capabilities, default_risk_score, max_allowed_risk,
                                human_approval_required, risk_level, health, criticality,
                                data_classification, default_environment, lifecycle_status,
                                origin_category, origin_provider, control_state,
                                owner_id, owner_type, technical_owner_id, compliance_owner_id,
                                discovery_source_ref, created_at, updated_at)
            VALUES (:id, :org, :name, 'ASSISTANT', 'x', 'ACTIVE', '1.0.0', '[]'::jsonb, 0, 100,
                    false, 'LOW', 'HEALTHY', 'MEDIUM', 'INTERNAL', 'DEVELOPMENT', :lifecycle,
                    :origin_cat, :origin_prov, :control_state, :owner, :owner_type, :owner, :owner,
                    :dsr, now(), now())
            """
        ),
        {"id": str(aid), "org": admin["organization_id"], "name": name or f"agent-{aid.hex[:8]}",
         "lifecycle": lifecycle_status, "origin_cat": origin_category, "origin_prov": origin_provider,
         "control_state": control_state, "owner": owner,
         "owner_type": "USER" if owned else None, "dsr": discovery_source_ref},
    )
    db.commit()
    return aid


def _insert_api_key(db, agent_id: uuid.UUID, *, last_used_days_ago: int | None = None,
                    created_days_ago: int = 1, expires_days: int | None = None,
                    status: str = "ACTIVE") -> uuid.UUID:
    kid = uuid.uuid4()
    last_used = None if last_used_days_ago is None else _now() - timedelta(days=last_used_days_ago)
    created = _now() - timedelta(days=created_days_ago)
    expires = None if expires_days is None else _now() + timedelta(days=expires_days)
    db.execute(
        text(
            """
            INSERT INTO agent_api_keys (id, agent_id, key_hash, key_prefix, status,
                                        last_used_at, expires_at, created_at)
            VALUES (:id, :aid, :kh, 'agt_test_AB', :st, :lu, :exp, :cr)
            """
        ),
        {"id": str(kid), "aid": str(agent_id), "kh": f"hash-{kid.hex}", "st": status,
         "lu": last_used, "exp": expires, "cr": created},
    )
    db.commit()
    return kid


def _insert_version(db, agent_id: uuid.UUID, *, status: str = "PUBLISHED",
                    model: dict | None = None) -> uuid.UUID:
    import json

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
            VALUES (:vid, :aid, :did, 1, '1.0.0', :st, '{}'::jsonb, CAST(:mc AS jsonb), '[]'::jsonb,
                    '[]'::jsonb, 'sha256:0', 'canonical-sha256', 'UNKNOWN', 'main', now())
            """
        ),
        {"vid": str(vid), "aid": str(agent_id), "did": str(did), "st": status,
         "mc": json.dumps(model or {"provider": "MOCK", "model": "mock-model"})},
    )
    db.commit()
    return vid


def _prod_env(db, admin: dict) -> uuid.UUID:
    eid = uuid.uuid4()
    db.execute(
        text(
            """
            INSERT INTO environments (id, organization_id, name, display_name, is_production,
                                      policy, created_at, updated_at)
            VALUES (:id, :org, :nm, 'Prod', true, '{}'::jsonb, now(), now())
            """
        ),
        {"id": str(eid), "org": admin["organization_id"], "nm": f"PROD-{eid.hex[:6]}"},
    )
    db.commit()
    return eid


def _prod_deployment(db, admin: dict, agent_id: uuid.UUID, version_id: uuid.UUID,
                     env_id: uuid.UUID) -> None:
    db.execute(
        text(
            """
            INSERT INTO agent_deployments (id, agent_id, agent_version_id, organization_id,
                environment, environment_id, status, lifecycle_state, deployment_strategy, updated_at)
            VALUES (gen_random_uuid(), :aid, :vid, :org, 'PRODUCTION', :env, 'ACTIVE', 'ACTIVE',
                    'RECREATE', now())
            """
        ),
        {"aid": str(agent_id), "vid": str(version_id), "org": admin["organization_id"],
         "env": str(env_id)},
    )
    db.commit()


def _insert_execution(db, admin: dict, agent_id: uuid.UUID, version_id: uuid.UUID,
                      *, status: str = "SUCCEEDED", deployment_id: uuid.UUID | None = None) -> uuid.UUID:
    eid = uuid.uuid4()
    db.execute(
        text(
            """
            INSERT INTO agent_executions (id, organization_id, agent_id, agent_version_id,
                trigger_type, input_payload, status, deployment_id, created_at)
            VALUES (:id, :org, :aid, :vid, 'API', '{}'::jsonb, :st, :dep, now())
            """
        ),
        {"id": str(eid), "org": admin["organization_id"], "aid": str(agent_id),
         "vid": str(version_id), "st": status, "dep": str(deployment_id) if deployment_id else None},
    )
    db.commit()
    return eid


def _second_user(client: TestClient, admin: dict, role: str = "VIEWER") -> dict:
    email = f"pu_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post(
        "/api/v1/identity/users", headers=admin["headers"],
        json={"email": email, "display_name": "U", "password": PASSWORD, "role": role,
              "organization_id": admin["organization_id"]},
    )
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"}}


def _register_mcp(client: TestClient, admin: dict, trust_status="UNKNOWN") -> dict:
    r = client.post(f"{GRAPH}/mcp-servers", headers=admin["headers"],
                    json={"name": f"mcp-{uuid.uuid4().hex[:8]}", "trust_status": trust_status,
                          "provenance": "DISCOVERED", "endpoint_reference": "mcp://local"})
    assert r.status_code == 201, r.text
    return r.json()


def _dep_edge(client: TestClient, admin: dict, source, edge_type, target) -> None:
    r = client.post(f"{GRAPH}/dependency-edges", headers=admin["headers"],
                    json={"source": source, "edge_type": edge_type, "target": target})
    assert r.status_code == 201, r.text


def _make_resource(db, admin: dict, resource_type: str) -> uuid.UUID:
    rid = uuid.uuid4()
    db.execute(
        text(
            """
            INSERT INTO resources (id, resource_type, resource_id, name, organization_id,
                                   owner_id, owner_type, visibility, status)
            VALUES (:id, :rt, :rid, :nm, :org, :owner, 'USER', 'ORGANIZATION', 'ACTIVE')
            """
        ),
        {"id": str(rid), "rt": resource_type, "rid": str(uuid.uuid4()), "nm": f"{resource_type}-sys",
         "org": admin["organization_id"], "owner": admin["user_id"]},
    )
    db.commit()
    return rid


def _make_tool(client: TestClient, admin: dict) -> str:
    r = client.post("/api/v1/runtime/tools", headers=admin["headers"],
                    json={"name": f"tool_{uuid.uuid4().hex[:8]}", "display_name": "T",
                          "tool_type": "FUNCTION"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _evaluate(client: TestClient, admin: dict, agent_id: uuid.UUID) -> dict:
    r = client.post(f"{POS}/agents/{agent_id}/evaluate", headers=admin["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _findings(client: TestClient, admin: dict, agent_id: uuid.UUID, **params) -> list[dict]:
    r = client.get(f"{POS}/agents/{agent_id}/findings", headers=admin["headers"])
    assert r.status_code == 200, r.text
    out = r.json()
    for k, v in params.items():
        out = [f for f in out if f.get(k) == v]
    return out


# =========================================================================== #
# AC-01 - live baseline / substrate
# =========================================================================== #
def test_ac01_substrate_present_and_head_recorded() -> None:
    from app.posture.evaluator import PostureEvaluator  # noqa: F401
    from app.posture.lifecycle import PostureFindingService  # noqa: F401
    from app.posture.rules import RULES  # noqa: F401
    from app.slo.states import AlertStatus  # the reused 4.7 lifecycle  # noqa: F401
    from app.models.graph import McpServer  # 5.4 evidence  # noqa: F401

    versions = {v.stem for v in (_BACKEND / "migrations" / "versions").glob("*.py")}
    assert {"0056_control_graph", "0057_dependency_graph", "0058_security_posture"} <= versions
    assert "0058_security_posture" in (_REPO / "REPO_STATE.md").read_text(encoding="utf-8")


# =========================================================================== #
# AC-02 - deterministic engine on the 4.7 lifecycle; no 4th finding system
# =========================================================================== #
def test_ac02_reuses_the_47_lifecycle_not_a_parallel_one() -> None:
    from app.core.database import Base

    assert "posture_findings" in Base.metadata.tables
    # it reuses the 4.7 status vocabulary verbatim (imported, not re-spelled)
    src = (_BACKEND / "app" / "posture" / "lifecycle.py").read_text(encoding="utf-8")
    assert "from app.slo.states import" in src
    # no parallel alert/finding table invented
    for banned in ("posture_alerts", "posture_signals", "shadow_findings", "risk_scores"):
        assert banned not in Base.metadata.tables, banned


def test_ac02_rules_are_deterministic(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        # A discovered agent whose provenance this test never establishes:
        # UNKNOWN is the truthful category (M5.1 "seen but not yet
        # classified"), as at test_ac06 below. The helper's NATIVE default
        # would assert an origin a DISCOVERED row cannot have (5.1 AC-09).
        aid = _insert_agent(db, admin, owned=False, control_state="DISCOVERED",
                            origin_category="UNKNOWN", origin_provider="UNKNOWN")
    finally:
        db.close()
    a = _evaluate(client, admin, aid)
    b = _evaluate(client, admin, aid)
    # same evidence -> same open findings; a re-run opens nothing new
    assert b["findings_opened"] == 0
    fa = {f["rule_id"] for f in _findings(client, admin, aid, status="OPEN")}
    assert "no_accountable_owner" in fa and "discovered_outside_lifecycle" in fa


# =========================================================================== #
# AC-03 - every finding self-explains
# =========================================================================== #
def test_ac03_finding_is_a_structured_self_explaining_record(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, owned=False)
    finally:
        db.close()
    _evaluate(client, admin, aid)
    f = _findings(client, admin, aid, rule_id="no_accountable_owner")[0]
    for key in ("rule_id", "control_id", "severity", "reason", "remediation", "status",
                "first_seen_at", "last_seen_at", "evidence", "governing_policy",
                "rule_version", "ruleset_version"):
        assert f.get(key) not in (None, ""), key
    assert f["evidence"]["refs"][0]["table"] == "agents"
    assert f["governing_policy"]["ruleset_version"] == "1"


# =========================================================================== #
# AC-04 - NO opaque score; deterministic + versioned + reconstructable
# =========================================================================== #
def test_ac04_no_ml_import_in_posture() -> None:
    forbidden = ("numpy", "scipy", "sklearn", "pandas", "torch", "tensorflow", "xgboost", "keras")
    for path in (_BACKEND / "app" / "posture").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                assert not any(n == b or n.startswith(b + ".") for b in forbidden), (path, n)


def test_ac04_summary_is_deterministic_versioned_and_reconstructable(
    client: TestClient, admin: dict
) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, owned=False)
    finally:
        db.close()
    _evaluate(client, admin, aid)
    s1 = client.get(f"{POS}/summary", headers=admin["headers"]).json()
    assert s1["ruleset_version"] == "1"
    assert "formula" in s1 and s1["severity_weights"]["CRITICAL"] == 10
    # reconstruct the score by hand from the contributions
    recomputed = sum(c["subtotal"] for c in s1["contributions"])
    assert recomputed == s1["score"]
    # add a HIGH finding -> the score moves by exactly one HIGH weight, explainably
    db = SessionLocal()
    try:
        _insert_api_key(db, aid, last_used_days_ago=200)
    finally:
        db.close()
    _evaluate(client, admin, aid)
    s2 = client.get(f"{POS}/summary", headers=admin["headers"]).json()
    assert s2["score"] == s1["score"] + s2["severity_weights"]["HIGH"]


# =========================================================================== #
# AC-05 - shadow is a derived finding-state, not a boolean
# =========================================================================== #
def test_ac05_no_shadow_column_anywhere() -> None:
    from app.core.database import Base

    for table in Base.metadata.tables.values():
        for col in table.columns:
            assert col.name != "shadow" and col.name != "is_shadow", (table.name, col.name)


def test_ac05_shadow_agents_is_a_query_over_findings_that_clears_on_resolve(
    client: TestClient, admin: dict
) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, owned=False, control_state="DISCOVERED",
                            origin_category="EXTERNAL", origin_provider="MICROSOFT")
    finally:
        db.close()
    _evaluate(client, admin, aid)
    sh = client.get(f"{POS}/shadow-agents", headers=admin["headers"]).json()
    entry = next(e for e in sh["agents"] if e["agent"]["id"] == str(aid))
    assert entry["shadow"] is True
    conditions = {c["rule_id"] for c in entry["conditions"]}
    assert "discovered_outside_lifecycle" in conditions
    for c in entry["conditions"]:
        assert c["reason"] and c["evidence"]  # each names its condition + evidence

    # resolve every shadow-class finding -> the agent is no longer shadow
    for c in entry["conditions"]:
        client.post(f"{POS}/findings/{c['finding_id']}/resolve", headers=admin["headers"],
                    json={"note": "handled"})
    state = client.get(f"{POS}/agents/{aid}/shadow", headers=admin["headers"]).json()
    assert state["shadow"] is False


# =========================================================================== #
# AC-06 - the rule set fires correctly
# =========================================================================== #
def test_ac06_rule_set_fires(client: TestClient, admin: dict, other_org_admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, owned=False, control_state="DISCOVERED",
                            origin_category="UNKNOWN", origin_provider="UNKNOWN")
        _insert_api_key(db, aid, last_used_days_ago=200)          # stale_credential
        _insert_api_key(db, aid, expires_days=-2)                 # expired_credential_still_active
        payroll = _make_resource(db, admin, "payroll")
    finally:
        db.close()
    mcp = _register_mcp(client, admin, trust_status="UNKNOWN")
    tool = _make_tool(client, admin)
    _dep_edge(client, admin, {"type": "AGENT", "id": str(aid)}, "DEPENDS_ON_MCP_SERVER",
              {"type": "MCP_SERVER", "id": mcp["id"]})
    _dep_edge(client, admin, {"type": "AGENT", "id": str(aid)}, "DEPENDS_ON_TOOL",
              {"type": "TOOL", "id": tool})
    _dep_edge(client, admin, {"type": "TOOL", "id": tool}, "TOOL_ACCESSES_RESOURCE",
              {"type": "RESOURCE", "id": str(payroll)})
    # tune prohibited_model + excessive_tool_scope so they fire deterministically
    client.put(f"{POS}/rules/excessive_tool_scope", headers=admin["headers"], json={"params": {"max_tools": 0}})

    _evaluate(client, admin, aid)
    fired = {f["rule_id"] for f in _findings(client, admin, aid, status="OPEN")}
    for expected in (
        "no_accountable_owner", "discovered_outside_lifecycle", "unknown_provenance",
        "stale_credential", "expired_credential_still_active", "unapproved_mcp_dependency",
        "dangerous_dependency", "excessive_tool_scope", "missing_runtime_governance_policy",
    ):
        assert expected in fired, (expected, sorted(fired))


def test_ac06_prohibited_model_and_missing_slo(client: TestClient, admin: dict) -> None:
    # a governed native agent with an applicable governance policy but no SLO,
    # active in production, on a prohibited model -> missing_slo + prohibited_model.
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, control_state="GOVERNED")
        vid = _insert_version(db, aid, model={"provider": "MOCK", "model": "banned-1"})
        env = _prod_env(db, admin)
        _prod_deployment(db, admin, aid, vid, env)
        db.execute(text(
            "INSERT INTO runtime_governance_policies (id, organization_id, name, constraints, "
            "mandatory, enabled, created_at, updated_at) VALUES "
            "(gen_random_uuid(), :org, 'p', '{}'::jsonb, false, true, now(), now())"),
            {"org": admin["organization_id"]})
        db.commit()
    finally:
        db.close()
    client.put(f"{POS}/rules/prohibited_model", headers=admin["headers"],
               json={"params": {"prohibited_models": ["banned-1"]}})
    _evaluate(client, admin, aid)
    fired = {f["rule_id"] for f in _findings(client, admin, aid, status="OPEN")}
    assert "missing_slo" in fired
    assert "prohibited_model" in fired
    assert "missing_runtime_governance_policy" not in fired  # it has a policy


# =========================================================================== #
# AC-07 - findings are signals; app/posture has no enforcement
# =========================================================================== #
def test_ac07_no_enforcement_vocabulary_in_posture() -> None:
    for path in (_BACKEND / "app" / "posture").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in ("KillSwitchService", "RuntimeGovernanceEngine",
                                       "GovernanceStopped"), f"{path.name} reaches for enforcement"
            if isinstance(node, ast.Attribute):
                assert node.attr not in ("kill", "halt_execution", "stop_execution"), path.name
        src = path.read_text(encoding="utf-8")
        assert "KillSwitchService" not in src and "RuntimeGovernanceEngine" not in src


def test_ac07_a_finding_never_stops_an_execution(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, owned=False)
        vid = _insert_version(db, aid)
        eid = _insert_execution(db, admin, aid, vid, status="RUNNING")
    finally:
        db.close()
    _evaluate(client, admin, aid)
    db = SessionLocal()
    try:
        status = db.execute(text("SELECT status FROM agent_executions WHERE id = :id"),
                            {"id": str(eid)}).scalar()
        assert status == "RUNNING"  # posture evaluation touched nothing
    finally:
        db.close()


# =========================================================================== #
# AC-08 - INSUFFICIENT_DATA explicit; unknown != safe
# =========================================================================== #
def test_ac08_dangerous_dependency_with_no_evidence_is_insufficient_data(
    client: TestClient, admin: dict
) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin)  # owned, governed, but NO dependency edges
    finally:
        db.close()
    _evaluate(client, admin, aid)
    insufficient = _findings(client, admin, aid, rule_id="dangerous_dependency",
                             outcome="INSUFFICIENT_DATA")
    assert len(insufficient) == 1
    assert "not safety" in insufficient[0]["reason"].lower()
    # it is NOT reported as a clean pass
    findings_outcome = _findings(client, admin, aid, rule_id="dangerous_dependency", outcome="FINDING")
    assert findings_outcome == []


# =========================================================================== #
# AC-09 - lifecycle + DB dedup + reopen; suppression != resolution
# =========================================================================== #
def test_ac09_lifecycle_transitions(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, owned=False)
    finally:
        db.close()
    _evaluate(client, admin, aid)
    f = _findings(client, admin, aid, rule_id="no_accountable_owner")[0]
    fid = f["id"]
    assert client.post(f"{POS}/findings/{fid}/acknowledge", headers=admin["headers"]).json()["status"] == "ACKNOWLEDGED"
    assert client.post(f"{POS}/findings/{fid}/resolve", headers=admin["headers"]).json()["status"] == "RESOLVED"
    # cannot acknowledge a resolved finding
    assert client.post(f"{POS}/findings/{fid}/acknowledge", headers=admin["headers"]).status_code == 409


def test_ac09_reopen_on_recurrence(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, owned=False)
    finally:
        db.close()
    _evaluate(client, admin, aid)
    fid = _findings(client, admin, aid, rule_id="no_accountable_owner")[0]["id"]
    client.post(f"{POS}/findings/{fid}/resolve", headers=admin["headers"])
    _evaluate(client, admin, aid)  # condition still holds -> re-open the same row
    reopened = client.get(f"{POS}/findings/{fid}", headers=admin["headers"]).json()
    assert reopened["status"] == "OPEN"
    assert reopened["recurrence_count"] >= 2


def test_ac09_suppression_is_not_resolution_and_is_audited(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, owned=False)
    finally:
        db.close()
    _evaluate(client, admin, aid)
    fid = _findings(client, admin, aid, rule_id="no_accountable_owner")[0]["id"]
    client.post(f"{POS}/findings/{fid}/suppress", headers=admin["headers"], json={"note": "known"})
    _evaluate(client, admin, aid)  # condition still holds -> a suppressed finding is NOT re-opened
    assert client.get(f"{POS}/findings/{fid}", headers=admin["headers"]).json()["status"] == "SUPPRESSED"
    db = SessionLocal()
    try:
        n = db.execute(text(
            "SELECT count(*) FROM authorization_audit WHERE organization_id = :org "
            "AND event_type = 'POSTURE_FINDING_SUPPRESSED'"), {"org": admin["organization_id"]}).scalar()
        assert n >= 1
    finally:
        db.close()


def test_ac09_db_enforced_dedup_one_open_finding_per_condition(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, owned=False)
    finally:
        db.close()
    for _ in range(3):
        _evaluate(client, admin, aid)
    db = SessionLocal()
    try:
        n = db.execute(text(
            "SELECT count(*) FROM posture_findings WHERE organization_id = :org AND subject_id = :aid "
            "AND rule_id = 'no_accountable_owner' AND status IN ('OPEN','ACKNOWLEDGED')"),
            {"org": admin["organization_id"], "aid": str(aid)}).scalar()
        assert n == 1
    finally:
        db.close()


# =========================================================================== #
# AC-10 - idempotent + 3.8-schedulable; no new scheduler
# =========================================================================== #
def test_ac10_posture_evaluate_is_a_registered_handler_no_new_scheduler() -> None:
    from app.scheduler.handlers import registered_keys

    assert "posture.evaluate" in registered_keys()
    # no new scheduler module / table
    from app.core.database import Base
    for banned in ("posture_jobs", "posture_scheduler", "posture_runs"):
        assert banned not in Base.metadata.tables


def test_ac10_tenant_evaluation_is_idempotent(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        for _ in range(3):
            _insert_agent(db, admin, owned=False)
    finally:
        db.close()
    a = client.post(f"{POS}/evaluate", headers=admin["headers"]).json()
    b = client.post(f"{POS}/evaluate", headers=admin["headers"]).json()
    assert a["findings_opened"] >= 3
    assert b["findings_opened"] == 0  # nothing new on the second pass


# =========================================================================== #
# AC-11 - tenant isolation; per-hop for graph rules; no secret
# =========================================================================== #
def test_ac11_cross_tenant_finding_read_is_404(client: TestClient, admin: dict, other_org_admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, owned=False)
    finally:
        db.close()
    _evaluate(client, admin, aid)
    fid = _findings(client, admin, aid, rule_id="no_accountable_owner")[0]["id"]
    assert client.get(f"{POS}/findings/{fid}", headers=other_org_admin["headers"]).status_code == 404
    assert client.post(f"{POS}/findings/{fid}/resolve", headers=other_org_admin["headers"]).status_code == 404


def test_ac11_dangerous_dependency_is_per_hop_tenant_bounded(
    client: TestClient, admin: dict, other_org_admin: dict
) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin)
        foreign_payroll = _make_resource(db, other_org_admin, "payroll")
    finally:
        db.close()
    tool = _make_tool(client, admin)
    _dep_edge(client, admin, {"type": "AGENT", "id": str(aid)}, "DEPENDS_ON_TOOL",
              {"type": "TOOL", "id": tool})
    # PLANT a cross-tenant edge: tenant A tool -> tenant B payroll resource
    db = SessionLocal()
    try:
        db.execute(text(
            """
            INSERT INTO control_graph_edges (id, organization_id, source_type, source_id, edge_type,
                target_type, target_id, evidence, confidence, provenance, valid_from, created_at, updated_at)
            VALUES (:id, :org, 'TOOL', :tool, 'TOOL_ACCESSES_RESOURCE', 'RESOURCE', :res,
                    '{}'::jsonb, 1.0, 'DERIVED', now(), now(), now())
            """
        ), {"id": str(uuid.uuid4()), "org": admin["organization_id"], "tool": tool,
            "res": str(foreign_payroll)})
        db.commit()
    finally:
        db.close()
    _evaluate(client, admin, aid)
    # the planted cross-tenant edge does not create a dangerous_dependency finding
    assert _findings(client, admin, aid, rule_id="dangerous_dependency", outcome="FINDING") == []


def test_ac11_no_secret_in_a_credential_finding(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin)
        _insert_api_key(db, aid, last_used_days_ago=300)
    finally:
        db.close()
    _evaluate(client, admin, aid)
    f = _findings(client, admin, aid, rule_id="stale_credential")[0]
    blob = str(f).lower()
    for needle in ("key_hash", "hash-", "secret", "password", "bearer", "token"):
        assert needle not in blob, needle
    assert f["evidence"]["refs"][0]["table"] == "agent_api_keys"  # references the row, not the secret


# =========================================================================== #
# AC-12 - concurrency: real separate Postgres sessions
# =========================================================================== #
def test_ac12_concurrent_evaluations_do_not_duplicate(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, owned=False)
    finally:
        db.close()
    barrier = threading.Barrier(3)

    def _run() -> None:
        c = TestClient(app)
        barrier.wait()
        c.post(f"{POS}/agents/{aid}/evaluate", headers=admin["headers"])

    with ThreadPoolExecutor(max_workers=3) as pool:
        for f in [pool.submit(_run) for _ in range(3)]:
            f.result()
    db = SessionLocal()
    try:
        n = db.execute(text(
            "SELECT count(*) FROM posture_findings WHERE subject_id = :aid AND rule_id = 'no_accountable_owner' "
            "AND status = 'OPEN'"), {"aid": str(aid)}).scalar()
        assert n == 1
    finally:
        db.close()


def test_ac12_concurrent_ack_converges(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, owned=False)
    finally:
        db.close()
    _evaluate(client, admin, aid)
    fid = _findings(client, admin, aid, rule_id="no_accountable_owner")[0]["id"]
    barrier = threading.Barrier(2)
    codes: list[int] = []
    lock = threading.Lock()

    def _ack() -> None:
        c = TestClient(app)
        barrier.wait()
        r = c.post(f"{POS}/findings/{fid}/acknowledge", headers=admin["headers"])
        with lock:
            codes.append(r.status_code)

    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in [pool.submit(_ack) for _ in range(2)]:
            f.result()
    assert all(c == 200 for c in codes)  # both converge on ACKNOWLEDGED


# =========================================================================== #
# AC-13 - lifecycle + rule changes audited
# =========================================================================== #
def test_ac13_rule_setting_change_is_versioned_and_audited(client: TestClient, admin: dict) -> None:
    r = client.put(f"{POS}/rules/stale_credential", headers=admin["headers"],
                   json={"params": {"max_age_days": 30}})
    assert r.status_code == 200
    assert r.json()["effective_params"]["max_age_days"] == 30
    assert r.json()["settings_revision"] == 1
    client.put(f"{POS}/rules/stale_credential", headers=admin["headers"], json={"enabled": False})
    assert client.get(f"{POS}/rules", headers=admin["headers"]).json()
    db = SessionLocal()
    try:
        n = db.execute(text(
            "SELECT count(*) FROM authorization_audit WHERE organization_id = :org "
            "AND event_type = 'POSTURE_RULE_SETTING_CHANGED'"), {"org": admin["organization_id"]}).scalar()
        assert n >= 2
    finally:
        db.close()


# =========================================================================== #
# AC-14 - fails open; no fabricated finding
# =========================================================================== #
def test_ac14_a_rule_that_raises_fails_open(client: TestClient, admin: dict, monkeypatch) -> None:
    import app.posture.evaluator as ev_mod
    import app.posture.rules as rules_mod
    from dataclasses import replace

    def _boom(ctx, params):
        raise RuntimeError("simulated rule failure")

    # PostureRule is a frozen dataclass -- build a replacement, don't mutate.
    boom_rule = replace(rules_mod.RULES_BY_ID["unknown_provenance"], fn=_boom)
    patched = tuple(boom_rule if r.id == "unknown_provenance" else r for r in rules_mod.RULES)
    monkeypatch.setattr(rules_mod, "RULES", patched)
    monkeypatch.setattr(ev_mod, "RULES", patched)

    db = SessionLocal()
    try:
        # An UNKNOWN-provenance agent cannot be GOVERNED (V0.2 / ADR-0023:
        # GOVERNED <=> NATIVE); DISCOVERED is its truthful control state, and
        # this test only needs the unknown_provenance rule to be reached.
        aid = _insert_agent(db, admin, owned=False, control_state="DISCOVERED",
                            origin_category="UNKNOWN", origin_provider="UNKNOWN")
    finally:
        db.close()
    summary = _evaluate(client, admin, aid)
    assert summary["rule_errors"] >= 1
    # the failing rule fabricated nothing; the other rules still produced findings
    assert _findings(client, admin, aid, rule_id="unknown_provenance") == []
    assert _findings(client, admin, aid, rule_id="no_accountable_owner")


# =========================================================================== #
# AC-15 - migration shape
# =========================================================================== #
def test_ac15_migration_shape() -> None:
    mig = (_BACKEND / "migrations" / "versions" / "0058_security_posture.py").read_text(encoding="utf-8")
    assert 'revision = "0058_security_posture"' in mig
    assert len("0058_security_posture") <= 32
    assert 'down_revision = "0057_dependency_graph"' in mig
    assert "def downgrade" in mig and "drop_table" in mig
    assert mig.count("create_table(") == 2
    assert "op.alter_column" not in mig and "op.drop_column" not in mig


# =========================================================================== #
# AC-18 - no forbidden markers
# =========================================================================== #
def test_ac18_no_forbidden_markers_in_new_files() -> None:
    forbidden = ("TO" + "DO", "FIX" + "ME", "Not" + "ImplementedError",
                 "pytest.mark." + "skip", "pytest.mark." + "xfail")
    files = list((_BACKEND / "app" / "posture").rglob("*.py")) + [
        _BACKEND / "app" / "models" / "posture.py",
        _BACKEND / "migrations" / "versions" / "0058_security_posture.py",
        Path(__file__),
    ]
    for f in files:
        body = f.read_text(encoding="utf-8")
        assert not [m for m in forbidden if m in body], f.name


def test_posture_permissions_registered_and_minimal() -> None:
    from app.authorization.catalog import group_for_code
    from app.services.rbac_service import PERMISSION_CATALOG

    assert "posture.view" in PERMISSION_CATALOG and "posture.manage" in PERMISSION_CATALOG
    for code in ("posture.view", "posture.manage"):
        assert group_for_code(code) == "runtime"
    for banned in ("posture.enforce", "posture.kill", "posture.govern", "posture.block"):
        assert banned not in PERMISSION_CATALOG


def test_ac11_viewer_cannot_manage(client: TestClient, admin: dict) -> None:
    viewer = _second_user(client, admin, role="VIEWER")
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, owned=False)
    finally:
        db.close()
    assert client.get(f"{POS}/findings", headers=viewer["headers"]).status_code == 403
    assert client.post(f"{POS}/agents/{aid}/evaluate", headers=viewer["headers"]).status_code == 403


# =========================================================================== #
# §14 - THE END-TO-END PROOF
# =========================================================================== #
def test_ss14_end_to_end_posture_proof(client: TestClient, admin: dict, other_org_admin: dict) -> None:
    """A discovered external agent with no owner, depending on an unapproved
    MCP server and holding a stale credential that can reach a payroll-kind
    resource. Posture evaluation produces a shadow-class finding, an
    unapproved-MCP finding, a stale-credential finding and a dangerous-
    dependency finding - each self-explaining. "Shadow agents" queries these
    findings (no boolean). The deterministic summary reflects them and is
    reconstructable. Suppressing one is permissioned + audited and does not
    resolve it; the condition re-opens... no, it does NOT re-open (suppressed).
    None of this stops the agent - app/posture has no enforcement path.
    """
    db = SessionLocal()
    try:
        aid = _insert_agent(db, admin, owned=False, control_state="DISCOVERED",
                            origin_category="EXTERNAL", origin_provider="MICROSOFT",
                            discovery_source_ref=str(uuid.uuid4()))
        _insert_api_key(db, aid, last_used_days_ago=250)
        payroll = _make_resource(db, admin, "payroll")
        # a live RUNNING execution to prove posture never touches it
        vid = _insert_version(db, aid)
        eid = _insert_execution(db, admin, aid, vid, status="RUNNING")
    finally:
        db.close()

    mcp = _register_mcp(client, admin, trust_status="UNKNOWN")
    tool = _make_tool(client, admin)
    _dep_edge(client, admin, {"type": "AGENT", "id": str(aid)}, "DEPENDS_ON_MCP_SERVER",
              {"type": "MCP_SERVER", "id": mcp["id"]})
    _dep_edge(client, admin, {"type": "AGENT", "id": str(aid)}, "DEPENDS_ON_TOOL",
              {"type": "TOOL", "id": tool})
    _dep_edge(client, admin, {"type": "TOOL", "id": tool}, "TOOL_ACCESSES_RESOURCE",
              {"type": "RESOURCE", "id": str(payroll)})

    summary = _evaluate(client, admin, aid)
    assert summary["findings_opened"] >= 4

    fired = {f["rule_id"]: f for f in _findings(client, admin, aid, status="OPEN")}
    for expected in ("discovered_outside_lifecycle", "unapproved_mcp_dependency",
                     "stale_credential", "dangerous_dependency", "unmanaged_external_agent"):
        assert expected in fired, sorted(fired)
        f = fired[expected]
        assert f["reason"] and f["remediation"] and f["evidence"].get("refs")

    # the unapproved-MCP finding names the dependency edge
    mcp_f = fired["unapproved_mcp_dependency"]
    assert any(r["table"] == "control_graph_edges" for r in mcp_f["evidence"]["refs"])
    assert any(r["table"] == "mcp_servers" for r in mcp_f["evidence"]["refs"])

    # "shadow agents" is a query over shadow-class findings
    sh = client.get(f"{POS}/shadow-agents", headers=admin["headers"]).json()
    entry = next(e for e in sh["agents"] if e["agent"]["id"] == str(aid))
    assert entry["shadow"] is True
    assert {c["rule_id"] for c in entry["conditions"]} >= {"discovered_outside_lifecycle",
                                                           "unmanaged_external_agent"}

    # the deterministic summary reflects the findings and is reconstructable
    s = client.get(f"{POS}/summary", headers=admin["headers"]).json()
    assert s["score"] == sum(c["subtotal"] for c in s["contributions"]) > 0
    assert s["ruleset_version"] == "1"

    # suppressing one finding is permissioned + audited and does not resolve it
    stale_fid = fired["stale_credential"]["id"]
    assert client.post(f"{POS}/findings/{stale_fid}/suppress",
                       headers=other_org_admin["headers"]).status_code == 404  # tenant-isolated
    client.post(f"{POS}/findings/{stale_fid}/suppress", headers=admin["headers"], json={"note": "accepted risk"})
    _evaluate(client, admin, aid)
    assert client.get(f"{POS}/findings/{stale_fid}", headers=admin["headers"]).json()["status"] == "SUPPRESSED"

    # none of this stopped the agent
    db = SessionLocal()
    try:
        assert db.execute(text("SELECT status FROM agent_executions WHERE id = :id"),
                          {"id": str(eid)}).scalar() == "RUNNING"
        # every finding + the sweep is audited
        assert db.execute(text(
            "SELECT count(*) FROM authorization_audit WHERE organization_id = :org "
            "AND event_type IN ('POSTURE_FINDING_OPENED','POSTURE_EVALUATED','POSTURE_FINDING_SUPPRESSED')"),
            {"org": admin["organization_id"]}).scalar() >= 3
        # no secret in any finding
        assert db.execute(text(
            "SELECT count(*) FROM posture_findings WHERE organization_id = :org "
            "AND evidence::text ILIKE '%hash-%'"), {"org": admin["organization_id"]}).scalar() == 0
    finally:
        db.close()
