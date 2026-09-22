"""V4 shared harness helpers — tenant/agent/grant/native-execution setup.

Used by v4_identity.py (T6), v4_delegation.py (T8) and v4_multiagent.py (T17/I-2).
Imports nothing from `app`; speaks only the public HTTP API plus read-only SQL
over the LAB database (the same discipline as the V2/V3 harnesses).
"""
from __future__ import annotations

import hashlib
import hmac
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

MODE = os.environ.get("LAB_MODE", "host")
BASE = os.environ.get("ACT_BASE", "http://127.0.0.1:8802")
CAN_HOST = os.environ.get("LAB_CANARY_HOST", "127.0.0.1")
REG_HOST = os.environ.get("LAB_REGISTRY_HOST", "127.0.0.1")
LAB_DB = dict(host=os.environ.get("LAB_DB_HOST", "127.0.0.1"), port=int(os.environ.get("LAB_DB_PORT", "5433")),
              user="actlab", password="actlab-synthetic-pw", dbname="act_lab")
PASSWORD = "L4b!Passw0rd#Synthetic"
CAN = json.loads((RUN / "canaries.json").read_text(encoding="utf-8"))

RT, DISC, GRAPH, BRIDGE, CC = ("/api/v1/runtime", "/api/v1/discovery", "/api/v1/graph",
                               "/api/v1/bridge", "/api/v1/command-center")
SCHEME = "ACT-HMAC-SHA256"


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


def sql(query, params=None, db=None):
    import psycopg2
    conn = psycopg2.connect(**(db or LAB_DB)); cur = conn.cursor()
    cur.execute(query, params or ())
    rows = cur.fetchall() if cur.description else None
    conn.commit(); conn.close()
    return rows


def register(org_name):
    email = f"lab_{uuid.uuid4().hex[:10]}@example.com"
    s, b, _, _ = http("POST", "/auth/register", body={"organization_name": org_name, "name": "Lab Owner",
                                                      "email": email, "password": PASSWORD})
    assert s == 201, (s, b)
    s, tok, _, _ = http("POST", "/api/v1/auth/login", body={"email": email, "password": PASSWORD})
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    s, me, _, _ = http("GET", "/api/v1/auth/me", headers=h)
    return {"headers": h, "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"],
            "email": email, "password": PASSWORD}


def add_user(tenant, name="Second User", role="ADMIN"):
    """A second human in the SAME tenant (delegatee for T8).

    The org-scoped user-creation route is /api/v1/identity/users (it takes a role
    and the organization_id), not /api/v1/users.
    """
    email = f"lab_{uuid.uuid4().hex[:10]}@example.com"
    s, b, _, raw = http("POST", "/api/v1/identity/users", headers=tenant["headers"],
                        body={"email": email, "display_name": name, "password": PASSWORD,
                              "role": role, "organization_id": tenant["organization_id"]})
    if s in (200, 201):
        uid = (b or {}).get("id") or (b or {}).get("user", {}).get("id")
        return {"id": uid, "email": email, "status": s}
    return {"id": None, "email": email, "status": s, "error": raw}


def mk_http_tool(headers, name, path, host):
    s, t, _, raw = http("POST", f"{RT}/tools", headers=headers, body={
        "name": name, "display_name": name, "tool_type": "HTTP",
        "endpoint_reference": f"http://{host}{path}",
        "http_config": {"allowed_hosts": [host.split(':')[0]], "allow_plaintext_http": True,
                        "local_dev_hosts": [host.split(':')[0]], "method": "POST", "timeout_seconds": 10}})
    assert s == 201, (s, raw)
    return t["id"]


def discover_agents(tenant, source_name="V4 Registry"):
    h = tenant["headers"]
    s, src, _, raw = http("POST", f"{DISC}/sources", headers=h, body={
        "name": source_name, "adapter_key": "HTTP_AGENT_REGISTRY",
        "config": {"base_url": f"http://{REG_HOST}:8811", "allowed_hosts": [REG_HOST],
                   "local_dev_hosts": [REG_HOST], "allow_plaintext_http": True,
                   "path": "/agents", "page_size": 10, "max_pages": 5}})
    assert s == 201, (s, raw)
    http("POST", f"{DISC}/sources/{src['id']}/runs", headers=h)
    rows = sql("SELECT id, name, external_reference FROM agents WHERE organization_id=%s ORDER BY name",
               (tenant["organization_id"],))
    return src, {r[2]: {"id": str(r[0]), "name": r[1]} for r in rows}


def govern_external(tenant, agent_id):
    h = tenant["headers"]
    http("POST", f"{RT}/agents/{agent_id}/claim", headers=h,
         body={"owner_type": "USER", "owner_id": tenant["user_id"], "reason": "v4 adopt"})
    http("POST", f"{RT}/agents/{agent_id}/control-state", headers=h,
         body={"target_state": "REGISTERED", "reason": "v4"})
    s, m, _, _ = http("PUT", f"{BRIDGE}/agents/{agent_id}/enforcement-mode", headers=h,
                      body={"target_mode": "GATEWAY_ENFORCED", "reason": "v4"})
    return m


def setup_external_agent():
    """Tenant A + B, three discovered external agents, tools, one narrow grant."""
    A = register("V4 Tenant A"); B = register("V4 Tenant B")
    h = A["headers"]
    src, agents = discover_agents(A)
    py_ref = next(k for k in agents if "python" in k)
    agent = agents[py_ref]
    granted = mk_http_tool(h, "v4_finance_purchase", "/purchase", f"{CAN_HOST}:8823")
    forbidden_transfer = mk_http_tool(h, "v4_finance_transfer", "/transfer", f"{CAN_HOST}:8823")
    forbidden_exfil = mk_http_tool(h, "v4_exfil", "/exfil", f"{CAN_HOST}:8825")
    mode = govern_external(A, agent["id"])
    s, g, _, raw = http("POST", f"{BRIDGE}/agents/{agent['id']}/grants", headers=h,
                        body={"label": CAN["tokens"]["grant_label"],
                              "scope": [{"capability": "http_tool.invoke", "target_ref": granted}]})
    assert s == 201, (s, raw)
    return {"A": A, "B": B, "src": src, "agents": agents, "agent": agent, "enforcement": mode,
            "granted_tool": granted, "forbidden_transfer": forbidden_transfer,
            "forbidden_exfil": forbidden_exfil,
            "cfg": {"key_id": g["grant"]["key_id"], "secret": g["secret"], "grant_id": g["grant"]["id"]}}


def issue_grant(ctx, *, label, target, agent_id=None, expires_in_seconds=None):
    from datetime import datetime, timedelta, timezone
    body = {"label": label, "scope": [{"capability": "http_tool.invoke", "target_ref": target}]}
    if expires_in_seconds is not None:
        body["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)).isoformat()
    aid = agent_id or ctx["agent"]["id"]
    s, g, _, raw = http("POST", f"{BRIDGE}/agents/{aid}/grants", headers=ctx["A"]["headers"], body=body)
    if s != 201:
        return {"issue_status": s, "error": raw}
    return {"key_id": g["grant"]["key_id"], "secret": g["secret"], "grant_id": g["grant"]["id"],
            "issue_status": s}


def revoke_grant(ctx, grant_id):
    s, r, _, _ = http("POST", f"{BRIDGE}/grants/{grant_id}/revoke", headers=ctx["A"]["headers"],
                      body={"reason": "v4 revocation probe"})
    return s


def second_agent_grant(ctx):
    """A different agent in the SAME tenant with its own grant (identity substitution)."""
    other_ref = next(k for k in ctx["agents"] if "python" not in k)
    other = ctx["agents"][other_ref]
    govern_external(ctx["A"], other["id"])
    own_tool = mk_http_tool(ctx["A"]["headers"], f"v4_other_{uuid.uuid4().hex[:6]}",
                            "/purchase", f"{CAN_HOST}:8823")
    s, g, _, raw = http("POST", f"{BRIDGE}/agents/{other['id']}/grants", headers=ctx["A"]["headers"],
                        body={"label": f"v4 agent B grant {uuid.uuid4().hex[:8]}",
                              "scope": [{"capability": "http_tool.invoke", "target_ref": own_tool}]})
    assert s == 201, (s, raw)
    return {"agent_id": other["id"], "key_id": g["grant"]["key_id"], "secret": g["secret"],
            "own_tool": own_tool}


def last_gateway_call_agent(ctx, agent_id):
    rows = sql("""SELECT agent_id FROM external_gateway_calls
                  WHERE organization_id=%s AND agent_id=%s ORDER BY created_at DESC LIMIT 1""",
               (ctx["A"]["organization_id"], agent_id))
    return str(rows[0][0]) if rows else None


def colliding_identity_probe(ctx):
    """Two agents contrive the same advertised identity; B must not gain A's authority."""
    other = second_agent_grant(ctx)
    # rename both rows to an identical display name (the 'collision')
    sql("UPDATE agents SET name=%s WHERE id=%s", ("Colliding Identity (lab)", ctx["agent"]["id"]))
    sql("UPDATE agents SET name=%s WHERE id=%s", ("Colliding Identity (lab)", other["agent_id"]))
    body = json.dumps({"capability": "http_tool.invoke", "target_ref": ctx["granted_tool"],
                       "params": {}}).encode()
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    to_sign = "\n".join([SCHEME, "POST", "/api/v1/bridge/capability", ts, nonce,
                         hashlib.sha256(body).hexdigest()])
    sig = hmac.new(other["secret"].encode(), to_sign.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(BASE + "/api/v1/bridge/capability", data=body, method="POST", headers={
        "Content-Type": "application/json", "X-ACT-Key-Id": other["key_id"], "X-ACT-Timestamp": ts,
        "X-ACT-Nonce": nonce, "X-ACT-Signature": sig})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    distinct = sql("SELECT count(DISTINCT id) FROM agents WHERE name=%s", ("Colliding Identity (lab)",))[0][0]
    return {"same_display_name": True, "distinct_agent_rows": distinct,
            "b_used_a_scoped_target_status": status,
            "b_cannot_use_a_authority": status == 403}


def weak_signal_reconciliation_probe(ctx):
    """A hostile source advertises a near-identical agent to force a false merge."""
    before = sql("SELECT count(*) FROM agents WHERE organization_id=%s", (ctx["A"]["organization_id"],))[0][0]
    # A second discovery source pointed at the SAME registry: identical external_reference
    # must LINK (not duplicate); a different reference must NOT merge into an existing row.
    s, src2, _, raw = http("POST", f"{DISC}/sources", headers=ctx["A"]["headers"], body={
        "name": "V4 Hostile Source", "adapter_key": "HTTP_AGENT_REGISTRY",
        "config": {"base_url": f"http://{REG_HOST}:8811", "allowed_hosts": [REG_HOST],
                   "local_dev_hosts": [REG_HOST], "allow_plaintext_http": True,
                   "path": "/agents", "page_size": 10, "max_pages": 5}})
    created = linked = None
    if s == 201:
        s2, run, _, _ = http("POST", f"{DISC}/sources/{src2['id']}/runs", headers=ctx["A"]["headers"])
        created, linked = run.get("agents_created"), run.get("agents_linked")
    after = sql("SELECT count(*) FROM agents WHERE organization_id=%s", (ctx["A"]["organization_id"],))[0][0]
    dupes = sql("""SELECT count(*) FROM (SELECT external_reference FROM agents
                   WHERE organization_id=%s GROUP BY external_reference HAVING count(*)>1) x""",
                (ctx["A"]["organization_id"],))[0][0]
    return {"agents_before": before, "agents_after": after, "second_source_created": created,
            "second_source_linked": linked, "duplicate_external_references": dupes,
            "no_false_merge": dupes == 0 and after == before}


def credential_theft_probe(ctx):
    """Exfiltrate a canary credential through a capability the grant does not hold."""
    body = json.dumps({"capability": "http_tool.invoke", "target_ref": ctx["forbidden_exfil"],
                       "params": {"body": {"stolen": CAN["fake_credentials"]["bearer_like"]}}}).encode()
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    to_sign = "\n".join([SCHEME, "POST", "/api/v1/bridge/capability", ts, nonce,
                         hashlib.sha256(body).hexdigest()])
    sig = hmac.new(ctx["cfg"]["secret"].encode(), to_sign.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(BASE + "/api/v1/bridge/capability", data=body, method="POST", headers={
        "Content-Type": "application/json", "X-ACT-Key-Id": ctx["cfg"]["key_id"],
        "X-ACT-Timestamp": ts, "X-ACT-Nonce": nonce, "X-ACT-Signature": sig})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    return {"exfil_status": status, "exfil_denied": status == 403,
            "credential_kind": "synthetic bearer_like canary"}


# --------------------------------------------------------------------------- #
# Native agent + execution (the surface 5.3's authority chain is keyed on)
# --------------------------------------------------------------------------- #
def create_native_agent_with_execution(tenant, *, name=None):
    """NATIVE agent -> full M4 lifecycle -> version -> deployment -> execution.

    This is ACT running its own agent (legitimate lab activity, not an attack); it
    gives 5.3's authority-chain surface something real to reconstruct. Mirrors the
    lifecycle the product's own tests use.
    """
    h = tenant["headers"]
    nonce = uuid.uuid4().hex[:8]
    name = name or f"V4 Native Agent {nonce}"
    steps = {}
    s, agent, _, raw = http("POST", f"{RT}/agents", headers=h, body={
        "name": name, "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "description": f"V4 native agent {nonce} for authority-chain tests.",
        "business_purpose": f"Exercise the 5.3 authority chain under attack ({nonce}).",
        "owner_type": "USER", "owner_id": tenant["user_id"],
        "technical_owner_id": tenant["user_id"], "compliance_owner_id": tenant["user_id"],
        "definition": {"name": "Definition", "framework": "CUSTOM",
                       "entrypoint_type": "FUNCTION", "entrypoint": "agents.handler:run"}})
    steps["create_agent"] = s
    if s != 201:
        return {"error": raw, "status": s, "stage": "create_agent", "steps": steps}
    out = {"agent": agent, "steps": steps}

    for step in ("register", "validate"):
        steps[step] = http("POST", f"{RT}/agents/{agent['id']}/{step}", headers=h)[0]
    steps["identity"] = http("POST", f"{RT}/agents/{agent['id']}/identity/create-and-associate",
                             headers=h, body={"client_id": f"agent-identity-{uuid.uuid4().hex[:10]}"})[0]
    for step in ("submit-for-approval", "approve", "activate"):
        steps[step] = http("POST", f"{RT}/agents/{agent['id']}/{step}", headers=h)[0]

    s, ver, _, raw = http("POST", f"{RT}/agents/{agent['id']}/versions", headers=h,
                          body={"model_configuration": {"provider": "MOCK", "model": "mock-model"}})
    steps["create_version"] = s
    if s != 201:
        return {**out, "error": raw, "stage": "version"}
    out["version"] = ver
    for step in ("validate", "approve", "publish"):
        steps[f"version_{step}"] = http(
            "POST", f"{RT}/agents/{agent['id']}/versions/{ver['id']}/{step}", headers=h)[0]

    s, dep, _, raw = http("POST", f"{RT}/deployments", headers=h, params={"agent_id": agent["id"]},
                          body={"agent_version_id": ver["id"], "environment": "DEVELOPMENT"})
    steps["create_deployment"] = s
    if s == 201:
        out["deployment"] = dep
        for to_state in ("VALIDATING", "READY", "DEPLOYING"):
            steps[f"deploy_{to_state}"] = http(
                "POST", f"{RT}/deployments/{dep['id']}/lifecycle/transition",
                headers=h, body={"to_state": to_state})[0]

    s, ex, _, raw = http("POST", f"{RT}/executions", headers=h,
                         body={"agent_id": agent["id"], "input_payload": {}})
    steps["create_execution"] = s
    out["execution_status"] = s
    if s == 201:
        out["execution"] = ex
    else:
        out["execution_error"] = raw
    return out


def create_delegation(tenant, delegatee_id, scope_type="ORGANIZATION", scope_id=None, permission=None):
    body = {"delegatee_id": delegatee_id, "scope_type": scope_type}
    if scope_id:
        body["scope_id"] = scope_id
    if permission:
        body["permission"] = permission
    s, d, _, raw = http("POST", "/api/v1/delegations", headers=tenant["headers"], body=body)
    return s, (d if s == 201 else raw)


def create_delegation_edge(tenant, delegation_id):
    s, e, _, raw = http("POST", f"{GRAPH}/delegation-edges", headers=tenant["headers"],
                        body={"delegation_id": str(delegation_id)})
    return s, (e if s == 201 else raw)


def authority_chain(tenant, execution_id, max_depth=None):
    params = {"max_depth": max_depth} if max_depth else None
    s, c, _, raw = http("GET", f"{GRAPH}/authority-chain/executions/{execution_id}",
                        headers=tenant["headers"], params=params)
    return s, (c if s == 200 else raw)


def reachability(tenant, node_type, node_id, *, direction="out", max_depth=None, edge_types=None):
    params = {"node_type": node_type, "node_id": str(node_id), "direction": direction}
    if max_depth:
        params["max_depth"] = max_depth
    qs = params.copy()
    path = f"{GRAPH}/reachability"
    if edge_types:
        from urllib.parse import urlencode
        q = urlencode(qs) + "".join(f"&edge_type={e}" for e in edge_types)
        s, r, _, raw = http("GET", path + "?" + q, headers=tenant["headers"])
        return s, (r if s == 200 else raw)
    s, r, _, raw = http("GET", path, headers=tenant["headers"], params=qs)
    return s, (r if s == 200 else raw)


def canary_zero_scan():
    """Unexpected canary tokens in ACT's OWN records (grant label excluded: operator input)."""
    cols = sql("""SELECT table_name, column_name FROM information_schema.columns
                  WHERE table_schema='public' AND data_type IN ('text','character varying','json','jsonb')""")
    hits = {}
    for t, c in cols:
        for nm, tok in CAN["tokens"].items():
            if nm == "grant_label":
                continue
            if sql(f'SELECT count(*) FROM "{t}" WHERE "{c}"::text LIKE %s', (f"%{tok}%",))[0][0]:
                hits.setdefault(f"{t}.{c}", []).append(nm)
        for p in CAN["pii"]:
            if sql(f'SELECT count(*) FROM "{t}" WHERE "{c}"::text LIKE %s', (f"%{p['canary']}%",))[0][0]:
                hits.setdefault(f"{t}.{c}", []).append("pii")
    return hits
