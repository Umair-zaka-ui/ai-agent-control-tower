"""V7 WAVE-1 AGENT — custom Python agent, full tier ladder.

An independent agent ACT did not build: plain stdlib, its own identity (an ACT
grant), its own tools and MCP dependency. Imports nothing from `app`.
T6 (multi-agent delegation) is NOT APPLICABLE: this is a single-process agent
with no peer framework, and that is recorded rather than simulated.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _agentlib as L


def main():
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    tier = int(sys.argv[2])
    out = {"agent": "custom_python", "framework": "custom (stdlib)", "tier": tier,
           "model": "none (no model in the loop)"}
    if tier == 6:
        out["not_applicable"] = "single-process custom agent has no framework-internal peer to delegate to"
        out["ok"] = True
        return L.emit(out)
    out["ok"] = L.tier_actions(cfg, tier, out)
    L.emit(out)


if __name__ == "__main__":
    main()
