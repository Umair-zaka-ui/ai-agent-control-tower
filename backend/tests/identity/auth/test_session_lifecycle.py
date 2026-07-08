"""Phase 4 Part 4.2.2.2 — login, logout & session lifecycle (SRS §29).

Covers all thirteen required scenarios:

    session creation · session expiration · idle timeout · absolute timeout
    refresh rotation · refresh reuse detection · multiple devices · logout
    logout all devices · device trust · session revocation · session listing
    session limits
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.identity.auth.device_service import fingerprint_for, parse_user_agent
from app.identity.auth.enums import AuthEventType
from app.identity.models.enums import (
    SessionRevocationReason,
    SessionSecurityBand,
    SessionStatus,
)
from app.identity.models.security_event import SecurityEvent
from app.identity.models.session import RefreshToken, UserDevice, UserSession
from app.main import app

PASSWORD = "T3st!Passw0rd#Ok"

CHROME_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
SAFARI_IOS = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1 Safari/604.1"
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _register(client: TestClient) -> str:
    email = f"sess_{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/auth/register",
        json={"organization_name": "Session Org", "name": "Owner", "email": email,
              "password": PASSWORD},
    )
    assert resp.status_code == 201
    return email


def _login(client: TestClient, email: str, *, ua: str = CHROME_WIN, remember_me: bool = False) -> dict:
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD, "remember_me": remember_me},
        headers={"User-Agent": ua},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _shift_session(session_id: str, **deltas: timedelta) -> None:
    """Move a session's deadlines into the past to simulate the clock advancing.

    Faking the clock beats sleeping for 30 minutes, and it exercises exactly the
    comparison the hot path makes.
    """
    db = SessionLocal()
    try:
        session = db.get(UserSession, uuid.UUID(session_id))
        for field, delta in deltas.items():
            setattr(session, field, datetime.now(timezone.utc) - delta)
        db.commit()
    finally:
        db.close()


def _events(user_id: uuid.UUID, event_type: AuthEventType) -> list[SecurityEvent]:
    db = SessionLocal()
    try:
        return list(
            db.execute(
                select(SecurityEvent).where(
                    SecurityEvent.actor_id == user_id,
                    SecurityEvent.event_type == event_type.value,
                )
            ).scalars().all()
        )
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 1. Session creation (SRS §5)
# --------------------------------------------------------------------------- #
def test_session_creation_persists_device_timings_and_family(client: TestClient) -> None:
    email = _register(client)
    tokens = _login(client, email)

    assert tokens["session_id"]
    assert tokens["security_score"] == 100  # first login: no history to penalise
    assert tokens["is_new_device"] is True
    assert tokens["idle_timeout_seconds"] == settings.SESSION_IDLE_TIMEOUT_SECONDS

    db = SessionLocal()
    try:
        session = db.get(UserSession, uuid.UUID(tokens["session_id"]))
        assert session.status == SessionStatus.ACTIVE.value
        assert session.organization_id is not None
        assert session.device_id is not None
        assert session.browser == "Chrome" and session.operating_system == "Windows 10/11"
        assert session.login_method == "PASSWORD"
        assert session.refresh_token_family_id is not None

        # The refresh token belongs to the session's family (SRS §7).
        token = db.execute(
            select(RefreshToken).where(RefreshToken.session_id == session.id)
        ).scalars().one()
        assert token.family_id == session.refresh_token_family_id

        # Timings: idle ≈ 30 min, absolute ≈ 12 h (SRS §12).
        span = (session.absolute_expires_at - session.created_at).total_seconds()
        idle = (session.idle_expires_at - session.created_at).total_seconds()
        assert abs(span - settings.SESSION_ABSOLUTE_TIMEOUT_SECONDS) < 5
        assert abs(idle - settings.SESSION_IDLE_TIMEOUT_SECONDS) < 5

        assert _events(session.user_id, AuthEventType.SESSION_CREATED)
    finally:
        db.close()


def test_remember_me_extends_absolute_ceiling_only(client: TestClient) -> None:
    """"Remember me" must not disable the idle timeout — an abandoned laptop is
    still an abandoned laptop."""
    email = _register(client)
    tokens = _login(client, email, remember_me=True)
    db = SessionLocal()
    try:
        session = db.get(UserSession, uuid.UUID(tokens["session_id"]))
        span = (session.absolute_expires_at - session.created_at).total_seconds()
        idle = (session.idle_expires_at - session.created_at).total_seconds()
        assert abs(span - settings.SESSION_REMEMBER_ME_SECONDS) < 5
        assert abs(idle - settings.SESSION_IDLE_TIMEOUT_SECONDS) < 5
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 2/3. Idle timeout (SRS §5, §12)
# --------------------------------------------------------------------------- #
def test_idle_timeout_rejects_and_records_reason(client: TestClient) -> None:
    email = _register(client)
    tokens = _login(client, email)
    assert client.get("/api/v1/auth/me", headers=_auth(tokens)).status_code == 200

    _shift_session(tokens["session_id"], idle_expires_at=timedelta(seconds=1))

    resp = client.get("/api/v1/auth/me", headers=_auth(tokens))
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "SESSION_IDLE_TIMEOUT"

    # The timeout is *recorded*, not merely derived, so the listing agrees.
    db = SessionLocal()
    try:
        session = db.get(UserSession, uuid.UUID(tokens["session_id"]))
        assert session.status == SessionStatus.EXPIRED.value
        assert session.revoked_reason == SessionRevocationReason.IDLE_TIMEOUT.value
    finally:
        db.close()


def test_activity_slides_the_idle_window(client: TestClient) -> None:
    email = _register(client)
    tokens = _login(client, email)
    session_id = tokens["session_id"]

    # Push last_activity_at back beyond the write-throttle so ``touch`` writes,
    # but keep the session inside its idle window.
    _shift_session(session_id, last_activity_at=timedelta(seconds=300))
    db = SessionLocal()
    try:
        before = db.get(UserSession, uuid.UUID(session_id)).idle_expires_at
    finally:
        db.close()

    assert client.get("/api/v1/auth/me", headers=_auth(tokens)).status_code == 200

    db = SessionLocal()
    try:
        after = db.get(UserSession, uuid.UUID(session_id)).idle_expires_at
        assert after > before, "activity did not extend the idle deadline"
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 4. Absolute timeout (SRS §12) — beats idle when both have elapsed
# --------------------------------------------------------------------------- #
def test_absolute_timeout_rejects_even_with_recent_activity(client: TestClient) -> None:
    email = _register(client)
    tokens = _login(client, email)
    _shift_session(tokens["session_id"], absolute_expires_at=timedelta(seconds=1))

    resp = client.get("/api/v1/auth/me", headers=_auth(tokens))
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "SESSION_EXPIRED"

    db = SessionLocal()
    try:
        session = db.get(UserSession, uuid.UUID(tokens["session_id"]))
        assert session.revoked_reason == SessionRevocationReason.ABSOLUTE_TIMEOUT.value
    finally:
        db.close()


def test_absolute_timeout_reported_when_both_deadlines_passed(client: TestClient) -> None:
    """A session past both deadlines is ABSOLUTE_TIMEOUT — the stronger statement."""
    email = _register(client)
    tokens = _login(client, email)
    _shift_session(
        tokens["session_id"],
        absolute_expires_at=timedelta(seconds=1),
        idle_expires_at=timedelta(seconds=1),
    )
    resp = client.get("/api/v1/auth/me", headers=_auth(tokens))
    assert resp.json()["error"]["code"] == "SESSION_EXPIRED"


def test_expired_session_cannot_be_refreshed(client: TestClient) -> None:
    """A refresh is activity, so it must respect the absolute ceiling too."""
    email = _register(client)
    tokens = _login(client, email)
    _shift_session(tokens["session_id"], absolute_expires_at=timedelta(seconds=1))

    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "SESSION_EXPIRED"


# --------------------------------------------------------------------------- #
# 5. Refresh rotation (SRS §8)
# --------------------------------------------------------------------------- #
def test_refresh_rotation_chains_within_one_family(client: TestClient) -> None:
    email = _register(client)
    tokens = _login(client, email)
    first = tokens["refresh_token"]

    second = client.post("/api/v1/auth/refresh", json={"refresh_token": first}).json()
    third = client.post("/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}).json()
    assert first != second["refresh_token"] != third["refresh_token"]

    db = SessionLocal()
    try:
        session = db.get(UserSession, uuid.UUID(tokens["session_id"]))
        chain = list(
            db.execute(
                select(RefreshToken)
                .where(RefreshToken.family_id == session.refresh_token_family_id)
                .order_by(RefreshToken.created_at)
            ).scalars().all()
        )
        assert len(chain) == 3, "each refresh must mint exactly one successor"
        # The first two are revoked and linked to their successor; the last is live.
        assert chain[0].revoked_at and chain[0].rotated_to_id == chain[1].id
        assert chain[1].revoked_at and chain[1].rotated_to_id == chain[2].id
        assert chain[2].revoked_at is None and chain[2].rotated_to_id is None
        assert {t.family_id for t in chain} == {session.refresh_token_family_id}
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 6. Refresh reuse detection (SRS §9)
# --------------------------------------------------------------------------- #
def test_refresh_reuse_kills_family_and_session(client: TestClient) -> None:
    email = _register(client)
    tokens = _login(client, email)
    stolen = tokens["refresh_token"]

    fresh = client.post("/api/v1/auth/refresh", json={"refresh_token": stolen}).json()
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": stolen})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "REFRESH_TOKEN_REUSED"

    db = SessionLocal()
    try:
        session = db.get(UserSession, uuid.UUID(tokens["session_id"]))
        assert session.status == SessionStatus.SUSPICIOUS.value
        assert session.revoked_reason == SessionRevocationReason.TOKEN_REUSE.value
        # SRS §15 works the example down to 20 on reuse. What matters is the band:
        # reuse must land in HIGH_RISK (0-49), not merely WARNING.
        assert session.security_score == 100 - settings.SESSION_SCORE_TOKEN_REUSE_PENALTY == 20
        assert SessionSecurityBand.for_score(session.security_score) == SessionSecurityBand.HIGH_RISK

        family = list(
            db.execute(
                select(RefreshToken).where(
                    RefreshToken.family_id == session.refresh_token_family_id
                )
            ).scalars().all()
        )
        assert all(t.revoked_at is not None for t in family), "family not fully revoked"
        assert any(t.reuse_detected_at is not None for t in family), "no forensic anchor"
        assert _events(session.user_id, AuthEventType.TOKEN_REUSE_DETECTED)
    finally:
        db.close()

    # The successor the legitimate client received is dead too.
    after = client.post("/api/v1/auth/refresh", json={"refresh_token": fresh["refresh_token"]})
    assert after.status_code == 401


def test_logout_is_not_reported_as_token_reuse(client: TestClient) -> None:
    """A revoked-but-never-rotated token is not a theft signal. Without the
    ``rotated_to_id`` condition, every logout would look like an attack."""
    email = _register(client)
    tokens = _login(client, email)
    client.post("/api/v1/auth/logout", headers=_auth(tokens))

    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "TOKEN_REVOKED"  # not REFRESH_TOKEN_REUSED


# --------------------------------------------------------------------------- #
# 7. Multiple devices / concurrent sessions (SRS §10)
# --------------------------------------------------------------------------- #
def test_multiple_devices_get_independent_sessions(client: TestClient) -> None:
    email = _register(client)
    laptop = _login(client, email, ua=CHROME_WIN)
    phone = _login(client, email, ua=SAFARI_IOS)
    desktop = _login(client, email, ua=FIREFOX_LINUX)

    assert len({laptop["session_id"], phone["session_id"], desktop["session_id"]}) == 3

    listed = client.get("/api/v1/auth/sessions", headers=_auth(phone)).json()
    assert len(listed) == 3
    current = [s for s in listed if s["is_current"]]
    assert len(current) == 1 and current[0]["id"] == phone["session_id"]

    devices = client.get("/api/v1/auth/devices", headers=_auth(phone)).json()
    assert len(devices) == 3
    assert {d["browser"] for d in devices} == {"Chrome", "Safari", "Firefox"}
    assert sum(1 for d in devices if d["is_current"]) == 1

    # Revoking the laptop must not touch the phone.
    client.post(f"/api/v1/auth/sessions/{laptop['session_id']}/revoke", headers=_auth(phone))
    assert client.get("/api/v1/auth/me", headers=_auth(phone)).status_code == 200
    assert client.get("/api/v1/auth/me", headers=_auth(laptop)).status_code == 401


def test_second_login_from_same_device_is_not_a_new_device(client: TestClient) -> None:
    email = _register(client)
    first = _login(client, email, ua=CHROME_WIN)
    second = _login(client, email, ua=CHROME_WIN)
    assert first["is_new_device"] is True
    assert second["is_new_device"] is False
    devices = client.get("/api/v1/auth/devices", headers=_auth(second)).json()
    assert len(devices) == 1, "same device registered twice"


# --------------------------------------------------------------------------- #
# 8/9. Logout & logout-all (SRS §16, §24)
# --------------------------------------------------------------------------- #
def test_logout_revokes_only_the_current_session(client: TestClient) -> None:
    email = _register(client)
    laptop = _login(client, email, ua=CHROME_WIN)
    phone = _login(client, email, ua=SAFARI_IOS)

    out = client.post("/api/v1/auth/logout", headers=_auth(laptop))
    assert out.status_code == 200
    assert out.json()["revoked_session_ids"] == [laptop["session_id"]]

    assert client.get("/api/v1/auth/me", headers=_auth(laptop)).status_code == 401
    assert client.get("/api/v1/auth/me", headers=_auth(phone)).status_code == 200


def test_logout_all_devices_revokes_every_session(client: TestClient) -> None:
    email = _register(client)
    laptop = _login(client, email, ua=CHROME_WIN)
    phone = _login(client, email, ua=SAFARI_IOS)
    desktop = _login(client, email, ua=FIREFOX_LINUX)

    out = client.post("/api/v1/auth/logout", headers=_auth(phone), json={"all_devices": True})
    assert out.status_code == 200
    assert len(out.json()["revoked_session_ids"]) == 3

    for tokens in (laptop, phone, desktop):
        assert client.get("/api/v1/auth/me", headers=_auth(tokens)).status_code == 401
    # Refresh tokens die with their sessions.
    assert client.post(
        "/api/v1/auth/refresh", json={"refresh_token": desktop["refresh_token"]}
    ).status_code == 401


# --------------------------------------------------------------------------- #
# 10. Device trust & blocking (SRS §14)
# --------------------------------------------------------------------------- #
def test_device_trust_and_block(client: TestClient) -> None:
    email = _register(client)
    phone = _login(client, email, ua=SAFARI_IOS)
    laptop = _login(client, email, ua=CHROME_WIN)

    devices = client.get("/api/v1/auth/devices", headers=_auth(laptop)).json()
    phone_device = next(d for d in devices if d["browser"] == "Safari")
    assert phone_device["status"] == "UNKNOWN"

    trusted = client.post(f"/api/v1/auth/devices/{phone_device['id']}/trust", headers=_auth(laptop))
    assert trusted.status_code == 200 and trusted.json()["status"] == "TRUSTED"

    # Blocking a device must also kill its live sessions — otherwise it is theatre.
    blocked = client.post(f"/api/v1/auth/devices/{phone_device['id']}/block", headers=_auth(laptop))
    assert blocked.status_code == 200 and blocked.json()["status"] == "BLOCKED"
    assert client.get("/api/v1/auth/me", headers=_auth(phone)).status_code == 401
    assert client.get("/api/v1/auth/me", headers=_auth(laptop)).status_code == 200

    # ...and a blocked device cannot log in again.
    denied = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
        headers={"User-Agent": SAFARI_IOS},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "DEVICE_BLOCKED"


def test_device_not_owned_by_caller_is_404(client: TestClient) -> None:
    email_a = _register(client)
    email_b = _register(client)
    a = _login(client, email_a)
    b = _login(client, email_b, ua=SAFARI_IOS)
    b_device = client.get("/api/v1/auth/devices", headers=_auth(b)).json()[0]

    resp = client.post(f"/api/v1/auth/devices/{b_device['id']}/trust", headers=_auth(a))
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# 11/12. Session revocation & listing (SRS §17, §18, §19)
# --------------------------------------------------------------------------- #
def test_session_detail_and_revocation_reason(client: TestClient) -> None:
    email = _register(client)
    laptop = _login(client, email, ua=CHROME_WIN)
    phone = _login(client, email, ua=SAFARI_IOS)

    detail = client.get(f"/api/v1/auth/sessions/{laptop['session_id']}", headers=_auth(phone))
    assert detail.status_code == 200
    body = detail.json()
    assert body["security_band"] == "HEALTHY"
    assert body["refresh_token_family_id"]
    assert body["is_current"] is False

    revoked = client.post(
        f"/api/v1/auth/sessions/{laptop['session_id']}/revoke",
        headers=_auth(phone),
        json={"reason": "ADMIN_REVOKED"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["revoked_reason"] == "ADMIN_REVOKED"


def test_cannot_see_or_revoke_another_users_session(client: TestClient) -> None:
    """A 404 for "not yours" must be indistinguishable from "does not exist"."""
    victim_email = _register(client)
    attacker_email = _register(client)
    victim = _login(client, victim_email, ua=CHROME_WIN)
    attacker = _login(client, attacker_email, ua=SAFARI_IOS)

    assert client.get(
        f"/api/v1/auth/sessions/{victim['session_id']}", headers=_auth(attacker)
    ).status_code == 404
    assert client.post(
        f"/api/v1/auth/sessions/{victim['session_id']}/revoke", headers=_auth(attacker)
    ).status_code == 404
    assert client.get(
        f"/api/v1/auth/sessions/{uuid.uuid4()}", headers=_auth(attacker)
    ).status_code == 404
    # The victim is untouched.
    assert client.get("/api/v1/auth/me", headers=_auth(victim)).status_code == 200


def test_listing_excludes_expired_sessions(client: TestClient) -> None:
    email = _register(client)
    laptop = _login(client, email, ua=CHROME_WIN)
    phone = _login(client, email, ua=SAFARI_IOS)

    _shift_session(laptop["session_id"], idle_expires_at=timedelta(seconds=1))
    listed = client.get("/api/v1/auth/sessions", headers=_auth(phone)).json()
    assert [s["id"] for s in listed] == [phone["session_id"]]

    db = SessionLocal()
    try:
        stale = db.get(UserSession, uuid.UUID(laptop["session_id"]))
        assert stale.status == SessionStatus.EXPIRED.value
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 13. Session limits (SRS §11)
# --------------------------------------------------------------------------- #
def test_session_limit_revokes_the_oldest(client: TestClient) -> None:
    email = _register(client)
    limit = settings.SESSION_MAX_CONCURRENT

    # Distinct device ids so each login is genuinely a separate device.
    logins = [
        client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": PASSWORD},
            headers={"User-Agent": CHROME_WIN, "X-Device-Id": f"device-{i}"},
        ).json()
        for i in range(limit + 1)
    ]

    newest = logins[-1]
    listed = client.get("/api/v1/auth/sessions", headers=_auth(newest)).json()
    assert len(listed) == limit, f"expected {limit} active sessions, got {len(listed)}"

    # The oldest was evicted, the newest survives.
    assert client.get("/api/v1/auth/me", headers=_auth(logins[0])).status_code == 401
    assert client.get("/api/v1/auth/me", headers=_auth(newest)).status_code == 200

    db = SessionLocal()
    try:
        evicted = db.get(UserSession, uuid.UUID(logins[0]["session_id"]))
        assert evicted.revoked_reason == SessionRevocationReason.SESSION_LIMIT_EXCEEDED.value
        assert _events(evicted.user_id, AuthEventType.SESSION_LIMIT_EXCEEDED)
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Security scoring (SRS §15)
# --------------------------------------------------------------------------- #
def test_first_login_scores_100_but_a_later_new_device_is_penalised(client: TestClient) -> None:
    """"New" is only meaningful against a baseline. The first-ever login has none,
    so it must not be flagged — otherwise every new account looks suspicious."""
    email = _register(client)
    first = _login(client, email, ua=CHROME_WIN)
    assert first["security_score"] == 100
    assert first["is_new_device"] is True  # true, but not penalised

    second_device = _login(client, email, ua=SAFARI_IOS)
    assert second_device["is_new_device"] is True
    assert second_device["security_score"] == 100 - settings.SESSION_SCORE_NEW_DEVICE_PENALTY

    db = SessionLocal()
    try:
        session = db.get(UserSession, uuid.UUID(second_device["session_id"]))
        assert session.security_score == second_device["security_score"]
    finally:
        db.close()


def test_trusted_device_absorbs_the_new_device_penalty(client: TestClient) -> None:
    email = _register(client)
    laptop = _login(client, email, ua=CHROME_WIN)

    # Pre-trust a device the user has not logged in from yet.
    db = SessionLocal()
    try:
        session = db.get(UserSession, uuid.UUID(laptop["session_id"]))
        device = UserDevice(
            user_id=session.user_id,
            fingerprint=fingerprint_for(SAFARI_IOS),
            device_name="iPhone",
            status="TRUSTED",
            created_at=datetime.now(timezone.utc),
        )
        db.add(device)
        db.commit()
    finally:
        db.close()

    phone = _login(client, email, ua=SAFARI_IOS)
    assert phone["security_score"] == 100, "a trusted device should not be penalised"


def test_security_band_reflects_score(client: TestClient) -> None:
    email = _register(client)
    _login(client, email, ua=CHROME_WIN)
    phone = _login(client, email, ua=SAFARI_IOS)  # 80 → HEALTHY boundary
    listed = client.get("/api/v1/auth/sessions", headers=_auth(phone)).json()
    current = next(s for s in listed if s["is_current"])
    assert current["security_score"] == 80
    assert current["security_band"] == "HEALTHY"


# --------------------------------------------------------------------------- #
# Account suspension must end live sessions (SRS §17, §20)
# --------------------------------------------------------------------------- #
def test_suspending_a_user_revokes_their_sessions(client: TestClient) -> None:
    """"Employee leaves the company" is the canonical force-logout case.

    Before this was wired, suspension blocked *new* logins while the existing
    access token kept working until the session's 12-hour absolute ceiling —
    because the hot path checks the session, not the user's status.
    """
    from app.identity.models.enums import IdentityStatus
    from app.identity.services.identity_service import IdentityService
    from app.models.user import User

    email = _register(client)
    laptop = _login(client, email, ua=CHROME_WIN)
    phone = _login(client, email, ua=SAFARI_IOS)
    assert client.get("/api/v1/auth/me", headers=_auth(laptop)).status_code == 200

    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.email == email)).scalar_one()
        IdentityService(db).transition_user(user.id, IdentityStatus.SUSPENDED)
    finally:
        db.close()

    for tokens in (laptop, phone):
        resp = client.get("/api/v1/auth/me", headers=_auth(tokens))
        assert resp.status_code == 401, "a suspended user's session survived"
        assert resp.json()["error"]["code"] == "SESSION_REVOKED"

    db = SessionLocal()
    try:
        session = db.get(UserSession, uuid.UUID(laptop["session_id"]))
        assert session.revoked_reason == SessionRevocationReason.ACCOUNT_DISABLED.value
    finally:
        db.close()

    # ...and the refresh token cannot resurrect it.
    assert client.post(
        "/api/v1/auth/refresh", json={"refresh_token": phone["refresh_token"]}
    ).status_code == 401


# --------------------------------------------------------------------------- #
# Unit: user-agent parsing & fingerprinting (SRS §13)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "ua,browser,os_name,device_type",
    [
        (CHROME_WIN, "Chrome", "Windows 10/11", "desktop"),
        (SAFARI_IOS, "Safari", "iOS", "mobile"),
        (FIREFOX_LINUX, "Firefox", "Linux", "desktop"),
        ("Mozilla/5.0 (Windows NT 10.0) Chrome/120 Safari/537 Edg/120.0", "Edge", "Windows 10/11", "desktop"),
        ("curl/8.4.0", None, None, "bot"),
        (None, None, None, "unknown"),
    ],
)
def test_user_agent_parsing(ua, browser, os_name, device_type) -> None:
    info = parse_user_agent(ua)
    assert info.browser == browser
    assert info.operating_system == os_name
    assert info.device_type == device_type


def test_edge_is_not_mistaken_for_chrome() -> None:
    """Edge advertises "Chrome"; Chrome advertises "Safari". Order matters."""
    edge = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
    assert parse_user_agent(edge).browser == "Edge"
    chrome = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    assert parse_user_agent(chrome).browser == "Chrome"


def test_fingerprint_is_stable_across_patch_versions() -> None:
    """A Chrome point release must not register as a brand-new device."""
    v120 = "Mozilla/5.0 (Windows NT 10.0) Chrome/120.0.6099.71 Safari/537.36"
    v121 = "Mozilla/5.0 (Windows NT 10.0) Chrome/121.0.6167.85 Safari/537.36"
    assert fingerprint_for(v120) == fingerprint_for(v121)
    assert fingerprint_for(v120) != fingerprint_for(SAFARI_IOS)


def test_explicit_device_id_header_wins() -> None:
    assert fingerprint_for(CHROME_WIN, "abc") != fingerprint_for(CHROME_WIN, "xyz")
    assert fingerprint_for(CHROME_WIN, "abc") == fingerprint_for(SAFARI_IOS, "abc")
