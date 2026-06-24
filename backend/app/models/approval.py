"""Approval model - the human review attached to a pending agent action."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import ApprovalDecision, ApprovalPriority
from app.models.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.agent_action import AgentAction


class Approval(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "approvals"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_actions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    requested_by_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decision: Mapped[ApprovalDecision] = mapped_column(
        Enum(ApprovalDecision, name="approval_decision"),
        nullable=False,
        default=ApprovalDecision.PENDING,
    )
    priority: Mapped[ApprovalPriority] = mapped_column(
        Enum(ApprovalPriority, name="approval_priority"),
        nullable=False,
        default=ApprovalPriority.MEDIUM,
        index=True,
    )
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SLA deadline by which this approval should be reviewed.
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    agent_action: Mapped["AgentAction"] = relationship(back_populates="approval")
    comments: Mapped[list["ApprovalComment"]] = relationship(
        back_populates="approval", cascade="all, delete-orphan", order_by="ApprovalComment.created_at"
    )


class ApprovalComment(Base, UUIDPrimaryKeyMixin):
    """A threaded comment left by a reviewer on an approval."""

    __tablename__ = "approval_comments"

    approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("approvals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    approval: Mapped["Approval"] = relationship(back_populates="comments")
