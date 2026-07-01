"""Tests for the Phase 3 Part 3.6 Analytics & AI Operations Center: overview,
KPIs, activity, fleet health, risk, performance, policy, review, cost, insights,
reports, and the analytics.view RBAC gate.
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
            "organization_name": "Analytics Org",
            "name": "Owner",
            "email": email,
            "password": "password123",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["access_token"], email


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_activity(client: TestClient, admin: dict[str, str]) -> None:
    agent_id = client.post(
        "/agents", headers=admin, json={"name": "ClaimsAgent", "agent_type": "billing"}
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
    # Pending-approval action + blocked action.
    client.post(
        "/agent-actions",
        headers=admin,
        json={"agent_id": agent_id, "resource": "CLAIM", "action": "SUBMIT_CLAIM", "input_payload": {"amount": 9000}},
    )
    client.post(
        "/agent-actions",
        headers=admin,
        json={"agent_id": agent_id, "resource": "CLAIM", "action": "DELETE", "input_payload": {}},
    )


def test_overview_and_kpis(client: TestClient) -> None:
    token, _ = _register(client)
    admin = _auth(token)
    _seed_activity(client, admin)

    overview = client.get("/analytics/overview", headers=admin).json()
    assert "kpis" in overview and "fleet_health" in overview
    assert "risk_distribution" in overview and "activity" in overview
    assert overview["fleet_health"]["total"] >= 1

    kpis = client.get("/analytics/kpis", headers=admin).json()
    keys = {k["key"] for k in kpis}
    assert {"total_agents", "actions_today", "success_rate", "compliance_score"} <= keys


def test_activity_ranges(client: TestClient) -> None:
    token, _ = _register(client)
    admin = _auth(token)
    _seed_activity(client, admin)
    for rng, n in (("daily", 14), ("weekly", 12), ("monthly", 12), ("yearly", 5)):
        rows = client.get("/analytics/activity", headers=admin, params={"range": rng}).json()
        assert len(rows) == n
        assert {"executed", "blocked", "approvals", "failures"} <= set(rows[0])


def test_fleet_risk_performance(client: TestClient) -> None:
    token, _ = _register(client)
    admin = _auth(token)
    _seed_activity(client, admin)

    fleet = client.get("/analytics/fleet-health", headers=admin).json()
    assert fleet["total"] >= 1 and fleet["healthy"] >= 0

    risk = client.get("/analytics/risk", headers=admin).json()
    assert "distribution" in risk and "heatmap" in risk and "high_risk_agents" in risk

    perf = client.get("/analytics/performance", headers=admin).json()
    assert "metrics" in perf and perf["metrics"]["estimated"] is True
    assert isinstance(perf["ranking"], list)


def test_policies_review_cost_insights(client: TestClient) -> None:
    token, _ = _register(client)
    admin = _auth(token)
    _seed_activity(client, admin)

    pol = client.get("/analytics/policies", headers=admin).json()
    assert pol["total_policies"] >= 1 and "coverage_pct" in pol

    review = client.get("/analytics/review", headers=admin).json()
    assert "pending_queue" in review and "reviewers" in review

    cost = client.get("/analytics/cost", headers=admin).json()
    assert cost["estimated"] is True and len(cost["items"]) == 6 and cost["total"] >= 0

    insights = client.get("/analytics/insights", headers=admin).json()
    assert isinstance(insights, list) and insights and "title" in insights[0]


def test_reports(client: TestClient) -> None:
    token, _ = _register(client)
    admin = _auth(token)
    _seed_activity(client, admin)
    report = client.get("/analytics/reports", headers=admin, params={"period": "monthly"}).json()
    assert report["period"] == "monthly"
    assert any(s["title"] == "Activity" for s in report["sections"])


def test_rbac_viewer_denied(client: TestClient) -> None:
    token, _ = _register(client)
    admin = _auth(token)

    viewer_email = f"viewer_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post(
        "/users",
        headers=admin,
        json={"name": "Vic Viewer", "email": viewer_email, "password": "password123", "role": "VIEWER"},
    )
    assert r.status_code == 201, r.text
    vtoken = client.post(
        "/auth/login", json={"email": viewer_email, "password": "password123"}
    ).json()["access_token"]
    viewer = _auth(vtoken)

    # Viewer lacks analytics.view → every analytics surface is forbidden.
    assert client.get("/analytics/overview", headers=viewer).status_code == 403
    assert client.get("/analytics/kpis", headers=viewer).status_code == 403
    assert client.get("/analytics/cost", headers=viewer).status_code == 403
