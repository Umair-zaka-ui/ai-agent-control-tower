"""RefreshTokenService — issue / rotate / detect-reuse / revoke (SRS §6, §20).

Builds on the identity-layer token store. Refresh tokens are stored hashed and
rotate on every use; presenting an already-rotated token is treated as a theft
signal (reuse detection). The dedicated ``family_id`` / ``reuse_detected_at``
columns arrive with the migration plan in Part 4.2.2; until then the session is
the family boundary and rotation state (``revoked_at`` + ``rotated_to_id``)
drives reuse detection.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.identity.models.session import RefreshToken
from app.identity.tokens.service import IssuedToken
from app.identity.tokens.service import RefreshTokenService as _StoreRefreshTokenService


class RefreshTokenService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._store = _StoreRefreshTokenService(db)
        self._ttl = timedelta(seconds=settings.AUTH_REFRESH_TOKEN_TTL_SECONDS)

    def issue(self, session_id: uuid.UUID) -> IssuedToken:
        return self._store.issue(session_id, ttl=self._ttl)

    def find(self, plaintext: str) -> RefreshToken | None:
        """Locate the stored record for a presented refresh token (by hash)."""
        from app.identity.security.passwords import hash_secret

        return self.db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_secret(plaintext))
        ).scalar_one_or_none()

    def rotate(self, current: RefreshToken) -> IssuedToken:
        return self._store.rotate(current, ttl=self._ttl)

    @staticmethod
    def is_valid(record: RefreshToken) -> bool:
        return _StoreRefreshTokenService.is_valid(record)

    @staticmethod
    def is_reuse(record: RefreshToken) -> bool:
        """A revoked token that was already rotated → replay of a stale token."""
        return record.revoked_at is not None and record.rotated_to_id is not None

    def revoke_session_family(self, session_id: uuid.UUID) -> int:
        """Revoke every refresh token for a session (family proxy). Returns count."""
        from datetime import datetime, timezone

        result = self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.session_id == session_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )
        self.db.flush()
        return int(result.rowcount or 0)
