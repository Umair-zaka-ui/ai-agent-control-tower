"""V7 WAVE-2 AGENT — a real LangGraph multi-agent graph, full tier ladder.

An independent multi-agent system ACT did not build. The supervisor/worker
handoffs are genuine LangGraph state-graph edges — framework-internal authority
relationships ACT has no producer for (I-2). At T6 the graph performs real
delegation; at T7 it runs a bounded autonomous loop carrying state between
steps. Enterprise is reached only through ACT's governed boundary.

Imports nothing from `app`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _agentlib as L


def _merge(a: list, b: list) -> list:
    return (a or []) + (b or [])


class State(TypedDict, total=False):
    tier: int
    handoffs: Annotated[list, _merge]
    boundary_calls: Annotated[list, _merge]
    notes: Annotated[list, _merge]


def run_graph(cfg, tier, out):
    from langgraph.graph import StateGraph, START, END

    def supervisor(state: State) -> dict:
        # The routing decision IS the agent-to-agent authority relationship.
        return {"handoffs": [{"from": "supervisor", "to": "worker",
                              "mechanism": "langgraph_state_edge", "tier": tier}],
                "notes": [f"supervisor planned tier {tier}"]}

    def worker(state: State) -> dict:
        calls = [{"target": "allowed",
                  **L.signed_call(cfg, cfg["allowed_tool"], {"body": {"from": "langgraph_worker"}})}]
        if tier >= 2:
            calls.append({"target": "forbidden", **L.signed_call(cfg, cfg["forbidden_tool"])})
        hand = []
        if tier >= 6:
            hand.append({"from": "worker", "to": "reviewer",
                         "mechanism": "langgraph_state_edge", "tier": tier})
        return {"boundary_calls": calls, "handoffs": hand}

    def reviewer(state: State) -> dict:
        calls = []
        if tier >= 7:
            for i in range(3):
                calls.append({"target": "allowed", "autonomy_step": i,
                              **L.signed_call(cfg, cfg["allowed_tool"], {"body": {"autonomy_step": i}})})
        return {"boundary_calls": calls, "notes": ["reviewer closed the loop"]}

    g = StateGraph(State)
    g.add_node("supervisor", supervisor)
    g.add_node("worker", worker)
    g.add_node("reviewer", reviewer)
    g.add_edge(START, "supervisor")
    g.add_edge("supervisor", "worker")
    if tier >= 6:
        g.add_edge("worker", "reviewer")
        g.add_edge("reviewer", END)
    else:
        g.add_edge("worker", END)
    app = g.compile()
    final = app.invoke({"tier": tier, "handoffs": [], "boundary_calls": [], "notes": []})
    out["handoffs"] = final.get("handoffs", [])
    out["boundary_calls"] = (out.get("boundary_calls") or []) + final.get("boundary_calls", [])
    out["a2a_handoff_count"] = len(out["handoffs"])
    out["autonomy_steps"] = len([c for c in out["boundary_calls"] if "autonomy_step" in c])


def main():
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    tier = int(sys.argv[2])
    out = {"agent": "langgraph", "framework": "LangGraph", "tier": tier,
           "model": cfg.get("model_label", "local deterministic substrate")}
    try:
        from importlib.metadata import version
        out["framework_version"] = version("langgraph")
    except Exception as e:
        out["framework_version"] = f"unknown ({type(e).__name__})"

    if tier == 5:
        out["skipped"] = "T5 cloud/SaaS privileges require the V8 cloud adapter; deferred, not fabricated"
        out["ok"] = False
        return L.emit(out)
    try:
        # shared ladder work (tools, MCP, fs, sandboxed compute) …
        L.tier_actions(cfg, min(tier, 4) if tier < 6 else 4, out)
        # … then the framework's own graph execution on top
        run_graph(cfg, tier, out)
        out["ok"] = True
    except Exception as e:
        out["ok"] = False
        out["error"] = f"{type(e).__name__}: {e}"[:300]
    L.emit(out)


if __name__ == "__main__":
    main()
