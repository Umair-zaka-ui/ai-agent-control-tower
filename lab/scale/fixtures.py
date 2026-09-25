"""V9 deterministic scale fixtures - committed, reproducible, honest-worst-case.

    python lab/scale/fixtures.py --rung 100000 --dist worst [--seed 9]

Two distributions per rung (the §1 mandate):
  * ``realistic`` - many tenants, Zipf-like sizes (largest ~4% at 100k). The
    measured tenant is the largest.
  * ``worst``     - ONE busy tenant owns 80% of the agents and ~85% of the
    edges; a RESOURCE hub with in-degree 50% of the tenant's agents, a TOOL
    hub at 40%, an AGENT super-node fanning out to 10%; 100 delegation chains
    of 31 hops (depth cap is 32); 50 execution replay chains of depth 31 behind
    a 10-hop human delegation prefix; dense reconciliation (observations that
    contend with existing external/native identifiers).

Everything is inserted with COPY from a seeded generator, then ANALYZEd (the
stale-statistics trap). The returned manifest is the ground truth the
measurements are scored against; it is written next to the results and
hash-anchored before any measurement runs.

A synthetic agent is NOT an independent agent (V7 proved interoperability;
this proves volume). Nothing here claims otherwise.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import labenv  # noqa: E402

settings = labenv.activate()

import app.main  # noqa: E402,F401 - registers every model on Base.metadata
from sqlalchemy import text  # noqa: E402
from sqlalchemy.types import Integer  # noqa: E402

from app.core.database import Base, SessionLocal, engine  # noqa: E402

NOW = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)
PASSWORD = "V9-Synthetic-Passw0rd!"
_HASH_CACHE: dict = {}

# Tables truncated between fixture sets (org-scoped state cascades from
# organizations; the platform-scoped ones are listed explicitly).
TRUNCATE = ("organizations", "worker_registrations", "execution_locks", "permission_cache")


def _uuid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def _ts(offset_s: int = 0) -> str:
    return (NOW + timedelta(seconds=offset_s)).isoformat()


class Copier:
    """Buffers rows per table and flushes them with COPY ... FROM STDIN (csv)."""

    def __init__(self, raw_conn, batch: int = 50_000) -> None:
        self.conn = raw_conn
        self.batch = batch
        self.buf: dict[str, list[dict]] = {}
        self.cols: dict[str, list[str]] = {}
        self.count: dict[str, int] = {}

    def add(self, table: str, row: dict) -> None:
        tbl = Base.metadata.tables[table]
        if table not in self.cols:
            names = {c.name for c in tbl.columns}
            wanted = [k for k in row if k in names]
            for auto in ("created_at", "updated_at"):
                if auto in names and auto not in wanted:
                    wanted.append(auto)
            self.cols[table] = wanted
        r = dict(row)
        for auto in ("created_at", "updated_at"):
            if auto in self.cols[table] and auto not in r:
                r[auto] = _ts()
        self.buf.setdefault(table, []).append(r)
        if len(self.buf[table]) >= self.batch:
            # Flush EVERY buffered table in first-seen order, never just this one: buffers are
            # filled in dependency order (versions before executions), and flushing a single
            # large table early would write children before their parents (an FK violation
            # observed at the worst/100k rung, where executions alone exceed the batch size).
            self.flush()

    def _fmt(self, v):
        if v is None:
            return r"\N"
        if isinstance(v, bool):
            return "t" if v else "f"
        if isinstance(v, (dict, list)):
            return json.dumps(v, separators=(",", ":"))
        return v

    def flush(self, table: str | None = None) -> None:
        for t in ([table] if table else list(self.buf)):
            rows = self.buf.get(t) or []
            if not rows:
                continue
            cols = self.cols[t]
            sio = io.StringIO()
            w = csv.writer(sio, lineterminator="\n")
            for r in rows:
                w.writerow([self._fmt(r.get(c)) for c in cols])
            sio.seek(0)
            cur = self.conn.cursor()
            cur.copy_expert(f'COPY {t} ({", ".join(cols)}) FROM STDIN WITH (FORMAT csv, NULL \'\\N\')', sio)
            cur.close()
            self.count[t] = self.count.get(t, 0) + len(rows)
            self.buf[t] = []


def _password_hash() -> str:
    if "h" not in _HASH_CACHE:
        from app.core.security import hash_password
        _HASH_CACHE["h"] = hash_password(PASSWORD)
    return _HASH_CACHE["h"]


def truncate_all(db) -> None:
    db.execute(text("TRUNCATE " + ", ".join(TRUNCATE) + " CASCADE"))
    db.commit()
    from app.authorization.seeding import seed_authorization
    seed_authorization(db)
    db.commit()


def register_tenant(db, name: str, idx: int) -> dict:
    """A real tenant through the product's own registration path (RBAC-complete)."""
    from app.services import auth_service
    email = f"v9-admin-{idx}@lab.example"
    user = auth_service.register_organization(db, organization_name=name, name="V9 Admin", email=email,
                                              password=PASSWORD)
    db.commit()
    db.refresh(user)
    return {"org_id": str(user.organization_id), "admin_id": str(user.id), "email": email, "name": name}


def tenant_sizes(rung: int, dist: str) -> list[int]:
    if dist == "worst":
        busy = int(rung * 0.8)
        others = max(1, min(20, rung - busy))
        rest = rung - busy
        base = [rest // others] * others
        for i in range(rest - sum(base)):
            base[i] += 1
        return [busy] + [b for b in base if b > 0]
    t = max(4, min(1000, rung // 100))
    w = [1.0 / ((i + 1) ** 0.7) for i in range(t)]
    s = sum(w)
    sizes = [max(1, int(rung * x / s)) for x in w]
    sizes[0] += rung - sum(sizes)
    return sizes


def generate(rung: int, dist: str, seed: int = 9, *, log=print) -> dict:
    rng = random.Random(f"v9-{rung}-{dist}-{seed}")
    t0 = time.perf_counter()
    db = SessionLocal()
    truncate_all(db)

    sizes = tenant_sizes(rung, dist)
    measured_idx = 0
    # Real registration only for the measured tenant + up to 3 small ones (RBAC needed for API checks);
    # filler tenants are COPYed.
    tenants: list[dict] = []
    real = min(4, len(sizes))
    for i in range(real):
        tenants.append(register_tenant(db, f"V9 {dist} tenant {i}", i))
    db.close()

    raw = engine.raw_connection()
    cp = Copier(raw)
    hash_ = _password_hash()
    for i in range(real, len(sizes)):
        org_id, admin_id = _uuid(rng), _uuid(rng)
        cp.add("organizations", {"id": org_id, "name": f"V9 {dist} tenant {i}", "status": "ACTIVE",
                                 "registration_mode": "INVITE_ONLY"})
        cp.add("users", {"id": admin_id, "organization_id": org_id, "name": "V9 Admin",
                         "email": f"v9-admin-{i}@lab.example", "password_hash": hash_, "role": "ADMIN",
                         "is_active": True, "status": "ACTIVE", "must_change_password": False})
        tenants.append({"org_id": org_id, "admin_id": admin_id, "name": f"V9 {dist} tenant {i}"})

    manifest: dict = {"rung": rung, "dist": dist, "seed": seed, "tenants": len(sizes), "sizes_top5": sizes[:5],
                      "measured": None, "tenant_agents": {}, "totals": {}}
    ver_type_int = isinstance(Base.metadata.tables["agent_versions"].c.version.type, Integer)

    for ti, (tenant, n_agents) in enumerate(zip(tenants, sizes)):
        org, admin = tenant["org_id"], tenant["admin_id"]
        is_measured = ti == measured_idx
        agents: list[str] = []
        ext_refs: list[str] = []      # EXTERNAL agents' external_reference (for LINK contention)
        nat_refs: list[str] = []      # NATIVE agents' external_reference (for NATIVE-collision FLAG)
        gateway_agents: list[str] = []
        unowned = 0
        for j in range(n_agents):
            aid = _uuid(rng)
            agents.append(aid)
            r = rng.random()
            if r < 0.30:
                origin, cs, prov, ext, mode = "NATIVE", "GOVERNED", "ACT_NATIVE", f"nat-{ti}-{j}", None
                nat_refs.append(ext)
            elif r < 0.90:
                origin, prov, ext = "EXTERNAL", "HTTP_AGENT_REGISTRY", f"ext-{ti}-{j}"
                cs = "REGISTERED" if rng.random() < 0.5 else "DISCOVERED"
                mode = "GATEWAY_ENFORCED" if cs == "REGISTERED" else "OBSERVED"
                ext_refs.append(ext)
                if cs == "REGISTERED":
                    gateway_agents.append(aid)
            else:
                origin, cs, prov, ext, mode = "UNKNOWN", "DISCOVERED", "UNKNOWN", f"unk-{ti}-{j}", None
            owned = rng.random() < 0.7
            if not owned:
                unowned += 1
            cp.add("agents", {
                "id": aid, "organization_id": org, "name": f"agent-{ti}-{j}", "agent_type": "ASSISTANT",
                "api_key_hash": hashlib.sha256(aid.encode()).hexdigest(), "status": "ACTIVE", "version": "1.0.0",
                "capabilities": [], "default_risk_score": 0, "max_allowed_risk": 100,
                "human_approval_required": False, "risk_level": "LOW", "health": "HEALTHY",
                "criticality": rng.choice(["LOW", "MEDIUM", "HIGH", "CRITICAL"]),
                "data_classification": "INTERNAL", "default_environment": "DEVELOPMENT",
                "lifecycle_status": "ACTIVE", "autonomy_level": "ASSISTIVE", "tags": [], "metadata": {},
                "registration_source": "MANUAL", "row_version": 1, "control_state": cs,
                "origin_category": origin, "origin_provider": prov, "external_reference": ext,
                "owner_type": "USER" if owned else None, "owner_id": admin if owned else None,
                "external_enforcement_mode": mode,
                "last_observed_at": _ts(-rng.randint(0, 200 * 86400)) if origin != "NATIVE" else None,
                "discovery_source_ref": None, "description": f"synthetic {dist} agent",
                "business_purpose": "volume fixture",
            })
        # tools / resources pools
        n_tools = max(5, n_agents // 10)
        n_res = max(5, n_agents // 20)
        tools = [_uuid(rng) for _ in range(n_tools)]
        resources = [_uuid(rng) for _ in range(n_res)]
        for k, tid in enumerate(tools):
            cp.add("tools", {"id": tid, "organization_id": org, "name": f"tool-{ti}-{k}",
                             "display_name": f"tool-{ti}-{k}", "tool_type": "FUNCTION", "risk_level": "MEDIUM",
                             "side_effect_level": "NONE", "data_classification": "INTERNAL",
                             "requires_approval": False, "timeout_seconds": 30, "enabled": True})
        for k, rid in enumerate(resources):
            kind = "payroll" if k < 3 else rng.choice(["storage", "queue", "database", "api"])
            cp.add("resources", {"id": rid, "resource_type": kind, "resource_id": _uuid(rng),
                                 "organization_id": org, "owner_id": admin, "owner_type": "USER",
                                 "visibility": "PRIVATE", "status": "ACTIVE", "name": f"res-{ti}-{k}-{kind}"})
        edges: set[tuple] = set()

        def edge(st, sid, et, tt, tid, prov="DISCOVERED"):
            key = (st, sid, et, tt, tid)
            if key in edges or (st == tt and sid == tid):
                return
            edges.add(key)
            cp.add("control_graph_edges", {
                "id": _uuid(rng), "organization_id": org, "source_type": st, "source_id": sid,
                "edge_type": et, "target_type": tt, "target_id": tid,
                "evidence": {"kind": "v9-synthetic", "dist": dist}, "confidence": "1.00",
                "provenance": prov, "valid_from": _ts(-3600)})

        edges_per_agent = 10
        for aid in agents:
            for tid in rng.sample(tools, min(5, len(tools))):
                edge("AGENT", aid, "DEPENDS_ON_TOOL", "TOOL", tid)
            for rid in rng.sample(resources, min(3, len(resources))):
                edge("AGENT", aid, "DEPENDS_ON_RESOURCE", "RESOURCE", rid)
            # inter-agent authority edges: worst-case = every agent trusts AND delegates to a random
            # peer (out-degree 2 -> a branching digraph); realistic = 30% of agents carry one of each
            if dist == "worst" or rng.random() < 0.3:
                edge("AGENT", aid, "TRUSTS", "AGENT", rng.choice(agents), "EXPLICIT")
            if dist == "worst" or rng.random() < 0.3:
                edge("AGENT", aid, "AGENT_DELEGATES_TO", "AGENT", rng.choice(agents), "EXPLICIT")
        for tid in tools:
            edge("TOOL", tid, "TOOL_ACCESSES_RESOURCE", "RESOURCE", rng.choice(resources))

        info = {"org_id": org, "admin_id": admin, "agents": n_agents, "tools": n_tools, "resources": n_res,
                "unowned": unowned, "gateway_agents": len(gateway_agents), "ext_refs": len(ext_refs),
                "nat_refs": len(nat_refs), "real_registration": ti < real}
        if is_measured:
            # --- worst-case shapes live on the measured tenant (both distributions get the
            # deep chains + replay chains so the chain benchmark is comparable; only `worst`
            # gets the hubs, which is the §1 high-degree shape).
            hub_res, hub_tool, super_agent = resources[0], tools[0], agents[0]
            if dist == "worst":
                for aid in rng.sample(agents, int(n_agents * 0.5)):
                    edge("AGENT", aid, "DEPENDS_ON_RESOURCE", "RESOURCE", hub_res)
                for aid in rng.sample(agents, int(n_agents * 0.4)):
                    edge("AGENT", aid, "DEPENDS_ON_TOOL", "TOOL", hub_tool)
                for aid in rng.sample(agents, int(n_agents * 0.1)):
                    edge("AGENT", super_agent, "TRUSTS", "AGENT", aid, "EXPLICIT")
            chain_len = 31
            n_chains = min(100, max(1, n_agents // 40))
            chain_heads = []
            for c in range(n_chains):
                if n_agents < chain_len + 1:
                    break
                nodes = rng.sample(agents, chain_len + 1)
                chain_heads.append(nodes[0])
                for a, b in zip(nodes, nodes[1:]):
                    edge("AGENT", a, "AGENT_DELEGATES_TO", "AGENT", b, "EXPLICIT")
            # human delegation prefix (10 hops) ending at the admin
            humans = [_uuid(rng) for _ in range(10)]
            for k, hid in enumerate(humans):
                cp.add("users", {"id": hid, "organization_id": org, "name": f"delegator-{k}",
                                 "email": f"v9-h{k}-{ti}@lab.example", "password_hash": hash_, "role": "VIEWER",
                                 "is_active": True, "status": "ACTIVE", "must_change_password": False})
            chain_humans = humans + [admin]
            for a, b in zip(chain_humans, chain_humans[1:]):
                did = _uuid(rng)
                cp.add("delegations", {"id": did, "organization_id": org, "delegator_id": a, "delegatee_id": b,
                                       "scope_type": "ORGANIZATION"})
                edge("HUMAN", a, "DELEGATES_TO", "HUMAN", b, "EXPLICIT")
            # versions + executions (cost + replay chains)
            n_ver_agents = min(1000, n_agents)
            ver_agents = agents[:n_ver_agents]
            versions = []
            for k, aid in enumerate(ver_agents):
                did, vid = _uuid(rng), _uuid(rng)
                cp.add("agent_definitions", {"id": did, "agent_id": aid, "name": "def", "entrypoint": "v9.handler:run"})
                cp.add("agent_versions", {"id": vid, "agent_id": aid, "definition_id": did,
                                          "version": 1 if ver_type_int else "1", "semantic_version": "1.0.0",
                                          "status": "PUBLISHED", "configuration_snapshot": {}, "model_configuration": {},
                                          "capabilities_snapshot": [], "tools_snapshot": [],
                                          "checksum": hashlib.sha256(vid.encode()).hexdigest(),
                                          "compatibility_level": "UNKNOWN", "release_branch": "main",
                                          "checksum_algorithm": "canonical-sha256"})
                versions.append((aid, vid))
            n_exec = max(rung // 1 if dist == "worst" else n_agents, 100)
            n_exec = min(int(n_exec * 1.2), 120_000)
            exec_ids = []
            for k in range(n_exec):
                aid, vid = versions[k % len(versions)]
                eid = _uuid(rng)
                exec_ids.append(eid)
                cost = round(rng.random() * 0.05, 8)
                cp.add("agent_executions", {
                    "id": eid, "organization_id": org, "agent_id": aid, "agent_version_id": vid,
                    "trigger_type": "API", "input_payload": {}, "status": "COMPLETED", "priority": "NORMAL",
                    "attempt_count": 1, "cancel_requested": False, "cost": 0, "token_accounting_complete": True,
                    "cost_currency": "USD", "cost_is_estimated": False, "was_streamed": False,
                    "stream_interrupted": False, "loop_iterations": 1, "cost_amount": cost,
                    "prompt_tokens": rng.randint(50, 2000), "completion_tokens": rng.randint(10, 800),
                    "total_tokens": 0, "started_at": _ts(-rng.randint(0, 30 * 86400)),
                    "completed_at": _ts(-rng.randint(0, 30 * 86400) + 5), "triggered_by_identity_id": admin,
                })
            replay_leaves = []
            for c in range(min(50, max(1, n_exec // 100))):
                aid, vid = versions[c % len(versions)]
                parent = None
                for d in range(31):
                    eid = _uuid(rng)
                    cp.add("agent_executions", {
                        "id": eid, "organization_id": org, "agent_id": aid, "agent_version_id": vid,
                        "trigger_type": "REPLAY" if parent else "MANUAL", "input_payload": {}, "status": "COMPLETED",
                        "priority": "NORMAL", "attempt_count": 1, "cancel_requested": False, "cost": 0,
                        "token_accounting_complete": True, "cost_currency": "USD", "cost_is_estimated": False,
                        "was_streamed": False, "stream_interrupted": False, "loop_iterations": 1,
                        "parent_execution_id": parent, "triggered_by_identity_id": admin if parent is None else None,
                    })
                    parent = eid
                replay_leaves.append(parent)
            # gateway history at volume (denied + allowed records; nothing dispatched)
            n_calls = min(3 * n_exec, 300_000)
            for k in range(n_calls):
                aid = gateway_agents[k % len(gateway_agents)] if gateway_agents else agents[0]
                allowed = rng.random() < 0.7
                cp.add("external_gateway_calls", {
                    "id": _uuid(rng), "organization_id": org, "agent_id": aid, "grant_id": None,
                    "capability_key": "http_tool.invoke", "target_ref": tools[k % n_tools],
                    "enforcement_mode_at_time": "GATEWAY_ENFORCED",
                    "authz_decision": "ALLOW" if allowed else "DENY", "authz_permission": "tool.invoke",
                    "policy_outcome": "NOT_APPLICABLE", "cost_outcome": "NOT_MEASURABLE",
                    "outcome": "ALLOWED" if allowed else "DENIED", "fail_mode": "FAIL_CLOSED",
                    "dispatch_status": "DISPATCHED" if allowed else "NOT_DISPATCHED",
                    "created_at": _ts(-rng.randint(0, 30 * 86400))})
            # budgets + alerts (durable state for recovery)
            cp.add("budgets", {"id": _uuid(rng), "organization_id": org, "name": "org-monthly", "scope_type": "ORGANIZATION",
                               "mode": "HARD_LIMIT", "period": "MONTHLY", "limit_amount": "1000.00", "currency": "USD",
                               "threshold_percent": 80, "enabled": True})
            for k, aid in enumerate(agents[:100]):
                cp.add("budgets", {"id": _uuid(rng), "organization_id": org, "name": f"agent-budget-{k}",
                                   "scope_type": "AGENT", "scope_id": aid, "mode": "WARNING", "period": "DAILY",
                                   "limit_amount": "10.00", "currency": "USD", "threshold_percent": 80, "enabled": True})
            for k in range(100):
                cp.add("runtime_alerts", {"id": _uuid(rng), "organization_id": org, "source": "SLO", "severity": "WARNING",
                                          "status": "OPEN", "metric": "synthetic.metric", "title": f"open alert {k}",
                                          "summary": "synthetic", "dedup_key": f"v9-alert-{k}", "context": {},
                                          "recurrence_count": 1, "opened_at": _ts(-60), "last_seen_at": _ts(-30)})
            # dense reconciliation set: a source + run + observations contending with existing ids
            src_id, run_id = _uuid(rng), _uuid(rng)
            cp.add("discovery_sources", {"id": src_id, "organization_id": org, "name": "v9-dense-source",
                                         "adapter_key": "HTTP_AGENT_REGISTRY",
                                         "config": {"base_url": "http://127.0.0.1:1", "allowed_hosts": ["127.0.0.1"],
                                                    "local_dev_hosts": ["127.0.0.1"], "allow_plaintext_http": True},
                                         "enabled": True, "missed_sweeps_before_stale": 1})
            cp.add("discovery_runs", {"id": run_id, "organization_id": org, "source_id": src_id, "status": "SUCCEEDED",
                                      "trigger": "MANUAL", "started_at": _ts(-10), "ended_at": _ts(-5), "checkpoint": {},
                                      "observations_count": 0, "agents_created": 0, "agents_linked": 0,
                                      "findings_created": 0})
            n_obs = n_agents
            n_link = int(n_obs * 0.5)
            n_flag = int(n_obs * 0.05)
            n_new = n_obs - n_link - n_flag
            obs_ids = []
            for k in range(n_obs):
                if k < n_link:
                    ext = ext_refs[k % len(ext_refs)] if ext_refs else f"new-{ti}-{k}"
                elif k < n_link + n_flag:
                    ext = nat_refs[k % len(nat_refs)] if nat_refs else f"new-{ti}-{k}"
                else:
                    ext = f"new-{ti}-{k}"
                oid = _uuid(rng)
                obs_ids.append(oid)
                cp.add("discovery_observations", {"id": oid, "organization_id": org, "source_id": src_id, "run_id": run_id,
                                                  "external_identifier": ext,
                                                  "normalized_payload": {"name": f"obs-{k}", "agent_type": "ASSISTANT",
                                                                         "origin_provider": "HTTP_AGENT_REGISTRY"},
                                                  "confidence": "1.00", "observed_at": _ts(-5)})
            # race set: a second run with 300 observations of NEW identifiers, reconciled by 3 sessions concurrently
            race_run = _uuid(rng)
            cp.add("discovery_runs", {"id": race_run, "organization_id": org, "source_id": src_id, "status": "SUCCEEDED",
                                      "trigger": "MANUAL", "started_at": _ts(-4), "ended_at": _ts(-3), "checkpoint": {},
                                      "observations_count": 0, "agents_created": 0, "agents_linked": 0,
                                      "findings_created": 0})
            for k in range(300):
                cp.add("discovery_observations", {"id": _uuid(rng), "organization_id": org, "source_id": src_id,
                                                  "run_id": race_run, "external_identifier": f"race-{ti}-{k}",
                                                  "normalized_payload": {"name": f"race-{k}"}, "confidence": "1.00",
                                                  "observed_at": _ts(-3)})
            # a small "other" tenant reference for isolation checks is chosen by the harness
            info.update({
                "hub_resource": hub_res, "hub_tool": hub_tool, "super_agent": super_agent,
                "chain_heads": chain_heads, "chain_len": chain_len, "delegation_hops": len(chain_humans) - 1,
                "replay_leaves": replay_leaves, "replay_depth": 31, "executions": n_exec, "versions": len(versions),
                "gateway_calls": n_calls, "sample_agent": agents[-1], "sample_resource": resources[-1],
                "sample_tool": tools[-1], "typical_execution": exec_ids[0],
                "source_id": src_id, "run_id": run_id, "race_run_id": race_run,
                "recon_expected": {"observations": n_obs, "created": n_new, "linked": n_link, "flagged": n_flag,
                                   "distinct_link_targets": min(n_link, len(ext_refs)),
                                   "distinct_flag_targets": min(n_flag, len(nat_refs))},
                "budgets": 1 + min(100, n_agents), "alerts": 100, "gateway_agent_ids": gateway_agents[:1000],
            })
            manifest["measured"] = info
        info["edges"] = len(edges)
        manifest["tenant_agents"][org] = n_agents
        if ti % 50 == 0 or is_measured:
            cp.flush()
            log(f"  tenant {ti}/{len(sizes)}: agents={n_agents} edges={len(edges)}")
    cp.flush()
    raw.commit()
    raw.close()

    db = SessionLocal()
    for t in ("agents", "control_graph_edges", "agent_executions", "discovery_observations", "external_gateway_calls",
              "tools", "resources", "users", "organizations", "delegations", "budgets"):
        db.execute(text(f"ANALYZE {t}"))
    db.commit()
    counts = {t: db.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in
              ("organizations", "users", "agents", "tools", "resources", "control_graph_edges", "agent_executions",
               "discovery_observations", "external_gateway_calls", "budgets", "runtime_alerts")}
    db.close()
    manifest["totals"] = counts
    manifest["generation_seconds"] = round(time.perf_counter() - t0, 1)
    manifest["other_tenants"] = [t["org_id"] for t in tenants[1:4]]
    manifest["other_admins"] = [t["admin_id"] for t in tenants[1:4]]
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rung", type=int, required=True)
    ap.add_argument("--dist", choices=("realistic", "worst"), required=True)
    ap.add_argument("--seed", type=int, default=9)
    a = ap.parse_args()
    m = generate(a.rung, a.dist, a.seed)
    out = labenv.RESULTS / f"v9_fixture_{a.dist}_{a.rung}.json"
    out.write_text(json.dumps(m, indent=1), encoding="utf-8")
    print(json.dumps({"totals": m["totals"], "seconds": m["generation_seconds"], "manifest": str(out)}))


if __name__ == "__main__":
    main()
