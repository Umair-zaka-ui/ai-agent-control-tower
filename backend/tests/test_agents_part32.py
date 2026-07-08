"""Tests for the Phase 3 Part 3.2 agent-management endpoints (extended create,
paginated list, update, delete, stats)."""

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


def test_create_agent_with_full_metadata(client: TestClient) -> None:
    admin = _auth(_register(client))
    r = client.post(
        "/agents",
        headers=admin,
        json={
            "name": "BillingBot",
            "agent_type": "billing",
            "owner": "ops@example.com",
            "department": "Finance",
            "capabilities": ["read", "write"],
            "default_risk_score": 20,
            "max_allowed_risk": 80,
            "human_approval_required": True,
            "risk_level": "MEDIUM",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["owner"] == "ops@example.com"
    assert body["capabilities"] == ["read", "write"]
    assert body["risk_level"] == "MEDIUM"
    assert body["health"] == "HEALTHY"
    assert isinstance(body["api_key"], str) and len(body["api_key"]) > 16


def test_list_is_paginated_and_searchable(client: TestClient) -> None:
    admin = _auth(_register(client))
    for name in ("Alpha", "Beta", "Gamma"):
        client.post("/agents", headers=admin, json={"name": name, "agent_type": "t"})

    r = client.get("/agents?page=1&page_size=2", headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["page"] == 1

    r = client.get("/agents?search=Beta", headers=admin)
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Beta"


def test_update_and_status_and_delete(client: TestClient) -> None:
    admin = _auth(_register(client))
    agent_id = client.post(
        "/agents", headers=admin, json={"name": "A", "agent_type": "t"}
    ).json()["id"]

    # PUT update.
    r = client.put(
        f"/agents/{agent_id}",
        headers=admin,
        json={"department": "R&D", "risk_level": "HIGH"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["department"] == "R&D"
    assert r.json()["risk_level"] == "HIGH"

    # New ARCHIVED status.
    r = client.patch(f"/agents/{agent_id}/status", headers=admin, json={"status": "ARCHIVED"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ARCHIVED"

    # Delete.
    r = client.delete(f"/agents/{agent_id}", headers=admin)
    assert r.status_code == 204, r.text
    assert client.get(f"/agents/{agent_id}", headers=admin).status_code == 404


def test_agent_stats_shape(client: TestClient) -> None:
    admin = _auth(_register(client))
    agent_id = client.post(
        "/agents", headers=admin, json={"name": "A", "agent_type": "t"}
    ).json()["id"]
    client.post(
        "/permissions",
        headers=admin,
        json={"agent_id": agent_id, "resource": "CLAIM", "action": "READ", "allowed": True},
    )
    client.post(
        "/agent-actions",
        headers=admin,
        json={"agent_id": agent_id, "resource": "CLAIM", "action": "READ", "input_payload": {}},
    )

    r = client.get(f"/agents/{agent_id}/stats", headers=admin)
    assert r.status_code == 200, r.text
    stats = r.json()
    assert stats["total_actions"] >= 1
    assert 0.0 <= stats["success_rate"] <= 1.0
    assert {"actions_today", "blocked_actions", "average_risk", "policies_triggered"} <= set(stats)
