"""AgentAction model - a single attempted action and its governance outcome."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import ActionDecision, ActionStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.approval import Approval


class AgentAction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agent_actions"

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
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    decision: Mapped[ActionDecision] = mapped_column(
        Enum(ActionDecision, name="action_decision"), nullable=False
    )
    decision_reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ActionStatus] = mapped_column(
        Enum(ActionStatus, name="action_status"), nullable=False
    )

    approval: Mapped["Approval | None"] = relationship(
        back_populates="agent_action",
        cascade="all, delete-orphan",
        uselist=False,
    )
