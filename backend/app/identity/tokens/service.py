"""Refresh token issuance + rotation (SRS §6 tokens).

Only token hashes are persisted; the plaintext is returned to the caller once.
Rotation revokes the old token and links it to its successor for the audit chain.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.identity.models.session import RefreshToken
from app.identity.security.passwords import hash_secret, verify_secret

DEFAULT_REFRESH_TTL = timedelta(days=30)


@dataclass
class IssuedToken:
    token: str  # plaintext (shown once)
    record: RefreshToken


class RefreshTokenService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def issue(self, session_id: uuid.UUID, *, ttl: timedelta = DEFAULT_REFRESH_TTL) -> IssuedToken:
        now = datetime.now(timezone.utc)
        plaintext = f"rt_{secrets.token_urlsafe(40)}"
        record = RefreshToken(
            session_id=session_id,
            token_hash=hash_secret(plaintext),
            created_at=now,
            expires_at=now + ttl,
        )
        self.db.add(record)
        self.db.flush()
        return IssuedToken(token=plaintext, record=record)

    def rotate(self, current: RefreshToken, *, ttl: timedelta = DEFAULT_REFRESH_TTL) -> IssuedToken:
        issued = self.issue(current.session_id, ttl=ttl)
        current.revoked_at = datetime.now(timezone.utc)
        current.rotated_to_id = issued.record.id
        self.db.flush()
        return issued

    @staticmethod
    def matches(plaintext: str, record: RefreshToken) -> bool:
        return verify_secret(plaintext, record.token_hash)

    @staticmethod
    def is_valid(record: RefreshToken) -> bool:
        if record.revoked_at is not None:
            return False
        return record.expires_at > datetime.now(timezone.utc)
