"""OBSERVABILITY -- a minimal OTLP/HTTP receiver on 127.0.0.1:8812.

Accepts POST /v1/traces, /v1/metrics, /v1/logs (JSON or protobuf bytes) and
appends the raw payload to lab/run/otlp/<signal>.jsonl for the canary scan.
`--down` starts nothing (the "down-collector" mode): ACT must degrade
telemetry, never fail an execution, when the collector is absent (ADR-0008).
Imports nothing from ACT.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RUN = Path(__file__).resolve().parents[1] / "run"
OUT = RUN / "otlp"
OUT.mkdir(parents=True, exist_ok=True)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b""
        signal = self.path.strip("/").split("/")[-1] or "unknown"
        ctype = self.headers.get("content-type", "")
        try:
            payload = json.loads(raw) if "json" in ctype else {"protobuf_b64": base64.b64encode(raw).decode()}
        except Exception:
            payload = {"raw_b64": base64.b64encode(raw).decode()}
        with (OUT / f"{signal}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"content_type": ctype, "payload": payload}) + "\n")
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"{}")

    def log_message(self, *a):
        pass


def main() -> int:
    if "--down" in sys.argv:
        (RUN / "otlp_collector.down").write_text("collector deliberately not started", encoding="utf-8")
        print("otlp collector in DOWN mode (not listening)", flush=True)
        return 0
    bind = os.environ.get("LAB_BIND", "127.0.0.1")  # 0.0.0.0 inside the V2.1 egress-deny network
    srv = ThreadingHTTPServer((bind, 8812), Handler)
    (RUN / "otlp_collector.ready").write_text(str(os.getpid()), encoding="utf-8")
    print(f"otlp collector listening on {bind}:8812", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
