"""Phase 4.3.7 integration + security tests (§25) — the administration portal
API: dashboard, delegated role/policy management, permissions/organizations/
resources listings, the simulator, the decision explorer, the full access
review lifecycle (with real revocation enforcement), analytics, audit events,
role-gated access and tenant isolation."""

from __future__ import annotations

import time
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

PASSWORD = "T3st!Passw0rd#Ok"
ADMIN = "/api/v1/admin"


def _register_org(client: TestClient, org: str = "Portal Org") -> dict:
    email = f"adm_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": org, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"],
            "organization_id": me["user"]["organization_id"], "email": email}


def _invite_member(client: TestClient, admin: dict, *, role: str = "VIEWER") -> dict:
    email = f"admm_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "Member", "password": PASSWORD, "role": role,
        "organization_id": admin["organization_id"],
    })
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "email": email}


def _audit_events(db_session, organization_id: str) -> set[str]:
    from app.models.rbac import AuthorizationAudit

    return {row.event_type for row in db_session.execute(
        select(AuthorizationAudit).where(
            AuthorizationAudit.organization_id == uuid.UUID(organization_id))
    ).scalars()}


# --------------------------------------------------------------------------- #
# Dashboard (§6, §24)
# --------------------------------------------------------------------------- #
def test_dashboard_widgets_and_charts(client: TestClient) -> None:
    org = _register_org(client)
    client.post("/api/v1/authorization/check", headers=org["headers"],
                json={"permission": "audit.view"})
    started = time.perf_counter()
    r = client.get(f"{ADMIN}/dashboard", headers=org["headers"])
    elapsed = time.perf_counter() - started
    assert r.status_code == 200, r.text
    body = r.json()
    w = body["widgets"]
    assert w["total_users"] >= 1 and w["active_roles"] >= 1
    assert w["active_permissions"] > 0
    for key in ("active_policies", "active_sessions", "authorization_requests_24h",
                "denied_requests_24h", "approval_requests_pending",
                "mfa_challenges_total", "high_risk_decisions_24h",
                "cache_hit_ratio", "policy_evaluation_latency_ms"):
        assert key in w, key
    for chart in ("authorization_trend", "top_permissions", "policy_matches",
                  "decision_breakdown", "approval_queue"):
        assert chart in body["charts"], chart
    assert elapsed < 2.0, f"dashboard took {elapsed:.2f}s (budget 2s, §24)"


# --------------------------------------------------------------------------- #
# Delegated role management (§7, §18)
# --------------------------------------------------------------------------- #
def test_role_lifecycle_through_admin_api(client: TestClient, db_session) -> None:
    org = _register_org(client)
    r = client.post(f"{ADMIN}/roles", headers=org["headers"], json={
        "name": f"ROLE_PORTAL_{uuid.uuid4().hex[:6].upper()}",
        "display_name": "Portal Test Role", "permissions": ["agent.view"],
    })
    assert r.status_code == 201, r.text
    role = r.json()

    r = client.put(f"{ADMIN}/roles/{role['id']}", headers=org["headers"],
                   json={"display_name": "Renamed Portal Role"})
    assert r.status_code == 200 and r.json()["display_name"] == "Renamed Portal Role"

    r = client.get(f"{ADMIN}/roles", headers=org["headers"],
                   params={"search": "Renamed Portal"})
    assert any(x["id"] == role["id"] for x in r.json())

    assert client.delete(f"{ADMIN}/roles/{role['id']}",
                         headers=org["headers"]).status_code == 204
    events = _audit_events(db_session, org["organization_id"])
    assert {"ROLE_CREATED", "ROLE_UPDATED", "ROLE_DELETED"} <= events


def test_catalog_listings(client: TestClient) -> None:
    org = _register_org(client)
    perms = client.get(f"{ADMIN}/permissions", headers=org["headers"]).json()
    assert any(p["code"] == "admin.reviews.manage" for p in perms)
    tree = client.get(f"{ADMIN}/organizations", headers=org["headers"]).json()
    assert tree["name"] and "children" in tree
    resources = client.get(f"{ADMIN}/resources", headers=org["headers"])
    assert resources.status_code == 200


# --------------------------------------------------------------------------- #
# Policy management + simulator (§10, §12, §18)
# --------------------------------------------------------------------------- #
def test_policy_management_and_simulator(client: TestClient, db_session) -> None:
    org = _register_org(client)
    r = client.post(f"{ADMIN}/policies", headers=org["headers"], json={
        "name": "portal policy", "effect": "DENY",
        "target": {"actions": ["dataset.export"]},
        "conditions": {"all": [{"attribute": "identity.type", "operator": "EQUALS",
                                "value": "HUMAN_USER"}]},
    })
    assert r.status_code == 201, r.text
    policy = r.json()
    r = client.put(f"{ADMIN}/policies/{policy['id']}", headers=org["headers"],
                   json={"name": "portal policy v2", "effect": "DENY"})
    assert r.status_code == 200 and r.json()["name"] == "portal policy v2"

    listed = client.get(f"{ADMIN}/policies", headers=org["headers"]).json()
    assert any(p["id"] == policy["id"] for p in listed)

    sim = client.post(f"{ADMIN}/policy-simulator", headers=org["headers"], json={
        "action": "audit.export",
        "policy": {"name": "draft", "effect": "DENY",
                   "conditions": {"all": [{"attribute": "identity.type",
                                           "operator": "EQUALS", "value": "HUMAN_USER"}]}},
    })
    assert sim.status_code == 200, sim.text
    body = sim.json()
    assert body["baseline_rbac"]["allowed"] is True
    assert body["abac"]["decision"] == "DENY"
    assert "SIMULATION_EXECUTED" in _audit_events(db_session, org["organization_id"])

    assert client.delete(f"{ADMIN}/policies/{policy['id']}",
                         headers=org["headers"]).status_code == 204


# --------------------------------------------------------------------------- #
# Decision explorer (§13, §24)
# --------------------------------------------------------------------------- #
def test_decision_explorer_filters_and_audit(client: TestClient, db_session) -> None:
    org = _register_org(client)
    member = _invite_member(client, org)
    # Generate one denied decision for the member.
    r = client.post("/api/v1/authorization/check", headers=member["headers"],
                    json={"permission": "policy.create"})
    assert r.json()["allowed"] is False

    started = time.perf_counter()
    rows = client.get(f"{ADMIN}/authorization-decisions", headers=org["headers"],
                      params={"allowed": False, "permission": "policy.create"}).json()
    elapsed = time.perf_counter() - started
    assert any(d["identity_id"] == member["user_id"] for d in rows), rows
    assert all(d["allowed"] is False for d in rows)
    assert elapsed < 1.0, f"decision lookup took {elapsed:.2f}s"
    assert "DECISION_VIEWED" in _audit_events(db_session, org["organization_id"])


def test_decision_explorer_is_tenant_isolated(client: TestClient) -> None:
    org_a = _register_org(client, org="Portal Tenant A")
    org_b = _register_org(client, org="Portal Tenant B")
    member = _invite_member(client, org_a)
    client.post("/api/v1/authorization/check", headers=member["headers"],
                json={"permission": "policy.create"})
    rows = client.get(f"{ADMIN}/authorization-decisions", headers=org_b["headers"]).json()
    assert all(d["identity_id"] != member["user_id"] for d in rows)


# --------------------------------------------------------------------------- #
# Access review campaigns (§14) — full lifecycle with real enforcement
# --------------------------------------------------------------------------- #
def test_access_review_full_lifecycle(client: TestClient, db_session) -> None:
    org = _register_org(client)
    member = _invite_member(client, org)

    # Give the member a real RBAC role to review.
    role = client.post(f"{ADMIN}/roles", headers=org["headers"], json={
        "name": f"ROLE_REVIEWED_{uuid.uuid4().hex[:6].upper()}",
        "permissions": ["agent.view"],
    }).json()
    assign = client.post("/api/v1/role-assignments", headers=org["headers"], json={
        "user_id": member["user_id"], "role_id": role["id"], "scope": "ORGANIZATION",
    })
    assert assign.status_code == 201, assign.text
    assignment_id = assign.json()["id"]

    # DRAFT → (edit) → ACTIVE with snapshot of in-scope assignments.
    campaign = client.post(f"{ADMIN}/access-reviews", headers=org["headers"], json={
        "name": "Q3 access certification", "scope": {"role_ids": [role["id"]]},
    }).json()
    assert campaign["status"] == "DRAFT" and campaign["total_items"] == 0

    r = client.put(f"{ADMIN}/access-reviews/{campaign['id']}", headers=org["headers"],
                   json={"description": "Quarterly certification"})
    assert r.status_code == 200

    active = client.post(f"{ADMIN}/access-reviews/{campaign['id']}/activate",
                         headers=org["headers"]).json()
    assert active["status"] == "ACTIVE" and active["total_items"] == 1

    # Completing with pending items must fail.
    r = client.post(f"{ADMIN}/access-reviews/{campaign['id']}/complete",
                    headers=org["headers"])
    assert r.status_code == 409, r.text

    items = client.get(f"{ADMIN}/access-reviews/{campaign['id']}/items",
                       headers=org["headers"]).json()
    assert len(items) == 1 and items[0]["subject_label"] == member["email"]

    # REVOKE is real enforcement: the assignment disappears.
    decided = client.post(
        f"{ADMIN}/access-reviews/{campaign['id']}/items/{items[0]['id']}/decide",
        headers=org["headers"],
        json={"decision": "REVOKED", "comment": "No longer needed"},
    ).json()
    assert decided["decision"] == "REVOKED"
    remaining = client.get("/api/v1/role-assignments", headers=org["headers"],
                           params={"user_id": member["user_id"]}).json()
    assert all(a["id"] != assignment_id for a in remaining), remaining

    completed = client.post(f"{ADMIN}/access-reviews/{campaign['id']}/complete",
                            headers=org["headers"]).json()
    assert completed["status"] == "COMPLETED" and completed["revoked_items"] == 1

    report = client.get(f"{ADMIN}/access-reviews/{campaign['id']}/export",
                        headers=org["headers"]).json()
    assert report["campaign"]["name"] == "Q3 access certification"
    assert report["items"][0]["decision"] == "REVOKED"

    archived = client.post(f"{ADMIN}/access-reviews/{campaign['id']}/archive",
                           headers=org["headers"]).json()
    assert archived["status"] == "ARCHIVED"

    events = _audit_events(db_session, org["organization_id"])
    assert {"ACCESS_REVIEW_CREATED", "ACCESS_REVIEW_ACTIVATED",
            "ACCESS_REVIEW_ITEM_DECIDED", "ACCESS_REVIEW_COMPLETED",
            "ACCESS_REVIEW_ARCHIVED", "AUDIT_EXPORTED"} <= events, events


def test_access_review_invalid_transitions_rejected(client: TestClient) -> None:
    org = _register_org(client)
    campaign = client.post(f"{ADMIN}/access-reviews", headers=org["headers"],
                           json={"name": "lifecycle guard"}).json()
    # DRAFT cannot complete or archive.
    assert client.post(f"{ADMIN}/access-reviews/{campaign['id']}/archive",
                       headers=org["headers"]).status_code == 409
    # DRAFT → SCHEDULED → ACTIVE is legal; re-activating is not.
    assert client.post(f"{ADMIN}/access-reviews/{campaign['id']}/schedule",
                       headers=org["headers"]).status_code == 200
    assert client.post(f"{ADMIN}/access-reviews/{campaign['id']}/activate",
                       headers=org["headers"]).status_code == 200
    assert client.post(f"{ADMIN}/access-reviews/{campaign['id']}/activate",
                       headers=org["headers"]).status_code == 409


def test_access_reviews_are_tenant_isolated(client: TestClient) -> None:
    org_a = _register_org(client, org="Portal Rev A")
    org_b = _register_org(client, org="Portal Rev B")
    campaign = client.post(f"{ADMIN}/access-reviews", headers=org_a["headers"],
                           json={"name": "tenant isolation"}).json()
    r = client.get(f"{ADMIN}/access-reviews/{campaign['id']}", headers=org_b["headers"])
    assert r.status_code in (400, 404, 422)
    listed = client.get(f"{ADMIN}/access-reviews", headers=org_b["headers"]).json()
    assert all(c["id"] != campaign["id"] for c in listed)


# --------------------------------------------------------------------------- #
# Analytics (§17)
# --------------------------------------------------------------------------- #
def test_security_analytics_snapshot(client: TestClient) -> None:
    org = _register_org(client)
    member = _invite_member(client, org)
    client.post("/api/v1/authorization/check", headers=member["headers"],
                json={"permission": "policy.create"})
    r = client.get(f"{ADMIN}/analytics", headers=org["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["denied_requests_24h"] >= 1
    for key in ("denied_requests_7d", "high_risk_decisions_24h", "mfa_challenges_total",
                "approval_requests_total", "approval_approval_rate",
                "authorization_latency_ms_avg", "authorization_latency_ms_p95",
                "cache_hit_ratio", "abac_denies_total", "abac_challenges_total",
                "policy_errors_total", "top_denied_permissions", "denied_trend",
                "sharing_trend"):
        assert key in body, key
    assert any(p["permission"] == "policy.create" for p in body["top_denied_permissions"])


# --------------------------------------------------------------------------- #
# §21, §23 — role-gated portal access
# --------------------------------------------------------------------------- #
def test_admin_endpoints_require_admin_permissions(client: TestClient) -> None:
    org = _register_org(client)
    member = _invite_member(client, org, role="VIEWER")
    for path in ("/dashboard", "/roles", "/permissions", "/organizations",
                 "/resources", "/policies", "/authorization-decisions",
                 "/access-reviews", "/analytics"):
        r = client.get(f"{ADMIN}{path}", headers=member["headers"])
        assert r.status_code == 403, f"{path} → {r.status_code}"
    r = client.post(f"{ADMIN}/policy-simulator", headers=member["headers"],
                    json={"action": "dataset.export"})
    assert r.status_code == 403


def test_admin_endpoints_require_authentication(client: TestClient) -> None:
    assert client.get(f"{ADMIN}/dashboard").status_code in (401, 403)
