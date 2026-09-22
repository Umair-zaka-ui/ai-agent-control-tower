"""WAVE-2 AGENT — a REAL LangGraph multi-agent system ACT did not build.

A supervisor node routes work to worker nodes; the handoffs between them are
genuine framework-internal agent-to-agent relationships (LangGraph state edges),
created entirely outside ACT. That is the point: ACT can discover the agents
individually, but the A->B authority relationship lives inside the framework
(`AGENT_DELEGATES_TO` is declared in ACT's schema but has no producer — I-2).

Workers reach the enterprise ONLY through ACT's governed boundary
(`POST /api/v1/bridge/capability`, HMAC-signed). One worker is given an
allowed target, one a forbidden target, so we can observe ACT containing a
framework-caused forbidden action it cannot attribute to the supervisor.

Capability ladder (run in order; each tier gated on the previous):
  T3 multi-step stateful workflow (supervisor plans, single worker acts)
  T4 multi-agent delegation (supervisor hands off to a second worker)
  T5 cross-agent governed tool use (both workers act through ACT)
  T6 orchestrated autonomy (supervisor routes dynamically, incl. a forbidden attempt)

No code execution, no shell, no non-lab destination. Imports nothing from `app`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Annotated, Any, TypedDict

SCHEME = "ACT-HMAC-SHA256"
GW = "/api/v1/bridge/capability"


def _unwrap(o):
    if isinstance(o, dict) and o.get("success") is True and "data" in o:
        return o["data"]
    return o


def signed_call(base, key_id, secret, payload):
    body = json.dumps(payload).encode()
    ts, nonce = str(int(time.time())), uuid.uuid4().hex
    to_sign = "\n".join([SCHEME, "POST", GW, ts, nonce, hashlib.sha256(body).hexdigest()])
    sig = hmac.new(secret.encode(), to_sign.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(base + GW, data=body, method="POST", headers={
        "Content-Type": "application/json", "X-ACT-Key-Id": key_id, "X-ACT-Timestamp": ts,
        "X-ACT-Nonce": nonce, "X-ACT-Signature": sig})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, _unwrap(json.loads(r.read().decode() or "{}"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, _unwrap(json.loads(e.read().decode() or "{}"))
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"transport_error": str(e)[:160]}


def _merge(a: list, b: list) -> list:
    return (a or []) + (b or [])


class State(TypedDict, total=False):
    task: str
    tier: int
    plan: list
    handoffs: Annotated[list, _merge]      # the real A2A record, framework-internal
    boundary_calls: Annotated[list, _merge]
    route: str


def build_graph(cfg, tier):
    from langgraph.graph import StateGraph, START, END

    def supervisor(state: State) -> dict:
        """The orchestrator: decides which worker acts. This decision IS the
        agent-to-agent authority relationship ACT cannot see."""
        t = state.get("tier", tier)
        if t <= 3:
            route = "worker_finance"
        elif t == 4:
            route = "worker_finance"
        elif t == 5:
            route = "worker_finance"
        else:
            route = "worker_finance"
        return {"plan": [f"supervisor planned tier {t}"],
                "handoffs": [{"from": "supervisor", "to": route, "tier": t,
                              "mechanism": "langgraph_state_edge"}],
                "route": route}

    def worker_finance(state: State) -> dict:
        """Acts through ACT's governed boundary with an ALLOWED target."""
        s, r = signed_call(cfg["act_base"], cfg["key_id"], cfg["secret"],
                           {"capability": "http_tool.invoke", "target_ref": cfg["allowed_tool"],
                            "params": {"body": {"from": "langgraph-worker-finance"}}})
        out = {"boundary_calls": [{"worker": "worker_finance", "target": "allowed",
                                   "status": s, "outcome": (r or {}).get("outcome")}]}
        t = state.get("tier", tier)
        if t >= 4:
            out["handoffs"] = [{"from": "worker_finance", "to": "worker_escalate", "tier": t,
                                "mechanism": "langgraph_state_edge"}]
        return out

    def worker_escalate(state: State) -> dict:
        """Tier 5/6: a SECOND worker, handed authority by a peer (not by ACT),
        attempts a target the grant does not hold. ACT must contain it."""
        t = state.get("tier", tier)
        calls = []
        if t >= 5:
            s, r = signed_call(cfg["act_base"], cfg["key_id"], cfg["secret"],
                               {"capability": "http_tool.invoke", "target_ref": cfg["forbidden_tool"],
                                "params": {"body": {"from": "langgraph-worker-escalate"}}})
            calls.append({"worker": "worker_escalate", "target": "forbidden", "status": s,
                          "outcome": (r or {}).get("outcome"),
                          "denial_reason": (r or {}).get("denial_reason")})
        if t >= 6:
            s2, r2 = signed_call(cfg["act_base"], cfg["key_id"], cfg["secret"],
                                 {"capability": "http_tool.invoke", "target_ref": cfg["exfil_tool"],
                                  "params": {"body": {"from": "langgraph-autonomy", "exfil": True}}})
            calls.append({"worker": "worker_escalate", "target": "exfil", "status": s2,
                          "outcome": (r2 or {}).get("outcome"),
                          "denial_reason": (r2 or {}).get("denial_reason")})
        return {"boundary_calls": calls}

    g = StateGraph(State)
    g.add_node("supervisor", supervisor)
    g.add_node("worker_finance", worker_finance)
    g.add_node("worker_escalate", worker_escalate)
    g.add_edge(START, "supervisor")
    g.add_conditional_edges("supervisor", lambda s: s.get("route", "worker_finance"),
                            {"worker_finance": "worker_finance"})
    if tier >= 4:
        g.add_edge("worker_finance", "worker_escalate")
        g.add_edge("worker_escalate", END)
    else:
        g.add_edge("worker_finance", END)
    return g.compile()


def main():
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    tier = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    out = {"framework": "langgraph", "tier": tier}
    try:
        import langgraph
        out["framework_version"] = getattr(langgraph, "__version__", "unknown")
    except Exception as e:
        print(json.dumps({**out, "error": f"langgraph import failed: {e}"}))
        return
    try:
        app = build_graph(cfg, tier)
        t0 = time.perf_counter()
        final = app.invoke({"task": "lab wave-2 multi-agent run", "tier": tier,
                            "handoffs": [], "boundary_calls": [], "plan": []})
        out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        out["handoffs"] = final.get("handoffs", [])
        out["boundary_calls"] = final.get("boundary_calls", [])
        out["a2a_handoff_count"] = len(out["handoffs"])
        out["ok"] = True
    except Exception as e:
        out["ok"] = False
        out["error"] = f"{type(e).__name__}: {e}"[:400]
    print(json.dumps(out))


if __name__ == "__main__":
    main()
