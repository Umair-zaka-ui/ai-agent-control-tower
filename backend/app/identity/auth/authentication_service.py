"""AuthenticationService — login / refresh / logout orchestration (SRS §16, §19–21).

Composes the credential, session-lifecycle, device, token, refresh-rotation,
security and event services. This is the enterprise login path (multi-identity,
session-backed, rotation + reuse detection); the legacy ``/auth/login`` route is
untouched and migrates onto this later.

Phase 4.2.2.2 makes the **session** the source of truth: login registers a device,
scores the session, enforces the concurrent-session limit, and every subsequent
request revalidates the session (see ``dependency.authenticate``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, needs_rehash
from app.identity.auth.context import IdentityContext
from app.identity.auth.credential_service import CredentialService
from app.identity.auth.device_service import DeviceService, parse_user_agent
from app.identity.auth.enums import (
    AuthAssuranceLevel,
    AuthEventType,
    AuthIdentityType,
    AuthMethod,
    MfaMethod,
)
from app.identity.auth.login_history_service import LoginHistoryService
from app.identity.auth.refresh_rotation_service import RefreshRotationService
from app.identity.auth.resolver import IdentityContextResolver
from app.identity.auth.security_event_service import SecurityEventService
from app.identity.auth.session_lifecycle_service import SessionLifecycleService
from app.identity.auth.session_security_service import SessionSecurityService
from app.identity.auth.token_service import TokenService
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.enums import IdentityStatus, SessionRevocationReason
from app.identity.models.session import UserSession
from app.models.user import User
from app.services import auth_service


@dataclass
class RequestClient:
    """Everything we know about the caller's client for one request."""

    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    device_id_header: str | None = None
    country: str | None = None
    city: str | None = None
    timezone_name: str | None = None


@dataclass
class LoginResult:
    access_token: str
    refresh_token: str
    session_id: uuid.UUID | None
    context: IdentityContext
    # Step-up (MFA) seam: when the identity/org requires a second factor, login
    # stops here — no session or refresh token is issued.
    mfa_required: bool = False
    mfa_challenge_token: str | None = None
    # Security posture surfaced to the client (SRS §15).
    security_score: int = 100
    is_new_device: bool = False
    revoked_sessions: list[uuid.UUID] = field(default_factory=list)
    # Credential posture (Part 4.2.2.3.2 §11, §13): the SPA must route the user to
    # the change-password flow before any feature when this is set — an expired or
    # temporary/admin-reset password grants a session but no access to the app.
    password_change_required: bool = False


@dataclass
class RefreshResult:
    access_token: str
    refresh_token: str
    session_id: uuid.UUID


class AuthenticationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.credentials = CredentialService()
        self.sessions = SessionLifecycleService(db)
        self.devices = DeviceService(db)
        self.tokens = TokenService(db)
        self.refresh_tokens = RefreshRotationService(db)
        self.events = SecurityEventService(db)
        self.resolver = IdentityContextResolver(db)
        self.login_history = LoginHistoryService(db)
        self.security = SessionSecurityService(db)

    # ------------------------------------------------------------------ #
    # Human login (SRS §5, §10, §19)
    # ------------------------------------------------------------------ #
    def login(
        self,
        email: str,
        password: str,
        *,
        client: RequestClient | None = None,
        remember_me: bool = False,
        # Back-compat keyword form used by existing callers/tests.
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
    ) -> LoginResult:
        client = client or RequestClient(
            ip_address=ip_address, user_agent=user_agent, request_id=request_id
        )
        ip, ua, rid = client.ip_address, client.user_agent, client.request_id

        # 1. Account lockout gate (SRS §10) — before touching credentials, so a
        #    locked account cannot be used to burn argon2id CPU.
        if self.login_history.is_locked(email):
            self._record_locked(email, ip, ua, rid)
            self.db.commit()
            raise IdentityError(
                ErrorCode.ACCOUNT_LOCKED,
                "Account temporarily locked due to repeated failed logins. Try again later.",
            )

        # 2. Credential verification (generic failure — never reveals existence).
        user = auth_service.authenticate_user(self.db, email, password)
        if user is None:
            self._record_failed_login(email, "invalid_credentials", ip, ua, rid)
            self.db.commit()
            raise IdentityError(ErrorCode.INVALID_CREDENTIALS, "Invalid email or password.")

        self._assert_identity_active(user, ip, ua, rid)

        # 3. Transparently upgrade a legacy bcrypt hash to argon2id (SRS §11).
        #    Deliberately skips policy validation: the password is already correct,
        #    and a user whose password predates the policy must still be able in.
        #    A silent upgrade *is* a credential rotation, so it is audited as one
        #    (Part 4.2.2.3.2 §18) — otherwise the event would be dead.
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
            self.db.flush()
            self.events.record(
                AuthEventType.PASSWORD_ROTATED,
                auth_method=AuthMethod.PASSWORD,
                identity_type=AuthIdentityType.HUMAN_USER.value,
                organization_id=user.organization_id,
                identity_id=user.id,
                ip_address=ip,
                user_agent=ua,
                request_id=rid,
                metadata={"reason": "hash_upgrade"},
            )

        # 4. Device registration + block check (SRS §13, §14).
        device, is_new_device = self.devices.register_or_touch(
            user.id, user_agent=ua, ip_address=ip, device_id_header=client.device_id_header
        )
        if device.blocked:
            self.events.record(
                AuthEventType.DEVICE_BLOCKED,
                auth_method=AuthMethod.PASSWORD,
                identity_type=AuthIdentityType.HUMAN_USER.value,
                organization_id=user.organization_id,
                identity_id=user.id,
                ip_address=ip,
                user_agent=ua,
                request_id=rid,
                metadata={"device_id": str(device.id), "reason": "device_blocked"},
            )
            self.login_history.record(
                email=email, success=False, user_id=user.id,
                failure_reason="device_blocked", ip_address=ip, user_agent=ua,
            )
            self.db.commit()
            raise IdentityError(
                ErrorCode.DEVICE_BLOCKED, "This device is blocked from signing in."
            )
        if is_new_device:
            self.events.record(
                AuthEventType.DEVICE_REGISTERED,
                auth_method=AuthMethod.PASSWORD,
                identity_type=AuthIdentityType.HUMAN_USER.value,
                organization_id=user.organization_id,
                identity_id=user.id,
                ip_address=ip,
                user_agent=ua,
                request_id=rid,
                metadata={"device_id": str(device.id), "device_name": device.device_name},
            )

        # 5. Step-up seam: stop before issuing a session if MFA is required.
        if self._mfa_required(user):
            return self._begin_mfa_challenge(user, ip, ua, rid)

        # 6. Risk score (SRS §15).
        assessment = self.security.assess_login(
            user.id, device=device, is_new_device=is_new_device, country=client.country
        )

        # 7. Concurrent-session limit, evaluated BEFORE creating the new session
        #    so the user ends up at the limit, not one over it (SRS §11).
        evicted = self.sessions.enforce_session_limit(user.id)
        for old in evicted:
            self.refresh_tokens.revoke_family(old.refresh_token_family_id)
            self.events.record(
                AuthEventType.SESSION_LIMIT_EXCEEDED,
                auth_method=AuthMethod.PASSWORD,
                identity_type=AuthIdentityType.HUMAN_USER.value,
                organization_id=user.organization_id,
                identity_id=user.id,
                request_id=rid,
                metadata={"revoked_session_id": str(old.id), "limit": settings.SESSION_MAX_CONCURRENT},
            )

        # 8. Create the session and its refresh-token family (SRS §5, §7).
        info = parse_user_agent(ua)
        session = self.sessions.create(
            user.id,
            organization_id=user.organization_id,
            device_id=device.id,
            device_name=device.device_name,
            device_type=device.device_type,
            browser=info.browser,
            browser_version=info.browser_version,
            operating_system=info.operating_system,
            ip_address=ip,
            user_agent=ua,
            country=client.country,
            city=client.city,
            timezone_name=client.timezone_name,
            login_method=AuthMethod.PASSWORD.value,
            remember_me=remember_me,
            security_score=assessment.score,
            is_trusted=device.trusted,
        )
        issued = self.refresh_tokens.issue(session.id, session.refresh_token_family_id)

        context = self.resolver.from_user(
            user,
            auth_method=AuthMethod.PASSWORD,
            session_id=str(session.id),
            assurance_level=AuthAssuranceLevel.AAL1.value,
            amr=["pwd"],
            ip_address=ip,
            user_agent=ua,
            request_id=rid,
        )
        access = self.tokens.create_access_token(context)

        self.login_history.record(
            email=email, success=True, user_id=user.id,
            ip_address=ip, user_agent=ua, country=client.country, city=client.city,
        )
        self.events.record(
            AuthEventType.SESSION_CREATED,
            auth_method=AuthMethod.PASSWORD,
            identity_type=AuthIdentityType.HUMAN_USER.value,
            organization_id=user.organization_id,
            identity_id=user.id,
            ip_address=ip,
            user_agent=ua,
            request_id=rid,
            metadata={
                "session_id": str(session.id),
                "device_id": str(device.id),
                "security_score": assessment.score,
                "signals": assessment.signals,
                "remember_me": remember_me,
            },
        )
        self.events.record(
            AuthEventType.AUTH_LOGIN_SUCCESS,
            auth_method=AuthMethod.PASSWORD,
            identity_type=AuthIdentityType.HUMAN_USER.value,
            organization_id=user.organization_id,
            identity_id=user.id,
            ip_address=ip,
            user_agent=ua,
            request_id=rid,
            metadata={"session_id": str(session.id)},
        )
        if assessment.signals:
            self.events.record(
                AuthEventType.SUSPICIOUS_LOGIN,
                auth_method=AuthMethod.PASSWORD,
                identity_type=AuthIdentityType.HUMAN_USER.value,
                organization_id=user.organization_id,
                identity_id=user.id,
                ip_address=ip,
                user_agent=ua,
                request_id=rid,
                metadata={"signals": assessment.signals, "security_score": assessment.score},
            )
        # Credential posture (Part 4.2.2.3.2 §11, §13). An expired or temporary
        # password does not block *login* — it blocks *access*, which the SPA
        # enforces by routing to the change-password flow. Emitting PASSWORD_EXPIRED
        # here (not at the change) is what makes an expiry visible in the audit
        # stream the moment it bites.
        from app.identity.credentials.policy_service import PasswordPolicyService

        change_required = PasswordPolicyService.change_required(user)
        if PasswordPolicyService.is_expired(user):
            self.events.record(
                AuthEventType.PASSWORD_EXPIRED,
                auth_method=AuthMethod.PASSWORD,
                identity_type=AuthIdentityType.HUMAN_USER.value,
                organization_id=user.organization_id,
                identity_id=user.id,
                ip_address=ip,
                user_agent=ua,
                request_id=rid,
                metadata={"session_id": str(session.id)},
            )

        self.db.commit()
        return LoginResult(
            access,
            issued.token,
            session.id,
            context,
            security_score=assessment.score,
            is_new_device=is_new_device,
            revoked_sessions=[s.id for s in evicted],
            password_change_required=change_required,
        )

    # ------------------------------------------------------------------ #
    # Login-history / lockout helpers (SRS §10, §13)
    # ------------------------------------------------------------------ #
    def _user_id_for_email(self, email: str) -> uuid.UUID | None:
        user = self.db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        return user.id if user else None

    def _record_failed_login(
        self, email: str, reason: str, ip: str | None, ua: str | None, request_id: str | None
    ) -> None:
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
    # Refresh with rotation + reuse detection (SRS §8, §9, §20)
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
            raise IdentityError(ErrorCode.INVALID_REFRESH_TOKEN, "Invalid refresh token.")

        if self.refresh_tokens.is_reuse(record):
            self._handle_token_reuse(record, ip_address, user_agent, request_id)

        if not self.refresh_tokens.is_valid(record):
            raise IdentityError(ErrorCode.TOKEN_REVOKED, "Refresh token is expired or revoked.")

        session = self.db.get(UserSession, record.session_id)
        if session is None:
            raise IdentityError(ErrorCode.SESSION_NOT_FOUND, "Session does not exist.")
        # A refresh is activity: it must respect idle + absolute timeouts too.
        self.sessions.assert_usable(session)

        user = self.db.get(User, session.user_id)
        if user is None:
            raise IdentityError(ErrorCode.INVALID_CREDENTIALS, "Identity no longer exists.")
        self._assert_identity_active(user, ip_address, user_agent, request_id)

        issued = self.refresh_tokens.rotate(record)
        self.sessions.touch(session)

        context = self.resolver.from_user(
            user,
            auth_method=AuthMethod.REFRESH_TOKEN,
            session_id=str(session.id),
            assurance_level=AuthAssuranceLevel.AAL1.value,
            amr=["pwd"],
        )
        access = self.tokens.create_access_token(context)
        self.events.record(
            AuthEventType.TOKEN_ROTATED,
            auth_method=AuthMethod.REFRESH_TOKEN,
            identity_type=AuthIdentityType.HUMAN_USER.value,
            organization_id=user.organization_id,
            identity_id=user.id,
            request_id=request_id,
            metadata={"session_id": str(session.id), "family_id": str(record.family_id)},
        )
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

    def _handle_token_reuse(
        self,
        record,
        ip_address: str | None,
        user_agent: str | None,
        request_id: str | None,
    ) -> None:
        """A stale, already-rotated token was replayed → assume theft (SRS §9).

        Kill the whole family and the session. Marking the session SUSPICIOUS
        (not merely REVOKED) preserves *why* it died for the incident review.
        """
        self.refresh_tokens.mark_reuse(record)
        self.refresh_tokens.revoke_family(record.family_id)
        session = self.db.get(UserSession, record.session_id)
        if session is not None:
            self.security.flag_token_reuse(session)
        for event in (AuthEventType.TOKEN_REUSE_DETECTED, AuthEventType.REFRESH_TOKEN_REUSED):
            self.events.record(
                event,
                auth_method=AuthMethod.REFRESH_TOKEN,
                identity_type=AuthIdentityType.HUMAN_USER.value,
                organization_id=session.organization_id if session else None,
                identity_id=session.user_id if session else None,
                request_id=request_id,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={
                    "session_id": str(record.session_id),
                    "family_id": str(record.family_id),
                    "token_id": str(record.id),
                },
            )
        self.db.commit()
        raise IdentityError(
            ErrorCode.REFRESH_TOKEN_REUSED, "Refresh token reuse detected; please log in again."
        )

    # ------------------------------------------------------------------ #
    # Logout (SRS §16, §21)
    # ------------------------------------------------------------------ #
    def logout(
        self,
        session: UserSession,
        *,
        reason: SessionRevocationReason = SessionRevocationReason.USER_LOGOUT,
        request_id: str | None = None,
    ) -> None:
        self.sessions.revoke(session, reason)
        self.refresh_tokens.revoke_family(session.refresh_token_family_id)
        self.events.record(
            AuthEventType.SESSION_REVOKED,
            auth_method=AuthMethod.JWT,
            identity_type=AuthIdentityType.HUMAN_USER.value,
            organization_id=session.organization_id,
            identity_id=session.user_id,
            request_id=request_id,
            metadata={"session_id": str(session.id), "reason": reason.value},
        )
        self.events.record(
            AuthEventType.AUTH_LOGOUT,
            auth_method=AuthMethod.JWT,
            identity_type=AuthIdentityType.HUMAN_USER.value,
            organization_id=session.organization_id,
            identity_id=session.user_id,
            request_id=request_id,
            metadata={"session_id": str(session.id)},
        )
        self.db.commit()

    def logout_all(
        self,
        user_id: uuid.UUID,
        *,
        except_session_id: uuid.UUID | None = None,
        reason: SessionRevocationReason = SessionRevocationReason.USER_LOGOUT,
        request_id: str | None = None,
    ) -> list[uuid.UUID]:
        """Revoke every active session for a user, optionally keeping the current
        one (the "log out my other devices" action). Returns the revoked ids."""
        revoked: list[uuid.UUID] = []
        for session in self.sessions.list_active(user_id):
            if except_session_id is not None and session.id == except_session_id:
                continue
            self.sessions.revoke(session, reason)
            self.refresh_tokens.revoke_family(session.refresh_token_family_id)
            self.events.record(
                AuthEventType.SESSION_REVOKED,
                auth_method=AuthMethod.JWT,
                identity_type=AuthIdentityType.HUMAN_USER.value,
                organization_id=session.organization_id,
                identity_id=session.user_id,
                request_id=request_id,
                metadata={"session_id": str(session.id), "reason": reason.value},
            )
            revoked.append(session.id)
        self.db.commit()
        return revoked

    def revoke_session(
        self,
        session: UserSession,
        reason: SessionRevocationReason,
        *,
        actor_id: uuid.UUID | None = None,
        request_id: str | None = None,
    ) -> UserSession:
        """Force-logout one session (SRS §17). Used by the owner and by admins."""
        self.sessions.revoke(session, reason)
        self.refresh_tokens.revoke_family(session.refresh_token_family_id)
        self.events.record(
            AuthEventType.SESSION_REVOKED,
            auth_method=AuthMethod.JWT,
            identity_type=AuthIdentityType.HUMAN_USER.value,
            organization_id=session.organization_id,
            identity_id=session.user_id,
            request_id=request_id,
            metadata={
                "session_id": str(session.id),
                "reason": reason.value,
                "actor_id": str(actor_id) if actor_id else None,
            },
        )
        self.db.commit()
        return session

    # ------------------------------------------------------------------ #
    # Step-up / multi-factor authentication (SRS §24)
    # ------------------------------------------------------------------ #
    def _mfa_required(self, user: User) -> bool:
        """Policy hook: does this identity/organization require a second factor?

        Enrollment state and org-level MFA policy land in a later subpart, so no
        identity is enrolled today and this returns ``False``. The seam exists so
        enabling MFA is purely additive.
        """
        return False

    def _begin_mfa_challenge(
        self, user: User, ip: str | None, ua: str | None, request_id: str | None
    ) -> LoginResult:
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
        """Second step of step-up login: verify the factor and elevate to AAL2."""
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

        device, _ = self.devices.register_or_touch(
            user.id, user_agent=user_agent, ip_address=ip_address
        )
        self.sessions.enforce_session_limit(user.id)
        info = parse_user_agent(user_agent)
        session = self.sessions.create(
            user.id,
            organization_id=user.organization_id,
            device_id=device.id,
            device_name=device.device_name,
            device_type=device.device_type,
            browser=info.browser,
            browser_version=info.browser_version,
            operating_system=info.operating_system,
            ip_address=ip_address,
            user_agent=user_agent,
            login_method=AuthMethod.PASSWORD.value,
            is_trusted=device.trusted,
        )
        issued = self.refresh_tokens.issue(session.id, session.refresh_token_family_id)
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
        """Delegates to the (future) MFA verifier + secret store. No factor is
        enrolled yet, so this returns ``False``; tests override it."""
        return False

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    # Why an identity cannot sign in. An onboarding user must not be told
    # "this identity is not permitted to authenticate" — they need to know their
    # email is unverified, or that an administrator has not approved them yet.
    # Both are actionable; "disabled" is not.
    _INACTIVE_REASONS: dict[str, str] = {
        IdentityStatus.SUSPENDED.value: ErrorCode.IDENTITY_SUSPENDED,
        IdentityStatus.INVITED.value: ErrorCode.EMAIL_NOT_VERIFIED,
        IdentityStatus.REGISTERED.value: ErrorCode.EMAIL_NOT_VERIFIED,
        IdentityStatus.EMAIL_PENDING.value: ErrorCode.EMAIL_NOT_VERIFIED,
        IdentityStatus.EMAIL_VERIFIED.value: ErrorCode.ACCOUNT_PENDING_APPROVAL,
        IdentityStatus.PENDING_VERIFICATION.value: ErrorCode.EMAIL_NOT_VERIFIED,
    }

    _INACTIVE_MESSAGES: dict[str, str] = {
        ErrorCode.EMAIL_NOT_VERIFIED: (
            "Confirm your email address before signing in. Check your inbox, or request a new link."
        ),
        ErrorCode.ACCOUNT_PENDING_APPROVAL: (
            "Your email is confirmed. An administrator must approve your account before you can sign in."
        ),
        ErrorCode.IDENTITY_SUSPENDED: "This identity is not permitted to authenticate.",
        ErrorCode.IDENTITY_DISABLED: "This identity is not permitted to authenticate.",
    }

    def _assert_identity_active(
        self, user: User, ip: str | None, ua: str | None, request_id: str | None
    ) -> None:
        active = user.is_active and user.status == IdentityStatus.ACTIVE.value
        if active:
            return
        code = self._INACTIVE_REASONS.get(user.status, ErrorCode.IDENTITY_DISABLED)
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
        raise IdentityError(
            code,
            self._INACTIVE_MESSAGES.get(code, "This identity is not permitted to authenticate."),
        )
