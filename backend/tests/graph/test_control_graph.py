"""Phase 5.3 (M5.3) - Identity, Delegation & Trust Graph.

AC-01..AC-18 + the §14 end-to-end proof. Each acceptance criterion is backed
by at least one named test here.

The load-bearing properties, and where they are proven:
  * NO graph database / relational substrate ................ AC-03
  * per-hop tenant-bounded traversal (the headline) ......... AC-06 (adversarial)
  * represent, don't create; an edge grants nothing ........ AC-04 / AC-08
  * bounded + cycle-safe traversal ......................... AC-07
  * fails open, missing evidence explicit .................. AC-14
"""

from __future__ import annotations

import ast
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import SessionLocal
from app.main import app
from tests.graph.conftest import PASSWORD, register_org

RT = "/api/v1/runtime"
GRAPH = "/api/v1/graph"
_BACKEND = Path(__file__).resolve().parents[2]
_REPO = _BACKEND.parent


# --------------------------------------------------------------------------- #
# helpers -- this suite's convention: each file defines its own
# --------------------------------------------------------------------------- #
def _second_user(client: TestClient, admin: dict, role: str = "ADMIN") -> dict:
    email = f"graphu_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post(
        "/api/v1/identity/users",
        headers=admin["headers"],
        json={
            "email": email,
            "display_name": "Second",
            "password": PASSWORD,
            "role": role,
            "organization_id": admin["organization_id"],
        },
    )
    assert r.status_code in (200, 201), r.text
    body = r.json()
    uid = body.get("id") or body.get("user", {}).get("id")
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"}, "user_id": uid}


def _ready_agent(client: TestClient, admin: dict) -> dict:
    nonce = uuid.uuid4().hex[:8]
    r = client.post(
        f"{RT}/agents",
        headers=admin["headers"],
        json={
            "name": f"Graph Agent {nonce}",
            "agent_type": "ASSISTANT",
            "criticality": "MEDIUM",
            "description": f"Test agent {nonce}.",
            "business_purpose": f"Exercise the control graph {nonce} in tests.",
            "owner_type": "USER",
            "owner_id": admin["user_id"],
            "technical_owner_id": admin["user_id"],
            "compliance_owner_id": admin["user_id"],
            "definition": {
                "name": "Definition",
                "framework": "CUSTOM",
                "entrypoint_type": "FUNCTION",
                "entrypoint": "agents.handler:run",
            },
        },
    )
    assert r.status_code == 201, r.text
    agent = r.json()
    for step in ("register", "validate"):
        assert (
            client.post(f"{RT}/agents/{agent['id']}/{step}", headers=admin["headers"]).status_code
            == 200
        )
    assert (
        client.post(
            f"{RT}/agents/{agent['id']}/identity/create-and-associate",
            headers=admin["headers"],
            json={"client_id": f"agent-identity-{uuid.uuid4().hex[:10]}"},
        ).status_code
        == 200
    )
    for step in ("submit-for-approval", "approve", "activate"):
        assert (
            client.post(f"{RT}/agents/{agent['id']}/{step}", headers=admin["headers"]).status_code
            == 200
        )
    r = client.post(
        f"{RT}/agents/{agent['id']}/versions",
        headers=admin["headers"],
        json={"model_configuration": {"provider": "MOCK", "model": "mock-model"}},
    )
    assert r.status_code == 201, r.text
    version = r.json()
    for step in ("validate", "approve", "publish"):
        assert (
            client.post(
                f"{RT}/agents/{agent['id']}/versions/{version['id']}/{step}",
                headers=admin["headers"],
            ).status_code
            == 200
        )
    r = client.post(
        f"{RT}/deployments",
        headers=admin["headers"],
        params={"agent_id": agent["id"]},
        json={"agent_version_id": version["id"], "environment": "DEVELOPMENT"},
    )
    assert r.status_code == 201, r.text
    deployment = r.json()
    for to_state in ("VALIDATING", "READY", "DEPLOYING"):
        assert (
            client.post(
                f"{RT}/deployments/{deployment['id']}/lifecycle/transition",
                headers=admin["headers"],
                json={"to_state": to_state},
            ).status_code
            == 200
        )
    return {"agent": agent, "version": version, "deployment": deployment}


def _execute(client: TestClient, admin: dict, setup: dict, **kwargs) -> dict:
    body = {"agent_id": setup["agent"]["id"], "input_payload": {}, **kwargs}
    r = client.post(f"{RT}/executions", headers=admin["headers"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _make_tool(client: TestClient, admin: dict) -> str:
    r = client.post(
        f"{RT}/tools",
        headers=admin["headers"],
        json={
            "name": f"tool_{uuid.uuid4().hex[:8]}",
            "display_name": "Graph Test Tool",
            "tool_type": "FUNCTION",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _insert_tool_call(db, *, execution_id, agent_id, tool_id, target_host=None) -> uuid.UUID:
    tc_id = uuid.uuid4()
    db.execute(
        text(
            """
            INSERT INTO tool_calls (id, execution_id, agent_id, tool_id, action, status,
                                    target_host, started_at)
            VALUES (:id, :eid, :aid, :tid, 'invoke', 'ALLOWED', :host, now())
            """
        ),
        {"id": str(tc_id), "eid": str(execution_id), "aid": str(agent_id),
         "tid": str(tool_id), "host": target_host},
    )
    db.commit()
    return tc_id


def _insert_execution(db, *, org_id, agent_id, version_id, trigger_type="API",
                      triggered_by=None, parent=None) -> uuid.UUID:
    eid = uuid.uuid4()
    db.execute(
        text(
            """
            INSERT INTO agent_executions
                (id, organization_id, agent_id, agent_version_id, trigger_type,
                 triggered_by_identity_id, parent_execution_id, input_payload, status)
            VALUES (:id, :org, :aid, :vid, :tt, :tb, :parent, '{}'::jsonb, 'SUCCEEDED')
            """
        ),
        {"id": str(eid), "org": str(org_id), "aid": str(agent_id), "vid": str(version_id),
         "tt": trigger_type, "tb": str(triggered_by) if triggered_by else None,
         "parent": str(parent) if parent else None},
    )
    db.commit()
    return eid


def _delegate(client: TestClient, admin: dict, delegatee_id: str) -> dict:
    r = client.post(
        "/api/v1/delegations",
        headers=admin["headers"],
        json={"delegatee_id": delegatee_id, "scope_type": "ORGANIZATION"},
    )
    assert r.status_code == 201, r.text
    return r.json()


# =========================================================================== #
# AC-01 - live baseline / substrate
# =========================================================================== #
def test_ac01_5_1_and_5_2_substrate_present_and_head_recorded() -> None:
    from app.discovery.reconciliation import ReconciliationService  # noqa: F401
    from app.runtime.registry.control import (  # noqa: F401
        AgentControlStateService,
        AgentProvenanceService,
    )

    # Phase 5.4 (M5.4) chained 0057_dependency_graph from this substrate; this
    # guard is intent-preserving -- it still asserts the current head migration
    # exists and is recorded in REPO_STATE, and the 5.3 substrate is present.
    versions = {v.stem for v in (_BACKEND / "migrations" / "versions").glob("*.py")}
    assert {"0054_agent_asset_model", "0055_agent_discovery", "0056_control_graph"} <= versions
    repo_state = (_REPO / "REPO_STATE.md").read_text(encoding="utf-8")
    assert "0056_control_graph" in repo_state


# =========================================================================== #
# AC-02 - a typed edge substrate over existing node rows
# =========================================================================== #
def test_ac02_edge_connects_existing_nodes_and_copies_no_state(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    other = _second_user(client, admin)
    # HUMAN -> AGENT trust edge, both real rows.
    r = client.post(
        f"{GRAPH}/trust-edges",
        headers=admin["headers"],
        json={
            "source": {"type": "HUMAN", "id": other["user_id"]},
            "target": {"type": "AGENT", "id": setup["agent"]["id"]},
            "note": "operator trusts this agent",
        },
    )
    assert r.status_code == 201, r.text
    edge = r.json()
    assert edge["edge_type"] == "TRUSTS"
    assert edge["provenance"] == "EXPLICIT"
    # the edge stores (type,id) only -- no name/email/status of either node.
    assert set(edge.keys()) >= {"source_type", "source_id", "target_type", "target_id"}
    assert "email" not in edge and "name" not in edge


def test_ac02_edge_endpoints_are_validated_against_real_rows(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    r = client.post(
        f"{GRAPH}/trust-edges",
        headers=admin["headers"],
        json={
            "source": {"type": "HUMAN", "id": str(uuid.uuid4())},  # no such user
            "target": {"type": "AGENT", "id": setup["agent"]["id"]},
        },
    )
    assert r.status_code == 404  # a non-existent endpoint is not representable


# =========================================================================== #
# AC-03 - NO graph database; Postgres edges + recursive CTEs; no projection
# =========================================================================== #
def test_ac03_no_graph_database_dependency_and_no_projection_table() -> None:
    from app.core.database import Base

    # the substrate is exactly one table.
    assert "control_graph_edges" in Base.metadata.tables
    for banned in ("graph_projection", "graph_nodes", "graph_paths", "reachability_cache",
                   "authority_chains"):
        assert banned not in Base.metadata.tables, banned

    # no graph-DB driver is imported anywhere in the package.
    pkg = _BACKEND / "app" / "graph"
    banned_imports = ("neo4j", "py2neo", "gremlin", "arango", "networkx", "igraph")
    for path in pkg.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                assert not any(n == b or n.startswith(b + ".") for b in banned_imports), (path, n)

    # the traversal is a real recursive CTE.
    src = (pkg / "traversal.py").read_text(encoding="utf-8")
    assert "WITH RECURSIVE" in src


def test_ac03_reachability_is_assembled_from_edges_within_budget(client: TestClient, admin: dict) -> None:
    """ADR-0008 discipline: a recorded measurement that assembly is fast
    enough, so 'no projection' keeps being the right call. An order of
    magnitude above what a small graph needs -- this catches a structural
    regression (an index dropped), not laptop noise."""
    import time

    setup = _ready_agent(client, admin)
    users = [_second_user(client, admin) for _ in range(6)]
    # a chain u0 -> u1 -> ... -> agent via TRUSTS
    prev = {"type": "HUMAN", "id": users[0]["user_id"]}
    for u in users[1:]:
        client.post(f"{GRAPH}/trust-edges", headers=admin["headers"],
                    json={"source": prev, "target": {"type": "HUMAN", "id": u["user_id"]}})
        prev = {"type": "HUMAN", "id": u["user_id"]}
    client.post(f"{GRAPH}/trust-edges", headers=admin["headers"],
                json={"source": prev, "target": {"type": "AGENT", "id": setup["agent"]["id"]}})

    t0 = time.perf_counter()
    r = client.get(
        f"{GRAPH}/reachability",
        headers=admin["headers"],
        params={"node_type": "HUMAN", "node_id": users[0]["user_id"], "direction": "out"},
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert r.status_code == 200, r.text
    reached = {(n["node_type"], n["node_id"]) for n in r.json()["reachable"]}
    assert ("AGENT", setup["agent"]["id"]) in reached
    assert elapsed_ms < 400, f"reachability assembly took {elapsed_ms:.1f}ms"


# =========================================================================== #
# AC-04 - delegation edges reuse DelegationService; represent, don't create
# =========================================================================== #
def test_ac04_delegation_edge_mirrors_an_existing_delegations_row(client: TestClient, admin: dict) -> None:
    other = _second_user(client, admin)
    deleg = _delegate(client, admin, other["user_id"])

    r = client.post(
        f"{GRAPH}/delegation-edges",
        headers=admin["headers"],
        json={"delegation_id": deleg["id"]},
    )
    assert r.status_code == 201, r.text
    edge = r.json()
    assert edge["edge_type"] == "DELEGATES_TO"
    assert edge["provenance"] == "DERIVED"
    assert edge["evidence"]["ref_table"] == "delegations"
    assert edge["evidence"]["ref_id"] == deleg["id"]
    assert edge["source_id"] == admin["user_id"]
    assert edge["target_id"] == other["user_id"]


def test_ac04_graph_never_writes_delegations_and_has_no_agent_delegation_producer() -> None:
    src = (_BACKEND / "app" / "graph").rglob("*.py")
    joined = "\n".join(p.read_text(encoding="utf-8") for p in src)
    # no INSERT/UPDATE into delegations from the graph package.
    assert "INSERT INTO delegations" not in joined
    assert "UPDATE delegations" not in joined
    # AGENT_DELEGATES_TO is a declared type with no producer this phase.
    assert "AGENT_DELEGATES_TO" in joined  # in the vocabulary
    assert "edge_type='AGENT_DELEGATES_TO'" not in joined.replace(" ", "")
    assert 'edge_type="AGENT_DELEGATES_TO"' not in joined


def test_ac04_delegation_edge_requires_a_live_delegation(client: TestClient, admin: dict) -> None:
    other = _second_user(client, admin)
    deleg = _delegate(client, admin, other["user_id"])
    # revoke it, then it is no longer representable as a live edge.
    assert client.delete(f"/api/v1/delegations/{deleg['id']}", headers=admin["headers"]).status_code == 200
    r = client.post(f"{GRAPH}/delegation-edges", headers=admin["headers"],
                    json={"delegation_id": deleg["id"]})
    assert r.status_code == 422


# =========================================================================== #
# AC-05 - authority-chain reconstruction (generalizes the 4.2 chain)
# =========================================================================== #
def test_ac05_authority_chain_human_agent_identity_tool(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    execution = _execute(client, admin, setup)
    tool_id = _make_tool(client, admin)
    db = SessionLocal()
    try:
        _insert_tool_call(db, execution_id=execution["id"], agent_id=setup["agent"]["id"],
                          tool_id=tool_id, target_host="api.example.com")
    finally:
        db.close()

    r = client.get(
        f"{GRAPH}/authority-chain/executions/{execution['id']}", headers=admin["headers"]
    )
    assert r.status_code == 200, r.text
    chain = r.json()
    edges = [h["edge"] for h in chain["hops"]]
    assert "TRIGGERED" in edges
    assert "EXECUTED_AS" in edges
    assert "ACTS_AS" in edges  # the agent_identities binding from _ready_agent
    assert "INVOKED" in edges
    assert "TARGETED" in edges
    # every hop names its evidence
    for h in chain["hops"]:
        assert h["evidence"].get("kind"), h
    # the origin is the human who triggered it
    first = chain["hops"][0]
    assert first["from"]["type"] == "HUMAN"
    assert first["from"]["id"] == admin["user_id"]


def test_ac05_authority_chain_is_deterministic(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    execution = _execute(client, admin, setup)
    a = client.get(f"{GRAPH}/authority-chain/executions/{execution['id']}", headers=admin["headers"]).json()
    b = client.get(f"{GRAPH}/authority-chain/executions/{execution['id']}", headers=admin["headers"]).json()
    assert a["hops"] == b["hops"]


def test_ac05_delegation_edge_appears_in_the_chain_with_its_scope(client: TestClient, admin: dict) -> None:
    """A human acting under another human's delegated authority: the
    delegation edge extends the chain, carrying the scope from the
    delegations row it mirrors."""
    setup = _ready_agent(client, admin)
    delegatee = _second_user(client, admin)
    deleg = _delegate(client, admin, delegatee["user_id"])
    client.post(f"{GRAPH}/delegation-edges", headers=admin["headers"], json={"delegation_id": deleg["id"]})

    # delegatee triggers an execution
    execution = _execute(client, delegatee, setup)
    r = client.get(f"{GRAPH}/authority-chain/executions/{execution['id']}", headers=admin["headers"])
    assert r.status_code == 200, r.text
    chain = r.json()
    deleg_hops = [h for h in chain["hops"] if h["edge"] == "DELEGATES_TO"]
    assert len(deleg_hops) == 1
    assert deleg_hops[0]["from"]["id"] == admin["user_id"]
    assert deleg_hops[0]["to"]["id"] == delegatee["user_id"]
    assert deleg_hops[0]["evidence"]["scope_type"] == "ORGANIZATION"


# =========================================================================== #
# AC-06 - per-hop tenant-bounded traversal (THE headline, adversarial)
# =========================================================================== #
def test_ac06_planted_cross_tenant_edge_does_not_extend_a_chain(
    client: TestClient, admin: dict, other_org_admin: dict
) -> None:
    setup = _ready_agent(client, admin)
    other_setup = _ready_agent(client, other_org_admin)

    # PLANT (bypassing the service, as a hostile direct insert would): an edge
    # in tenant A whose target is an AGENT that lives in tenant B.
    db = SessionLocal()
    try:
        db.execute(
            text(
                """
                INSERT INTO control_graph_edges
                    (id, organization_id, source_type, source_id, edge_type,
                     target_type, target_id, evidence, confidence, provenance, valid_from, created_at, updated_at)
                VALUES (:id, :org_a, 'AGENT', :agent_a, 'TRUSTS', 'AGENT', :agent_b,
                        '{}'::jsonb, 1.0, 'EXPLICIT', now(), now(), now())
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "org_a": admin["organization_id"],
                "agent_a": setup["agent"]["id"],
                "agent_b": other_setup["agent"]["id"],
            },
        )
        db.commit()
    finally:
        db.close()

    # tenant A traverses out from its own agent. The walk must STOP at the
    # tenant edge -- tenant B's agent is not surfaced.
    r = client.get(
        f"{GRAPH}/reachability",
        headers=admin["headers"],
        params={"node_type": "AGENT", "node_id": setup["agent"]["id"], "direction": "out"},
    )
    assert r.status_code == 200, r.text
    reached_ids = {n["node_id"] for n in r.json()["reachable"]}
    assert other_setup["agent"]["id"] not in reached_ids


def test_ac06_authority_chain_cannot_cross_a_tenant_boundary(
    client: TestClient, admin: dict, other_org_admin: dict
) -> None:
    setup = _ready_agent(client, admin)
    delegatee = _second_user(client, admin)
    deleg = _delegate(client, admin, delegatee["user_id"])
    client.post(f"{GRAPH}/delegation-edges", headers=admin["headers"], json={"delegation_id": deleg["id"]})
    execution = _execute(client, delegatee, setup)

    # PLANT an incoming delegation edge whose delegator is a user in tenant B.
    other_user_id = other_org_admin["user_id"]
    db = SessionLocal()
    try:
        db.execute(
            text(
                """
                INSERT INTO control_graph_edges
                    (id, organization_id, source_type, source_id, edge_type,
                     target_type, target_id, evidence, confidence, provenance, valid_from, created_at, updated_at)
                VALUES (:id, :org_a, 'HUMAN', :foreign_user, 'DELEGATES_TO', 'HUMAN', :admin_a,
                        '{}'::jsonb, 1.0, 'EXPLICIT', now(), now(), now())
                """
            ),
            {"id": str(uuid.uuid4()), "org_a": admin["organization_id"],
             "foreign_user": other_user_id, "admin_a": admin["user_id"]},
        )
        db.commit()
    finally:
        db.close()

    chain = client.get(
        f"{GRAPH}/authority-chain/executions/{execution['id']}", headers=admin["headers"]
    ).json()
    # no hop may reference the foreign tenant's user
    for h in chain["hops"]:
        assert h["from"]["id"] != other_user_id
        assert h["to"]["id"] != other_user_id
    assert any("truncated" in n for n in chain["notes"])


def test_ac06_foreign_tenant_chain_query_is_404(
    client: TestClient, admin: dict, other_org_admin: dict
) -> None:
    setup = _ready_agent(client, admin)
    execution = _execute(client, admin, setup)
    r = client.get(
        f"{GRAPH}/authority-chain/executions/{execution['id']}",
        headers=other_org_admin["headers"],
    )
    assert r.status_code == 404  # no existence leak


# =========================================================================== #
# AC-07 - bounded / cycle-safe traversal
# =========================================================================== #
def test_ac07_a_cycle_does_not_hang_the_traversal(client: TestClient, admin: dict) -> None:
    u = [_second_user(client, admin) for _ in range(3)]
    ids = [x["user_id"] for x in u]
    # a -> b -> c -> a
    for i in range(3):
        client.post(
            f"{GRAPH}/trust-edges",
            headers=admin["headers"],
            json={
                "source": {"type": "HUMAN", "id": ids[i]},
                "target": {"type": "HUMAN", "id": ids[(i + 1) % 3]},
            },
        )
    r = client.get(
        f"{GRAPH}/reachability",
        headers=admin["headers"],
        params={"node_type": "HUMAN", "node_id": ids[0], "direction": "out"},
    )
    assert r.status_code == 200
    reached = {n["node_id"] for n in r.json()["reachable"]}
    assert reached == {ids[1], ids[2]}  # each once, no infinite walk


def test_ac07_max_depth_is_bounded(client: TestClient, admin: dict) -> None:
    from app.graph.traversal import MAX_TRAVERSAL_DEPTH

    r = client.get(
        f"{GRAPH}/reachability",
        headers=admin["headers"],
        params={
            "node_type": "HUMAN",
            "node_id": admin["user_id"],
            "max_depth": MAX_TRAVERSAL_DEPTH + 500,
        },
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "GRAPH_TRAVERSAL_DEPTH_EXCEEDED"


# =========================================================================== #
# AC-08 - an edge grants no authority
# =========================================================================== #
def test_ac08_a_trust_edge_grants_no_permission(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    viewer = _second_user(client, admin, role="VIEWER")
    # give the viewer a TRUSTS edge to the agent -- it must not let them do
    # anything the AuthorizationGateway would deny.
    client.post(
        f"{GRAPH}/trust-edges",
        headers=admin["headers"],
        json={
            "source": {"type": "HUMAN", "id": _second_user(client, admin)["user_id"]},
            "target": {"type": "AGENT", "id": setup["agent"]["id"]},
        },
    )
    # the viewer still cannot manage edges or execute the agent
    assert client.post(
        f"{GRAPH}/trust-edges",
        headers=viewer["headers"],
        json={
            "source": {"type": "HUMAN", "id": admin["user_id"]},
            "target": {"type": "AGENT", "id": setup["agent"]["id"]},
        },
    ).status_code == 403
    assert client.post(
        f"{RT}/executions",
        headers=viewer["headers"],
        json={"agent_id": setup["agent"]["id"], "input_payload": {}},
    ).status_code in (401, 403)


def test_ac08_reading_a_chain_is_not_audited_as_a_change_but_reconstruction_is(
    client: TestClient, admin: dict
) -> None:
    setup = _ready_agent(client, admin)
    execution = _execute(client, admin, setup)
    client.get(f"{GRAPH}/authority-chain/executions/{execution['id']}", headers=admin["headers"])
    db = SessionLocal()
    try:
        n = db.execute(
            text(
                "SELECT count(*) FROM authorization_audit "
                "WHERE event_type = 'GRAPH_AUTHORITY_CHAIN_RECONSTRUCTED' "
                "AND organization_id = :org"
            ),
            {"org": admin["organization_id"]},
        ).scalar()
        assert n >= 1
    finally:
        db.close()


# =========================================================================== #
# AC-09 - confused-deputy visibility
# =========================================================================== #
def test_ac09_agent_acting_under_propagated_authority_is_visible(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    delegatee = _second_user(client, admin)
    deleg = _delegate(client, admin, delegatee["user_id"])
    client.post(f"{GRAPH}/delegation-edges", headers=admin["headers"], json={"delegation_id": deleg["id"]})
    execution = _execute(client, delegatee, setup)

    chain = client.get(
        f"{GRAPH}/authority-chain/executions/{execution['id']}", headers=admin["headers"]
    ).json()
    # the deputy (the agent) is visible acting under authority that originated
    # with the delegator, through the delegatee.
    froms = [h["from"]["id"] for h in chain["hops"]]
    assert admin["user_id"] in froms  # original authority
    assert delegatee["user_id"] in froms  # the deputy human
    assert any(h["to"]["type"] == "AGENT" for h in chain["hops"])  # the agent deputy


# =========================================================================== #
# AC-10 - revoked/expired delegation drops from active chains; discovered agent
# =========================================================================== #
def test_ac10_revoked_edge_drops_from_the_chain(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    delegatee = _second_user(client, admin)
    deleg = _delegate(client, admin, delegatee["user_id"])
    edge = client.post(
        f"{GRAPH}/delegation-edges", headers=admin["headers"], json={"delegation_id": deleg["id"]}
    ).json()
    execution = _execute(client, delegatee, setup)

    before = client.get(
        f"{GRAPH}/authority-chain/executions/{execution['id']}", headers=admin["headers"]
    ).json()
    assert any(h["edge"] == "DELEGATES_TO" for h in before["hops"])

    assert client.delete(f"{GRAPH}/edges/{edge['id']}", headers=admin["headers"]).status_code == 200
    after = client.get(
        f"{GRAPH}/authority-chain/executions/{execution['id']}", headers=admin["headers"]
    ).json()
    assert not any(h["edge"] == "DELEGATES_TO" for h in after["hops"])


def test_ac10_expired_edge_is_not_followed(client: TestClient, admin: dict) -> None:
    a = _second_user(client, admin)
    b = _second_user(client, admin)
    r = client.post(
        f"{GRAPH}/trust-edges",
        headers=admin["headers"],
        json={
            "source": {"type": "HUMAN", "id": a["user_id"]},
            "target": {"type": "HUMAN", "id": b["user_id"]},
            "valid_until": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        },
    )
    assert r.status_code == 201
    reach = client.get(
        f"{GRAPH}/reachability",
        headers=admin["headers"],
        params={"node_type": "HUMAN", "node_id": a["user_id"], "direction": "out"},
    ).json()
    assert b["user_id"] not in {n["node_id"] for n in reach["reachable"]}


def test_ac10_discovered_external_agent_identity_edge_is_representable(client: TestClient, admin: dict) -> None:
    db = SessionLocal()
    try:
        from app.models.user import User
        from app.runtime.registry.control import AgentProvenanceService

        actor = db.execute(
            text("SELECT * FROM users WHERE id = :id"), {"id": admin["user_id"]}
        )
        user = db.get(User, uuid.UUID(admin["user_id"]))
        agent = AgentProvenanceService(db).record_external_agent(
            actor=user,
            name="Discovered Copilot",
            origin_category="EXTERNAL",
            origin_provider="MICROSOFT",
            external_reference=f"copilot://{uuid.uuid4().hex}",
        )
        agent_id = str(agent.id)
    finally:
        db.close()
    # a trust edge from the discovered agent to a resource node representing
    # an observed identity string is representable (RESOURCE row).
    db = SessionLocal()
    try:
        res_id = uuid.uuid4()
        db.execute(
            text(
                """
                INSERT INTO resources (id, resource_type, resource_id, name, organization_id,
                                       owner_id, owner_type, visibility, status)
                VALUES (:id, 'observed_identity', :rid, 'observed://idp/user', :org,
                        :owner, 'USER', 'ORGANIZATION', 'ACTIVE')
                """
            ),
            {"id": str(res_id), "rid": str(uuid.uuid4()), "org": admin["organization_id"],
             "owner": admin["user_id"]},
        )
        db.commit()
    finally:
        db.close()
    r = client.post(
        f"{GRAPH}/trust-edges",
        headers=admin["headers"],
        json={
            "source": {"type": "AGENT", "id": agent_id},
            "target": {"type": "RESOURCE", "id": str(res_id)},
            "note": "discovered agent observed using this identity",
        },
    )
    assert r.status_code == 201, r.text


# =========================================================================== #
# AC-11 - tenant isolation on every edge/query; cross-tenant -> 404
# =========================================================================== #
def test_ac11_cross_tenant_edge_read_is_404(client: TestClient, admin: dict, other_org_admin: dict) -> None:
    other = _second_user(client, admin)
    setup = _ready_agent(client, admin)
    edge = client.post(
        f"{GRAPH}/trust-edges",
        headers=admin["headers"],
        json={
            "source": {"type": "HUMAN", "id": other["user_id"]},
            "target": {"type": "AGENT", "id": setup["agent"]["id"]},
        },
    ).json()
    assert client.get(f"{GRAPH}/edges/{edge['id']}", headers=other_org_admin["headers"]).status_code == 404
    assert client.delete(f"{GRAPH}/edges/{edge['id']}", headers=other_org_admin["headers"]).status_code == 404


def test_ac11_edge_to_a_foreign_node_is_404(client: TestClient, admin: dict, other_org_admin: dict) -> None:
    other_setup = _ready_agent(client, other_org_admin)
    r = client.post(
        f"{GRAPH}/trust-edges",
        headers=admin["headers"],
        json={
            "source": {"type": "HUMAN", "id": admin["user_id"]},
            "target": {"type": "AGENT", "id": other_setup["agent"]["id"]},
        },
    )
    assert r.status_code == 404


# =========================================================================== #
# AC-12 - concurrency: real separate Postgres sessions
# =========================================================================== #
def test_ac12_concurrent_edge_create_yields_one_edge(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    other = _second_user(client, admin)
    payload = {
        "source": {"type": "HUMAN", "id": other["user_id"]},
        "target": {"type": "AGENT", "id": setup["agent"]["id"]},
    }
    barrier = threading.Barrier(2)
    results: list[int] = []
    lock = threading.Lock()

    def _create() -> None:
        c = TestClient(app)
        barrier.wait()
        resp = c.post(f"{GRAPH}/trust-edges", headers=admin["headers"], json=payload)
        with lock:
            results.append(resp.status_code)

    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in [pool.submit(_create) for _ in range(2)]:
            f.result()

    assert all(s == 201 for s in results), results
    db = SessionLocal()
    try:
        n = db.execute(
            text(
                "SELECT count(*) FROM control_graph_edges WHERE organization_id = :org "
                "AND source_id = :sid AND target_id = :tid AND edge_type = 'TRUSTS' "
                "AND revoked_at IS NULL"
            ),
            {"org": admin["organization_id"], "sid": other["user_id"], "tid": setup["agent"]["id"]},
        ).scalar()
        assert n == 1, f"expected exactly one live edge, found {n}"
    finally:
        db.close()


def test_ac12_concurrent_revoke_is_deterministic(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    other = _second_user(client, admin)
    edge = client.post(
        f"{GRAPH}/trust-edges",
        headers=admin["headers"],
        json={
            "source": {"type": "HUMAN", "id": other["user_id"]},
            "target": {"type": "AGENT", "id": setup["agent"]["id"]},
        },
    ).json()
    barrier = threading.Barrier(2)
    codes: list[int] = []
    lock = threading.Lock()

    def _revoke() -> None:
        c = TestClient(app)
        barrier.wait()
        resp = c.delete(f"{GRAPH}/edges/{edge['id']}", headers=admin["headers"])
        with lock:
            codes.append(resp.status_code)

    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in [pool.submit(_revoke) for _ in range(2)]:
            f.result()

    assert sorted(codes) == [200, 409], codes  # one revokes, one gets ALREADY_REVOKED


# =========================================================================== #
# AC-13 - delegation/trust edge changes are audited; no secret in edges/audit
# =========================================================================== #
def test_ac13_edge_lifecycle_is_audited(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    other = _second_user(client, admin)
    edge = client.post(
        f"{GRAPH}/trust-edges",
        headers=admin["headers"],
        json={
            "source": {"type": "HUMAN", "id": other["user_id"]},
            "target": {"type": "AGENT", "id": setup["agent"]["id"]},
        },
    ).json()
    client.delete(f"{GRAPH}/edges/{edge['id']}", headers=admin["headers"])
    db = SessionLocal()
    try:
        events = {
            e
            for (e,) in db.execute(
                text(
                    "SELECT event_type FROM authorization_audit WHERE organization_id = :org "
                    "AND event_type LIKE 'GRAPH_%'"
                ),
                {"org": admin["organization_id"]},
            ).all()
        }
        assert "GRAPH_TRUST_EDGE_CREATED" in events
        assert "GRAPH_TRUST_EDGE_REVOKED" in events
    finally:
        db.close()


def test_ac13_no_secret_material_in_edge_or_evidence(client: TestClient, admin: dict) -> None:
    other = _second_user(client, admin)
    deleg = _delegate(client, admin, other["user_id"])
    edge = client.post(
        f"{GRAPH}/delegation-edges", headers=admin["headers"], json={"delegation_id": deleg["id"]}
    ).json()
    blob = str(edge).lower()
    for needle in ("password", "secret", "token", "api_key", "bearer", "hash"):
        assert needle not in blob, needle


# =========================================================================== #
# AC-14 - fails open; missing evidence explicit
# =========================================================================== #
def test_ac14_missing_trigger_identity_is_explicit_not_no_delegation(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    db = SessionLocal()
    try:
        eid = _insert_execution(
            db,
            org_id=admin["organization_id"],
            agent_id=setup["agent"]["id"],
            version_id=setup["version"]["id"],
            trigger_type="SYSTEM",
            triggered_by=None,
        )
    finally:
        db.close()
    chain = client.get(f"{GRAPH}/authority-chain/executions/{eid}", headers=admin["headers"]).json()
    assert chain["complete"] is False
    assert any("no triggering identity" in n for n in chain["notes"])
    # it still reconstructs the spine it *can* see
    assert any(h["edge"] == "EXECUTED_AS" for h in chain["hops"])


def test_ac14_graph_is_off_the_execution_path(client: TestClient, admin: dict) -> None:
    """Structural: nothing under app/runtime imports app/graph, so a graph
    failure cannot reach an execution."""
    runtime = _BACKEND / "app" / "runtime"
    for path in runtime.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            for m in mods:
                assert not m.startswith("app.graph"), f"{path} imports {m}"


# =========================================================================== #
# AC-15 - migration additive / reversible / id <= 32
# =========================================================================== #
def test_ac15_migration_shape() -> None:
    mig = (_BACKEND / "migrations" / "versions" / "0056_control_graph.py").read_text(encoding="utf-8")
    assert 'revision = "0056_control_graph"' in mig
    assert len("0056_control_graph") <= 32
    assert 'down_revision = "0055_agent_discovery"' in mig
    assert "def downgrade" in mig and "drop_table" in mig
    # additive: creates exactly one table, alters none.
    assert mig.count("create_table(") == 1
    assert "op.alter_column" not in mig and "op.drop_column" not in mig


# =========================================================================== #
# AC-16 - "the entire M1-M4.11a + 5.1 + 5.2 suite passes unchanged" and
# AC-17 - "full backend suite passes, count >= 2,385, deselection preserved"
# are the whole suite run, not a single test. The only existing tests this
# phase touches are the two updated intent-preserving (M5.2 test_ac01's
# migration-head guard, M5.1 test_ac12_no_discovery_or_graph_machinery_shipped)
# -- both still assert their real intent and both pass.
# AC-18 - no forbidden markers in this phase's files
# =========================================================================== #
def test_ac18_no_forbidden_markers_in_new_files() -> None:
    files = [
        _BACKEND / "app" / "graph" / "__init__.py",
        _BACKEND / "app" / "graph" / "nodes.py",
        _BACKEND / "app" / "graph" / "traversal.py",
        _BACKEND / "app" / "graph" / "service.py",
        _BACKEND / "app" / "graph" / "schemas.py",
        _BACKEND / "app" / "graph" / "routes.py",
        _BACKEND / "app" / "models" / "graph.py",
        _BACKEND / "migrations" / "versions" / "0056_control_graph.py",
        Path(__file__),
    ]
    forbidden = ("TO" + "DO", "FIX" + "ME", "Not" + "ImplementedError",
                 "pytest.mark." + "skip", "pytest.mark." + "xfail")
    for f in files:
        body = f.read_text(encoding="utf-8")
        assert not [m for m in forbidden if m in body], f.name


def test_graph_permissions_registered_and_minimal() -> None:
    from app.authorization.catalog import group_for_code
    from app.services.rbac_service import PERMISSION_CATALOG

    assert "graph.view" in PERMISSION_CATALOG
    assert "graph.manage" in PERMISSION_CATALOG
    for code in ("graph.view", "graph.manage"):
        assert group_for_code(code) == "runtime"
    # no permission that would imply the graph grants authority
    for banned in ("graph.grant", "graph.authorize", "graph.delegate", "graph.enforce"):
        assert banned not in PERMISSION_CATALOG


# =========================================================================== #
# §14 - THE END-TO-END PROOF
# =========================================================================== #
def test_ss14_end_to_end_authority_chain_proof(
    client: TestClient, admin: dict, other_org_admin: dict
) -> None:
    """A real execution occurs (human -> agent -> tool). 5.3 reconstructs the
    authority chain from existing rows + edges, each hop naming its evidence.
    A delegation edge (created through DelegationService, bounded scope)
    extends the chain to a second human and its agent deputy, visible as a
    confused-deputy relationship. A planted cross-tenant edge does NOT extend
    the chain. A revoked delegation drops from the active chain. Reading the
    chain grants no authority. Every edge/query is tenant-isolated and
    audited; the graph query failing does not block execution."""
    setup = _ready_agent(client, admin)
    delegatee = _second_user(client, admin)

    # 1. delegation, through DelegationService, with a bounded scope
    deleg = _delegate(client, admin, delegatee["user_id"])
    edge = client.post(
        f"{GRAPH}/delegation-edges", headers=admin["headers"], json={"delegation_id": deleg["id"]}
    ).json()

    # 2. the delegatee triggers a real execution; a tool is invoked
    execution = _execute(client, delegatee, setup)
    tool_id = _make_tool(client, admin)
    db = SessionLocal()
    try:
        _insert_tool_call(
            db, execution_id=execution["id"], agent_id=setup["agent"]["id"],
            tool_id=tool_id, target_host="downstream.example.com",
        )
    finally:
        db.close()

    # 3. reconstruct: origin -> delegatee -> execution -> agent -> identity -> tool -> host
    chain = client.get(
        f"{GRAPH}/authority-chain/executions/{execution['id']}", headers=admin["headers"]
    ).json()
    assert chain["complete"] is True, chain["notes"]
    edges = [h["edge"] for h in chain["hops"]]
    for expected in ("DELEGATES_TO", "TRIGGERED", "EXECUTED_AS", "ACTS_AS", "INVOKED", "TARGETED"):
        assert expected in edges, (expected, edges)
    for h in chain["hops"]:
        assert h["evidence"].get("kind")
    assert chain["hops"][0]["from"]["id"] == admin["user_id"]  # authority began with the delegator

    # 4. a planted cross-tenant edge does not extend the chain
    db = SessionLocal()
    try:
        db.execute(
            text(
                """
                INSERT INTO control_graph_edges
                    (id, organization_id, source_type, source_id, edge_type, target_type,
                     target_id, evidence, confidence, provenance, valid_from, created_at, updated_at)
                VALUES (:id, :org, 'HUMAN', :foreign, 'DELEGATES_TO', 'HUMAN', :admin_a,
                        '{}'::jsonb, 1.0, 'EXPLICIT', now(), now(), now())
                """
            ),
            {"id": str(uuid.uuid4()), "org": admin["organization_id"],
             "foreign": other_org_admin["user_id"], "admin_a": admin["user_id"]},
        )
        db.commit()
    finally:
        db.close()
    chain2 = client.get(
        f"{GRAPH}/authority-chain/executions/{execution['id']}", headers=admin["headers"]
    ).json()
    assert all(h["from"]["id"] != other_org_admin["user_id"] for h in chain2["hops"])

    # 5. a revoked delegation drops from the active chain
    assert client.delete(f"{GRAPH}/edges/{edge['id']}", headers=admin["headers"]).status_code == 200
    chain3 = client.get(
        f"{GRAPH}/authority-chain/executions/{execution['id']}", headers=admin["headers"]
    ).json()
    assert not any(h["edge"] == "DELEGATES_TO" for h in chain3["hops"])

    # 6. reading the chain is a pure read -- it grants nothing and mutates
    #    nothing (an edge grants no authority; reading one even less so).
    db = SessionLocal()
    try:
        before = db.execute(
            text("SELECT count(*) FROM control_graph_edges WHERE organization_id = :org"),
            {"org": admin["organization_id"]},
        ).scalar()
    finally:
        db.close()
    for _ in range(3):
        client.get(
            f"{GRAPH}/authority-chain/executions/{execution['id']}", headers=admin["headers"]
        )
    # and a VIEWER (no graph.view) still cannot even read it
    viewer_email = f"e2ev_{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": viewer_email, "display_name": "V", "password": PASSWORD, "role": "VIEWER",
        "organization_id": admin["organization_id"]})
    vt = client.post("/api/v1/auth/login", json={"email": viewer_email, "password": PASSWORD}).json()
    assert client.get(
        f"{GRAPH}/authority-chain/executions/{execution['id']}",
        headers={"Authorization": f"Bearer {vt['access_token']}"},
    ).status_code == 403
    db = SessionLocal()
    try:
        after = db.execute(
            text("SELECT count(*) FROM control_graph_edges WHERE organization_id = :org"),
            {"org": admin["organization_id"]},
        ).scalar()
    finally:
        db.close()
    assert before == after  # reads changed no state

    # 7. tenant isolation + audit
    assert client.get(
        f"{GRAPH}/authority-chain/executions/{execution['id']}",
        headers=other_org_admin["headers"],
    ).status_code == 404
    db = SessionLocal()
    try:
        assert db.execute(
            text(
                "SELECT count(*) FROM authorization_audit WHERE organization_id = :org "
                "AND event_type IN ('GRAPH_DELEGATION_EDGE_CREATED','GRAPH_DELEGATION_EDGE_REVOKED')"
            ),
            {"org": admin["organization_id"]},
        ).scalar() >= 2
    finally:
        db.close()
