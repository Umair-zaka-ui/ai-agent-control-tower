"""Resource-based authorization models (Phase 4.3.4 §15).

Every managed object becomes a first-class protected resource with its own
authorization metadata: an owner, a visibility level, an ACL, shares,
delegations, an ownership history and an optional resource policy.

``resource_ownership`` (Phase 4.3.3) keeps holding a resource's *organizational
path* (used for scoped-grant inheritance); the ``resources`` registry below
holds its *authorization metadata*. The two are linked by
``(resource_type, resource_id)``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ProtectedResource(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """§6, §15 — the resource registry. One row per protected object; ``id`` is
    the handle used by the /resources API, ``(resource_type, resource_id)``
    links to the underlying platform object (agent, policy, workflow, …)."""

    __tablename__ = "resources"
    __table_args__ = (
        UniqueConstraint("resource_type", "resource_id", name="uq_resources_type_id"),
    )

    resource_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # §6 — exactly one owner. owner_type: USER / TEAM / DEPARTMENT / ORGANIZATION /
    # SERVICE_ACCOUNT; owner_id points into the matching table.
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    owner_type: Mapped[str] = mapped_column(String(20), nullable=False, default="USER")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # §9 — PRIVATE / TEAM / DEPARTMENT / ORGANIZATION / PUBLIC_INTERNAL.
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="PRIVATE")
    # ACTIVE / ARCHIVED / SYSTEM. SYSTEM resources carry the §22 platform-admin
    # protection (owners cannot deny platform administrators on them).
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    # §14 — optional resource policy: a list of rules, each
    # ``{"permission": <code|action>, "principal_type": ..., "principal_id": ...}``
    # meaning only matching principals may perform that permission.
    policy: Mapped[list | None] = mapped_column(JSONB, nullable=True)


class ResourceACLEntry(Base, UUIDPrimaryKeyMixin):
    """§10, §15 — one ACL entry. Explicit DENY always overrides ALLOW (§11);
    expired entries are ignored (§22)."""

    __tablename__ = "resource_acl"

    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resources.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # USER / ROLE / TEAM / DEPARTMENT / ORGANIZATION / SERVICE_ACCOUNT.
    principal_type: Mapped[str] = mapped_column(String(20), nullable=False)
    principal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    # A concrete permission code ("agent.update"), a bare action ("update"), or "*".
    permission: Mapped[str] = mapped_column(String(100), nullable=False)
    effect: Mapped[str] = mapped_column(String(5), nullable=False, default="ALLOW")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ResourceShare(Base, UUIDPrimaryKeyMixin):
    """§12, §15 — an explicit share with a user, team, department or the whole
    organization at an access level (READ/COMMENT/EXECUTE/EDIT/MANAGE)."""

    __tablename__ = "resource_shares"

    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resources.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    shared_with_type: Mapped[str] = mapped_column(String(20), nullable=False)
    shared_with_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    access_level: Mapped[str] = mapped_column(String(10), nullable=False, default="READ")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OwnershipHistory(Base, UUIDPrimaryKeyMixin):
    """§8, §15 — every ownership transfer is preserved."""

    __tablename__ = "ownership_history"

    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resources.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    previous_owner: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    previous_owner_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    new_owner: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    new_owner_type: Mapped[str] = mapped_column(String(20), nullable=False, default="USER")
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ResourceDelegation(Base, UUIDPrimaryKeyMixin):
    """§13, §15 — the owner delegates a set of actions on one resource to a user,
    optionally time-boxed. Active while ``status == 'ACTIVE'`` and not expired."""

    __tablename__ = "resource_delegations"

    resource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resources.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    delegate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # JSON list of actions/permission codes ("manage", "agent.update", "*").
    permissions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="ACTIVE")
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
