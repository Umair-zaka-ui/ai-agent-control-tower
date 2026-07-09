"""Password-reset request model (4.2.2.3.3 §5).

**No token plaintext is ever stored.** The reset token is 256 bits of CSPRNG behind
the ``rst_`` prefix, returned once in an email link and persisted only as a SHA-256
hash. A database dump therefore cannot be used to reset anyone's password.

``recovery_events`` from §5 is *not* a separate table: recovery audit events land in
the platform's single ``security_events`` stream (as every other identity event
does), so the existing audit UI and export surface them with no new plumbing. See
``docs/identity/recovery.md``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.identity.models.enums import PasswordResetStatus
from app.models.mixins import UUIDPrimaryKeyMixin


class PasswordResetRequest(Base, UUIDPrimaryKeyMixin):
    """A single-use, short-lived request to reset one user's password."""

    __tablename__ = "password_reset_requests"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PasswordResetStatus.PENDING.value, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Forensic context of who asked (§5). An unexpected IP is the first hint that a
    # reset request was not the account owner.
    created_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_password_reset_requests_user_status", "user_id", "status"),
    )
