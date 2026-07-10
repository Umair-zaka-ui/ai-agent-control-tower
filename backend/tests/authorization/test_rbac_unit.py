"""Phase 4.3.1 unit tests: permission-name validation, hierarchy cycle detection,
scope validation, and the seeded catalog/taxonomy (§27)."""

from __future__ import annotations

import uuid

import pytest

from app.authorization.catalog import (
    BUILTIN_ROLES,
    PERMISSION_GROUPS,
    ROLE_HIERARCHY_EDGES,
    group_for_code,
    split_code,
)
from app.authorization.enums import RoleStatus
from app.authorization.services import PermissionService
from app.identity.errors import ErrorCode, IdentityError


# --- permission-name validation (§11, §24) --------------------------------- #
@pytest.mark.parametrize("code", ["agent.create", "policy.approve", "audit.export", "agent.*",
                                  "agent_action.view"])
def test_valid_permission_names(code: str) -> None:
    PermissionService.validate_name(code)  # must not raise


@pytest.mark.parametrize("code", ["Agent.Create", "agent create", "agent", "agent.", ".create",
                                  "AGENT.CREATE", "agent..create", ""])
def test_invalid_permission_names(code: str) -> None:
    with pytest.raises(IdentityError) as exc:
        PermissionService.validate_name(code)
    assert exc.value.code == ErrorCode.INVALID_PERMISSION_NAME


# --- catalog integrity ----------------------------------------------------- #
def test_split_code() -> None:
    assert split_code("agent.create") == ("agent", "create")
    assert split_code("agent") == ("agent", "*")


def test_every_permission_maps_to_a_defined_group() -> None:
    group_names = {g.name for g in PERMISSION_GROUPS}
    from app.services.rbac_service import PERMISSION_CATALOG

    for code in PERMISSION_CATALOG:
        assert group_for_code(code) in group_names


def test_builtin_role_children_reference_real_roles() -> None:
    names = {r.name for r in BUILTIN_ROLES}
    for role in BUILTIN_ROLES:
        for child in role.children:
            assert child in names, f"{role.name} -> unknown child {child}"


def test_builtin_hierarchy_is_acyclic() -> None:
    # Build adjacency and DFS for a back-edge.
    adj: dict[str, list[str]] = {}
    for parent, child in ROLE_HIERARCHY_EDGES:
        adj.setdefault(parent, []).append(child)

    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = {}

    def visit(node: str) -> None:
        color[node] = GREY
        for nxt in adj.get(node, []):
            if color.get(nxt, WHITE) == GREY:
                raise AssertionError(f"cycle via {node} -> {nxt}")
            if color.get(nxt, WHITE) == WHITE:
                visit(nxt)
        color[node] = BLACK

    for parent, _ in ROLE_HIERARCHY_EDGES:
        if color.get(parent, WHITE) == WHITE:
            visit(parent)


def test_role_status_assignable_states() -> None:
    assert RoleStatus.ACTIVE.is_assignable_state
    assert not RoleStatus.ARCHIVED.is_assignable_state
    assert not RoleStatus.DELETED.is_assignable_state


# --- cycle detection in the live service (§17, §25) ------------------------ #
def test_cycle_detection_direct_and_transitive(db_session) -> None:
    """A -> B -> C exists; adding C -> A must be rejected as circular."""
    from app.authorization.services import RoleHierarchyService, RoleService

    org_id = None  # global throwaway roles (no organizations FK to satisfy)
    # Three throwaway custom roles (no user needed for hierarchy).
    svc = RoleService(db_session)
    a = svc.create(name=f"A_{uuid.uuid4().hex[:6]}", display_name=None, description=None,
                   category="CUSTOM", priority=50, permission_codes=[], organization_id=org_id,
                   actor_id=None)
    b = svc.create(name=f"B_{uuid.uuid4().hex[:6]}", display_name=None, description=None,
                   category="CUSTOM", priority=50, permission_codes=[], organization_id=org_id,
                   actor_id=None)
    c = svc.create(name=f"C_{uuid.uuid4().hex[:6]}", display_name=None, description=None,
                   category="CUSTOM", priority=50, permission_codes=[], organization_id=org_id,
                   actor_id=None)
    hs = RoleHierarchyService(db_session)
    hs.add_edge(a.id, b.id, organization_id=org_id, actor_id=None)
    hs.add_edge(b.id, c.id, organization_id=org_id, actor_id=None)

    # self edge
    assert hs.would_create_cycle(a.id, a.id) is True
    # transitive back-edge C -> A
    assert hs.would_create_cycle(c.id, a.id) is True
    with pytest.raises(IdentityError) as exc:
        hs.add_edge(c.id, a.id, organization_id=org_id, actor_id=None)
    assert exc.value.code == ErrorCode.CIRCULAR_ROLE_HIERARCHY
    db_session.rollback()
