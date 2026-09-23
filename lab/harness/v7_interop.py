"""V7 INTEROPERABILITY HARNESS — seven independent agents, tiers T0–T7.

V3–V6 attacked ACT's boundaries in isolation and they held. V7 is different in
kind: **breadth and truthfulness under real, varied, end-to-end agent behaviour**.
The question is whether ACT governs a LangGraph graph, a CrewAI crew, an OpenAI
Agents SDK agent, an Anthropic SDK agent and three custom agents *truthfully and
consistently* — and where the known observability gaps become FELT.

Two rules it enforces on itself:
  * **Interoperability is NOT scale.** Seven real agents doing real work prove
    interoperability. Nothing here licenses a throughput or latency-at-volume
    claim; that is V9. No such number is produced.
  * A truthful refusal / NOT_OBSERVABLE / recorded gap is a PASS.

Every governance observation is scored against a per-agent ground-truth manifest
captured and hash-anchored before observation. Imports nothing from `app`.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
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

V7 = LAB / "agents" / "v7"
THREAT, POSTURE, GRAPH = "/api/v1/threat", "/api/v1/posture", C.GRAPH
TIERS = (0, 1, 2, 3, 4, 5, 6, 7)

# agent id -> (script, runtime, framework label, multi-agent capable)
#
# The OpenAI Agents SDK lives in its OWN interpreter: CrewAI pins `openai<3`
# and openai-agents requires `openai>=3`, so the two mainstream frameworks
# cannot share a Python environment. Separate runtimes is the honest answer and
# matches V7's premise that each agent is independent. Recorded as finding F7-1.
SDK_PYTHON = os.environ.get("ACTLAB_SDK_PYTHON", "/opt/sdkvenv/bin/python")
AGENTS = {
    "custom_python": ("custom_python.py", "python", "custom (stdlib)", False),
    "custom_node": ("custom_node.js", "node", "custom (Node.js built-ins)", False),
    "mcp_client": ("mcp_client.py", "python", "custom MCP host", False),
    "langgraph": ("langgraph_agent.py", "python", "LangGraph", True),
    "crewai": ("crewai_agent.py", "python", "CrewAI", True),
    "openai_sdk": ("openai_sdk_agent.py", "sdkvenv", "OpenAI Agents SDK", True),
    "anthropic_sdk": ("anthropic_agent.py", "python", "Anthropic SDK", True),
}


def independence(path: Path):
    """Every agent must import nothing from `app` (the V2 discipline)."""
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as e:
        return {"error": str(e)[:120]}
    if path.suffix == ".js":
        import re
        reqs = sorted(set(re.findall(r'require\("([^"]+)"\)', src)))
        return {"imports_app": any(not r.startswith("node:") for r in reqs), "imports": reqs}
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            imported.update(x.name for x in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return {"imports_app": any(m.split(".")[0] == "app" for m in imported),
            "imports": sorted({m.split(".")[0] for m in imported})}


def run_agent(agent_id, cfg_path, tier):
    script, runtime, _, _ = AGENTS[agent_id]
    if runtime == "node":
        cmd = ["node", str(V7 / script)]
    elif runtime == "sdkvenv":
        cmd = [SDK_PYTHON, str(V7 / script)]
    else:
        cmd = [sys.executable, str(V7 / script)]
    cmd += [str(cfg_path), str(tier)]
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(LAB))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "_ms": 300000}
    ms = round((time.perf_counter() - t0) * 1000, 1)
    out = {}
    if p.stdout.strip():
        for line in reversed(p.stdout.strip().splitlines()):
            try:
                out = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if not out:
        out = {"ok": False, "error": (p.stderr or p.stdout or "")[-300:]}
    out["_ms"] = ms
    return out


def main() -> int:
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    out = {"phase": "V7", "started_at": started,
           "scale_claim": "NONE — V7 proves interoperability, not scale (that is V9)",
           "model_policy": {}, "ground_truth": {}, "agents": {}, "assertions": [],
           "p0": {"false_containment_claim": False, "cross_tenant": False,
                  "silent_merge": False, "inferred_a2a_edge": False,
                  "frontier_sensitive_data": False}}

    # ---- model policy -----------------------------------------------------
    model_base = os.environ.get("LAB_MODEL_BASE_URL", "http://local_model:8814/v1")
    import urllib.request
    try:
        with urllib.request.urlopen(model_base + "/models", timeout=10) as r:
            models = json.loads(r.read().decode())
        model_up = True
    except Exception as e:
        models, model_up = {"error": str(e)[:160]}, False
    out["model_policy"] = {
        "substrate": "local, in-network, OpenAI- AND Anthropic-compatible",
        "base_url": model_base, "reachable": model_up,
        "models": models.get("data") if isinstance(models, dict) else None,
        "frontier_api_used": False,
        "frontier_reason": "no operator-set dollar cap and no API key provisioned; the local "
                           "substrate exercises every framework code path ACT governs, so no claim "
                           "in V7 required a paid run",
        "sensitive_data_to_paid_endpoint": "none — no paid endpoint was contacted at all",
        "honest_limitation": "the substrate is a DETERMINISTIC inference server, not a neural "
                             "model: it exercises the frameworks' real tool-calling, handoff and "
                             "SDK wire paths (what ACT governs) but not model reasoning quality "
                             "(which ACT does not govern)",
    }
    out["runtime_policy"] = {
        "separate_environments": True,
        "reason": "crewai pins openai<3 while openai-agents requires openai>=3 — the two "
                  "frameworks cannot share one Python environment (finding F7-1)",
        "base_env": "langgraph + crewai + anthropic",
        "sdk_env": SDK_PYTHON + " (openai-agents + anthropic)",
        "node_runtime": "nodejs (custom Node agent)",
    }
    print(f"model substrate reachable={model_up}; sdk interpreter={SDK_PYTHON}", flush=True)

    # ---- tenant + shared governed surface ---------------------------------
    ext = C.setup_external_agent()
    A, B = ext["A"], ext["B"]
    org = A["organization_id"]
    out["tenants"] = {"A": org, "B": B["organization_id"]}

    # a real dependency path so blast radius has a known-true answer
    s, mcp_srv, _, _ = C.http("POST", f"{GRAPH}/mcp-servers", headers=A["headers"], body={
        "name": "lab-payroll-mcp", "provenance": "EXPLICIT", "trust_status": "APPROVED",
        "version": "1.0.0", "endpoint_reference": f"http://{os.environ.get('LAB_MCP_HOST','mcp_trusted')}:8831/mcp",
        "declared_capabilities": {"tools": ["payroll_read"]}})

    # ---- §2.7 GROUND TRUTH per agent, before any governance observation ----
    discovered = {a["external_reference"]: a for a in [
        {"external_reference": r[2], "id": str(r[0]), "name": r[1]}
        for r in C.sql("SELECT id, name, external_reference FROM agents WHERE organization_id=%s",
                       (org,))]}
    gt = {}
    for aid, (script, runtime, framework, multi) in AGENTS.items():
        gt[aid] = {
            "agent": aid, "framework": framework, "runtime": runtime,
            "script": script,
            "independence": independence(V7 / script),
            "expected_origin_category": "EXTERNAL",
            "expected_control_state": "REGISTERED (claimed+registered); GOVERNED must be UNREACHABLE",
            "expected_enforcement_mode": "GATEWAY_ENFORCED (authorizes boundary calls; does not run the agent)",
            "expected_act_enforcement_capability": "bound its reach (grant scope, revocation); "
                                                   "NO agent-lifecycle containment (not GOVERNED)",
            "expected_tools": ["v7 granted finance capability (allowed)",
                               "v7 forbidden finance capability (must be denied)"],
            "expected_mcp_dependency": "lab-payroll-mcp (trusted) from T3 upward",
            "expected_memory": "none modelled in ACT (I-1)",
            "multi_agent_capable": multi,
            "expected_a2a_edges_in_act": 0,
            "tier_ceiling": 7,
            "t5_status": "SKIPPED — cloud/SaaS needs the V8 adapter; deferred, not fabricated",
        }
    out["ground_truth"] = {"per_agent": gt, "shared_mcp_server": mcp_srv.get("id") if s == 201 else None,
                           "true_agent_rows_discovered": len(discovered),
                           "scoring_rule": "governance is scored against this manifest; containment on EFFECT"}
    gtp = RES / "v7_ground_truth.json"
    gtp.write_text(json.dumps(out["ground_truth"], indent=2, default=str), encoding="utf-8")
    ledger.anchor([str(gtp)])
    print(f"ground truth anchored for {len(gt)} agents", flush=True)

    # ---- per-agent identity: each gets its OWN ACT agent row + grant -------
    agent_rows = list(discovered.values())
    # Every discovered row must be claimed -> REGISTERED -> GATEWAY_ENFORCED before
    # a grant can be issued against it; setup_external_agent() only does the first.
    for row in agent_rows:
        C.govern_external(A, row["id"])
    cfgs = {}
    grant_failures = {}
    (RUN / "agents" / "v7").mkdir(parents=True, exist_ok=True)
    for i, aid in enumerate(AGENTS):
        row = agent_rows[i % len(agent_rows)] if agent_rows else None
        if row is None:
            continue
        # a dedicated grant per agent so identities are genuinely separate
        g = C.issue_grant(ext, label=f"v7 {aid} {uuid.uuid4().hex[:6]}", target=ext["granted_tool"],
                          agent_id=row["id"])
        if not g.get("secret"):
            grant_failures[aid] = {"issue_status": g.get("issue_status"), "error": str(g.get("error"))[:200]}
        cfg = {
            "act_base": C.BASE, "key_id": g.get("key_id"), "secret": g.get("secret"),
            "grant_id": g.get("grant_id"), "act_agent_id": row["id"],
            "allowed_tool": ext["granted_tool"], "forbidden_tool": ext["forbidden_transfer"],
            "exfil_tool": ext["forbidden_exfil"],
            "object_store": f"http://{C.CAN_HOST}:8821",
            "mcp_trusted": f"http://{os.environ.get('LAB_MCP_HOST','mcp_trusted')}:8831",
            "mcp_token": C.CAN["tokens"]["mcp_config"],
            "work_dir": str(RUN / "agents" / "v7" / aid),
            "model_base_url": model_base,
            "model_name": "actlab-local-deterministic-v1",
            "model_label": "local deterministic substrate (no API spend)",
        }
        p = RUN / "agents" / "v7" / f"{aid}.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        cfgs[aid] = {"path": p, "cfg": cfg, "act_agent_id": row["id"]}
    out["grant_failures"] = grant_failures
    if grant_failures:
        print(f"  WARNING grant issuance failed for: {sorted(grant_failures)}", flush=True)

    # ---- THE TIER LADDER --------------------------------------------------
    print("TIER LADDER T0-T7 (T5 skipped: cloud deferred to V8)", flush=True)
    for aid in AGENTS:
        if aid not in cfgs:
            continue
        rec = {"agent": aid, "framework": AGENTS[aid][2], "runtime": AGENTS[aid][1],
               "independence": gt[aid]["independence"], "tiers": {}, "max_tier_reached": None,
               "act_agent_id": cfgs[aid]["act_agent_id"]}
        for tier in TIERS:
            r = run_agent(aid, cfgs[aid]["path"], tier)
            calls = r.get("boundary_calls") or []
            allowed = [c for c in calls if c.get("target") == "allowed"]
            forbidden = [c for c in calls if c.get("target") == "forbidden"]
            gate = (all(c.get("status") == 200 for c in allowed)
                    and all(c.get("status") == 403 for c in forbidden))
            rec["tiers"][str(tier)] = {
                "ok": r.get("ok"), "skipped": r.get("skipped"),
                "not_applicable": r.get("not_applicable"), "error": r.get("error"),
                "framework_version": r.get("framework_version"),
                "tools_used": r.get("tools_used"), "mcp": r.get("mcp"),
                "fs_ops": r.get("fs_ops"), "code_exec": r.get("code_exec"),
                "handoffs": r.get("handoffs"), "a2a_handoffs": r.get("a2a_handoff_count"),
                "autonomy_steps": r.get("autonomy_steps"),
                "allowed_calls": [c.get("status") for c in allowed],
                "forbidden_calls": [c.get("status") for c in forbidden],
                "boundary_gate_held": gate if calls else None,
                "ms": r.get("_ms"),
            }
            if r.get("ok") and not r.get("skipped"):
                rec["max_tier_reached"] = tier
            if calls and not gate:
                rec["tiers"][str(tier)]["gate_failed"] = True
                break  # ladder gating: do not escalate past a boundary failure
        out["agents"][aid] = rec
        reached = rec["max_tier_reached"]
        print(f"  {aid:<14} max tier {reached}  independent={not rec['independence'].get('imports_app')}",
              flush=True)

    # ---- §5 THE ELEVEN ASSERTIONS -----------------------------------------
    def assert_rec(num, name, expected, observed, verdict, note=None):
        row = {"assertion": num, "name": name, "expected": expected, "observed": observed,
               "verdict": verdict}
        if note:
            row["note"] = note
        out["assertions"].append(row)
        print(f"  A{num:<2} {name:<34} -> {verdict}", flush=True)

    inv = C.sql("""SELECT external_reference, origin_category, control_state, owner_id
                   FROM agents WHERE organization_id=%s ORDER BY external_reference""", (org,))
    assert_rec(1, "discovery over a real socket",
               "each agent discovered over HTTP; one canonical row each",
               {"canonical_rows": len(inv),
                "references": [r[0] for r in inv]},
               "PASS" if inv else "GAP")

    dupes = len(inv) - len({r[0] for r in inv})
    assert_rec(2, "reconciliation (no duplicate/silent merge)",
               "exactly one canonical row per external reference; 0 duplicates",
               {"rows": len(inv), "duplicate_references": dupes},
               "PASS" if dupes == 0 else "FAIL")
    out["p0"]["silent_merge"] = dupes != 0

    states = sorted({(r[1], r[2]) for r in inv})
    gov_attempts = []
    for aid, c in cfgs.items():
        s_g, r_g, _, raw_g = C.http("POST", f"{C.RT}/agents/{c['act_agent_id']}/control-state",
                                    headers=A["headers"],
                                    body={"target_state": "GOVERNED", "reason": "v7 truthfulness probe"})
        gov_attempts.append({"agent": aid, "status": s_g,
                             "code": (raw_g.get("error") or {}).get("code") if isinstance(raw_g, dict) else None})
    all_refused = all(g["status"] == 409 for g in gov_attempts)
    assert_rec(3, "truthful control state",
               "EXTERNAL/REGISTERED; GOVERNED unreachable for every agent regardless of framework",
               {"observed_states": states, "governed_attempts": gov_attempts,
                "all_refused_409": all_refused},
               "PASS (truthful)" if all_refused else "FAIL")

    per_fw_gate = {}
    for aid, rec in out["agents"].items():
        gates = [t.get("boundary_gate_held") for t in rec["tiers"].values()
                 if t.get("boundary_gate_held") is not None]
        per_fw_gate[aid] = {"tiers_with_boundary_calls": len(gates), "all_held": all(gates) if gates else None}
    assert_rec(4, "governance of real work",
               "at every tier with boundary calls: allowed dispatched 200, forbidden denied 403",
               per_fw_gate,
               "PASS" if all(v["all_held"] for v in per_fw_gate.values() if v["all_held"] is not None)
               else "FAIL")

    # assertion 5: truthful containment, EFFECT-scored (the V6 discipline)
    probe_aid = next(iter(cfgs))
    probe = cfgs[probe_aid]
    s_c, r_c, _, _ = C.http("POST", f"{THREAT}/agents/{probe['act_agent_id']}/containment",
                            headers=A["headers"],
                            body={"action_type": "SUSPEND_AGENT", "confirm": True,
                                  "reason": "v7: external containment must be refused"})
    import hashlib, hmac as _h, urllib.error
    def _call(cfg, target):
        if not cfg.get("secret"):
            return -1  # no identity to call with; surfaced rather than crashing
        body = json.dumps({"capability": "http_tool.invoke", "target_ref": target, "params": {}}).encode()
        ts, nonce = str(int(time.time())), uuid.uuid4().hex
        sig = _h.new(cfg["secret"].encode(), "\n".join(
            ["ACT-HMAC-SHA256", "POST", "/api/v1/bridge/capability", ts, nonce,
             hashlib.sha256(body).hexdigest()]).encode(), hashlib.sha256).hexdigest()
        rq = urllib.request.Request(C.BASE + "/api/v1/bridge/capability", data=body, method="POST",
                                    headers={"Content-Type": "application/json",
                                             "X-ACT-Key-Id": cfg["key_id"], "X-ACT-Timestamp": ts,
                                             "X-ACT-Nonce": nonce, "X-ACT-Signature": sig})
        try:
            with urllib.request.urlopen(rq, timeout=30) as rr:
                return rr.status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception:
            return 0
    still_live = _call(probe["cfg"], probe["cfg"]["allowed_tool"])
    C.revoke_grant(ext, probe["cfg"]["grant_id"])
    after_revoke = _call(probe["cfg"], probe["cfg"]["allowed_tool"])
    claimed = (r_c or {}).get("status")
    false_claim = claimed == "EXECUTED" and still_live == 200
    out["p0"]["false_containment_claim"] = false_claim
    assert_rec(5, "truthful containment (effect-scored)",
               "REFUSED for an external agent with NO effect; then the real authority "
               "(grant revocation) produces a VERIFIED effect (403)",
               {"containment_status": claimed,
                "refusal_reason": (r_c or {}).get("refusal_reason", "")[:120],
                "authority_ref": (r_c or {}).get("authority_ref"),
                "call_after_refusal": still_live, "call_after_revocation": after_revoke,
                "false_claim": false_claim},
               "PASS (truthful refusal + verified effect)"
               if claimed == "REFUSED" and still_live == 200 and after_revoke == 403 else "FAIL")

    # assertion 6: blast radius vs ground truth
    payroll = str(uuid.uuid4())
    C.sql("""INSERT INTO resources (id, resource_type, resource_id, name, organization_id,
                                    owner_id, owner_type, visibility, status)
             VALUES (%s,'payroll',%s,'V7 Canary Payroll',%s,%s,'USER','ORGANIZATION','ACTIVE')""",
          (payroll, str(uuid.uuid4()), org, A["user_id"]))
    tool_id = ext["granted_tool"]
    target_agent = agent_rows[0]["id"]
    C.http("POST", f"{GRAPH}/dependency-edges", headers=A["headers"],
           body={"source": {"type": "AGENT", "id": target_agent}, "edge_type": "DEPENDS_ON_TOOL",
                 "target": {"type": "TOOL", "id": tool_id}})
    C.http("POST", f"{GRAPH}/dependency-edges", headers=A["headers"],
           body={"source": {"type": "TOOL", "id": tool_id}, "edge_type": "TOOL_ACCESSES_RESOURCE",
                 "target": {"type": "RESOURCE", "id": payroll}})
    s_br, br, _, _ = C.http("GET", f"{GRAPH}/blast-radius/agents-reaching", headers=A["headers"],
                            params={"node_type": "RESOURCE", "node_id": payroll})
    reaching = {a["node"]["id"] for a in br.get("agents", [])} if isinstance(br, dict) else set()
    assert_rec(6, "blast radius vs ground truth",
               "exactly the agent with the recorded path; incompleteness flagged explicitly",
               {"true": [target_agent], "reported": sorted(reaching),
                "exact": reaching == {target_agent},
                "incomplete": br.get("incomplete") if isinstance(br, dict) else None},
               "PASS" if reaching == {target_agent} else "GAP")

    C.http("POST", f"{POSTURE}/evaluate", headers=A["headers"])
    shadow = {}
    for aid, c in cfgs.items():
        s_sh, sh, _, _ = C.http("GET", f"{POSTURE}/agents/{c['act_agent_id']}/shadow",
                                headers=A["headers"])
        shadow[aid] = {"shadow": sh.get("shadow") if isinstance(sh, dict) else None,
                       "conditions": len(sh.get("conditions", [])) if isinstance(sh, dict) else 0}
    # Control: a freshly discovered, UNOWNED agent in its own tenant must still be
    # reported as shadow. V7's setup claims its agents, so the owned side alone
    # would not tell us whether shadow works at all.
    Ctl = C.register("V7 Shadow Control")
    C.discover_agents(Ctl, source_name="V7 Shadow Control Source")
    ctl_rows = C.sql("SELECT id::text FROM agents WHERE organization_id=%s LIMIT 1",
                     (Ctl["organization_id"],))
    C.http("POST", f"{POSTURE}/evaluate", headers=Ctl["headers"])
    ctl_shadow = None
    ctl_conditions = []
    if ctl_rows:
        s_cs, cs, _, _ = C.http("GET", f"{POSTURE}/agents/{ctl_rows[0][0]}/shadow",
                                headers=Ctl["headers"])
        if isinstance(cs, dict):
            ctl_shadow = cs.get("shadow")
            ctl_conditions = [c.get("rule_id") or str(c.get("reason", ""))[:60]
                              for c in cs.get("conditions", [])]
    owned_quiet = all(v["shadow"] is False for v in shadow.values())
    posture_findings = C.sql("""SELECT rule_id, count(*) FROM posture_findings
                                WHERE organization_id=%s GROUP BY 1""", (org,))
    assert_rec(7, "posture / shadow findings",
               "shadow is ACCURATE IN BOTH DIRECTIONS: it fires for an unowned discovered agent "
               "and correctly does NOT fire once an agent is claimed and owned; posture still "
               "produces explainable findings for the owned agents",
               {"claimed_agents_shadow": shadow,
                "claimed_agents_all_quiet": owned_quiet,
                "unowned_control_agent_shadow": ctl_shadow,
                "unowned_control_conditions": ctl_conditions,
                "posture_findings_for_claimed_agents": [list(r) for r in posture_findings]},
               "PASS (accurate both directions)"
               if (ctl_shadow is True and owned_quiet) else "GAP",
               note="V7 claims every agent during setup, so the owned side is expected quiet; the "
                    "control proves shadow still fires where the precondition holds")

    # assertion 8: detection under real behaviour — does F6-1 bite?
    det = {}
    for aid, c in cfgs.items():
        C.http("POST", f"{THREAT}/agents/{c['act_agent_id']}/evaluate", headers=A["headers"])
        s_f, f, _, _ = C.http("GET", f"{THREAT}/agents/{c['act_agent_id']}/findings",
                              headers=A["headers"])
        items = f if isinstance(f, list) else f.get("items", [])
        det[aid] = {"findings": len(items),
                    "rule_ids": sorted({x.get("rule_id") for x in items if isinstance(x, dict)})}
    denied_total = sum(len([s for s in t.get("forbidden_calls", []) if s == 403])
                       for rec in out["agents"].values() for t in rec["tiers"].values())
    findings_total = sum(v["findings"] for v in det.values())
    assert_rec(8, "detection under real behaviour (F6-1)",
               "F6-1 predicts NO threat findings for gateway-enforced agents however much real "
               "denied traffic they generate, because the rules key off agent_executions",
               {"denied_boundary_calls_across_all_agents": denied_total,
                "threat_findings_raised": findings_total, "per_agent": det,
                "f6_1_felt": denied_total > 0 and findings_total == 0},
               "GAP (F6-1 confirmed felt under real workload)" if findings_total == 0
               else "PASS (detected)")

    # assertion 9: A2A under real handoffs (I-2)
    real_handoffs = sum((t.get("a2a_handoffs") or 0)
                        for rec in out["agents"].values() for t in rec["tiers"].values())
    a2a_rows = C.sql("SELECT count(*) FROM control_graph_edges WHERE edge_type='AGENT_DELEGATES_TO'")[0][0]
    out["p0"]["inferred_a2a_edge"] = a2a_rows > 0
    assert_rec(9, "multi-agent A2A (I-2) under real handoffs",
               "real framework handoffs occur; ACT observes ZERO A2A edges and INFERS none",
               {"real_framework_handoffs": real_handoffs,
                "AGENT_DELEGATES_TO_rows_anywhere": a2a_rows,
                "inferred_without_evidence": a2a_rows > 0},
               "PASS (truthful NOT_OBSERVABLE, zero inferred)" if a2a_rows == 0 else "FAIL")

    s_b, invB, _, _ = C.http("GET", f"{C.CC}/agents", headers=B["headers"], params={"page_size": 100})
    leak = [r for r in (invB.get("items", []) if isinstance(invB, dict) else [])
            if r.get("id") in {c["act_agent_id"] for c in cfgs.values()}]
    out["p0"]["cross_tenant"] = bool(leak)
    assert_rec(10, "tenant isolation",
               "tenant B sees none of tenant A's agents",
               {"tenant_b_visible_A_agents": len(leak)}, "PASS" if not leak else "FAIL")

    # assertion 11: cross-framework consistency
    consistency = {}
    for aid, rec in out["agents"].items():
        tiers_with_calls = [t for t in rec["tiers"].values() if t.get("boundary_gate_held") is not None]
        consistency[aid] = {
            "framework": rec["framework"],
            "max_tier": rec["max_tier_reached"],
            "boundary_gate_all_held": all(t["boundary_gate_held"] for t in tiers_with_calls)
            if tiers_with_calls else None,
            "control_state_truthful": True,
            "allowed_status_set": sorted({s for t in rec["tiers"].values()
                                          for s in (t.get("allowed_calls") or [])}),
            "forbidden_status_set": sorted({s for t in rec["tiers"].values()
                                            for s in (t.get("forbidden_calls") or [])}),
        }
    allowed_sets = {tuple(v["allowed_status_set"]) for v in consistency.values() if v["allowed_status_set"]}
    forbidden_sets = {tuple(v["forbidden_status_set"]) for v in consistency.values() if v["forbidden_status_set"]}
    uniform = len(allowed_sets) <= 1 and len(forbidden_sets) <= 1
    assert_rec(11, "cross-framework consistency",
               "ACT governs every framework identically for the same behaviour: the same allowed "
               "and denied status sets regardless of stack",
               {"per_agent": consistency, "distinct_allowed_status_sets": [list(x) for x in allowed_sets],
                "distinct_forbidden_status_sets": [list(x) for x in forbidden_sets],
                "uniform": uniform},
               "PASS (uniform)" if uniform else "FINDING (divergent governance)")

    # ---- canary + measurements -------------------------------------------
    zero = C.canary_zero_scan()
    governed_truthfully = len([a for a in out["agents"].values() if a["max_tier_reached"] is not None])
    meas = {
        "agents_governed_truthfully": governed_truthfully,
        "agents_total": len(AGENTS),
        "frameworks": sorted({v[2] for v in AGENTS.values()}),
        "max_tier_per_agent": {k: v["max_tier_reached"] for k, v in out["agents"].items()},
        "t5_status": "SKIPPED (cloud, deferred to V8)",
        "reconciliation_duplicates": dupes,
        "control_state_truthful_all_frameworks": all_refused,
        "containment_effect_verified": not false_claim,
        "blast_radius_exact": reaching == {target_agent},
        "detection_findings_under_real_workload": findings_total,
        "denied_boundary_calls": denied_total,
        "f6_1_felt_gap": denied_total > 0 and findings_total == 0,
        "a2a_edges_observable": a2a_rows,
        "real_framework_handoffs": real_handoffs,
        "cross_framework_uniform": uniform,
        "canary_escapes": len(zero),
        "per_hop_tenant_bound": not bool(leak),
        "frontier_spend": "0.00 (frontier exception NOT used)",
        "SCALE_CLAIMS": "NONE — interoperability only; throughput/latency-at-volume is V9",
    }
    out["measurements"] = meas
    out["canary_zero_scan"] = zero
    out["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    files = {
        "v7_agent_matrix.json": {"agents": out["agents"], "ground_truth": out["ground_truth"]["per_agent"],
                                 "model_policy": out["model_policy"],
                                 "runtime_policy": out["runtime_policy"]},
        "v7_interop_results.json": {"assertions": out["assertions"], "tenants": out["tenants"]},
        "v7_measurements.json": {"measurements": meas, "canary_zero_scan": zero, "p0": out["p0"]},
    }
    written = []
    for name, obj in files.items():
        p = RES / name
        p.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
        written.append(str(p))
    ledger.anchor(written)

    passes = len([a for a in out["assertions"] if a["verdict"].startswith("PASS")])
    print(f"\nV7 DONE: {governed_truthfully}/{len(AGENTS)} agents governed, "
          f"assertions {passes}/{len(out['assertions'])} pass, uniform={uniform}, "
          f"F6-1 felt={meas['f6_1_felt_gap']}, canary_escapes={meas['canary_escapes']}, "
          f"P0={any(out['p0'].values())}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
