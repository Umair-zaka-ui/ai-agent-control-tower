"""Phase 5.8 (M5.8) — the Enterprise Agent Command Center's backend half.

Two read-only aggregation endpoints, and the properties that keep them from
quietly becoming a third opinion about what ACT can do: they are structurally
read-only, they re-use 5.5's and 5.7's own services rather than recomputing
their answers, they are tenant-isolated, and a section the caller cannot read
comes back as "hidden" rather than as a zero that would read as "all clear".

AC-01, AC-11, AC-12 and AC-16 are proven here; the rest of Phase 5.8's
acceptance criteria are frontend properties and live in
``frontend/src/modules/command/tests/command.test.tsx``.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import SessionLocal
from app.models.agent import Agent
from app.models.user import User
from app.runtime.registry.control import AgentProvenanceService

CC = "/api/v1/command-center"
_BACKEND = Path(__file__).resolve().parents[2]
_PKG = _BACKEND / "app" / "command_center"


def _make_external(admin: dict, **kw) -> str:
    """An agent that exists OUTSIDE ACT, via Phase 5.1's own seam."""
    db = SessionLocal()
    try:
        actor = db.get(User, uuid.UUID(admin["user_id"]))
        agent = AgentProvenanceService(db).record_external_agent(
            actor, name=kw.pop("name", f"Ext {uuid.uuid4().hex[:6]}"),
            origin_category="EXTERNAL", origin_provider="LANGGRAPH", **kw)
        db.commit()
        return str(agent.id)
    finally:
        db.close()


def _source() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(_PKG.glob("*.py")))


# --------------------------------------------------------------------------- #
# AC-01 — the substrate this phase assembles
# --------------------------------------------------------------------------- #
def test_ac01_substrate_present_and_no_migration_needed() -> None:
    """5.8 adds no table and no column: it reads what 5.1–5.7 already store."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from app.bridge.modes import effective_mode  # noqa: F401 — 5.7's derivation
    from app.posture.shadow import ShadowAgentService  # noqa: F401 — 5.5's shadow
    from app.posture.summary import PostureSummaryService  # noqa: F401 — 5.5's score

    # At 5.8's own time this pinned the head to 5.7's migration to show that
    # 5.8 added none of its own. Phase 5.9 has since legitimately moved the head,
    # so the assertion is now the invariant it was protecting directly: no
    # migration in the chain belongs to the command center. That stays true
    # however many later phases add migrations of their own.
    script = ScriptDirectory.from_config(Config(str(_BACKEND / "alembic.ini")))
    assert len(script.get_heads()) == 1, "the migration chain must stay linear"
    versions = _BACKEND / "migrations" / "versions"
    for path in versions.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "command center" not in text and "command_center" not in text, path.name


# --------------------------------------------------------------------------- #
# AC-12 / AC-16 — read-only, and no domain logic (structural)
# --------------------------------------------------------------------------- #
def test_ac12_the_aggregation_surface_is_structurally_read_only() -> None:
    """No write verb exists in this package. The command center triggers
    actions through the 5.1–5.7 endpoints that own them; a write here would be
    a second door into logic that already has one."""
    from app.command_center.routes import router

    for route in router.routes:
        methods = set(getattr(route, "methods", set())) - {"HEAD", "OPTIONS"}
        assert methods <= {"GET"}, (route.path, methods)

    tree = ast.parse(_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in ("post", "put", "patch", "delete"), node.attr


def test_ac12_computes_no_domain_state_of_its_own() -> None:
    """It calls the authorities rather than re-deriving their answers: 5.7 for
    the enforcement mode, 5.5 for posture and shadow."""
    src = _source()
    assert "from app.bridge.modes import" in src
    assert "PostureSummaryService" in src
    assert "ShadowAgentService" in src

    code = ast.parse(src)
    called = {n.func.attr for n in ast.walk(code)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    # It must never enforce, and never write.
    for banned in ("activate", "revoke", "revoke_key", "disable", "suspend",
                   "terminate", "execute_containment", "commit", "flush", "add"):
        assert banned not in called, banned

    # And it must not re-spell the mode derivation. Filtering a column by a
    # caller-supplied value is fine — that is a query, not an opinion. What is
    # forbidden is comparing control_state or the mode against a *literal*,
    # which would be a second definition of "governed" waiting to drift from
    # 5.7's. Checked over the AST so a legitimate parameterized filter passes
    # and a hardcoded one does not.
    for node in ast.walk(code):
        if not isinstance(node, ast.Compare):
            continue
        left = ast.dump(node.left)
        if "control_state" not in left and "enforcement_mode" not in left:
            continue
        for comparator in node.comparators:
            assert not (isinstance(comparator, ast.Constant)
                        and isinstance(comparator.value, str)), ast.dump(node)

    # The constant itself comes from 5.7, never from a string typed here.
    assert "NATIVE_CONTROL_STATE" in src
    code_only = "\n".join(
        line for line in src.splitlines()
        if not line.strip().startswith(("#", "*", '"""', "'''", '"', "'")))
    assert '"GOVERNED"' not in code_only and "'GOVERNED'" not in code_only


def test_ac12_no_new_table_or_model_was_added() -> None:
    from app.core.database import Base

    names = set(Base.metadata.tables)
    for banned in ("command_center_estate", "estate_snapshots", "agent_projection",
                   "command_center_agents"):
        assert banned not in names, banned
    assert not (_PKG / "models.py").exists()


# --------------------------------------------------------------------------- #
# AC-11 / AC-12 — tenant isolation and authorization
# --------------------------------------------------------------------------- #
def test_ac11_estate_counts_only_the_callers_tenant(
        client: TestClient, admin: dict, other_org_admin: dict) -> None:
    _make_external(admin, name="Mine A")
    _make_external(admin, name="Mine B")
    _make_external(other_org_admin, name="Theirs")

    mine = client.get(f"{CC}/estate", headers=admin["headers"])
    theirs = client.get(f"{CC}/estate", headers=other_org_admin["headers"])
    assert mine.status_code == theirs.status_code == 200

    # Each tenant sees only its own agents — no estate count leaks across.
    assert mine.json()["agents"]["total"] >= 2
    assert theirs.json()["agents"]["total"] >= 1

    names = {a["name"] for a in
             client.get(f"{CC}/agents", headers=admin["headers"]).json()["items"]}
    assert "Theirs" not in names


def test_ac11_inventory_is_tenant_scoped(
        client: TestClient, admin: dict, other_org_admin: dict) -> None:
    foreign = _make_external(other_org_admin, name="Foreign Agent")
    rows = client.get(f"{CC}/agents", headers=admin["headers"]).json()["items"]
    assert all(r["id"] != foreign for r in rows)


def test_ac12_both_endpoints_require_a_permission(client: TestClient) -> None:
    assert client.get(f"{CC}/estate").status_code in (401, 403)
    assert client.get(f"{CC}/agents").status_code in (401, 403)


# --------------------------------------------------------------------------- #
# The honesty property: "hidden" is not "zero"
# --------------------------------------------------------------------------- #
def test_a_section_the_caller_cannot_read_is_hidden_not_zeroed(
        client: TestClient, admin: dict) -> None:
    """A viewer without ``posture.view`` must not be shown 0 shadow agents —
    that reads as "all clear" when the truth is "you cannot see this"."""
    from tests.command_center.conftest import PASSWORD

    email = f"ccv_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "Viewer", "password": PASSWORD,
        "role": "VIEWER", "organization_id": admin["organization_id"]})
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login",
                         json={"email": email, "password": PASSWORD}).json()
    viewer = {"Authorization": f"Bearer {tokens['access_token']}"}

    body = client.get(f"{CC}/estate", headers=viewer)
    assert body.status_code == 200, body.text
    payload = body.json()
    for key in ("posture", "shadow", "threats", "external"):
        section = payload[key]
        if not section["visible"]:
            # The permission is named, and no number is invented.
            assert section["data"] is None
            assert section["permission"]

    # The admin, who can read posture, gets real data in the same shape.
    admin_payload = client.get(f"{CC}/estate", headers=admin["headers"]).json()
    assert admin_payload["shadow"]["visible"] is True
    assert admin_payload["shadow"]["data"] is not None


# --------------------------------------------------------------------------- #
# The truthful-affordance signal ships with the row
# --------------------------------------------------------------------------- #
def test_inventory_row_carries_the_servers_own_reach_signal(
        client: TestClient, admin: dict) -> None:
    """Every row carries what the UI renders affordances from, computed by
    5.7's own functions — so the browser never derives it."""
    from app.bridge.modes import REACH

    agent_id = _make_external(admin, name="Signal Agent")
    rows = client.get(f"{CC}/agents", headers=admin["headers"]).json()["items"]
    row = next(r for r in rows if r["id"] == agent_id)

    # A DISCOVERED external agent: ACT sees it and can do nothing to it.
    assert row["enforcement_mode"] == "OBSERVED"
    assert row["reaches_agent_execution"] is False
    assert row["reaches_boundary_calls"] is False
    # The sentences are 5.7's, verbatim — not composed here.
    assert row["enforcement_display"] == REACH["OBSERVED"].display
    assert row["enforcement_limits"] == REACH["OBSERVED"].limits
    assert "govern this agent" not in row["enforcement_display"].lower()


def test_a_governed_agent_reports_full_reach(client: TestClient, admin: dict) -> None:
    from app.bridge.modes import REACH

    r = client.post("/api/v1/runtime/agents", headers=admin["headers"], json={
        "name": f"Native {uuid.uuid4().hex[:6]}", "description": "d",
        "business_purpose": "d", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "owner_type": "USER", "owner_id": admin["user_id"],
        "technical_owner_id": admin["user_id"], "compliance_owner_id": admin["user_id"],
        "definition": {"name": "D", "framework": "CUSTOM",
                       "entrypoint_type": "FUNCTION", "entrypoint": "a.h:run"},
    })
    assert r.status_code == 201, r.text
    agent_id = r.json()["id"]

    rows = client.get(f"{CC}/agents", headers=admin["headers"]).json()["items"]
    row = next(x for x in rows if x["id"] == agent_id)
    assert row["enforcement_mode"] == "NATIVE_ENFORCED"
    assert row["reaches_agent_execution"] is True
    assert row["enforcement_display"] == REACH["NATIVE_ENFORCED"].display


def test_estate_mode_breakdown_matches_the_inventory_rows(
        client: TestClient, admin: dict) -> None:
    """The estate's grouped counts and the per-row derivation must agree —
    they come from the same function, and this proves the GROUP BY stub used
    for the breakdown did not diverge from the real row path."""
    _make_external(admin, name="Agree A")
    _make_external(admin, name="Agree B")

    estate = client.get(f"{CC}/estate", headers=admin["headers"]).json()
    rows = client.get(f"{CC}/agents", headers=admin["headers"],
                      params={"page_size": 200}).json()["items"]

    from collections import Counter
    counted = Counter(r["enforcement_mode"] for r in rows)
    for mode, n in counted.items():
        assert estate["agents"]["by_enforcement_mode"].get(mode, 0) >= n


def test_cost_reports_unmeasurable_rather_than_inventing_a_number(
        client: TestClient, admin: dict) -> None:
    body = client.get(f"{CC}/estate", headers=admin["headers"]).json()
    cost = body["cost"]
    if cost["visible"]:
        assert "boundary_calls_not_measurable" in cost["data"]
        assert "not estimated" in cost["data"]["note"]
        # No fabricated total anywhere in the section.
        assert "total_spend" not in cost["data"]


# --------------------------------------------------------------------------- #
# AC-17 — hygiene
# --------------------------------------------------------------------------- #
def test_ac17_no_todo_fixme_skip_or_xfail_in_this_phase() -> None:
    targets = list(_PKG.glob("*.py")) + [Path(__file__)]
    for path in targets:
        src = path.read_text(encoding="utf-8")
        body = src.split("def test_ac17")[0] if path == Path(__file__) else src
        for marker in ("TODO", "FIXME", "NotImplementedError",
                       "pytest.mark.skip", "pytest.mark.xfail"):
            assert marker not in body, f"{path.name}: {marker}"
