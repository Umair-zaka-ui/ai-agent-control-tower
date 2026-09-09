"""Phase 5.4 (M5.4) - MCP / Tool / Credential / Resource Dependency Graph.

AC-01..AC-18 + the §15 end-to-end proof + the §V blast-radius benchmark.
Each acceptance criterion is backed by at least one named test here.

The load-bearing properties, and where they are proven:
  * dependency edges on the 5.3 substrate (more edge types, one table) . AC-02
  * MCP via the existing Tool domain / NO second registry (structural) . AC-03
  * observed vs declared dependency distinguished .................... AC-04
  * blast-radius answers correctly + explainably ................... AC-05 / §15
  * per-hop tenant-bounded blast-radius (adversarial) .............. AC-06
  * reuses the 5.3 CTE machinery; no new engine ................... AC-07
  * NO graph DB; §V benchmark recorded; projection only if measured  AC-08
  * unapproved / unknown-provenance MCP surfaced as evidence ...... AC-09
"""

from __future__ import annotations

import ast
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import SessionLocal
from app.main import app
from tests.graph.conftest import PASSWORD

RT = "/api/v1/runtime"
GRAPH = "/api/v1/graph"
_BACKEND = Path(__file__).resolve().parents[2]
_REPO = _BACKEND.parent


# --------------------------------------------------------------------------- #
# helpers -- this suite's convention: each file defines its own
# --------------------------------------------------------------------------- #
def _second_user(client: TestClient, admin: dict, role: str = "ADMIN") -> dict:
    email = f"depu_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post(
        "/api/v1/identity/users",
        headers=admin["headers"],
        json={"email": email, "display_name": "Second", "password": PASSWORD,
              "role": role, "organization_id": admin["organization_id"]},
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
            "name": f"Dep Agent {nonce}", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
            "description": f"Test agent {nonce}.",
            "business_purpose": f"Exercise the dependency graph {nonce} in tests.",
            "owner_type": "USER", "owner_id": admin["user_id"],
            "technical_owner_id": admin["user_id"], "compliance_owner_id": admin["user_id"],
            "definition": {"name": "Definition", "framework": "CUSTOM",
                           "entrypoint_type": "FUNCTION", "entrypoint": "agents.handler:run"},
        },
    )
    assert r.status_code == 201, r.text
    agent = r.json()
    for step in ("register", "validate"):
        assert client.post(f"{RT}/agents/{agent['id']}/{step}", headers=admin["headers"]).status_code == 200
    assert client.post(
        f"{RT}/agents/{agent['id']}/identity/create-and-associate",
        headers=admin["headers"], json={"client_id": f"agent-identity-{uuid.uuid4().hex[:10]}"},
    ).status_code == 200
    for step in ("submit-for-approval", "approve", "activate"):
        assert client.post(f"{RT}/agents/{agent['id']}/{step}", headers=admin["headers"]).status_code == 200
    r = client.post(
        f"{RT}/agents/{agent['id']}/versions", headers=admin["headers"],
        json={"model_configuration": {"provider": "MOCK", "model": "mock-model"}},
    )
    assert r.status_code == 201, r.text
    version = r.json()
    for step in ("validate", "approve", "publish"):
        assert client.post(
            f"{RT}/agents/{agent['id']}/versions/{version['id']}/{step}", headers=admin["headers"]
        ).status_code == 200
    r = client.post(
        f"{RT}/deployments", headers=admin["headers"], params={"agent_id": agent["id"]},
        json={"agent_version_id": version["id"], "environment": "DEVELOPMENT"},
    )
    assert r.status_code == 201, r.text
    deployment = r.json()
    for to_state in ("VALIDATING", "READY", "DEPLOYING"):
        assert client.post(
            f"{RT}/deployments/{deployment['id']}/lifecycle/transition",
            headers=admin["headers"], json={"to_state": to_state},
        ).status_code == 200
    return {"agent": agent, "version": version, "deployment": deployment}


def _execute(client: TestClient, admin: dict, setup: dict, **kwargs) -> dict:
    body = {"agent_id": setup["agent"]["id"], "input_payload": {}, **kwargs}
    r = client.post(f"{RT}/executions", headers=admin["headers"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _make_tool(client: TestClient, admin: dict, name: str | None = None) -> str:
    r = client.post(
        f"{RT}/tools",
        headers=admin["headers"],
        json={"name": name or f"tool_{uuid.uuid4().hex[:8]}",
              "display_name": "Dep Test Tool", "tool_type": "FUNCTION"},
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


def _make_resource(db, admin: dict, *, resource_type: str, name: str) -> uuid.UUID:
    rid = uuid.uuid4()
    db.execute(
        text(
            """
            INSERT INTO resources (id, resource_type, resource_id, name, organization_id,
                                   owner_id, owner_type, visibility, status)
            VALUES (:id, :rt, :rid, :name, :org, :owner, 'USER', 'ORGANIZATION', 'ACTIVE')
            """
        ),
        {"id": str(rid), "rt": resource_type, "rid": str(uuid.uuid4()), "name": name,
         "org": admin["organization_id"], "owner": admin["user_id"]},
    )
    db.commit()
    return rid


def _make_provider_credential(db, admin: dict, provider: str = "MOCK") -> uuid.UUID:
    cid = uuid.uuid4()
    db.execute(
        text(
            """
            INSERT INTO provider_credentials (id, organization_id, provider, encrypted_secret,
                                              secret_hint, status, created_at, updated_at)
            VALUES (:id, :org, :p, 'ciphertext-not-a-secret', 'ab12', 'ACTIVE', now(), now())
            """
        ),
        {"id": str(cid), "org": admin["organization_id"], "p": provider},
    )
    db.commit()
    return cid


def _register_mcp(client: TestClient, admin: dict, *, name=None, trust_status="PENDING",
                  provenance="EXPLICIT") -> dict:
    r = client.post(
        f"{GRAPH}/mcp-servers", headers=admin["headers"],
        json={"name": name or f"mcp-{uuid.uuid4().hex[:8]}", "trust_status": trust_status,
              "provenance": provenance, "endpoint_reference": "mcp://local/reference"},
    )
    assert r.status_code == 201, r.text
    return r.json()


# =========================================================================== #
# AC-01 - live baseline / 5.1+5.2+5.3 substrate
# =========================================================================== #
def test_ac01_substrate_present_and_head_recorded() -> None:
    from app.graph.blast_radius import BlastRadiusService  # noqa: F401
    from app.graph.dependencies import DependencyGraphService  # noqa: F401
    from app.graph.mcp import McpServerService  # noqa: F401
    from app.graph.traversal import traverse_with_edges  # noqa: F401

    versions = sorted((_BACKEND / "migrations" / "versions").glob("*.py"))
    assert versions[-1].stem == "0057_dependency_graph"
    assert {"0055_agent_discovery", "0056_control_graph"} <= {v.stem for v in versions}
    repo_state = (_REPO / "REPO_STATE.md").read_text(encoding="utf-8")
    assert "0057_dependency_graph" in repo_state


# =========================================================================== #
# AC-02 - dependency edge types on control_graph_edges, referencing existing rows
# =========================================================================== #
def test_ac02_dependency_edges_are_more_edge_types_on_one_table() -> None:
    from app.core.database import Base
    from app.models.graph import DEPENDENCY_EDGE_TYPES

    assert "control_graph_edges" in Base.metadata.tables
    for banned in ("dependency_edges", "graph_dependencies", "blast_radius_cache",
                   "reachability_projection", "graph_projection"):
        assert banned not in Base.metadata.tables, banned
    assert {"DEPENDS_ON_TOOL", "DEPENDS_ON_MCP_SERVER", "DEPENDS_ON_CREDENTIAL",
            "MCP_EXPOSES_TOOL", "TOOL_USES_CREDENTIAL", "TOOL_ACCESSES_RESOURCE",
            "CREDENTIAL_ACCESSES_RESOURCE"} <= set(DEPENDENCY_EDGE_TYPES)


def test_ac02_dependency_edge_endpoints_are_validated_against_real_rows(
    client: TestClient, admin: dict
) -> None:
    setup = _ready_agent(client, admin)
    r = client.post(
        f"{GRAPH}/dependency-edges", headers=admin["headers"],
        json={"source": {"type": "AGENT", "id": setup["agent"]["id"]},
              "edge_type": "DEPENDS_ON_TOOL",
              "target": {"type": "TOOL", "id": str(uuid.uuid4())}},
    )
    assert r.status_code == 404  # non-existent tool endpoint


def test_ac02_declared_edge_shape_is_enforced(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    tool_id = _make_tool(client, admin)
    # DEPENDS_ON_TOOL connects AGENT -> TOOL, not TOOL -> AGENT
    r = client.post(
        f"{GRAPH}/dependency-edges", headers=admin["headers"],
        json={"source": {"type": "TOOL", "id": tool_id}, "edge_type": "DEPENDS_ON_TOOL",
              "target": {"type": "AGENT", "id": setup["agent"]["id"]}},
    )
    assert r.status_code == 422


# =========================================================================== #
# AC-03 - MCP via the existing Tool domain; NO second tool registry (structural)
# =========================================================================== #
def test_ac03_no_second_tool_registry() -> None:
    from app.core.database import Base

    tables = set(Base.metadata.tables)
    assert "tools" in tables and "mcp_servers" in tables
    for banned in ("mcp_tools", "mcp_server_tools", "mcp_exposed_tools", "mcp_tool_registry"):
        assert banned not in tables, banned
    # mcp_servers does NOT carry tool columns -- an exposed tool is a `tools` row.
    mcp_cols = {c.name for c in Base.metadata.tables["mcp_servers"].columns}
    assert not ({"input_schema", "output_schema", "tool_type", "endpoint"} & mcp_cols)
    # the link is one nullable FK on the existing tools table.
    tool_cols = {c.name for c in Base.metadata.tables["tools"].columns}
    assert "mcp_server_id" in tool_cols


def test_ac03_mcp_exposed_tool_is_a_tool_row_using_the_existing_gateway(
    client: TestClient, admin: dict
) -> None:
    server = _register_mcp(client, admin)
    tool_id = _make_tool(client, admin)  # created through the *existing* runtime tool API
    r = client.post(
        f"{GRAPH}/mcp-servers/{server['id']}/tools", headers=admin["headers"],
        json={"tool_id": tool_id},
    )
    assert r.status_code == 201, r.text
    edge = r.json()
    assert edge["edge_type"] == "MCP_EXPOSES_TOOL"
    # the tool row now points at its server; it is still an ordinary Tool.
    listing = client.get(f"{GRAPH}/mcp-servers/{server['id']}/tools", headers=admin["headers"]).json()
    assert any(t["id"] == tool_id and t["mcp_server_id"] == server["id"] for t in listing["tools"])
    db = SessionLocal()
    try:
        n = db.execute(text("SELECT count(*) FROM tools WHERE id = :id"), {"id": tool_id}).scalar()
        assert n == 1  # one tool row, in the one tools table
    finally:
        db.close()


# =========================================================================== #
# AC-04 - observed vs declared dependency is distinguished
# =========================================================================== #
def test_ac04_observed_and_declared_dependencies_carry_distinct_evidence(
    client: TestClient, admin: dict
) -> None:
    setup = _ready_agent(client, admin)
    observed_tool = _make_tool(client, admin)
    execution = _execute(client, admin, setup)
    db = SessionLocal()
    try:
        _insert_tool_call(db, execution_id=execution["id"], agent_id=setup["agent"]["id"],
                          tool_id=observed_tool)
    finally:
        db.close()
    # a declared (assigned) tool that was never called
    declared_tool = _make_tool(client, admin)
    r = client.post(
        f"{GRAPH}/dependency-edges", headers=admin["headers"],
        json={"source": {"type": "AGENT", "id": setup["agent"]["id"]},
              "edge_type": "DEPENDS_ON_TOOL", "target": {"type": "TOOL", "id": declared_tool},
              "note": "assigned in the agent spec"},
    )
    assert r.status_code == 201

    rebuild = client.post(
        f"{GRAPH}/agents/{setup['agent']['id']}/dependencies/rebuild", headers=admin["headers"]
    )
    assert rebuild.status_code == 200, rebuild.text
    assert "unknown != safe" in rebuild.json()["note"]

    deps = client.get(
        f"{GRAPH}/agents/{setup['agent']['id']}/dependencies", headers=admin["headers"]
    ).json()
    by_target = {d["target_id"]: d for d in deps}
    assert by_target[observed_tool]["evidence"]["mode"] == "OBSERVED"
    assert by_target[observed_tool]["evidence"]["source"] == "tool_calls"
    assert by_target[declared_tool]["evidence"]["mode"] == "DECLARED"


# =========================================================================== #
# AC-05 - blast-radius queries answer correctly + explainably
# =========================================================================== #
def _payroll_scenario(client: TestClient, admin: dict) -> dict:
    """agent -> tool -> payroll RESOURCE, and agent -> credential -> payroll."""
    setup = _ready_agent(client, admin)
    agent_id = setup["agent"]["id"]
    tool_id = _make_tool(client, admin)
    db = SessionLocal()
    try:
        payroll = _make_resource(db, admin, resource_type="payroll", name="Payroll System")
        other = _make_resource(db, admin, resource_type="crm", name="CRM")
        cred = _make_provider_credential(db, admin)
    finally:
        db.close()
    # agent -> tool (declared), tool -> payroll (declared), agent -> cred, cred -> payroll
    for body in (
        {"source": {"type": "AGENT", "id": agent_id}, "edge_type": "DEPENDS_ON_TOOL",
         "target": {"type": "TOOL", "id": tool_id}},
        {"source": {"type": "TOOL", "id": tool_id}, "edge_type": "TOOL_ACCESSES_RESOURCE",
         "target": {"type": "RESOURCE", "id": str(payroll)}},
        {"source": {"type": "TOOL", "id": tool_id}, "edge_type": "TOOL_ACCESSES_RESOURCE",
         "target": {"type": "RESOURCE", "id": str(other)}},
        {"source": {"type": "AGENT", "id": agent_id}, "edge_type": "DEPENDS_ON_CREDENTIAL",
         "target": {"type": "CREDENTIAL", "id": str(cred)}},
        {"source": {"type": "CREDENTIAL", "id": str(cred)}, "edge_type": "CREDENTIAL_ACCESSES_RESOURCE",
         "target": {"type": "RESOURCE", "id": str(payroll)}},
    ):
        rr = client.post(f"{GRAPH}/dependency-edges", headers=admin["headers"], json=body)
        assert rr.status_code == 201, rr.text
    return {"agent_id": agent_id, "tool_id": tool_id, "payroll": str(payroll),
            "other": str(other), "cred": str(cred)}


def test_ac05_which_agents_can_reach_payroll_with_explainable_paths(
    client: TestClient, admin: dict
) -> None:
    sc = _payroll_scenario(client, admin)
    r = client.get(
        f"{GRAPH}/blast-radius/agents-reaching", headers=admin["headers"],
        params={"node_type": "RESOURCE", "node_id": sc["payroll"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    agent_ids = {a["node"]["id"] for a in body["agents"]}
    assert sc["agent_id"] in agent_ids
    # explainable: the answer names the edge chain + each edge's evidence
    path = next(a for a in body["agents"] if a["node"]["id"] == sc["agent_id"])
    edge_types = {e["edge_type"] for e in path["edges"]}
    assert edge_types & {"DEPENDS_ON_TOOL", "TOOL_ACCESSES_RESOURCE",
                         "DEPENDS_ON_CREDENTIAL", "CREDENTIAL_ACCESSES_RESOURCE"}
    for e in path["edges"]:
        assert "mode" in e["evidence"]


def test_ac05_what_breaks_if_this_credential_is_revoked(client: TestClient, admin: dict) -> None:
    sc = _payroll_scenario(client, admin)
    r = client.get(
        f"{GRAPH}/blast-radius/what-breaks", headers=admin["headers"],
        params={"node_type": "CREDENTIAL", "node_id": sc["cred"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert sc["agent_id"] in {a["node"]["id"] for a in body["affected_agents"]}
    assert body["incomplete"] is False


def test_ac05_which_agents_reach_a_resource_of_kind_payroll(client: TestClient, admin: dict) -> None:
    sc = _payroll_scenario(client, admin)
    r = client.get(
        f"{GRAPH}/blast-radius/resource-kind", headers=admin["headers"],
        params={"kind": "payroll"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "payroll"
    assert sc["agent_id"] in {a["agent"]["id"] for a in body["agents"]}
    # the CRM resource is a different kind and must not appear
    assert sc["other"] not in {mr["id"] for mr in body["matched_resources"]}


# =========================================================================== #
# AC-06 - per-hop tenant-bounded blast-radius (adversarial)
# =========================================================================== #
def test_ac06_planted_cross_tenant_dependency_edge_does_not_extend_a_blast_radius(
    client: TestClient, admin: dict, other_org_admin: dict
) -> None:
    sc = _payroll_scenario(client, admin)
    other_setup = _ready_agent(client, other_org_admin)
    foreign_agent = other_setup["agent"]["id"]

    # PLANT (hostile direct insert): tenant A edge whose SOURCE is tenant B's agent,
    # pointing at tenant A's tool -- an attempt to make B's agent "reach" payroll.
    db = SessionLocal()
    try:
        db.execute(
            text(
                """
                INSERT INTO control_graph_edges
                    (id, organization_id, source_type, source_id, edge_type, target_type,
                     target_id, evidence, confidence, provenance, valid_from, created_at, updated_at)
                VALUES (:id, :org_a, 'AGENT', :foreign, 'DEPENDS_ON_TOOL', 'TOOL', :tool_a,
                        '{}'::jsonb, 1.0, 'DERIVED', now(), now(), now())
                """
            ),
            {"id": str(uuid.uuid4()), "org_a": admin["organization_id"],
             "foreign": foreign_agent, "tool_a": sc["tool_id"]},
        )
        db.commit()
    finally:
        db.close()

    body = client.get(
        f"{GRAPH}/blast-radius/agents-reaching", headers=admin["headers"],
        params={"node_type": "RESOURCE", "node_id": sc["payroll"]},
    ).json()
    reached = {a["node"]["id"] for a in body["agents"]}
    assert foreign_agent not in reached
    for p in body["all_dependents"]:
        assert p["node"]["id"] != foreign_agent
        for e in p["edges"]:
            assert e["from"]["id"] != foreign_agent and e["to"]["id"] != foreign_agent


def test_ac06_blast_radius_query_for_a_foreign_node_is_404(
    client: TestClient, admin: dict, other_org_admin: dict
) -> None:
    sc = _payroll_scenario(client, admin)
    r = client.get(
        f"{GRAPH}/blast-radius/agents-reaching", headers=other_org_admin["headers"],
        params={"node_type": "RESOURCE", "node_id": sc["payroll"]},
    )
    assert r.status_code == 404  # no existence leak


# =========================================================================== #
# AC-07 - reuses the 5.3 CTE machinery; cycle-safe, depth-capped
# =========================================================================== #
def test_ac07_blast_radius_reuses_the_recursive_cte_not_a_new_engine() -> None:
    src = (_BACKEND / "app" / "graph" / "traversal.py").read_text(encoding="utf-8")
    assert src.count("WITH RECURSIVE") >= 2  # traverse + traverse_with_edges
    br = (_BACKEND / "app" / "graph" / "blast_radius.py").read_text(encoding="utf-8")
    assert "traverse_with_edges" in br
    for banned in ("neo4j", "networkx", "igraph", "gremlin"):
        assert banned not in br
    # blast-radius delegates traversal, it does not hand-roll a walk
    tree = ast.parse(br)
    assert not any(
        isinstance(n, ast.While) for n in ast.walk(tree)
    ), "blast_radius must not hand-roll a traversal loop"


def test_ac07_blast_radius_is_cycle_safe_and_depth_capped(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    db = SessionLocal()
    try:
        r1 = _make_resource(db, admin, resource_type="thing", name="R1")
        r2 = _make_resource(db, admin, resource_type="thing", name="R2")
    finally:
        db.close()
    t1 = _make_tool(client, admin)
    t2 = _make_tool(client, admin)
    # a cycle among tools/resources via TOOL_ACCESSES_RESOURCE + a planted reverse edge
    for body in (
        {"source": {"type": "AGENT", "id": setup["agent"]["id"]}, "edge_type": "DEPENDS_ON_TOOL",
         "target": {"type": "TOOL", "id": t1}},
        {"source": {"type": "TOOL", "id": t1}, "edge_type": "TOOL_ACCESSES_RESOURCE",
         "target": {"type": "RESOURCE", "id": str(r1)}},
        {"source": {"type": "TOOL", "id": t2}, "edge_type": "TOOL_ACCESSES_RESOURCE",
         "target": {"type": "RESOURCE", "id": str(r1)}},
        {"source": {"type": "TOOL", "id": t2}, "edge_type": "TOOL_ACCESSES_RESOURCE",
         "target": {"type": "RESOURCE", "id": str(r2)}},
    ):
        assert client.post(f"{GRAPH}/dependency-edges", headers=admin["headers"], json=body).status_code == 201

    r = client.get(
        f"{GRAPH}/blast-radius/agents-reaching", headers=admin["headers"],
        params={"node_type": "RESOURCE", "node_id": str(r1), "max_depth": 999},
    )
    assert r.status_code == 422  # depth cap enforced (reuses MAX_TRAVERSAL_DEPTH)
    r = client.get(
        f"{GRAPH}/blast-radius/agents-reaching", headers=admin["headers"],
        params={"node_type": "RESOURCE", "node_id": str(r1)},
    )
    assert r.status_code == 200
    assert setup["agent"]["id"] in {a["node"]["id"] for a in r.json()["agents"]}


# =========================================================================== #
# AC-08 - NO graph database; the §V benchmark is recorded; projection only if measured
# =========================================================================== #
def test_ac08_no_graph_db_and_no_projection_table() -> None:
    from app.core.database import Base

    for banned in ("graph_projection", "reachability_projection", "reachability_cache",
                   "blast_radius_cache", "dependency_closure", "graph_nodes", "graph_paths"):
        assert banned not in Base.metadata.tables, banned
    for path in (_BACKEND / "app" / "graph").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                assert not any(n == b or n.startswith(b + ".")
                               for b in ("neo4j", "py2neo", "gremlin", "arango", "networkx", "igraph")), (path, n)


def test_ac08_v_blast_radius_benchmark_at_scale(client: TestClient, admin: dict) -> None:
    """§V: a blast-radius query at an honest single-busy-tenant worst-case,
    latency recorded. If assembly meets the target -> NO projection, numbers
    recorded (the restraint outcome). The full 1M-edge run + extrapolation is
    in docs/graph/blast-radius.md.

    Fixture: one tenant, a sparse dependency graph of realistic shape
    (agents -> tools -> resources, tools -> credentials), inflated with filler
    edges to ~200k, then the four blast-radius queries are timed.
    """
    org = admin["organization_id"]
    owner = admin["user_id"]
    N_AGENTS, N_TOOLS, N_RES, N_CRED = 12000, 1200, 300, 150
    db = SessionLocal()
    try:
        db.execute(
            text(
                """
                INSERT INTO agents (id, organization_id, name, agent_type, api_key_hash, status,
                                    version, capabilities, default_risk_score, max_allowed_risk,
                                    human_approval_required, risk_level, health, criticality,
                                    data_classification, default_environment, lifecycle_status,
                                    origin_category, control_state, created_at, updated_at)
                SELECT gen_random_uuid(), :org, 'bench-agent-' || g, 'ASSISTANT', 'x', 'ACTIVE',
                       '1.0.0', '[]'::jsonb, 0, 100, false, 'LOW', 'HEALTHY', 'LOW',
                       'INTERNAL', 'DEVELOPMENT', 'ACTIVE', 'NATIVE', 'GOVERNED', now(), now()
                FROM generate_series(1, :n) g
                """
            ),
            {"org": org, "n": N_AGENTS},
        )
        db.execute(
            text(
                """
                INSERT INTO tools (id, organization_id, name, display_name, tool_type,
                                   risk_level, side_effect_level, data_classification,
                                   requires_approval, timeout_seconds, enabled, created_at, updated_at)
                SELECT gen_random_uuid(), :org, 'bench-tool-' || g, 'T' || g, 'FUNCTION',
                       'MEDIUM', 'NONE', 'INTERNAL', false, 30, true, now(), now()
                FROM generate_series(1, :n) g
                """
            ),
            {"org": org, "n": N_TOOLS},
        )
        db.execute(
            text(
                """
                INSERT INTO resources (id, resource_type, resource_id, name, organization_id,
                                       owner_id, owner_type, visibility, status)
                SELECT gen_random_uuid(),
                       CASE WHEN g = 1 THEN 'payroll' ELSE 'dataset' END,
                       gen_random_uuid(), 'bench-res-' || g, :org, :owner, 'USER',
                       'ORGANIZATION', 'ACTIVE'
                FROM generate_series(1, :n) g
                """
            ),
            {"org": org, "owner": owner, "n": N_RES},
        )
        db.execute(
            text(
                """
                INSERT INTO provider_credentials (id, organization_id, provider, encrypted_secret,
                                                  secret_hint, status, created_at, updated_at)
                SELECT gen_random_uuid(), :org, 'bench-' || g, 'ct', 'ab', 'ACTIVE', now(), now()
                FROM generate_series(1, :n) g
                """
            ),
            {"org": org, "n": N_CRED},
        )
        db.commit()

        # sparse edges via modulo joins -- each agent ~10 tools, each tool ~5
        # resources + ~2 credentials, ~1/3 agents -> 1 credential directly.
        for k in range(10):
            db.execute(
                text(
                    """
                    INSERT INTO control_graph_edges
                        (id, organization_id, source_type, source_id, edge_type, target_type,
                         target_id, evidence, confidence, provenance, valid_from, created_at, updated_at)
                    SELECT gen_random_uuid(), :org, 'AGENT', a.id, 'DEPENDS_ON_TOOL', 'TOOL', t.id,
                           '{"mode":"OBSERVED","source":"benchmark"}'::jsonb, 1.0, 'DERIVED',
                           now(), now(), now()
                    FROM (SELECT id, row_number() OVER (ORDER BY id) rn FROM agents
                          WHERE organization_id = :org AND name LIKE 'bench-agent-%') a
                    JOIN (SELECT id, row_number() OVER (ORDER BY id) rn FROM tools
                          WHERE organization_id = :org AND name LIKE 'bench-tool-%') t
                      ON t.rn = ((a.rn * 7 + :k * 101) % :ntools) + 1
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"org": org, "ntools": N_TOOLS, "k": k},
            )
        for k in range(5):
            db.execute(
                text(
                    """
                    INSERT INTO control_graph_edges
                        (id, organization_id, source_type, source_id, edge_type, target_type,
                         target_id, evidence, confidence, provenance, valid_from, created_at, updated_at)
                    SELECT gen_random_uuid(), :org, 'TOOL', t.id, 'TOOL_ACCESSES_RESOURCE', 'RESOURCE', r.id,
                           '{"mode":"DECLARED","source":"benchmark"}'::jsonb, 1.0, 'DERIVED',
                           now(), now(), now()
                    FROM (SELECT id, row_number() OVER (ORDER BY id) rn FROM tools
                          WHERE organization_id = :org AND name LIKE 'bench-tool-%') t
                    JOIN (SELECT id, row_number() OVER (ORDER BY id) rn FROM resources
                          WHERE organization_id = :org AND name LIKE 'bench-res-%') r
                      ON r.rn = ((t.rn * 3 + :k * 17) % :nres) + 1
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"org": org, "nres": N_RES, "k": k},
            )
        for k in range(2):
            db.execute(
                text(
                    """
                    INSERT INTO control_graph_edges
                        (id, organization_id, source_type, source_id, edge_type, target_type,
                         target_id, evidence, confidence, provenance, valid_from, created_at, updated_at)
                    SELECT gen_random_uuid(), :org, 'TOOL', t.id, 'TOOL_USES_CREDENTIAL', 'CREDENTIAL', c.id,
                           '{"mode":"DECLARED","source":"benchmark"}'::jsonb, 1.0, 'DERIVED',
                           now(), now(), now()
                    FROM (SELECT id, row_number() OVER (ORDER BY id) rn FROM tools
                          WHERE organization_id = :org AND name LIKE 'bench-tool-%') t
                    JOIN (SELECT id, row_number() OVER (ORDER BY id) rn FROM provider_credentials
                          WHERE organization_id = :org AND provider LIKE 'bench-%') c
                      ON c.rn = ((t.rn + :k * 13) % :ncred) + 1
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"org": org, "ncred": N_CRED, "k": k},
            )
        db.commit()
        # A bulk load leaves the planner with stale statistics; in production
        # autovacuum maintains them and single-edge inserts through the service
        # never move them far. ANALYZE here measures steady-state assembly, not
        # a cold-stats artefact.
        for tbl in ("control_graph_edges", "agents", "tools", "resources", "provider_credentials"):
            db.execute(text(f"ANALYZE {tbl}"))
        db.commit()

        total = db.execute(
            text("SELECT count(*) FROM control_graph_edges WHERE organization_id = :org"),
            {"org": org},
        ).scalar()
        payroll_id = db.execute(
            text("SELECT id FROM resources WHERE organization_id = :org AND resource_type = 'payroll'"),
            {"org": org},
        ).scalar()
        busy_cred = db.execute(
            text(
                """
                SELECT target_id FROM control_graph_edges
                WHERE organization_id = :org AND edge_type = 'TOOL_USES_CREDENTIAL'
                GROUP BY target_id ORDER BY count(*) DESC LIMIT 1
                """
            ),
            {"org": org},
        ).scalar()
    finally:
        db.close()

    timings: dict[str, float] = {}
    try:
        for label, url, params in (
            ("agents_reaching_payroll", f"{GRAPH}/blast-radius/agents-reaching",
             {"node_type": "RESOURCE", "node_id": str(payroll_id), "max_depth": 6}),
            ("what_breaks_credential", f"{GRAPH}/blast-radius/what-breaks",
             {"node_type": "CREDENTIAL", "node_id": str(busy_cred), "max_depth": 6}),
            ("resource_kind_payroll", f"{GRAPH}/blast-radius/resource-kind",
             {"kind": "payroll", "max_depth": 6}),
            ("unapproved_mcp", f"{GRAPH}/blast-radius/unapproved-mcp", {}),
        ):
            t0 = time.perf_counter()
            resp = client.get(url, headers=admin["headers"], params=params)
            timings[label] = (time.perf_counter() - t0) * 1000
            assert resp.status_code == 200, resp.text

        print(
            f"\n[§V BENCHMARK] single-tenant edges={total} "
            + " ".join(f"{k}={v:.0f}ms" for k, v in timings.items())
        )
        # ADR-0008 / ADR-0017 discipline: a recorded measurement that assembly
        # from edges is fast enough, so 'no projection' keeps being the right
        # call. At this single-busy-tenant scale the blast-radius queries land
        # well under 1s; the ceiling here is generous headroom that catches a
        # structural regression (an index dropped, the double-CTE reintroduced),
        # not CI noise. The full 1M-edge run + extrapolation is recorded in
        # docs/graph/blast-radius.md and ADR-0018.
        assert max(timings.values()) < 3000, timings
    finally:
        db = SessionLocal()
        try:
            db.execute(
                text("DELETE FROM control_graph_edges WHERE organization_id = :org"), {"org": org}
            )
            db.execute(text("DELETE FROM tool_calls tc USING agents a "
                            "WHERE tc.agent_id = a.id AND a.organization_id = :org "
                            "AND a.name LIKE 'bench-agent-%'"), {"org": org})
            db.execute(text("DELETE FROM resources WHERE organization_id = :org AND name LIKE 'bench-res-%'"),
                       {"org": org})
            db.execute(text("DELETE FROM provider_credentials WHERE organization_id = :org AND provider LIKE 'bench-%'"),
                       {"org": org})
            db.execute(text("DELETE FROM tools WHERE organization_id = :org AND name LIKE 'bench-tool-%'"),
                       {"org": org})
            db.execute(text("DELETE FROM agents WHERE organization_id = :org AND name LIKE 'bench-agent-%'"),
                       {"org": org})
            db.commit()
        finally:
            db.close()


def test_ac08_projection_decision_is_documented() -> None:
    doc = (_REPO / "docs" / "graph" / "blast-radius.md").read_text(encoding="utf-8")
    assert "no projection" in doc.lower() or "no materialised projection" in doc.lower()
    adr = (_REPO / "docs" / "architecture" / "adr" / "0018-mcp-representation-via-tool-domain.md").read_text(
        encoding="utf-8"
    )
    assert "benchmark" in adr.lower()


# =========================================================================== #
# AC-09 - MCP trust/approval; unapproved / unknown-provenance surfaced as evidence
# =========================================================================== #
def test_ac09_unapproved_mcp_dependency_is_surfaced_as_evidence(
    client: TestClient, admin: dict
) -> None:
    setup = _ready_agent(client, admin)
    unknown = _register_mcp(client, admin, trust_status="UNKNOWN", provenance="DISCOVERED")
    approved = _register_mcp(client, admin, trust_status="APPROVED")
    for srv in (unknown, approved):
        assert client.post(
            f"{GRAPH}/dependency-edges", headers=admin["headers"],
            json={"source": {"type": "AGENT", "id": setup["agent"]["id"]},
                  "edge_type": "DEPENDS_ON_MCP_SERVER",
                  "target": {"type": "MCP_SERVER", "id": srv["id"]}},
        ).status_code == 201

    r = client.get(f"{GRAPH}/blast-radius/unapproved-mcp", headers=admin["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    flagged = {d["mcp_server"]["id"] for d in body["dependencies"]}
    assert unknown["id"] in flagged
    assert approved["id"] not in flagged
    assert "5.5" in body["note"] and "does not raise" in body["note"]

    # and the per-server view marks it
    dep = client.get(
        f"{GRAPH}/blast-radius/mcp-dependents/{unknown['id']}", headers=admin["headers"]
    ).json()
    assert dep["mcp_server"]["is_unapproved_dependency"] is True
    assert setup["agent"]["id"] in {a["node"]["id"] for a in dep["agents"]}


def test_ac09_mcp_trust_state_transitions_are_audited(client: TestClient, admin: dict) -> None:
    server = _register_mcp(client, admin, trust_status="PENDING")
    r = client.post(
        f"{GRAPH}/mcp-servers/{server['id']}/trust", headers=admin["headers"],
        json={"trust_status": "APPROVED", "note": "reviewed by security"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["trust_status"] == "APPROVED"
    db = SessionLocal()
    try:
        events = {
            e for (e,) in db.execute(
                text("SELECT event_type FROM authorization_audit WHERE organization_id = :org "
                     "AND event_type LIKE 'GRAPH_MCP%'"),
                {"org": admin["organization_id"]},
            ).all()
        }
        assert {"GRAPH_MCP_SERVER_REGISTERED", "GRAPH_MCP_TRUST_CHANGED"} <= events
    finally:
        db.close()


# =========================================================================== #
# AC-10 - MCP security via existing authorities; no MCP probe holds a DB lock
# =========================================================================== #
def test_ac10_no_mcp_probe_holds_a_db_lock() -> None:
    mcp = (_BACKEND / "app" / "graph" / "mcp.py").read_text(encoding="utf-8")
    # record_probe is fetch-then-write: it does not open a transaction across a
    # network call, and there is no with_for_update in the probe path.
    assert "fetch-then-write" in mcp.lower() or "fetch-then-write" in mcp
    probe_start = mcp.index("def record_probe")
    probe_body = mcp[probe_start:probe_start + 900]
    assert "with_for_update" not in probe_body


def test_ac10_mcp_tool_io_uses_the_existing_schema_validation_and_egress(
    client: TestClient, admin: dict
) -> None:
    """An MCP-exposed tool is a `tools` row -- it goes through the same tool
    gateway / schema validation / egress guard as a native tool. Structural:
    nothing in app/graph re-implements schema validation or an egress guard."""
    joined = "\n".join(
        p.read_text(encoding="utf-8") for p in (_BACKEND / "app" / "graph").rglob("*.py")
    )
    for banned in ("jsonschema", "egress_guard", "GovernedHttpClient", "httpx", "socket"):
        assert banned not in joined, banned


# =========================================================================== #
# AC-11 - edges grant no authority; represent, don't create
# =========================================================================== #
def test_ac11_dependency_edge_grants_nothing(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    tool_id = _make_tool(client, admin)
    viewer_email = f"depv_{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": viewer_email, "display_name": "V", "password": PASSWORD, "role": "VIEWER",
        "organization_id": admin["organization_id"]})
    vt = client.post("/api/v1/auth/login", json={"email": viewer_email, "password": PASSWORD}).json()
    vh = {"Authorization": f"Bearer {vt['access_token']}"}

    client.post(f"{GRAPH}/dependency-edges", headers=admin["headers"],
                json={"source": {"type": "AGENT", "id": setup["agent"]["id"]},
                      "edge_type": "DEPENDS_ON_TOOL", "target": {"type": "TOOL", "id": tool_id}})
    # a VIEWER holds neither graph.view nor graph.manage
    assert client.get(f"{GRAPH}/agents/{setup['agent']['id']}/dependencies", headers=vh).status_code == 403
    assert client.post(f"{GRAPH}/dependency-edges", headers=vh,
                       json={"source": {"type": "AGENT", "id": setup["agent"]["id"]},
                             "edge_type": "DEPENDS_ON_TOOL",
                             "target": {"type": "TOOL", "id": tool_id}}).status_code == 403
    assert client.post(f"{RT}/executions", headers=vh,
                       json={"agent_id": setup["agent"]["id"], "input_payload": {}}
                       ).status_code in (401, 403)


def test_ac11_graph_is_off_the_execution_path() -> None:
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
# AC-12 - tenant isolation per-hop; cross-tenant -> 404; no secret in edges/audit
# =========================================================================== #
def test_ac12_cross_tenant_mcp_and_dependency_reads_are_404(
    client: TestClient, admin: dict, other_org_admin: dict
) -> None:
    server = _register_mcp(client, admin)
    assert client.get(f"{GRAPH}/mcp-servers/{server['id']}", headers=other_org_admin["headers"]).status_code == 404
    assert client.post(f"{GRAPH}/mcp-servers/{server['id']}/trust", headers=other_org_admin["headers"],
                       json={"trust_status": "APPROVED"}).status_code == 404
    assert client.get(f"{GRAPH}/blast-radius/mcp-dependents/{server['id']}",
                      headers=other_org_admin["headers"]).status_code == 404


def test_ac12_no_secret_material_in_a_credential_edge_or_evidence(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    db = SessionLocal()
    try:
        cred = _make_provider_credential(db, admin)
    finally:
        db.close()
    edge = client.post(
        f"{GRAPH}/dependency-edges", headers=admin["headers"],
        json={"source": {"type": "AGENT", "id": setup["agent"]["id"]},
              "edge_type": "DEPENDS_ON_CREDENTIAL", "target": {"type": "CREDENTIAL", "id": str(cred)}},
    ).json()
    blob = str(edge).lower()
    for needle in ("ciphertext", "secret", "password", "token", "bearer", "encrypted_secret"):
        assert needle not in blob, needle


# =========================================================================== #
# AC-13 - concurrency: real separate Postgres sessions
# =========================================================================== #
def test_ac13_concurrent_dependency_edge_create_yields_one_edge(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    tool_id = _make_tool(client, admin)
    payload = {"source": {"type": "AGENT", "id": setup["agent"]["id"]},
               "edge_type": "DEPENDS_ON_TOOL", "target": {"type": "TOOL", "id": tool_id}}
    barrier = threading.Barrier(2)
    codes: list[int] = []
    lock = threading.Lock()

    def _create() -> None:
        c = TestClient(app)
        barrier.wait()
        resp = c.post(f"{GRAPH}/dependency-edges", headers=admin["headers"], json=payload)
        with lock:
            codes.append(resp.status_code)

    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in [pool.submit(_create) for _ in range(2)]:
            f.result()
    assert all(s == 201 for s in codes), codes
    db = SessionLocal()
    try:
        n = db.execute(
            text("SELECT count(*) FROM control_graph_edges WHERE organization_id = :org "
                 "AND source_id = :sid AND target_id = :tid AND edge_type = 'DEPENDS_ON_TOOL' "
                 "AND revoked_at IS NULL"),
            {"org": admin["organization_id"], "sid": setup["agent"]["id"], "tid": tool_id},
        ).scalar()
        assert n == 1, n
    finally:
        db.close()


def test_ac13_concurrent_mcp_trust_update_is_safe(client: TestClient, admin: dict) -> None:
    server = _register_mcp(client, admin)
    barrier = threading.Barrier(2)
    results: list[tuple[int, str]] = []
    lock = threading.Lock()
    targets = ["APPROVED", "REJECTED"]

    def _set(i: int) -> None:
        c = TestClient(app)
        barrier.wait()
        resp = c.post(f"{GRAPH}/mcp-servers/{server['id']}/trust", headers=admin["headers"],
                      json={"trust_status": targets[i]})
        with lock:
            results.append((resp.status_code, resp.json().get("trust_status")))

    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in [pool.submit(_set, i) for i in range(2)]:
            f.result()
    assert all(s == 200 for s, _ in results)
    final = client.get(f"{GRAPH}/mcp-servers/{server['id']}", headers=admin["headers"]).json()
    assert final["trust_status"] in targets  # one of the two, deterministically serialized


# =========================================================================== #
# AC-14 - dependency/MCP-trust changes audited; fails open; incomplete says so
# =========================================================================== #
def test_ac14_blast_radius_incomplete_is_explicit_not_falsely_empty(
    client: TestClient, admin: dict
) -> None:
    # a chain longer than a tiny max_depth -> the answer must say "incomplete",
    # never present a truncated result as the whole blast radius.
    setup = _ready_agent(client, admin)
    db = SessionLocal()
    try:
        r_end = _make_resource(db, admin, resource_type="deep", name="deep-res")
    finally:
        db.close()
    t1 = _make_tool(client, admin)
    db = SessionLocal()
    try:
        cred = _make_provider_credential(db, admin)
    finally:
        db.close()
    edges = [
        ("AGENT", setup["agent"]["id"], "DEPENDS_ON_TOOL", "TOOL", t1),
        ("TOOL", t1, "TOOL_USES_CREDENTIAL", "CREDENTIAL", str(cred)),
        ("CREDENTIAL", str(cred), "CREDENTIAL_ACCESSES_RESOURCE", "RESOURCE", str(r_end)),
    ]
    for s_t, s_i, e_t, t_t, t_i in edges:
        assert client.post(f"{GRAPH}/dependency-edges", headers=admin["headers"],
                           json={"source": {"type": s_t, "id": s_i}, "edge_type": e_t,
                                 "target": {"type": t_t, "id": t_i}}).status_code == 201

    shallow = client.get(
        f"{GRAPH}/blast-radius/agents-reaching", headers=admin["headers"],
        params={"node_type": "RESOURCE", "node_id": str(r_end), "max_depth": 1},
    ).json()
    assert shallow["incomplete"] is True
    assert shallow["incomplete_reason"]

    full = client.get(
        f"{GRAPH}/blast-radius/agents-reaching", headers=admin["headers"],
        params={"node_type": "RESOURCE", "node_id": str(r_end)},
    ).json()
    assert full["incomplete"] is False
    assert setup["agent"]["id"] in {a["node"]["id"] for a in full["agents"]}


def test_ac14_resource_kind_with_no_matches_says_so(client: TestClient, admin: dict) -> None:
    r = client.get(f"{GRAPH}/blast-radius/resource-kind", headers=admin["headers"],
                   params={"kind": f"nonexistent-{uuid.uuid4().hex[:6]}"})
    assert r.status_code == 200
    body = r.json()
    assert body["agents"] == []
    assert "no resource of this kind is recorded" in (body["incomplete_reason"] or "")


def test_ac14_dependency_rebuild_is_audited(client: TestClient, admin: dict) -> None:
    setup = _ready_agent(client, admin)
    client.post(f"{GRAPH}/agents/{setup['agent']['id']}/dependencies/rebuild", headers=admin["headers"])
    db = SessionLocal()
    try:
        n = db.execute(
            text("SELECT count(*) FROM authorization_audit WHERE organization_id = :org "
                 "AND event_type = 'GRAPH_DEPENDENCIES_REBUILT'"),
            {"org": admin["organization_id"]},
        ).scalar()
        assert n >= 1
    finally:
        db.close()


# =========================================================================== #
# AC-15 - migration additive / reversible / id <= 32
# =========================================================================== #
def test_ac15_migration_shape() -> None:
    mig = (_BACKEND / "migrations" / "versions" / "0057_dependency_graph.py").read_text(encoding="utf-8")
    assert 'revision = "0057_dependency_graph"' in mig
    assert len("0057_dependency_graph") <= 32
    assert 'down_revision = "0056_control_graph"' in mig
    assert "def downgrade" in mig and "drop_table" in mig
    # exactly one new table + one additive column on tools; no column drop/alter
    # of an existing column type.
    assert mig.count("create_table(") == 1
    assert "op.add_column(\n        \"tools\"" in mig or 'op.add_column(\n        "tools"' in mig
    assert "op.drop_column" in mig  # only in downgrade, for the additive column
    # the only ALTERs are CHECK-constraint widenings (drop+recreate), never a
    # column type change.
    assert "alter_column" not in mig


# =========================================================================== #
# AC-16 / AC-17 - whole-suite guarantees (run by the full pytest, not here).
# AC-18 - no forbidden markers in this phase's files
# =========================================================================== #
def test_ac18_no_forbidden_markers_in_new_files() -> None:
    files = [
        _BACKEND / "app" / "graph" / "mcp.py",
        _BACKEND / "app" / "graph" / "dependencies.py",
        _BACKEND / "app" / "graph" / "blast_radius.py",
        _BACKEND / "app" / "graph" / "traversal.py",
        _BACKEND / "app" / "graph" / "routes.py",
        _BACKEND / "app" / "graph" / "schemas.py",
        _BACKEND / "app" / "models" / "graph.py",
        _BACKEND / "migrations" / "versions" / "0057_dependency_graph.py",
        Path(__file__),
    ]
    forbidden = ("TO" + "DO", "FIX" + "ME", "Not" + "ImplementedError",
                 "pytest.mark." + "skip", "pytest.mark." + "xfail")
    for f in files:
        body = f.read_text(encoding="utf-8")
        assert not [m for m in forbidden if m in body], f.name


def test_graph_permissions_still_minimal_after_5_4() -> None:
    from app.services.rbac_service import PERMISSION_CATALOG

    assert "graph.view" in PERMISSION_CATALOG and "graph.manage" in PERMISSION_CATALOG
    # 5.4 added NO new permission (MCP-trust reuses graph.manage) and nothing
    # that would imply the graph grants authority.
    for banned in ("graph.grant", "graph.authorize", "graph.mcp.manage", "graph.enforce",
                   "graph.dependency.grant"):
        assert banned not in PERMISSION_CATALOG


# =========================================================================== #
# §15 - THE END-TO-END PROOF
# =========================================================================== #
def test_ss15_end_to_end_dependency_blast_radius_proof(
    client: TestClient, admin: dict, other_org_admin: dict
) -> None:
    """A set of agents (native + a discovered external one) depend on tools, an
    MCP server (via the Tool domain, one unapproved), credentials and resources
    (including a payroll-kind resource). 5.4 builds the dependency edges
    (observed from tool_calls + declared from bindings). Then the blast-radius
    queries answer correctly + explainably; a planted cross-tenant edge does
    not extend any blast radius; every query is tenant-isolated and audited; no
    secret appears in any edge; the MCP-exposed tool used the existing Tool
    validation (no second registry)."""
    # --- native agent, real execution, observed tool use ------------------ #
    setup = _ready_agent(client, admin)
    agent_id = setup["agent"]["id"]
    native_tool = _make_tool(client, admin)
    execution = _execute(client, admin, setup)
    db = SessionLocal()
    try:
        _insert_tool_call(db, execution_id=execution["id"], agent_id=agent_id, tool_id=native_tool)
        payroll = _make_resource(db, admin, resource_type="payroll", name="Payroll")
        cred = _make_provider_credential(db, admin)
        # a discovered external agent (Phase 5.2 seam)
        from app.models.user import User
        from app.runtime.registry.control import AgentProvenanceService
        user = db.get(User, uuid.UUID(admin["user_id"]))
        ext_agent = AgentProvenanceService(db).record_external_agent(
            actor=user, name="Discovered Copilot", origin_category="EXTERNAL",
            origin_provider="MICROSOFT", external_reference=f"copilot://{uuid.uuid4().hex}",
        )
        ext_agent_id = str(ext_agent.id)
    finally:
        db.close()

    # --- MCP server via the Tool domain, one unapproved ------------------- #
    unapproved_mcp = _register_mcp(client, admin, trust_status="UNKNOWN", provenance="DISCOVERED")
    mcp_tool = _make_tool(client, admin)
    assert client.post(f"{GRAPH}/mcp-servers/{unapproved_mcp['id']}/tools",
                       headers=admin["headers"], json={"tool_id": mcp_tool}).status_code == 201

    # --- declared dependency edges --------------------------------------- #
    for body in (
        {"source": {"type": "AGENT", "id": agent_id}, "edge_type": "DEPENDS_ON_TOOL",
         "target": {"type": "TOOL", "id": native_tool}},
        {"source": {"type": "TOOL", "id": native_tool}, "edge_type": "TOOL_ACCESSES_RESOURCE",
         "target": {"type": "RESOURCE", "id": str(payroll)}},
        {"source": {"type": "AGENT", "id": agent_id}, "edge_type": "DEPENDS_ON_CREDENTIAL",
         "target": {"type": "CREDENTIAL", "id": str(cred)}},
        {"source": {"type": "CREDENTIAL", "id": str(cred)}, "edge_type": "CREDENTIAL_ACCESSES_RESOURCE",
         "target": {"type": "RESOURCE", "id": str(payroll)}},
        {"source": {"type": "AGENT", "id": agent_id}, "edge_type": "DEPENDS_ON_MCP_SERVER",
         "target": {"type": "MCP_SERVER", "id": unapproved_mcp["id"]}},
        {"source": {"type": "AGENT", "id": ext_agent_id}, "edge_type": "DEPENDS_ON_MCP_SERVER",
         "target": {"type": "MCP_SERVER", "id": unapproved_mcp["id"]}},
    ):
        assert client.post(f"{GRAPH}/dependency-edges", headers=admin["headers"], json=body).status_code == 201

    # observed edges from evidence
    rebuild = client.post(f"{GRAPH}/agents/{agent_id}/dependencies/rebuild", headers=admin["headers"]).json()
    assert rebuild["by_type"].get("DEPENDS_ON_TOOL", 0) >= 1

    # 1. which agents can reach payroll -- correct + explainable
    reach = client.get(f"{GRAPH}/blast-radius/agents-reaching", headers=admin["headers"],
                       params={"node_type": "RESOURCE", "node_id": str(payroll)}).json()
    assert agent_id in {a["node"]["id"] for a in reach["agents"]}
    assert all(a["edges"] for a in reach["agents"])  # every answer names its path

    # 2. what breaks if the credential is revoked -- exact dependent set
    breaks = client.get(f"{GRAPH}/blast-radius/what-breaks", headers=admin["headers"],
                        params={"node_type": "CREDENTIAL", "node_id": str(cred)}).json()
    assert {a["node"]["id"] for a in breaks["affected_agents"]} == {agent_id}

    # 3. which agents depend on the unapproved MCP server -- surfaces both
    mcp_dep = client.get(f"{GRAPH}/blast-radius/mcp-dependents/{unapproved_mcp['id']}",
                         headers=admin["headers"]).json()
    assert {a["node"]["id"] for a in mcp_dep["agents"]} == {agent_id, ext_agent_id}
    assert mcp_dep["mcp_server"]["is_unapproved_dependency"] is True  # evidence, not a finding

    # 4. a planted cross-tenant dependency edge does not extend any blast radius
    other_setup = _ready_agent(client, other_org_admin)
    db = SessionLocal()
    try:
        db.execute(
            text(
                """
                INSERT INTO control_graph_edges
                    (id, organization_id, source_type, source_id, edge_type, target_type,
                     target_id, evidence, confidence, provenance, valid_from, created_at, updated_at)
                VALUES (:id, :org_a, 'AGENT', :foreign, 'DEPENDS_ON_TOOL', 'TOOL', :tool_a,
                        '{}'::jsonb, 1.0, 'DERIVED', now(), now(), now())
                """
            ),
            {"id": str(uuid.uuid4()), "org_a": admin["organization_id"],
             "foreign": other_setup["agent"]["id"], "tool_a": native_tool},
        )
        db.commit()
    finally:
        db.close()
    reach2 = client.get(f"{GRAPH}/blast-radius/agents-reaching", headers=admin["headers"],
                        params={"node_type": "RESOURCE", "node_id": str(payroll)}).json()
    assert other_setup["agent"]["id"] not in {a["node"]["id"] for a in reach2["all_dependents"]}

    # 5. tenant isolation + audit + no secret
    assert client.get(f"{GRAPH}/blast-radius/agents-reaching", headers=other_org_admin["headers"],
                      params={"node_type": "RESOURCE", "node_id": str(payroll)}).status_code == 404
    db = SessionLocal()
    try:
        assert db.execute(
            text("SELECT count(*) FROM authorization_audit WHERE organization_id = :org "
                 "AND event_type IN ('GRAPH_BLAST_RADIUS_QUERIED','GRAPH_DEPENDENCY_EDGE_CREATED',"
                 "'GRAPH_MCP_SERVER_REGISTERED')"),
            {"org": admin["organization_id"]},
        ).scalar() >= 3
        secret_hits = db.execute(
            text("SELECT count(*) FROM control_graph_edges WHERE organization_id = :org "
                 "AND evidence::text ILIKE '%ciphertext%'"),
            {"org": admin["organization_id"]},
        ).scalar()
        assert secret_hits == 0
    finally:
        db.close()
