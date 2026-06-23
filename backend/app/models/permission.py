"""Permission model - per-agent allow/deny rules for resource + action pairs."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.agent import Agent


class Permission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "permissions"
    __table_args__ = (
        # An agent has a single rule per (resource, action) pair.
        UniqueConstraint(
            "agent_id", "resource", "action", name="uq_permission_agent_resource_action"
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    agent: Mapped["Agent"] = relationship(back_populates="permissions")
