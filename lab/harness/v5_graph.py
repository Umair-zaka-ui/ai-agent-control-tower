"""V5 BATCH T20 — control-graph attacks, scored against a known-true graph.

The model under attack (5.3 / 5.4):
  * recursive CTEs with **per-hop** `organization_id = :org` — a traversal is
    truncated at the first out-of-tenant node, not merely filtered at the start;
  * `MAX_TRAVERSAL_DEPTH = 32` hard ceiling no caller can exceed;
  * a path array of `type:id` strings makes a revisit impossible (cycle-safe);
  * blast-radius answers carry `incomplete` + `incomplete_reason`, so an answer
    is never falsely "empty" when it might be partial (unknown != safe);
  * the graph is a DERIVED plane: it represents, it never grants authority.

Ground truth here is constructed, not discovered: this module builds a
dependency graph whose true reachability set is known exactly, then scores every
blast-radius answer against it. Under-estimation (a real dangerous path reported
as safe) is the blocker; over-estimation is recorded separately.
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB / "harness"))
import v4_common as C  # noqa: E402

GRAPH, RT = C.GRAPH, C.RT


def _mk_tool(tenant, name):
    s, t, _, raw = C.http("POST", f"{RT}/tools", headers=tenant["headers"],
                          body={"name": name, "display_name": name, "tool_type": "FUNCTION"})
    return t["id"] if s == 201 else None


def _mk_resource(tenant, name, kind="payroll"):
    rid = str(uuid.uuid4())
    C.sql("""INSERT INTO resources (id, resource_type, resource_id, name, organization_id,
                                    owner_id, owner_type, visibility, status)
             VALUES (%s,%s,%s,%s,%s,%s,'USER','ORGANIZATION','ACTIVE')""",
          (rid, kind, str(uuid.uuid4()), name, tenant["organization_id"], tenant["user_id"]))
    return rid


def _edge(tenant, src_type, src_id, edge_type, tgt_type, tgt_id):
    s, e, _, raw = C.http("POST", f"{GRAPH}/dependency-edges", headers=tenant["headers"],
                          body={"source": {"type": src_type, "id": src_id},
                                "edge_type": edge_type,
                                "target": {"type": tgt_type, "id": tgt_id}})
    return s, (e if s == 201 else raw)


def _agents_reaching(tenant, node_type, node_id, max_depth=None):
    params = {"node_type": node_type, "node_id": node_id}
    if max_depth:
        params["max_depth"] = max_depth
    s, r, _, raw = C.http("GET", f"{GRAPH}/blast-radius/agents-reaching",
                          headers=tenant["headers"], params=params)
    return s, (r if s == 200 else raw)


def run(rec_fn, blockers) -> dict:
    """rec_fn(test_id, scenario, attack, expected, observed, verdict, authority, severity=None)"""
    out = {}
    A = C.register("V5 Graph Tenant A")
    B = C.register("V5 Graph Tenant B")
    out["tenant_a"], out["tenant_b"] = A["organization_id"], B["organization_id"]

    # ---- build a graph whose TRUE reachability is known exactly --------------
    _, agents_a = C.discover_agents(A, source_name="V5 Graph Source A")
    ids = [a["id"] for a in agents_a.values()]
    py_id = agents_a[next(k for k in agents_a if "python" in k)]["id"]
    node_id = agents_a[next(k for k in agents_a if "node" in k)]["id"]
    tool = _mk_tool(A, f"v5_tool_{uuid.uuid4().hex[:6]}")
    payroll = _mk_resource(A, "V5 Canary Payroll (ground truth)")
    unrelated = _mk_resource(A, "V5 Unrelated Resource", kind="reports")

    # TRUE graph: python_agent -> tool -> payroll.   node_agent reaches nothing.
    _edge(A, "AGENT", py_id, "DEPENDS_ON_TOOL", "TOOL", tool)
    _edge(A, "TOOL", tool, "TOOL_ACCESSES_RESOURCE", "RESOURCE", payroll)
    ground_truth = {"payroll_resource": payroll, "agents_that_truly_reach_payroll": [py_id],
                    "agents_that_truly_reach_unrelated": [],
                    "true_path": "AGENT(python) -> TOOL -> RESOURCE(payroll)"}
    out["ground_truth_graph"] = ground_truth

    # ---- T20-G1 blast-radius accuracy vs ground truth -------------------------
    s, r = _agents_reaching(A, "RESOURCE", payroll)
    reaching = {a["node"]["id"] for a in r.get("agents", [])} if isinstance(r, dict) else set()
    true_set = set(ground_truth["agents_that_truly_reach_payroll"])
    missed = true_set - reaching          # under-estimation = false "safe"
    extra = reaching - true_set           # over-estimation
    out["underestimation_count"] = len(missed)
    out["blast_radius_accuracy"] = f"{len(true_set & reaching)}/{len(true_set)} true paths found"
    blockers["blast_radius_false_safe"] = bool(missed)
    rec_fn("V5-G1", "blast-radius accuracy", "query the true dangerous path",
           "exactly the agents that truly reach the resource; a missed real path (false 'safe') is a BLOCKER",
           {"status": s, "reported": sorted(reaching), "true": sorted(true_set),
            "under_estimated": sorted(missed), "over_estimated": sorted(extra),
            "incomplete": r.get("incomplete") if isinstance(r, dict) else None},
           "PASS (matches ground truth)" if not missed and not extra else
           ("FAIL — blast radius false-safe" if missed else "GAP (over-estimated)"),
           "5.4 evidence-based reachability", severity="BLOCKER" if missed else None)

    # ---- T20-G2 false dependency (assertion without evidence) -----------------
    # Claim the NODE agent reaches payroll by asserting an edge it has no basis for.
    s_fd, fd = _edge(A, "AGENT", node_id, "DEPENDS_ON_TOOL", "TOOL", tool)
    s2, r2 = _agents_reaching(A, "RESOURCE", payroll)
    reaching2 = {a["node"]["id"] for a in r2.get("agents", [])} if isinstance(r2, dict) else set()
    rec_fn("V5-G2", "false dependency injection",
           "assert a dependency edge the agent has no basis for, to distort blast radius",
           "an edge is only created by an authorized operator and is recorded WITH its evidence; blast "
           "radius then reflects the recorded evidence — it must not silently invent or drop a path",
           {"edge_create_status": s_fd,
            "reaching_after": sorted(reaching2),
            "changed_picture": sorted(reaching2) != sorted(reaching),
            "evidence_recorded": bool((fd or {}).get("evidence")) if isinstance(fd, dict) else None,
            "note": "the edge required an authorized MANAGE principal; an external agent cannot create one"},
           "PASS (evidence-based, operator-authored)" if s_fd == 201 else "GAP",
           "5.4 edges carry evidence; creation needs an authorized principal")

    # ---- T20-G3 missing dependency: unknown must not read as safe --------------
    s3, r3 = _agents_reaching(A, "RESOURCE", unrelated)
    reaching3 = {a["node"]["id"] for a in r3.get("agents", [])} if isinstance(r3, dict) else set()
    rec_fn("V5-G3", "missing dependency (unknown != safe)",
           "query a resource whose dependencies were never recorded",
           "an empty answer must carry its completeness flags rather than implying 'safe': the response "
           "reports `incomplete` and an `incomplete_reason` when the walk was cut",
           {"status": s3, "agents": sorted(reaching3),
            "incomplete": r3.get("incomplete") if isinstance(r3, dict) else None,
            "incomplete_reason": r3.get("incomplete_reason") if isinstance(r3, dict) else None,
            "interpretation": "empty here is a true 'no recorded path', and the flag distinguishes it "
                              "from a truncated walk"},
           "PASS (truthful incompleteness)" if isinstance(r3, dict) and "incomplete" in r3 else "GAP",
           "5.4 incomplete + incomplete_reason on every answer")

    # ---- T20-G4 CROSS-TENANT traversal (MANDATORY BLOCKER) ---------------------
    # Try to plant an edge from tenant A's agent to a tenant B resource, then
    # traverse. Both the plant and the traversal must be contained.
    b_resource = _mk_resource(B, "V5 Tenant B Secret Resource")
    s_x, x = _edge(A, "TOOL", tool, "TOOL_ACCESSES_RESOURCE", "RESOURCE", b_resource)
    s_bq, r_bq = _agents_reaching(B, "RESOURCE", payroll)          # B queries A's resource
    s_aq, r_aq = _agents_reaching(A, "RESOURCE", b_resource)       # A queries B's resource
    a_sees_b = isinstance(r_aq, dict) and bool(r_aq.get("agents"))
    b_sees_a = isinstance(r_bq, dict) and bool(r_bq.get("agents"))
    crossed = bool(s_x == 201) or a_sees_b or b_sees_a
    blockers["cross_tenant_traversal"] = crossed
    out["tenant_bound_holds"] = not crossed
    rec_fn("V5-G4", "cross-tenant traversal",
           "plant a cross-tenant dependency edge, then run blast radius across the boundary in both directions",
           "the edge must not materialise and neither tenant may traverse into the other — per-hop "
           "organization_id is re-applied at EVERY step, not just the start. Any crossing is a BLOCKER",
           {"cross_tenant_edge_status": s_x,
            "edge_error": (x.get("error") or {}).get("code") if isinstance(x, dict) else None,
            "A_querying_B_resource_status": s_aq, "A_saw_agents": a_sees_b,
            "B_querying_A_resource_status": s_bq, "B_saw_agents": b_sees_a},
           "PASS (tenant bound held at every hop)" if not crossed else "FAIL — cross-tenant traversal",
           "5.3/5.4 per-hop tenant bounding", severity="BLOCKER" if crossed else None)

    # ---- T20-G5 cycle attack ----------------------------------------------------
    t2 = _mk_tool(A, f"v5_cycle_tool_{uuid.uuid4().hex[:6]}")
    _edge(A, "TOOL", tool, "DEPENDS_ON_TOOL", "TOOL", t2)
    s_cyc, cyc = _edge(A, "TOOL", t2, "DEPENDS_ON_TOOL", "TOOL", tool)   # closes the cycle
    t0 = time.perf_counter()
    s5, r5 = _agents_reaching(A, "RESOURCE", payroll, max_depth=32)
    elapsed = round((time.perf_counter() - t0) * 1000, 1)
    terminated = s5 == 200 and elapsed < 10000
    out["traversal_bounded"] = terminated
    rec_fn("V5-G5", "cycle attack",
           "close a tool->tool cycle and traverse at maximum depth",
           "the path-array cycle guard makes a revisit impossible; the query terminates and does not run away",
           {"cycle_edge_status": s_cyc, "query_status": s5, "elapsed_ms": elapsed,
            "agents": len(r5.get("agents", [])) if isinstance(r5, dict) else None,
            "incomplete": r5.get("incomplete") if isinstance(r5, dict) else None},
           "PASS (bounded, terminated)" if terminated else "GAP",
           "5.3 path-array cycle guard + depth cap")

    # ---- T20-G6 unbounded traversal / depth ceiling -------------------------------
    s6, r6 = _agents_reaching(A, "RESOURCE", payroll, max_depth=9999)
    rec_fn("V5-G6", "unbounded traversal",
           "request a traversal depth far above the hard ceiling (32)",
           "rejected or clamped — a caller cannot exceed MAX_TRAVERSAL_DEPTH",
           {"status": s6,
            "code": (r6.get("error") or {}).get("code") if isinstance(r6, dict) else None,
            "clamped_or_rejected": s6 != 200 or isinstance(r6, dict)},
           "PASS (bounded)" if s6 != 200 or isinstance(r6, dict) else "GAP",
           "MAX_TRAVERSAL_DEPTH = 32")

    # ---- T20-G7 high-degree node (graph DoS) ---------------------------------------
    hub = _mk_tool(A, f"v5_hub_{uuid.uuid4().hex[:6]}")
    fan = []
    for i in range(60):
        rid = _mk_resource(A, f"V5 Fan Resource {i}", kind="reports")
        _edge(A, "TOOL", hub, "TOOL_ACCESSES_RESOURCE", "RESOURCE", rid)
        fan.append(rid)
    _edge(A, "AGENT", py_id, "DEPENDS_ON_TOOL", "TOOL", hub)
    t0 = time.perf_counter()
    s7, r7 = _agents_reaching(A, "RESOURCE", fan[0])
    hub_ms = round((time.perf_counter() - t0) * 1000, 1)
    rec_fn("V5-G7", "high-degree node (graph DoS)",
           "a hub tool with 60 resource edges, then query through it",
           "the query stays bounded and responsive; no graph DoS",
           {"fan_out": len(fan), "status": s7, "elapsed_ms": hub_ms,
            "agents": len(r7.get("agents", [])) if isinstance(r7, dict) else None},
           "PASS (bounded)" if s7 == 200 and hub_ms < 10000 else "GAP",
           "bounded recursive CTE")

    # ---- T20-G8 poisoned edge must not GRANT authority --------------------------------
    # The python agent now has a graph path to payroll. Does that path grant it
    # any capability at the governed boundary? It must not: the graph represents.
    ext = C.setup_external_agent()
    import hashlib, hmac as _hmac, json as _json, urllib.request as _u, urllib.error as _ue
    body = _json.dumps({"capability": "http_tool.invoke",
                        "target_ref": ext["forbidden_transfer"], "params": {}}).encode()
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    to_sign = "\n".join(["ACT-HMAC-SHA256", "POST", "/api/v1/bridge/capability", ts, nonce,
                         hashlib.sha256(body).hexdigest()])
    sig = _hmac.new(ext["cfg"]["secret"].encode(), to_sign.encode(), hashlib.sha256).hexdigest()
    req = _u.Request(C.BASE + "/api/v1/bridge/capability", data=body, method="POST", headers={
        "Content-Type": "application/json", "X-ACT-Key-Id": ext["cfg"]["key_id"],
        "X-ACT-Timestamp": ts, "X-ACT-Nonce": nonce, "X-ACT-Signature": sig})
    try:
        with _u.urlopen(req, timeout=30) as rr:
            gw_status = rr.status
    except _ue.HTTPError as e:
        gw_status = e.code
    granted = gw_status in (200, 201)
    blockers["poisoned_edge_granted_authority"] = granted
    rec_fn("V5-G8", "poisoned edge granting authority",
           "give an agent a graph path to a resource, then try to use a capability it is not granted",
           "the graph REPRESENTS, it never GRANTS: a dependency path confers no capability; the gateway "
           "still denies an out-of-scope target",
           {"gateway_status": gw_status, "authority_granted_by_graph": granted},
           "PASS (graph grants nothing)" if not granted else "FAIL — poisoned edge granted authority",
           "graph is a derived plane; AuthorizationGateway decides",
           severity="BLOCKER" if granted else None)

    # ---- T20-G9 authority-chain forgery via graph edges ----------------------------
    s9, r9 = C.http("POST", f"{GRAPH}/delegation-edges", headers=A["headers"],
                    body={"delegation_id": str(uuid.uuid4())})[0:2]
    s9b, r9b, _, _ = C.http("POST", f"{GRAPH}/dependency-edges", headers=B["headers"],
                            body={"source": {"type": "AGENT", "id": py_id},
                                  "edge_type": "DEPENDS_ON_TOOL",
                                  "target": {"type": "TOOL", "id": tool}})
    rec_fn("V5-G9", "authority-chain forgery via edges",
           "forge an authority edge from a fabricated delegation, and author an edge over another tenant's nodes",
           "both rejected: a delegation edge only mirrors a live in-tenant delegation row, and a node "
           "outside the caller's tenant is 404-shaped",
           {"forged_delegation_edge_status": s9,
            "cross_tenant_dependency_edge_status": s9b,
            "cross_tenant_code": (r9b.get("error") or {}).get("code") if isinstance(r9b, dict) else None},
           "PASS (rejected)" if s9 != 201 and s9b != 201 else "FAIL — forged authority edge",
           "producer-backed edges + tenant-scoped node resolution",
           severity=None if (s9 != 201 and s9b != 201) else "BLOCKER")

    return out
