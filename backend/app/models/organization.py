"""Organization model - the top-level tenant boundary."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.user import User


class Organization(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Phase 4.3.3 §5: URL-safe slug + the organization owner.
    slug: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True, index=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Phase 4 Part 4.1a: canonical identity lifecycle (IdentityStatus).
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE")
    # How humans may join this organization (4.2.2.3.1 §3). Enterprise default is
    # INVITE_ONLY: unrestricted public registration is the exception, not the rule.
    registration_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="INVITE_ONLY", server_default="INVITE_ONLY"
    )

    # ``owner_id`` (Phase 4.3.3) adds a second FK path org↔user, so the membership
    # collection must name the one it uses (users.organization_id).
    users: Mapped[list["User"]] = relationship(
        back_populates="organization",
        cascade="all, delete-orphan",
        foreign_keys="User.organization_id",
    )
    agents: Mapped[list["Agent"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
