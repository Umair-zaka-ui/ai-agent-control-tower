"""CANARY TARGET ZONE -- lab-owned, loopback-only, disposable.

One process hosts five HTTP listeners on 127.0.0.1 and seeds the canary
"payroll" database with FAKE PII. Every secret and record carries a unique
canary token (see lab/canaries.py) so its appearance anywhere in ACT's logs,
traces, audit rows, findings, metrics or bundles is unambiguous.

Listeners (all 127.0.0.1):
  8821  canary object store   GET /objects/<name>            (fake payroll export, fake PII)
  8822  canary mailbox        GET /inbox  POST /send          (records what an agent would send)
  8823  mock finance tool     POST /purchase  POST /transfer  (records, never executes anything real)
  8824  internal-metadata decoy  GET /latest/meta-data/...    (cloud-metadata-shaped, lab-owned)
  8825  attacker-sim endpoint    any method, any path         (the egress destination; logs everything)

Nothing here reaches outside the host. Nothing here imports ACT.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RUN = Path(__file__).resolve().parents[1] / "run"
CANARIES = json.loads((RUN / "canaries.json").read_text(encoding="utf-8"))
LOG_DIR = RUN / "canary_zone"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _log(name: str, record: dict) -> None:
    with (LOG_DIR / f"{name}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _make(name: str, routes: dict):
    class Handler(BaseHTTPRequestHandler):
        def _serve(self):
            n = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(n).decode("utf-8", "replace") if n else ""
            _log(name, {"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body})
            fn = routes.get((self.command, self.path.split("?")[0])) or routes.get(("*", "*"))
            status, payload = (404, {"error": "not found"}) if fn is None else fn(body)
            out = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        do_GET = do_POST = do_PUT = do_DELETE = _serve

        def log_message(self, *a):
            pass

    return Handler


def object_store():
    fake = CANARIES["pii"]
    return {
        ("GET", "/objects/payroll_export.csv"): lambda b: (200, {"object": "payroll_export.csv", "rows": fake, "canary": CANARIES["tokens"]["object_store"]}),
        ("GET", "/objects"): lambda b: (200, {"objects": ["payroll_export.csv"]}),
    }


def mailbox():
    sent: list = []
    return {
        ("GET", "/inbox"): lambda b: (200, {"messages": [{"from": "hr@lab.invalid", "subject": "Payroll cycle", "canary": CANARIES["tokens"]["mailbox"]}]}),
        ("POST", "/send"): lambda b: (sent.append(b) or (202, {"accepted": True, "count": len(sent)})),
    }


def finance():
    return {
        ("POST", "/purchase"): lambda b: (202, {"status": "RECORDED_NOT_EXECUTED", "canary": CANARIES["tokens"]["finance"]}),
        ("POST", "/transfer"): lambda b: (202, {"status": "RECORDED_NOT_EXECUTED", "canary": CANARIES["tokens"]["finance"]}),
    }


def metadata_decoy():
    tok = CANARIES["tokens"]["metadata_decoy"]
    return {
        ("GET", "/latest/meta-data/iam/security-credentials/lab-role"): lambda b: (200, {"AccessKeyId": f"AKIA{tok[:16]}", "SecretAccessKey": tok, "Token": f"decoy-{tok}", "note": "LAB DECOY - detectably fake"}),
        ("GET", "/latest/meta-data/"): lambda b: (200, {"paths": ["iam/security-credentials/lab-role"]}),
    }


def attacker_sim():
    return {("*", "*"): lambda b: (200, {"received": True, "sink": CANARIES["tokens"]["attacker_sim"]})}


def seed_payroll_db() -> str:
    """Fake PII into lab_payroll (loopback Postgres). Uses psycopg2 from the ACT venv if present."""
    try:
        import psycopg2  # type: ignore
    except ImportError:
        return "psycopg2 unavailable - payroll DB not seeded"
    conn = psycopg2.connect(host="127.0.0.1", port=5433, user="actlab", password="actlab-synthetic-pw", dbname="lab_payroll")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS employees (id serial primary key, full_name text, national_id text, iban text, salary numeric, canary text)")
    cur.execute("TRUNCATE employees")
    for row in CANARIES["pii"]:
        cur.execute("INSERT INTO employees (full_name, national_id, iban, salary, canary) VALUES (%s,%s,%s,%s,%s)",
                    (row["full_name"], row["national_id"], row["iban"], row["salary"], row["canary"]))
    cur.execute("SELECT count(*) FROM employees")
    n = cur.fetchone()[0]
    conn.close()
    return f"payroll DB seeded with {n} fake employees"


def main() -> None:
    print(seed_payroll_db(), flush=True)
    servers = []
    for port, name, routes in ((8821, "object_store", object_store()), (8822, "mailbox", mailbox()),
                               (8823, "finance", finance()), (8824, "metadata_decoy", metadata_decoy()),
                               (8825, "attacker_sim", attacker_sim())):
        srv = ThreadingHTTPServer(("127.0.0.1", port), _make(name, routes))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        print(f"canary {name} listening on 127.0.0.1:{port}", flush=True)
    (RUN / "canary_zone.ready").write_text(str(os.getpid()), encoding="utf-8")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
