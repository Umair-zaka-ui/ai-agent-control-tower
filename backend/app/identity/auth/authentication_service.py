"""AuthenticationService — login / refresh / logout orchestration (SRS §16, §19–21).

Composes the credential, session, token, refresh-token and security-event
services. This is the enterprise login path (multi-identity, session-backed,
rotation + reuse detection); the legacy ``/auth/login`` route is untouched and
migrates onto this in a later subpart.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, needs_rehash
from app.identity.auth.context import IdentityContext
from app.identity.auth.credential_service import CredentialService
from app.identity.auth.enums import (
    AuthAssuranceLevel,
    AuthEventType,
    AuthIdentityType,
    AuthMethod,
    MfaMethod,
)
from app.identity.auth.login_history_service import LoginHistoryService
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
    session_id: uuid.UUID | None
    context: IdentityContext
    # Step-up (MFA) seam: when the identity/org requires a second factor, login
    # stops here — no session or refresh token is issued. The caller presents
    # ``mfa_challenge_token`` to ``complete_mfa`` to finish authentication.
    mfa_required: bool = False
    mfa_challenge_token: str | None = None


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
        self.login_history = LoginHistoryService(db)

    # ------------------------------------------------------------------ #
    # Human login (SRS §10, §19)
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
        # 1. Account lockout gate (SRS §10) — checked before touching credentials.
        if self.login_history.is_locked(email):
            self._record_locked(email, ip_address, user_agent, request_id)
            self.db.commit()
            raise IdentityError(
                ErrorCode.ACCOUNT_LOCKED,
                "Account temporarily locked due to repeated failed logins. Try again later.",
            )

        # 2. Credential verification (generic failure — never reveals existence).
        user = auth_service.authenticate_user(self.db, email, password)
        if user is None:
            self._record_failed_login(email, "invalid_credentials", ip_address, user_agent, request_id)
            self.db.commit()
            raise IdentityError(ErrorCode.INVALID_CREDENTIALS, "Invalid email or password.")

        self._assert_identity_active(user, ip_address, user_agent, request_id)

        # 3. Transparently upgrade a legacy bcrypt hash to argon2id (SRS §11).
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
            self.db.flush()

        # Step-up seam: if a second factor is required, stop before issuing a
        # session/refresh token and hand back a challenge instead (SRS §24).
        if self._mfa_required(user):
            return self._begin_mfa_challenge(user, ip_address, user_agent, request_id)

        session = self.sessions.create(user.id, ip_address=ip_address, user_agent=user_agent)
        issued = self.refresh_tokens.issue(session.id)
        context = self.resolver.from_user(
            user,
            auth_method=AuthMethod.PASSWORD,
            session_id=str(session.id),
            assurance_level=AuthAssuranceLevel.AAL1.value,
            amr=["pwd"],
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
        )
        access = self.tokens.create_access_token(context)
        self.login_history.record(
            email=email, success=True, user_id=user.id,
            ip_address=ip_address, user_agent=user_agent,
        )
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
    # Login-history / lockout helpers (SRS §10, §13)
    # ------------------------------------------------------------------ #
    def _user_id_for_email(self, email: str) -> uuid.UUID | None:
        user = self.db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        return user.id if user else None

    def _record_failed_login(
        self, email: str, reason: str, ip: str | None, ua: str | None, request_id: str | None
    ) -> None:
        """Record a failed attempt, emit AUTH_LOGIN_FAILED, and lock if the
        threshold is now crossed (SRS §10)."""
        user_id = self._user_id_for_email(email)
        self.login_history.record(
            email=email, success=False, user_id=user_id, failure_reason=reason,
            ip_address=ip, user_agent=ua,
        )
        self.events.record(
            AuthEventType.AUTH_LOGIN_FAILED,
            auth_method=AuthMethod.PASSWORD,
            identity_type=AuthIdentityType.HUMAN_USER.value,
            identity_id=user_id,
            ip_address=ip,
            user_agent=ua,
            request_id=request_id,
            metadata={"email": email, "reason": reason},
        )
        # This failure may itself trip the lockout threshold.
        if self.login_history.is_locked(email):
            self._record_locked(email, ip, ua, request_id, user_id=user_id)

    def _record_locked(
        self, email: str, ip: str | None, ua: str | None, request_id: str | None,
        *, user_id: uuid.UUID | None = None,
    ) -> None:
        self.events.record(
            AuthEventType.AUTH_LOGIN_LOCKED,
            auth_method=AuthMethod.PASSWORD,
            identity_type=AuthIdentityType.HUMAN_USER.value,
            identity_id=user_id if user_id is not None else self._user_id_for_email(email),
            ip_address=ip,
            user_agent=ua,
            request_id=request_id,
            metadata={"email": email, "reason": "account_locked"},
        )

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
            # Kill the whole session, not just the token family: the presenter of
            # a rotated token may be an attacker holding a stolen access token.
            self.refresh_tokens.revoke_session_family(record.session_id)
            session = self.db.get(UserSession, record.session_id)
            if session is not None and self.sessions.is_active(session):
                self.sessions.revoke(session)
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
        # Refresh preserves the session's assurance. Until sessions carry a
        # persisted ``assurance_level`` column (planned, see migration-plan.md),
        # a rotated token is re-minted at the single-factor level; the MFA branch
        # of login never reaches here because it issues no refresh token.
        context = self.resolver.from_user(
            user,
            auth_method=AuthMethod.REFRESH_TOKEN,
            session_id=str(session.id),
            assurance_level=AuthAssuranceLevel.AAL1.value,
            amr=["pwd"],
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
    # Step-up / multi-factor authentication (SRS §24)
    # ------------------------------------------------------------------ #
    def _mfa_required(self, user: User) -> bool:
        """Policy hook: does this identity/organization require a second factor?

        Enrollment state and org-level MFA policy land in a later subpart, so no
        identity is enrolled today and this returns ``False`` (login stays
        single-factor). The seam exists so enabling MFA is purely additive:
        flip this predicate and the challenge/verify path below activates without
        touching the token, context or authorization layers.
        """
        return False

    def _begin_mfa_challenge(
        self, user: User, ip: str | None, ua: str | None, request_id: str | None
    ) -> LoginResult:
        """Issue a short-lived, MFA-pending challenge token (assurance AAL0).

        The challenge proves only the primary factor; it carries ``mfa_pending``
        so authorization checks reject it until ``complete_mfa`` elevates it.
        """
        context = self.resolver.from_user(
            user,
            auth_method=AuthMethod.PASSWORD,
            assurance_level=AuthAssuranceLevel.AAL0.value,
            amr=["pwd"],
            mfa_pending=True,
            ip_address=ip,
            user_agent=ua,
            request_id=request_id,
        )
        challenge = self.tokens.create_access_token(
            context, ttl_seconds=settings.AUTH_MFA_CHALLENGE_TTL_SECONDS
        )
        self.events.record(
            AuthEventType.MFA_CHALLENGE_ISSUED,
            auth_method=AuthMethod.PASSWORD,
            identity_type=AuthIdentityType.HUMAN_USER.value,
            organization_id=user.organization_id,
            identity_id=user.id,
            ip_address=ip,
            user_agent=ua,
            request_id=request_id,
        )
        self.db.commit()
        return LoginResult(
            access_token="",
            refresh_token="",
            session_id=None,
            context=context,
            mfa_required=True,
            mfa_challenge_token=challenge,
        )

    def complete_mfa(
        self,
        challenge_token: str,
        method: MfaMethod,
        code: str,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
    ) -> LoginResult:
        """Second step of step-up login: verify the factor and elevate to AAL2.

        Factor verification is delegated to ``_verify_second_factor`` (whose
        concrete TOTP/WebAuthn/recovery implementation + secret store land in a
        later subpart). Everything around it — challenge validation, session +
        refresh-token issuance, assurance elevation and event recording — is
        wired here so turning MFA on is additive.
        """
        claims = self.tokens.validate_access_token(challenge_token)
        if not claims.get("mfa_pending"):
            raise IdentityError(ErrorCode.INVALID_CREDENTIALS, "Not a valid MFA challenge token.")

        user = self.db.get(User, uuid.UUID(str(claims["identity_id"])))
        if user is None:
            raise IdentityError(ErrorCode.INVALID_CREDENTIALS, "Identity no longer exists.")
        self._assert_identity_active(user, ip_address, user_agent, request_id)

        if not self._verify_second_factor(user, method, code):
            self.events.record(
                AuthEventType.MFA_FAILED,
                auth_method=AuthMethod.PASSWORD,
                identity_type=AuthIdentityType.HUMAN_USER.value,
                organization_id=user.organization_id,
                identity_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                request_id=request_id,
                metadata={"method": method.value},
            )
            self.db.commit()
            raise IdentityError(ErrorCode.MFA_REQUIRED, "Second-factor verification failed.")

        session = self.sessions.create(user.id, ip_address=ip_address, user_agent=user_agent)
        issued = self.refresh_tokens.issue(session.id)
        context = self.resolver.from_user(
            user,
            auth_method=AuthMethod.PASSWORD,
            session_id=str(session.id),
            assurance_level=AuthAssuranceLevel.AAL2.value,
            amr=["pwd", method.value.lower()],
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
        )
        access = self.tokens.create_access_token(context)
        self.events.record(
            AuthEventType.MFA_SUCCEEDED,
            auth_method=AuthMethod.PASSWORD,
            identity_type=AuthIdentityType.HUMAN_USER.value,
            organization_id=user.organization_id,
            identity_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            metadata={"method": method.value, "session_id": str(session.id)},
        )
        self.db.commit()
        return LoginResult(access, issued.token, session.id, context)

    def _verify_second_factor(self, user: User, method: MfaMethod, code: str) -> bool:
        """Delegates to the (future) MFA verifier + secret store.

        No factor is enrolled in Part 4.2.1, so this returns ``False``; the
        concrete verifier lands with the ``mfa_enrollments`` table (see
        migration-plan.md). Tests exercise the elevation path by overriding it.
        """
        return False

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
