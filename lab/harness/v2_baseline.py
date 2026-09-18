"""V2 BASELINE OBSERVATION HARNESS (V2 §6) -- observe, measure, record. No attacks.

Drives ACT-under-test (http://127.0.0.1:8802, lab env, dedicated lab DB) through
the ten observations of §6 with the three Wave-1 agents at Tier 0-2, and writes
lab/run/results/v2_baseline.json plus per-step evidence files. Uses only the
public HTTP API, the three agent processes, and read-only SQL over the LAB DB
for the canary scan (plus one lab-side seed: the canary payroll Resource row,
exactly as the 5.10 proof seeds it). Imports nothing from ACT.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "lab"
RUN = LAB / "run"
RES = RUN / "results"
RES.mkdir(parents=True, exist_ok=True)
# Host mode (V2): loopback ports, ACT's venv, backend/ on disk. Wrapped mode (V2.1):
# in-network hostnames and the container's own interpreter (LAB_MODE=wrapped, set by the
# runner service). Only endpoints change between the two -- never what is observed.
MODE = os.environ.get("LAB_MODE", "host")
BACKEND = Path(os.environ.get("LAB_BACKEND_DIR", str(ROOT / "backend")))
PY = (sys.executable if MODE == "wrapped" else
      (str(BACKEND / ".venv" / "Scripts" / "python.exe") if os.name == "nt" else str(BACKEND / ".venv" / "bin" / "python")))
ENV_FILE = Path(os.environ.get("LAB_ENV_FILE", str(LAB / "env" / "act-lab.env")))
BASE = os.environ.get("ACT_BASE", "http://127.0.0.1:8802")
REG_HOST = os.environ.get("LAB_REGISTRY_HOST", "127.0.0.1")
CAN_HOST = os.environ.get("LAB_CANARY_HOST", "127.0.0.1")
MCP_HOST = os.environ.get("LAB_MCP_HOST", "127.0.0.1")
NODE = os.environ.get("LAB_NODE_BIN", "node")
RT, DISC, GRAPH, POSTURE, THREAT, BRIDGE, ASSURE, CC = ("/api/v1/runtime", "/api/v1/discovery", "/api/v1/graph",
                                                        "/api/v1/posture", "/api/v1/threat", "/api/v1/bridge",
                                                        "/api/v1/assurance", "/api/v1/command-center")
CAN = json.loads((RUN / "canaries.json").read_text(encoding="utf-8"))
PASSWORD = "L4b!Passw0rd#Synthetic"
LAB_DB = dict(host=os.environ.get("LAB_DB_HOST", "127.0.0.1"), port=int(os.environ.get("LAB_DB_PORT", "5433")),
              user="actlab", password="actlab-synthetic-pw", dbname="act_lab")

results: dict = {"mode": MODE, "act_base": BASE, "observations": {}, "measurements": {}, "findings": [],
                 "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def _unwrap(obj):
    if isinstance(obj, dict) and obj.get("success") is True and "data" in obj:
        return obj["data"]
    return obj


def http(method, path, headers=None, body=None, params=None):
    url = BASE + path
    if params:
        from urllib.parse import urlencode
        url += "?" + urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode(); status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode(); status = e.code
    ms = round((time.perf_counter() - t) * 1000, 1)
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = {"raw": raw[:500]}
    return status, _unwrap(parsed), ms, parsed


def register(org_name):
    email = f"lab_{uuid.uuid4().hex[:10]}@example.com"  # synthetic; .invalid is rejected by the validator
    s, b, _, _ = http("POST", "/auth/register", body={"organization_name": org_name, "name": "Lab Owner", "email": email, "password": PASSWORD})
    assert s == 201, (s, b)
    s, tok, _, _ = http("POST", "/api/v1/auth/login", body={"email": email, "password": PASSWORD})
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    s, me, _, _ = http("GET", "/api/v1/auth/me", headers=h)
    return {"headers": h, "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"], "email": email}


def obs(key, value):
    results["observations"][key] = value
    print(f"  {key}: {json.dumps(value)[:160]}", flush=True)


def finding(text):
    results["findings"].append(text)
    print(f"  FINDING: {text}", flush=True)


def sql(query, params=None, db=None):
    import psycopg2  # from ACT's venv; read-only use except the one documented seed
    conn = psycopg2.connect(**(db or LAB_DB)); cur = conn.cursor()
    cur.execute(query, params or ())
    rows = cur.fetchall() if cur.description else None
    conn.commit(); conn.close()
    return rows


def main() -> int:
    A = register("Lab Tenant A"); B = register("Lab Tenant B")
    hA = A["headers"]
    results["tenants"] = {"A": A["organization_id"], "B": B["organization_id"]}

    # ---- 1. DISCOVERY over a real socket ------------------------------------
    print("1. discovery", flush=True)
    s, src, ms, _ = http("POST", f"{DISC}/sources", headers=hA, body={
        "name": "Lab Wave-1 Registry", "adapter_key": "HTTP_AGENT_REGISTRY",
        "config": {"base_url": f"http://{REG_HOST}:8811", "allowed_hosts": [REG_HOST], "local_dev_hosts": [REG_HOST],
                   "allow_plaintext_http": True, "path": "/agents", "page_size": 10, "max_pages": 5}})
    assert s == 201, (s, src)
    s, run1, ms1, _ = http("POST", f"{DISC}/sources/{src['id']}/runs", headers=hA)
    assert s == 201, (s, run1)
    reg_reqs = (RUN / "registry_requests.jsonl").read_text(encoding="utf-8").strip().splitlines() if (RUN / "registry_requests.jsonl").exists() else []
    obs("discovery_first_sweep", {"agents_created": run1.get("agents_created"), "agents_linked": run1.get("agents_linked"), "status": run1.get("status"), "registry_requests_seen": len(reg_reqs), "ms": ms1})
    results["measurements"]["time_to_discover_ms"] = ms1
    if run1.get("agents_created") != 3:
        finding(f"expected 3 agents created on first sweep, got {run1.get('agents_created')}")

    # ---- 2. RECONCILIATION: second sweep links, never duplicates -------------
    print("2. reconciliation", flush=True)
    s, run2, ms2, _ = http("POST", f"{DISC}/sources/{src['id']}/runs", headers=hA)
    obs("discovery_second_sweep", {"agents_created": run2.get("agents_created"), "agents_linked": run2.get("agents_linked"), "ms": ms2})
    results["measurements"]["time_to_reconcile_ms"] = ms2
    rows = sql("SELECT id, name, external_reference, origin_category, origin_provider, control_state, owner_id FROM agents WHERE organization_id=%s ORDER BY name", (A["organization_id"],))
    agents = {r[2]: {"id": str(r[0]), "name": r[1], "origin_category": r[3], "origin_provider": r[4], "control_state": r[5], "owner_id": r[6]} for r in rows}
    obs("canonical_rows", {"count": len(agents), "duplicates": len(rows) - len({r[2] for r in rows})})
    results["measurements"]["reconciliation_precision"] = {"expected_rows": 3, "actual_rows": len(rows), "duplicates": len(rows) - len({r[2] for r in rows})}
    if len(rows) != 3 or run2.get("agents_created") != 0 or run2.get("agents_linked") != 3:
        finding("reconciliation did not produce exactly one canonical row per agent with 0 created / 3 linked on the second sweep")

    # ---- 3. TRUTHFUL CONTROL STATE: expected vs observed ---------------------
    print("3. control state", flush=True)
    cs = {}
    for ref, a in agents.items():
        s, snap, _, _ = http("GET", f"{RT}/agents/{a['id']}/control-state", headers=hA)
        s2, gov, _, raw = http("POST", f"{RT}/agents/{a['id']}/control-state", headers=hA, body={"target_state": "GOVERNED", "reason": "lab: must be refused"})
        code = (raw.get("error") or {}).get("code") if isinstance(raw, dict) else None
        cs[ref] = {"expected": "DISCOVERED", "observed": snap.get("control_state"), "origin": snap.get("origin_category"),
                   "governed_attempt": {"status": s2, "code": code}}
        if snap.get("control_state") != "DISCOVERED" or snap.get("origin_category") == "NATIVE":
            finding(f"{ref}: expected DISCOVERED/non-NATIVE, observed {snap.get('control_state')}/{snap.get('origin_category')}")
        if not (s2 == 409 and code == "CONTROL_STATE_ORIGIN_INCOMPATIBLE"):
            finding(f"{ref}: GOVERNED was not refused with CONTROL_STATE_ORIGIN_INCOMPATIBLE (got {s2} {code})")
    obs("control_state_before_claim", cs)

    # ---- 6/7 prep. POSTURE + DEPENDENCY GRAPH with the canary payroll path ---
    print("6. posture/shadow", flush=True)
    s, ev, ms_ev, _ = http("POST", f"{POSTURE}/evaluate", headers=hA)
    shadow = {}
    for ref, a in agents.items():
        s, sh, _, _ = http("GET", f"{POSTURE}/agents/{a['id']}/shadow", headers=hA)
        s, fnd, _, _ = http("GET", f"{POSTURE}/agents/{a['id']}/findings", headers=hA, params={"status": "OPEN"})
        rules = sorted({f["rule_id"] for f in (fnd if isinstance(fnd, list) else fnd.get("items", []))})
        shadow[ref] = {"shadow": sh.get("shadow"), "conditions": [c.get("rule_id") or c.get("reason", "")[:60] for c in sh.get("conditions", [])], "open_rules": rules}
        if not sh.get("shadow") or not sh.get("conditions"):
            finding(f"{ref}: unowned discovered agent not reported as shadow-with-conditions")
    obs("posture_shadow", shadow)
    results["measurements"]["posture_evaluate_ms"] = ms_ev
    results["measurements"]["finding_precision"] = {"agents_expected_shadow": 3, "agents_observed_shadow": sum(1 for v in shadow.values() if v["shadow"])}

    print("7. dependency graph + blast radius (canary payroll path)", flush=True)
    s, mcp_trusted, _, _ = http("POST", f"{GRAPH}/mcp-servers", headers=hA, body={
        "name": "lab-payroll-mcp", "provenance": "EXPLICIT", "trust_status": "APPROVED", "version": "1.0.0",
        "endpoint_reference": f"http://{MCP_HOST}:8831/mcp", "declared_capabilities": {"tools": ["payroll_read"]}})
    assert s == 201, (s, mcp_trusted)
    s, tool, _, _ = http("POST", f"{RT}/tools", headers=hA, body={"name": "payroll_read", "display_name": "Payroll Read", "tool_type": "FUNCTION"})
    assert s == 201, (s, tool)
    s, link, _, _ = http("POST", f"{GRAPH}/mcp-servers/{mcp_trusted['id']}/tools", headers=hA, body={"tool_id": tool["id"]})
    assert s == 201, (s, link)
    payroll = str(uuid.uuid4())
    sql("""INSERT INTO resources (id, resource_type, resource_id, name, organization_id, owner_id, owner_type, visibility, status)
           VALUES (%s,'payroll',%s,'Canary Payroll System (lab)',%s,%s,'USER','ORGANIZATION','ACTIVE')""",
        (payroll, str(uuid.uuid4()), A["organization_id"], A["user_id"]))
    py_id = agents[next(k for k in agents if "python" in k)]["id"]
    for body in ({"source": {"type": "AGENT", "id": py_id}, "edge_type": "DEPENDS_ON_MCP_SERVER", "target": {"type": "MCP_SERVER", "id": mcp_trusted["id"]}},
                 {"source": {"type": "AGENT", "id": py_id}, "edge_type": "DEPENDS_ON_TOOL", "target": {"type": "TOOL", "id": tool["id"]}},
                 {"source": {"type": "TOOL", "id": tool["id"]}, "edge_type": "TOOL_ACCESSES_RESOURCE", "target": {"type": "RESOURCE", "id": payroll}}):
        s, e, _, _ = http("POST", f"{GRAPH}/dependency-edges", headers=hA, body=body)
        assert s == 201, (s, e)
    s, reach, ms_br, _ = http("GET", f"{GRAPH}/blast-radius/agents-reaching", headers=hA, params={"node_type": "RESOURCE", "node_id": payroll})
    reaching = {a["node"]["id"] for a in reach.get("agents", [])}
    obs("blast_radius_payroll", {"python_agent_reaches_payroll": py_id in reaching, "agents_reaching": len(reaching), "ms": ms_br})
    results["measurements"]["blast_radius_latency_ms"] = ms_br
    if py_id not in reaching or len(reaching) != 1:
        finding("blast radius did not return exactly the python agent for the canary payroll path")

    # ---- MCP OBSERVABILITY BASELINE (G-3): registered vs live manifests ------
    print("N. MCP observability baseline", flush=True)
    s, recorded, _, _ = http("GET", f"{GRAPH}/mcp-servers/{mcp_trusted['id']}", headers=hA)
    manifests = {}
    for v, port in (("trusted", 8831), ("unknown", 8832), ("risky", 8833), ("impersonator", 8834), ("rugpull", 8835)):
        host = f"mcp_{v}" if MODE == "wrapped" else "127.0.0.1"
        with urllib.request.urlopen(f"http://{host}:{port}/manifest", timeout=5) as r:
            manifests[v] = json.loads(r.read().decode())
    s, listing, _, _ = http("GET", f"{GRAPH}/mcp-servers", headers=hA)
    results["mcp_baseline"] = {
        "act_recorded_fields": sorted(recorded.keys()),
        "act_recorded_trusted": recorded,
        "act_server_count_in_tenant": len(listing) if isinstance(listing, list) else listing.get("total"),
        "live_variants": {v: {"server": m["server"], "transport": m["transport"], "auth_required": m["auth_required"],
                              "tool_names": [t["name"] for t in m["tools"]], "tool_descriptions_sha256": m["tool_descriptions_sha256"]}
                          for v, m in manifests.items()},
        "not_captured_by_act": ["tool descriptions (text)", "tool description hash / version pin", "transport type (STDIO vs HTTP)",
                                "auth requirement", "post-approval change detection", "name collision with an unregistered server (impersonator)"],
        "name_collision": manifests["trusted"]["server"] == manifests["impersonator"]["server"],
    }
    obs("mcp_recorded_field_names", sorted(recorded.keys()))

    # ---- 4/5 prep. CLAIM -> REGISTERED -> GATEWAY_ENFORCED for all three ------
    print("4. claim / register / mode (truthful affordances)", flush=True)
    s, cap_a, _, _ = http("POST", f"{RT}/tools", headers=hA, body={
        "name": "lab_finance_purchase", "display_name": "Lab Finance (canary)", "tool_type": "HTTP",
        "endpoint_reference": f"http://{CAN_HOST}:8823/purchase",
        "http_config": {"allowed_hosts": [CAN_HOST], "allow_plaintext_http": True, "local_dev_hosts": [CAN_HOST], "method": "POST", "timeout_seconds": 10}})
    assert s == 201, (s, cap_a)
    s, cap_f, _, _ = http("POST", f"{RT}/tools", headers=hA, body={
        "name": "lab_finance_transfer", "display_name": "Lab Finance Transfer (canary, never granted)", "tool_type": "HTTP",
        "endpoint_reference": f"http://{CAN_HOST}:8823/transfer",
        "http_config": {"allowed_hosts": [CAN_HOST], "allow_plaintext_http": True, "local_dev_hosts": [CAN_HOST], "method": "POST", "timeout_seconds": 10}})
    assert s == 201, (s, cap_f)
    grants = {}; modes = {}
    for ref, a in agents.items():
        s, c, _, raw = http("POST", f"{RT}/agents/{a['id']}/claim", headers=hA, body={"owner_type": "USER", "owner_id": A["user_id"], "reason": "lab: adopt Wave-1 agent"})
        assert s == 200, (s, raw)
        s, r, _, raw = http("POST", f"{RT}/agents/{a['id']}/control-state", headers=hA, body={"target_state": "REGISTERED", "reason": "lab: in scope"})
        assert s == 200, (s, raw)
        s2, gov, _, raw2 = http("POST", f"{RT}/agents/{a['id']}/control-state", headers=hA, body={"target_state": "GOVERNED", "reason": "lab: must be refused"})
        s, m, _, _ = http("PUT", f"{BRIDGE}/agents/{a['id']}/enforcement-mode", headers=hA, body={"target_mode": "GATEWAY_ENFORCED", "reason": "lab: ACT authorizes its boundary calls"})
        assert s == 200, (s, m)
        modes[ref] = {"mode": m.get("enforcement_mode"), "reaches_boundary_calls": m.get("reaches_boundary_calls"), "reaches_agent_execution": m.get("reaches_agent_execution"),
                      "display": m.get("display"), "governed_attempt_after_register": {"status": s2, "code": (raw2.get("error") or {}).get("code")}}
        if m.get("reaches_agent_execution") is not False or "govern this agent" in (m.get("display") or "").lower():
            finding(f"{ref}: GATEWAY_ENFORCED affordance over-claims")
        if s2 != 409:
            finding(f"{ref}: GOVERNED reachable after REGISTERED (status {s2})")
        s, g, _, raw = http("POST", f"{BRIDGE}/agents/{a['id']}/grants", headers=hA, body={"label": CAN["tokens"]["grant_label"], "scope": [{"capability": "http_tool.invoke", "target_ref": cap_a["id"]}]})
        assert s == 201, (s, raw)
        grants[ref] = g
    obs("enforcement_modes", modes)

    # ---- 5. THE AGENTS RUN (Tier 0-2) in their own OS processes -------------
    print("5. Wave-1 agents run (T0-T2)", flush=True)
    (RUN / "agents").mkdir(exist_ok=True)
    agent_out = {}
    independence = {}
    for ref, a in agents.items():
        kind = "python" if "python" in ref else ("node" if "node" in ref else "mcp")
        cfg = {"act_base": BASE, "key_id": grants[ref]["grant"]["key_id"], "secret": grants[ref]["secret"], "tier": 2,
               "allowed_tool": cap_a["id"], "forbidden_tool": cap_f["id"], "object_store": f"http://{CAN_HOST}:8821",
               "mcp_trusted": f"http://{MCP_HOST}:8831", "mcp_token": CAN["tokens"]["mcp_config"],
               "canary": CAN["tokens"][f"agent_config_{'py' if kind=='python' else kind}"],
               "fake_credentials": CAN["fake_credentials"]}
        cfgp = RUN / "agents" / f"{kind}.json"; cfgp.write_text(json.dumps(cfg), encoding="utf-8")
        if kind == "node":
            src = (LAB / "agents" / "node_agent.js").read_text(encoding="utf-8")
            reqs = sorted(set(__import__("re").findall(r'require\("([^"]+)"\)', src)))
            # Independence = every require() is a node: built-in; nothing under backend/ or app.
            independence[kind] = {"requires_act": any(not r.startswith("node:") for r in reqs), "requires": reqs}
            cmd = [NODE, str(LAB / "agents" / "node_agent.js"), str(cfgp)]
        else:
            fn = "python_agent.py" if kind == "python" else "mcp_client.py"
            src = (LAB / "agents" / fn).read_text(encoding="utf-8")
            imported = set()
            for node in ast.walk(ast.parse(src)):
                if isinstance(node, ast.Import): imported.update(x.name for x in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module: imported.add(node.module)
            independence[kind] = {"imports_app": any(m.split(".")[0] == "app" for m in imported), "imports": sorted(imported)}
            cmd = [sys.executable, str(LAB / "agents" / fn), str(cfgp)]
        t = time.perf_counter()
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=str(LAB))
        agent_out[kind] = {"rc": p.returncode, "out": json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 and p.stdout.strip() else p.stderr[-500:], "ms": round((time.perf_counter() - t) * 1000)}
        o = agent_out[kind]["out"]
        if isinstance(o, dict):
            al = o.get("t2_allowed"); fb = o.get("t2_forbidden")
            if al and not (al[0] == 200 and al[1].get("outcome") == "ALLOWED" and al[1].get("dispatch_status") == "DISPATCHED"):
                finding(f"{kind}: T2 allowed call did not dispatch: {al}")
            if fb and not (fb[0] == 403 and fb[1].get("outcome") == "DENIED"):
                finding(f"{kind}: forbidden call not denied: {fb}")
        else:
            finding(f"{kind} agent process failed: {o}")
    obs("agent_runs", {k: {"rc": v["rc"], "ms": v["ms"], "summary": {kk: (vv if not isinstance(vv, list) else vv[0]) for kk, vv in (v["out"].items() if isinstance(v["out"], dict) else [])}} for k, v in agent_out.items()})
    obs("agent_independence", independence)
    finance_log = (RUN / "canary_zone" / "finance.jsonl")
    dispatched = len(finance_log.read_text(encoding="utf-8").strip().splitlines()) if finance_log.exists() else 0
    obs("capability_dispatches_reached_canary_finance", dispatched)

    # ---- 5b. TRUTHFUL CONTAINMENT: refusal, then the real revocation -------
    print("5b. truthful containment", flush=True)
    http("POST", f"{THREAT}/agents/{py_id}/evaluate", headers=hA)
    s, kill, _, raw = http("POST", f"{THREAT}/agents/{py_id}/containment", headers=hA, body={"action_type": "SUSPEND_AGENT", "confirm": True, "reason": "lab: baseline refusal check"})
    contain = {"status_code": s, "status": kill.get("status"), "refusal_reason": kill.get("refusal_reason"), "authority_ref": kill.get("authority_ref")}
    if not (s in (200, 201) and kill.get("status") == "REFUSED" and "no enforcement authority" in (kill.get("refusal_reason") or "").lower()):
        finding(f"SUSPEND_AGENT on an external agent was not truthfully REFUSED: {contain}")
    py_ref = next(k for k in agents if "python" in k)
    s, rev, _, _ = http("POST", f"{BRIDGE}/grants/{grants[py_ref]['grant']['id']}/revoke", headers=hA, body={"reason": "lab: real containment ACT holds"})
    contain["revoke_status"] = s
    p = subprocess.run([sys.executable, str(LAB / "agents" / "python_agent.py"), str(RUN / "agents" / "python.json")], capture_output=True, text=True, timeout=120, cwd=str(LAB))
    after = json.loads(p.stdout.strip().splitlines()[-1])
    contain["allowed_call_after_revoke"] = after["t2_allowed"][0]
    dispatched2 = len(finance_log.read_text(encoding="utf-8").strip().splitlines()) if finance_log.exists() else 0
    contain["dispatches_after_revoke_delta"] = dispatched2 - dispatched
    if after["t2_allowed"][0] != 403 or dispatched2 != dispatched:
        finding("revoked grant still dispatched")
    obs("truthful_containment", contain)

    # ---- 12/13. ASSURANCE + COMMAND CENTER affordances -----------------------
    print("13. assurance + command center", flush=True)
    s, ev, _, _ = http("POST", f"{ASSURE}/agents/{py_id}/evaluate", headers=hA)
    res = {r["control_id"]: r["result"] for r in ev} if isinstance(ev, list) else ev
    obs("assurance_python_agent", res)
    s, inv, _, _ = http("GET", f"{CC}/agents", headers=hA, params={"page_size": 200})
    cc = {}
    for ref, a in agents.items():
        row = next((r for r in inv.get("items", []) if r["id"] == a["id"]), None)
        cc[ref] = None if row is None else {"enforcement_mode": row.get("enforcement_mode"), "reaches_agent_execution": row.get("reaches_agent_execution"), "display": row.get("enforcement_display")}
        if row and (row.get("reaches_agent_execution") is not False or "govern this agent" in (row.get("enforcement_display") or "").lower()):
            finding(f"{ref}: command center over-claims")
    obs("command_center_rows", cc)

    # ---- 8. TENANT ISOLATION -------------------------------------------------
    print("8. tenant isolation", flush=True)
    s, invB, _, _ = http("GET", f"{CC}/agents", headers=B["headers"], params={"page_size": 200})
    leak = [r["id"] for r in invB.get("items", []) if r["id"] in {a["id"] for a in agents.values()}]
    s404 = [http("GET", f"{BRIDGE}/agents/{a['id']}/enforcement-mode", headers=B["headers"])[0] for a in agents.values()]
    obs("tenant_isolation", {"tenant_B_sees_A_agents": leak, "tenant_B_mode_lookups": s404})
    if leak or any(x != 404 for x in s404):
        finding("cross-tenant visibility")

    # ---- 9. AUDIT + CANARY SCAN ----------------------------------------------
    print("9. audit + canary scan", flush=True)
    events = {r[0] for r in sql("SELECT DISTINCT event_type FROM authorization_audit WHERE organization_id=%s", (A["organization_id"],))}
    expected = {"DISCOVERY_RUN_STARTED", "RUNTIME_AGENT_CLAIMED", "RUNTIME_AGENT_CONTROL_STATE_CHANGED", "RUNTIME_AGENT_CONTROL_STATE_REJECTED",
                "EXTERNAL_ENFORCEMENT_MODE_CHANGED", "EXTERNAL_GRANT_ISSUED", "EXTERNAL_GATEWAY_CALL_ALLOWED", "EXTERNAL_GATEWAY_CALL_DENIED",
                "EXTERNAL_GRANT_REVOKED", "CONTAINMENT_ACTION_REFUSED", "ASSURANCE_EVALUATED", "POSTURE_EVALUATED"}
    obs("audit_events", {"present": sorted(events & expected), "missing": sorted(expected - events)})
    tokens = list(CAN["tokens"].values()) + [p["canary"] for p in CAN["pii"]] + list(CAN["fake_credentials"].values())
    marker = CAN["grep_marker"]
    scan = {"db_hits": {}, "act_log_hits": 0, "otlp_hits": 0}
    cols = sql("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public' AND data_type IN ('text','character varying','json','jsonb')")
    for t, c in cols:
        n = sql(f'SELECT count(*) FROM "{t}" WHERE "{c}"::text LIKE %s', (f"%{marker}%",))[0][0]
        if n:
            scan["db_hits"][f"{t}.{c}"] = n
    act_log = RUN / "logs" / "act.log"
    if act_log.exists():
        txt = act_log.read_text(encoding="utf-8", errors="replace"); scan["act_log_hits"] = txt.count(marker)
    for f in (RUN / "otlp").glob("*.jsonl") if (RUN / "otlp").exists() else []:
        scan["otlp_hits"] += f.read_text(encoding="utf-8", errors="replace").count(marker)
    scan["tokens_checked"] = len(tokens)
    scan["expected_hits_in_act"] = {"grant_label": "the grant label token is deliberately stored by ACT (an operator-supplied label) - listed, not a leak"}
    obs("canary_scan", scan)
    # The grant-label token is operator input ACT is REQUIRED to record (the grant
    # row and its EXTERNAL_GRANT_ISSUED audit meta); every other token must be absent.
    unexpected = {}
    for k, v in scan["db_hits"].items():
        t, c = k.split(".")
        hit_tokens = {name for name, tok in CAN["tokens"].items()
                      if sql(f'SELECT count(*) FROM "{t}" WHERE "{c}"::text LIKE %s', (f"%{tok}%",))[0][0]}
        if hit_tokens - {"grant_label"}:
            unexpected[k] = sorted(hit_tokens)
    scan["db_hit_tokens"] = {k: "grant_label (expected)" for k in scan["db_hits"]} | unexpected
    if unexpected or scan["act_log_hits"] or scan["otlp_hits"]:
        finding(f"canary tokens found in ACT records: {unexpected} log={scan['act_log_hits']} otlp={scan['otlp_hits']}")

    # ---- 10. M4.11 lab key material ------------------------------------------
    print("10. M4.11 lab keys", flush=True)
    env = {k: v for k, v in os.environ.items()}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1); env[k] = v
    ok = subprocess.run([PY, "-m", "app.security.keys", "verify"], cwd=str(BACKEND), env=env, capture_output=True, text=True)
    bad_env = dict(env, SIGNING_KEY_PATH=str(RUN / "no-such-keys/"), MODEL_CREDENTIAL_ENCRYPTION_KEY_PATH=str(RUN / "no-such-keys/model_credentials.key"))
    bad = subprocess.run([PY, "-m", "app.security.keys", "verify"], cwd=str(BACKEND), env=bad_env, capture_output=True, text=True)
    status = subprocess.run([PY, "-m", "app.security.keys", "status"], cwd=str(BACKEND), env=env, capture_output=True, text=True)
    keys = {"verify_with_lab_keys_rc": ok.returncode, "verify_with_missing_keys_rc": bad.returncode,
            "missing_keys_message": (bad.stdout + bad.stderr).strip()[-300:], "status": status.stdout.strip()[-400:],
            "secret_leak_check": any(s in (ok.stdout + ok.stderr + bad.stdout + bad.stderr + status.stdout) for s in ("BEGIN PRIVATE KEY", "gAAAA"))}
    obs("m411_lab_keys", keys)
    if ok.returncode != 0 or bad.returncode == 0 or keys["secret_leak_check"]:
        finding("M4.11 lab-key behaviour not fail-loud or leaked material")

    results["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    (RES / "v2_baseline.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nDONE: {len(results['findings'])} finding(s). Results -> {RES / 'v2_baseline.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
