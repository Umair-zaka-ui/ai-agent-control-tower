"""Resource-based authorization API (Phase 4.3.4 §19).

The resource registry plus per-resource ownership, ACL, sharing, delegation,
policy and the authorization/inspector endpoint — all under ``/api/v1``.

Gating: registration and per-resource management use ``get_current_user`` plus
service-level checks (§7 owners administer their own resources; ``resource.manage``
administers any). Read endpoints require view access to the resource's metadata:
owner, manager, or the ``resource.view`` permission.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.authorization.resources.schemas import (
    ACLEntryCreate,
    ACLEntryRead,
    ACLEntryUpdate,
    AuthorizeRequest,
    AuthorizeResponse,
    OwnerRead,
    OwnershipHistoryRead,
    OwnershipTransferRequest,
    PolicyWrite,
    ResourceDelegationCreate,
    ResourceDelegationRead,
    ResourceRead,
    ResourceRegister,
    ResourceUpdate,
    ShareCreate,
    ShareRead,
    ShareUpdate,
)
from app.authorization.resources.enums import ResourceAuditEvent, ResourceType, VisibilityLevel
from app.authorization.resources.services import (
    ResourceACLService,
    ResourceAuthorizationService,
    ResourceDelegationService,
    ResourceOwnershipService,
    ResourcePolicyService,
    ResourceRegistryService,
    ResourceSharingService,
    record_resource_event,
)
from app.core.database import get_db
from app.identity.api.deps import get_current_user
from app.identity.errors import ErrorCode, IdentityError
from app.models.resource_authorization import ProtectedResource
from app.models.user import User
from app.services.rbac_service import user_has_permission

router = APIRouter(prefix="/api/v1", tags=["resource-authorization"])

_VIEW = "resource.view"
_MANAGE = "resource.manage"


def _can(db: Session, actor: User, permission: str) -> bool:
    return user_has_permission(db, actor, permission)


def _get_resource(db: Session, actor: User, resource_pk: uuid.UUID) -> ProtectedResource:
    return ResourceRegistryService(db).get(actor, resource_pk)


def _assert_meta_view(db: Session, actor: User, res: ProtectedResource) -> None:
    """Reading a resource's authorization metadata: owner/manager or resource.view."""
    svc = ResourceACLService(db)
    if _can(db, actor, _VIEW) or svc.can_manage(actor, res, has_manage_permission=False):
        return
    raise IdentityError(ErrorCode.RESOURCE_ACCESS_DENIED,
                        "You may not view this resource's authorization metadata.")


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
@router.get("/resources/types", response_model=list[str])
def list_resource_types(actor: User = Depends(get_current_user)) -> list[str]:
    """§3 — the built-in resource-type catalog (free-form types also accepted)."""
    return [t.value for t in ResourceType]


@router.get("/resources", response_model=list[ResourceRead])
def list_resources(
    resource_type: str | None = Query(default=None),
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> list[ProtectedResource]:
    return ResourceRegistryService(db).list(
        actor, can_view_all=_can(db, actor, _VIEW), resource_type=resource_type
    )


@router.post("/resources", response_model=ResourceRead, status_code=status.HTTP_201_CREATED)
def register_resource(
    payload: ResourceRegister,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> ProtectedResource:
    res = ResourceRegistryService(db).register(
        actor, resource_type=payload.resource_type, resource_id=payload.resource_id,
        name=payload.name, visibility=payload.visibility, owner_id=payload.owner_id,
        owner_type=payload.owner_type, project_id=payload.project_id,
        can_manage_any=_can(db, actor, _MANAGE),
    )
    db.commit()
    return res


@router.get("/resources/{resource_pk}", response_model=ResourceRead)
def get_resource(
    resource_pk: uuid.UUID,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> ProtectedResource:
    res = _get_resource(db, actor, resource_pk)
    _assert_meta_view(db, actor, res)
    return res


@router.put("/resources/{resource_pk}", response_model=ResourceRead)
def update_resource(
    resource_pk: uuid.UUID, payload: ResourceUpdate,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> ProtectedResource:
    res = _get_resource(db, actor, resource_pk)
    svc = ResourceACLService(db)
    svc.assert_can_manage(actor, res, has_manage_permission=_can(db, actor, _MANAGE))
    if payload.name is not None:
        res.name = payload.name
    if payload.visibility is not None:
        try:
            res.visibility = VisibilityLevel(payload.visibility).value
        except ValueError as exc:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "Unknown visibility level.") from exc
        record_resource_event(db, ResourceAuditEvent.RESOURCE_VISIBILITY_CHANGED,
                              organization_id=res.organization_id, actor_id=actor.id,
                              meta={"resource_pk": str(res.id), "visibility": res.visibility})
    if payload.status is not None:
        res.status = payload.status
    db.commit()
    return res


# --------------------------------------------------------------------------- #
# Ownership (§6–§8, §19)
# --------------------------------------------------------------------------- #
@router.get("/resources/{resource_pk}/owner", response_model=OwnerRead)
def get_owner(
    resource_pk: uuid.UUID,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> OwnerRead:
    res = _get_resource(db, actor, resource_pk)
    _assert_meta_view(db, actor, res)
    return OwnerRead(resource_pk=res.id, owner_id=res.owner_id, owner_type=res.owner_type,
                     created_by=res.created_by)


@router.post("/resources/{resource_pk}/transfer-ownership", response_model=ResourceRead)
def transfer_ownership(
    resource_pk: uuid.UUID, payload: OwnershipTransferRequest,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> ProtectedResource:
    res = _get_resource(db, actor, resource_pk)
    res = ResourceOwnershipService(db).transfer(
        actor, res, new_owner_id=payload.new_owner_id, new_owner_type=payload.new_owner_type,
        reason=payload.reason, has_manage_permission=_can(db, actor, _MANAGE),
    )
    db.commit()
    return res


@router.get("/resources/{resource_pk}/ownership-history",
            response_model=list[OwnershipHistoryRead])
def ownership_history(
    resource_pk: uuid.UUID,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    res = _get_resource(db, actor, resource_pk)
    _assert_meta_view(db, actor, res)
    return ResourceOwnershipService(db).history(res)


# --------------------------------------------------------------------------- #
# ACL (§10, §19)
# --------------------------------------------------------------------------- #
@router.get("/resources/{resource_pk}/acl", response_model=list[ACLEntryRead])
def list_acl(
    resource_pk: uuid.UUID,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    res = _get_resource(db, actor, resource_pk)
    _assert_meta_view(db, actor, res)
    return ResourceACLService(db).list(res)


@router.post("/resources/{resource_pk}/acl", response_model=ACLEntryRead,
             status_code=status.HTTP_201_CREATED)
def add_acl_entry(
    resource_pk: uuid.UUID, payload: ACLEntryCreate,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    res = _get_resource(db, actor, resource_pk)
    entry = ResourceACLService(db).add(
        actor, res, principal_type=payload.principal_type, principal_id=payload.principal_id,
        permission=payload.permission, effect=payload.effect, expires_at=payload.expires_at,
        has_manage_permission=_can(db, actor, _MANAGE),
    )
    db.commit()
    return entry


@router.put("/resources/{resource_pk}/acl/{acl_id}", response_model=ACLEntryRead)
def update_acl_entry(
    resource_pk: uuid.UUID, acl_id: uuid.UUID, payload: ACLEntryUpdate,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    res = _get_resource(db, actor, resource_pk)
    entry = ResourceACLService(db).update(
        actor, res, acl_id, permission=payload.permission, effect=payload.effect,
        expires_at=payload.expires_at, has_manage_permission=_can(db, actor, _MANAGE),
    )
    db.commit()
    return entry


@router.delete("/resources/{resource_pk}/acl/{acl_id}",
               status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_acl_entry(
    resource_pk: uuid.UUID, acl_id: uuid.UUID,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> Response:
    res = _get_resource(db, actor, resource_pk)
    ResourceACLService(db).remove(actor, res, acl_id,
                                  has_manage_permission=_can(db, actor, _MANAGE))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Sharing (§12, §19)
# --------------------------------------------------------------------------- #
@router.get("/resources/{resource_pk}/shares", response_model=list[ShareRead])
def list_shares(
    resource_pk: uuid.UUID,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    res = _get_resource(db, actor, resource_pk)
    _assert_meta_view(db, actor, res)
    return ResourceSharingService(db).list(res)


@router.post("/resources/{resource_pk}/share", response_model=ShareRead,
             status_code=status.HTTP_201_CREATED)
def share_resource(
    resource_pk: uuid.UUID, payload: ShareCreate,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    res = _get_resource(db, actor, resource_pk)
    share = ResourceSharingService(db).share(
        actor, res, shared_with_type=payload.shared_with_type,
        shared_with_id=payload.shared_with_id, access_level=payload.access_level,
        expires_at=payload.expires_at, has_manage_permission=_can(db, actor, _MANAGE),
    )
    db.commit()
    return share


@router.put("/resources/{resource_pk}/share/{share_id}", response_model=ShareRead)
def update_share(
    resource_pk: uuid.UUID, share_id: uuid.UUID, payload: ShareUpdate,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    res = _get_resource(db, actor, resource_pk)
    share = ResourceSharingService(db).update(
        actor, res, share_id, access_level=payload.access_level,
        expires_at=payload.expires_at, has_manage_permission=_can(db, actor, _MANAGE),
    )
    db.commit()
    return share


@router.delete("/resources/{resource_pk}/share/{share_id}",
               status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def revoke_share(
    resource_pk: uuid.UUID, share_id: uuid.UUID,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> Response:
    res = _get_resource(db, actor, resource_pk)
    ResourceSharingService(db).revoke(actor, res, share_id,
                                      has_manage_permission=_can(db, actor, _MANAGE))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Delegation (§13, §19)
# --------------------------------------------------------------------------- #
@router.get("/resources/{resource_pk}/delegations",
            response_model=list[ResourceDelegationRead])
def list_delegations(
    resource_pk: uuid.UUID,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    res = _get_resource(db, actor, resource_pk)
    _assert_meta_view(db, actor, res)
    return ResourceDelegationService(db).list(res)


@router.post("/resources/{resource_pk}/delegate", response_model=ResourceDelegationRead,
             status_code=status.HTTP_201_CREATED)
def delegate_resource(
    resource_pk: uuid.UUID, payload: ResourceDelegationCreate,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    res = _get_resource(db, actor, resource_pk)
    d = ResourceDelegationService(db).delegate(
        actor, res, delegate_id=payload.delegate_id, permissions=payload.permissions,
        expires_at=payload.expires_at, reason=payload.reason,
        has_manage_permission=_can(db, actor, _MANAGE),
    )
    db.commit()
    return d


@router.delete("/resources/{resource_pk}/delegate/{delegation_id}",
               response_model=ResourceDelegationRead)
def revoke_delegation(
    resource_pk: uuid.UUID, delegation_id: uuid.UUID,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    res = _get_resource(db, actor, resource_pk)
    d = ResourceDelegationService(db).revoke(actor, res, delegation_id,
                                             has_manage_permission=_can(db, actor, _MANAGE))
    db.commit()
    return d


# --------------------------------------------------------------------------- #
# Resource policy (§14)
# --------------------------------------------------------------------------- #
@router.put("/resources/{resource_pk}/policy", response_model=ResourceRead)
def set_policy(
    resource_pk: uuid.UUID, payload: PolicyWrite,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> ProtectedResource:
    res = _get_resource(db, actor, resource_pk)
    res = ResourcePolicyService(db).set_policy(
        actor, res, payload.policy, has_manage_permission=_can(db, actor, _MANAGE)
    )
    db.commit()
    return res


# --------------------------------------------------------------------------- #
# Authorization + inspector (§18, §19, §21)
# --------------------------------------------------------------------------- #
@router.post("/resources/{resource_pk}/authorize", response_model=AuthorizeResponse)
def authorize(
    resource_pk: uuid.UUID, payload: AuthorizeRequest,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> AuthorizeResponse:
    """Evaluate the full §18 chain for the caller — or, for security administrators
    holding ``resource.manage``, simulate another identity (Authorization Inspector §21).
    Every decision is audited (§22.8)."""
    res = _get_resource(db, actor, resource_pk)
    subject = actor
    if payload.identity_id is not None and payload.identity_id != actor.id:
        if not _can(db, actor, _MANAGE):
            raise IdentityError(ErrorCode.RESOURCE_ACCESS_DENIED,
                                "Simulating another identity requires resource.manage.")
        subject = db.get(User, payload.identity_id)
        if subject is None or subject.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.USER_NOT_FOUND, "Identity not found.")
    d = ResourceAuthorizationService(db).authorize(subject, payload.permission, res)
    db.commit()
    return AuthorizeResponse(
        allowed=d.allowed, permission=d.permission, reason=d.reason, source=d.source,
        error_code=d.error_code, resource_pk=d.resource_pk, resource_type=d.resource_type,
        owner_id=d.owner_id, owner_type=d.owner_type, visibility=d.visibility,
        scope=d.scope, source_role=d.source_role, matched_rule_id=d.matched_rule_id,
        steps=d.steps,
    )
