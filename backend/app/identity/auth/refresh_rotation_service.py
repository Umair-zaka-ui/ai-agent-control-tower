"""RefreshRotationService — rotate, detect reuse, revoke families (SRS §7, §8, §9).

Rules, in order of importance:

1. A refresh token is **single use**. Every presentation rotates it.
2. An already-rotated token presented again is a **replay**. The only two parties
   who can hold it are the legitimate client and a thief, and the legitimate
   client has already moved on to its successor. So: kill the family and the
   session, and make both parties re-authenticate.
3. The plaintext is never stored, never logged, never compared in Python.

Rule 2 costs the victim a logout. That is deliberate: an interrupted session is
strictly better than a silently hijacked one.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.identity.models.session import RefreshToken
from app.identity.repositories.refresh_token_repository import RefreshTokenRepository
from app.identity.security.passwords import hash_secret

TOKEN_PREFIX = "rt_"


@dataclass
class IssuedToken:
    token: str  # plaintext, shown exactly once
    record: RefreshToken


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class RefreshRotationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = RefreshTokenRepository(db)
        self._ttl = timedelta(seconds=settings.AUTH_REFRESH_TOKEN_TTL_SECONDS)

    # ------------------------------------------------------------------ #
    # Issue / rotate (SRS §8)
    # ------------------------------------------------------------------ #
    def issue(self, session_id: uuid.UUID, family_id: uuid.UUID) -> IssuedToken:
        now = _now()
        plaintext = f"{TOKEN_PREFIX}{secrets.token_urlsafe(40)}"
        record = RefreshToken(
            session_id=session_id,
            family_id=family_id,
            token_hash=hash_secret(plaintext),
            created_at=now,
            expires_at=now + self._ttl,
        )
        self.db.add(record)
        self.db.flush()
        return IssuedToken(token=plaintext, record=record)

    def rotate(self, current: RefreshToken) -> IssuedToken:
        """Issue the successor, revoke the predecessor, link them."""
        issued = self.issue(current.session_id, current.family_id)
        current.revoked_at = _now()
        current.rotated_to_id = issued.record.id
        self.db.flush()
        return issued

    def find(self, plaintext: str) -> RefreshToken | None:
        return self.repo.get_by_plaintext(plaintext)

    # ------------------------------------------------------------------ #
    # Validity & reuse (SRS §9)
    # ------------------------------------------------------------------ #
    @staticmethod
    def is_reuse(record: RefreshToken) -> bool:
        """Revoked **and** already rotated → a stale token was replayed.

        A token that is merely revoked (e.g. by logout) is not a reuse signal:
        nobody rotated it, so nobody raced anybody. Requiring ``rotated_to_id``
        keeps logout from being reported as theft.
        """
        return record.revoked_at is not None and record.rotated_to_id is not None

    @staticmethod
    def is_valid(record: RefreshToken) -> bool:
        if record.revoked_at is not None:
            return False
        return _aware(record.expires_at) > _now()

    # ------------------------------------------------------------------ #
    # Family revocation (SRS §7, §9)
    # ------------------------------------------------------------------ #
    def revoke_family(self, family_id: uuid.UUID) -> int:
        return self.repo.revoke_family(family_id, now=_now())

    def mark_reuse(self, record: RefreshToken) -> RefreshToken:
        return self.repo.mark_reuse(record, now=_now())

    def family_chain(self, family_id: uuid.UUID) -> list[RefreshToken]:
        """The rotation chain, oldest first — the forensic view of a family."""
        return self.repo.list_family(family_id)
