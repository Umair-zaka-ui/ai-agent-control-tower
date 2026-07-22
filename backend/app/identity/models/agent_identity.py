"""AI Agent Identity — the *identity* of an agent, not the agent itself (SRS §7).

The ``agents`` table (Phase 1) models the agent's behaviour and configuration.
This table models its identity/credential posture within the Identity Platform.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.identity.models.enums import CredentialType, IdentityStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AgentIdentity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agent_identities"
    # Phase 5.1 SRS §11.1 — mandatory 1:1 machine identity: one identity can't
    # silently attach to two agents.
    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_agent_identities_agent"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Public identifier used by the agent when authenticating.
    client_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    credential_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=CredentialType.API_KEY.value
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=IdentityStatus.ACTIVE.value
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
