"""PasswordResetService — the forgot-password / reset flow (4.2.2.3.3 §9, §10, §19).

Two operations:

- ``request_reset(email)`` — always succeeds from the caller's point of view (§9);
  only if the account exists *and* has a real password does it mint a token and send
  a mail. Enumeration is impossible: the endpoint's response and timing do not depend
  on whether the address is known.
- ``reset(token, new_password)`` — validates the single-use token, sets the new
  password through the credential write path (policy + no-reuse + argon2id + history),
  revokes every session (§13), marks the token used, and alerts the user by email.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import security as core_security
from app.core.config import settings
from app.identity.auth.enums import AuthEventType
from app.identity.credentials.audit import CredentialContext
from app.identity.credentials.service import CredentialService, _no_revoke
from app.identity.email import EmailService
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.enums import PasswordResetStatus
from app.identity.models.recovery import PasswordResetRequest
from app.identity.recovery.audit import RecoveryAuditService, RecoveryContext
from app.identity.recovery.repository import PasswordResetRepository
from app.identity.registration.tokens import generate_reset_token
from app.identity.repositories.registration_repositories import UserProfileRepository
from app.models.user import User

SessionRevoker = Callable[[uuid.UUID, str], int]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class PasswordResetService:
    def __init__(self, db: Session, *, revoke_sessions: SessionRevoker | None = None) -> None:
        self.db = db
        self.repo = PasswordResetRepository(db)
        self.profiles = UserProfileRepository(db)
        self.emails = EmailService()
        self.audit = RecoveryAuditService(db)
        self.credentials = CredentialService(db, revoke_sessions=revoke_sessions or _no_revoke)
        self.ttl = timedelta(seconds=settings.PASSWORD_RESET_TTL_SECONDS)

    # ------------------------------------------------------------------ #
    # Request (§9) — always uniform, never an existence oracle
    # ------------------------------------------------------------------ #
    def request_reset(self, email: str, *, context: RecoveryContext | None = None) -> None:
        """Mint + send a reset token if the address maps to a real account. Commits.

        Returns nothing: the route answers identically whatever happened here.
        """
        if not settings.PASSWORD_RESET_ENABLED:
            raise IdentityError(
                ErrorCode.PASSWORD_RESET_DISABLED, "Password reset is disabled for this deployment."
            )

        normalized = email.strip().lower()
        user = self.db.execute(select(User).where(User.email == normalized)).scalars().first()

        # No account, or an SSO/SCIM identity with no password to reset → do nothing,
        # silently. The caller cannot tell this apart from success.
        if user is None or core_security.is_unusable_password(user.password_hash):
            self.db.commit()
            return

        # Supersede any outstanding request: a fresh link must invalidate the old one,
        # or "single use" becomes "N concurrent valid links" (§9).
        for old in self.repo.active_for_user(user.id):
            old.status = PasswordResetStatus.REVOKED.value
            self.audit.record(
                AuthEventType.RECOVERY_REQUEST_REVOKED,
                organization_id=user.organization_id,
                user_id=user.id,
                target_email=user.email,
                context=context,
                metadata={"request_id": str(old.id), "reason": "superseded"},
            )

        plaintext, hashed = generate_reset_token()
        now = _now()
        request = PasswordResetRequest(
            user_id=user.id,
            organization_id=user.organization_id,
            token_hash=hashed,
            status=PasswordResetStatus.PENDING.value,
            expires_at=now + self.ttl,
            created_ip=context.ip_address if context else None,
            created_user_agent=(context.user_agent if context else None),
            created_at=now,
        )
        self.repo.add(request)
        self.db.flush()

        profile = self.profiles.get_for_user(user.id)
        result = self.emails.send_password_reset(
            user.email,
            first_name=profile.first_name if profile else None,
            token=plaintext,
            expires_in_minutes=max(1, settings.PASSWORD_RESET_TTL_SECONDS // 60),
        )
        self.audit.record(
            AuthEventType.PASSWORD_RESET_REQUESTED,
            organization_id=user.organization_id,
            user_id=user.id,
            target_email=user.email,
            context=context,
            metadata={"request_id": str(request.id), "delivered": result.sent},
        )
        self.db.commit()

    # ------------------------------------------------------------------ #
    # Reset (§10) — single-use token, full credential discipline
    # ------------------------------------------------------------------ #
    def reset(
        self, token: str, new_password: str, *, context: RecoveryContext | None = None
    ) -> User:
        """Validate the token and set the new password. Commits.

        Distinguishes invalid / expired / used, because each has a different next
        step: a used or expired link means "request a new one"; an invalid one is a
        typo or an attack. Possession of the unguessable token already proves the
        holder received the email, so naming the reason reveals nothing.
        """
        request = self.repo.get_by_token(token)
        if request is None:
            self.audit.record(
                AuthEventType.PASSWORD_RESET_FAILED,
                organization_id=None,
                user_id=None,
                context=context,
                metadata={"reason": "token_not_found"},
            )
            self.db.commit()
            raise IdentityError(ErrorCode.RESET_TOKEN_INVALID, "This reset link is not valid.")

        # Materialise expiry on read — the clock decides, and the audit list and the
        # reset path must never disagree (same discipline as invitations).
        status = PasswordResetStatus(request.status)
        if status is PasswordResetStatus.PENDING and _aware(request.expires_at) <= _now():
            request.status = PasswordResetStatus.EXPIRED.value
            self.audit.record(
                AuthEventType.RECOVERY_REQUEST_EXPIRED,
                organization_id=request.organization_id,
                user_id=request.user_id,
                context=context,
                metadata={"request_id": str(request.id)},
            )
            status = PasswordResetStatus.EXPIRED

        if status is PasswordResetStatus.USED:
            self._fail(request, context, "token_used")
            raise IdentityError(ErrorCode.RESET_TOKEN_USED, "This reset link has already been used.")
        if status is PasswordResetStatus.EXPIRED:
            self._fail(request, context, "token_expired")
            raise IdentityError(
                ErrorCode.RESET_TOKEN_EXPIRED, "This reset link has expired. Request a new one."
            )
        if status is PasswordResetStatus.REVOKED:
            self._fail(request, context, "token_revoked")
            raise IdentityError(
                ErrorCode.RESET_TOKEN_INVALID,
                "A newer reset link was issued. Please use the most recent email.",
            )

        user = self.db.get(User, request.user_id)
        if user is None:  # pragma: no cover - FK cascade makes this unreachable
            raise IdentityError(ErrorCode.INVALID_RECOVERY_REQUEST, "Account no longer exists.")

        # Set the password through the credential write path (policy + no-reuse +
        # argon2id + history + lifecycle stamp), then revoke every session (§13).
        try:
            self.credentials.apply_recovery_reset(
                user,
                new_password,
                context=CredentialContext(
                    ip_address=context.ip_address if context else None,
                    user_agent=context.user_agent if context else None,
                    request_id=context.request_id if context else None,
                ),
                event=AuthEventType.PASSWORD_RESET_COMPLETED,
            )
        except IdentityError:
            # apply_recovery_reset committed its own audit for the policy/reuse failure;
            # record the recovery-level failure too, but leave the token PENDING so the
            # user can retry with a compliant password on the same link.
            self.audit.record(
                AuthEventType.PASSWORD_RESET_FAILED,
                organization_id=user.organization_id,
                user_id=user.id,
                target_email=user.email,
                context=context,
                metadata={"request_id": str(request.id), "reason": "password_rejected"},
            )
            self.db.commit()
            raise

        request.status = PasswordResetStatus.USED.value
        request.used_at = _now()
        # Any other pending request for this user is now moot.
        for other in self.repo.active_for_user(user.id):
            if other.id != request.id:
                other.status = PasswordResetStatus.REVOKED.value

        self.emails.send_password_changed_alert(user.email)
        self.db.commit()
        return user

    def _fail(
        self, request: PasswordResetRequest, context: RecoveryContext | None, reason: str
    ) -> None:
        self.audit.record(
            AuthEventType.PASSWORD_RESET_FAILED,
            organization_id=request.organization_id,
            user_id=request.user_id,
            context=context,
            metadata={"request_id": str(request.id), "reason": reason},
        )
        self.db.commit()

    # ------------------------------------------------------------------ #
    # Maintenance (§26) — automatic cleanup of stale requests
    # ------------------------------------------------------------------ #
    def expire_stale(self, *, organization_id: uuid.UUID | None = None, limit: int = 500) -> int:
        """Mark PENDING requests past their deadline EXPIRED. Bounded; does not commit."""
        count = 0
        for request in self.repo.list_expired_pending(
            _now(), organization_id=organization_id, limit=limit
        ):
            request.status = PasswordResetStatus.EXPIRED.value
            self.audit.record(
                AuthEventType.RECOVERY_REQUEST_EXPIRED,
                organization_id=request.organization_id,
                user_id=request.user_id,
                metadata={"request_id": str(request.id), "reaped": True},
            )
            count += 1
        return count
