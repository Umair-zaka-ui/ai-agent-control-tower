"""V9 scale measurements - p50/p95/p99 + captured-statement EXPLAIN scans.

    python lab/scale/measure.py --manifest lab/run/results/v9_fixture_worst_100000.json

Every operation is the product's own service/route (unchanged), called the
way the API calls it, against the manifest's measured tenant. Each timed
operation runs a warm-up, then N iterations on fresh sessions; the last
iteration captures every SQL statement, each read statement is EXPLAINed and
scanned for `Seq Scan` on a hot table (> 5,000 live rows) - the 4.2
"no full scan on the hot path" discipline. Heavy operations run under a
wall-clock budget and report progress honestly when they exceed it (a
measured cliff is the deliverable, never hidden).
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import http.server
import json
import math
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import labenv  # noqa: E402

settings = labenv.activate()
labenv.ensure_lab_encryption_key()

import app.main  # noqa: E402,F401 - registers every model on Base.metadata
from sqlalchemy import and_, event, func, or_, select, text  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402
from app.models.agent import Agent  # noqa: E402
from app.models.discovery import DiscoveryFinding, DiscoveryObservation, DiscoveryRun, DiscoverySource  # noqa: E402
from app.models.user import User  # noqa: E402

HOT = {"agents", "control_graph_edges", "agent_executions", "discovery_observations", "external_gateway_calls",
       "posture_findings", "external_capability_grants", "tools", "resources", "users", "discovery_findings",
       "delegations", "budgets"}
PASSWORD = "V9-Synthetic-Passw0rd!"
BUDGET_S = 300.0


# --------------------------------------------------------------------------- #
# statement capture + EXPLAIN
# --------------------------------------------------------------------------- #
class _Capture:
    def __init__(self) -> None:
        self.on = False
        self.stmts: list[tuple[str, object, bool]] = []

    def __call__(self, conn, cursor, statement, parameters, context, executemany):
        if self.on:
            self.stmts.append((statement, parameters, executemany))


CAP = _Capture()
event.listen(engine, "before_cursor_execute", CAP)
_RELTUPLES: dict[str, float] = {}


def reltuples() -> dict[str, float]:
    if not _RELTUPLES:
        db = SessionLocal()
        for name, n in db.execute(text("SELECT relname, reltuples FROM pg_class WHERE relkind='r'")).all():
            _RELTUPLES[name] = float(n)
        db.close()
    return _RELTUPLES


def _walk(plan: dict, out: list) -> None:
    if plan.get("Node Type") == "Seq Scan":
        out.append({"relation": plan.get("Relation Name"), "plan_rows": plan.get("Plan Rows"),
                    "filter": (plan.get("Filter") or "")[:120]})
    for child in plan.get("Plans", []) or []:
        _walk(child, out)


def explain_scans(stmts: list, *, analyze_keys: tuple[str, ...] = ("WITH RECURSIVE",), max_analyze: int = 2) -> dict:
    flagged, seen, plans = [], set(), []
    raw = engine.raw_connection()
    cur = raw.cursor()
    analyzed = 0
    for stmt, params, many in stmts:
        head = stmt.lstrip()[:16].upper()
        if many or not (head.startswith("SELECT") or head.startswith("WITH")):
            continue
        key = hashlib.sha1(stmt.encode()).hexdigest()[:10]
        if key in seen:
            continue
        seen.add(key)
        try:
            cur.execute("EXPLAIN (FORMAT JSON) " + stmt, params)
            plan = cur.fetchone()[0][0]["Plan"]
        except Exception as exc:  # noqa: BLE001 - explain is best-effort evidence
            raw.rollback()
            plans.append({"stmt": key, "error": str(exc)[:200]})
            continue
        scans: list = []
        _walk(plan, scans)
        for s in scans:
            rel = s["relation"]
            rows = reltuples().get(rel, 0)
            entry = {**s, "live_rows": int(rows), "hot": rel in HOT, "stmt": key}
            if rel in HOT and rows > 5000:
                flagged.append(entry)
        if analyzed < max_analyze and any(k in stmt for k in analyze_keys):
            try:
                cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " + stmt, params)
                plans.append({"stmt": key, "sql": stmt[:1500], "plan": "\n".join(r[0] for r in cur.fetchall())})
                analyzed += 1
            except Exception as exc:  # noqa: BLE001
                raw.rollback()
                plans.append({"stmt": key, "error": str(exc)[:200]})
    raw.rollback()
    cur.close()
    raw.close()
    return {"flagged": flagged, "plans": plans, "distinct_read_statements": len(seen)}


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    return round(s[min(len(s) - 1, max(0, math.ceil(p / 100 * len(s)) - 1))], 2)


def timed(name: str, fn, *, n: int = 10, warmup: int = 1, explain: bool = True, extra: dict | None = None) -> dict:
    for _ in range(warmup):
        fn()
    times: list[float] = []
    for i in range(n):
        if i == n - 1 and explain:
            CAP.stmts, CAP.on = [], True
        t = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t) * 1000)
        CAP.on = False
    stmts, CAP.stmts = CAP.stmts[:], []
    scans = explain_scans(stmts) if explain else {"flagged": [], "plans": [], "distinct_read_statements": 0}
    rec = {"op": name, "n": n, "p50_ms": pct(times, 50), "p95_ms": pct(times, 95), "p99_ms": pct(times, 99),
           "min_ms": round(min(times), 2), "max_ms": round(max(times), 2), "statements": len(stmts),
           "distinct_read_statements": scans["distinct_read_statements"], "hot_seq_scans": scans["flagged"],
           "plans": scans["plans"]}
    rec.update(extra or {})
    print(f"    {name}: p50={rec['p50_ms']}ms p95={rec['p95_ms']}ms n={n} stmts={len(stmts)} "
          f"hot_seq_scans={len(scans['flagged'])}", flush=True)
    return rec


@contextmanager
def session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


def actor_of(db, admin_id: str) -> User:
    return db.get(User, uuid.UUID(admin_id))


# --------------------------------------------------------------------------- #
# local http servers (discovery registry + gateway dispatch target) - loopback only
# --------------------------------------------------------------------------- #
class _State:
    items: list[dict] = []
    hits = 0


@contextmanager
def local_server():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            p = urlsplit(self.path)
            q = parse_qs(p.query)
            if p.path != "/agents":
                self.send_response(404); self.end_headers(); return
            off, lim = int(q.get("offset", ["0"])[0]), int(q.get("limit", ["50"])[0])
            page = _State.items[off:off + lim]
            nxt = off + lim if off + lim < len(_State.items) else None
            body = json.dumps({"items": page, "next_offset": nxt}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(n)
            _State.hits += 1
            body = b'{"ok":true}'
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        yield srv.server_port
    finally:
        srv.shutdown()
        th.join(timeout=5)


# --------------------------------------------------------------------------- #
# the operations
# --------------------------------------------------------------------------- #
def run_all(m: dict) -> dict:
    meas = m["measured"]
    org, admin = meas["org_id"], meas["admin_id"]
    dist, rung = m["dist"], m["rung"]
    out: dict = {"rung": rung, "dist": dist, "tenant_agents": meas["agents"], "tenant_edges": meas["edges"],
                 "totals": m["totals"], "ops": [], "checks": {}}
    ops = out["ops"]
    heavy_n = 3 if rung >= 10_000 else 5

    from app.graph.blast_radius import BlastRadiusService
    from app.graph.service import AuthorityChainService

    # ---- graph: reachability / blast radius / authority chain ----
    # The trust/delegation reachability CTE enumerates simple paths (path-array cycle guard), so
    # its cost is exponential in branching x depth. Probe it as a depth ladder under a hard
    # statement_timeout so the lab can never fill a disk again (it did, at rung 100, depth 32).
    def reach_at(depth: int):
        with session() as db:
            db.execute(text("SET LOCAL statement_timeout = '60s'"))
            return AuthorityChainService(db).reachability(
                actor_of(db, admin), node_type="AGENT", node_id=uuid.UUID(meas["chain_heads"][0]),
                edge_types=["AGENT_DELEGATES_TO", "TRUSTS"], direction="out", max_depth=depth)
    ladder = []
    for depth in (4, 8, 12, 16, 20, 24, 32):
        t = time.perf_counter()
        try:
            nodes = reach_at(depth)
            ladder.append({"depth": depth, "ms": round((time.perf_counter() - t) * 1000, 1), "nodes": len(nodes)})
        except Exception as exc:  # noqa: BLE001 - timeout / temp-file limit is the measurement
            ladder.append({"depth": depth, "ms": round((time.perf_counter() - t) * 1000, 1),
                           "error": type(exc).__name__, "detail": str(exc).splitlines()[0][:160]})
            print(f"    reachability depth {depth}: {ladder[-1]['error']} after {ladder[-1]['ms']}ms", flush=True)
            break
        print(f"    reachability depth {depth}: {ladder[-1]['ms']}ms nodes={ladder[-1]['nodes']}", flush=True)
    # path-growth probe: rows the recursion materialises per depth (bounded, timeout-protected)
    growth = []
    with session() as db:
        db.execute(text("SET LOCAL statement_timeout = '60s'"))
        try:
            rows = db.execute(text("""
                WITH RECURSIVE reach(node_type, node_id, depth, path) AS (
                    SELECT CAST('AGENT' AS varchar), CAST(:start AS uuid), 0, ARRAY[CAST(:key AS text)]
                  UNION ALL
                    SELECT e.target_type, e.target_id, r.depth + 1, r.path || (e.target_type || ':' || e.target_id)
                    FROM reach r JOIN control_graph_edges e
                      ON e.source_type = r.node_type AND e.source_id = r.node_id AND e.organization_id = :org
                     AND e.revoked_at IS NULL AND e.edge_type = ANY(:types)
                    WHERE r.depth < :d AND NOT ((e.target_type || ':' || e.target_id) = ANY(r.path))
                )
                SELECT depth, count(*) AS paths, count(DISTINCT node_id) AS distinct_nodes FROM reach GROUP BY depth ORDER BY depth
            """), {"start": meas["chain_heads"][0], "key": "AGENT:" + meas["chain_heads"][0], "org": org,
                   "types": ["AGENT_DELEGATES_TO", "TRUSTS"], "d": 14}).all()
            growth = [{"depth": int(a), "paths": int(b), "distinct_nodes": int(c)} for a, b, c in rows]
        except Exception as exc:  # noqa: BLE001
            growth = [{"error": type(exc).__name__, "detail": str(exc).splitlines()[0][:160]}]
    last_ok = [x for x in ladder if "nodes" in x]
    r = {"op": "reachability.trust_delegation_depth_ladder", "n": len(ladder), "ladder": ladder,
         "path_growth_per_depth(max14)": growth, "chain_len": meas["chain_len"],
         "max_depth_completed": last_ok[-1]["depth"] if last_ok else None,
         "p50_ms": last_ok[-1]["ms"] if last_ok else None, "p95_ms": last_ok[-1]["ms"] if last_ok else None,
         "cliff": any("error" in x for x in ladder), "hot_seq_scans": [], "plans": []}
    ops.append(r)

    def reach_super():
        with session() as db:
            return AuthorityChainService(db).reachability(
                actor_of(db, admin), node_type="AGENT", node_id=uuid.UUID(meas["super_agent"]),
                edge_types=["TRUSTS"], direction="out", max_depth=2)
    r = timed("reachability.super_node_fanout_depth2", reach_super, n=heavy_n)
    r["result_nodes"] = len(reach_super())
    ops.append(r)

    def br_hub():
        with session() as db:
            return BlastRadiusService(db).agents_reaching(
                actor_of(db, admin), node_type="RESOURCE", node_id=uuid.UUID(meas["hub_resource"]), max_depth=16)
    r = timed("blast_radius.reverse_hub_resource_depth16", br_hub, n=heavy_n)
    res = br_hub()
    r.update({"agents_found": len(res["agents"]), "all_dependents": len(res["all_dependents"]),
              "incomplete": res["incomplete"]})
    ops.append(r)

    def br_typical():
        with session() as db:
            return BlastRadiusService(db).agents_reaching(
                actor_of(db, admin), node_type="RESOURCE", node_id=uuid.UUID(meas["sample_resource"]), max_depth=16)
    r = timed("blast_radius.reverse_typical_resource_depth16", br_typical, n=10)
    res = br_typical()
    r.update({"agents_found": len(res["agents"]), "incomplete": res["incomplete"]})
    ops.append(r)

    def wb_tool_hub():
        with session() as db:
            return BlastRadiusService(db).what_breaks(
                actor_of(db, admin), node_type="TOOL", node_id=uuid.UUID(meas["hub_tool"]), max_depth=16)
    r = timed("blast_radius.what_breaks_tool_hub_depth16", wb_tool_hub, n=heavy_n)
    res = wb_tool_hub()
    r.update({"affected_agents": len(res["affected_agents"]), "affected_nodes": len(res["affected_nodes"])})
    ops.append(r)

    def kind_payroll():
        with session() as db:
            return BlastRadiusService(db).agents_reaching_resource_kind(actor_of(db, admin), "payroll", max_depth=16)
    r = timed("blast_radius.agents_reaching_resource_kind_payroll", kind_payroll, n=heavy_n)
    res = kind_payroll()
    r.update({"agents": len(res.get("agents", res.get("by_agent", []))) if isinstance(res, dict) else None,
              "resources": len(res.get("resources", []))})
    ops.append(r)

    def chain_replay():
        with session() as db:
            return AuthorityChainService(db).reconstruct(actor_of(db, admin), uuid.UUID(meas["replay_leaves"][0]),
                                                         max_depth=32)
    r = timed("authority_chain.reconstruct_replay_depth31_plus_10_delegation_hops", chain_replay, n=10)
    c = chain_replay()
    r.update({"hops": len(c.hops), "complete": c.complete})
    ops.append(r)

    def chain_typical():
        with session() as db:
            return AuthorityChainService(db).reconstruct(actor_of(db, admin), uuid.UUID(meas["typical_execution"]),
                                                         max_depth=32)
    r = timed("authority_chain.reconstruct_typical", chain_typical, n=10)
    c = chain_typical()
    r.update({"hops": len(c.hops), "complete": c.complete})
    ops.append(r)

    # ---- estate / inventory read models ----
    from app.command_center.service import CommandCenterService

    def estate():
        with session() as db:
            return CommandCenterService(db).estate(actor_of(db, admin))
    r = timed("estate.command_center_overview", estate, n=10)
    r["agents_total"] = estate()["agents"]["total"]
    ops.append(r)

    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    def unwrap(body):
        return body.get("data", body) if isinstance(body, dict) else body

    def login(email: str) -> dict:
        r_ = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        tok = unwrap(r_.json())
        assert "access_token" in tok, r_.text[:300]
        return {"Authorization": f"Bearer {tok['access_token']}"}
    with session() as db:
        admin_email = db.get(User, uuid.UUID(admin)).email
    H = login(admin_email)

    def list_first():
        r_ = client.get("/api/v1/runtime/agents", headers=H, params={"page": 1, "page_size": 50})
        assert r_.status_code == 200, r_.text
        return r_.json()
    ops.append(timed("inventory.list_agents_page1_size50", list_first, n=10))
    last_page = max(1, meas["agents"] // 50)

    def list_last():
        r_ = client.get("/api/v1/runtime/agents", headers=H, params={"page": last_page, "page_size": 50})
        assert r_.status_code == 200, r_.text
        return r_.json()
    ops.append(timed(f"inventory.list_agents_last_page({last_page})_size50", list_last, n=5))

    def list_filtered():
        r_ = client.get("/api/v1/runtime/agents", headers=H, params={"page": 1, "page_size": 50, "criticality": "CRITICAL",
                                                                     "query": "agent-0-1"})
        assert r_.status_code == 200, r_.text
        return r_.json()
    ops.append(timed("inventory.list_agents_filtered_search", list_filtered, n=10))

    # ---- cost aggregation (4.4) ----
    from app.finops.aggregation import CostAggregator

    def cost_total():
        with session() as db:
            return CostAggregator(db).summary(uuid.UUID(org)).as_dict()
    r = timed("cost.summary_total", cost_total, n=10)
    r["executions"] = cost_total().get("executions")
    ops.append(r)

    def cost_by_agent():
        with session() as db:
            return CostAggregator(db).summary(uuid.UUID(org), dimension="agent").as_dict()
    ops.append(timed("cost.summary_by_agent", cost_by_agent, n=5))

    # ---- posture: full-population invariant guard (V0.2) + tenant evaluation ----
    from app.runtime.registry.control import CONTROL_STATES, LEGAL_CONTROL_STATES_BY_ORIGIN, ORIGIN_CATEGORIES
    violates = or_(
        Agent.control_state.not_in(CONTROL_STATES), Agent.origin_category.not_in(ORIGIN_CATEGORIES),
        and_(Agent.origin_category == "NATIVE", Agent.origin_provider != "ACT_NATIVE"),
        *[and_(Agent.origin_category == o, Agent.control_state.not_in(legal))
          for o, legal in LEGAL_CONTROL_STATES_BY_ORIGIN.items()])

    def guard():
        with session() as db:
            return db.execute(select(func.count()).select_from(Agent).where(violates)).scalar()
    r = timed("posture.full_population_origin_state_guard(all_tenants)", guard, n=10)
    r["violating_rows"] = guard()
    ops.append(r)

    from app.posture import evaluator as pe
    orig = pe.PostureEvaluator._evaluate_one
    prog = {"agents": 0, "t0": 0.0}

    def wrapped(self, organization_id, agent, summary):
        prog["agents"] += 1
        if time.perf_counter() - prog["t0"] > BUDGET_S:
            raise TimeoutError("v9 budget")
        return orig(self, organization_id, agent, summary)
    pe.PostureEvaluator._evaluate_one = wrapped
    try:
        with session() as db:
            prog["t0"] = time.perf_counter()
            t = time.perf_counter()
            try:
                s = pe.PostureEvaluator(db).evaluate_tenant(actor_of(db, admin))
                el = time.perf_counter() - t
                rec = {"op": "posture.evaluate_tenant_full", "n": 1, "p50_ms": round(el * 1000, 1),
                       "p95_ms": round(el * 1000, 1), "agents_evaluated": prog["agents"], "budget_exceeded": False,
                       "findings_opened": getattr(s, "findings_opened", None),
                       "summary": {k: v for k, v in vars(s).items() if isinstance(v, (int, float, str, bool))}}
            except TimeoutError:
                el = time.perf_counter() - t
                rec = {"op": "posture.evaluate_tenant_full", "n": 1, "p50_ms": None, "p95_ms": None,
                       "budget_exceeded": True, "budget_s": BUDGET_S, "agents_evaluated": prog["agents"],
                       "elapsed_s": round(el, 1), "per_agent_ms": round(el * 1000 / max(1, prog["agents"]), 2),
                       "projected_full_s": round(el / max(1, prog["agents"]) * meas["agents"], 1)}
            rec["tenant_agents"] = meas["agents"]
            rec["per_agent_ms"] = rec.get("per_agent_ms") or round(el * 1000 / max(1, prog["agents"]), 2)
    finally:
        pe.PostureEvaluator._evaluate_one = orig
    print(f"    posture.evaluate_tenant_full: {rec}", flush=True)
    ops.append(rec)

    # ---- gateway authorization (5.7) at volume ----
    from app.bridge.identity import ExternalGrantService
    with local_server() as port:
        def mk_tool(name):
            r_ = client.post("/api/v1/runtime/tools", headers=H, json={
                "name": name, "display_name": name, "tool_type": "HTTP",
                "endpoint_reference": f"http://127.0.0.1:{port}/hook",
                "http_config": {"allowed_hosts": ["127.0.0.1"], "allow_plaintext_http": True,
                                "local_dev_hosts": ["127.0.0.1"], "method": "POST", "timeout_seconds": 10}})
            assert r_.status_code == 201, r_.text
            return unwrap(r_.json())["id"]
        t_in, t_out = mk_tool(f"v9-in-{uuid.uuid4().hex[:6]}"), mk_tool(f"v9-out-{uuid.uuid4().hex[:6]}")
        grants = []
        issue_fail = None
        with session() as db:
            act = actor_of(db, admin)
            for aid in meas["gateway_agent_ids"][:200]:
                ag = db.get(Agent, uuid.UUID(aid))
                try:
                    g, secret = ExternalGrantService(db).issue(
                        act, ag, label=f"v9-{uuid.uuid4().hex[:8]}",
                        scope=[{"capability": "http_tool.invoke", "target_ref": t_in}], rate_limit_per_minute=600)
                    grants.append((g.key_id, secret))
                except Exception as exc:  # noqa: BLE001
                    issue_fail = f"{type(exc).__name__}: {exc}"[:200]
                    db.rollback()
                    break
        out["checks"]["grants_issued"] = {"count": len(grants), "first_error": issue_fail}

        def signed(target, idx):
            key_id, secret = grants[idx % len(grants)]
            body = json.dumps({"capability": "http_tool.invoke", "target_ref": target, "params": {}}).encode()
            ts, nonce = str(int(time.time())), uuid.uuid4().hex
            to_sign = "\n".join(["ACT-HMAC-SHA256", "POST", "/api/v1/bridge/capability", ts, nonce,
                                 hashlib.sha256(body).hexdigest()])
            sig = hmac.new(secret.encode(), to_sign.encode(), hashlib.sha256).hexdigest()
            return client.post("/api/v1/bridge/capability", content=body, headers={
                "Content-Type": "application/json", "X-ACT-Key-Id": key_id, "X-ACT-Timestamp": ts,
                "X-ACT-Nonce": nonce, "X-ACT-Signature": sig})
        if grants:
            k = {"i": 0}

            def denied():
                k["i"] += 1
                r_ = signed(t_out, k["i"])
                assert r_.status_code == 403, (r_.status_code, r_.text[:200])
            ops.append(timed("gateway.authz_only_denied_outside_scope(403)", denied, n=40))

            def allowed():
                k["i"] += 1
                r_ = signed(t_in, k["i"])
                assert r_.status_code == 200, (r_.status_code, r_.text[:200])
            before = _State.hits
            ops.append(timed("gateway.allowed_with_local_dispatch(200)", allowed, n=40))
            out["checks"]["gateway_dispatch_hits"] = _State.hits - before

    # ---- reconciliation at volume (5.2) - dense contention ----
    from app.discovery.reconciliation import ReconciliationService
    exp = meas["recon_expected"]
    with session() as db:
        act = actor_of(db, admin)
        src = db.get(DiscoverySource, uuid.UUID(meas["source_id"]))
        run = db.get(DiscoveryRun, uuid.UUID(meas["run_id"]))
        obs = db.execute(select(DiscoveryObservation).where(DiscoveryObservation.run_id == run.id)).scalars().all()
        agents_before = db.execute(select(func.count()).select_from(Agent).where(Agent.organization_id == src.organization_id)).scalar()
        CAP.stmts, CAP.on = [], True
        t = time.perf_counter()
        res = ReconciliationService(db).reconcile(act, run, src, obs)
        el = time.perf_counter() - t
        CAP.on = False
        stmts = CAP.stmts[:1500]
        CAP.stmts = []
        agents_after = db.execute(select(func.count()).select_from(Agent).where(Agent.organization_id == src.organization_id)).scalar()
        dups = db.execute(text("SELECT count(*) FROM (SELECT external_reference FROM agents WHERE organization_id=:o "
                               "AND external_reference IS NOT NULL GROUP BY external_reference HAVING count(*)>1) d"),
                          {"o": org}).scalar()
        scans = explain_scans(stmts, analyze_keys=("FROM agents",), max_analyze=1)
    rec = {"op": "reconciliation.dense_run", "n": 1, "observations": len(obs), "elapsed_s": round(el, 2),
           "throughput_obs_per_s": round(len(obs) / el, 1), "per_obs_ms": round(el * 1000 / max(1, len(obs)), 2),
           "result": res, "expected": exp,
           "precision": {"created_match": res["created"] == exp["created"], "linked_match": res["linked"] == exp["linked"],
                         "flagged_match": res["flagged"] == exp["flagged"],
                         "agents_delta_equals_created": (agents_after - agents_before) == res["created"],
                         "duplicate_external_references": dups},
           "hot_seq_scans": scans["flagged"], "plans": scans["plans"]}
    print(f"    reconciliation.dense_run: {rec['observations']} obs in {rec['elapsed_s']}s "
          f"({rec['throughput_obs_per_s']}/s) result={res} precision={rec['precision']}", flush=True)
    ops.append(rec)

    # staleness after a partial re-observation (10% missing)
    with session() as db:
        act = actor_of(db, admin)
        src = db.get(DiscoverySource, uuid.UUID(meas["source_id"]))
        refs = [r_[0] for r_ in db.execute(select(Agent.external_reference).where(
            Agent.organization_id == src.organization_id, Agent.discovery_source_ref == str(src.id))).all()]
        observed = set(refs[: int(len(refs) * 0.9)])
        t = time.perf_counter()
        st = ReconciliationService(db).check_staleness(act, src, observed_external_ids=observed)
        el = time.perf_counter() - t
    ops.append({"op": "reconciliation.check_staleness_10pct_missing", "n": 1, "linked_agents": len(refs),
                "elapsed_s": round(el, 2), "result": st, "p50_ms": round(el * 1000, 1), "p95_ms": round(el * 1000, 1)})
    print(f"    staleness: {len(refs)} linked, {st} in {el:.2f}s", flush=True)

    # concurrent reconciliation race - 3 real sessions over the same 300 new identifiers
    results, errors = [], []

    def worker():
        db = SessionLocal()
        try:
            act = actor_of(db, admin)
            src = db.get(DiscoverySource, uuid.UUID(meas["source_id"]))
            rr = db.get(DiscoveryRun, uuid.UUID(meas["race_run_id"]))
            o = db.execute(select(DiscoveryObservation).where(DiscoveryObservation.run_id == rr.id)).scalars().all()
            results.append(ReconciliationService(db).reconcile(act, rr, src, o))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}"[:200])
        finally:
            db.close()
    ths = [threading.Thread(target=worker) for _ in range(3)]
    t = time.perf_counter()
    [th.start() for th in ths]
    [th.join() for th in ths]
    el = time.perf_counter() - t
    with session() as db:
        race_agents = db.execute(text("SELECT count(*) FROM agents WHERE organization_id=:o AND external_reference LIKE 'race-%'"),
                                 {"o": org}).scalar()
        race_dups = db.execute(text("SELECT count(*) FROM (SELECT external_reference FROM agents WHERE organization_id=:o "
                                    "AND external_reference LIKE 'race-%' GROUP BY external_reference HAVING count(*)>1) d"),
                               {"o": org}).scalar()
    ops.append({"op": "reconciliation.concurrent_3_sessions_300_obs", "n": 1, "elapsed_s": round(el, 2),
                "per_session": results, "errors": errors, "agents_created_total": race_agents,
                "expected_agents": 300, "duplicates": race_dups, "no_duplicate_create": race_dups == 0 and race_agents == 300})
    print(f"    race: sessions={results} agents={race_agents} dups={race_dups} errors={errors}", flush=True)

    # ---- discovery sweep at volume (HTTP reference adapter, loopback) ----
    from app.discovery.service import DiscoveryRunService, DiscoverySourceService
    n_sweep = min(meas["agents"], 20_000)
    _State.items = [{"id": f"sweep-{i}", "name": f"Sweep Agent {i}", "agent_type": "ASSISTANT"} for i in range(n_sweep)]
    with local_server() as port:
        with session() as db:
            act = actor_of(db, admin)
            cfg = {"base_url": f"http://127.0.0.1:{port}", "allowed_hosts": ["127.0.0.1"], "local_dev_hosts": ["127.0.0.1"],
                   "allow_plaintext_http": True, "path": "/agents", "page_size": 200, "max_pages": 100}
            src = DiscoverySourceService(db).create(act, name=f"v9-sweep-{uuid.uuid4().hex[:6]}",
                                                    adapter_key="HTTP_AGENT_REGISTRY", config=cfg)
            runs = []
            for i in range(2):
                t = time.perf_counter()
                rr = DiscoveryRunService(db).run_source(act, src, trigger="MANUAL")
                runs.append({"status": rr.status, "observations": rr.observations_count, "created": rr.agents_created,
                             "linked": rr.agents_linked, "findings": rr.findings_created, "elapsed_s": round(time.perf_counter() - t, 2),
                             "checkpoint": rr.checkpoint, "error": rr.error})
            dups = db.execute(text("SELECT count(*) FROM (SELECT external_reference FROM agents WHERE organization_id=:o "
                                   "AND external_reference LIKE 'sweep-%' GROUP BY external_reference HAVING count(*)>1) d"),
                              {"o": org}).scalar()
        rec = {"op": "discovery.sweep_volume_two_runs", "n": 2, "items_served": n_sweep, "runs": runs,
               "idempotent": runs[0]["created"] == n_sweep and runs[1]["created"] == 0 and runs[1]["linked"] == n_sweep,
               "duplicates": dups, "p50_ms": round(runs[0]["elapsed_s"] * 1000, 1), "p95_ms": round(runs[1]["elapsed_s"] * 1000, 1)}
        print(f"    sweep: {rec}", flush=True)
        ops.append(rec)
        if rung >= 100_000:
            _State.items = [{"id": f"big-{i}", "name": f"Big {i}"} for i in range(100_000)]
            with session() as db:
                act = actor_of(db, admin)
                src2 = DiscoverySourceService(db).create(act, name=f"v9-bound-{uuid.uuid4().hex[:6]}",
                                                         adapter_key="HTTP_AGENT_REGISTRY", config=cfg)
                t = time.perf_counter()
                rr = DiscoveryRunService(db).run_source(act, src2, trigger="MANUAL")
                rec = {"op": "discovery.sweep_100k_source_single_run_bound", "n": 1, "items_served": 100_000,
                       "status": rr.status, "observations": rr.observations_count, "created": rr.agents_created,
                       "checkpoint": rr.checkpoint, "error": rr.error, "elapsed_s": round(time.perf_counter() - t, 2),
                       "p50_ms": round((time.perf_counter() - t) * 1000, 1), "p95_ms": round((time.perf_counter() - t) * 1000, 1)}
            print(f"    sweep bound: {rec}", flush=True)
            ops.append(rec)

    # ---- tenant scope at volume ----
    other_org = m["other_tenants"][0]
    other_admin = m["other_admins"][0]
    with session() as db:
        other_email = db.get(User, uuid.UUID(other_admin)).email
        other_res = db.execute(text("SELECT id FROM resources WHERE organization_id=:o LIMIT 1"), {"o": other_org}).scalar()
        other_agent = db.execute(text("SELECT id FROM agents WHERE organization_id=:o LIMIT 1"), {"o": other_org}).scalar()
        other_count = db.execute(text("SELECT count(*) FROM agents WHERE organization_id=:o"), {"o": other_org}).scalar()
    H2 = login(other_email)

    def small_list():
        r_ = client.get("/api/v1/runtime/agents", headers=H2, params={"page": 1, "page_size": 50})
        assert r_.status_code == 200
        return r_.json()
    r = timed("tenant.small_tenant_list_agents_beside_busy_tenant", small_list, n=10)
    body = unwrap(small_list())
    total = body.get("total") if isinstance(body, dict) else None
    r["small_tenant_agents"] = other_count
    r["api_total_matches_fixture"] = (total == other_count) if total is not None else None
    ops.append(r)

    with session() as db:
        # cross-tenant blast radius with the busy actor -> must be a 404-class refusal, not data
        from app.identity.errors import IdentityError
        try:
            BlastRadiusService(db).agents_reaching(actor_of(db, admin), node_type="RESOURCE", node_id=other_res, max_depth=8)
            xt = "LEAK: returned data"
        except IdentityError as exc:
            xt = exc.code.value if hasattr(exc.code, "value") else str(exc.code)
        db.rollback()
        # hostile cross-tenant edge inserted directly -> the walk must stop at the tenant edge
        hostile = str(uuid.uuid4())
        db.execute(text("INSERT INTO control_graph_edges (id, organization_id, source_type, source_id, edge_type, target_type, "
                        "target_id, evidence, confidence, provenance, valid_from, created_at, updated_at) VALUES "
                        "(:id, :o, 'AGENT', :s, 'TRUSTS', 'AGENT', :t, '{}', 1.00, 'EXPLICIT', now(), now(), now())"),
                   {"id": hostile, "o": org, "s": meas["sample_agent"], "t": str(other_agent)})
        db.commit()
        t = time.perf_counter()
        nodes = AuthorityChainService(db).reachability(actor_of(db, admin), node_type="AGENT",
                                                       node_id=uuid.UUID(meas["sample_agent"]), direction="out", max_depth=3)
        el = time.perf_counter() - t
        leaked = any(str(n.node_id) == str(other_agent) for n in nodes)
        db.execute(text("DELETE FROM control_graph_edges WHERE id=:id"), {"id": hostile})
        db.commit()
    out["checks"]["cross_tenant_blast_radius"] = xt
    out["checks"]["hostile_edge_truncated_at_tenant_edge"] = not leaked
    out["checks"]["hostile_edge_walk_ms"] = round(el * 1000, 1)
    with session() as db:
        live = db.execute(text("SELECT count(*) FROM agents WHERE organization_id=:o"), {"o": org}).scalar()
    out["checks"]["estate_total_equals_live_count"] = estate()["agents"]["total"] == live
    out["checks"]["estate_total_equals_fixture"] = out["checks"]["estate_total_equals_live_count"]
    print(f"    tenant checks: cross_tenant={xt} hostile_truncated={not leaked} estate_ok={out['checks']['estate_total_equals_fixture']}",
          flush=True)
    out["hot_seq_scan_ops"] = [o["op"] for o in ops if o.get("hot_seq_scans")]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    a = ap.parse_args()
    mp = Path(a.manifest)
    if not mp.is_absolute():
        mp = labenv.ROOT / mp
    m = json.loads(mp.read_text(encoding="utf-8"))
    print(f"== measuring rung={m['rung']} dist={m['dist']} tenant_agents={m['measured']['agents']} "
          f"tenant_edges={m['measured']['edges']} totals={m['totals']}", flush=True)
    t0 = time.perf_counter()
    out = run_all(m)
    out["elapsed_s"] = round(time.perf_counter() - t0, 1)
    out["env"] = {"postgres": "17.10 host-native (PostgreSQL 17 Windows build, dedicated instance on 127.0.0.1:55432; 12 CPU / 16 GB host)",
                  "shared_buffers": "512MB", "work_mem": "32MB", "harness": "in-process, host CPython 3.13, loopback only"}
    dest = labenv.RESULTS / f"v9_measure_{m['dist']}_{m['rung']}.json"
    dest.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(f"== wrote {dest} in {out['elapsed_s']}s", flush=True)


if __name__ == "__main__":
    main()
