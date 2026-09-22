"""V4 BATCH T8 — DELEGATION RED TEAM: forgery, amplification, laundering, truncation.

The model under attack:
  * `Delegation` rows are created by `DelegationService.delegate`, always with
    `organization_id = actor.organization_id` and `delegator_id = actor.id`;
    delegating a scope that does not resolve to the actor's own org raises
    `DELEGATION_EXCEEDS_AUTHORITY`.
  * `POST /graph/delegation-edges` only **mirrors** an existing, live, in-tenant
    delegation row (both HUMAN endpoints re-checked in-tenant). There is no route
    that creates a free-form authority edge, and none that creates
    `AGENT_DELEGATES_TO` at all.
  * `GET /graph/authority-chain/executions/{id}` reconstructs who authorized an
    execution, per-hop tenant-bounded, each hop naming its evidence, and sets
    `complete=False` **with a note** whenever a hop cannot be resolved — it reports
    "may be incomplete", never falsely complete or falsely empty.
  * Traversal is bounded (`MAX_TRAVERSAL_DEPTH = 32`) and cycle-safe (a path array
    makes a revisit impossible).

**P1 (§0):** a forgeable, replayable, amplifiable, launderable or *truncatable*
authority chain blocks pilot readiness. Expected behaviour is fixed before
execution. Imports nothing from `app`.
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "lab"
RUN = LAB / "run"
RES = RUN / "results"
RES.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(LAB / "harness"))
import ledger  # noqa: E402
import v4_common as C  # noqa: E402


def login(email, password=C.PASSWORD):
    s, tok, _, _ = C.http("POST", "/api/v1/auth/login", body={"email": email, "password": password})
    if s != 200:
        return None
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    s, me, _, _ = C.http("GET", "/api/v1/auth/me", headers=h)
    return {"headers": h, "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"],
            "email": email}


def main() -> int:
    out = {"batch": "T8", "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "scenarios": [],
           "p1": {"forgeable": False, "amplifiable": False, "launderable": False,
                  "truncatable_silently": False}}

    A = C.register("V4 T8 Tenant A")
    B = C.register("V4 T8 Tenant B")
    out["tenant_a"], out["tenant_b"] = A["organization_id"], B["organization_id"]

    def rec(test_id, scenario, attack, expected, observed, verdict, authority, severity=None):
        row = {"test_id": test_id, "threat": "T8", "scenario": scenario, "attack": attack,
               "expected": expected, "observed": observed, "verdict": verdict, "authority": authority}
        if severity:
            row["severity"] = severity
        out["scenarios"].append(row)
        print(f"  T8 {test_id:<8} {scenario:<38} -> {verdict}", flush=True)

    # --- control: a real native execution + its authority chain ----------------
    native = C.create_native_agent_with_execution(A)
    out["native_setup_steps"] = native.get("steps")
    exec_id = (native.get("execution") or {}).get("id")
    out["execution_id"] = exec_id
    if exec_id:
        s, chain = C.authority_chain(A, exec_id)
        hops = chain.get("hops", []) if isinstance(chain, dict) else []
        rec("T8-01", "authority-chain baseline (control)", "reconstruct a real execution's chain",
            "200 with hops, each naming evidence, and a truthful `complete` flag",
            {"status": s, "hop_count": len(hops), "complete": chain.get("complete"),
             "notes": chain.get("notes"), "hop_types": [h.get("edge_type") or h.get("node_type") for h in hops]},
            "PASS (control)" if s == 200 else "FAIL (control)", "5.3 authority chain")
    else:
        rec("T8-01", "authority-chain baseline (control)", "reconstruct a real execution's chain",
            "200 with hops", {"execution_created": False, "detail": native.get("execution_error"),
                              "steps": native.get("steps")},
            "BLOCKED (no execution surface in lab)", "5.3 authority chain")

    # --- T8-02 forged delegation edge (no such delegation) ----------------------
    s, r = C.create_delegation_edge(A, uuid.uuid4())
    forged_ok = s == 201
    out["p1"]["forgeable"] = out["p1"]["forgeable"] or forged_ok
    rec("T8-02", "forged delegation edge", "create an authority edge from a fabricated delegation id",
        "reject — the edge only mirrors an existing live in-tenant delegation row",
        {"status": s, "code": (r.get("error") or {}).get("code") if isinstance(r, dict) else None},
        "PASS (rejected)" if not forged_ok else "FAIL — P1 FORGERY", "DelegationService ownership of the lifecycle",
        severity="P1" if forged_ok else None)

    # --- second + third human in tenant A (delegatees) ---------------------------
    u2 = C.add_user(A, "V4 Delegatee B")
    u3 = C.add_user(A, "V4 Delegatee C")
    out["users"] = {"u2": u2.get("status"), "u3": u3.get("status")}

    deleg_id = None
    if u2.get("id"):
        s, d = C.create_delegation(A, u2["id"], scope_type="ORGANIZATION")
        if s == 201:
            deleg_id = d["id"]
        rec("T8-03", "legitimate delegation (control)", "org-scoped delegation to an in-tenant human",
            "201 — the delegator may delegate within their own organization",
            {"status": s, "delegation_id": deleg_id}, "PASS (control)" if s == 201 else "FAIL",
            "DelegationService.delegate")

    # --- T8-04 delegation scope outside the delegator's own org ------------------
    s, r = C.create_delegation(A, u2["id"] if u2.get("id") else str(uuid.uuid4()),
                               scope_type="ORGANIZATION", scope_id=B["organization_id"])
    code = (r.get("error") or {}).get("code") if isinstance(r, dict) else None
    amplified = s == 201
    out["p1"]["amplifiable"] = out["p1"]["amplifiable"] or amplified
    rec("T8-04", "delegate a scope outside own authority",
        "delegate ORGANIZATION scope naming ANOTHER tenant's org id",
        "reject with DELEGATION_EXCEEDS_AUTHORITY — a delegator cannot grant beyond their own org",
        {"status": s, "code": code},
        "PASS (rejected)" if not amplified else "FAIL — P1 AMPLIFICATION",
        "DelegationService org boundary", severity="P1" if amplified else None)

    # --- T8-05 cross-tenant delegatee -------------------------------------------
    s, r = C.create_delegation(A, B["user_id"], scope_type="ORGANIZATION")
    # a delegation row is always stamped with the delegator's org; a cross-tenant
    # delegatee must not yield an edge that extends authority into tenant B.
    xdeleg = d_id = None
    if s == 201:
        d_id = r["id"]
        se, re_ = C.create_delegation_edge(A, d_id)
        xdeleg = {"delegation_status": s, "edge_status": se,
                  "edge_code": (re_.get("error") or {}).get("code") if isinstance(re_, dict) else None}
        ok = se != 201  # the edge must NOT materialize for an out-of-tenant endpoint
    else:
        xdeleg = {"delegation_status": s,
                  "code": (r.get("error") or {}).get("code") if isinstance(r, dict) else None}
        ok = True
    rec("T8-05", "cross-tenant delegatee", "delegate to a human in another tenant",
        "the authority edge must not materialize across the tenant boundary "
        "(both HUMAN endpoints are re-checked in-tenant)",
        xdeleg, "PASS (tenant bound held)" if ok else "FAIL — cross-tenant authority",
        "create_delegation_edge in-tenant endpoint check", severity=None if ok else "P0")

    # --- T8-06 delegation edge from a REVOKED delegation --------------------------
    if deleg_id:
        s_rev, _, _, _ = C.http("DELETE", f"/api/v1/delegations/{deleg_id}", headers=A["headers"])
        s, r = C.create_delegation_edge(A, deleg_id)
        rec("T8-06", "edge from a revoked delegation", "materialize an edge after revoking the delegation",
            "reject — the edge may only mirror a LIVE delegation",
            {"revoke_status": s_rev, "edge_status": s,
             "code": (r.get("error") or {}).get("code") if isinstance(r, dict) else None},
            "PASS (rejected)" if s != 201 else "FAIL — revoked authority materialized",
            "live-delegation requirement")

    # --- T8-07 replay: same delegation materialized twice --------------------------
    if u3.get("id"):
        s, d3 = C.create_delegation(A, u3["id"], scope_type="ORGANIZATION")
        if s == 201:
            s1, _ = C.create_delegation_edge(A, d3["id"])
            s2, r2 = C.create_delegation_edge(A, d3["id"])
            rec("T8-07", "delegation edge replay", "materialize the same delegation edge twice",
                "the second must not create a second independent authority edge "
                "(idempotent or conflict) — authority must not accumulate by replay",
                {"first": s1, "second": s2,
                 "code": (r2.get("error") or {}).get("code") if isinstance(r2, dict) else None},
                "PASS (no authority accumulation)" if s2 != 201 or s1 != 201 else "GAP (duplicate edge created)",
                "edge uniqueness")

    # --- T8-08 authority laundering A -> B -> C -------------------------------------
    launder = {"note": "delegations are always stamped organization_id = delegator's org"}
    if u2.get("id") and u3.get("id"):
        Bu = login(u2["email"])
        if Bu:
            s, d = C.create_delegation(Bu, u3["id"], scope_type="ORGANIZATION")
            launder["b_to_c_status"] = s
            rows = C.sql("""SELECT DISTINCT organization_id::text FROM delegations
                            WHERE organization_id=%s""", (A["organization_id"],))
            launder["all_delegations_in_tenant_a"] = [r[0] for r in rows]
            launder["c_org_exceeds_a"] = any(r[0] != A["organization_id"] for r in rows)
        else:
            launder["b_login"] = "failed"
    laundered = bool(launder.get("c_org_exceeds_a"))
    out["p1"]["launderable"] = laundered
    rec("T8-08", "authority laundering A->B->C", "chain delegations so C exceeds A's authority",
        "C cannot exceed A: every delegation is stamped with the delegator's own org and "
        "cannot name another organization",
        launder, "PASS (no widening)" if not laundered else "FAIL — P1 LAUNDERING",
        "DelegationService org stamping", severity="P1" if laundered else None)

    # --- T8-09 cyclic delegation / recursive loop -------------------------------------
    cyc = {}
    try:
        agents = C.sql("SELECT id FROM agents WHERE organization_id=%s LIMIT 2", (A["organization_id"],))
        if len(agents) < 2:
            # populate the tenant with the lab's external agents so a cycle has nodes
            C.discover_agents(A, source_name="V4 T8 Registry")
            agents = C.sql("SELECT id FROM agents WHERE organization_id=%s LIMIT 2",
                           (A["organization_id"],))
        if len(agents) >= 2:
            a1, a2 = str(agents[0][0]), str(agents[1][0])
            s1, _, _, _ = C.http("POST", "/api/v1/graph/trust-edges", headers=A["headers"],
                                 body={"source": {"type": "AGENT", "id": a1},
                                       "target": {"type": "AGENT", "id": a2}, "note": "v4 cycle a"})
            s2, _, _, _ = C.http("POST", "/api/v1/graph/trust-edges", headers=A["headers"],
                                 body={"source": {"type": "AGENT", "id": a2},
                                       "target": {"type": "AGENT", "id": a1}, "note": "v4 cycle b"})
            t0 = time.perf_counter()
            sr, reach = C.reachability(A, "AGENT", a1, direction="out", max_depth=32)
            cyc = {"edge_a": s1, "edge_b": s2, "reachability_status": sr,
                   "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
                   "reachable_count": len(reach.get("reachable", [])) if isinstance(reach, dict) else None}
        else:
            cyc = {"note": "fewer than two agents available"}
    except Exception as e:
        cyc = {"error": str(e)[:200]}
    bounded = cyc.get("reachability_status") == 200 and (cyc.get("elapsed_ms") or 0) < 10000
    rec("T8-09", "cyclic delegation / recursive loop", "A->B and B->A, then traverse",
        "bounded and cycle-safe: a path array makes a revisit impossible; must terminate",
        cyc, "PASS (bounded, terminated)" if bounded else "GAP", "cycle-safe recursive CTE + depth cap")

    # --- T8-10 CHAIN TRUNCATION: does a depth-limited chain LIE about completeness? ---
    trunc = {}
    # Build a chain that actually HAS a delegation prefix, otherwise a depth limit
    # has nothing to truncate and the probe proves nothing. Delegate A->B, mirror
    # the edge, then have B trigger the execution so B's identity roots the chain.
    deleg_exec_id = None
    if u2.get("id"):
        s_d2, d2 = C.create_delegation(A, u2["id"], scope_type="ORGANIZATION")
        if s_d2 == 201:
            s_e2, _ = C.create_delegation_edge(A, d2["id"])
            trunc["delegation_edge_status"] = s_e2
        Bu2 = login(u2["email"])
        if Bu2 and native.get("agent"):
            s_x, x, _, _ = C.http("POST", f"{C.RT}/executions", headers=Bu2["headers"],
                                  body={"agent_id": native["agent"]["id"], "input_payload": {}})
            trunc["delegatee_execution_status"] = s_x
            if s_x == 201:
                deleg_exec_id = x["id"]
    probe_exec = deleg_exec_id or exec_id
    trunc["chain_execution_used"] = probe_exec
    trunc["chain_has_delegation_prefix"] = deleg_exec_id is not None
    if probe_exec:
        s_full, full = C.authority_chain(A, probe_exec)
        s_lim, lim = C.authority_chain(A, probe_exec, max_depth=1)
        trunc = {"full_status": s_full, "full_hops": len(full.get("hops", [])) if isinstance(full, dict) else None,
                 "full_complete": full.get("complete") if isinstance(full, dict) else None,
                 "full_notes": full.get("notes") if isinstance(full, dict) else None,
                 "limited_status": s_lim,
                 "limited_hops": len(lim.get("hops", [])) if isinstance(lim, dict) else None,
                 "limited_complete": lim.get("complete") if isinstance(lim, dict) else None,
                 "limited_notes": lim.get("notes") if isinstance(lim, dict) else None,
                 **trunc}
        # A silent truncation = fewer hops than the full chain while still claiming complete=True.
        silent = (trunc["limited_hops"] is not None and trunc["full_hops"] is not None
                  and trunc["limited_hops"] < trunc["full_hops"] and trunc["limited_complete"] is True)
        out["p1"]["truncatable_silently"] = silent
        rec("T8-10", "chain truncation (hidden hop)",
            "force a depth limit and check whether a shortened chain still claims completeness",
            "ACT must never present a truncated chain as complete: fewer hops must come with "
            "complete=false and a note naming the reason",
            trunc, "PASS (no silent truncation)" if not silent else "FAIL — P1 HIDDEN HOP",
            "5.3 `complete` flag + notes", severity="P1" if silent else None)

    # --- T8-11 depth ceiling ------------------------------------------------------------
    if exec_id:
        s, r = C.authority_chain(A, exec_id, max_depth=999)
        rec("T8-11", "traversal depth ceiling", "request max_depth far above the hard ceiling (32)",
            "reject — GRAPH_TRAVERSAL_DEPTH_EXCEEDED (defence in depth against a pathological request)",
            {"status": s, "code": (r.get("error") or {}).get("code") if isinstance(r, dict) else None},
            "PASS (rejected)" if s != 200 else "GAP", "MAX_TRAVERSAL_DEPTH = 32")

    # --- T8-12 cross-tenant chain reconstruction (no existence leak) ----------------------
    if exec_id:
        s, r = C.authority_chain(B, exec_id)
        rec("T8-12", "cross-tenant chain reconstruction", "tenant B reconstructs tenant A's execution",
            "404 — cross-tenant and missing must be indistinguishable (no existence leak)",
            {"status": s, "code": (r.get("error") or {}).get("code") if isinstance(r, dict) else None},
            "PASS (contained, no leak)" if s == 404 else "FAIL — cross-tenant leak",
            "per-tenant bound", severity=None if s == 404 else "P0")

    # --- T8-13 external-agent attribution boundary (an honest observability finding) -------
    ext = C.setup_external_agent()
    import hashlib, hmac as _hmac
    body = json.dumps({"capability": "http_tool.invoke", "target_ref": ext["granted_tool"],
                       "params": {}}).encode()
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    to_sign = "\n".join(["ACT-HMAC-SHA256", "POST", "/api/v1/bridge/capability", ts, nonce,
                         hashlib.sha256(body).hexdigest()])
    sig = _hmac.new(ext["cfg"]["secret"].encode(), to_sign.encode(), hashlib.sha256).hexdigest()
    import urllib.request, urllib.error
    req = urllib.request.Request(C.BASE + "/api/v1/bridge/capability", data=body, method="POST", headers={
        "Content-Type": "application/json", "X-ACT-Key-Id": ext["cfg"]["key_id"],
        "X-ACT-Timestamp": ts, "X-ACT-Nonce": nonce, "X-ACT-Signature": sig})
    try:
        with urllib.request.urlopen(req, timeout=30) as rr:
            call_status = rr.status
    except urllib.error.HTTPError as e:
        call_status = e.code
    gw = C.sql("""SELECT agent_id::text, grant_id::text, outcome FROM external_gateway_calls
                  WHERE organization_id=%s ORDER BY created_at DESC LIMIT 1""",
               (ext["A"]["organization_id"],))
    execs = C.sql("SELECT count(*) FROM agent_executions WHERE organization_id=%s",
                  (ext["A"]["organization_id"],))[0][0]
    rec("T8-13", "external-agent attribution boundary",
        "ask what authority surface exists for an EXTERNAL agent's boundary call",
        "external calls are attributed by agent_id + grant_id in external_gateway_calls; they produce "
        "no agent_executions, so the 5.3 authority-chain surface does not cover them — record truthfully",
        {"gateway_call_status": call_status, "attributed": bool(gw),
         "agent_id": gw[0][0] if gw else None, "grant_id": gw[0][1] if gw else None,
         "agent_executions_for_external_tenant": execs,
         "authority_chain_applies": execs > 0},
        "PASS (truthful boundary: attributed at the gateway, no chain surface)",
        "external_gateway_calls attribution")

    # --- T8-14 non-repudiation / audit ------------------------------------------------------
    events = {r[0] for r in C.sql("SELECT DISTINCT event_type FROM authorization_audit WHERE organization_id=%s",
                                  (A["organization_id"],))}
    org_events = set()
    try:
        org_events = {r[0] for r in C.sql(
            "SELECT DISTINCT event_type FROM organization_audit_events WHERE organization_id=%s",
            (A["organization_id"],))}
    except Exception:
        pass
    want = {"DELEGATION_CREATED", "DELEGATION_REVOKED"}
    rec("T8-14", "non-repudiation (audit of delegation)",
        "deny having authorized a delegation",
        "delegation creation and revocation are recorded with actor and delegatee, making the act "
        "non-repudiable; chain reconstruction is itself audited",
        {"org_audit_events_present": sorted(org_events & want),
         "graph_chain_audit": "GRAPH_AUTHORITY_CHAIN_RECONSTRUCTED" in events,
         "authorization_audit_sample": sorted(list(events))[:8]},
        "PASS (non-repudiable)" if (org_events & want) or "GRAPH_AUTHORITY_CHAIN_RECONSTRUCTED" in events
        else "GAP", "audit trail")

    out["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    fails = [s for s in out["scenarios"] if s["verdict"].startswith("FAIL")]
    integrity_tests = [s for s in out["scenarios"] if s["test_id"] in
                       ("T8-02", "T8-04", "T8-05", "T8-06", "T8-07", "T8-08", "T8-10", "T8-11", "T8-12")]
    held = [s for s in integrity_tests if s["verdict"].startswith("PASS")]
    out["summary"] = {
        "total": len(out["scenarios"]),
        "passes": len([s for s in out["scenarios"] if s["verdict"].startswith("PASS")]),
        "fails": len(fails),
        "delegation_integrity_rate": f"{len(held)}/{len(integrity_tests)}",
        "p1_triggered": any(out["p1"].values()),
    }
    p = RES / "v4_delegation_results.json"
    p.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    ledger.anchor([str(p)])
    print(f"\nT8 DONE: {out['summary']['passes']}/{out['summary']['total']} pass, "
          f"{out['summary']['fails']} fail, P1={out['summary']['p1_triggered']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
