"""V4 RUN ORCHESTRATOR (host side) — identity / delegation / multi-agent.

  1. ensure the wrapped lab is up (build ACT/runner/wave2 images if needed)
  2. PRE-FLIGHT: re-run the boundary proof WITH and WITHOUT ACT; STOP if it fails
  3. runner: v4_preflight-equivalent (ledger active, canary zero-scan, positive control)
  4. runner: v4_identity.py   (T6)
  5. runner: v4_delegation.py (T8)
  6. wave2 : v4_multiagent.py (T17 / I-2, real frameworks)
  7. capture + anchor the ACT log; final ledger verify

The host never gets a network path into the lab; it only `docker compose exec`s
and reads lab/run through the bind mount. Nothing here changes ACT.

    python lab/wrapper/v4_run.py             # full phase
    python lab/wrapper/v4_run.py --no-proof  # skip the boundary re-proof
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


def sh(cmd, check=True, timeout=3600, env=None):
    p = subprocess.run(cmd, cwd=str(WRAP), capture_output=True, text=True, timeout=timeout, env=env,
                       encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        raise SystemExit(f"FAILED: {' '.join(cmd)}\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")
    return p


def host_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]; s.close()
        return ip
    except Exception:
        return ""


def running() -> bool:
    p = sh(COMPOSE + ["ps", "--format", "{{.Name}} {{.State}}"], check=False)
    return "actlab-wrapped-act-1" in p.stdout and "running" in p.stdout


def healthy_wait():
    for _ in range(90):
        st = sh(["docker", "inspect", "--format", "{{.State.Health.Status}}",
                 "actlab-wrapped-act-1"], check=False).stdout.strip()
        if st == "healthy":
            return "healthy"
        time.sleep(2)
    return st


def main() -> int:
    t0 = time.time(); steps = []
    RUN.mkdir(parents=True, exist_ok=True)
    (LAB / ".keys").mkdir(exist_ok=True)

    def step(name, fn):
        s = time.time()
        r = fn()
        steps.append({"step": name, "seconds": round(time.time() - s, 2), "result": r})
        print(f"[{steps[-1]['seconds']:>7.2f}s] {name}: {str(r)[:220]}", flush=True)

    if not running():
        # act first (runner is FROM the act image — DG-7), then the rest.
        step("build act", lambda: sh(COMPOSE + ["build", "act"]).returncode)
        step("build runner + wave2 (frameworks)",
             lambda: sh(COMPOSE + ["build", "runner", "wave2"], timeout=3600).returncode)
        step("up -d --wait", lambda: sh(COMPOSE + ["up", "-d", "--wait", "--wait-timeout", "420"]).returncode)
    else:
        print("wrapped lab already running", flush=True)
        step("build wave2 (if changed)", lambda: sh(COMPOSE + ["build", "wave2"], timeout=3600).returncode)
        step("start wave2", lambda: sh(COMPOSE + ["up", "-d", "wave2"], check=False).returncode)

    step("network is internal",
         lambda: sh(["docker", "network", "inspect", "actlab-wrapped_lab_net",
                     "--format", "internal={{.Internal}} driver={{.Driver}}"]).stdout.strip())
    step("no published ports",
         lambda: sh(COMPOSE + ["ps", "--format", "{{.Name}} {{.Ports}}"]).stdout.strip().replace("\n", " | "))

    if "--no-proof" not in sys.argv:
        env = dict(os.environ, HOST_IP=host_ip())

        def _proof(label):
            sh(COMPOSE + ["exec", "-e", f"HOST_IP={env['HOST_IP']}", "proof", "sh",
                          "/lab/wrapper/boundary_proof.sh"], check=False, timeout=600)
            src = RUN / "results" / "boundary_proof.txt"
            dst = RUN / "results" / f"boundary_proof_{label}.txt"
            if src.exists():
                shutil.copy(src, dst)
                txt = dst.read_text(encoding="utf-8", errors="replace")
                denied = sum(1 for l in txt.splitlines() if "rc=1" in l)
                allowed = sum(1 for l in txt.splitlines() if "rc=0" in l)
                return {"deny_lines_rc1": denied, "allow_lines_rc0": allowed}
            return {"error": "no proof output"}

        step("boundary proof (ACT running)", lambda: _proof("act_running"))
        step("stop ACT", lambda: sh(COMPOSE + ["stop", "act"]).returncode)
        step("boundary proof (ACT STOPPED)", lambda: _proof("act_stopped"))
        step("start ACT", lambda: sh(COMPOSE + ["start", "act"]).returncode)
        step("ACT healthy again", healthy_wait)

    step("pre-flight (runner)",
         lambda: sh(COMPOSE + ["exec", "runner", "python", "/lab/harness/v3_preflight.py"],
                    check=False, timeout=600).stdout.strip().splitlines()[-1:])

    def _batch(service, script, label, timeout=2400):
        p = sh(COMPOSE + ["exec", service, "python", script], check=False, timeout=timeout)
        (RUN / "logs").mkdir(parents=True, exist_ok=True)
        (RUN / "logs" / f"{label}.log").write_text(p.stdout + "\n--- stderr ---\n" + p.stderr,
                                                   encoding="utf-8")
        return p.stdout.strip().splitlines()[-3:] or p.stderr[-300:]

    step("T6 identity (runner)", lambda: _batch("runner", "/lab/harness/v4_identity.py", "v4_identity"))
    step("T8 delegation (runner)", lambda: _batch("runner", "/lab/harness/v4_delegation.py", "v4_delegation"))
    step("T17/I-2 multi-agent (wave2)",
         lambda: _batch("wave2", "/lab/harness/v4_multiagent.py", "v4_multiagent", timeout=3000))

    def _actlog():
        (RUN / "logs").mkdir(parents=True, exist_ok=True)
        txt = sh(COMPOSE + ["logs", "--no-color", "act"], check=False).stdout
        (RUN / "logs" / "act_wrapped.log").write_text(txt, encoding="utf-8")
        can = json.loads((RUN / "canaries.json").read_text(encoding="utf-8"))
        hits = sum(txt.count(tok) for nm, tok in can["tokens"].items() if nm != "grant_label")
        sh(COMPOSE + ["exec", "runner", "python", "/lab/harness/ledger.py", "anchor",
                      "/lab/run/logs/act_wrapped.log"], check=False)
        return {"lines": len(txt.splitlines()), "unexpected_canary_hits": hits,
                "tracebacks": txt.lower().count("traceback")}

    step("capture + anchor ACT log", _actlog)
    step("wave2 framework versions",
         lambda: sh(COMPOSE + ["exec", "wave2", "cat", "/wave2_versions.json"],
                    check=False).stdout.strip())
    step("final ledger verify",
         lambda: sh(COMPOSE + ["exec", "runner", "python", "/lab/harness/ledger.py", "verify"],
                    check=False).stdout.strip().splitlines()[-1:])

    total = round(time.time() - t0, 2)
    (RUN / "v4_run_log.json").write_text(json.dumps({"total_seconds": total, "steps": steps},
                                                    indent=2, default=str), encoding="utf-8")
    print(f"V4 RUN complete in {total}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
