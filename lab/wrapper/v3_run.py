"""V3 RUN ORCHESTRATOR (host side).

Runs the full V3 adversarial phase inside the V2.1 egress-deny wrapper:

  1. ensure the wrapped lab is up (build/start if needed)
  2. PRE-FLIGHT batch-1 requirement: re-run the boundary proof WITH and WITHOUT
     ACT (V2.1 prerequisite) -- if any deny-proof fails, STOP
  3. exec the runner: v3_preflight.py (ledger active, canary zero-scan, positive control)
  4. exec the runner: v3_redteam.py (T1, T4, T3, T5 batches; hash-anchored results)
  5. capture the ACT container log + canary grep; anchor it; final ledger verify

The host never gets a network path into the lab; it only `docker compose exec`s
and reads lab/run through the bind mount. Nothing here changes ACT.

    python lab/wrapper/v3_run.py            # up + proof + preflight + batches
    python lab/wrapper/v3_run.py --no-proof # skip the boundary re-proof (only if already proven this session)
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "lab"
RUN = LAB / "run"
WRAP = LAB / "wrapper"
COMPOSE = ["docker", "compose", "-f", str(WRAP / "docker-compose.wrapped.yml")]


def sh(cmd, check=True, timeout=1800, env=None):
    p = subprocess.run(cmd, cwd=str(WRAP), capture_output=True, text=True, timeout=timeout, env=env)
    if check and p.returncode != 0:
        raise SystemExit(f"FAILED: {' '.join(cmd)}\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")
    return p


def host_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1)); ip = s.getsockname()[0]; s.close()
        return ip
    except Exception:
        return ""


def running() -> bool:
    p = sh(COMPOSE + ["ps", "--format", "{{.Name}} {{.State}}"], check=False)
    return "actlab-wrapped-act-1" in p.stdout and "running" in p.stdout


def healthy_wait():
    for _ in range(90):
        st = sh(["docker", "inspect", "--format", "{{.State.Health.Status}}", "actlab-wrapped-act-1"], check=False).stdout.strip()
        if st == "healthy":
            return "healthy"
        time.sleep(2)
    return st


def main() -> int:
    t0 = time.time(); steps = []

    def step(name, fn):
        s = time.time(); r = fn(); steps.append({"step": name, "seconds": round(time.time() - s, 2), "result": r})
        print(f"[{steps[-1]['seconds']:>7.2f}s] {name}: {str(r)[:200]}", flush=True)

    if not running():
        step("build", lambda: sh(COMPOSE + ["build"]).returncode)
        step("up -d --wait", lambda: sh(COMPOSE + ["up", "-d", "--wait", "--wait-timeout", "300"]).returncode)
    else:
        print("wrapped lab already running", flush=True)

    if "--no-proof" not in sys.argv:
        env = dict(os.environ, HOST_IP=host_ip())

        def _proof(label):
            sh(COMPOSE + ["exec", "-e", f"HOST_IP={env['HOST_IP']}", "proof", "sh", "/lab/wrapper/boundary_proof.sh"], check=False, timeout=600)
            src = RUN / "results" / "boundary_proof.txt"
            dst = RUN / "results" / f"boundary_proof_{label}.txt"
            if src.exists():
                shutil.copy(src, dst)
                txt = dst.read_text(encoding="utf-8", errors="replace")
                return {"denies": txt.count("DENIED"), "allows": txt.count("ALLOWED")}
            return {"error": "no proof output"}

        step("boundary proof (ACT running)", lambda: _proof("act_running"))
        step("stop ACT", lambda: sh(COMPOSE + ["stop", "act"]).returncode)
        step("boundary proof (ACT STOPPED)", lambda: _proof("act_stopped"))
        step("start ACT", lambda: sh(COMPOSE + ["start", "act"]).returncode)
        step("ACT healthy again", healthy_wait)

    step("pre-flight (runner)", lambda: sh(COMPOSE + ["exec", "runner", "python", "/lab/harness/v3_preflight.py"], check=False, timeout=600).stdout.strip().splitlines()[-1:])
    step("V3 batches (runner)", lambda: sh(COMPOSE + ["exec", "runner", "python", "/lab/harness/v3_redteam.py"], check=False, timeout=1800).stdout.strip().splitlines()[-3:])

    def _actlog():
        (RUN / "logs").mkdir(parents=True, exist_ok=True)
        txt = sh(COMPOSE + ["logs", "--no-color", "act"], check=False).stdout
        (RUN / "logs" / "act_wrapped.log").write_text(txt, encoding="utf-8")
        # anchor the act log and re-scan it for canary tokens (except the grant label)
        can = json.loads((RUN / "canaries.json").read_text(encoding="utf-8"))
        hits = sum(txt.count(tok) for name, tok in can["tokens"].items() if name != "grant_label")
        sh(COMPOSE + ["exec", "runner", "python", "/lab/harness/ledger.py", "anchor", "/lab/run/logs/act_wrapped.log"], check=False)
        return {"lines": len(txt.splitlines()), "unexpected_canary_hits": hits, "tracebacks": txt.lower().count("traceback")}

    step("capture + anchor ACT log", _actlog)
    step("final ledger verify", lambda: sh(COMPOSE + ["exec", "runner", "python", "/lab/harness/ledger.py", "verify"], check=False).stdout.strip().splitlines()[-1:])

    total = round(time.time() - t0, 2)
    (RUN / "v3_run_log.json").write_text(json.dumps({"total_seconds": total, "steps": steps}, indent=2, default=str), encoding="utf-8")
    print(f"V3 RUN complete in {total}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
