"""AuthenticationService — login / refresh / logout orchestration (SRS §16, §19–21).

Composes the credential, session, token, refresh-token and security-event
services. This is the enterprise login path (multi-identity, session-backed,
rotation + reuse detection); the legacy ``/auth/login`` route is untouched and
migrates onto this in a later subpart.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.identity.auth.context import IdentityContext
from app.identity.auth.credential_service import CredentialService
from app.identity.auth.enums import AuthEventType, AuthIdentityType, AuthMethod
from app.identity.auth.refresh_token_service import RefreshTokenService
from app.identity.auth.resolver import IdentityContextResolver
from app.identity.auth.security_event_service import SecurityEventService
from app.identity.auth.session_service import SessionService
from app.identity.auth.token_service import TokenService
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.enums import IdentityStatus
from app.identity.models.session import UserSession
from app.models.user import User
from app.services import auth_service


@dataclass
class LoginResult:
    access_token: str
    refresh_token: str
    session_id: uuid.UUID
    context: IdentityContext


@dataclass
class RefreshResult:
    access_token: str
    refresh_token: str
    session_id: uuid.UUID


class AuthenticationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.credentials = CredentialService()
        self.sessions = SessionService(db)
        self.tokens = TokenService(db)
        self.refresh_tokens = RefreshTokenService(db)
        self.events = SecurityEventService(db)
        self.resolver = IdentityContextResolver(db)

    # ------------------------------------------------------------------ #
    # Human login (SRS §19)
    # ------------------------------------------------------------------ #
    def login(
        self,
        email: str,
        password: str,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
    ) -> LoginResult:
        user = auth_service.authenticate_user(self.db, email, password)
        if user is None:
            # Do not reveal whether the email exists (SRS §19).
            self.events.record(
                AuthEventType.AUTH_LOGIN_FAILED,
                auth_method=AuthMethod.PASSWORD,
                identity_type=AuthIdentityType.HUMAN_USER.value,
                ip_address=ip_address,
                user_agent=user_agent,
                request_id=request_id,
                metadata={"email": email, "reason": "invalid_credentials"},
            )
            self.db.commit()
            raise IdentityError(ErrorCode.INVALID_CREDENTIALS, "Invalid email or password.")

        self._assert_identity_active(user, ip_address, user_agent, request_id)

        session = self.sessions.create(user.id, ip_address=ip_address, user_agent=user_agent)
        issued = self.refresh_tokens.issue(session.id)
        context = self.resolver.from_user(
            user,
            auth_method=AuthMethod.PASSWORD,
            session_id=str(session.id),
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
        )
        access = self.tokens.create_access_token(context)
        self.events.record(
            AuthEventType.AUTH_LOGIN_SUCCESS,
            auth_method=AuthMethod.PASSWORD,
            identity_type=AuthIdentityType.HUMAN_USER.value,
            organization_id=user.organization_id,
            identity_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            metadata={"session_id": str(session.id)},
        )
        self.db.commit()
        return LoginResult(access, issued.token, session.id, context)

    # ------------------------------------------------------------------ #
    # Refresh with rotation + reuse detection (SRS §20)
    # ------------------------------------------------------------------ #
    def refresh(
        self,
        refresh_token: str,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
    ) -> RefreshResult:
        record = self.refresh_tokens.find(refresh_token)
        if record is None:
            raise IdentityError(ErrorCode.INVALID_CREDENTIALS, "Invalid refresh token.")

        if self.refresh_tokens.is_reuse(record):
            # Stale, already-rotated token replayed → possible theft (SRS §20).
            self.refresh_tokens.revoke_session_family(record.session_id)
            session = self.db.get(UserSession, record.session_id)
            if session is not None:
                session.revoked_at = session.revoked_at
            self.events.record(
                AuthEventType.REFRESH_TOKEN_REUSED,
                auth_method=AuthMethod.REFRESH_TOKEN,
                identity_type=AuthIdentityType.HUMAN_USER.value,
                request_id=request_id,
                ip_address=ip_address,
                metadata={"session_id": str(record.session_id)},
            )
            self.db.commit()
            raise IdentityError(
                ErrorCode.REFRESH_TOKEN_REUSED, "Refresh token reuse detected; please log in again."
            )

        if not self.refresh_tokens.is_valid(record):
            raise IdentityError(ErrorCode.TOKEN_REVOKED, "Refresh token is expired or revoked.")

        session = self.db.get(UserSession, record.session_id)
        if session is None or not self.sessions.is_active(session):
            raise IdentityError(ErrorCode.SESSION_REVOKED, "Session is no longer active.")

        user = self.db.get(User, session.user_id)
        if user is None:
            raise IdentityError(ErrorCode.INVALID_CREDENTIALS, "Identity no longer exists.")
        self._assert_identity_active(user, ip_address, user_agent, request_id)

        issued = self.refresh_tokens.rotate(record)
        self.sessions.touch(session)
        context = self.resolver.from_user(
            user, auth_method=AuthMethod.REFRESH_TOKEN, session_id=str(session.id)
        )
        access = self.tokens.create_access_token(context)
        self.events.record(
            AuthEventType.TOKEN_REFRESHED,
            auth_method=AuthMethod.REFRESH_TOKEN,
            identity_type=AuthIdentityType.HUMAN_USER.value,
            organization_id=user.organization_id,
            identity_id=user.id,
            request_id=request_id,
            metadata={"session_id": str(session.id)},
        )
        self.db.commit()
        return RefreshResult(access, issued.token, session.id)

    # ------------------------------------------------------------------ #
    # Logout (SRS §21)
    # ------------------------------------------------------------------ #
    def logout(self, session: UserSession, *, request_id: str | None = None) -> None:
        self.sessions.revoke(session)
        self.refresh_tokens.revoke_session_family(session.id)
        self.events.record(
            AuthEventType.AUTH_LOGOUT,
            auth_method=AuthMethod.JWT,
            identity_type=AuthIdentityType.HUMAN_USER.value,
            identity_id=session.user_id,
            request_id=request_id,
            metadata={"session_id": str(session.id)},
        )
        self.db.commit()

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    def _assert_identity_active(
        self, user: User, ip: str | None, ua: str | None, request_id: str | None
    ) -> None:
        active = user.is_active and user.status == IdentityStatus.ACTIVE.value
        if active:
            return
        code = (
            ErrorCode.IDENTITY_SUSPENDED
            if user.status == IdentityStatus.SUSPENDED.value
            else ErrorCode.IDENTITY_DISABLED
        )
        self.events.record(
            AuthEventType.AUTH_LOGIN_FAILED,
            auth_method=AuthMethod.PASSWORD,
            identity_type=AuthIdentityType.HUMAN_USER.value,
            organization_id=user.organization_id,
            identity_id=user.id,
            ip_address=ip,
            user_agent=ua,
            request_id=request_id,
            metadata={"reason": "identity_not_active", "status": user.status},
        )
        self.db.commit()
        raise IdentityError(code, "This identity is not permitted to authenticate.")
