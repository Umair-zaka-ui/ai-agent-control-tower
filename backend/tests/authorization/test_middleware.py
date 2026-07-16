"""Phase 4.3.6 integration + security tests (§37) — REST enforcement through
the gateway, ABAC challenges on protected routes, worker/workflow/scheduler
authorization, the agent runtime enforcement point, the six §24 audit events,
middleware bypass attempts and the metrics endpoint."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

PASSWORD = "T3st!Passw0rd#Ok"
BASE = "/api/v1/authorization"


def _register_org(client: TestClient, org: str = "Mw Org") -> dict:
    email = f"mw_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": org, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"],
            "organization_id": me["user"]["organization_id"], "email": email}


def _invite_member(client: TestClient, admin: dict, *, role: str = "VIEWER") -> dict:
    email = f"mwm_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "Member", "password": PASSWORD, "role": role,
        "organization_id": admin["organization_id"],
    })
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "email": email}


def _publish_policy(client: TestClient, who: dict, *, effect: str,
                    actions: list[str], obligations: dict | None = None,
                    identity_types: list[str] | None = None,
                    conditions: dict | None = None) -> dict:
    target: dict = {"actions": actions}
    if identity_types:
        target["identity_types"] = identity_types
    subject_type = (identity_types or ["HUMAN_USER"])[0]
    body = {
        "name": f"mw_{uuid.uuid4().hex[:8]}", "effect": effect, "target": target,
        "conditions": conditions or {"all": [
            {"attribute": "identity.type", "operator": "EQUALS", "value": subject_type},
        ]},
    }
    if obligations:
        body["obligations"] = obligations
    r = client.post(f"{BASE}/abac/policies", json=body, headers=who["headers"])
    assert r.status_code == 201, r.text
    policy = r.json()
    r = client.post(f"{BASE}/abac/policies/{policy['id']}/publish", headers=who["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _user(db_session, user_id: str):
    from app.models.user import User

    return db_session.get(User, uuid.UUID(user_id))


# --------------------------------------------------------------------------- #
# §27 — every protected API flows through the gateway (no bypass)
# --------------------------------------------------------------------------- #
def test_protected_route_cannot_bypass_gateway(client: TestClient, admin: dict,
                                               monkeypatch) -> None:
    """If the gateway is unavailable the protected route must fail, proving
    require_permission has no fallback path around the middleware (§36)."""
    from app.authorization.middleware.gateway import AuthorizationGateway

    def _boom(self, *a, **k):
        raise RuntimeError("gateway is mandatory")

    monkeypatch.setattr(AuthorizationGateway, "authorize", _boom)
    with pytest.raises(RuntimeError, match="gateway is mandatory"):
        client.get("/audit", headers=admin["headers"])


def test_rbac_deny_keeps_legacy_403_contract(client: TestClient, admin: dict) -> None:
    org = _register_org(client)
    member = _invite_member(client, org, role="VIEWER")
    r = client.get(f"{BASE}/abac/policies", headers=member["headers"])
    assert r.status_code == 403
    assert "Missing required permission" in r.text


def test_unauthenticated_request_is_rejected(client: TestClient) -> None:
    assert client.get("/audit").status_code in (401, 403)


# --------------------------------------------------------------------------- #
# §15, §33 — ABAC decisions enforced on protected routes
# --------------------------------------------------------------------------- #
def test_abac_deny_blocks_protected_route(client: TestClient) -> None:
    org = _register_org(client)
    assert client.get("/audit", headers=org["headers"]).status_code == 200
    _publish_policy(client, org, effect="DENY", actions=["audit.view"])
    assert client.get("/audit", headers=org["headers"]).status_code == 403


def test_abac_approval_challenge_surfaces_typed_error(client: TestClient) -> None:
    org = _register_org(client)
    _publish_policy(client, org, effect="REQUIRE_APPROVAL", actions=["audit.view"],
                    obligations={"priority": "CRITICAL", "reviewer_role": "ROLE_AI_REVIEWER"})
    r = client.get("/audit", headers=org["headers"])
    assert r.status_code == 403
    body = r.json()
    assert body["error"]["code"] == "APPROVAL_REQUIRED", body


def test_justification_challenge_satisfied_in_band(client: TestClient) -> None:
    org = _register_org(client)
    _publish_policy(client, org, effect="REQUIRE_JUSTIFICATION", actions=["audit.view"])
    r = client.get("/audit", headers=org["headers"])
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "JUSTIFICATION_REQUIRED"
    # The same request with an X-Justification header satisfies the challenge.
    r = client.get("/audit", headers={**org["headers"],
                                      "X-Justification": "quarterly compliance review"})
    assert r.status_code == 200, r.text


def test_mfa_challenge_surfaces_typed_error(client: TestClient) -> None:
    org = _register_org(client)
    _publish_policy(client, org, effect="REQUIRE_MFA", actions=["audit.view"])
    r = client.get("/audit", headers=org["headers"])
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "MFA_REQUIRED"


def test_constraint_decision_allows_with_obligations(client: TestClient) -> None:
    org = _register_org(client)
    _publish_policy(client, org, effect="LIMIT_ACTION", actions=["audit.view"],
                    obligations={"maximum_export_rows": 100})
    # LIMIT_ACTION allows the call; the obligation rides on request.state for
    # the handler. The route still returns 200.
    assert client.get("/audit", headers=org["headers"]).status_code == 200
    check = client.post(f"{BASE}/check", headers=org["headers"],
                        json={"permission": "audit.view"}).json()
    assert check["decision"] == "LIMIT_ACTION" and check["allowed"] is True
    assert check["obligations"][0]["type"] == "LIMIT_ACTION"


# --------------------------------------------------------------------------- #
# §19, §23 — decision caching on the live check endpoint
# --------------------------------------------------------------------------- #
def test_decision_cache_hit_and_policy_invalidation(client: TestClient) -> None:
    org = _register_org(client)
    body = {"permission": "audit.view"}
    first = client.post(f"{BASE}/check", headers=org["headers"], json=body).json()
    second = client.post(f"{BASE}/check", headers=org["headers"], json=body).json()
    assert first["cache_hit"] is False and second["cache_hit"] is True
    assert second["decision"] == first["decision"] == "ALLOW"
    # Publishing a policy rotates the ABAC generation → the next check re-evaluates.
    _publish_policy(client, org, effect="DENY", actions=["audit.view"])
    third = client.post(f"{BASE}/check", headers=org["headers"], json=body).json()
    assert third["cache_hit"] is False and third["decision"] == "DENY"


# --------------------------------------------------------------------------- #
# §28, §30 — background workers, schedulers and workflow nodes
# --------------------------------------------------------------------------- #
def test_worker_authorization_through_gateway(client: TestClient, admin: dict,
                                              db_session) -> None:
    from app.authorization.middleware.gateway import AuthorizationGateway

    decision = AuthorizationGateway(db_session).authorize_background(
        uuid.UUID(admin["user_id"]), "audit.view",
        source="WORKER", job_name="nightly-audit-report",
    )
    assert decision.allowed and decision.decision == "ALLOW"
    stages = {s["stage"]: s["status"] for s in decision.pipeline_trace}
    assert stages["SESSION_VALIDATION"] == "-"  # workers have no HTTP session
    assert decision.request_id.startswith("worker:")


def test_workflow_node_denied_without_permission(client: TestClient) -> None:
    from app.authorization.middleware.gateway import AuthorizationGateway
    from app.core.database import SessionLocal

    org = _register_org(client)
    member = _invite_member(client, org, role="VIEWER")
    db = SessionLocal()
    try:
        decision = AuthorizationGateway(db).authorize_background(
            uuid.UUID(member["user_id"]), "policy.create", source="WORKFLOW",
            job_name="auto-publish-node",
        )
        assert not decision.allowed and decision.decision == "DENY"
    finally:
        db.rollback()
        db.close()


def test_unknown_background_principal_is_denied(db_session) -> None:
    from app.authorization.middleware.gateway import AuthorizationGateway

    decision = AuthorizationGateway(db_session).authorize_background(
        uuid.uuid4(), "agent.view", source="SCHEDULER",
    )
    assert not decision.allowed
    assert decision.pipeline_trace[0] == {
        "stage": "AUTHENTICATION", "status": "✗", "detail": "unknown principal"}


# --------------------------------------------------------------------------- #
# §29, §31 — AI runtime and API-key integration enforcement
# --------------------------------------------------------------------------- #
def _agent_with_permission(client: TestClient, org: dict, *, resource: str = "CLAIM",
                           action: str = "READ") -> tuple[str, dict]:
    r = client.post("/agents", headers=org["headers"],
                    json={"name": f"A{uuid.uuid4().hex[:6]}", "agent_type": "billing"})
    assert r.status_code == 201, r.text
    agent_id = r.json()["id"]
    key = client.post(f"/agents/{agent_id}/generate-api-key",
                      headers=org["headers"], json={}).json()["api_key"]
    rp = client.post("/permissions", headers=org["headers"], json={
        "agent_id": agent_id, "resource": resource, "action": action, "allowed": True})
    assert rp.status_code == 201, rp.text
    return agent_id, {"Authorization": f"Bearer {key}"}


def test_agent_runtime_allows_when_no_policy_applies(client: TestClient) -> None:
    org = _register_org(client)
    agent_id, agent_auth = _agent_with_permission(client, org)
    r = client.post("/agent-actions", headers=agent_auth, json={
        "agent_id": agent_id, "resource": "CLAIM", "action": "READ", "input_payload": {}})
    assert r.status_code == 201 and r.json()["decision"] == "ALLOW"


def test_agent_runtime_blocked_by_abac_policy(client: TestClient) -> None:
    org = _register_org(client)
    agent_id, agent_auth = _agent_with_permission(client, org)
    _publish_policy(client, org, effect="DENY", actions=["claim.read"],
                    identity_types=["AI_AGENT"])
    r = client.post("/agent-actions", headers=agent_auth, json={
        "agent_id": agent_id, "resource": "CLAIM", "action": "READ", "input_payload": {}})
    assert r.status_code == 201, r.text
    assert r.json()["decision"] == "BLOCK"


def test_agent_runtime_approval_challenge_routes_to_queue(client: TestClient) -> None:
    org = _register_org(client)
    agent_id, agent_auth = _agent_with_permission(client, org)
    _publish_policy(client, org, effect="REQUIRE_APPROVAL", actions=["claim.read"],
                    identity_types=["AI_AGENT"],
                    obligations={"priority": "CRITICAL"})
    r = client.post("/agent-actions", headers=agent_auth, json={
        "agent_id": agent_id, "resource": "CLAIM", "action": "READ", "input_payload": {}})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["decision"] == "PENDING_APPROVAL"
    # The action landed in the human-review queue.
    q = client.get("/approvals", headers=org["headers"])
    assert q.status_code == 200
    assert any(a["agent_action_id"] == body["agent_action_id"] for a in q.json()), q.json()


def test_agent_abac_policies_do_not_leak_across_tenants(client: TestClient) -> None:
    org_a = _register_org(client, org="Mw Tenant A")
    org_b = _register_org(client, org="Mw Tenant B")
    _publish_policy(client, org_a, effect="DENY", actions=["claim.read"],
                    identity_types=["AI_AGENT"])
    agent_id, agent_auth = _agent_with_permission(client, org_b)
    r = client.post("/agent-actions", headers=agent_auth, json={
        "agent_id": agent_id, "resource": "CLAIM", "action": "READ", "input_payload": {}})
    assert r.status_code == 201 and r.json()["decision"] == "ALLOW"


# --------------------------------------------------------------------------- #
# §24 — the six pipeline audit events
# --------------------------------------------------------------------------- #
def test_pipeline_audit_events_are_recorded(client: TestClient, db_session) -> None:
    from app.models.audit_log import AuditLog

    org = _register_org(client)
    rid = f"mw-audit-{uuid.uuid4().hex[:8]}"
    r = client.post(f"{BASE}/check",
                    headers={**org["headers"], "X-Request-ID": rid},
                    json={"permission": "audit.view"})
    assert r.status_code == 200
    events = {row.event_type for row in db_session.execute(
        select(AuditLog).where(AuditLog.request_id == rid)).scalars()}
    assert {"AUTHORIZATION_STARTED", "DECISION_GENERATED",
            "AUTHORIZATION_COMPLETED"} <= events, events


def test_denied_pipeline_records_failure_event(client: TestClient, db_session) -> None:
    from app.models.audit_log import AuditLog

    org = _register_org(client)
    member = _invite_member(client, org, role="VIEWER")
    rid = f"mw-fail-{uuid.uuid4().hex[:8]}"
    r = client.post(f"{BASE}/check",
                    headers={**member["headers"], "X-Request-ID": rid},
                    json={"permission": "policy.create"})
    assert r.status_code == 200 and r.json()["allowed"] is False
    events = {row.event_type for row in db_session.execute(
        select(AuditLog).where(AuditLog.request_id == rid)).scalars()}
    assert "AUTHORIZATION_FAILED" in events and "DECISION_GENERATED" in events


def test_execution_completed_event_after_agent_action(client: TestClient,
                                                      db_session) -> None:
    from app.models.audit_log import AuditLog

    org = _register_org(client)
    agent_id, agent_auth = _agent_with_permission(client, org)
    rid = f"mw-exec-{uuid.uuid4().hex[:8]}"
    r = client.post("/agent-actions", headers={**agent_auth, "X-Request-ID": rid},
                    json={"agent_id": agent_id, "resource": "CLAIM", "action": "READ",
                          "input_payload": {}})
    assert r.status_code == 201
    events = {row.event_type for row in db_session.execute(
        select(AuditLog).where(AuditLog.request_id == rid)).scalars()}
    assert "EXECUTION_COMPLETED" in events, events


# --------------------------------------------------------------------------- #
# §26, §36 — decisions and errors never leak policy internals
# --------------------------------------------------------------------------- #
def test_challenge_error_does_not_leak_policy_details(client: TestClient) -> None:
    org = _register_org(client)
    _publish_policy(client, org, effect="REQUIRE_APPROVAL", actions=["audit.view"],
                    obligations={"priority": "CRITICAL"})
    body = client.get("/audit", headers=org["headers"]).json()
    text = str(body)
    assert "conditions" not in text and "environment.timestamp" not in text
    assert set(body) <= {"success", "error", "request_id", "meta"}


def test_check_context_cannot_spoof_identity(client: TestClient) -> None:
    org = _register_org(client)
    member = _invite_member(client, org, role="VIEWER")
    r = client.post(f"{BASE}/check", headers=member["headers"],
                    json={"permission": "policy.create",
                          "context": {"identity.roles": ["ROLE_PLATFORM_OWNER"]}})
    assert r.status_code == 200 and r.json()["allowed"] is False


# --------------------------------------------------------------------------- #
# §34 — metrics endpoint
# --------------------------------------------------------------------------- #
def test_middleware_metrics_endpoint(client: TestClient, admin: dict) -> None:
    client.post(f"{BASE}/check", headers=admin["headers"],
                json={"permission": "audit.view"})
    r = client.get(f"{BASE}/middleware/metrics", headers=admin["headers"])
    assert r.status_code == 200
    snap = r.json()
    assert snap["authorization_requests_total"] >= 1
    for key in ("authorization_denied_total", "authorization_latency_ms_avg",
                "decision_cache_hit_ratio", "authorization_pipeline_errors_total"):
        assert key in snap, key
