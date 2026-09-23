"""V7 WAVE-1 AGENT — MCP client agent, full tier ladder.

Exercises the MCP zone the way an MCP host would, and reaches enterprise only
through ACT's governed boundary. Imports nothing from `app`. T6 N/A (no peer).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _agentlib as L


def main():
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    tier = int(sys.argv[2])
    out = {"agent": "mcp_client", "framework": "custom MCP host (stdlib)", "tier": tier,
           "model": "none (no model in the loop)"}
    if tier == 6:
        out["not_applicable"] = "MCP host agent has no framework-internal peer to delegate to"
        out["ok"] = True
        return L.emit(out)
    ok = L.tier_actions(cfg, tier, out)
    # an MCP-first agent touches MCP from T1 upward, not only at T3
    if tier in (1, 2) and out.get("mcp") is None:
        init = L.mcp_rpc(cfg["mcp_trusted"], cfg["mcp_token"], "initialize",
                         {"protocolVersion": "2025-11-25",
                          "clientInfo": {"name": "mcp_client", "version": "1"}})
        out["mcp"] = {"initialized": bool(init.get("result")), "tools": [], "call_ok": None}
    out["ok"] = ok
    L.emit(out)


if __name__ == "__main__":
    main()
