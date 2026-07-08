"""Refresh-token repository (SRS 4.2.2.2 §22).

Lookup is always by *hash* — the plaintext ``rt_…`` is never stored, never logged,
and never compared in Python.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update

from app.identity.models.session import RefreshToken
from app.identity.repositories.base import BaseRepository
from app.identity.security.passwords import hash_secret


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    def get_by_plaintext(self, plaintext: str) -> RefreshToken | None:
        """Constant-work lookup: hash the presented token, match on the indexed hash."""
        stmt = select(RefreshToken).where(RefreshToken.token_hash == hash_secret(plaintext))
        return self.db.execute(stmt).scalars().first()

    def list_family(self, family_id: uuid.UUID) -> list[RefreshToken]:
        stmt = (
            select(RefreshToken)
            .where(RefreshToken.family_id == family_id)
            .order_by(RefreshToken.created_at.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def revoke_family(self, family_id: uuid.UUID, *, now: datetime) -> int:
        """Revoke every live token in a family. Returns the number revoked."""
        result = self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        self.db.flush()
        return int(result.rowcount or 0)

    def mark_reuse(self, token: RefreshToken, *, now: datetime) -> RefreshToken:
        """Anchor the forensic record on the exact token that was replayed."""
        token.reuse_detected_at = now
        self.db.flush()
        return token
