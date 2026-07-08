"""Repositories for invitations, email verifications and user profiles (§5).

Lookup is always **by token hash**. The plaintext token exists in exactly two places:
the email that was sent, and the URL the user clicks. It is never stored, never
logged, and never compared in Python.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from app.identity.models.enums import InvitationStatus
from app.identity.models.registration import EmailVerification, Invitation, UserProfile
from app.identity.repositories.base import BaseRepository
from app.identity.security.passwords import hash_secret


class InvitationRepository(BaseRepository[Invitation]):
    model = Invitation

    def get_by_token(self, plaintext: str) -> Invitation | None:
        """One indexed read on the unique ``token_hash``."""
        stmt = select(Invitation).where(Invitation.token_hash == hash_secret(plaintext))
        return self.db.execute(stmt).scalars().first()

    def get_pending_for_email(self, organization_id: uuid.UUID, email: str) -> Invitation | None:
        """Matches the partial unique index: one live invitation per (org, email).

        Case-insensitive, because ``Ada@x.com`` and ``ada@x.com`` are the same mailbox.
        """
        stmt = select(Invitation).where(
            Invitation.organization_id == organization_id,
            Invitation.email.ilike(email),
            Invitation.status == InvitationStatus.PENDING.value,
        )
        return self.db.execute(stmt).scalars().first()

    def list_for_organization(
        self,
        organization_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Invitation]:
        stmt = select(Invitation).where(Invitation.organization_id == organization_id)
        if status:
            stmt = stmt.where(Invitation.status == status)
        stmt = stmt.order_by(Invitation.created_at.desc()).limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars().all())

    def list_expired_pending(
        self,
        now: datetime,
        *,
        organization_id: uuid.UUID | None = None,
        limit: int = 500,
    ) -> list[Invitation]:
        """PENDING invitations whose clock has run out — for the reaper.

        Scoped to one organization when given: an admin listing reaps its own tenant,
        never someone else's.
        """
        stmt = select(Invitation).where(
            Invitation.status == InvitationStatus.PENDING.value,
            Invitation.expires_at <= now,
        )
        if organization_id is not None:
            stmt = stmt.where(Invitation.organization_id == organization_id)
        return list(self.db.execute(stmt.limit(limit)).scalars().all())


class EmailVerificationRepository(BaseRepository[EmailVerification]):
    model = EmailVerification

    def get_by_token(self, plaintext: str) -> EmailVerification | None:
        stmt = select(EmailVerification).where(
            EmailVerification.verification_token_hash == hash_secret(plaintext)
        )
        return self.db.execute(stmt).scalars().first()

    def latest_for_user(self, user_id: uuid.UUID) -> EmailVerification | None:
        stmt = (
            select(EmailVerification)
            .where(EmailVerification.user_id == user_id)
            .order_by(EmailVerification.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalars().first()

    def active_for_user(self, user_id: uuid.UUID) -> list[EmailVerification]:
        """Tokens that could still be redeemed — everything a resend must supersede."""
        stmt = select(EmailVerification).where(
            EmailVerification.user_id == user_id,
            EmailVerification.verified_at.is_(None),
            EmailVerification.superseded_at.is_(None),
        )
        return list(self.db.execute(stmt).scalars().all())

    def has_verified(self, user_id: uuid.UUID) -> bool:
        stmt = (
            select(EmailVerification.id)
            .where(
                EmailVerification.user_id == user_id,
                EmailVerification.verified_at.is_not(None),
            )
            .limit(1)
        )
        return self.db.execute(stmt).scalars().first() is not None


class UserProfileRepository(BaseRepository[UserProfile]):
    model = UserProfile

    def get_for_user(self, user_id: uuid.UUID) -> UserProfile | None:
        stmt = select(UserProfile).where(UserProfile.user_id == user_id)
        return self.db.execute(stmt).scalars().first()
