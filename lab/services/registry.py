"""LAB AGENT REGISTRY -- the inbound discovery surface (5.2 HTTP_AGENT_REGISTRY shape).

A real HTTP server on 127.0.0.1:8811 listing the Wave-1 agents. ACT discovers
them through its real adapter over a real socket. Format mirrors the 5.10 proof
registry: GET /agents?offset=&limit= -> {"items": [...], "next_offset": n|null}.
Records every request so the harness can prove the fetch happened. Imports nothing from ACT.
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

RUN = Path(__file__).resolve().parents[1] / "run"
CANARIES = json.loads((RUN / "canaries.json").read_text(encoding="utf-8"))
BUILD = CANARIES["build_id"]

AGENTS = [
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


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlsplit(self.path)
        q = parse_qs(parsed.query)
        with (RUN / "registry_requests.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"path": parsed.path, "query": q}) + "\n")
        if parsed.path != "/agents":
            self.send_response(404); self.end_headers(); return
        offset = int(q.get("offset", ["0"])[0]); limit = int(q.get("limit", ["50"])[0])
        page = AGENTS[offset:offset + limit]
        nxt = offset + limit if offset + limit < len(AGENTS) else None
        body = json.dumps({"items": page, "next_offset": nxt}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


def main() -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", 8811), Handler)
    (RUN / "registry.ready").write_text(str(os.getpid()), encoding="utf-8")
    print("lab registry listening on 127.0.0.1:8811", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
