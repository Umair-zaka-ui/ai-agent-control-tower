"""Down-collector observation (V2 §3 observability zone, ADR-0008).

Kills whatever listens on the lab OTLP port (127.0.0.1:8812) -- by port, not by
recorded PID, because the venv launcher's PID is not the listener's -- waits
until the port is free, runs the Node agent's governed T2 call, and records
that ACT still authorizes and dispatches (telemetry is derived; its absence
must not fail an execution). Then restarts the collector and records how many
spans it receives afterwards (proves ACT really exports to it when it is up).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "lab"; RUN = LAB / "run"
BACKEND = ROOT / "backend"
PY = str(BACKEND / ".venv" / "Scripts" / "python.exe") if os.name == "nt" else str(BACKEND / ".venv" / "bin" / "python")
PORT = 8812


def listeners() -> list[int]:
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    return sorted({int(l.split()[-1]) for l in out.splitlines() if "LISTENING" in l and l.split()[1].endswith(f":{PORT}")})


def main() -> int:
    rec = {"before_pids": listeners()}
    for pid in rec["before_pids"]:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    for _ in range(30):
        if not listeners():
            break
        time.sleep(0.5)
    rec["listeners_after_kill"] = listeners()
    log = RUN / "logs" / "act.log"
    errs_before = log.read_text(encoding="utf-8", errors="replace").lower().count("traceback") if log.exists() else 0
    p = subprocess.run(["node", str(LAB / "agents" / "node_agent.js"), str(RUN / "agents" / "node.json")], capture_output=True, text=True, timeout=120, cwd=str(LAB))
    out = json.loads(p.stdout.strip().splitlines()[-1])
    rec["node_t2_allowed_with_collector_down"] = [out["t2_allowed"][0], out["t2_allowed"][1].get("outcome"), out["t2_allowed"][1].get("dispatch_status")]
    time.sleep(7)  # let the export scheduler attempt a flush against the dead collector
    errs_after = log.read_text(encoding="utf-8", errors="replace").lower().count("traceback") if log.exists() else 0
    rec["act_tracebacks_during_outage"] = errs_after - errs_before
    spans_before = sum(1 for f in (RUN / "otlp").glob("*.jsonl") for _ in f.open(encoding="utf-8")) if (RUN / "otlp").exists() else 0
    lf = open(RUN / "logs" / "otlp_collector.log", "ab")
    kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}
    subprocess.Popen([PY, str(LAB / "services" / "otlp_collector.py")], cwd=str(LAB), stdout=lf, stderr=subprocess.STDOUT, **kw)
    for _ in range(20):
        if listeners():
            break
        time.sleep(0.5)
    time.sleep(8)  # next scheduler tick
    spans_after = sum(1 for f in (RUN / "otlp").glob("*.jsonl") for _ in f.open(encoding="utf-8")) if (RUN / "otlp").exists() else 0
    rec["collector_restarted"] = bool(listeners())
    rec["otlp_batches_received_after_restart_delta"] = spans_after - spans_before
    (RUN / "results").mkdir(exist_ok=True)
    (RUN / "results" / "collector_down.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    print(json.dumps(rec, indent=2))
    ok = rec["node_t2_allowed_with_collector_down"][0] == 200 and not rec["listeners_after_kill"] and rec["act_tracebacks_during_outage"] == 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
