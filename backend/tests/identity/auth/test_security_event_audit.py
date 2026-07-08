"""Reading the security-event stream (SRS §26; DoD §32 "…and audit user sessions").

Every session/device/token event is written to ``security_events``. Until this
existed, **nothing read that table** — no SELECT anywhere in ``app/`` — and the
events were deliberately not mirrored into ``audit_logs``
(``mirror_to_audit_log=False``). An administrator could revoke an employee's session
but could not afterwards answer "who revoked it, when, and why?".

Generating an audit event that nobody can read is not an audit trail.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.identity.schemas.identity import UserCreate
from app.identity.services.identity_service import IdentityService
from app.main import app
from app.models.user import User

PASSWORD = "T3st!Passw0rd#Ok"
MEMBER_PASSWORD = "M3mber!Passw0rd#Ok"
CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/604.1"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _register(client: TestClient) -> tuple[str, str]:
    email = f"audit_{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/auth/register",
        json={"organization_name": "Audit Org", "name": "Owner", "email": email,
              "password": PASSWORD},
    )
    assert resp.status_code == 201
    return email, resp.json()["access_token"]


def _create_member(owner_email: str) -> tuple[uuid.UUID, str]:
    db = SessionLocal()
    try:
        owner = db.execute(select(User).where(User.email == owner_email)).scalar_one()
        member_email = f"m_{uuid.uuid4().hex[:8]}@example.com"
        member = IdentityService(db).create_user(
            UserCreate(email=member_email, display_name="Member", password=MEMBER_PASSWORD,
                       organization_id=owner.organization_id)
        )
        db.commit()
        return member.id, member_email
    finally:
        db.close()


def _login(client: TestClient, email: str, password: str, ua: str = CHROME) -> dict:
    resp = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password},
        headers={"User-Agent": ua},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _types(events: list[dict]) -> set[str]:
    return {e["event_type"] for e in events}


# --------------------------------------------------------------------------- #
# Admin: audit the organization's security events (DoD §32)
# --------------------------------------------------------------------------- #
def test_admin_can_read_the_security_event_stream(client: TestClient) -> None:
    owner_email, admin = _register(client)
    _create_member(owner_email)

    resp = client.get("/api/v1/identity/security-events", headers=_h(admin))
    assert resp.status_code == 200, "security_events has no read path"
    body = resp.json()
    assert body["total"] >= 1
    assert _types(body["items"]) & {"SESSION_CREATED", "AUTH_LOGIN_SUCCESS", "IDENTITY_LIFECYCLE_CHANGED"}


def test_events_are_newest_first_and_paginated(client: TestClient) -> None:
    owner_email, admin = _register(client)
    _login(client, owner_email, PASSWORD)
    _login(client, owner_email, PASSWORD, ua=IPHONE)

    page = client.get("/api/v1/identity/security-events?limit=2", headers=_h(admin)).json()
    assert len(page["items"]) == 2
    assert page["items"][0]["created_at"] >= page["items"][1]["created_at"]
    assert page["total"] > 2

    second = client.get("/api/v1/identity/security-events?limit=2&offset=2", headers=_h(admin)).json()
    assert {e["id"] for e in page["items"]}.isdisjoint({e["id"] for e in second["items"]})


def test_filter_by_event_type_and_actor(client: TestClient) -> None:
    owner_email, admin = _register(client)
    member_id, member_email = _create_member(owner_email)
    _login(client, member_email, MEMBER_PASSWORD)

    by_type = client.get(
        "/api/v1/identity/security-events?event_type=SESSION_CREATED", headers=_h(admin)
    ).json()
    assert by_type["items"] and _types(by_type["items"]) == {"SESSION_CREATED"}

    by_actor = client.get(
        f"/api/v1/identity/security-events?actor_id={member_id}", headers=_h(admin)
    ).json()
    assert by_actor["items"]
    assert all(e["actor_id"] == str(member_id) for e in by_actor["items"])


def test_admin_can_audit_one_sessions_full_history(client: TestClient) -> None:
    """"Who revoked this session, when, and why?" — the question §32 demands."""
    owner_email, admin = _register(client)
    member_id, member_email = _create_member(owner_email)
    member = _login(client, member_email, MEMBER_PASSWORD)
    session_id = member["session_id"]

    client.post(f"/api/v1/identity/sessions/{session_id}/revoke", headers=_h(admin))

    resp = client.get(f"/api/v1/identity/sessions/{session_id}/events", headers=_h(admin))
    assert resp.status_code == 200
    events = resp.json()
    assert _types(events) >= {"SESSION_CREATED", "SESSION_REVOKED"}
    assert all(e["meta"]["session_id"] == session_id for e in events)

    revoked = next(e for e in events if e["event_type"] == "SESSION_REVOKED")
    assert revoked["meta"]["reason"] == "ADMIN_REVOKED"
    assert revoked["meta"]["actor_email"] == owner_email  # who pulled the trigger
    assert revoked["created_at"]                            # when


def test_token_reuse_is_visible_in_the_audit_stream(client: TestClient) -> None:
    owner_email, admin = _register(client)
    tokens = _login(client, owner_email, PASSWORD)
    stolen = tokens["refresh_token"]
    client.post("/api/v1/auth/refresh", json={"refresh_token": stolen})
    client.post("/api/v1/auth/refresh", json={"refresh_token": stolen})

    events = client.get(
        f"/api/v1/identity/sessions/{tokens['session_id']}/events", headers=_h(admin)
    ).json()
    assert _types(events) >= {"TOKEN_REUSE_DETECTED", "SESSION_SUSPICIOUS"}
    suspicious = next(e for e in events if e["event_type"] == "SESSION_SUSPICIOUS")
    assert suspicious["meta"]["band"] == "HIGH_RISK"


def test_timeouts_are_visible_in_the_audit_stream(client: TestClient) -> None:
    from datetime import datetime, timedelta, timezone

    from app.identity.models.session import UserSession

    owner_email, admin = _register(client)
    tokens = _login(client, owner_email, PASSWORD)

    db = SessionLocal()
    try:
        s = db.get(UserSession, uuid.UUID(tokens["session_id"]))
        s.idle_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    client.get("/api/v1/auth/me", headers=_h(tokens["access_token"]))

    events = client.get(
        f"/api/v1/identity/sessions/{tokens['session_id']}/events", headers=_h(admin)
    ).json()
    assert _types(events) >= {"SESSION_TIMEOUT", "SESSION_EXPIRED"}
    timeout = next(e for e in events if e["event_type"] == "SESSION_TIMEOUT")
    assert timeout["meta"]["reason"] == "IDLE_TIMEOUT"


# --------------------------------------------------------------------------- #
# Isolation & authorization
# --------------------------------------------------------------------------- #
def test_events_are_scoped_to_the_callers_organization(client: TestClient) -> None:
    owner_a, admin_a = _register(client)
    owner_b, _ = _register(client)
    b_tokens = _login(client, owner_b, PASSWORD)

    body = client.get("/api/v1/identity/security-events?limit=200", headers=_h(admin_a)).json()
    session_ids = {e.get("meta", {}).get("session_id") for e in body["items"]}
    assert b_tokens["session_id"] not in session_ids, "cross-tenant event leak"

    # And another org's session id yields nothing rather than 200-with-data.
    other = client.get(
        f"/api/v1/identity/sessions/{b_tokens['session_id']}/events", headers=_h(admin_a)
    )
    assert other.status_code == 404


def test_reader_without_permission_is_refused(client: TestClient) -> None:
    owner_email, _ = _register(client)
    _, member_email = _create_member(owner_email)
    member_legacy = client.post(
        "/auth/login", json={"email": member_email, "password": MEMBER_PASSWORD}
    ).json()["access_token"]

    assert client.get(
        "/api/v1/identity/security-events", headers=_h(member_legacy)
    ).status_code == 403


# --------------------------------------------------------------------------- #
# Self-service: my own security activity (SRS §24, §25)
# --------------------------------------------------------------------------- #
def test_user_can_read_their_own_security_activity(client: TestClient) -> None:
    email, _ = _register(client)
    tokens = _login(client, email, PASSWORD)

    resp = client.get("/api/v1/auth/security-events", headers=_h(tokens["access_token"]))
    assert resp.status_code == 200
    events = resp.json()
    assert _types(events) >= {"SESSION_CREATED"}


def test_own_activity_never_leaks_another_users_events(client: TestClient) -> None:
    owner_email, _ = _register(client)
    member_id, member_email = _create_member(owner_email)
    _login(client, member_email, MEMBER_PASSWORD)
    owner = _login(client, owner_email, PASSWORD)

    events = client.get(
        "/api/v1/auth/security-events?limit=200", headers=_h(owner["access_token"])
    ).json()
    assert all(e["actor_id"] != str(member_id) for e in events)
