"""Verified email-change flow (4.2.2.3.3 §12, §24, §30)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.identity.auth.enums import AuthEventType
from app.identity.models.enums import EmailVerificationPurpose
from app.identity.models.registration import EmailVerification
from app.identity.models.security_event import SecurityEvent
from app.identity.registration.tokens import generate_verification_token
from app.identity.security.passwords import hash_secret
from app.main import app
from app.models.user import User

PASSWORD = "T3st!Passw0rd#Ok"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)


def _register_and_login(client: TestClient) -> tuple[str, dict]:
    email = f"chg_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post(
        "/auth/register",
        json={"organization_name": "Change Org", "name": "Owner", "email": email, "password": PASSWORD},
    ).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    return email, tokens


def _auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _user(email: str) -> User:
    db = SessionLocal()
    try:
        return db.execute(select(User).where(User.email == email)).scalar_one()
    finally:
        db.close()


def _capture_change_token(user_id: uuid.UUID) -> str:
    """Overwrite the pending EMAIL_CHANGE token hash with a known plaintext (the real
    token is only in an email we do not send in tests)."""
    plaintext, hashed = generate_verification_token()
    db = SessionLocal()
    try:
        row = db.scalars(
            select(EmailVerification)
            .where(
                EmailVerification.user_id == user_id,
                EmailVerification.purpose == EmailVerificationPurpose.EMAIL_CHANGE.value,
                EmailVerification.verified_at.is_(None),
                EmailVerification.superseded_at.is_(None),
            )
            .order_by(EmailVerification.created_at.desc())
        ).first()
        row.verification_token_hash = hashed
        db.commit()
    finally:
        db.close()
    return plaintext


def test_email_change_requires_correct_current_password(client: TestClient) -> None:
    _email, tokens = _register_and_login(client)
    resp = client.post(
        "/api/v1/auth/change-email",
        headers=_auth(tokens),
        json={"new_email": f"new_{uuid.uuid4().hex[:8]}@example.com", "current_password": "wrong"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"


def test_email_change_end_to_end_swaps_the_address(client: TestClient) -> None:
    email, tokens = _register_and_login(client)
    user = _user(email)
    new_email = f"new_{uuid.uuid4().hex[:8]}@example.com"

    req = client.post(
        "/api/v1/auth/change-email",
        headers=_auth(tokens),
        json={"new_email": new_email, "current_password": PASSWORD},
    )
    assert req.status_code == 200

    # Current email still authoritative until confirmed (§12).
    refreshed = _user(email)
    assert refreshed.email == email and refreshed.pending_email == new_email

    token = _capture_change_token(user.id)
    verify = client.post("/api/v1/auth/verify-new-email", json={"token": token})
    assert verify.status_code == 200

    swapped = _user(new_email)
    assert swapped.id == user.id and swapped.pending_email is None
    # Can sign in with the new address; the old one no longer resolves.
    assert client.post("/api/v1/auth/login", json={"email": new_email, "password": PASSWORD}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401

    db = SessionLocal()
    try:
        for ev in (AuthEventType.EMAIL_CHANGE_VERIFIED, AuthEventType.EMAIL_CHANGED):
            assert db.scalars(
                select(SecurityEvent).where(
                    SecurityEvent.actor_id == user.id, SecurityEvent.event_type == ev.value
                )
            ).first() is not None
    finally:
        db.close()


def test_email_change_rejects_an_address_already_in_use(client: TestClient) -> None:
    _email_a, tokens_a = _register_and_login(client)
    email_b, _tokens_b = _register_and_login(client)
    resp = client.post(
        "/api/v1/auth/change-email",
        headers=_auth(tokens_a),
        json={"new_email": email_b, "current_password": PASSWORD},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "EMAIL_ALREADY_IN_USE"


def test_verify_new_email_rejects_an_invalid_token(client: TestClient) -> None:
    resp = client.post("/api/v1/auth/verify-new-email", json={"token": "vrf_bogus"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_VERIFICATION_TOKEN"


def test_change_email_requires_authentication(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/auth/change-email",
        json={"new_email": "x@example.com", "current_password": PASSWORD},
    )
    assert resp.status_code == 401
