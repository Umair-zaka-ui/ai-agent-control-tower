"""Tests for the Phase 3 Part 3.3 policy-management endpoints (metadata, list
filters, enable/disable, test, audit, templates)."""

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
            "password": "password123",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_policy(client: TestClient, admin: dict[str, str], **overrides) -> dict:
    body = {
        "name": "Large Claim Approval",
        "resource": "CLAIM",
        "action": "SUBMIT_CLAIM",
        "conditions": {"amount_gt": 10000},
        "decision": "PENDING_APPROVAL",
        "priority": 100,
        "severity": "HIGH",
        "status": "ENABLED",
        **overrides,
    }
    r = client.post("/policies", headers=admin, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_includes_metadata(client: TestClient) -> None:
    admin = _auth(_register(client))
    policy = _make_policy(client, admin)
    assert policy["severity"] == "HIGH"
    assert policy["status"] == "ENABLED"
    assert policy["enabled"] is True
    assert policy["trigger_count"] == 0
    assert policy["created_by"] is not None


def test_list_search_and_filters(client: TestClient) -> None:
    admin = _auth(_register(client))
    _make_policy(client, admin, name="Alpha Policy", severity="LOW")
    _make_policy(client, admin, name="Beta Policy", severity="CRITICAL")

    assert len(client.get("/policies?search=Alpha", headers=admin).json()) == 1
    crit = client.get("/policies?severity=CRITICAL", headers=admin).json()
    assert len(crit) == 1 and crit[0]["name"] == "Beta Policy"


def test_enable_disable(client: TestClient) -> None:
    admin = _auth(_register(client))
    policy = _make_policy(client, admin)

    r = client.patch(f"/policies/{policy['id']}/disable", headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "DISABLED"
    assert r.json()["enabled"] is False

    r = client.patch(f"/policies/{policy['id']}/enable", headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "ENABLED"
    assert r.json()["enabled"] is True


def test_policy_test_simulation(client: TestClient) -> None:
    admin = _auth(_register(client))
    policy = _make_policy(client, admin)

    # Matching input (amount > 10000).
    r = client.post(
        f"/policies/{policy['id']}/test",
        headers=admin,
        json={"resource": "CLAIM", "action": "SUBMIT_CLAIM", "input_payload": {"amount": 15000}},
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["matched"] is True
    assert result["decision"] == "PENDING_APPROVAL"
    assert any("amount" in c for c in result["triggered_conditions"])

    # Non-matching input (amount below threshold).
    r = client.post(
        f"/policies/{policy['id']}/test",
        headers=admin,
        json={"resource": "CLAIM", "action": "SUBMIT_CLAIM", "input_payload": {"amount": 100}},
    )
    assert r.json()["matched"] is False


def test_audit_and_templates(client: TestClient) -> None:
    admin = _auth(_register(client))
    policy = _make_policy(client, admin)

    audit = client.get(f"/policies/{policy['id']}/audit", headers=admin).json()
    assert any(e["event_type"] == "POLICY_CREATED" for e in audit)

    templates = client.get("/policies/templates", headers=admin).json()
    assert len(templates) == 7
    assert all({"name", "resource", "action", "decision", "severity"} <= set(t) for t in templates)
