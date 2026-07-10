"""Phase 4.3.2 integration tests — the /authorization/check endpoint, the cached
engine, wildcard + cache invalidation, explicit deny, and decision audit (§29)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.rbac import AuthorizationDecision


def _check(client, admin, permission, **body):
    resp = client.post(
        "/api/v1/authorization/check",
        json={"permission": permission, **body},
        headers=admin["headers"],
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _new_role(client, admin, **over) -> dict:
    body = {"name": f"role_{uuid.uuid4().hex[:8]}", "category": "CUSTOM",
            "priority": 40, "permissions": ["agent.view"], **over}
    resp = client.post("/api/v1/roles", json=body, headers=admin["headers"])
    assert resp.status_code == 201, resp.text
    return resp.json()


def _assign(client, admin, role_id, scope="ORGANIZATION"):
    resp = client.post(
        "/api/v1/role-assignments",
        json={"user_id": admin["user_id"], "role_id": role_id, "scope": scope},
        headers=admin["headers"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- the check endpoint ---------------------------------------------------- #
def test_check_requires_auth(client: TestClient) -> None:
    assert client.post("/api/v1/authorization/check", json={"permission": "agent.view"}).status_code in (401, 403)


def test_check_allows_held_permission(client: TestClient, admin: dict) -> None:
    # The org owner (SUPER_ADMIN) holds the full catalog via the legacy fallback.
    result = _check(client, admin, "agent.view")
    assert result["allowed"] is True
    assert result["evaluation_time_ms"] is not None


def test_check_denies_unheld_permission(client: TestClient, admin: dict) -> None:
    result = _check(client, admin, "nonexistent.permission")
    assert result["allowed"] is False
    assert "not assigned" in result["reason"].lower()


def test_check_records_a_decision(client: TestClient, admin: dict) -> None:
    _check(client, admin, "nonexistent.audited")
    db = SessionLocal()
    try:
        row = db.execute(
            select(AuthorizationDecision)
            .where(AuthorizationDecision.permission == "nonexistent.audited")
            .order_by(AuthorizationDecision.created_at.desc())
        ).scalars().first()
        assert row is not None and row.allowed is False
        assert row.evaluation_time_ms is not None
    finally:
        db.close()


# --- wildcard + cache invalidation ----------------------------------------- #
def test_global_wildcard_and_cache_invalidation(client: TestClient, admin: dict) -> None:
    novel = f"zzz.{uuid.uuid4().hex[:8]}"
    # Initially denied — SUPER_ADMIN has the concrete catalog, not the '*' wildcard.
    assert _check(client, admin, novel)["allowed"] is False

    # Fetch the global ROLE_PLATFORM_OWNER (has '*') and assign it. Assigning bumps
    # the org permission version, which must invalidate the cached deny above.
    roles = client.get("/api/v1/roles", headers=admin["headers"]).json()
    owner = next(r for r in roles if r["name"] == "ROLE_PLATFORM_OWNER")
    _assign(client, admin, owner["id"], scope="GLOBAL")

    after = _check(client, admin, novel)
    assert after["allowed"] is True, "global wildcard did not grant, or cache was not invalidated"


# --- explicit deny (§16) --------------------------------------------------- #
def test_explicit_deny_wins_over_allow(client: TestClient, admin: dict) -> None:
    # A role that allows agent.view but explicitly denies agent.delete.
    role = _new_role(client, admin, permissions=["agent.view"], denied_permissions=["agent.delete"])
    body = client.get(f"/api/v1/roles/{role['id']}", headers=admin["headers"]).json()
    assert body["denied_permissions"] == ["agent.delete"]
    _assign(client, admin, role["id"], scope="GLOBAL")

    # The owner still holds agent.delete via the legacy fallback (ALLOW), but the
    # new role's explicit DENY must win.
    assert _check(client, admin, "agent.delete")["allowed"] is False
    assert _check(client, admin, "agent.view")["allowed"] is True


# --- cache hit ------------------------------------------------------------- #
def test_cache_hit_on_second_check(client: TestClient, admin: dict) -> None:
    _check(client, admin, "agent.view")          # populates cache (miss)
    second = _check(client, admin, "agent.view")  # should hit
    assert second["cache_hit"] is True


# --- audit events (§27) ---------------------------------------------------- #
def test_check_generates_named_engine_events(client: TestClient, admin: dict) -> None:
    # First call is a miss -> a cache refresh + the pipeline-step events + a granted event.
    first = _check(client, admin, "agent.view")
    assert "PERMISSION_CACHE_REFRESHED" in first["events"]
    for ev in ("ROLE_RESOLVED", "SCOPE_VALIDATED", "CONFLICT_RESOLVED", "AUTHORIZATION_GRANTED"):
        assert ev in first["events"], ev

    denied = _check(client, admin, "nope.nope")
    assert "AUTHORIZATION_DENIED" in denied["events"]


def test_wildcard_expanded_event(client: TestClient, admin: dict) -> None:
    roles = client.get("/api/v1/roles", headers=admin["headers"]).json()
    owner = next(r for r in roles if r["name"] == "ROLE_PLATFORM_OWNER")
    _assign(client, admin, owner["id"], scope="GLOBAL")  # grants '*'
    result = _check(client, admin, f"anything.{uuid.uuid4().hex[:6]}")
    assert result["allowed"] is True
    assert "WILDCARD_EXPANDED" in result["events"]
