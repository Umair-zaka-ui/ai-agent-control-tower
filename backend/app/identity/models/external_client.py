"""External Client identity — Power BI, Zapier, Salesforce, Fabric, etc. (SRS §7)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.identity.models.enums import IdentityStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ExternalClient(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "external_clients"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Public OAuth-style client identifier (unique, safe to share).
    client_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    redirect_uri: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # Only the hash of the secret is stored.
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    allowed_scopes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=IdentityStatus.ACTIVE.value
    )
