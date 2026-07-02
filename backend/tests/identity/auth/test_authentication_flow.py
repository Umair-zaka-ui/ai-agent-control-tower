"""Integration tests: login / refresh / rotation / reuse detection / logout."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.identity.auth.authentication_service import AuthenticationService
from app.identity.auth.enums import AuthEventType
from app.identity.auth.token_service import TokenService
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.enums import IdentityStatus
from app.identity.models.security_event import SecurityEvent
from app.identity.services.identity_service import IdentityService
from app.identity.schemas.identity import UserCreate
from app.main import app
from app.models.user import User


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _register(client: TestClient) -> tuple[str, uuid.UUID]:
    email = f"owner_{uuid.uuid4().hex[:10]}@example.com"
    client.post(
        "/auth/register",
        json={"organization_name": "Auth Org", "name": "Owner", "email": email, "password": "password123"},
    )
    return email, "password123"  # type: ignore[return-value]


def test_login_success_issues_tokens_and_event(client: TestClient) -> None:
    email, password = _register(client)
    db = SessionLocal()
    try:
        result = AuthenticationService(db).login(email, password, ip_address="1.2.3.4")
        assert result.access_token and result.refresh_token.startswith("rt_")
        # Access token validates and carries the human identity type.
        claims = TokenService().validate_access_token(result.access_token)
        assert claims["identity_type"] == "HUMAN_USER" and claims["session_id"]
        # A success security event was recorded.
        events = db.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == AuthEventType.AUTH_LOGIN_SUCCESS.value)
        ).scalars().all()
        assert any(str(e.actor_id) == claims["identity_id"] for e in events)
    finally:
        db.close()


def test_login_failure_is_generic_and_audited(client: TestClient) -> None:
    email, _ = _register(client)
    db = SessionLocal()
    try:
        with pytest.raises(IdentityError) as exc:
            AuthenticationService(db).login(email, "wrong-password")
        assert exc.value.code == ErrorCode.INVALID_CREDENTIALS
        failed = db.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == AuthEventType.AUTH_LOGIN_FAILED.value)
        ).scalars().all()
        assert len(failed) >= 1
    finally:
        db.close()


def test_disabled_identity_blocked(client: TestClient) -> None:
    email, password = _register(client)
    db = SessionLocal()
    try:
        service = IdentityService(db)
        member_email = f"m_{uuid.uuid4().hex[:8]}@example.com"
        owner = db.execute(select(User).where(User.email == email)).scalar_one()
        member = service.create_user(
            UserCreate(email=member_email, display_name="M", password="Str0ngPass", organization_id=owner.organization_id)
        )
        service.transition_user(member.id, IdentityStatus.SUSPENDED)
        with pytest.raises(IdentityError) as exc:
            AuthenticationService(db).login(member_email, "Str0ngPass")
        assert exc.value.code in (ErrorCode.IDENTITY_SUSPENDED, ErrorCode.IDENTITY_DISABLED)
    finally:
        db.close()


def test_refresh_rotation_and_reuse_detection(client: TestClient) -> None:
    email, password = _register(client)
    db = SessionLocal()
    try:
        auth = AuthenticationService(db)
        login = auth.login(email, password)
        old_refresh = login.refresh_token

        # First refresh rotates: new token differs, new access token issued.
        rotated = auth.refresh(old_refresh)
        assert rotated.refresh_token != old_refresh
        assert TokenService().validate_access_token(rotated.access_token)

        # Replaying the OLD (already-rotated) token is detected as reuse.
        with pytest.raises(IdentityError) as exc:
            auth.refresh(old_refresh)
        assert exc.value.code == ErrorCode.REFRESH_TOKEN_REUSED

        # Reuse revoked the whole family: the rotated token no longer works.
        with pytest.raises(IdentityError):
            auth.refresh(rotated.refresh_token)

        assert db.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == AuthEventType.REFRESH_TOKEN_REUSED.value)
        ).scalars().first() is not None
    finally:
        db.close()


def test_logout_revokes_session(client: TestClient) -> None:
    email, password = _register(client)
    db = SessionLocal()
    try:
        auth = AuthenticationService(db)
        login = auth.login(email, password)
        from app.identity.models.session import UserSession

        session = db.get(UserSession, login.session_id)
        auth.logout(session)
        # Refresh after logout fails (family revoked).
        with pytest.raises(IdentityError):
            auth.refresh(login.refresh_token)
        assert db.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == AuthEventType.AUTH_LOGOUT.value)
        ).scalars().first() is not None
    finally:
        db.close()
