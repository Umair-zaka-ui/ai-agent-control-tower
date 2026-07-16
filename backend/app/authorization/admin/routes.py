"""Administration portal API (Phase 4.3.7 §18) — /api/v1/admin.

Every endpoint is a thin, permission-gated (§21) delegation to the existing
phase services, so the portal has exactly the same semantics, auditing and
cache invalidation as the underlying APIs. Enforcement runs through the 4.3.6
authorization gateway like every other route.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.authorization.abac.routes import _is_platform_admin, _simulate
from app.authorization.abac.schemas import (
    PolicyRead,
    PolicyWrite,
    SimulateRequest,
    SimulationRead,
)
from app.authorization.admin.schemas import (
    AnalyticsRead,
    CampaignCreate,
    CampaignRead,
    CampaignUpdate,
    DashboardRead,
    DecisionRead,
    ItemDecision,
    ReviewItemRead,
)
from app.authorization.admin.services import (
    AccessReviewService,
    DashboardService,
    DecisionExplorerService,
    SecurityAnalyticsService,
)
from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.schemas import PermissionRead, RoleCreate, RoleRead, RoleUpdate
from app.authorization.services import AuthorizationAuditService, RoleService
from app.core.database import get_db
from app.models.rbac import RbacPermission
from app.models.user import User

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

_DASHBOARD = "admin.dashboard.view"
_ROLES = "admin.roles.manage"
_PERMISSIONS = "admin.permissions.manage"
_ORGS = "admin.organizations.manage"
_RESOURCES = "admin.resources.manage"
_POLICIES = "admin.policies.manage"
_SIMULATOR = "admin.simulator.use"
_AUDIT = "admin.audit.view"
_ANALYTICS = "admin.analytics.view"
_REVIEWS = "admin.reviews.manage"


def _commit_invalidating(db: Session, organization_id: uuid.UUID | None) -> None:
    from app.authorization.cache import PermissionCacheService

    PermissionCacheService(db).invalidate_org(organization_id)
    db.commit()


# --------------------------------------------------------------------------- #
# Dashboard (§6)
# --------------------------------------------------------------------------- #
@router.get("/dashboard", response_model=DashboardRead)
def dashboard(actor: User = Depends(require_permission(_DASHBOARD)),
              db: Session = Depends(get_db)):
    return DashboardService(db).snapshot(actor)


# --------------------------------------------------------------------------- #
# Roles (§7, §18) — delegated to the 4.3.1 RoleService
# --------------------------------------------------------------------------- #
@router.get("/roles", response_model=list[RoleRead])
def list_roles(search: str | None = Query(default=None),
               actor: User = Depends(require_permission(_ROLES)),
               db: Session = Depends(get_db)):
    from app.authorization.repositories import RoleRepository
    from app.authorization.routes import _role_read

    roles = RoleRepository(db).list_visible(actor.organization_id, search=search)
    return [_role_read(role, db) for role in roles]


@router.post("/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
def create_role(payload: RoleCreate,
                actor: User = Depends(require_permission(_ROLES)),
                db: Session = Depends(get_db)):
    from app.authorization.routes import _role_read

    role = RoleService(db).create(
        name=payload.name, display_name=payload.display_name,
        description=payload.description, category=payload.category,
        priority=payload.priority, permission_codes=payload.permissions,
        denied_permission_codes=payload.denied_permissions,
        organization_id=actor.organization_id, actor_id=actor.id,
    )
    _commit_invalidating(db, actor.organization_id)
    return _role_read(role, db)


@router.put("/roles/{role_id}", response_model=RoleRead)
def update_role(role_id: uuid.UUID, payload: RoleUpdate,
                actor: User = Depends(require_permission(_ROLES)),
                db: Session = Depends(get_db)):
    from app.authorization.routes import _role_read

    svc = RoleService(db)
    role = svc.update(
        svc.get_or_404(role_id, actor.organization_id),
        organization_id=actor.organization_id, actor_id=actor.id,
        display_name=payload.display_name, description=payload.description,
        priority=payload.priority, status=payload.status,
        permission_codes=payload.permissions,
        denied_permission_codes=payload.denied_permissions,
    )
    _commit_invalidating(db, actor.organization_id)
    return _role_read(role, db)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT,
               response_class=Response)
def delete_role(role_id: uuid.UUID,
                actor: User = Depends(require_permission(_ROLES)),
                db: Session = Depends(get_db)):
    svc = RoleService(db)
    role = svc.get_or_404(role_id, actor.organization_id)
    svc.delete(role, actor_id=actor.id, organization_id=actor.organization_id)
    _commit_invalidating(db, actor.organization_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Permissions / organizations / resources (§18)
# --------------------------------------------------------------------------- #
@router.get("/permissions", response_model=list[PermissionRead])
def list_permissions(actor: User = Depends(require_permission(_PERMISSIONS)),
                     db: Session = Depends(get_db)):
    return list(db.execute(
        select(RbacPermission).order_by(RbacPermission.code)).scalars())


@router.get("/organizations")
def organization_tree(actor: User = Depends(require_permission(_ORGS)),
                      db: Session = Depends(get_db)) -> dict:
    from app.authorization.hierarchy.services import OrganizationHierarchyService

    return OrganizationHierarchyService(db).tree(actor)


@router.get("/resources")
def list_resources(resource_type: str | None = Query(default=None),
                   actor: User = Depends(require_permission(_RESOURCES)),
                   db: Session = Depends(get_db)) -> list[dict]:
    from app.authorization.resources.services import ResourceRegistryService

    rows = ResourceRegistryService(db).list(actor, can_view_all=True,
                                            resource_type=resource_type)
    return [{
        "id": str(r.id), "resource_type": r.resource_type,
        "resource_id": str(r.resource_id), "owner_id": str(r.owner_id),
        "owner_type": r.owner_type, "visibility": r.visibility, "status": r.status,
    } for r in rows]


# --------------------------------------------------------------------------- #
# ABAC policies (§10, §18) — delegated to the 4.3.5 PolicyService
# --------------------------------------------------------------------------- #
@router.get("/policies", response_model=list[PolicyRead])
def list_policies(status_filter: str | None = Query(default=None, alias="status"),
                  actor: User = Depends(require_permission(_POLICIES)),
                  db: Session = Depends(get_db)):
    from app.authorization.abac.policies import PolicyService

    return PolicyService(db).list(actor, status=status_filter)


@router.post("/policies", response_model=PolicyRead, status_code=status.HTTP_201_CREATED)
def create_policy(payload: PolicyWrite,
                  actor: User = Depends(require_permission(_POLICIES)),
                  db: Session = Depends(get_db)):
    from app.authorization.abac.policies import PolicyService

    policy = PolicyService(db).create(actor, payload.model_dump(exclude_unset=True),
                                      is_platform_admin=_is_platform_admin(db, actor))
    db.commit()
    return policy


@router.put("/policies/{policy_id}", response_model=PolicyRead)
def update_policy(policy_id: uuid.UUID, payload: PolicyWrite,
                  actor: User = Depends(require_permission(_POLICIES)),
                  db: Session = Depends(get_db)):
    from app.authorization.abac.policies import PolicyService

    policy = PolicyService(db).update(actor, policy_id,
                                      payload.model_dump(exclude_unset=True))
    db.commit()
    return policy


@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT,
               response_class=Response)
def delete_policy(policy_id: uuid.UUID,
                  actor: User = Depends(require_permission(_POLICIES)),
                  db: Session = Depends(get_db)):
    from app.authorization.abac.policies import PolicyService

    PolicyService(db).delete(actor, policy_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Policy simulator (§12, §18) — read-only; never modifies production state.
# --------------------------------------------------------------------------- #
@router.post("/policy-simulator", response_model=SimulationRead)
def policy_simulator(payload: SimulateRequest,
                     actor: User = Depends(require_permission(_SIMULATOR)),
                     db: Session = Depends(get_db)):
    result = _simulate(actor, db, payload, payload.policy)
    AuthorizationAuditService(db).record_change(
        AuthorizationAuditEvent.SIMULATION_EXECUTED,
        organization_id=actor.organization_id, actor_id=actor.id,
        meta={"action": payload.action,
              "identity_id": str(payload.identity_id) if payload.identity_id else None},
    )
    db.commit()
    return result


# --------------------------------------------------------------------------- #
# Authorization decision explorer (§13, §18)
# --------------------------------------------------------------------------- #
@router.get("/authorization-decisions", response_model=list[DecisionRead])
def authorization_decisions(
    identity_id: uuid.UUID | None = Query(default=None),
    permission: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    allowed: bool | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    actor: User = Depends(require_permission(_AUDIT)),
    db: Session = Depends(get_db),
):
    rows = DecisionExplorerService(db).search(
        actor, identity_id=identity_id, permission=permission,
        resource_type=resource_type, allowed=allowed,
        since=since, until=until, limit=limit,
    )
    db.commit()  # persists the DECISION_VIEWED audit event
    return rows


# --------------------------------------------------------------------------- #
# Access review campaigns (§14, §18)
# --------------------------------------------------------------------------- #
def _campaign_read(svc: AccessReviewService, campaign) -> CampaignRead:
    total, decided, revoked = svc.counts(campaign.id)
    read = CampaignRead.model_validate(campaign)
    read.total_items, read.decided_items, read.revoked_items = total, decided, revoked
    return read


@router.get("/access-reviews", response_model=list[CampaignRead])
def list_campaigns(status_filter: str | None = Query(default=None, alias="status"),
                   actor: User = Depends(require_permission(_REVIEWS)),
                   db: Session = Depends(get_db)):
    svc = AccessReviewService(db)
    return [_campaign_read(svc, c) for c in svc.list(actor, status=status_filter)]


@router.post("/access-reviews", response_model=CampaignRead,
             status_code=status.HTTP_201_CREATED)
def create_campaign(payload: CampaignCreate,
                    actor: User = Depends(require_permission(_REVIEWS)),
                    db: Session = Depends(get_db)):
    svc = AccessReviewService(db)
    campaign = svc.create(actor, payload.model_dump(exclude_unset=True))
    db.commit()
    return _campaign_read(svc, campaign)


@router.get("/access-reviews/{campaign_id}", response_model=CampaignRead)
def get_campaign(campaign_id: uuid.UUID,
                 actor: User = Depends(require_permission(_REVIEWS)),
                 db: Session = Depends(get_db)):
    svc = AccessReviewService(db)
    return _campaign_read(svc, svc.get_or_404(actor, campaign_id))


@router.put("/access-reviews/{campaign_id}", response_model=CampaignRead)
def update_campaign(campaign_id: uuid.UUID, payload: CampaignUpdate,
                    actor: User = Depends(require_permission(_REVIEWS)),
                    db: Session = Depends(get_db)):
    svc = AccessReviewService(db)
    campaign = svc.update(actor, campaign_id, payload.model_dump(exclude_unset=True))
    db.commit()
    return _campaign_read(svc, campaign)


@router.post("/access-reviews/{campaign_id}/schedule", response_model=CampaignRead)
def schedule_campaign(campaign_id: uuid.UUID,
                      actor: User = Depends(require_permission(_REVIEWS)),
                      db: Session = Depends(get_db)):
    svc = AccessReviewService(db)
    campaign = svc.schedule(actor, campaign_id)
    db.commit()
    return _campaign_read(svc, campaign)


@router.post("/access-reviews/{campaign_id}/activate", response_model=CampaignRead)
def activate_campaign(campaign_id: uuid.UUID,
                      actor: User = Depends(require_permission(_REVIEWS)),
                      db: Session = Depends(get_db)):
    svc = AccessReviewService(db)
    campaign = svc.activate(actor, campaign_id)
    db.commit()
    return _campaign_read(svc, campaign)


@router.get("/access-reviews/{campaign_id}/items", response_model=list[ReviewItemRead])
def campaign_items(campaign_id: uuid.UUID,
                   actor: User = Depends(require_permission(_REVIEWS)),
                   db: Session = Depends(get_db)):
    return AccessReviewService(db).items(actor, campaign_id)


@router.post("/access-reviews/{campaign_id}/items/{item_id}/decide",
             response_model=ReviewItemRead)
def decide_item(campaign_id: uuid.UUID, item_id: uuid.UUID, payload: ItemDecision,
                actor: User = Depends(require_permission(_REVIEWS)),
                db: Session = Depends(get_db)):
    item = AccessReviewService(db).decide_item(
        actor, campaign_id, item_id,
        decision=payload.decision, comment=payload.comment,
    )
    db.commit()
    return item


@router.post("/access-reviews/{campaign_id}/complete", response_model=CampaignRead)
def complete_campaign(campaign_id: uuid.UUID,
                      actor: User = Depends(require_permission(_REVIEWS)),
                      db: Session = Depends(get_db)):
    svc = AccessReviewService(db)
    campaign = svc.complete(actor, campaign_id)
    db.commit()
    return _campaign_read(svc, campaign)


@router.post("/access-reviews/{campaign_id}/archive", response_model=CampaignRead)
def archive_campaign(campaign_id: uuid.UUID,
                     actor: User = Depends(require_permission(_REVIEWS)),
                     db: Session = Depends(get_db)):
    svc = AccessReviewService(db)
    campaign = svc.archive(actor, campaign_id)
    db.commit()
    return _campaign_read(svc, campaign)


@router.get("/access-reviews/{campaign_id}/export")
def export_campaign(campaign_id: uuid.UUID,
                    actor: User = Depends(require_permission(_REVIEWS)),
                    db: Session = Depends(get_db)) -> dict:
    report = AccessReviewService(db).export(actor, campaign_id)
    db.commit()  # persists the AUDIT_EXPORTED event
    return report


# --------------------------------------------------------------------------- #
# Security analytics (§17, §18)
# --------------------------------------------------------------------------- #
@router.get("/analytics", response_model=AnalyticsRead)
def analytics(actor: User = Depends(require_permission(_ANALYTICS)),
              db: Session = Depends(get_db)):
    return SecurityAnalyticsService(db).snapshot(actor)
