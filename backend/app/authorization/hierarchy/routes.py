"""Organization hierarchy API (Phase 4.3.3 §15, §17).

CRUD for organizations → business units → departments → teams → projects, plus the
hierarchy tree, resource ownership and delegated administration. All under
``/api/v1`` and org-scoped (isolation §9): ``organization.view`` to read,
``organization.manage`` to change.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.authorization.hierarchy.schemas import (
    BusinessUnitRead,
    BusinessUnitWrite,
    DelegationCreate,
    DelegationRead,
    DepartmentRead,
    DepartmentWrite,
    OrganizationRead,
    OrganizationWrite,
    OwnershipTransfer,
    ProjectRead,
    ProjectWrite,
    ResourceOwnershipAssign,
    ResourceOwnershipRead,
    TeamRead,
    TeamWrite,
)
from app.authorization.hierarchy.services import (
    BusinessUnitService,
    DelegationService,
    DepartmentService,
    OrganizationHierarchyService,
    ProjectService,
    ResourceOwnershipService,
    TeamService,
    record_org_event,
)
from app.authorization.hierarchy.enums import OrgAuditEvent, OrgEntityStatus
from app.core.database import get_db
from app.identity.api.deps import require_permission
from app.identity.errors import ErrorCode, IdentityError
from app.models.organization import Organization
from app.models.user import User

router = APIRouter(prefix="/api/v1", tags=["organization-hierarchy"])

_VIEW = "organization.view"
_MANAGE = "organization.manage"


# --------------------------------------------------------------------------- #
# Organizations
# --------------------------------------------------------------------------- #
@router.get("/organizations", response_model=list[OrganizationRead])
def list_organizations(
    actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)
) -> list[Organization]:
    """The caller's own organization plus any into which they hold a delegation
    (isolation §9 — never every tenant)."""
    org_ids = {actor.organization_id}
    org_ids.update(d.organization_id for d in DelegationService(db).active_for_user(actor.id))
    return list(db.execute(select(Organization).where(Organization.id.in_(org_ids))).scalars())


@router.post("/organizations", response_model=OrganizationRead, status_code=201)
def create_organization(
    payload: OrganizationWrite,
    actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db),
) -> Organization:
    org = Organization(name=payload.name.strip(), slug=payload.slug, owner_id=actor.id,
                       status=OrgEntityStatus.ACTIVE.value)
    db.add(org)
    db.flush()
    record_org_event(db, OrgAuditEvent.ORGANIZATION_CREATED, organization_id=org.id,
                     actor_id=actor.id, meta={"organization_id": str(org.id), "name": org.name})
    db.commit()
    return org


def _own_org(actor: User, db: Session, org_id: uuid.UUID) -> Organization:
    org = db.get(Organization, org_id)
    delegated = {d.organization_id for d in DelegationService(db).active_for_user(actor.id)}
    if org is None or (org.id != actor.organization_id and org.id not in delegated):
        raise IdentityError(ErrorCode.ORGANIZATION_NOT_FOUND, "Organization not found.")
    return org


@router.get("/organizations/{org_id}", response_model=OrganizationRead)
def get_organization(
    org_id: uuid.UUID,
    actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db),
) -> Organization:
    return _own_org(actor, db, org_id)


@router.put("/organizations/{org_id}", response_model=OrganizationRead)
def update_organization(
    org_id: uuid.UUID, payload: OrganizationWrite,
    actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db),
) -> Organization:
    org = _own_org(actor, db, org_id)
    org.name = payload.name or org.name
    if payload.slug is not None:
        org.slug = payload.slug
    if payload.status is not None:
        org.status = payload.status
    if payload.owner_id is not None:
        org.owner_id = payload.owner_id
    record_org_event(db, OrgAuditEvent.ORGANIZATION_UPDATED, organization_id=org.id,
                     actor_id=actor.id, meta={"organization_id": str(org.id)})
    db.commit()
    return org


@router.delete("/organizations/{org_id}", status_code=204, response_class=Response)
def delete_organization(
    org_id: uuid.UUID,
    actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db),
) -> Response:
    org = _own_org(actor, db, org_id)
    # Organizations are archived, never hard-deleted (they anchor every tenant record).
    org.status = OrgEntityStatus.ARCHIVED.value
    record_org_event(db, OrgAuditEvent.ORGANIZATION_DELETED, organization_id=org.id,
                     actor_id=actor.id, meta={"organization_id": str(org.id)})
    db.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Business units
# --------------------------------------------------------------------------- #
@router.get("/business-units", response_model=list[BusinessUnitRead])
def list_business_units(actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    return BusinessUnitService(db).list(actor)


@router.post("/business-units", response_model=BusinessUnitRead, status_code=201)
def create_business_unit(payload: BusinessUnitWrite, actor: User = Depends(require_permission(_MANAGE)),
                         db: Session = Depends(get_db)):
    bu = BusinessUnitService(db).create(actor, name=payload.name, manager_id=payload.manager_id)
    db.commit()
    return bu


@router.get("/business-units/{bu_id}", response_model=BusinessUnitRead)
def get_business_unit(bu_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)),
                      db: Session = Depends(get_db)):
    return BusinessUnitService(db).get(actor, bu_id)


@router.put("/business-units/{bu_id}", response_model=BusinessUnitRead)
def update_business_unit(bu_id: uuid.UUID, payload: BusinessUnitWrite,
                         actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db)):
    bu = BusinessUnitService(db).update(actor, bu_id, name=payload.name,
                                        manager_id=payload.manager_id, status=payload.status)
    db.commit()
    return bu


@router.delete("/business-units/{bu_id}", status_code=204, response_class=Response)
def delete_business_unit(bu_id: uuid.UUID, actor: User = Depends(require_permission(_MANAGE)),
                         db: Session = Depends(get_db)):
    BusinessUnitService(db).delete(actor, bu_id)
    db.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Departments
# --------------------------------------------------------------------------- #
@router.get("/departments", response_model=list[DepartmentRead])
def list_departments(actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    return DepartmentService(db).list(actor)


@router.post("/departments", response_model=DepartmentRead, status_code=201)
def create_department(payload: DepartmentWrite, actor: User = Depends(require_permission(_MANAGE)),
                      db: Session = Depends(get_db)):
    d = DepartmentService(db).create(actor, name=payload.name, manager_id=payload.manager_id,
                                     business_unit_id=payload.business_unit_id)
    db.commit()
    return d


@router.get("/departments/{dept_id}", response_model=DepartmentRead)
def get_department(dept_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)),
                   db: Session = Depends(get_db)):
    return DepartmentService(db).get(actor, dept_id)


@router.put("/departments/{dept_id}", response_model=DepartmentRead)
def update_department(dept_id: uuid.UUID, payload: DepartmentWrite,
                      actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db)):
    d = DepartmentService(db).update(actor, dept_id, name=payload.name, manager_id=payload.manager_id,
                                     business_unit_id=payload.business_unit_id, status=payload.status)
    db.commit()
    return d


@router.delete("/departments/{dept_id}", status_code=204, response_class=Response)
def delete_department(dept_id: uuid.UUID, actor: User = Depends(require_permission(_MANAGE)),
                      db: Session = Depends(get_db)):
    DepartmentService(db).delete(actor, dept_id)
    db.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Teams
# --------------------------------------------------------------------------- #
@router.get("/teams", response_model=list[TeamRead])
def list_teams(actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    return TeamService(db).list(actor)


@router.post("/teams", response_model=TeamRead, status_code=201)
def create_team(payload: TeamWrite, actor: User = Depends(require_permission(_MANAGE)),
                db: Session = Depends(get_db)):
    if payload.department_id is None:
        raise IdentityError(ErrorCode.VALIDATION_ERROR, "department_id is required.")
    t = TeamService(db).create(actor, department_id=payload.department_id, name=payload.name,
                               lead_id=payload.lead_id)
    db.commit()
    return t


@router.get("/teams/{team_id}", response_model=TeamRead)
def get_team(team_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)),
             db: Session = Depends(get_db)):
    return TeamService(db).get(actor, team_id)


@router.put("/teams/{team_id}", response_model=TeamRead)
def update_team(team_id: uuid.UUID, payload: TeamWrite,
                actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db)):
    t = TeamService(db).update(actor, team_id, name=payload.name, lead_id=payload.lead_id,
                               status=payload.status)
    db.commit()
    return t


@router.delete("/teams/{team_id}", status_code=204, response_class=Response)
def delete_team(team_id: uuid.UUID, actor: User = Depends(require_permission(_MANAGE)),
                db: Session = Depends(get_db)):
    TeamService(db).delete(actor, team_id)
    db.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Projects
# --------------------------------------------------------------------------- #
@router.get("/projects", response_model=list[ProjectRead])
def list_projects(actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    return ProjectService(db).list(actor)


@router.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(payload: ProjectWrite, actor: User = Depends(require_permission(_MANAGE)),
                   db: Session = Depends(get_db)):
    if payload.team_id is None:
        raise IdentityError(ErrorCode.VALIDATION_ERROR, "team_id is required.")
    p = ProjectService(db).create(actor, team_id=payload.team_id, name=payload.name,
                                  owner_id=payload.owner_id)
    db.commit()
    return p


@router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)),
                db: Session = Depends(get_db)):
    return ProjectService(db).get(actor, project_id)


@router.put("/projects/{project_id}", response_model=ProjectRead)
def update_project(project_id: uuid.UUID, payload: ProjectWrite,
                   actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db)):
    p = ProjectService(db).update(actor, project_id, name=payload.name, owner_id=payload.owner_id,
                                  status=payload.status)
    db.commit()
    return p


@router.delete("/projects/{project_id}", status_code=204, response_class=Response)
def delete_project(project_id: uuid.UUID, actor: User = Depends(require_permission(_MANAGE)),
                   db: Session = Depends(get_db)):
    ProjectService(db).delete(actor, project_id)
    db.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Hierarchy tree (§17)
# --------------------------------------------------------------------------- #
@router.get("/hierarchy/tree")
def hierarchy_tree(actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)) -> dict:
    return OrganizationHierarchyService(db).tree(actor)


# --------------------------------------------------------------------------- #
# Resource ownership (§6)
# --------------------------------------------------------------------------- #
@router.post("/resource-ownership", response_model=ResourceOwnershipRead, status_code=201)
def assign_ownership(payload: ResourceOwnershipAssign,
                     actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db)):
    row = ResourceOwnershipService(db).assign(
        actor, resource_type=payload.resource_type, resource_id=payload.resource_id,
        project_id=payload.project_id, team_id=payload.team_id,
        department_id=payload.department_id, owner_id=payload.owner_id,
    )
    db.commit()
    return row


@router.post("/resource-ownership/transfer", response_model=ResourceOwnershipRead)
def transfer_ownership(payload: OwnershipTransfer,
                       actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db)):
    row = ResourceOwnershipService(db).transfer(
        actor, payload.resource_type, payload.resource_id, payload.new_owner_id
    )
    db.commit()
    return row


@router.get("/resource-ownership/{resource_type}/{resource_id}", response_model=ResourceOwnershipRead)
def get_ownership(resource_type: str, resource_id: uuid.UUID,
                  actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    from app.models.organization_hierarchy import ResourceOwnership

    row = db.execute(
        select(ResourceOwnership).where(
            ResourceOwnership.resource_type == resource_type,
            ResourceOwnership.resource_id == resource_id,
        )
    ).scalar_one_or_none()
    if row is None or row.organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.RESOURCE_OWNERSHIP_NOT_FOUND, "Resource ownership not found.")
    return row


# --------------------------------------------------------------------------- #
# Delegated administration (§10)
# --------------------------------------------------------------------------- #
@router.get("/delegations", response_model=list[DelegationRead])
def list_delegations(actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    return DelegationService(db).list(actor)


@router.post("/delegations", response_model=DelegationRead, status_code=201)
def create_delegation(payload: DelegationCreate,
                      actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db)):
    d = DelegationService(db).delegate(
        actor, delegatee_id=payload.delegatee_id, scope_type=payload.scope_type,
        scope_id=payload.scope_id, permission=payload.permission,
    )
    db.commit()
    return d


@router.delete("/delegations/{delegation_id}", response_model=DelegationRead)
def revoke_delegation(delegation_id: uuid.UUID,
                      actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db)):
    d = DelegationService(db).revoke(actor, delegation_id)
    db.commit()
    return d
