"""Agent model - the AI agents whose actions are governed."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import AgentStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.api_key import AgentApiKey
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

    # --- Phase 3 Part 3.2: enterprise agent metadata ---
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False, default="1.0.0")
    capabilities: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    default_risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_allowed_risk: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    human_approval_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    auto_suspend_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="LOW")
    health: Mapped[str] = mapped_column(String(20), nullable=False, default="HEALTHY")

    organization: Mapped["Organization"] = relationship(back_populates="agents")
    permissions: Mapped[list["Permission"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list["AgentApiKey"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
