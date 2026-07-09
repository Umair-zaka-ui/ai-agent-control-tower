"""Credential-management endpoint + flow tests (4.2.2.3.2 §22, §30).

Covers the acceptance criteria end to end: change-password, history/reuse,
expiration enforcement at login, temporary passwords, the mandatory first-login
change, administrative reset, and the read surfaces (policy, expiration, dashboard).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.identity.auth.enums import AuthEventType
from app.identity.models.security_event import SecurityEvent
from app.identity.models.session import UserSession
from app.main import app
from app.models.user import User

PASSWORD = "T3st!Passw0rd#Ok"
NEW_PASSWORD = "Rt7&kLm2!Qw9zP"
THIRD_PASSWORD = "Vv4#nBx8!Lp2Qr"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_min_age(monkeypatch):
    """Neutralise the 24h minimum-age gate so multi-change tests can run back to
    back. Minimum age is exercised on its own in ``test_min_age_blocks_rapid_change``."""
    monkeypatch.setattr(settings, "PASSWORD_MIN_AGE_HOURS", 0)


def _register_owner(client: TestClient) -> tuple[str, dict]:
    email = f"cred_{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/auth/register",
        json={"organization_name": "Cred Org", "name": "Owner", "email": email, "password": PASSWORD},
    )
    assert resp.status_code == 201
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    return email, login.json()


def _auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _events(email_user_id: uuid.UUID, event_type: AuthEventType) -> list[SecurityEvent]:
    db = SessionLocal()
    try:
        return list(
            db.scalars(
                select(SecurityEvent).where(
                    SecurityEvent.target_id == email_user_id,
                    SecurityEvent.event_type == event_type.value,
                )
            )
        )
    finally:
        db.close()


def _user_by_email(email: str) -> User:
    db = SessionLocal()
    try:
        return db.execute(select(User).where(User.email == email)).scalar_one()
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Change password
# --------------------------------------------------------------------------- #
def test_change_password_succeeds_and_sets_expiry(client: TestClient) -> None:
    email, tokens = _register_owner(client)
    resp = client.post(
        "/api/v1/auth/change-password",
        headers=_auth(tokens),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["password_expires_at"] is not None

    user = _user_by_email(email)
    assert user.password_changed_at is not None
    assert user.password_expires_at is not None
    # The new password works; the old one no longer does.
    assert client.post("/api/v1/auth/login", json={"email": email, "password": NEW_PASSWORD}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401
    assert _events(user.id, AuthEventType.PASSWORD_CHANGED)


def test_change_password_wrong_current_is_401(client: TestClient) -> None:
    _email, tokens = _register_owner(client)
    resp = client.post(
        "/api/v1/auth/change-password",
        headers=_auth(tokens),
        json={"current_password": "not-the-password", "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"


def test_change_password_rejects_weak_new_password(client: TestClient) -> None:
    _email, tokens = _register_owner(client)
    resp = client.post(
        "/api/v1/auth/change-password",
        headers=_auth(tokens),
        json={"current_password": PASSWORD, "new_password": "weak"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] in ("PASSWORD_TOO_WEAK", "PASSWORD_POLICY_FAILED")


def test_change_password_rejects_reuse_of_current(client: TestClient) -> None:
    _email, tokens = _register_owner(client)
    resp = client.post(
        "/api/v1/auth/change-password",
        headers=_auth(tokens),
        json={"current_password": PASSWORD, "new_password": PASSWORD},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "PASSWORD_REUSED"


def test_history_prevents_returning_to_an_old_password(client: TestClient) -> None:
    email, tokens = _register_owner(client)
    # PASSWORD -> NEW_PASSWORD
    r1 = client.post(
        "/api/v1/auth/change-password",
        headers=_auth(tokens),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert r1.status_code == 200
    tokens2 = client.post("/api/v1/auth/login", json={"email": email, "password": NEW_PASSWORD}).json()
    # NEW_PASSWORD -> back to PASSWORD must be refused (it is in history).
    r2 = client.post(
        "/api/v1/auth/change-password",
        headers=_auth(tokens2),
        json={"current_password": NEW_PASSWORD, "new_password": PASSWORD},
    )
    assert r2.status_code == 422
    assert r2.json()["error"]["code"] == "PASSWORD_REUSED"
    # A genuinely new password is accepted.
    r3 = client.post(
        "/api/v1/auth/change-password",
        headers=_auth(tokens2),
        json={"current_password": NEW_PASSWORD, "new_password": THIRD_PASSWORD},
    )
    assert r3.status_code == 200


def test_min_age_blocks_rapid_change(client: TestClient, monkeypatch) -> None:
    """A password cannot be changed again within the minimum-age window (SRS §6) —
    the guard against cycling through history back to a favourite password."""
    monkeypatch.setattr(settings, "PASSWORD_MIN_AGE_HOURS", 24)
    email, tokens = _register_owner(client)
    r1 = client.post(
        "/api/v1/auth/change-password",
        headers=_auth(tokens),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert r1.status_code == 200
    tokens2 = client.post("/api/v1/auth/login", json={"email": email, "password": NEW_PASSWORD}).json()
    r2 = client.post(
        "/api/v1/auth/change-password",
        headers=_auth(tokens2),
        json={"current_password": NEW_PASSWORD, "new_password": THIRD_PASSWORD},
    )
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "PASSWORD_MIN_AGE"


def test_change_password_revokes_other_sessions(client: TestClient) -> None:
    email, tokens_a = _register_owner(client)
    # A second session for the same user.
    tokens_b = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    # Change from session A -> session B must be revoked, A survives.
    resp = client.post(
        "/api/v1/auth/change-password",
        headers=_auth(tokens_a),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 200
    # B can no longer be used.
    me_b = client.get("/api/v1/auth/me", headers=_auth(tokens_b))
    assert me_b.status_code == 401
    # A still works.
    assert client.get("/api/v1/auth/me", headers=_auth(tokens_a)).status_code == 200


# --------------------------------------------------------------------------- #
# Expiration at login
# --------------------------------------------------------------------------- #
def test_expired_password_flags_change_required_at_login(client: TestClient) -> None:
    email, _tokens = _register_owner(client)
    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.email == email)).scalar_one()
        user.password_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()
        user_id = user.id
    finally:
        db.close()

    resp = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200
    assert resp.json()["password_change_required"] is True
    assert _events(user_id, AuthEventType.PASSWORD_EXPIRED)


# --------------------------------------------------------------------------- #
# Admin reset + first-login change
# --------------------------------------------------------------------------- #
def _create_member(org_id: uuid.UUID, password: str) -> User:
    from app.core.enums import UserRole

    db = SessionLocal()
    try:
        member = User(
            organization_id=org_id,
            name="Member",
            email=f"member_{uuid.uuid4().hex[:10]}@example.com",
            password_hash=hash_password(password),
            role=UserRole.VIEWER,
            is_active=True,
            status="ACTIVE",
            password_changed_at=datetime.now(timezone.utc),
        )
        db.add(member)
        db.commit()
        db.refresh(member)
        db.expunge(member)
        return member
    finally:
        db.close()


def test_admin_reset_issues_temp_password_and_forces_change(client: TestClient) -> None:
    _owner_email, owner_tokens = _register_owner(client)
    owner = _user_by_email(_owner_email)
    member = _create_member(owner.organization_id, PASSWORD)

    resp = client.post(
        "/api/v1/auth/admin/reset-password",
        headers=_auth(owner_tokens),
        json={"user_id": str(member.id)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    temp = body["temporary_password"]
    assert body["must_change_password"] is True

    # The member logs in with the temp password and is told to change it.
    login = client.post("/api/v1/auth/login", json={"email": member.email, "password": temp})
    assert login.status_code == 200
    assert login.json()["password_change_required"] is True

    # First-login change works and clears the flag; audited as FIRST_LOGIN.
    member_tokens = login.json()
    change = client.post(
        "/api/v1/auth/change-password",
        headers=_auth(member_tokens),
        json={"current_password": temp, "new_password": NEW_PASSWORD},
    )
    assert change.status_code == 200
    refreshed = _user_by_email(member.email)
    assert refreshed.must_change_password is False
    assert _events(member.id, AuthEventType.FIRST_LOGIN_PASSWORD_CHANGED)
    assert _events(member.id, AuthEventType.PASSWORD_RESET)
    assert _events(member.id, AuthEventType.TEMP_PASSWORD_CREATED)


def test_admin_reset_cannot_cross_organizations(client: TestClient) -> None:
    _owner_a, tokens_a = _register_owner(client)
    _owner_b, _tokens_b = _register_owner(client)
    victim = _user_by_email(_owner_b)
    resp = client.post(
        "/api/v1/auth/admin/reset-password",
        headers=_auth(tokens_a),
        json={"user_id": str(victim.id)},
    )
    assert resp.status_code == 404  # never confirm a user in another org exists


# --------------------------------------------------------------------------- #
# Read surfaces
# --------------------------------------------------------------------------- #
def test_validate_password_endpoint_scores_without_side_effects(client: TestClient) -> None:
    _email, tokens = _register_owner(client)
    resp = client.post(
        "/api/v1/auth/validate-password",
        headers=_auth(tokens),
        json={"password": "Zt9$mQ2!vLp7Xw-Rainy"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meets_policy"] is True
    assert body["level"] in ("strong", "very_strong")

    weak = client.post(
        "/api/v1/auth/validate-password",
        headers=_auth(tokens),
        json={"password": "abc"},
    )
    assert weak.json()["meets_policy"] is False


def test_password_policy_endpoint_returns_active_policy(client: TestClient) -> None:
    _email, tokens = _register_owner(client)
    resp = client.get("/api/v1/auth/password-policy", headers=_auth(tokens))
    assert resp.status_code == 200
    body = resp.json()
    assert body["min_length"] == 12
    assert body["history_depth"] == settings.PASSWORD_HISTORY_DEPTH
    assert body["max_age_days"] == settings.PASSWORD_MAX_AGE_DAYS


def test_password_expiration_endpoint_reports_status(client: TestClient) -> None:
    _email, tokens = _register_owner(client)
    resp = client.get("/api/v1/auth/password-expiration", headers=_auth(tokens))
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_expired"] is False
    assert body["change_required"] is False


def test_password_dashboard_requires_permission_and_lists_temporary(client: TestClient) -> None:
    _owner_email, owner_tokens = _register_owner(client)
    owner = _user_by_email(_owner_email)
    member = _create_member(owner.organization_id, PASSWORD)
    client.post(
        "/api/v1/auth/admin/reset-password",
        headers=_auth(owner_tokens),
        json={"user_id": str(member.id)},
    )

    resp = client.get("/api/v1/security/password-dashboard", headers=_auth(owner_tokens))
    assert resp.status_code == 200
    body = resp.json()
    temp_ids = {row["user_id"] for row in body["temporary"]}
    assert str(member.id) in temp_ids
    assert body["total_users"] >= 2


def test_credential_endpoints_require_authentication(client: TestClient) -> None:
    assert client.post("/api/v1/auth/change-password", json={}).status_code == 401
    assert client.get("/api/v1/auth/password-expiration").status_code == 401
    assert client.get("/api/v1/security/password-dashboard").status_code in (401, 403)
