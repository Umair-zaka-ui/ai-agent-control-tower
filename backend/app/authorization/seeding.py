"""Idempotent seeding of the authorization foundation (Phase 4.3.1 §7, §12, §17).

Creates the permission groups, enriches the permission catalog with group/resource
metadata, materialises the built-in role taxonomy as GLOBAL system roles, and wires
the role hierarchy. Safe to run repeatedly; run at app seed time and in tests.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.catalog import (
    BUILTIN_ROLES,
    PERMISSION_GROUPS,
    ROLE_HIERARCHY_EDGES,
    display_name_for_code,
    group_for_code,
    legacy_role_priority,
    split_code,
)
from app.authorization.enums import RoleCategory, RoleStatus
from app.models.rbac import (
    PermissionGroup,
    RbacPermission,
    Role,
    RoleHierarchy,
    RolePermission,
)
from app.services.rbac_service import PERMISSION_CATALOG


def _ensure_groups(db: Session) -> dict[str, PermissionGroup]:
    by_name = {g.name: g for g in db.execute(select(PermissionGroup)).scalars()}
    for gdef in PERMISSION_GROUPS:
        group = by_name.get(gdef.name)
        if group is None:
            group = PermissionGroup(
                name=gdef.name,
                display_name=gdef.display_name,
                description=gdef.description,
                sort_order=gdef.sort_order,
            )
            db.add(group)
            by_name[gdef.name] = group
        else:
            group.display_name = gdef.display_name
            group.description = gdef.description
            group.sort_order = gdef.sort_order
    db.flush()
    return by_name


def _ensure_permissions(db: Session, groups: dict[str, PermissionGroup]) -> dict[str, RbacPermission]:
    by_code = {p.code: p for p in db.execute(select(RbacPermission)).scalars()}
    for code, description in PERMISSION_CATALOG.items():
        resource, action = split_code(code)
        group = groups.get(group_for_code(code))
        perm = by_code.get(code)
        if perm is None:
            perm = RbacPermission(code=code, description=description)
            db.add(perm)
            by_code[code] = perm
        perm.description = perm.description or description
        perm.display_name = display_name_for_code(code)
        perm.resource_type = resource
        perm.action = action
        perm.is_system = True
        perm.group_id = group.id if group else None
    db.flush()
    return by_code


def _grant(db: Session, role: Role, codes: set[str], by_code: dict[str, RbacPermission]) -> None:
    granted = {
        pid for (pid,) in db.execute(
            select(RolePermission.permission_id).where(RolePermission.role_id == role.id)
        )
    }
    for code in codes:
        perm = by_code.get(code)
        if perm is not None and perm.id not in granted:
            db.add(RolePermission(role_id=role.id, permission_id=perm.id))


def _ensure_builtin_roles(db: Session, by_code: dict[str, RbacPermission]) -> dict[str, Role]:
    """Global (organization_id IS NULL) system roles from the §7 taxonomy."""
    existing = {
        r.name: r
        for r in db.execute(select(Role).where(Role.organization_id.is_(None))).scalars()
    }
    for rdef in BUILTIN_ROLES:
        role = existing.get(rdef.name)
        if role is None:
            role = Role(
                organization_id=None,
                name=rdef.name,
                display_name=rdef.display_name,
                description=rdef.description,
                category=rdef.category.value,
                status=RoleStatus.ACTIVE.value,
                is_system=True,
                is_assignable=rdef.is_assignable,
                priority=rdef.priority,
            )
            db.add(role)
            existing[rdef.name] = role
        else:
            role.display_name = rdef.display_name
            role.description = rdef.description
            role.category = rdef.category.value
            role.is_system = True
            role.priority = rdef.priority
        db.flush()
        _grant(db, role, rdef.permissions, by_code)
    db.flush()
    return existing


def _ensure_hierarchy(db: Session, roles: dict[str, Role]) -> None:
    for parent_name, child_name in ROLE_HIERARCHY_EDGES:
        parent, child = roles.get(parent_name), roles.get(child_name)
        if parent is None or child is None:
            continue
        exists = db.execute(
            select(RoleHierarchy).where(
                RoleHierarchy.parent_role_id == parent.id,
                RoleHierarchy.child_role_id == child.id,
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(RoleHierarchy(parent_role_id=parent.id, child_role_id=child.id))
    db.flush()


def _backfill_legacy_roles(db: Session) -> None:
    """Give the four legacy per-org system roles (SUPER_ADMIN/ADMIN/REVIEWER/VIEWER)
    a sensible category/priority/display_name so they sort with the new taxonomy."""
    for role in db.execute(select(Role).where(Role.is_system.is_(True))).scalars():
        if role.name.startswith("ROLE_"):
            continue  # a new-taxonomy role, already set
        role.category = RoleCategory.SYSTEM.value
        role.priority = legacy_role_priority(role.name)
        role.display_name = role.display_name or role.name.replace("_", " ").title()
        if role.status is None:
            role.status = RoleStatus.ACTIVE.value
    db.flush()


def _ensure_global_wildcard(db: Session, roles: dict[str, Role]) -> None:
    """Grant the reserved global wildcard ``*`` to ROLE_PLATFORM_OWNER only (§14).

    Kept out of the shared PERMISSION_CATALOG so ordinary admin roles never receive
    it; created directly here and granted to the platform owner."""
    owner = roles.get("ROLE_PLATFORM_OWNER")
    if owner is None:
        return
    star = db.execute(select(RbacPermission).where(RbacPermission.code == "*")).scalar_one_or_none()
    if star is None:
        star = RbacPermission(
            code="*", description="Global wildcard — every permission (reserved)",
            display_name="Global wildcard", resource_type="*", action="*", is_system=True,
        )
        db.add(star)
        db.flush()
    already = db.execute(
        select(RolePermission).where(
            RolePermission.role_id == owner.id, RolePermission.permission_id == star.id
        )
    ).scalar_one_or_none()
    if already is None:
        db.add(RolePermission(role_id=owner.id, permission_id=star.id))
    db.flush()


def seed_authorization(db: Session) -> None:
    """Idempotently seed groups, permission metadata, built-in roles and hierarchy.
    Stages everything; the caller commits."""
    groups = _ensure_groups(db)
    by_code = _ensure_permissions(db, groups)
    roles = _ensure_builtin_roles(db, by_code)
    _ensure_hierarchy(db, roles)
    _ensure_global_wildcard(db, roles)
    _backfill_legacy_roles(db)
