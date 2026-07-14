"""Resource-based authorization services (Phase 4.3.4 §16, §17).

``ResourceAuthorizationService`` coordinates the complete §5/§18 evaluation:

    identity → org scope → roles (Permission Engine) → ownership → ACL →
    delegation → sharing → resource policy → visibility → decision

with the §11 priority (explicit DENY → explicit ALLOW → inherited permission →
visibility rule → default DENY). The management services (`ResourceACLService`,
`ResourceSharingService`, `ResourceOwnershipService`, `ResourceDelegationService`,
`ResourcePolicyService`) mutate the metadata and audit every change (§23).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.authorization.engine import GLOBAL_WILDCARD, PermissionEngine, ResourceContext
from app.authorization.resources.enums import (
    ACLEffect,
    DelegationStatus,
    OwnerType,
    PrincipalType,
    ResourceAuditEvent,
    ResourceStatus,
    ShareAccessLevel,
    VisibilityLevel,
)
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.department import Department, Team
from app.models.rbac import AuthorizationAudit, Role, UserRole
from app.models.resource_authorization import (
    OwnershipHistory,
    ProtectedResource,
    ResourceACLEntry,
    ResourceDelegation,
    ResourceShare,
)
from app.models.user import User

# --------------------------------------------------------------------------- #
# Action vocabulary
# --------------------------------------------------------------------------- #
# A permission code is "<resource_type>.<action>" (agent.update); ACL entries,
# shares and delegations may name the full code, the bare action, or "*".
VIEW_ACTIONS = {"view", "read", "list", "get"}
_SHARE_ACTIONS: dict[str, set[str]] = {
    ShareAccessLevel.READ.value: set(VIEW_ACTIONS),
    ShareAccessLevel.COMMENT.value: VIEW_ACTIONS | {"comment"},
    ShareAccessLevel.EXECUTE.value: VIEW_ACTIONS | {"execute", "run", "invoke", "test"},
    ShareAccessLevel.EDIT.value: VIEW_ACTIONS | {"comment", "execute", "run", "invoke",
                                                 "test", "update", "edit", "write"},
    # MANAGE covers every action except ownership transfer (owner/admin only §8).
    ShareAccessLevel.MANAGE.value: {"*"},
}


def action_of(permission: str) -> str:
    """The action part of a permission code: ``agent.update`` → ``update``."""
    return permission.rsplit(".", 1)[-1].lower()


def permission_covers(granted: str, requested: str) -> bool:
    """Does an ACL/delegation ``granted`` string cover the ``requested`` code?
    Matches on "*", the exact code, or the bare action."""
    if granted == "*":
        return True
    g = granted.lower()
    return g == requested.lower() or g == action_of(requested)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _not_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return True
    value = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    return value > _now()


# --------------------------------------------------------------------------- #
# Audit (§23) — recorded on the shared authorization_audit table.
# --------------------------------------------------------------------------- #
def record_resource_event(
    db: Session,
    event: ResourceAuditEvent,
    *,
    organization_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    meta: dict | None = None,
) -> None:
    db.add(
        AuthorizationAudit(
            organization_id=organization_id,
            actor_id=actor_id,
            event_type=event.value,
            meta=meta,
        )
    )
    db.flush()


# --------------------------------------------------------------------------- #
# Membership resolver — does an identity match a principal? (§10, §12)
# --------------------------------------------------------------------------- #
class MembershipResolver:
    """Resolves USER/ROLE/TEAM/DEPARTMENT/ORGANIZATION principals to a yes/no
    for one identity. Team membership = team lead or a role assignment scoped to
    the team; department membership = the user's own department, its manager, or
    a department-scoped role assignment."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def matches(self, user: User, principal_type: str, principal_id: uuid.UUID) -> bool:
        pt = principal_type.upper()
        if pt in (PrincipalType.USER.value, PrincipalType.SERVICE_ACCOUNT.value):
            return user.id == principal_id
        if pt == PrincipalType.ORGANIZATION.value:
            return user.organization_id == principal_id
        if pt == PrincipalType.ROLE.value:
            return self._has_role(user, principal_id)
        if pt == PrincipalType.DEPARTMENT.value:
            return self.in_department(user, principal_id)
        if pt == PrincipalType.TEAM.value:
            return self.in_team(user, principal_id)
        return False

    def in_department(self, user: User, department_id: uuid.UUID) -> bool:
        if user.department_id == department_id:
            return True
        dept = self.db.get(Department, department_id)
        if dept is not None and dept.manager_id == user.id:
            return True
        return self._has_scoped_assignment(user, department_id=department_id)

    def in_team(self, user: User, team_id: uuid.UUID) -> bool:
        team = self.db.get(Team, team_id)
        if team is not None and team.lead_id == user.id:
            return True
        return self._has_scoped_assignment(user, team_id=team_id)

    def _has_role(self, user: User, role_id: uuid.UUID) -> bool:
        now = _now()
        rows = self.db.execute(
            select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role_id)
        ).scalars()
        return any(r.expires_at is None or r.expires_at > now for r in rows)

    def _has_scoped_assignment(
        self, user: User, *,
        department_id: uuid.UUID | None = None, team_id: uuid.UUID | None = None,
    ) -> bool:
        q = select(UserRole).where(UserRole.user_id == user.id)
        if department_id is not None:
            q = q.where(UserRole.department_id == department_id)
        if team_id is not None:
            q = q.where(UserRole.team_id == team_id)
        now = _now()
        return any(
            r.expires_at is None or r.expires_at > now
            for r in self.db.execute(q).scalars()
        )


# --------------------------------------------------------------------------- #
# Registry + shared helpers
# --------------------------------------------------------------------------- #
class ResourceRegistryService:
    """Register and look up protected resources (§3, §6). Registration is open to
    any authenticated identity (they become the owner); administering someone
    else's resource needs ``resource.manage``."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, actor: User, resource_pk: uuid.UUID) -> ProtectedResource:
        res = self.db.get(ProtectedResource, resource_pk)
        if res is None:
            raise IdentityError(ErrorCode.RESOURCE_NOT_FOUND, "Resource not found.")
        # Cross-tenant lookups answer "not found", never "forbidden" (§22.4) —
        # except PUBLIC_INTERNAL resources, which any authenticated user may see.
        if (res.organization_id != actor.organization_id
                and res.visibility != VisibilityLevel.PUBLIC_INTERNAL.value):
            raise IdentityError(ErrorCode.RESOURCE_NOT_FOUND, "Resource not found.")
        return res

    def by_external(self, resource_type: str, resource_id: uuid.UUID) -> ProtectedResource | None:
        return self.db.execute(
            select(ProtectedResource).where(
                ProtectedResource.resource_type == resource_type,
                ProtectedResource.resource_id == resource_id,
            )
        ).scalar_one_or_none()

    def list(self, actor: User, *, can_view_all: bool,
             resource_type: str | None = None) -> list[ProtectedResource]:
        q = select(ProtectedResource).where(
            ProtectedResource.organization_id == actor.organization_id
        )
        if not can_view_all:
            # Without resource.view, an identity sees only what it owns or created.
            q = q.where(or_(ProtectedResource.owner_id == actor.id,
                            ProtectedResource.created_by == actor.id))
        if resource_type:
            q = q.where(ProtectedResource.resource_type == resource_type)
        return list(self.db.execute(q.order_by(ProtectedResource.created_at.desc())).scalars())

    def register(
        self, actor: User, *, resource_type: str, resource_id: uuid.UUID | None,
        name: str | None, visibility: str, owner_id: uuid.UUID | None,
        owner_type: str, project_id: uuid.UUID | None, can_manage_any: bool,
    ) -> ProtectedResource:
        if owner_id is not None and owner_id != actor.id and not can_manage_any:
            raise IdentityError(ErrorCode.RESOURCE_OWNER_REQUIRED,
                                "Only a resource administrator may register on behalf of another owner.")
        try:
            VisibilityLevel(visibility)
        except ValueError as exc:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "Unknown visibility level.") from exc
        try:
            OwnerType(owner_type)
        except ValueError as exc:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "Unknown owner type.") from exc

        external_id = resource_id or uuid.uuid4()
        existing = self.by_external(resource_type, external_id)
        if existing is not None:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "Resource is already registered.")
        res = ProtectedResource(
            resource_type=resource_type, resource_id=external_id, name=name,
            organization_id=actor.organization_id, project_id=project_id,
            owner_id=owner_id or actor.id, owner_type=owner_type,
            created_by=actor.id, visibility=visibility,
            status=ResourceStatus.ACTIVE.value,
        )
        self.db.add(res)
        self.db.flush()
        record_resource_event(self.db, ResourceAuditEvent.RESOURCE_REGISTERED,
                              organization_id=actor.organization_id, actor_id=actor.id,
                              meta={"resource_pk": str(res.id), "resource_type": resource_type,
                                    "resource_id": str(external_id)})
        return res


class _ResourceScoped:
    """Shared helpers for the per-resource management services."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.registry = ResourceRegistryService(db)
        self.members = MembershipResolver(db)

    # --- ownership (§6, §7) ------------------------------------------------ #
    def is_owner(self, actor: User, res: ProtectedResource) -> bool:
        ot = res.owner_type
        if ot in (OwnerType.USER.value, OwnerType.SERVICE_ACCOUNT.value):
            return res.owner_id == actor.id
        if ot == OwnerType.TEAM.value:
            return self.members.in_team(actor, res.owner_id)
        if ot == OwnerType.DEPARTMENT.value:
            return self.members.in_department(actor, res.owner_id)
        if ot == OwnerType.ORGANIZATION.value:
            return actor.organization_id == res.owner_id
        return False

    def _has_manage_share_or_delegation(self, actor: User, res: ProtectedResource) -> bool:
        now_ok = _not_expired
        for share in self.db.execute(
            select(ResourceShare).where(ResourceShare.resource_id == res.id,
                                        ResourceShare.access_level == ShareAccessLevel.MANAGE.value)
        ).scalars():
            if now_ok(share.expires_at) and self.members.matches(
                actor, share.shared_with_type, share.shared_with_id
            ):
                return True
        for d in self.db.execute(
            select(ResourceDelegation).where(
                ResourceDelegation.resource_id == res.id,
                ResourceDelegation.delegate_id == actor.id,
                ResourceDelegation.status == DelegationStatus.ACTIVE.value,
            )
        ).scalars():
            if now_ok(d.expires_at) and any(
                p == "*" or p.lower() in ("manage", f"{res.resource_type}.manage")
                for p in (d.permissions or [])
            ):
                return True
        return False

    def can_manage(self, actor: User, res: ProtectedResource, *,
                   has_manage_permission: bool) -> bool:
        """§7/§22 — owner, platform resource administrator, a MANAGE share, or a
        manage delegation may administer the resource's authorization metadata."""
        if res.organization_id != actor.organization_id and not has_manage_permission:
            return False
        return (
            has_manage_permission
            or self.is_owner(actor, res)
            or self._has_manage_share_or_delegation(actor, res)
        )

    def assert_can_manage(self, actor: User, res: ProtectedResource, *,
                          has_manage_permission: bool) -> None:
        if not self.can_manage(actor, res, has_manage_permission=has_manage_permission):
            raise IdentityError(ErrorCode.RESOURCE_OWNER_REQUIRED,
                                "Only the owner or a resource administrator may do this.")

    def _actor_is_platform_admin(self, actor: User) -> bool:
        """§22.1 — a user holding the global wildcard grant."""
        grants = PermissionEngine(self.db).resolve_grants(actor)
        return any(g.pattern == GLOBAL_WILDCARD for g in grants)


# --------------------------------------------------------------------------- #
# ACL (§10, §11)
# --------------------------------------------------------------------------- #
class ResourceACLService(_ResourceScoped):
    def list(self, res: ProtectedResource) -> list[ResourceACLEntry]:
        return list(self.db.execute(
            select(ResourceACLEntry).where(ResourceACLEntry.resource_id == res.id)
            .order_by(ResourceACLEntry.created_at.desc())
        ).scalars())

    def add(
        self, actor: User, res: ProtectedResource, *, principal_type: str,
        principal_id: uuid.UUID, permission: str, effect: str,
        expires_at: datetime | None, has_manage_permission: bool,
    ) -> ResourceACLEntry:
        self.assert_can_manage(actor, res, has_manage_permission=has_manage_permission)
        try:
            PrincipalType(principal_type.upper())
            effect_v = ACLEffect(effect.upper()).value
        except ValueError as exc:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "Unknown principal type or effect.") from exc
        self._guard_platform_admin_deny(res, principal_type, principal_id, effect_v)
        entry = ResourceACLEntry(
            resource_id=res.id, principal_type=principal_type.upper(),
            principal_id=principal_id, permission=permission, effect=effect_v,
            expires_at=expires_at, created_by=actor.id,
        )
        self.db.add(entry)
        self.db.flush()
        record_resource_event(self.db, ResourceAuditEvent.RESOURCE_ACL_CREATED,
                              organization_id=res.organization_id, actor_id=actor.id,
                              meta={"resource_pk": str(res.id), "acl_id": str(entry.id),
                                    "principal_type": entry.principal_type,
                                    "principal_id": str(principal_id),
                                    "permission": permission, "effect": effect_v})
        return entry

    def update(
        self, actor: User, res: ProtectedResource, acl_id: uuid.UUID, *,
        permission: str | None, effect: str | None, expires_at: datetime | None,
        has_manage_permission: bool,
    ) -> ResourceACLEntry:
        self.assert_can_manage(actor, res, has_manage_permission=has_manage_permission)
        entry = self._get(res, acl_id)
        if effect is not None:
            try:
                effect_v = ACLEffect(effect.upper()).value
            except ValueError as exc:
                raise IdentityError(ErrorCode.VALIDATION_ERROR, "Unknown effect.") from exc
            self._guard_platform_admin_deny(res, entry.principal_type, entry.principal_id, effect_v)
            entry.effect = effect_v
        if permission is not None:
            entry.permission = permission
        if expires_at is not None:
            entry.expires_at = expires_at
        self.db.flush()
        record_resource_event(self.db, ResourceAuditEvent.RESOURCE_ACL_UPDATED,
                              organization_id=res.organization_id, actor_id=actor.id,
                              meta={"resource_pk": str(res.id), "acl_id": str(entry.id)})
        return entry

    def remove(self, actor: User, res: ProtectedResource, acl_id: uuid.UUID, *,
               has_manage_permission: bool) -> None:
        self.assert_can_manage(actor, res, has_manage_permission=has_manage_permission)
        entry = self._get(res, acl_id)
        self.db.delete(entry)
        self.db.flush()
        record_resource_event(self.db, ResourceAuditEvent.RESOURCE_ACL_DELETED,
                              organization_id=res.organization_id, actor_id=actor.id,
                              meta={"resource_pk": str(res.id), "acl_id": str(acl_id)})

    def _get(self, res: ProtectedResource, acl_id: uuid.UUID) -> ResourceACLEntry:
        entry = self.db.get(ResourceACLEntry, acl_id)
        if entry is None or entry.resource_id != res.id:
            raise IdentityError(ErrorCode.ACL_ENTRY_NOT_FOUND, "ACL entry not found.")
        return entry

    def _guard_platform_admin_deny(
        self, res: ProtectedResource, principal_type: str, principal_id: uuid.UUID,
        effect: str,
    ) -> None:
        """§22.1 — on system-level resources, a DENY entry may not target a
        platform administrator."""
        if effect != ACLEffect.DENY.value or res.status != ResourceStatus.SYSTEM.value:
            return
        if principal_type.upper() not in (PrincipalType.USER.value,
                                          PrincipalType.SERVICE_ACCOUNT.value):
            return
        target = self.db.get(User, principal_id)
        if target is not None and self._actor_is_platform_admin(target):
            raise IdentityError(
                ErrorCode.SYSTEM_ROLE_PROTECTED,
                "Platform administrators cannot be denied on system-level resources.",
            )


# --------------------------------------------------------------------------- #
# Sharing (§12)
# --------------------------------------------------------------------------- #
class ResourceSharingService(_ResourceScoped):
    def list(self, res: ProtectedResource) -> list[ResourceShare]:
        return list(self.db.execute(
            select(ResourceShare).where(ResourceShare.resource_id == res.id)
            .order_by(ResourceShare.created_at.desc())
        ).scalars())

    def share(
        self, actor: User, res: ProtectedResource, *, shared_with_type: str,
        shared_with_id: uuid.UUID, access_level: str, expires_at: datetime | None,
        has_manage_permission: bool,
    ) -> ResourceShare:
        self.assert_can_manage(actor, res, has_manage_permission=has_manage_permission)
        try:
            level = ShareAccessLevel(access_level.upper()).value
            swt = PrincipalType(shared_with_type.upper()).value
        except ValueError as exc:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "Unknown share target or access level.") from exc
        self._assert_same_org_target(actor, swt, shared_with_id)
        share = ResourceShare(
            resource_id=res.id, shared_with_type=swt, shared_with_id=shared_with_id,
            access_level=level, expires_at=expires_at, created_by=actor.id,
        )
        self.db.add(share)
        self.db.flush()
        record_resource_event(self.db, ResourceAuditEvent.RESOURCE_SHARED,
                              organization_id=res.organization_id, actor_id=actor.id,
                              meta={"resource_pk": str(res.id), "share_id": str(share.id),
                                    "shared_with_type": swt, "shared_with_id": str(shared_with_id),
                                    "access_level": level})
        return share

    def update(
        self, actor: User, res: ProtectedResource, share_id: uuid.UUID, *,
        access_level: str | None, expires_at: datetime | None,
        has_manage_permission: bool,
    ) -> ResourceShare:
        self.assert_can_manage(actor, res, has_manage_permission=has_manage_permission)
        share = self._get(res, share_id)
        if access_level is not None:
            try:
                share.access_level = ShareAccessLevel(access_level.upper()).value
            except ValueError as exc:
                raise IdentityError(ErrorCode.VALIDATION_ERROR, "Unknown access level.") from exc
        if expires_at is not None:
            share.expires_at = expires_at
        self.db.flush()
        record_resource_event(self.db, ResourceAuditEvent.RESOURCE_SHARE_UPDATED,
                              organization_id=res.organization_id, actor_id=actor.id,
                              meta={"resource_pk": str(res.id), "share_id": str(share.id)})
        return share

    def revoke(self, actor: User, res: ProtectedResource, share_id: uuid.UUID, *,
               has_manage_permission: bool) -> None:
        self.assert_can_manage(actor, res, has_manage_permission=has_manage_permission)
        share = self._get(res, share_id)
        self.db.delete(share)
        self.db.flush()
        record_resource_event(self.db, ResourceAuditEvent.RESOURCE_UNSHARED,
                              organization_id=res.organization_id, actor_id=actor.id,
                              meta={"resource_pk": str(res.id), "share_id": str(share_id)})

    def _get(self, res: ProtectedResource, share_id: uuid.UUID) -> ResourceShare:
        share = self.db.get(ResourceShare, share_id)
        if share is None or share.resource_id != res.id:
            raise IdentityError(ErrorCode.RESOURCE_NOT_SHARED, "Share not found.")
        return share

    def _assert_same_org_target(self, actor: User, swt: str, target_id: uuid.UUID) -> None:
        """§22.4 — cross-organization sharing is denied by default."""
        org_id: uuid.UUID | None
        if swt in (PrincipalType.USER.value, PrincipalType.SERVICE_ACCOUNT.value):
            target = self.db.get(User, target_id)
            org_id = target.organization_id if target else None
        elif swt == PrincipalType.DEPARTMENT.value:
            dept = self.db.get(Department, target_id)
            org_id = dept.organization_id if dept else None
        elif swt == PrincipalType.TEAM.value:
            team = self.db.get(Team, target_id)
            dept = self.db.get(Department, team.department_id) if team else None
            org_id = dept.organization_id if dept else None
        elif swt == PrincipalType.ORGANIZATION.value:
            org_id = target_id
        else:  # ROLE
            role = self.db.get(Role, target_id)
            org_id = role.organization_id if (role and role.organization_id) else actor.organization_id
        if org_id != actor.organization_id:
            raise IdentityError(ErrorCode.CROSS_ORGANIZATION_ACCESS_DENIED,
                                "Cross-organization sharing is not allowed.")


# --------------------------------------------------------------------------- #
# Ownership + transfer (§6–§8)
# --------------------------------------------------------------------------- #
class ResourceOwnershipService(_ResourceScoped):
    def history(self, res: ProtectedResource) -> list[OwnershipHistory]:
        return list(self.db.execute(
            select(OwnershipHistory).where(OwnershipHistory.resource_id == res.id)
            .order_by(OwnershipHistory.created_at.desc())
        ).scalars())

    def transfer(
        self, actor: User, res: ProtectedResource, *, new_owner_id: uuid.UUID,
        new_owner_type: str, reason: str | None, has_manage_permission: bool,
    ) -> ProtectedResource:
        # §8/§22 — transfer is owner/administrator only (a MANAGE share or manage
        # delegation is deliberately NOT enough).
        if not (has_manage_permission or self.is_owner(actor, res)):
            raise IdentityError(ErrorCode.OWNER_TRANSFER_NOT_ALLOWED,
                                "Only the owner or a resource administrator may transfer ownership.")
        try:
            not_ = OwnerType(new_owner_type.upper()).value
        except ValueError as exc:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "Unknown owner type.") from exc
        self._assert_target_in_org(actor, not_, new_owner_id)

        previous, previous_type = res.owner_id, res.owner_type
        res.owner_id, res.owner_type = new_owner_id, not_
        self.db.add(OwnershipHistory(
            resource_id=res.id, previous_owner=previous, previous_owner_type=previous_type,
            new_owner=new_owner_id, new_owner_type=not_, changed_by=actor.id, reason=reason,
        ))
        self.db.flush()
        record_resource_event(self.db, ResourceAuditEvent.RESOURCE_OWNER_CHANGED,
                              organization_id=res.organization_id, actor_id=actor.id,
                              meta={"resource_pk": str(res.id),
                                    "from": str(previous), "from_type": previous_type,
                                    "to": str(new_owner_id), "to_type": not_,
                                    "reason": reason})
        return res

    def _assert_target_in_org(self, actor: User, owner_type: str, owner_id: uuid.UUID) -> None:
        """The new owner must exist inside the actor's organization (§8, §22.4)."""
        if owner_type in (OwnerType.USER.value, OwnerType.SERVICE_ACCOUNT.value):
            target = self.db.get(User, owner_id)
            ok = target is not None and target.organization_id == actor.organization_id
        elif owner_type == OwnerType.TEAM.value:
            team = self.db.get(Team, owner_id)
            dept = self.db.get(Department, team.department_id) if team else None
            ok = dept is not None and dept.organization_id == actor.organization_id
        elif owner_type == OwnerType.DEPARTMENT.value:
            dept = self.db.get(Department, owner_id)
            ok = dept is not None and dept.organization_id == actor.organization_id
        else:  # ORGANIZATION
            ok = owner_id == actor.organization_id
        if not ok:
            raise IdentityError(ErrorCode.OWNER_TRANSFER_NOT_ALLOWED,
                                "The new owner must exist in your organization.")


# --------------------------------------------------------------------------- #
# Delegation (§13)
# --------------------------------------------------------------------------- #
class ResourceDelegationService(_ResourceScoped):
    def list(self, res: ProtectedResource) -> list[ResourceDelegation]:
        return list(self.db.execute(
            select(ResourceDelegation).where(ResourceDelegation.resource_id == res.id)
            .order_by(ResourceDelegation.created_at.desc())
        ).scalars())

    def delegate(
        self, actor: User, res: ProtectedResource, *, delegate_id: uuid.UUID,
        permissions: list[str], expires_at: datetime | None, reason: str | None,
        has_manage_permission: bool,
    ) -> ResourceDelegation:
        self.assert_can_manage(actor, res, has_manage_permission=has_manage_permission)
        if not permissions:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "Delegate at least one permission.")
        if expires_at is not None and not _not_expired(expires_at):
            raise IdentityError(ErrorCode.DELEGATION_EXPIRED, "The delegation expiry is in the past.")
        delegate = self.db.get(User, delegate_id)
        if delegate is None or delegate.organization_id != res.organization_id:
            raise IdentityError(ErrorCode.CROSS_ORGANIZATION_ACCESS_DENIED,
                                "The delegate must belong to the resource's organization.")
        d = ResourceDelegation(
            resource_id=res.id, delegate_id=delegate_id, permissions=permissions,
            expires_at=expires_at, status=DelegationStatus.ACTIVE.value, reason=reason,
            approved_by=actor.id, created_by=actor.id,
        )
        self.db.add(d)
        self.db.flush()
        record_resource_event(self.db, ResourceAuditEvent.RESOURCE_DELEGATED,
                              organization_id=res.organization_id, actor_id=actor.id,
                              meta={"resource_pk": str(res.id), "delegation_id": str(d.id),
                                    "delegate_id": str(delegate_id), "permissions": permissions,
                                    "reason": reason})
        return d

    def revoke(self, actor: User, res: ProtectedResource, delegation_id: uuid.UUID, *,
               has_manage_permission: bool) -> ResourceDelegation:
        self.assert_can_manage(actor, res, has_manage_permission=has_manage_permission)
        d = self.db.get(ResourceDelegation, delegation_id)
        if d is None or d.resource_id != res.id:
            raise IdentityError(ErrorCode.DELEGATION_NOT_FOUND, "Delegation not found.")
        if d.status == DelegationStatus.ACTIVE.value:
            d.status = DelegationStatus.REVOKED.value
            self.db.flush()
            record_resource_event(self.db, ResourceAuditEvent.RESOURCE_DELEGATION_REVOKED,
                                  organization_id=res.organization_id, actor_id=actor.id,
                                  meta={"resource_pk": str(res.id), "delegation_id": str(d.id)})
        return d

    def active_for(self, res: ProtectedResource, user_id: uuid.UUID) -> list[ResourceDelegation]:
        return [
            d for d in self.db.execute(
                select(ResourceDelegation).where(
                    ResourceDelegation.resource_id == res.id,
                    ResourceDelegation.delegate_id == user_id,
                    ResourceDelegation.status == DelegationStatus.ACTIVE.value,
                )
            ).scalars()
            if _not_expired(d.expires_at)  # §22.6 — expired delegations are ignored
        ]


# --------------------------------------------------------------------------- #
# Resource policy (§14)
# --------------------------------------------------------------------------- #
class ResourcePolicyService(_ResourceScoped):
    """A resource policy is a list of rules
    ``{"permission": <code|action|*>, "principal_type": ..., "principal_id": ...}``.
    When any rule names the requested permission, only matching principals may
    perform it — evaluated after role permissions (§14)."""

    def set_policy(self, actor: User, res: ProtectedResource, policy: list[dict] | None, *,
                   has_manage_permission: bool) -> ProtectedResource:
        self.assert_can_manage(actor, res, has_manage_permission=has_manage_permission)
        for rule in policy or []:
            if not isinstance(rule, dict) or "permission" not in rule:
                raise IdentityError(ErrorCode.VALIDATION_ERROR,
                                    "Each policy rule needs at least a 'permission'.")
        res.policy = policy
        self.db.flush()
        record_resource_event(self.db, ResourceAuditEvent.RESOURCE_POLICY_UPDATED,
                              organization_id=res.organization_id, actor_id=actor.id,
                              meta={"resource_pk": str(res.id), "rules": len(policy or [])})
        return res

    def evaluate(self, actor: User, res: ProtectedResource, permission: str) -> bool | None:
        """None = no rule constrains this permission; True/False = constrained and
        the actor does/doesn't satisfy at least one matching rule."""
        rules = [r for r in (res.policy or [])
                 if permission_covers(str(r.get("permission", "")), permission)]
        if not rules:
            return None
        for rule in rules:
            pt, pid = rule.get("principal_type"), rule.get("principal_id")
            if not pt or not pid:
                continue
            try:
                pid_u = uuid.UUID(str(pid))
            except ValueError:
                continue
            if self.members.matches(actor, str(pt), pid_u):
                return True
        return False


# --------------------------------------------------------------------------- #
# The complete evaluation (§5, §11, §18)
# --------------------------------------------------------------------------- #
@dataclass
class ResourceDecision:
    allowed: bool
    permission: str
    reason: str
    # OWNER / ACL / DELEGATION / SHARE / ROLE / VISIBILITY / ROLE_DENY / ACL_DENY /
    # POLICY_DENY / CROSS_ORG_DENY / DEFAULT_DENY
    source: str
    error_code: str | None = None
    # Inspector fields (§21).
    resource_pk: uuid.UUID | None = None
    resource_type: str | None = None
    owner_id: uuid.UUID | None = None
    owner_type: str | None = None
    visibility: str | None = None
    scope: str | None = None
    source_role: str | None = None
    matched_rule_id: uuid.UUID | None = None
    steps: list[str] = field(default_factory=list)


class ResourceAuthorizationService(_ResourceScoped):
    """§17 — coordinates the complete authorization evaluation for one resource,
    layering ownership, ACL, delegation, sharing, policy and visibility over the
    Permission Engine's role decision."""

    def authorize(
        self, actor: User, permission: str, res: ProtectedResource, *,
        record: bool = True,
    ) -> ResourceDecision:
        d = self._evaluate(actor, permission, res)
        if record:
            event = (ResourceAuditEvent.RESOURCE_ACCESS_GRANTED if d.allowed
                     else ResourceAuditEvent.RESOURCE_ACCESS_DENIED)
            record_resource_event(self.db, event,
                                  organization_id=res.organization_id, actor_id=actor.id,
                                  meta={"resource_pk": str(res.id), "permission": permission,
                                        "source": d.source, "reason": d.reason})
        return d

    def _evaluate(self, actor: User, permission: str, res: ProtectedResource) -> ResourceDecision:
        steps: list[str] = ["IDENTITY_VERIFIED"]
        action = action_of(permission)

        def decision(allowed: bool, reason: str, source: str, **kw) -> ResourceDecision:
            return ResourceDecision(
                allowed=allowed, permission=permission, reason=reason, source=source,
                resource_pk=res.id, resource_type=res.resource_type,
                owner_id=res.owner_id, owner_type=res.owner_type,
                visibility=res.visibility, steps=steps, **kw,
            )

        # 1–2. Organization scope (§5.2, §22.4).
        steps.append("ORG_SCOPE_RESOLVED")
        grants = PermissionEngine(self.db).resolve_grants(actor)
        if res.organization_id != actor.organization_id:
            if res.visibility == VisibilityLevel.PUBLIC_INTERNAL.value and action in VIEW_ACTIONS:
                steps.append("VISIBILITY_EVALUATED")
                return decision(True, "Public internal resource", "VISIBILITY")
            if not any(g.pattern == GLOBAL_WILDCARD for g in grants):
                steps.append("CROSS_ORG_DENIED")
                return decision(False, "Cross-organization access denied", "CROSS_ORG_DENY",
                                error_code=ErrorCode.CROSS_ORGANIZATION_ACCESS_DENIED)

        # 3–4. Roles + inherited permissions through the Permission Engine (§5.3–4).
        ctx = self._resource_context(res)
        rbac = PermissionEngine(self.db).evaluate(actor, permission, grants, ctx)
        steps.append("ROLES_RESOLVED")
        if not rbac.allowed and rbac.reason.startswith("Explicitly denied"):
            # §7 — nobody, including the owner, bypasses a global explicit deny.
            steps.append("EXPLICIT_DENY_APPLIED")
            return decision(False, rbac.reason, "ROLE_DENY",
                            error_code=ErrorCode.RESOURCE_ACCESS_DENIED,
                            scope=rbac.scope, source_role=rbac.source_role)

        # 6 + §11 priority: explicit ACL DENY overrides every allow.
        acl_entries = self._live_acl(res)
        deny = self._first_matching(actor, res, acl_entries, permission, ACLEffect.DENY.value)
        if deny is not None:
            steps.append("ACL_DENY_APPLIED")
            return decision(False, "Explicitly denied by ACL", "ACL_DENY",
                            error_code=ErrorCode.RESOURCE_ACCESS_DENIED,
                            matched_rule_id=deny.id)

        # Resource policy (§14) — a restriction, so it binds even privileged paths.
        policy_ok = ResourcePolicyService(self.db).evaluate(actor, res, permission)
        if policy_ok is False:
            steps.append("POLICY_DENIED")
            return decision(False, "Denied by resource policy", "POLICY_DENY",
                            error_code=ErrorCode.RESOURCE_POLICY_DENIED)
        if policy_ok is True:
            steps.append("POLICY_SATISFIED")

        # 5. Ownership (§5.5, §7) — the owner may do everything on their resource.
        if self.is_owner(actor, res):
            steps.append("OWNERSHIP_MATCHED")
            return decision(True, "Granted by resource ownership", "OWNER")

        # 6. Explicit ACL ALLOW (§5.6, §11).
        allow = self._first_matching(actor, res, acl_entries, permission, ACLEffect.ALLOW.value)
        if allow is not None:
            steps.append("ACL_ALLOW_MATCHED")
            return decision(True, "Granted via ACL", "ACL", matched_rule_id=allow.id)

        # 7. Delegation (§5.7, §13). A "manage" delegation covers every action
        # (like a MANAGE share); anything else matches code/action-wise.
        for deleg in ResourceDelegationService(self.db).active_for(res, actor.id):
            if any(
                permission_covers(str(p), permission)
                or str(p).lower() in ("manage", f"{res.resource_type}.manage")
                for p in (deleg.permissions or [])
            ):
                steps.append("DELEGATION_MATCHED")
                return decision(True, "Granted via delegation", "DELEGATION",
                                matched_rule_id=deleg.id)

        # 8. Sharing (§12).
        share = self._matching_share(actor, res, action)
        if share is not None:
            steps.append("SHARE_MATCHED")
            return decision(True, f"Granted via {share.access_level} share", "SHARE",
                            matched_rule_id=share.id)

        # Inherited role permission (§11.3).
        if rbac.allowed:
            steps.append("ROLE_PERMISSION_MATCHED")
            return decision(True, rbac.reason, "ROLE",
                            scope=rbac.scope, source_role=rbac.source_role)

        # 9. Visibility (§5.8, §9, §11.4) — read access only.
        if action in VIEW_ACTIONS and self._visible_to(actor, res):
            steps.append("VISIBILITY_EVALUATED")
            return decision(True, f"Granted by {res.visibility} visibility", "VISIBILITY")

        # 10–11. Default deny (§5.11, §22.7).
        steps.append("DEFAULT_DENY")
        return decision(False, "Resource access denied", "DEFAULT_DENY",
                        error_code=ErrorCode.RESOURCE_ACCESS_DENIED)

    # --- helpers ------------------------------------------------------------ #
    def _resource_context(self, res: ProtectedResource) -> ResourceContext:
        """Build the engine context from the 4.3.3 ownership path when present."""
        from app.authorization.hierarchy.services import (
            ResourceOwnershipService as PathService,
        )

        path = PathService(self.db).resolve_path(res.resource_type, res.resource_id) or {}
        return ResourceContext(
            organization_id=path.get("organization_id") or res.organization_id,
            business_unit_id=path.get("business_unit_id"),
            department_id=path.get("department_id"),
            team_id=path.get("team_id"),
            project_id=path.get("project_id") or res.project_id,
            resource_type=res.resource_type, resource_id=res.resource_id,
        )

    def _live_acl(self, res: ProtectedResource) -> list[ResourceACLEntry]:
        # §22.5 — expired ACL entries are ignored.
        return [e for e in ResourceACLService(self.db).list(res) if _not_expired(e.expires_at)]

    def _first_matching(
        self, actor: User, res: ProtectedResource, entries: list[ResourceACLEntry],
        permission: str, effect: str,
    ) -> ResourceACLEntry | None:
        for e in entries:
            if e.effect != effect or not permission_covers(e.permission, permission):
                continue
            if not self.members.matches(actor, e.principal_type, e.principal_id):
                continue
            # §22.1 — a DENY never binds a platform admin on a system resource.
            if (effect == ACLEffect.DENY.value
                    and res.status == ResourceStatus.SYSTEM.value
                    and self._actor_is_platform_admin(actor)):
                continue
            return e
        return None

    def _matching_share(self, actor: User, res: ProtectedResource, action: str) -> ResourceShare | None:
        for share in ResourceSharingService(self.db).list(res):
            if not _not_expired(share.expires_at):
                continue
            allowed = _SHARE_ACTIONS.get(share.access_level, set())
            if "*" not in allowed and action not in allowed:
                continue
            if self.members.matches(actor, share.shared_with_type, share.shared_with_id):
                return share
        return None

    def _visible_to(self, actor: User, res: ProtectedResource) -> bool:
        vis = res.visibility
        if vis == VisibilityLevel.PUBLIC_INTERNAL.value:
            return True
        if res.organization_id != actor.organization_id:
            return False
        if vis == VisibilityLevel.ORGANIZATION.value:
            return True
        path = self._resource_context(res)
        if vis == VisibilityLevel.DEPARTMENT.value and path.department_id is not None:
            return self.members.in_department(actor, path.department_id)
        if vis == VisibilityLevel.TEAM.value and path.team_id is not None:
            return self.members.in_team(actor, path.team_id)
        return False
