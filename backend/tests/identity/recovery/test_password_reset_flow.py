"""Forgot-password / reset flow (4.2.2.3.3 §9, §10, §13, §14, §28, §30).

Recovery is a takeover vector, so the tests pin the security properties, not just the
happy path: enumeration safety, single-use, expiry, replay rejection, session
invalidation, and audit.
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
from app.identity.models.enums import PasswordResetStatus
from app.identity.models.recovery import PasswordResetRequest
from app.identity.models.security_event import SecurityEvent
from app.identity.recovery.repository import PasswordResetRepository
from app.identity.registration.tokens import generate_reset_token
from app.main import app
from app.models.user import User

PASSWORD = "T3st!Passw0rd#Ok"
NEW_PASSWORD = "Rt7&kLm2!Qw9zP"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)


def _register(client: TestClient) -> str:
    email = f"recover_{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/auth/register",
        json={"organization_name": "Recover Org", "name": "Owner", "email": email, "password": PASSWORD},
    )
    assert resp.status_code == 201
    return email


def _user(email: str) -> User:
    db = SessionLocal()
    try:
        return db.execute(select(User).where(User.email == email)).scalar_one()
    finally:
        db.close()


def _events(user_id: uuid.UUID, event: AuthEventType) -> list[SecurityEvent]:
    db = SessionLocal()
    try:
        return list(
            db.scalars(
                select(SecurityEvent).where(
                    SecurityEvent.actor_id == user_id, SecurityEvent.event_type == event.value
                )
            )
        )
    finally:
        db.close()


def _mint_reset_token(email: str, *, expires_in: timedelta = timedelta(minutes=30),
                      status: str = PasswordResetStatus.PENDING.value) -> str:
    """Create a reset request directly and return its plaintext token — the token is
    otherwise only in an email we do not send in tests."""
    user = _user(email)
    plaintext, hashed = generate_reset_token()
    db = SessionLocal()
    try:
        db.add(PasswordResetRequest(
            user_id=user.id, organization_id=user.organization_id, token_hash=hashed,
            status=status, expires_at=datetime.now(timezone.utc) + expires_in,
        ))
        db.commit()
    finally:
        db.close()
    return plaintext


# --------------------------------------------------------------------------- #
# Forgot password — enumeration safety (§9)
# --------------------------------------------------------------------------- #
def test_forgot_password_is_uniform_for_known_and_unknown(client: TestClient) -> None:
    email = _register(client)
    known = client.post("/api/v1/auth/forgot-password", json={"email": email})
    unknown = client.post(
        "/api/v1/auth/forgot-password", json={"email": f"nobody_{uuid.uuid4().hex}@example.com"}
    )
    assert known.status_code == 200 and unknown.status_code == 200
    # Byte-identical body: no oracle.
    assert known.json() == unknown.json()
    assert "if an account exists" in known.json()["message"].lower()


def test_forgot_password_creates_a_request_only_for_a_real_account(client: TestClient) -> None:
    email = _register(client)
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    user = _user(email)
    db = SessionLocal()
    try:
        reqs = db.scalars(
            select(PasswordResetRequest).where(PasswordResetRequest.user_id == user.id)
        ).all()
        assert len(reqs) == 1 and reqs[0].status == PasswordResetStatus.PENDING.value
    finally:
        db.close()
    assert _events(user.id, AuthEventType.PASSWORD_RESET_REQUESTED)


def test_forgot_password_supersedes_a_previous_request(client: TestClient) -> None:
    email = _register(client)
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    user = _user(email)
    db = SessionLocal()
    try:
        reqs = db.scalars(
            select(PasswordResetRequest).where(PasswordResetRequest.user_id == user.id)
        ).all()
        pending = [r for r in reqs if r.status == PasswordResetStatus.PENDING.value]
        revoked = [r for r in reqs if r.status == PasswordResetStatus.REVOKED.value]
        assert len(pending) == 1 and len(revoked) == 1
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Reset — the happy path + security properties (§10, §13, §14)
# --------------------------------------------------------------------------- #
def test_reset_sets_new_password_and_old_one_stops_working(client: TestClient) -> None:
    email = _register(client)
    token = _mint_reset_token(email)
    resp = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    assert client.post("/api/v1/auth/login", json={"email": email, "password": NEW_PASSWORD}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401
    assert _events(_user(email).id, AuthEventType.PASSWORD_RESET_COMPLETED)


def test_reset_token_is_single_use(client: TestClient) -> None:
    email = _register(client)
    token = _mint_reset_token(email)
    first = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert first.status_code == 200
    second = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": "An0ther!Passw0rd#Z"}
    )
    assert second.status_code == 410
    assert second.json()["error"]["code"] == "RESET_TOKEN_USED"


def test_expired_reset_token_is_rejected(client: TestClient) -> None:
    email = _register(client)
    token = _mint_reset_token(email, expires_in=timedelta(minutes=-1))
    resp = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert resp.status_code == 410
    assert resp.json()["error"]["code"] == "RESET_TOKEN_EXPIRED"


def test_invalid_reset_token_is_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/auth/reset-password", json={"token": "rst_not-a-real-token", "new_password": NEW_PASSWORD}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "RESET_TOKEN_INVALID"


def test_reset_rejects_a_weak_new_password(client: TestClient) -> None:
    email = _register(client)
    token = _mint_reset_token(email)
    resp = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": "weak"}
    )
    assert resp.status_code == 422
    # The token is left usable so the user can retry with a compliant password.
    ok = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert ok.status_code == 200


def test_reset_revokes_all_sessions(client: TestClient) -> None:
    email = _register(client)
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}).status_code == 200

    reset_token = _mint_reset_token(email)
    client.post("/api/v1/auth/reset-password", json={"token": reset_token, "new_password": NEW_PASSWORD})

    # The pre-reset session is dead (§13).
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 401


def test_disabled_reset_returns_403(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "PASSWORD_RESET_ENABLED", False)
    email = _register(client)
    resp = client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PASSWORD_RESET_DISABLED"
