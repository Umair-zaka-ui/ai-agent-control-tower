"""Organization hierarchy services (Phase 4.3.3 §12, §13).

Entity CRUD (organization → business unit → department → team → project), the
hierarchy resolver (parent chain / descendants / path), resource ownership, the
tree builder, and delegated administration — each org-scoped for isolation (§9)
and audited (§18).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.authorization.hierarchy.enums import HierarchyLevel, OrgAuditEvent, OrgEntityStatus
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.department import Department, Team
from app.models.organization import Organization
from app.models.organization_hierarchy import (
    BusinessUnit,
    Delegation,
    Project,
    ResourceOwnership,
)
from app.models.rbac import AuthorizationAudit
from app.models.user import User


# --------------------------------------------------------------------------- #
# Audit (§18) — recorded on the shared authorization_audit table.
# --------------------------------------------------------------------------- #
def record_org_event(
    db: Session,
    event: OrgAuditEvent,
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
# Hierarchy resolver (§13)
# --------------------------------------------------------------------------- #
class HierarchyResolverService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --- org resolution per level (for isolation checks) --------------- #
    def org_of(self, level: HierarchyLevel, entity_id: uuid.UUID) -> uuid.UUID | None:
        path = self.resolve_path(level, entity_id)
        return path.get("organization_id") if path else None

    def resolve_path(self, level: HierarchyLevel, entity_id: uuid.UUID) -> dict | None:
        """Resolve an entity's full ancestor path as a dict of ids (§13 parent chain)."""
        if level is HierarchyLevel.ORGANIZATION:
            org = self.db.get(Organization, entity_id)
            return {"organization_id": org.id} if org else None
        if level is HierarchyLevel.BUSINESS_UNIT:
            bu = self.db.get(BusinessUnit, entity_id)
            return None if bu is None else {
                "organization_id": bu.organization_id, "business_unit_id": bu.id,
            }
        if level is HierarchyLevel.DEPARTMENT:
            d = self.db.get(Department, entity_id)
            return None if d is None else {
                "organization_id": d.organization_id, "business_unit_id": d.business_unit_id,
                "department_id": d.id,
            }
        if level is HierarchyLevel.TEAM:
            t = self.db.get(Team, entity_id)
            if t is None:
                return None
            parent = self.resolve_path(HierarchyLevel.DEPARTMENT, t.department_id) or {}
            return {**parent, "team_id": t.id}
        if level is HierarchyLevel.PROJECT:
            p = self.db.get(Project, entity_id)
            if p is None:
                return None
            parent = self.resolve_path(HierarchyLevel.TEAM, p.team_id) or {}
            return {**parent, "project_id": p.id}
        return None

    def has_children(self, level: HierarchyLevel, entity_id: uuid.UUID) -> bool:
        if level is HierarchyLevel.ORGANIZATION:
            return self._exists(BusinessUnit, BusinessUnit.organization_id, entity_id) or \
                self._exists(Department, Department.organization_id, entity_id)
        if level is HierarchyLevel.BUSINESS_UNIT:
            return self._exists(Department, Department.business_unit_id, entity_id)
        if level is HierarchyLevel.DEPARTMENT:
            return self._exists(Team, Team.department_id, entity_id)
        if level is HierarchyLevel.TEAM:
            return self._exists(Project, Project.team_id, entity_id)
        return False

    def _exists(self, model, column, value) -> bool:
        return self.db.execute(
            select(func.count()).select_from(model).where(column == value)
        ).scalar_one() > 0


# --------------------------------------------------------------------------- #
# Entity CRUD services (§12)
# --------------------------------------------------------------------------- #
class _OrgScoped:
    """Shared helpers: every hierarchy entity resolves to exactly one organization,
    and a caller may only touch entities in their own org (isolation §9)."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.resolver = HierarchyResolverService(db)

    def _assert_same_org(
        self, actor: User, org_id: uuid.UUID | None,
        not_found: str = ErrorCode.CROSS_ORG_FORBIDDEN,
    ) -> None:
        if org_id != actor.organization_id:
            # Never reveal existence across the tenant boundary (§9): a cross-org
            # lookup answers "not found", not "forbidden".
            raise IdentityError(not_found, "Not found.")


class BusinessUnitService(_OrgScoped):
    def list(self, actor: User) -> list[BusinessUnit]:
        return list(self.db.execute(
            select(BusinessUnit).where(BusinessUnit.organization_id == actor.organization_id)
            .order_by(BusinessUnit.name)
        ).scalars())

    def get(self, actor: User, bu_id: uuid.UUID) -> BusinessUnit:
        bu = self.db.get(BusinessUnit, bu_id)
        if bu is None:
            raise IdentityError(ErrorCode.BUSINESS_UNIT_NOT_FOUND, "Business unit not found.")
        self._assert_same_org(actor, bu.organization_id, ErrorCode.BUSINESS_UNIT_NOT_FOUND)
        return bu

    def create(self, actor: User, *, name: str, manager_id: uuid.UUID | None) -> BusinessUnit:
        bu = BusinessUnit(organization_id=actor.organization_id, name=name.strip(),
                          manager_id=manager_id, status=OrgEntityStatus.ACTIVE.value)
        self.db.add(bu)
        self.db.flush()
        record_org_event(self.db, OrgAuditEvent.BUSINESS_UNIT_CREATED,
                         organization_id=actor.organization_id, actor_id=actor.id,
                         meta={"business_unit_id": str(bu.id), "name": bu.name})
        return bu

    def update(self, actor: User, bu_id: uuid.UUID, *, name, manager_id, status) -> BusinessUnit:
        bu = self.get(actor, bu_id)
        if name is not None:
            bu.name = name
        if manager_id is not None:
            bu.manager_id = manager_id
        if status is not None:
            bu.status = status
        self.db.flush()
        record_org_event(self.db, OrgAuditEvent.ENTITY_UPDATED,
                         organization_id=actor.organization_id, actor_id=actor.id,
                         meta={"level": "BUSINESS_UNIT", "id": str(bu.id)})
        return bu

    def delete(self, actor: User, bu_id: uuid.UUID) -> None:
        bu = self.get(actor, bu_id)
        if self.resolver.has_children(HierarchyLevel.BUSINESS_UNIT, bu.id):
            raise IdentityError(ErrorCode.ENTITY_HAS_CHILDREN,
                                "Reassign or remove this unit's departments first.")
        self.db.delete(bu)
        self.db.flush()
        record_org_event(self.db, OrgAuditEvent.ENTITY_DELETED,
                         organization_id=actor.organization_id, actor_id=actor.id,
                         meta={"level": "BUSINESS_UNIT", "id": str(bu_id)})


class DepartmentService(_OrgScoped):
    def list(self, actor: User) -> list[Department]:
        return list(self.db.execute(
            select(Department).where(Department.organization_id == actor.organization_id)
            .order_by(Department.name)
        ).scalars())

    def get(self, actor: User, dept_id: uuid.UUID) -> Department:
        d = self.db.get(Department, dept_id)
        if d is None:
            raise IdentityError(ErrorCode.DEPARTMENT_NOT_FOUND, "Department not found.")
        self._assert_same_org(actor, d.organization_id, ErrorCode.DEPARTMENT_NOT_FOUND)
        return d

    def create(self, actor: User, *, name, manager_id, business_unit_id) -> Department:
        if business_unit_id is not None:
            bu = self.db.get(BusinessUnit, business_unit_id)
            if bu is None or bu.organization_id != actor.organization_id:
                raise IdentityError(ErrorCode.BUSINESS_UNIT_NOT_FOUND, "Business unit not found.")
        d = Department(organization_id=actor.organization_id, name=name.strip(),
                       manager_id=manager_id, business_unit_id=business_unit_id,
                       status=OrgEntityStatus.ACTIVE.value)
        self.db.add(d)
        self.db.flush()
        record_org_event(self.db, OrgAuditEvent.DEPARTMENT_CREATED,
                         organization_id=actor.organization_id, actor_id=actor.id,
                         meta={"department_id": str(d.id), "name": d.name})
        return d

    def update(self, actor, dept_id, *, name, manager_id, business_unit_id, status) -> Department:
        d = self.get(actor, dept_id)
        if name is not None:
            d.name = name
        if manager_id is not None:
            d.manager_id = manager_id
        if business_unit_id is not None:
            bu = self.db.get(BusinessUnit, business_unit_id)
            if bu is None or bu.organization_id != actor.organization_id:
                raise IdentityError(ErrorCode.BUSINESS_UNIT_NOT_FOUND, "Business unit not found.")
            d.business_unit_id = business_unit_id
        if status is not None:
            d.status = status
        self.db.flush()
        record_org_event(self.db, OrgAuditEvent.ENTITY_UPDATED,
                         organization_id=actor.organization_id, actor_id=actor.id,
                         meta={"level": "DEPARTMENT", "id": str(d.id)})
        return d

    def delete(self, actor, dept_id: uuid.UUID) -> None:
        d = self.get(actor, dept_id)
        if self.resolver.has_children(HierarchyLevel.DEPARTMENT, d.id):
            raise IdentityError(ErrorCode.ENTITY_HAS_CHILDREN,
                                "Reassign or remove this department's teams first.")
        self.db.delete(d)
        self.db.flush()
        record_org_event(self.db, OrgAuditEvent.ENTITY_DELETED,
                         organization_id=actor.organization_id, actor_id=actor.id,
                         meta={"level": "DEPARTMENT", "id": str(dept_id)})


class TeamService(_OrgScoped):
    def list(self, actor: User) -> list[Team]:
        return list(self.db.execute(
            select(Team).join(Department, Team.department_id == Department.id)
            .where(Department.organization_id == actor.organization_id).order_by(Team.name)
        ).scalars())

    def get(self, actor: User, team_id: uuid.UUID) -> Team:
        t = self.db.get(Team, team_id)
        if t is None:
            raise IdentityError(ErrorCode.TEAM_NOT_FOUND, "Team not found.")
        self._assert_same_org(actor, self.resolver.org_of(HierarchyLevel.TEAM, t.id), ErrorCode.TEAM_NOT_FOUND)
        return t

    def create(self, actor: User, *, department_id, name, lead_id) -> Team:
        dept = self.db.get(Department, department_id)
        if dept is None or dept.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.DEPARTMENT_NOT_FOUND, "Department not found.")
        t = Team(department_id=department_id, name=name.strip(), lead_id=lead_id,
                 status=OrgEntityStatus.ACTIVE.value)
        self.db.add(t)
        self.db.flush()
        record_org_event(self.db, OrgAuditEvent.TEAM_CREATED,
                         organization_id=actor.organization_id, actor_id=actor.id,
                         meta={"team_id": str(t.id), "name": t.name})
        return t

    def update(self, actor, team_id, *, name, lead_id, status) -> Team:
        t = self.get(actor, team_id)
        if name is not None:
            t.name = name
        if lead_id is not None:
            t.lead_id = lead_id
        if status is not None:
            t.status = status
        self.db.flush()
        record_org_event(self.db, OrgAuditEvent.ENTITY_UPDATED,
                         organization_id=actor.organization_id, actor_id=actor.id,
                         meta={"level": "TEAM", "id": str(t.id)})
        return t

    def delete(self, actor, team_id: uuid.UUID) -> None:
        t = self.get(actor, team_id)
        if self.resolver.has_children(HierarchyLevel.TEAM, t.id):
            raise IdentityError(ErrorCode.ENTITY_HAS_CHILDREN,
                                "Reassign or remove this team's projects first.")
        self.db.delete(t)
        self.db.flush()
        record_org_event(self.db, OrgAuditEvent.ENTITY_DELETED,
                         organization_id=actor.organization_id, actor_id=actor.id,
                         meta={"level": "TEAM", "id": str(team_id)})


class ProjectService(_OrgScoped):
    def list(self, actor: User) -> list[Project]:
        return list(self.db.execute(
            select(Project).join(Team, Project.team_id == Team.id)
            .join(Department, Team.department_id == Department.id)
            .where(Department.organization_id == actor.organization_id).order_by(Project.name)
        ).scalars())

    def get(self, actor: User, project_id: uuid.UUID) -> Project:
        p = self.db.get(Project, project_id)
        if p is None:
            raise IdentityError(ErrorCode.PROJECT_NOT_FOUND, "Project not found.")
        self._assert_same_org(actor, self.resolver.org_of(HierarchyLevel.PROJECT, p.id), ErrorCode.PROJECT_NOT_FOUND)
        return p

    def create(self, actor: User, *, team_id, name, owner_id) -> Project:
        team = self.db.get(Team, team_id)
        if team is None or self.resolver.org_of(HierarchyLevel.TEAM, team.id) != actor.organization_id:
            raise IdentityError(ErrorCode.TEAM_NOT_FOUND, "Team not found.")
        p = Project(team_id=team_id, name=name.strip(), owner_id=owner_id or actor.id,
                    status=OrgEntityStatus.ACTIVE.value)
        self.db.add(p)
        self.db.flush()
        record_org_event(self.db, OrgAuditEvent.PROJECT_CREATED,
                         organization_id=actor.organization_id, actor_id=actor.id,
                         meta={"project_id": str(p.id), "name": p.name})
        return p

    def update(self, actor, project_id, *, name, owner_id, status) -> Project:
        p = self.get(actor, project_id)
        if name is not None:
            p.name = name
        if owner_id is not None:
            p.owner_id = owner_id
        if status is not None:
            p.status = status
        self.db.flush()
        record_org_event(self.db, OrgAuditEvent.ENTITY_UPDATED,
                         organization_id=actor.organization_id, actor_id=actor.id,
                         meta={"level": "PROJECT", "id": str(p.id)})
        return p

    def delete(self, actor, project_id: uuid.UUID) -> None:
        p = self.get(actor, project_id)
        self.db.delete(p)
        self.db.flush()
        record_org_event(self.db, OrgAuditEvent.ENTITY_DELETED,
                         organization_id=actor.organization_id, actor_id=actor.id,
                         meta={"level": "PROJECT", "id": str(project_id)})


# --------------------------------------------------------------------------- #
# Resource ownership (§6, §13)
# --------------------------------------------------------------------------- #
class ResourceOwnershipService(_OrgScoped):
    def resolve_path(self, resource_type: str, resource_id: uuid.UUID) -> dict | None:
        row = self.db.execute(
            select(ResourceOwnership).where(
                ResourceOwnership.resource_type == resource_type,
                ResourceOwnership.resource_id == resource_id,
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return {
            "organization_id": row.organization_id,
            "business_unit_id": row.business_unit_id,
            "department_id": row.department_id,
            "team_id": row.team_id,
            "project_id": row.project_id,
            "owner_id": row.owner_id,
        }

    def assign(
        self, actor: User, *, resource_type: str, resource_id: uuid.UUID,
        project_id: uuid.UUID | None = None, team_id: uuid.UUID | None = None,
        department_id: uuid.UUID | None = None, owner_id: uuid.UUID | None = None,
    ) -> ResourceOwnership:
        """Attach a resource to the hierarchy. The path is derived from the deepest
        entity supplied; everything resolves to the caller's organization (§9)."""
        path: dict = {"organization_id": actor.organization_id}
        if project_id is not None:
            resolved = HierarchyResolverService(self.db).resolve_path(HierarchyLevel.PROJECT, project_id)
            if resolved is None or resolved["organization_id"] != actor.organization_id:
                raise IdentityError(ErrorCode.PROJECT_NOT_FOUND, "Project not found.")
            path = resolved
        elif team_id is not None:
            resolved = HierarchyResolverService(self.db).resolve_path(HierarchyLevel.TEAM, team_id)
            if resolved is None or resolved["organization_id"] != actor.organization_id:
                raise IdentityError(ErrorCode.TEAM_NOT_FOUND, "Team not found.")
            path = resolved
        elif department_id is not None:
            resolved = HierarchyResolverService(self.db).resolve_path(HierarchyLevel.DEPARTMENT, department_id)
            if resolved is None or resolved["organization_id"] != actor.organization_id:
                raise IdentityError(ErrorCode.DEPARTMENT_NOT_FOUND, "Department not found.")
            path = resolved

        row = self.db.execute(
            select(ResourceOwnership).where(
                ResourceOwnership.resource_type == resource_type,
                ResourceOwnership.resource_id == resource_id,
            )
        ).scalar_one_or_none()
        if row is None:
            row = ResourceOwnership(resource_type=resource_type, resource_id=resource_id)
            self.db.add(row)
        row.organization_id = path["organization_id"]
        row.business_unit_id = path.get("business_unit_id")
        row.department_id = path.get("department_id")
        row.team_id = path.get("team_id")
        row.project_id = path.get("project_id")
        row.owner_id = owner_id or actor.id
        self.db.flush()
        record_org_event(self.db, OrgAuditEvent.RESOURCE_ASSIGNED,
                         organization_id=actor.organization_id, actor_id=actor.id,
                         meta={"resource_type": resource_type, "resource_id": str(resource_id)})
        return row

    def transfer(self, actor: User, resource_type: str, resource_id: uuid.UUID,
                 new_owner_id: uuid.UUID) -> ResourceOwnership:
        row = self.db.execute(
            select(ResourceOwnership).where(
                ResourceOwnership.resource_type == resource_type,
                ResourceOwnership.resource_id == resource_id,
            )
        ).scalar_one_or_none()
        if row is None:
            raise IdentityError(ErrorCode.RESOURCE_OWNERSHIP_NOT_FOUND, "Resource ownership not found.")
        self._assert_same_org(actor, row.organization_id)
        previous = row.owner_id
        row.owner_id = new_owner_id
        self.db.flush()
        record_org_event(self.db, OrgAuditEvent.OWNERSHIP_TRANSFERRED,
                         organization_id=actor.organization_id, actor_id=actor.id,
                         meta={"resource_type": resource_type, "resource_id": str(resource_id),
                               "from": str(previous) if previous else None, "to": str(new_owner_id)})
        return row


# --------------------------------------------------------------------------- #
# Tree builder (§13, §17)
# --------------------------------------------------------------------------- #
class OrganizationHierarchyService(_OrgScoped):
    def tree(self, actor: User) -> dict:
        """Full nested hierarchy for the caller's organization (§17)."""
        org = self.db.get(Organization, actor.organization_id)
        if org is None:
            raise IdentityError(ErrorCode.ORGANIZATION_NOT_FOUND, "Organization not found.")

        depts = list(self.db.execute(
            select(Department).where(Department.organization_id == org.id)
        ).scalars())
        teams_by_dept: dict[uuid.UUID, list[Team]] = {}
        for t in self.db.execute(
            select(Team).join(Department, Team.department_id == Department.id)
            .where(Department.organization_id == org.id)
        ).scalars():
            teams_by_dept.setdefault(t.department_id, []).append(t)
        projects_by_team: dict[uuid.UUID, list[Project]] = {}
        for p in self.db.execute(
            select(Project).join(Team, Project.team_id == Team.id)
            .join(Department, Team.department_id == Department.id)
            .where(Department.organization_id == org.id)
        ).scalars():
            projects_by_team.setdefault(p.team_id, []).append(p)

        bus = list(self.db.execute(
            select(BusinessUnit).where(BusinessUnit.organization_id == org.id)
        ).scalars())

        def team_node(t: Team) -> dict:
            return {"id": str(t.id), "name": t.name, "level": "TEAM",
                    "children": [{"id": str(p.id), "name": p.name, "level": "PROJECT", "children": []}
                                 for p in projects_by_team.get(t.id, [])]}

        def dept_node(d: Department) -> dict:
            return {"id": str(d.id), "name": d.name, "level": "DEPARTMENT",
                    "business_unit_id": str(d.business_unit_id) if d.business_unit_id else None,
                    "children": [team_node(t) for t in teams_by_dept.get(d.id, [])]}

        # Departments grouped under their business unit (or directly under the org).
        depts_by_bu: dict[uuid.UUID | None, list[Department]] = {}
        for d in depts:
            depts_by_bu.setdefault(d.business_unit_id, []).append(d)

        bu_nodes = [
            {"id": str(bu.id), "name": bu.name, "level": "BUSINESS_UNIT",
             "children": [dept_node(d) for d in depts_by_bu.get(bu.id, [])]}
            for bu in bus
        ]
        loose_depts = [dept_node(d) for d in depts_by_bu.get(None, [])]

        return {"id": str(org.id), "name": org.name, "level": "ORGANIZATION",
                "children": bu_nodes + loose_depts}


# --------------------------------------------------------------------------- #
# Delegated administration (§10, §13, §19)
# --------------------------------------------------------------------------- #
class DelegationService(_OrgScoped):
    def list(self, actor: User) -> list[Delegation]:
        return list(self.db.execute(
            select(Delegation).where(Delegation.organization_id == actor.organization_id)
            .order_by(Delegation.created_at.desc())
        ).scalars())

    def active_for_user(self, user_id: uuid.UUID) -> list[Delegation]:
        return list(self.db.execute(
            select(Delegation).where(
                Delegation.delegatee_id == user_id, Delegation.revoked_at.is_(None)
            )
        ).scalars())

    def delegate(
        self, actor: User, *, delegatee_id: uuid.UUID, scope_type: str,
        scope_id: uuid.UUID | None, permission: str | None,
    ) -> Delegation:
        try:
            level = HierarchyLevel(scope_type)
        except ValueError as exc:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "Unknown delegation scope.") from exc

        # Boundary: the delegated scope must resolve to the delegator's own org, and
        # a delegator cannot grant a scope outside their own authority (§19).
        if level in (HierarchyLevel.BUSINESS_UNIT, HierarchyLevel.DEPARTMENT,
                     HierarchyLevel.TEAM, HierarchyLevel.PROJECT):
            if scope_id is None:
                raise IdentityError(ErrorCode.VALIDATION_ERROR, f"{scope_type} delegation needs a scope_id.")
            scope_org = self.resolver.org_of(level, scope_id)
            if scope_org is None or scope_org != actor.organization_id:
                raise IdentityError(ErrorCode.DELEGATION_EXCEEDS_AUTHORITY,
                                    "You cannot delegate outside your organization.")
        elif level is HierarchyLevel.ORGANIZATION:
            # Only an org owner/admin may delegate at org level; enforced by the
            # organization.manage gate on the route. Scope must be the actor's org.
            if scope_id not in (None, actor.organization_id):
                raise IdentityError(ErrorCode.DELEGATION_EXCEEDS_AUTHORITY,
                                    "You cannot delegate another organization.")
            scope_id = actor.organization_id
        else:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "Delegation scope not supported.")

        d = Delegation(organization_id=actor.organization_id, delegator_id=actor.id,
                       delegatee_id=delegatee_id, scope_type=level.value, scope_id=scope_id,
                       permission=permission)
        self.db.add(d)
        self.db.flush()
        record_org_event(self.db, OrgAuditEvent.DELEGATION_CREATED,
                         organization_id=actor.organization_id, actor_id=actor.id,
                         meta={"delegation_id": str(d.id), "delegatee_id": str(delegatee_id),
                               "scope_type": level.value})
        return d

    def revoke(self, actor: User, delegation_id: uuid.UUID) -> Delegation:
        d = self.db.get(Delegation, delegation_id)
        if d is None or d.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.DELEGATION_NOT_FOUND, "Delegation not found.")
        if d.revoked_at is None:
            d.revoked_at = datetime.now(timezone.utc)
            self.db.flush()
            record_org_event(self.db, OrgAuditEvent.DELEGATION_REVOKED,
                             organization_id=actor.organization_id, actor_id=actor.id,
                             meta={"delegation_id": str(d.id)})
        return d
