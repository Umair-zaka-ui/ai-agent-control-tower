"""AgentApiKey model - hashed, rotatable API keys for agent authentication."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import ApiKeyStatus
from app.models.mixins import UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.agent import Agent


class AgentApiKey(Base, UUIDPrimaryKeyMixin):
    """An API key issued to an agent. Only the hash is ever stored."""

    __tablename__ = "agent_api_keys"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # SHA-256 hash of the full key; lookups happen by this value.
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    # First chars of the key (e.g. "agt_live_AB") - safe to display for identification.
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[ApiKeyStatus] = mapped_column(
        Enum(ApiKeyStatus, name="api_key_status"),
        nullable=False,
        default=ApiKeyStatus.ACTIVE,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    agent: Mapped["Agent"] = relationship(back_populates="api_keys")
