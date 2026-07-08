"""EmailVerificationService — issue, validate, redeem (4.2.2.3.1 §7, §12).

Token lifetime 24 hours. Single use. Hashed at rest. A resend **supersedes** every
outstanding token for that user rather than adding another one — otherwise "single
use" quietly becomes "N simultaneous valid links", and a token leaked from an old
email would stay redeemable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.identity.auth.enums import AuthEventType
from app.identity.email import EmailService
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.registration import EmailVerification
from app.identity.registration.audit import RegistrationAuditService, RequestContext
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


@dataclass
class IssuedVerification:
    verification: EmailVerification
    token: str
    email_sent: bool


class EmailVerificationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = EmailVerificationRepository(db)
        self.profiles = UserProfileRepository(db)
        self.emails = EmailService()
        self.audit = RegistrationAuditService(db)
        self.ttl = timedelta(seconds=settings.EMAIL_VERIFICATION_TTL_SECONDS)

    # ------------------------------------------------------------------ #
    # Issue (§12)
    # ------------------------------------------------------------------ #
    def issue(
        self, user: User, *, context: RequestContext | None = None, send: bool = True
    ) -> IssuedVerification:
        """Mint a token, superseding any outstanding one. Does not commit."""
        if self.repo.has_verified(user.id):
            raise IdentityError(
                ErrorCode.EMAIL_ALREADY_VERIFIED, "This email address is already verified."
            )

        now = _now()
        for stale in self.repo.active_for_user(user.id):
            stale.superseded_at = now

        plaintext, hashed = generate_verification_token()
        verification = EmailVerification(
            user_id=user.id,
            verification_token_hash=hashed,
            expires_at=now + self.ttl,
            created_at=now,
        )
        self.repo.add(verification)

        sent = False
        if send:
            profile = self.profiles.get_for_user(user.id)
            result = self.emails.send_verification(
                user.email,
                first_name=profile.first_name if profile else None,
                token=plaintext,
                expires_in_hours=max(1, settings.EMAIL_VERIFICATION_TTL_SECONDS // 3600),
            )
            sent = result.sent
            self.audit.record(
                AuthEventType.EMAIL_VERIFICATION_SENT,
                organization_id=user.organization_id,
                target_email=user.email,
                actor_id=user.id,
                context=context,
                metadata={"verification_id": str(verification.id), "delivered": sent},
            )

        return IssuedVerification(verification, plaintext, sent)

    # ------------------------------------------------------------------ #
    # Redeem (§12)
    # ------------------------------------------------------------------ #
    def redeem(self, plaintext: str, *, context: RequestContext | None = None) -> User:
        """Validate a token and mark the address verified. Does not commit.

        Distinguishes *expired* from *invalid*: an expired token can be resent, an
        invalid one is either a typo or an attack. A single generic error would tell
        an honest user to give up.
        """
        verification = self.repo.get_by_token(plaintext)
        if verification is None:
            raise IdentityError(
                ErrorCode.INVALID_VERIFICATION_TOKEN, "This verification link is not valid."
            )
        if verification.verified_at is not None:
            raise IdentityError(
                ErrorCode.EMAIL_ALREADY_VERIFIED, "This email address is already verified."
            )
        if verification.superseded_at is not None:
            # A newer link was sent. This one is not "invalid" in a way the user caused.
            raise IdentityError(
                ErrorCode.INVALID_VERIFICATION_TOKEN,
                "A newer verification link was sent. Please use the most recent email.",
            )
        if _aware(verification.expires_at) <= _now():
            raise IdentityError(
                ErrorCode.VERIFICATION_TOKEN_EXPIRED,
                "This verification link has expired. Request a new one.",
            )

        user = self.db.get(User, verification.user_id)
        if user is None:  # pragma: no cover - FK cascade makes this unreachable
            raise IdentityError(ErrorCode.USER_NOT_FOUND, "User does not exist.")

        verification.verified_at = _now()
        self.db.flush()
        self.audit.record(
            AuthEventType.EMAIL_VERIFIED,
            organization_id=user.organization_id,
            target_email=user.email,
            actor_id=user.id,
            context=context,
            metadata={"verification_id": str(verification.id)},
        )
        return user

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    def is_verified(self, user_id: uuid.UUID) -> bool:
        return self.repo.has_verified(user_id)

    def latest_for_user(self, user_id: uuid.UUID) -> EmailVerification | None:
        return self.repo.latest_for_user(user_id)
