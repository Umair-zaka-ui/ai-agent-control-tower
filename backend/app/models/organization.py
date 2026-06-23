"""Organization model - the top-level tenant boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.user import User


class Organization(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    users: Mapped[list["User"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    agents: Mapped[list["Agent"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
