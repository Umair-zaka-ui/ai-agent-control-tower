"""Part 4.2.2.1 — human authentication endpoint + lockout + policy tests (SRS §25)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.config import settings
from app.identity.auth.enums import AuthEventType
from app.identity.auth.password_service import PasswordPolicyError, PasswordService
from app.identity.models.enums import IdentityStatus
from app.identity.models.login_history import LoginHistory
from app.identity.models.security_event import SecurityEvent
from app.identity.models.session import UserSession
from app.identity.schemas.identity import UserCreate
from app.identity.services.identity_service import IdentityService
from app.main import app
from app.models.user import User

PASSWORD = "T3st!Passw0rd#Ok"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _register(client: TestClient) -> str:
    email = f"human_{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/auth/register",
        json={"organization_name": "Human Auth Org", "name": "Owner", "email": email, "password": PASSWORD},
    )
    assert resp.status_code == 201
    return email


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #
def test_login_success_returns_tokens_and_records_history(client: TestClient) -> None:
    email = _register(client)
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] and body["refresh_token"].startswith("rt_")
    assert body["expires_in"] == settings.AUTH_ACCESS_TOKEN_TTL_SECONDS
    assert body["user"]["email"] == email
    assert body["mfa_required"] is False

    db = SessionLocal()
    try:
        hist = db.execute(
            select(LoginHistory).where(LoginHistory.email == email, LoginHistory.success.is_(True))
        ).scalars().all()
        assert len(hist) == 1
    finally:
        db.close()


def test_login_wrong_password_is_generic_and_audited(client: TestClient) -> None:
    email = _register(client)
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"

    db = SessionLocal()
    try:
        fails = db.execute(
            select(LoginHistory).where(LoginHistory.email == email, LoginHistory.success.is_(False))
        ).scalars().all()
        assert len(fails) == 1 and fails[0].failure_reason == "invalid_credentials"
    finally:
        db.close()


def test_login_unknown_email_does_not_reveal_existence(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": f"nobody_{uuid.uuid4().hex[:8]}@example.com", "password": "whatever12345"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_suspended_user_blocked(client: TestClient) -> None:
    owner_email = _register(client)
    db = SessionLocal()
    try:
        svc = IdentityService(db)
        owner = db.execute(select(User).where(User.email == owner_email)).scalar_one()
        member_email = f"m_{uuid.uuid4().hex[:8]}@example.com"
        member = svc.create_user(
            UserCreate(email=member_email, display_name="M", password="Str0ngPass!x2",
                       organization_id=owner.organization_id)
        )
        svc.transition_user(member.id, IdentityStatus.SUSPENDED)
        db.commit()
    finally:
        db.close()
    resp = client.post("/api/v1/auth/login", json={"email": member_email, "password": "Str0ngPass!x2"})
    assert resp.status_code in (403,)
    assert resp.json()["error"]["code"] in ("IDENTITY_SUSPENDED", "IDENTITY_DISABLED")


# --------------------------------------------------------------------------- #
# Account lockout (SRS §10)
# --------------------------------------------------------------------------- #
def test_account_lockout_after_threshold(client: TestClient) -> None:
    email = _register(client)
    # Exhaust the threshold with wrong passwords.
    for _ in range(settings.AUTH_LOCKOUT_THRESHOLD):
        r = client.post("/api/v1/auth/login", json={"email": email, "password": "bad-passwordxx"})
        assert r.status_code == 401

    # Next attempt is locked — even with the CORRECT password.
    locked = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert locked.status_code == 423
    assert locked.json()["error"]["code"] == "ACCOUNT_LOCKED"

    db = SessionLocal()
    try:
        assert db.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == AuthEventType.AUTH_LOGIN_LOCKED.value)
        ).scalars().first() is not None
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Refresh / logout / me / sessions
# --------------------------------------------------------------------------- #
def _login(client: TestClient, email: str) -> dict:
    return client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()


def test_refresh_rotates_and_detects_reuse(client: TestClient) -> None:
    email = _register(client)
    tokens = _login(client, email)
    old_refresh = tokens["refresh_token"]

    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != old_refresh

    reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "REFRESH_TOKEN_REUSED"


def test_me_returns_identity_projection(client: TestClient) -> None:
    email = _register(client)
    tokens = _login(client, email)
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["email"] == email
    assert body["assurance_level"] == "AAL1"
    assert body["session_id"]


def test_logout_revokes_session(client: TestClient) -> None:
    email = _register(client)
    tokens = _login(client, email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    out = client.post("/api/v1/auth/logout", headers=headers)
    assert out.status_code == 204
    # Refresh after logout fails (family revoked).
    reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert reuse.status_code == 401


def test_list_and_revoke_sessions(client: TestClient) -> None:
    email = _register(client)
    tokens = _login(client, email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    listed = client.get("/api/v1/auth/sessions", headers=headers)
    assert listed.status_code == 200
    sessions = listed.json()
    assert len(sessions) >= 1
    sid = sessions[0]["id"]

    revoked = client.delete(f"/api/v1/auth/sessions/{sid}", headers=headers)
    assert revoked.status_code == 204

    # Revoking a random (non-owned) session id is a generic 404.
    other = client.delete(f"/api/v1/auth/sessions/{uuid.uuid4()}", headers=headers)
    assert other.status_code == 404


# --------------------------------------------------------------------------- #
# Password policy (SRS §9)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "password",
    [
        "Short1!",            # too short
        "alllowercase123!",   # no uppercase
        "ALLUPPERCASE123!",   # no lowercase
        "NoDigitsHere!!",     # no digit
        "NoSpecialChar123",   # no special
        "Password123!",       # too common (blocklist)
    ],
)
def test_password_policy_rejects_weak(password: str) -> None:
    with pytest.raises(PasswordPolicyError):
        PasswordService.validate_complexity(password)


def test_password_policy_accepts_strong_and_rejects_identity_substring() -> None:
    PasswordService.validate_complexity("Str0ngP@ssword!")
    with pytest.raises(PasswordPolicyError):
        PasswordService.validate_complexity("Johnsmith99!!X", email="johnsmith@example.com")


# --------------------------------------------------------------------------- #
# Regression: the policy must be enforced at the ROUTES that set a password,
# not merely defined in PasswordService. Long-but-weak passwords clear Pydantic's
# min_length and must still be rejected by the complexity policy (SRS §9).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "password",
    [
        "password1234",       # long enough, but blocklisted
        "alllowercase123!",   # long enough, but no uppercase
        "NoSpecialChar123",   # long enough, but no special character
    ],
)
def test_register_endpoint_rejects_weak_password(client: TestClient, password: str) -> None:
    resp = client.post(
        "/auth/register",
        json={
            "organization_name": "Weak Org",
            "name": "Owner",
            "email": f"weak_{uuid.uuid4().hex[:8]}@example.com",
            "password": password,
        },
    )
    assert resp.status_code == 422, f"weak password {password!r} was accepted"


def test_create_user_endpoint_rejects_weak_password(client: TestClient) -> None:
    email = f"admin_{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post(
        "/auth/register",
        json={"organization_name": "Org", "name": "Owner", "email": email, "password": PASSWORD},
    )
    token = reg.json()["access_token"]
    resp = client.post(
        "/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Member",
            "email": f"member_{uuid.uuid4().hex[:8]}@example.com",
            "password": "alllowercase123!",
        },
    )
    assert resp.status_code == 422, "weak password accepted by /users"


def test_register_endpoint_accepts_strong_password(client: TestClient) -> None:
    resp = client.post(
        "/auth/register",
        json={
            "organization_name": "Strong Org",
            "name": "Owner",
            "email": f"strong_{uuid.uuid4().hex[:8]}@example.com",
            "password": "Str0ngP@ssword!",
        },
    )
    assert resp.status_code == 201


# --------------------------------------------------------------------------- #
# Regression: refresh-token reuse is a theft signal — it must kill the SESSION,
# not just the token family (SRS §20).
# --------------------------------------------------------------------------- #
def test_refresh_reuse_revokes_the_session(client: TestClient) -> None:
    email = _register(client)
    tokens = _login(client, email)
    old_refresh = tokens["refresh_token"]

    session_id = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    ).json()["session_id"]

    client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert reuse.json()["error"]["code"] == "REFRESH_TOKEN_REUSED"

    db = SessionLocal()
    try:
        session = db.get(UserSession, uuid.UUID(session_id))
        assert session.revoked_at is not None, "session survived a refresh-token reuse"
    finally:
        db.close()

    # ...and the revoked session no longer appears as active.
    listed = client.get(
        "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert session_id not in [s["id"] for s in listed.json()]


def test_access_token_outlives_session_revocation_documented_gap(client: TestClient) -> None:
    """Pins a KNOWN GAP (see docs/identity/token-strategy.md).

    `authenticate` validates the JWT signature without loading the session, so an
    access token minted before logout stays valid until it expires (≤15 min).
    If this test ever fails, revocation became immediate — delete the test and
    the "Known gap" note in token-strategy.md.
    """
    email = _register(client)
    tokens = _login(client, email)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    # The session is gone, but the already-issued access token still authenticates.
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
