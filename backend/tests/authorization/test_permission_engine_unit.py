"""Phase 4.3.2 unit tests — the pure resolvers and evaluation (§29).

Wildcard matching, scope application, conflict resolution and end-to-end evaluation
are all pure over a resolved grant list, so they need no database.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.authorization.engine import (
    ALLOW,
    DENY,
    ConflictResolver,
    Grant,
    PermissionEngine,
    ResourceContext,
    ScopeResolver,
    WildcardResolver,
)


def _user(org=None):
    return SimpleNamespace(id=uuid.uuid4(), organization_id=org or uuid.uuid4())


# --- wildcards (§13, §14) -------------------------------------------------- #
@pytest.mark.parametrize("pattern,code,expected", [
    ("*", "agent.delete", True),
    ("agent.*", "agent.delete", True),
    ("agent.*", "agent.view", True),
    ("agent.*", "policy.view", False),
    ("agent.view", "agent.view", True),
    ("agent.view", "agent.delete", False),
])
def test_wildcard_matches(pattern, code, expected):
    assert WildcardResolver.matches(pattern, code) is expected


def test_wildcard_expand():
    known = {"agent.view", "agent.create", "policy.view"}
    assert WildcardResolver.expand("agent.*", known) == {"agent.view", "agent.create"}
    assert WildcardResolver.expand("*", known) == known


# --- scope (§15) ----------------------------------------------------------- #
def test_scope_global_always_applies():
    g = Grant("agent.view", ALLOW, "GLOBAL", "r")
    assert ScopeResolver.applies(g, _user(), None) is True


def test_scope_organization():
    org = uuid.uuid4()
    u = _user(org)
    same = Grant("agent.view", ALLOW, "ORGANIZATION", "r", organization_id=str(org))
    other = Grant("agent.view", ALLOW, "ORGANIZATION", "r", organization_id=str(uuid.uuid4()))
    assert ScopeResolver.applies(same, u, None) is True
    assert ScopeResolver.applies(other, u, None) is False


def test_scope_department_needs_matching_target():
    dept = uuid.uuid4()
    g = Grant("agent.view", ALLOW, "DEPARTMENT", "r", department_id=str(dept))
    assert ScopeResolver.applies(g, _user(), None) is False  # no resource named
    ctx = ResourceContext(department_id=dept)
    assert ScopeResolver.applies(g, _user(), ctx) is True
    assert ScopeResolver.applies(g, _user(), ResourceContext(department_id=uuid.uuid4())) is False


def test_scope_resource():
    rid = uuid.uuid4()
    g = Grant("agent.delete", ALLOW, "RESOURCE", "r", resource_type="agent", resource_id=str(rid))
    assert ScopeResolver.applies(g, _user(), None) is False
    ctx = ResourceContext(resource_type="agent", resource_id=rid)
    assert ScopeResolver.applies(g, _user(), ctx) is True
    other = ResourceContext(resource_type="agent", resource_id=uuid.uuid4())
    assert ScopeResolver.applies(g, _user(), other) is False


# --- conflict resolution (§16) --------------------------------------------- #
def test_conflict_deny_wins():
    matching = [Grant("agent.delete", ALLOW, "GLOBAL", "r1"),
                Grant("agent.delete", DENY, "GLOBAL", "r2")]
    result = ConflictResolver.resolve("agent.delete", matching)
    assert result.allowed is False and "denied" in result.reason.lower()


def test_conflict_allow():
    result = ConflictResolver.resolve("agent.view", [Grant("agent.view", ALLOW, "GLOBAL", "r1")])
    assert result.allowed is True and result.source_role == "r1"


def test_conflict_default_deny():
    result = ConflictResolver.resolve("agent.view", [])
    assert result.allowed is False and "not assigned" in result.reason.lower()


# --- full evaluation ------------------------------------------------------- #
def test_evaluate_wildcard_allow():
    engine = PermissionEngine(None)  # evaluate is pure; no DB used
    grants = [Grant("agent.*", ALLOW, "GLOBAL", "ROLE_AI_OPERATOR")]
    assert engine.evaluate(_user(), "agent.delete", grants).allowed is True


def test_evaluate_explicit_deny_beats_wildcard():
    engine = PermissionEngine(None)
    grants = [
        Grant("agent.*", ALLOW, "GLOBAL", "ROLE_AI_OPERATOR"),
        Grant("agent.delete", DENY, "GLOBAL", "ROLE_SAFETY"),
    ]
    assert engine.evaluate(_user(), "agent.delete", grants).allowed is False
    assert engine.evaluate(_user(), "agent.view", grants).allowed is True  # only delete denied


def test_evaluate_scope_gate():
    engine = PermissionEngine(None)
    dept = uuid.uuid4()
    grants = [Grant("agent.view", ALLOW, "DEPARTMENT", "ROLE_X", department_id=str(dept))]
    # No resource context -> the department grant does not satisfy a generic check.
    assert engine.evaluate(_user(), "agent.view", grants).allowed is False
    # Matching department -> allowed.
    ctx = ResourceContext(department_id=dept)
    assert engine.evaluate(_user(), "agent.view", grants, ctx).allowed is True


def test_grant_json_roundtrip():
    g = Grant("agent.view", ALLOW, "RESOURCE", "r", resource_type="agent", resource_id="abc")
    assert Grant.from_json(g.to_json()) == g
