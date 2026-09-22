"""HOSTILE DISCOVERY SOURCE (V5) -- a controllable, poisoned agent registry.

Same wire shape as the honest lab registry (GET /agents?offset=&limit= ->
{"items":[...], "next_offset": n|null}) so ACT's real HTTP_AGENT_REGISTRY
adapter fetches it over a real socket -- but the payload is attacker-chosen.

A lab-only control plane switches the served scenario without a restart:

    POST /_control  {"scenario": "<name>", ...}   -> 200 {"scenario": ...}
    GET  /_control                                -> current scenario + served ids

Gated: /_control is refused unless ACTLAB_ALLOW_ADVERSARIAL=V5, so this server
cannot be driven adversarially outside the authorized phase.

Scenarios (each maps to a §3/§4 attack):
  baseline            the three REAL agents -- the ground-truth inventory
  false_assets        baseline + fabricated agents that do not exist
  identifier_collision  two DIFFERENT agents advertised under ONE id
  split_identity      the SAME real agent advertised under TWO different ids
  oversized           hostile giant name / description / origin_provider / id
  replay              baseline repeated verbatim (idempotency probe)
  disappear           a subset -- a real agent vanishes (tombstone/staleness)
  native_collision    an item whose id collides with a NATIVE agent's reference
  ownership_poison    items carrying owner/control_state/origin_category/trust
                      fields, trying to inject ownership or trusted status

Nothing here executes code, touches a non-lab destination, or imports ACT.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

RUN = Path(__file__).resolve().parents[1] / "run"
CANARIES = json.loads((RUN / "canaries.json").read_text(encoding="utf-8"))
BUILD = CANARIES["build_id"]
PORT = 8813

# The three REAL agents -- identical ids to the honest registry, so the
# ground-truth inventory is the same asset set.
REAL = [
    {"id": f"lab://wave1/python-agent/{BUILD}", "name": "Lab Python Agent",
     "description": "Wave-1 reference external agent (Python, Tier 2). Not built by ACT.",
     "origin_provider": "CUSTOM"},
    {"id": f"lab://wave1/node-agent/{BUILD}", "name": "Lab Node Agent",
     "description": "Wave-1 external agent (Node.js, Tier 2). Not built by ACT.",
     "origin_provider": "CUSTOM"},
    {"id": f"lab://wave1/mcp-client/{BUILD}", "name": "Lab MCP Client Agent",
     "description": "Wave-1 external MCP client (Python, Tier 2). Not built by ACT.",
     "origin_provider": "CUSTOM"},
]

FAKE = [
    {"id": f"lab://v5/ghost-agent-a/{BUILD}", "name": "Ghost Agent A (does not exist)",
     "description": "Fabricated by a hostile source. No such agent runs anywhere.",
     "origin_provider": "HOSTILE"},
    {"id": f"lab://v5/ghost-agent-b/{BUILD}", "name": "Ghost Agent B (does not exist)",
     "description": "Fabricated by a hostile source. No such agent runs anywhere.",
     "origin_provider": "HOSTILE"},
]

_state = {"scenario": "baseline", "native_reference": None, "extra": {}}
_lock = threading.Lock()


def _oversized():
    big_name = "A" * 5000
    big_desc = "D" * 200000
    big_provider = "P" * 500
    big_id = "lab://v5/oversized/" + ("X" * 5000)
    return [{"id": big_id, "name": big_name, "description": big_desc,
             "origin_provider": big_provider, "agent_type": "B" * 200}]


def items_for(scenario: str) -> list:
    if scenario == "baseline":
        return list(REAL)
    if scenario == "false_assets":
        return list(REAL) + list(FAKE)
    if scenario == "identifier_collision":
        # Two genuinely DIFFERENT agents advertised under ONE identifier.
        cid = f"lab://v5/collision/{BUILD}"
        return [
            {"id": cid, "name": "Collision Agent ONE",
             "description": "First distinct agent claiming the shared identifier.",
             "origin_provider": "HOSTILE"},
            {"id": cid, "name": "Collision Agent TWO",
             "description": "A DIFFERENT agent claiming the same identifier.",
             "origin_provider": "HOSTILE"},
        ]
    if scenario == "split_identity":
        # ONE real agent advertised under TWO different identifiers.
        return [
            {"id": f"lab://v5/split-a/{BUILD}", "name": "Lab Python Agent",
             "description": "Wave-1 reference external agent (Python, Tier 2). Not built by ACT.",
             "origin_provider": "CUSTOM"},
            {"id": f"lab://v5/split-b/{BUILD}", "name": "Lab Python Agent",
             "description": "Wave-1 reference external agent (Python, Tier 2). Not built by ACT.",
             "origin_provider": "CUSTOM"},
        ]
    if scenario == "oversized":
        return _oversized()
    if scenario == "replay":
        return list(REAL)
    if scenario == "disappear":
        return [REAL[0]]  # the node agent and mcp client vanish
    if scenario == "native_collision":
        ref = _state.get("native_reference") or f"lab://v5/unset-native/{BUILD}"
        return [{"id": ref, "name": "Impersonating a NATIVE agent",
                 "description": "Hostile source claims the identifier of an ACT-governed native agent.",
                 "origin_provider": "HOSTILE"}]
    if scenario == "ownership_poison":
        return [{"id": f"lab://v5/owned-ghost/{BUILD}", "name": "Pre-owned Ghost",
                 "description": "Hostile source asserts its own ownership and trusted control state.",
                 "origin_provider": "HOSTILE",
                 # every one of these is an attempt to inject authority via payload
                 "owner_id": "00000000-0000-0000-0000-000000000001",
                 "owner_type": "USER", "control_state": "GOVERNED",
                 "origin_category": "NATIVE", "trust_status": "APPROVED",
                 "lifecycle_status": "ACTIVE", "is_trusted": True,
                 "discovery_confidence": "1.00", "confidence": "1.00"}]
    return list(REAL)


class Handler(BaseHTTPRequestHandler):
    def _json(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urlsplit(self.path)
        if parsed.path != "/_control":
            return self._json(404, {"error": "not found"})
        if os.environ.get("ACTLAB_ALLOW_ADVERSARIAL") != "V5":
            return self._json(403, {"error": "hostile control plane not authorized"})
        n = int(self.headers.get("content-length") or 0)
        req = json.loads(self.rfile.read(n) or b"{}")
        with _lock:
            if "scenario" in req:
                _state["scenario"] = str(req["scenario"])
            if "native_reference" in req:
                _state["native_reference"] = req["native_reference"]
        with (RUN / "hostile_registry.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": "CONTROL", "state": dict(_state)}) + "\n")
        self._json(200, {"scenario": _state["scenario"],
                         "served_ids": [str(i.get("id"))[:80] for i in items_for(_state["scenario"])]})

    def do_GET(self):
        parsed = urlsplit(self.path)
        q = parse_qs(parsed.query)
        if parsed.path == "/_control":
            return self._json(200, {"scenario": _state["scenario"],
                                    "served_ids": [str(i.get("id"))[:80]
                                                   for i in items_for(_state["scenario"])]})
        with (RUN / "hostile_registry.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": "FETCH", "path": parsed.path, "query": q,
                                 "scenario": _state["scenario"]}) + "\n")
        if parsed.path != "/agents":
            return self._json(404, {"error": "not found"})
        offset = int(q.get("offset", ["0"])[0])
        limit = int(q.get("limit", ["50"])[0])
        items = items_for(_state["scenario"])
        page = items[offset:offset + limit]
        nxt = offset + limit if offset + limit < len(items) else None
        self._json(200, {"items": page, "next_offset": nxt})

    def log_message(self, *a):
        pass


def main() -> int:
    bind = os.environ.get("LAB_BIND", "127.0.0.1")
    srv = ThreadingHTTPServer((bind, PORT), Handler)
    (RUN / "hostile_registry.ready").write_text(str(os.getpid()), encoding="utf-8")
    print(f"hostile registry listening on {bind}:{PORT} (scenario={_state['scenario']})", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
