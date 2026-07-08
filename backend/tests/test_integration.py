"""End-to-end integration tests for Phase 2 against the configured database.

Each test registers a brand-new organization (unique email) so runs are
isolated and do not depend on seed data.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _register(client: TestClient) -> str:
    email = f"owner_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post(
        "/auth/register",
        json={
            "organization_name": "Test Org",
            "name": "Owner",
            "email": email,
            "password": "T3st!Passw0rd#Ok",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_full_phase2_flow(client: TestClient) -> None:
    token = _register(client)
    admin = _auth(token)

    # rbac/me reflects the seeded SUPER_ADMIN role + permissions.
    me = client.get("/rbac/me", headers=admin).json()
    assert me["role"] == "SUPER_ADMIN"
    assert "policy.create" in me["permissions"]
    assert "approval.review" in me["permissions"]

    # Create an agent.
    r = client.post("/agents", headers=admin, json={"name": "BillingAgent", "agent_type": "billing"})
    assert r.status_code == 201, r.text
    agent_id = r.json()["id"]

    # Issue a Phase 2 agent API key.
    r = client.post(f"/agents/{agent_id}/generate-api-key", headers=admin, json={})
    assert r.status_code == 201, r.text
    api_key = r.json()["api_key"]
    assert api_key.startswith("agt_live_")
    agent_auth = _auth(api_key)

    # Permissions for the agent.
    for action in ("READ", "SUBMIT_CLAIM"):
        rp = client.post(
            "/permissions",
            headers=admin,
            json={"agent_id": agent_id, "resource": "CLAIM", "action": action, "allowed": True},
        )
        assert rp.status_code == 201, rp.text

    # A policy: large claims require approval.
    rpol = client.post(
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
    assert rpol.status_code == 201, rpol.text

    # --- Agent authenticates with its API KEY and submits actions ---
    # Low-risk READ -> ALLOW.
    r = client.post(
        "/agent-actions",
        headers=agent_auth,
        json={"agent_id": agent_id, "resource": "CLAIM", "action": "READ", "input_payload": {}},
    )
    assert r.status_code == 201, r.text
    assert r.json()["decision"] == "ALLOW"

    # Large claim -> policy forces PENDING_APPROVAL.
    r = client.post(
        "/agent-actions",
        headers=agent_auth,
        json={
            "agent_id": agent_id,
            "resource": "CLAIM",
            "action": "SUBMIT_CLAIM",
            "input_payload": {"amount": 6000},
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["decision"] == "PENDING_APPROVAL"
    assert body["matched_policy"] == "Large Claim Approval"
    approval_id = body["approval_id"]
    assert approval_id is not None

    # Dashboard reflects the activity.
    summary = client.get("/dashboard/summary", headers=admin).json()
    assert summary["agents"] >= 1
    assert summary["policies"] >= 1
    assert summary["pending_approvals"] >= 1

    # Approve the pending action (SUPER_ADMIN holds approval.review).
    r = client.post(
        f"/approvals/{approval_id}/approve",
        headers=admin,
        json={"review_comment": "ok"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["decision"] == "APPROVED"

    # Comment thread captured the review comment.
    comments = client.get(f"/approvals/{approval_id}/comments", headers=admin).json()
    assert any(c["comment"] == "ok" for c in comments)

    # Revoke the key -> agent can no longer act.
    keys = client.get(f"/agents/{agent_id}/api-keys", headers=admin).json()
    key_id = keys[0]["id"]
    r = client.post(f"/api-keys/{key_id}/revoke", headers=admin)
    assert r.status_code == 200, r.text

    r = client.post(
        "/agent-actions",
        headers=agent_auth,
        json={"agent_id": agent_id, "resource": "CLAIM", "action": "READ", "input_payload": {}},
    )
    assert r.status_code == 401, r.text


def test_inactive_agent_via_jwt_is_blocked(client: TestClient) -> None:
    token = _register(client)
    admin = _auth(token)

    agent_id = client.post(
        "/agents", headers=admin, json={"name": "A", "agent_type": "t"}
    ).json()["id"]
    client.post(
        "/permissions",
        headers=admin,
        json={"agent_id": agent_id, "resource": "CLAIM", "action": "READ", "allowed": True},
    )
    # Suspend the agent.
    client.patch(f"/agents/{agent_id}/status", headers=admin, json={"status": "SUSPENDED"})

    r = client.post(
        "/agent-actions",
        headers=admin,
        json={"agent_id": agent_id, "resource": "CLAIM", "action": "READ", "input_payload": {}},
    )
    assert r.status_code == 201, r.text
    assert r.json()["decision"] == "BLOCK"
