"""Password-reset repository (4.2.2.3.3 §20). Lookup is always by token hash."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from app.identity.models.enums import PasswordResetStatus
from app.identity.models.recovery import PasswordResetRequest
from app.identity.repositories.base import BaseRepository
from app.identity.security.passwords import hash_secret


class PasswordResetRepository(BaseRepository[PasswordResetRequest]):
    model = PasswordResetRequest

    def get_by_token(self, plaintext: str) -> PasswordResetRequest | None:
        """One indexed read on the unique ``token_hash`` — plaintext never compared."""
        stmt = select(PasswordResetRequest).where(
            PasswordResetRequest.token_hash == hash_secret(plaintext)
        )
        return self.db.execute(stmt).scalars().first()

    def active_for_user(self, user_id: uuid.UUID) -> list[PasswordResetRequest]:
        """PENDING requests a new request must supersede (§9)."""
        stmt = select(PasswordResetRequest).where(
            PasswordResetRequest.user_id == user_id,
            PasswordResetRequest.status == PasswordResetStatus.PENDING.value,
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_for_organization(
        self, organization_id: uuid.UUID, *, status: str | None = None, limit: int = 100
    ) -> list[PasswordResetRequest]:
        stmt = select(PasswordResetRequest).where(
            PasswordResetRequest.organization_id == organization_id
        )
        if status:
            stmt = stmt.where(PasswordResetRequest.status == status)
        stmt = stmt.order_by(PasswordResetRequest.created_at.desc()).limit(limit)
        return list(self.db.execute(stmt).scalars().all())

    def list_expired_pending(
        self, now: datetime, *, organization_id: uuid.UUID | None = None, limit: int = 500
    ) -> list[PasswordResetRequest]:
        """PENDING requests whose 30 minutes have run out — for the reaper (§26)."""
        stmt = select(PasswordResetRequest).where(
            PasswordResetRequest.status == PasswordResetStatus.PENDING.value,
            PasswordResetRequest.expires_at <= now,
        )
        if organization_id is not None:
            stmt = stmt.where(PasswordResetRequest.organization_id == organization_id)
        return list(self.db.execute(stmt.limit(limit)).scalars().all())
