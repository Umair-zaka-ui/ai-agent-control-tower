"""Enterprise organization hierarchy models (Phase 4.3.3 §5, §6, §10, §11).

Platform → Organization → Business Unit → Department → Team → Project → Resources.

``Organization`` (``app/models/organization.py``), ``Department`` and ``Team``
(``app/identity/models/department.py``) already exist and were extended in place;
this module adds the new levels plus resource ownership and delegation.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class BusinessUnit(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """§5 — a division inside an organization (Healthcare, Finance, …)."""

    __tablename__ = "business_units"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_business_unit_org_name"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")


class Project(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """§5 — a project inside a team (Medical AI, Revenue Cycle, …)."""

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("team_id", "name", name="uq_project_team_name"),
    )

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")


class ResourceOwnership(Base, UUIDPrimaryKeyMixin):
    """§6, §11 — a resource's full organizational path + owner. One row per
    (resource_type, resource_id)."""

    __tablename__ = "resource_ownership"
    __table_args__ = (
        UniqueConstraint("resource_type", "resource_id", name="uq_resource_ownership"),
    )

    resource_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    business_unit_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Delegation(Base, UUIDPrimaryKeyMixin):
    """§10 — delegated administrative authority over a scope. A delegatee may act
    within ``scope_type``/``scope_id`` (optionally limited to one ``permission``).
    Active while ``revoked_at IS NULL``."""

    __tablename__ = "delegations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    delegator_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    delegatee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # HierarchyLevel value: ORGANIZATION / BUSINESS_UNIT / DEPARTMENT / TEAM / PROJECT.
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Optional narrowing to a single permission; NULL = full admin within the scope.
    permission: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
