"""Enterprise authorization API (Phase 4.3.1 §20).

Roles, permissions, permission groups, scoped role assignments, role hierarchy
and the authorization audit trail — all under ``/api/v1`` and permission-gated:
``role.view`` to read, ``role.manage`` to change roles/permissions/hierarchy,
``role.assign`` to assign roles.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.authorization.repositories import (
    AuthorizationAuditRepository,
    RoleAssignmentRepository,
    RoleHierarchyRepository,
    RoleRepository,
)
from app.authorization.schemas import (
    AuthorizationAuditRead,
    AuthorizationCheckRequest,
    AuthorizationCheckResponse,
    EffectivePermissionsRead,
    PermissionCreate,
    PermissionGroupRead,
    PermissionRead,
    PermissionUpdate,
    RoleAssignmentCreate,
    RoleAssignmentRead,
    RoleCreate,
    RoleHierarchyCreate,
    RoleHierarchyRead,
    RoleRead,
    RoleUpdate,
)
from app.authorization.services import (
    PermissionGroupService,
    PermissionService,
    RoleAssignmentService,
    RoleHierarchyService,
    RoleService,
)
from sqlalchemy import select

from app.core.database import get_db
from app.identity.api.deps import get_current_user, require_permission
from app.models.rbac import RbacPermission, Role, RolePermission
from app.models.user import User

router = APIRouter(prefix="/api/v1", tags=["authorization"])

_VIEW = "role.view"
_MANAGE = "role.manage"
_ASSIGN = "role.assign"


def _commit_invalidating(db: Session, organization_id) -> None:
    """Commit a mutation and invalidate the org's permission cache (§10, §26).

    System/global roles are permission-protected, so only org-scoped changes alter
    grants at runtime — bumping the acting org's version is sufficient and immediate.
    """
    from app.authorization.cache import PermissionCacheService

    PermissionCacheService(db).bump_version(organization_id)
    db.commit()


def _role_read(role: Role, db: Session, *, assignment_count: int | None = None) -> RoleRead:
    rows = db.execute(
        select(RbacPermission.code, RolePermission.effect)
        .join(RolePermission, RolePermission.permission_id == RbacPermission.id)
        .where(RolePermission.role_id == role.id)
    ).all()
    allow = sorted(code for code, effect in rows if effect != "DENY")
    deny = sorted(code for code, effect in rows if effect == "DENY")
    return RoleRead(
        id=role.id,
        organization_id=role.organization_id,
        name=role.name,
        display_name=role.display_name,
        description=role.description,
        category=role.category,
        status=role.status,
        is_system=role.is_system,
        is_assignable=role.is_assignable,
        priority=role.priority,
        permissions=allow,
        denied_permissions=deny,
        assignment_count=assignment_count,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
@router.get("/roles", response_model=list[RoleRead])
def list_roles(
    category: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
) -> list[RoleRead]:
    roles = RoleRepository(db).list_visible(
        actor.organization_id, category=category, status=status_filter, search=search
    )
    return [_role_read(role, db) for role in roles]


@router.post("/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
def create_role(
    payload: RoleCreate,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
) -> RoleRead:
    role = RoleService(db).create(
        name=payload.name, display_name=payload.display_name, description=payload.description,
        category=payload.category, priority=payload.priority,
        permission_codes=payload.permissions, denied_permission_codes=payload.denied_permissions,
        organization_id=actor.organization_id, actor_id=actor.id,
    )
    _commit_invalidating(db, actor.organization_id)
    return _role_read(role, db)


@router.get("/roles/{role_id}", response_model=RoleRead)
def get_role(
    role_id: uuid.UUID,
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
) -> RoleRead:
    svc = RoleService(db)
    role = svc.get_or_404(role_id, actor.organization_id)
    return _role_read(role, db, assignment_count=svc.repo.assignment_count(role.id))


@router.put("/roles/{role_id}", response_model=RoleRead)
def update_role(
    role_id: uuid.UUID,
    payload: RoleUpdate,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
) -> RoleRead:
    svc = RoleService(db)
    role = svc.get_or_404(role_id, actor.organization_id)
    svc.update(
        role, display_name=payload.display_name, description=payload.description,
        priority=payload.priority, status=payload.status, permission_codes=payload.permissions,
        denied_permission_codes=payload.denied_permissions,
        actor_id=actor.id, organization_id=actor.organization_id,
    )
    _commit_invalidating(db, actor.organization_id)
    return _role_read(role, db)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_role(
    role_id: uuid.UUID,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
) -> Response:
    svc = RoleService(db)
    role = svc.get_or_404(role_id, actor.organization_id)
    svc.delete(role, actor_id=actor.id, organization_id=actor.organization_id)
    _commit_invalidating(db, actor.organization_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/roles/{role_id}/effective-permissions", response_model=EffectivePermissionsRead)
def role_effective_permissions(
    role_id: uuid.UUID,
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
) -> EffectivePermissionsRead:
    """A role's own permissions plus everything it inherits via the hierarchy (§17)."""
    RoleService(db).get_or_404(role_id, actor.organization_id)
    codes = RoleHierarchyService(db).resolve_effective_permissions(role_id)
    return EffectivePermissionsRead(role_id=role_id, permissions=sorted(codes))


# --------------------------------------------------------------------------- #
# Permissions & groups
# --------------------------------------------------------------------------- #
@router.get("/permissions", response_model=list[PermissionRead])
def list_permissions(
    group_id: uuid.UUID | None = Query(default=None),
    search: str | None = Query(default=None),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
) -> list[PermissionRead]:
    return PermissionService(db).repo.list(group_id=group_id, search=search)


@router.post("/permissions", response_model=PermissionRead, status_code=status.HTTP_201_CREATED)
def create_permission(
    payload: PermissionCreate,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
) -> PermissionRead:
    perm = PermissionService(db).create(
        code=payload.code, description=payload.description, display_name=payload.display_name,
        group_id=payload.group_id, actor_id=actor.id, organization_id=actor.organization_id,
    )
    _commit_invalidating(db, actor.organization_id)
    return perm


@router.put("/permissions/{permission_id}", response_model=PermissionRead)
def update_permission(
    permission_id: uuid.UUID,
    payload: PermissionUpdate,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
) -> PermissionRead:
    perm = PermissionService(db).update(
        permission_id, description=payload.description, display_name=payload.display_name,
        group_id=payload.group_id, actor_id=actor.id, organization_id=actor.organization_id,
    )
    _commit_invalidating(db, actor.organization_id)
    return perm


@router.delete("/permissions/{permission_id}", status_code=status.HTTP_204_NO_CONTENT,
               response_class=Response)
def delete_permission(
    permission_id: uuid.UUID,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
) -> Response:
    PermissionService(db).delete(
        permission_id, actor_id=actor.id, organization_id=actor.organization_id
    )
    _commit_invalidating(db, actor.organization_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/permission-groups", response_model=list[PermissionGroupRead])
def list_permission_groups(
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
) -> list[PermissionGroupRead]:
    return PermissionGroupService(db).list()


# --------------------------------------------------------------------------- #
# Role assignments
# --------------------------------------------------------------------------- #
@router.get("/role-assignments", response_model=list[RoleAssignmentRead])
def list_role_assignments(
    user_id: uuid.UUID | None = Query(default=None),
    role_id: uuid.UUID | None = Query(default=None),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
) -> list[RoleAssignmentRead]:
    return RoleAssignmentRepository(db).list(user_id=user_id, role_id=role_id)


@router.post("/role-assignments", response_model=RoleAssignmentRead,
             status_code=status.HTTP_201_CREATED)
def create_role_assignment(
    payload: RoleAssignmentCreate,
    actor: User = Depends(require_permission(_ASSIGN)),
    db: Session = Depends(get_db),
) -> RoleAssignmentRead:
    assignment = RoleAssignmentService(db).assign(
        user_id=payload.user_id, role_id=payload.role_id, scope=payload.scope,
        organization_id=actor.organization_id, department_id=payload.department_id,
        team_id=payload.team_id, project_id=payload.project_id,
        resource_type=payload.resource_type, resource_id=payload.resource_id,
        expires_at=payload.expires_at, actor_id=actor.id,
    )
    _commit_invalidating(db, actor.organization_id)
    return assignment


@router.delete("/role-assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT,
               response_class=Response)
def delete_role_assignment(
    assignment_id: uuid.UUID,
    actor: User = Depends(require_permission(_ASSIGN)),
    db: Session = Depends(get_db),
) -> Response:
    RoleAssignmentService(db).remove(
        assignment_id, organization_id=actor.organization_id, actor_id=actor.id
    )
    _commit_invalidating(db, actor.organization_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Role hierarchy
# --------------------------------------------------------------------------- #
@router.get("/role-hierarchy", response_model=list[RoleHierarchyRead])
def list_role_hierarchy(
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
) -> list[RoleHierarchyRead]:
    return RoleHierarchyRepository(db).list()


@router.post("/role-hierarchy", response_model=RoleHierarchyRead,
             status_code=status.HTTP_201_CREATED)
def create_role_hierarchy(
    payload: RoleHierarchyCreate,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
) -> RoleHierarchyRead:
    edge = RoleHierarchyService(db).add_edge(
        payload.parent_role_id, payload.child_role_id,
        organization_id=actor.organization_id, actor_id=actor.id,
    )
    _commit_invalidating(db, actor.organization_id)
    return edge


@router.delete("/role-hierarchy/{edge_id}", status_code=status.HTTP_204_NO_CONTENT,
               response_class=Response)
def delete_role_hierarchy(
    edge_id: uuid.UUID,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
) -> Response:
    RoleHierarchyService(db).remove_edge(
        edge_id, organization_id=actor.organization_id, actor_id=actor.id
    )
    _commit_invalidating(db, actor.organization_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Permission engine: authorization check (§22)
# --------------------------------------------------------------------------- #
@router.post("/authorization/check", response_model=AuthorizationCheckResponse)
def authorization_check(
    payload: AuthorizationCheckRequest,
    request: Request,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuthorizationCheckResponse:
    """Evaluate whether the caller holds a permission (optionally on a resource).
    Phase 4.3.6 (§22): the route is a thin enforcement point — the
    ``AuthorizationGateway`` runs the full deterministic pipeline (organization
    context, RBAC/resource baseline, ABAC, obligations, audit, cache) and this
    endpoint just maps the normalized decision onto the response schema."""
    from app.authorization.middleware.gateway import AuthorizationGateway

    decision = AuthorizationGateway(db).authorize(
        actor, payload.permission,
        resource_type=payload.resource_type, resource_id=payload.resource_id,
        context=payload.context,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=request.headers.get("x-request-id"),
        correlation_id=request.headers.get("x-correlation-id"),
        justification=request.headers.get("x-justification"),
        force_record=True,  # the explicit check endpoint always records (4.3.2 §20)
    )
    return AuthorizationCheckResponse(
        allowed=decision.allowed, permission=decision.permission,
        reason=decision.reason, scope=decision.scope,
        source_role=decision.source_role,
        evaluation_time_ms=decision.evaluation_time_ms,
        cache_hit=decision.cache_hit, events=decision.events,
        decision=decision.decision, obligations=decision.obligations,
    )


# --------------------------------------------------------------------------- #
# Authorization audit
# --------------------------------------------------------------------------- #
@router.get("/authorization/audit", response_model=list[AuthorizationAuditRead])
def list_authorization_audit(
    event_type: str | None = Query(default=None),
    identity_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
) -> list[AuthorizationAuditRead]:
    return AuthorizationAuditRepository(db).list(
        actor.organization_id, event_type=event_type, identity_id=identity_id, limit=limit
    )
