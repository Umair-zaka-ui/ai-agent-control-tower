"""PasswordHistoryService — store past hashes, detect reuse, prune (SRS §10, §19).

Reuse detection is a hash comparison, never a plaintext one: the candidate is
verified against each stored argon2id hash exactly as a login would verify it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import verify_password
from app.identity.models.credential import PasswordHistory


class PasswordHistoryService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.depth = settings.PASSWORD_HISTORY_DEPTH

    def _recent(self, user_id: uuid.UUID) -> list[PasswordHistory]:
        return list(
            self.db.scalars(
                select(PasswordHistory)
                .where(PasswordHistory.user_id == user_id)
                .order_by(PasswordHistory.created_at.desc())
                .limit(self.depth)
            )
        )

    def is_reused(
        self, user_id: uuid.UUID, new_password: str, *, current_hash: str | None = None
    ) -> bool:
        """True if ``new_password`` matches the current password or any of the last
        N stored hashes (SRS §10).

        The *current* hash is checked too — the common "reuse" is setting the same
        password again, and it is not yet in the history table when a change begins.
        """
        if current_hash and verify_password(new_password, current_hash):
            return True
        return any(verify_password(new_password, row.password_hash) for row in self._recent(user_id))

    def record(self, user_id: uuid.UUID, password_hash: str) -> PasswordHistory:
        """Append a (former) hash and prune to the configured depth.

        Called with the hash being *replaced*, so the just-set password does not
        immediately count against its own history but every prior one does.
        """
        entry = PasswordHistory(user_id=user_id, password_hash=password_hash)
        self.db.add(entry)
        self.db.flush()
        self._prune(user_id)
        return entry

    def _prune(self, user_id: uuid.UUID) -> None:
        """Keep only the newest ``depth`` rows; older ones can never be re-checked."""
        stale = list(
            self.db.scalars(
                select(PasswordHistory)
                .where(PasswordHistory.user_id == user_id)
                .order_by(PasswordHistory.created_at.desc())
                .offset(self.depth)
            )
        )
        for row in stale:
            self.db.delete(row)
