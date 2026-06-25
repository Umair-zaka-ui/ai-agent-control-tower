"""Tests for the Phase 3 Part 3.1 dashboard endpoints (activity, risk-trend,
today's actions, system health)."""

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


def _make_action(client: TestClient, admin: dict[str, str]) -> None:
    agent_id = client.post(
        "/agents", headers=admin, json={"name": "A", "agent_type": "t"}
    ).json()["id"]
    client.post(
        "/permissions",
        headers=admin,
        json={"agent_id": agent_id, "resource": "CLAIM", "action": "READ", "allowed": True},
    )
    r = client.post(
        "/agent-actions",
        headers=admin,
        json={"agent_id": agent_id, "resource": "CLAIM", "action": "READ", "input_payload": {}},
    )
    assert r.status_code == 201, r.text


def test_summary_includes_today_actions(client: TestClient) -> None:
    admin = _auth(_register(client))
    _make_action(client, admin)

    summary = client.get("/dashboard/summary", headers=admin).json()
    assert "today_actions" in summary
    assert summary["today_actions"] >= 1
    assert summary["total_actions"] >= summary["today_actions"]


def test_activity_series_is_continuous(client: TestClient) -> None:
    admin = _auth(_register(client))
    _make_action(client, admin)

    series = client.get("/dashboard/activity", headers=admin).json()
    assert len(series) == 7  # default 7-day window
    assert all({"date", "actions"} <= set(point) for point in series)
    # Today (last point) should reflect at least the one action we created.
    assert series[-1]["actions"] >= 1


def test_risk_trend_series(client: TestClient) -> None:
    admin = _auth(_register(client))
    _make_action(client, admin)

    series = client.get("/dashboard/risk-trend?days=30", headers=admin).json()
    assert len(series) == 30
    assert all({"date", "risk_score"} <= set(point) for point in series)
    assert all(0 <= point["risk_score"] <= 100 for point in series)


def test_system_health_all_healthy(client: TestClient) -> None:
    admin = _auth(_register(client))

    health = client.get("/system/health", headers=admin).json()
    assert health == {
        "api": "healthy",
        "database": "healthy",
        "policy_engine": "healthy",
        "approval_engine": "healthy",
        "audit": "healthy",
    }
