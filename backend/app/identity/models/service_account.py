"""Service Account identity — backend automation (SRS §7)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.identity.models.enums import IdentityStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ServiceAccount(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "service_accounts"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Only the hash of the client secret is stored (never the plaintext).
    client_secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Namespaced permission codes granted directly to this account.
    permissions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    # The human user who owns / is accountable for this account.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=IdentityStatus.ACTIVE.value
    )
