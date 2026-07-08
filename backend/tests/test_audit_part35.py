"""Tests for the Phase 3 Part 3.5 Audit & Compliance Center: enriched list,
statistics, timeline, event catalog, detail (with related events), security &
compliance dashboards, export, and the audit.export RBAC split.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _register(client: TestClient) -> tuple[str, str]:
    email = f"owner_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post(
        "/auth/register",
        json={
            "organization_name": "Audit Org",
            "name": "Owner",
            "email": email,
            "password": "T3st!Passw0rd#Ok",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"], email


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_activity(client: TestClient, admin: dict[str, str]) -> None:
    """Generate a spread of audit events: agent action (approval), a blocked
    action, an API key revoke, and a failed login."""
    agent_id = client.post(
        "/agents", headers=admin, json={"name": "AuditBot", "agent_type": "billing"}
    ).json()["id"]
    for act in ("READ", "SUBMIT_CLAIM"):
        client.post(
            "/permissions",
            headers=admin,
            json={"agent_id": agent_id, "resource": "CLAIM", "action": act, "allowed": True},
        )
    client.post(
        "/policies",
        headers=admin,
        json={
            "name": "Large Claim Approval",
            "resource": "CLAIM",
            "action": "SUBMIT_CLAIM",
            "conditions": {"amount_gt": 5000},
            "decision": "PENDING_APPROVAL",
            "priority": 100,
        },
    )
    # Pending-approval action.
    client.post(
        "/agent-actions",
        headers=admin,
        json={"agent_id": agent_id, "resource": "CLAIM", "action": "SUBMIT_CLAIM", "input_payload": {"amount": 9000}},
    )
    # Blocked action (no permission for DELETE).
    client.post(
        "/agent-actions",
        headers=admin,
        json={"agent_id": agent_id, "resource": "CLAIM", "action": "DELETE", "input_payload": {}},
    )


def test_list_statistics_timeline_catalog(client: TestClient) -> None:
    token, email = _register(client)
    admin = _auth(token)
    _seed_activity(client, admin)
    # A failed login for the security surface.
    client.post("/auth/login", json={"email": email, "password": "wrong-pass"})

    rows = client.get("/audit", headers=admin).json()
    assert len(rows) > 0
    sample = rows[0]
    for key in ("event_type", "category", "severity", "status", "actor_type"):
        assert key in sample

    stats = client.get("/audit/statistics", headers=admin).json()
    assert stats["total_events"] >= len(rows) or stats["total_events"] > 0
    assert stats["policy_evaluations"] >= 1
    assert stats["approval_events"] >= 1

    timeline = client.get("/audit/timeline", headers=admin).json()
    assert timeline and "label" in timeline[0]

    catalog = client.get("/audit/events", headers=admin).json()
    values = {c["value"] for c in catalog}
    assert "AGENT_ACTION_DECISION" in values and "AUTH_LOGIN" in values


def test_filters_and_search(client: TestClient) -> None:
    token, _ = _register(client)
    admin = _auth(token)
    _seed_activity(client, admin)

    # Filter by event_type.
    decisions = client.get("/audit", headers=admin, params={"event_type": "AGENT_ACTION_DECISION"}).json()
    assert decisions and all(r["event_type"] == "AGENT_ACTION_DECISION" for r in decisions)

    # Severity filter (derived) — HIGH should include the blocked action.
    high = client.get("/audit", headers=admin, params={"severity": "HIGH"}).json()
    assert any(r["decision"] == "BLOCK" for r in high)

    # Search by resource.
    found = client.get("/audit", headers=admin, params={"search": "CLAIM"}).json()
    assert found


def test_detail_with_related_events(client: TestClient) -> None:
    token, _ = _register(client)
    admin = _auth(token)
    _seed_activity(client, admin)
    rows = client.get("/audit", headers=admin, params={"event_type": "AGENT_ACTION_DECISION"}).json()
    event_id = rows[0]["id"]

    detail = client.get(f"/audit/{event_id}", headers=admin).json()
    assert detail["id"] == event_id
    assert "related_events" in detail
    # Admin holds audit.export, so raw payloads are present.
    assert detail["response_payload"] is not None


def test_security_and_compliance(client: TestClient) -> None:
    token, email = _register(client)
    admin = _auth(token)
    _seed_activity(client, admin)
    client.post("/auth/login", json={"email": email, "password": "nope"})

    sec = client.get("/audit/security", headers=admin).json()
    assert sec["failed_logins"] >= 1
    assert sec["suspicious_activity"] >= 1  # the blocked action
    assert "recent" in sec

    comp = client.get("/audit/compliance", headers=admin).json()
    assert comp["audit_completeness"]["score"] == 100
    assert comp["policy_coverage"]["label"] == "Policy Coverage"


def test_export_returns_full_set(client: TestClient) -> None:
    token, _ = _register(client)
    admin = _auth(token)
    _seed_activity(client, admin)
    export = client.get("/audit/export", headers=admin).json()
    assert len(export) >= 1


def test_rbac_export_split(client: TestClient) -> None:
    token, _ = _register(client)
    admin = _auth(token)
    _seed_activity(client, admin)

    # Create a VIEWER (no audit.export) and log in.
    viewer_email = f"viewer_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post(
        "/users",
        headers=admin,
        json={"name": "Vic Viewer", "email": viewer_email, "password": "T3st!Passw0rd#Ok", "role": "VIEWER"},
    )
    assert r.status_code == 201, r.text
    vtoken = client.post("/auth/login", json={"email": viewer_email, "password": "T3st!Passw0rd#Ok"}).json()["access_token"]
    viewer = _auth(vtoken)

    # Viewer can see the table + statistics...
    assert client.get("/audit", headers=viewer).status_code == 200
    assert client.get("/audit/statistics", headers=viewer).status_code == 200
    # ...but NOT the sensitive surfaces.
    assert client.get("/audit/security", headers=viewer).status_code == 403
    assert client.get("/audit/compliance", headers=viewer).status_code == 403
    assert client.get("/audit/export", headers=viewer).status_code == 403

    # And raw payloads are redacted in the detail view for the viewer.
    rows = client.get("/audit", headers=viewer, params={"event_type": "AGENT_ACTION_DECISION"}).json()
    detail = client.get(f"/audit/{rows[0]['id']}", headers=viewer).json()
    assert detail["response_payload"] is None
    assert detail["request_payload"] is None
