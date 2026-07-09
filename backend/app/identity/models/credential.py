"""Credential-history ORM model (4.2.2.3.2 §10, §21).

The live credential is still ``users.password_hash`` — this table records the
*previous* hashes so a change can refuse to reuse one of the last N (SRS §10). It
stores only argon2id hashes, never plaintext, and never the current hash's salt
separately (argon2 encodes its parameters and salt in the hash string itself).

We deliberately do **not** introduce a separate ``credentials`` table that would
duplicate ``users.password_hash`` as a second source of truth for the *active*
credential: forking that would put the entire authentication stack at risk for no
functional gain. See ``docs/identity/credential-management.md``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PasswordHistory(Base):
    __tablename__ = "password_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # A former argon2id hash. Verified against on change to reject reuse (§10).
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
