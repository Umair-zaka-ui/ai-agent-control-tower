"""EmailChangeService — verified email change (4.2.2.3.3 §12).

Changing the address on an account is a takeover vector, so it is gated three ways:

1. Re-authentication — the current password must be supplied again.
2. Confirmation of the *new* address before it takes effect. Until then the current
   email stays authoritative, so a typo or a hostile request cannot lock the owner out.
3. An alert to the *old* address when the change completes — the mailbox an attacker
   does not control is where the alarm must ring.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import security as core_security
from app.core.config import settings
from app.identity.auth.enums import AuthEventType
from app.identity.email import EmailService
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.enums import EmailVerificationPurpose
from app.identity.models.registration import EmailVerification
from app.identity.recovery.audit import RecoveryAuditService, RecoveryContext
from app.identity.registration.tokens import generate_verification_token
from app.identity.repositories.registration_repositories import (
    EmailVerificationRepository,
    UserProfileRepository,
)
from app.models.user import User


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class EmailChangeService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = EmailVerificationRepository(db)
        self.profiles = UserProfileRepository(db)
        self.emails = EmailService()
        self.audit = RecoveryAuditService(db)
        self.ttl = timedelta(seconds=settings.EMAIL_CHANGE_TTL_SECONDS)

    # ------------------------------------------------------------------ #
    # Request a change (§12)
    # ------------------------------------------------------------------ #
    def request_change(
        self,
        user: User,
        *,
        new_email: str,
        current_password: str,
        context: RecoveryContext | None = None,
    ) -> None:
        """Re-authenticate, then send a confirmation link to the new address. Commits."""
        if not core_security.verify_password(current_password, user.password_hash):
            raise IdentityError(
                ErrorCode.INVALID_CURRENT_PASSWORD, "Your current password is incorrect."
            )

        normalized = new_email.strip().lower()
        if normalized == user.email.lower():
            raise IdentityError(
                ErrorCode.INVALID_RECOVERY_REQUEST, "That is already your email address."
            )
        # Case-insensitive uniqueness across all users (email is globally unique).
        taken = self.db.execute(
            select(User.id).where(func.lower(User.email) == normalized, User.id != user.id)
        ).scalars().first()
        if taken is not None:
            raise IdentityError(
                ErrorCode.EMAIL_ALREADY_IN_USE, "That email address is already in use."
            )

        # Supersede any outstanding EMAIL_CHANGE token — one pending change at a time.
        now = _now()
        for stale in self.repo.active_for_user(user.id):
            if stale.purpose == EmailVerificationPurpose.EMAIL_CHANGE.value:
                stale.superseded_at = now

        plaintext, hashed = generate_verification_token()
        verification = EmailVerification(
            user_id=user.id,
            verification_token_hash=hashed,
            expires_at=now + self.ttl,
            purpose=EmailVerificationPurpose.EMAIL_CHANGE.value,
            new_email=normalized,
            created_at=now,
        )
        self.repo.add(verification)
        user.pending_email = normalized
        self.db.flush()

        profile = self.profiles.get_for_user(user.id)
        result = self.emails.send_email_change_verification(
            normalized,
            first_name=profile.first_name if profile else None,
            token=plaintext,
            expires_in_hours=max(1, settings.EMAIL_CHANGE_TTL_SECONDS // 3600),
        )
        self.audit.record(
            AuthEventType.EMAIL_CHANGE_REQUESTED,
            organization_id=user.organization_id,
            user_id=user.id,
            target_email=normalized,
            context=context,
            metadata={"verification_id": str(verification.id), "delivered": result.sent},
        )
        self.db.commit()

    # ------------------------------------------------------------------ #
    # Confirm the new address (§12)
    # ------------------------------------------------------------------ #
    def verify_new_email(self, token: str, *, context: RecoveryContext | None = None) -> User:
        """Redeem an EMAIL_CHANGE token and swap the primary address. Commits."""
        verification = self.repo.get_by_token(token)
        if (
            verification is None
            or verification.purpose != EmailVerificationPurpose.EMAIL_CHANGE.value
        ):
            raise IdentityError(
                ErrorCode.INVALID_VERIFICATION_TOKEN, "This confirmation link is not valid."
            )
        if verification.verified_at is not None:
            raise IdentityError(
                ErrorCode.EMAIL_ALREADY_VERIFIED, "This email change was already confirmed."
            )
        if verification.superseded_at is not None:
            raise IdentityError(
                ErrorCode.INVALID_VERIFICATION_TOKEN,
                "A newer confirmation link was sent. Please use the most recent email.",
            )
        if _aware(verification.expires_at) <= _now():
            raise IdentityError(
                ErrorCode.EMAIL_VERIFICATION_EXPIRED,
                "This confirmation link has expired. Request the change again.",
            )

        user = self.db.get(User, verification.user_id)
        if user is None:  # pragma: no cover - FK cascade
            raise IdentityError(ErrorCode.USER_NOT_FOUND, "User does not exist.")

        new_email = verification.new_email or user.pending_email
        if not new_email:  # pragma: no cover - defensive
            raise IdentityError(ErrorCode.INVALID_RECOVERY_REQUEST, "No pending email change.")

        # Guard against the address having been taken since the request.
        taken = self.db.execute(
            select(User.id).where(func.lower(User.email) == new_email.lower(), User.id != user.id)
        ).scalars().first()
        if taken is not None:
            raise IdentityError(
                ErrorCode.EMAIL_ALREADY_IN_USE, "That email address is now in use by another account."
            )

        old_email = user.email
        user.email = new_email
        user.pending_email = None
        verification.verified_at = _now()
        self.db.flush()

        self.audit.record(
            AuthEventType.EMAIL_CHANGE_VERIFIED,
            organization_id=user.organization_id,
            user_id=user.id,
            target_email=new_email,
            context=context,
            metadata={"old_email": old_email},
        )
        self.audit.record(
            AuthEventType.EMAIL_CHANGED,
            organization_id=user.organization_id,
            user_id=user.id,
            target_email=new_email,
            context=context,
            metadata={"old_email": old_email},
        )
        # The alarm rings at the OLD mailbox — the one an attacker does not control.
        self.emails.send_email_changed_alert(old_email, new_email=new_email)
        self.db.commit()
        return user
