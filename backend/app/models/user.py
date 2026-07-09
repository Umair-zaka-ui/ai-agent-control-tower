"""User model - human operators (admins, reviewers, viewers)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import UserRole
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Phase 4 Part 4.1: optional placement in the org → department hierarchy.
    # Nullable so existing users and creation paths are unaffected.
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"),
        nullable=False,
        default=UserRole.VIEWER,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Phase 4 Part 4.1a: canonical identity lifecycle (IdentityStatus). Kept in
    # sync with ``is_active`` (ACTIVE ⇔ is_active) so authentication is unchanged.
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE")

    # Phase 4 Part 4.2.2.3.2: credential lifecycle (SRS §11, §12, §13).
    #   password_changed_at — when the current password was set; drives min-age and
    #                          the reference point for expiry.
    #   password_expires_at — hard deadline; NULL means "never expires".
    #   must_change_password — a temporary/admin-reset password that must be replaced
    #                          at first login before any feature is reachable.
    # All nullable/defaulted so existing rows and creation paths are unaffected.
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    password_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    organization: Mapped["Organization"] = relationship(back_populates="users")
