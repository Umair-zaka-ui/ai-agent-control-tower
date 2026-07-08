"""Tests for the Phase 3 Part 3.4 Approval Queue & Human Review Workbench:
list/filter, statistics, detail payload, timeline, escalate and assign flows.
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


def _make_pending_approval(client: TestClient, admin: dict[str, str]) -> str:
    """Create an agent + policy + a large-claim action that requires approval."""
    agent_id = client.post(
        "/agents", headers=admin, json={"name": "BillingAgent", "agent_type": "billing"}
    ).json()["id"]
    for action in ("READ", "SUBMIT_CLAIM"):
        client.post(
            "/permissions",
            headers=admin,
            json={"agent_id": agent_id, "resource": "CLAIM", "action": action, "allowed": True},
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
    r = client.post(
        "/agent-actions",
        headers=admin,
        json={
            "agent_id": agent_id,
            "resource": "CLAIM",
            "action": "SUBMIT_CLAIM",
            "input_payload": {"amount": 6000},
        },
    )
    assert r.status_code == 201, r.text
    approval_id = r.json()["approval_id"]
    assert approval_id is not None
    return approval_id


def test_list_and_filter_queue(client: TestClient) -> None:
    admin = _auth(_register(client))
    approval_id = _make_pending_approval(client, admin)

    rows = client.get("/approvals", headers=admin).json()
    assert any(row["id"] == approval_id for row in rows)
    row = next(row for row in rows if row["id"] == approval_id)
    assert row["agent_name"] == "BillingAgent"
    assert row["resource"] == "CLAIM"
    assert row["action"] == "SUBMIT_CLAIM"
    assert row["decision"] == "PENDING"

    # Status filter.
    pending = client.get("/approvals", headers=admin, params={"status": "PENDING"}).json()
    assert any(r["id"] == approval_id for r in pending)
    approved = client.get("/approvals", headers=admin, params={"status": "APPROVED"}).json()
    assert all(r["id"] != approval_id for r in approved)

    # Search by agent name.
    found = client.get("/approvals", headers=admin, params={"search": "Billing"}).json()
    assert any(r["id"] == approval_id for r in found)
    missing = client.get("/approvals", headers=admin, params={"search": "zzz-none"}).json()
    assert all(r["id"] != approval_id for r in missing)


def test_statistics(client: TestClient) -> None:
    admin = _auth(_register(client))
    _make_pending_approval(client, admin)
    stats = client.get("/approvals/statistics", headers=admin).json()
    assert stats["pending"] >= 1
    assert "approved_today" in stats and "rejected_today" in stats
    assert "escalated" in stats and "avg_review_seconds" in stats


def test_detail_payload(client: TestClient) -> None:
    admin = _auth(_register(client))
    approval_id = _make_pending_approval(client, admin)

    detail = client.get(f"/approvals/{approval_id}", headers=admin).json()
    assert detail["agent"]["name"] == "BillingAgent"
    assert detail["action"]["resource"] == "CLAIM"
    assert detail["action"]["input_payload"]["amount"] == 6000
    assert detail["policy"]["matched"] is True
    assert detail["policy"]["policy_name"] == "Large Claim Approval"
    assert detail["risk"]["score"] >= 0
    assert detail["risk"]["recommendation"]
    assert isinstance(detail["risk"]["factors"], dict)


def test_escalate_then_decide(client: TestClient) -> None:
    admin = _auth(_register(client))
    approval_id = _make_pending_approval(client, admin)

    r = client.post(
        f"/approvals/{approval_id}/escalate",
        headers=admin,
        json={"target": "COMPLIANCE_OFFICER", "reason": "Needs compliance sign-off."},
    )
    assert r.status_code == 200, r.text
    assert r.json()["decision"] == "ESCALATED"
    assert r.json()["escalation_target"] == "COMPLIANCE_OFFICER"

    # Escalated approvals appear on the escalations board.
    esc = client.get("/approvals/escalations", headers=admin).json()
    assert any(row["id"] == approval_id for row in esc)

    # An escalated approval can still be approved.
    r = client.post(
        f"/approvals/{approval_id}/approve", headers=admin, json={"review_comment": "ok"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["decision"] == "APPROVED"


def test_assign_reviewer_and_timeline(client: TestClient) -> None:
    admin = _auth(_register(client))
    approval_id = _make_pending_approval(client, admin)

    # The registering owner is the only org user; assign to self.
    me = client.get("/rbac/me", headers=admin).json()
    user_id = me["id"] if "id" in me else me.get("user_id")
    if user_id is None:
        # Fall back to the users listing.
        user_id = client.get("/users", headers=admin).json()[0]["id"]

    r = client.post(
        f"/approvals/{approval_id}/assign", headers=admin, json={"user_id": user_id}
    )
    assert r.status_code == 200, r.text
    assert r.json()["assigned_to_user_id"] == user_id

    timeline = client.get(f"/approvals/{approval_id}/timeline", headers=admin).json()
    event_types = {ev["event_type"] for ev in timeline}
    assert "APPROVAL_REQUESTED" in event_types
    assert "APPROVAL_ASSIGNED" in event_types


def test_history_lists_resolved(client: TestClient) -> None:
    admin = _auth(_register(client))
    approval_id = _make_pending_approval(client, admin)
    client.post(f"/approvals/{approval_id}/reject", headers=admin, json={"review_comment": "no - insufficient documentation"})

    history = client.get("/approvals/history", headers=admin).json()
    assert any(row["id"] == approval_id and row["decision"] == "REJECTED" for row in history)
