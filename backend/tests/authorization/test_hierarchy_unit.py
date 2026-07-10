"""Phase 4.3.3 unit tests — hierarchy resolution, parent chain, descendants (§21)."""

from __future__ import annotations

import uuid

from app.authorization.hierarchy.enums import HierarchyLevel
from app.authorization.hierarchy.services import HierarchyResolverService
from app.identity.models.department import Department, Team
from app.models.organization import Organization
from app.models.organization_hierarchy import BusinessUnit, Project


def test_resolve_path_and_descendants(db_session) -> None:
    org = Organization(name=f"U_{uuid.uuid4().hex[:6]}", status="ACTIVE")
    db_session.add(org)
    db_session.flush()

    bu = BusinessUnit(organization_id=org.id, name="BU", status="ACTIVE")
    db_session.add(bu)
    db_session.flush()
    dept = Department(organization_id=org.id, name="Dept", business_unit_id=bu.id, status="ACTIVE")
    db_session.add(dept)
    db_session.flush()
    team = Team(department_id=dept.id, name="Team", status="ACTIVE")
    db_session.add(team)
    db_session.flush()
    project = Project(team_id=team.id, name="Proj", status="ACTIVE")
    db_session.add(project)
    db_session.flush()

    resolver = HierarchyResolverService(db_session)

    # Full parent chain for the deepest entity (§13).
    path = resolver.resolve_path(HierarchyLevel.PROJECT, project.id)
    assert path == {
        "organization_id": org.id, "business_unit_id": bu.id,
        "department_id": dept.id, "team_id": team.id, "project_id": project.id,
    }

    # Intermediate levels.
    assert resolver.resolve_path(HierarchyLevel.TEAM, team.id)["department_id"] == dept.id
    assert resolver.org_of(HierarchyLevel.PROJECT, project.id) == org.id

    # Descendants / has_children (§13, §19).
    assert resolver.has_children(HierarchyLevel.ORGANIZATION, org.id) is True
    assert resolver.has_children(HierarchyLevel.BUSINESS_UNIT, bu.id) is True
    assert resolver.has_children(HierarchyLevel.DEPARTMENT, dept.id) is True
    assert resolver.has_children(HierarchyLevel.TEAM, team.id) is True
    assert resolver.has_children(HierarchyLevel.PROJECT, project.id) is False

    db_session.rollback()


def test_resolve_path_missing_entity(db_session) -> None:
    resolver = HierarchyResolverService(db_session)
    assert resolver.resolve_path(HierarchyLevel.PROJECT, uuid.uuid4()) is None
    assert resolver.org_of(HierarchyLevel.TEAM, uuid.uuid4()) is None
