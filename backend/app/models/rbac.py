"""Advanced RBAC models: roles, permission catalog and their join tables.

Note: the Phase 1 ``permissions`` table governs *agent* resource/action access.
This RBAC permission catalog (what *users* may do, e.g. ``agent.create``) is a
separate concept, so its table is named ``rbac_permissions`` to avoid collision.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class Role(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_role_org_name"),
    )

    # ``organization_id`` NULL => a built-in system role shared by all orgs.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- Phase 4.3.1 enterprise role metadata (§8, §9, §10, §16) --------- #
    display_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # RoleCategory value; String (not a PG enum) per the codebase convention.
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="CUSTOM")
    # RoleStatus value — CREATED/ACTIVE/UPDATED/DEPRECATED/ARCHIVED/DELETED.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE", index=True)
    is_assignable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Conflict-resolution weight (§16): higher wins.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    permissions: Mapped[list["RbacPermission"]] = relationship(
        secondary="role_permissions", back_populates="roles"
    )


class RbacPermission(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "rbac_permissions"

    # Dotted permission code, e.g. "agent.create", "policy.edit", "audit.view".
    # This is the canonical ``name`` (§10/§11 resource.action convention).
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Phase 4.3.1 permission metadata (§10, §11, §12) ----------------- #
    display_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permission_groups.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    action: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    group: Mapped["PermissionGroup | None"] = relationship(back_populates="permissions")
    roles: Mapped[list["Role"]] = relationship(
        secondary="role_permissions", back_populates="permissions"
    )


class PermissionGroup(Base, UUIDPrimaryKeyMixin):
    """§12 — permissions grouped by domain (Agents, Policies, Security, …)."""

    __tablename__ = "permission_groups"

    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    permissions: Mapped[list["RbacPermission"]] = relationship(back_populates="group")


class RolePermission(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rbac_permissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserRole(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "user_roles"
    # A user may hold the same role at different scopes (org-wide vs one department),
    # so uniqueness now spans the scope key, not just (user, role).
    __table_args__ = (
        UniqueConstraint(
            "user_id", "role_id", "scope", "organization_id", "department_id",
            "team_id", "project_id", "resource_type", "resource_id",
            name="uq_user_role_scope",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # --- Phase 4.3.1 scoped assignment (§14, §15) ------------------------ #
    # AssignmentScope value; GLOBAL means "everywhere the role applies".
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="GLOBAL", index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="CASCADE"), nullable=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=True
    )
    # No ``projects`` table yet (a later phase); a soft reference for now.
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Generic RESOURCE scope target (§15) — e.g. resource_type="agent", resource_id=<agent>.
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Time-boxed assignments (§18 RoleAssignmentService.expire).
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    role: Mapped["Role"] = relationship()


class RoleHierarchy(Base, UUIDPrimaryKeyMixin):
    """§17 — directed edge: ``parent`` (senior) inherits ``child``'s permissions.
    The graph is kept acyclic; cycles are rejected at write time."""

    __tablename__ = "role_hierarchy"
    __table_args__ = (
        UniqueConstraint("parent_role_id", "child_role_id", name="uq_role_hierarchy_edge"),
    )

    parent_role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    child_role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuthorizationAudit(Base, UUIDPrimaryKeyMixin):
    """§10, §23 — one row per authorization decision *or* administrative change.

    A superset of the §10 schema so it can hold both a per-request decision
    (``permission``/``decision``/``reason``) and a change event
    (``event_type``/``actor_id``/``meta``)."""

    __tablename__ = "authorization_audit"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # The administrator who made a change (for change events).
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    # The subject the decision/change concerns (user/agent/service identity).
    identity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    permission: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
