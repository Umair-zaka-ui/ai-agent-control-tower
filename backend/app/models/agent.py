"""Agent model - the AI agents whose actions are governed."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import AgentStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.permission import Permission


class Agent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agents"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_type: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, name="agent_status"),
        nullable=False,
        default=AgentStatus.ACTIVE,
    )

    organization: Mapped["Organization"] = relationship(back_populates="agents")
    permissions: Mapped[list["Permission"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
