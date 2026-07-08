"""Phase 4 Part 4.2.2.2 — audit-event completeness + administrative session management.

Closes the two acceptance-criteria gaps found in the §31 audit:

1. **§26 audit events.** Four event types were defined and never emitted:
   ``SESSION_UPDATED``, ``SESSION_EXPIRED``, ``SESSION_TIMEOUT``,
   ``SESSION_SUSPICIOUS``. Timeouts — the headline feature of this part — left no
   audit trail at all.
2. **§32 Definition of Done.** Every endpoint was self-service; an administrator
   could not see or revoke another user's session without disabling the account.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.identity.auth.enums import AuthEventType
from app.identity.models.enums import SessionRevocationReason, SessionStatus
from app.identity.models.security_event import SecurityEvent
from app.identity.models.session import UserSession
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
    """Register an org; returns (owner_email, legacy_admin_token).

    The identity admin API authenticates with the *legacy* token (it depends on
    ``app.api.deps.get_current_user``), which is what /auth/register returns.
    """
    email = f"admin_{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/auth/register",
        json={"organization_name": "Admin Org", "name": "Owner", "email": email,
              "password": PASSWORD},
    )
    assert resp.status_code == 201
    return email, resp.json()["access_token"]


def _create_member(owner_email: str) -> tuple[uuid.UUID, str]:
    db = SessionLocal()
    try:
        owner = db.execute(select(User).where(User.email == owner_email)).scalar_one()
        member_email = f"member_{uuid.uuid4().hex[:8]}@example.com"
        member = IdentityService(db).create_user(
            UserCreate(
                email=member_email,
                display_name="Member",
                password=MEMBER_PASSWORD,
                organization_id=owner.organization_id,
            )
        )
        db.commit()
        return member.id, member_email
    finally:
        db.close()


def _login(client: TestClient, email: str, password: str = PASSWORD, ua: str = CHROME) -> dict:
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers={"User-Agent": ua},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _admin(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _events(session_id: str, event_type: AuthEventType) -> list[SecurityEvent]:
    db = SessionLocal()
    try:
        rows = db.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == event_type.value)
        ).scalars().all()
        return [e for e in rows if (e.meta or {}).get("session_id") == session_id]
    finally:
        db.close()


def _shift(session_id: str, **deltas: timedelta) -> None:
    db = SessionLocal()
    try:
        session = db.get(UserSession, uuid.UUID(session_id))
        for field, delta in deltas.items():
            setattr(session, field, datetime.now(timezone.utc) - delta)
        db.commit()
    finally:
        db.close()


# =========================================================================== #
# 1. Audit-event completeness (SRS §26)
# =========================================================================== #
def test_idle_timeout_emits_session_timeout_and_session_expired(client: TestClient) -> None:
    """A timeout is a lifecycle event nobody else observes: it happens inside the
    lifecycle service on a request that is about to be rejected. If it is not
    recorded there, it is never audited."""
    email, _ = _register(client)
    tokens = _login(client, email)
    sid = tokens["session_id"]

    _shift(sid, idle_expires_at=timedelta(seconds=1))
    resp = client.get("/api/v1/auth/me", headers=_auth(tokens))
    assert resp.json()["error"]["code"] == "SESSION_IDLE_TIMEOUT"

    timeout = _events(sid, AuthEventType.SESSION_TIMEOUT)
    expired = _events(sid, AuthEventType.SESSION_EXPIRED)
    assert timeout, "idle timeout produced no SESSION_TIMEOUT event"
    assert expired, "idle timeout produced no SESSION_EXPIRED event"
    assert timeout[0].meta["reason"] == SessionRevocationReason.IDLE_TIMEOUT.value


def test_absolute_timeout_emits_events_with_the_right_reason(client: TestClient) -> None:
    email, _ = _register(client)
    tokens = _login(client, email)
    sid = tokens["session_id"]

    _shift(sid, absolute_expires_at=timedelta(seconds=1))
    assert client.get("/api/v1/auth/me", headers=_auth(tokens)).status_code == 401

    timeout = _events(sid, AuthEventType.SESSION_TIMEOUT)
    assert timeout, "absolute timeout produced no SESSION_TIMEOUT event"
    assert timeout[0].meta["reason"] == SessionRevocationReason.ABSOLUTE_TIMEOUT.value


def test_token_reuse_emits_session_suspicious(client: TestClient) -> None:
    """TOKEN_REUSE_DETECTED describes what happened to the *token*.
    SESSION_SUSPICIOUS describes what happened to the *session*."""
    email, _ = _register(client)
    tokens = _login(client, email)
    sid = tokens["session_id"]
    stolen = tokens["refresh_token"]

    client.post("/api/v1/auth/refresh", json={"refresh_token": stolen})
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": stolen})
    assert replay.json()["error"]["code"] == "REFRESH_TOKEN_REUSED"

    suspicious = _events(sid, AuthEventType.SESSION_SUSPICIOUS)
    assert suspicious, "token reuse produced no SESSION_SUSPICIOUS event"
    assert suspicious[0].meta["signal"] == "refresh_token_reuse"
    assert suspicious[0].meta["band"] == "HIGH_RISK"
    # ...and the token-level event is still recorded.
    assert _events(sid, AuthEventType.TOKEN_REUSE_DETECTED)


def test_idle_state_is_real_and_resuming_emits_session_updated(client: TestClient) -> None:
    """``IDLE`` was a dead enum member: nothing ever assigned it, so the
    IDLE→ACTIVE transition — and therefore SESSION_UPDATED — could never happen.

    A session is IDLE when it is inside the warning window: still usable, but
    expiry is imminent. It is discovered by *observing* a session (listing it),
    never by the session making a request — a request is, by definition, activity.
    """
    email, _ = _register(client)
    other = _login(client, email, PASSWORD, ua=IPHONE)  # observer session
    target = _login(client, email, PASSWORD, ua=CHROME)
    sid = target["session_id"]

    # Push the idle deadline into the warning window (still in the future).
    warn = settings.SESSION_IDLE_WARNING_SECONDS
    db = SessionLocal()
    try:
        session = db.get(UserSession, uuid.UUID(sid))
        session.idle_expires_at = datetime.now(timezone.utc) + timedelta(seconds=warn // 2)
        session.last_activity_at = datetime.now(timezone.utc) - timedelta(seconds=600)
        db.commit()
    finally:
        db.close()

    # Observing the session materialises IDLE.
    listed = client.get("/api/v1/auth/sessions", headers=_auth(other)).json()
    assert any(s["id"] == sid and s["status"] == "IDLE" for s in listed), "IDLE never materialised"

    # The idle session is still usable, and using it resumes ACTIVE + audits it.
    assert client.get("/api/v1/auth/me", headers=_auth(target)).status_code == 200

    db = SessionLocal()
    try:
        assert db.get(UserSession, uuid.UUID(sid)).status == SessionStatus.ACTIVE.value
    finally:
        db.close()

    updated = _events(sid, AuthEventType.SESSION_UPDATED)
    assert updated, "IDLE→ACTIVE resume produced no SESSION_UPDATED event"
    assert updated[0].meta["from"] == "IDLE" and updated[0].meta["to"] == "ACTIVE"


def test_session_updated_is_not_emitted_on_every_request(client: TestClient) -> None:
    """Auditing the sliding idle deadline would write one event per user per
    minute, forever, and drown the stream it belongs to."""
    email, _ = _register(client)
    tokens = _login(client, email)
    sid = tokens["session_id"]

    for _ in range(3):
        # Force ``touch`` past its write throttle each time.
        _shift(sid, last_activity_at=timedelta(seconds=300))
        assert client.get("/api/v1/auth/me", headers=_auth(tokens)).status_code == 200

    assert _events(sid, AuthEventType.SESSION_UPDATED) == [], "SESSION_UPDATED emitted on activity"


def test_every_srs_26_event_type_is_reachable() -> None:
    """Guards against re-introducing a defined-but-never-emitted event type.

    Every §26 event must be referenced by production code, not just declared in
    the enum. This is the check that would have caught the original gap.
    """
    import pathlib
    import re

    srs_26 = [
        AuthEventType.SESSION_CREATED,
        AuthEventType.SESSION_UPDATED,
        AuthEventType.SESSION_REVOKED,
        AuthEventType.SESSION_EXPIRED,
        AuthEventType.SESSION_TIMEOUT,
        AuthEventType.SESSION_SUSPICIOUS,
        AuthEventType.SESSION_LIMIT_EXCEEDED,
        AuthEventType.DEVICE_REGISTERED,
        AuthEventType.DEVICE_TRUSTED,
        AuthEventType.DEVICE_BLOCKED,
        AuthEventType.TOKEN_ROTATED,
        AuthEventType.TOKEN_REUSE_DETECTED,
    ]
    app_dir = pathlib.Path(__file__).resolve().parents[3] / "app"
    sources = "\n".join(
        p.read_text(encoding="utf-8")
        for p in app_dir.rglob("*.py")
        if p.name != "enums.py"
    )
    dead = [
        e.name for e in srs_26
        if not re.search(rf"AuthEventType\.{e.name}\b", sources)
    ]
    assert not dead, f"SRS §26 event types defined but never emitted: {dead}"


# =========================================================================== #
# 2. Administrative session management (SRS §17, §32)
# =========================================================================== #
def test_admin_can_list_and_inspect_another_users_sessions(client: TestClient) -> None:
    owner_email, admin_token = _register(client)
    member_id, member_email = _create_member(owner_email)
    member = _login(client, member_email, MEMBER_PASSWORD)

    listed = client.get(
        f"/api/v1/identity/sessions?user_id={member_id}", headers=_admin(admin_token)
    )
    assert listed.status_code == 200
    assert [s["id"] for s in listed.json()] == [member["session_id"]]

    detail = client.get(
        f"/api/v1/identity/sessions/{member['session_id']}", headers=_admin(admin_token)
    )
    assert detail.status_code == 200
    assert detail.json()["security_band"] == "HEALTHY"

    devices = client.get(
        f"/api/v1/identity/users/{member_id}/devices", headers=_admin(admin_token)
    )
    assert devices.status_code == 200 and len(devices.json()) == 1


def test_admin_force_logout_kills_the_members_session_immediately(client: TestClient) -> None:
    """The "employee leaves the company" case — without disabling the account."""
    owner_email, admin_token = _register(client)
    member_id, member_email = _create_member(owner_email)
    member = _login(client, member_email, MEMBER_PASSWORD)
    assert client.get("/api/v1/auth/me", headers=_auth(member)).status_code == 200

    revoked = client.post(
        f"/api/v1/identity/sessions/{member['session_id']}/revoke",
        headers=_admin(admin_token),
    )
    assert revoked.status_code == 200
    assert revoked.json()["revoked_reason"] == SessionRevocationReason.ADMIN_REVOKED.value

    dead = client.get("/api/v1/auth/me", headers=_auth(member))
    assert dead.status_code == 401
    assert dead.json()["error"]["code"] == "SESSION_REVOKED"
    # The refresh token cannot resurrect it.
    assert client.post(
        "/api/v1/auth/refresh", json={"refresh_token": member["refresh_token"]}
    ).status_code == 401

    # The account still works — this is force-logout, not account disablement.
    assert _login(client, member_email, MEMBER_PASSWORD)["access_token"]


def test_admin_revoke_all_signs_member_out_of_every_device(client: TestClient) -> None:
    owner_email, admin_token = _register(client)
    member_id, member_email = _create_member(owner_email)
    laptop = _login(client, member_email, MEMBER_PASSWORD, ua=CHROME)
    phone = _login(client, member_email, MEMBER_PASSWORD, ua=IPHONE)

    resp = client.post(
        f"/api/v1/identity/users/{member_id}/sessions/revoke-all",
        headers=_admin(admin_token),
        json={"reason": "SECURITY_EVENT"},
    )
    assert resp.status_code == 200
    assert len(resp.json()["revoked_session_ids"]) == 2

    for tokens in (laptop, phone):
        assert client.get("/api/v1/auth/me", headers=_auth(tokens)).status_code == 401


def test_admin_revocation_records_who_did_it(client: TestClient) -> None:
    """An audit record of a force-logout that omits the actor is not an audit record."""
    owner_email, admin_token = _register(client)
    member_id, member_email = _create_member(owner_email)
    member = _login(client, member_email, MEMBER_PASSWORD)

    client.post(
        f"/api/v1/identity/sessions/{member['session_id']}/revoke",
        headers=_admin(admin_token),
    )
    events = _events(member["session_id"], AuthEventType.SESSION_REVOKED)
    assert events, "no SESSION_REVOKED event"
    meta = events[-1].meta
    assert meta["actor_email"] == owner_email
    assert meta["reason"] == SessionRevocationReason.ADMIN_REVOKED.value
    # The subject is the member, not the admin.
    assert str(events[-1].actor_id) == str(member_id)


def test_admin_cannot_touch_another_organizations_session(client: TestClient) -> None:
    """Cross-tenant isolation: 404, never "exists but not yours"."""
    _, admin_a = _register(client)
    owner_b, _ = _register(client)
    victim_id, victim_email = _create_member(owner_b)
    victim = _login(client, victim_email, MEMBER_PASSWORD)

    assert client.get(
        f"/api/v1/identity/sessions?user_id={victim_id}", headers=_admin(admin_a)
    ).status_code == 404
    assert client.get(
        f"/api/v1/identity/sessions/{victim['session_id']}", headers=_admin(admin_a)
    ).status_code == 404
    assert client.post(
        f"/api/v1/identity/sessions/{victim['session_id']}/revoke", headers=_admin(admin_a)
    ).status_code == 404
    assert client.post(
        f"/api/v1/identity/users/{victim_id}/sessions/revoke-all", headers=_admin(admin_a)
    ).status_code == 404

    # The victim's session is untouched.
    assert client.get("/api/v1/auth/me", headers=_auth(victim)).status_code == 200


def test_non_admin_cannot_revoke_sessions(client: TestClient) -> None:
    """A VIEWER holds neither session.view nor session.revoke."""
    owner_email, _ = _register(client)
    member_id, member_email = _create_member(owner_email)
    member = _login(client, member_email, MEMBER_PASSWORD)

    # The member's own legacy token: default role is VIEWER.
    legacy = client.post(
        "/auth/login", json={"email": member_email, "password": MEMBER_PASSWORD}
    ).json()["access_token"]

    assert client.get(
        f"/api/v1/identity/sessions?user_id={member_id}", headers=_admin(legacy)
    ).status_code == 403
    assert client.post(
        f"/api/v1/identity/sessions/{member['session_id']}/revoke", headers=_admin(legacy)
    ).status_code == 403
    # ...and their own session still works: authorization failed, nothing was revoked.
    assert client.get("/api/v1/auth/me", headers=_auth(member)).status_code == 200


def test_suspend_endpoint_also_terminates_sessions(client: TestClient) -> None:
    """``POST /users/{id}/suspend`` goes through ``set_user_active``, a *different*
    code path from ``transition_user``. The guarantee must not depend on which door
    the administrator walked through.

    Disabled identities get ``TERMINATED``, not ``REVOKED``: a revoked session is one
    the user could replace by signing in again; a terminated one is final.
    """
    owner_email, admin_token = _register(client)
    member_id, member_email = _create_member(owner_email)
    member = _login(client, member_email, MEMBER_PASSWORD)
    assert client.get("/api/v1/auth/me", headers=_auth(member)).status_code == 200

    resp = client.post(
        f"/api/v1/identity/users/{member_id}/suspend", headers=_admin(admin_token)
    )
    assert resp.status_code == 200

    dead = client.get("/api/v1/auth/me", headers=_auth(member))
    assert dead.status_code == 401, "suspend endpoint left the session alive"
    assert dead.json()["error"]["code"] == "SESSION_REVOKED"

    db = SessionLocal()
    try:
        session = db.get(UserSession, uuid.UUID(member["session_id"]))
        assert session.status == SessionStatus.TERMINATED.value
        assert session.revoked_reason == SessionRevocationReason.ACCOUNT_DISABLED.value
    finally:
        db.close()

    # A suspended identity cannot sign back in.
    blocked = client.post(
        "/api/v1/auth/login", json={"email": member_email, "password": MEMBER_PASSWORD}
    )
    assert blocked.status_code == 403


def test_admin_revoke_rejects_an_unknown_reason(client: TestClient) -> None:
    owner_email, admin_token = _register(client)
    _, member_email = _create_member(owner_email)
    member = _login(client, member_email, MEMBER_PASSWORD)

    resp = client.post(
        f"/api/v1/identity/sessions/{member['session_id']}/revoke",
        headers=_admin(admin_token),
        json={"reason": "BECAUSE_I_SAID_SO"},
    )
    assert resp.status_code == 422
    assert client.get("/api/v1/auth/me", headers=_auth(member)).status_code == 200
