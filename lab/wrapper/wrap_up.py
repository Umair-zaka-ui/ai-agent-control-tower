"""WRAPPED LAB UP (V2.1). Builds the whole V2 lab inside the egress-deny Docker network.

    python lab/wrapper/wrap_up.py              # build + start + wait healthy
    python lab/wrapper/wrap_up.py --baseline   # ...then run the V2 baseline inside the runner
    python lab/wrapper/wrap_up.py --proof      # ...then run the boundary proofs (with and without ACT)

Everything is `docker compose` on lab/wrapper/docker-compose.wrapped.yml. The host never
gets a network path into the lab; it only execs into containers and reads lab/run/.
Timings go to lab/run/wrapped_build_log.json.
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


def main() -> int:
    t0 = time.time(); steps = []
    RUN.mkdir(parents=True, exist_ok=True)
    (LAB / ".keys").mkdir(exist_ok=True)

    def step(name, fn):
        s = time.time(); r = fn(); steps.append({"step": name, "seconds": round(time.time() - s, 2), "result": r})
        print(f"[{steps[-1]['seconds']:>7.2f}s] {name}: {str(r)[:160]}", flush=True)

    step("docker compose build (act image from requirements only; runner = act + node)",
         lambda: sh(COMPOSE + ["build"]).stdout.strip().splitlines()[-1:] or "built")
    step("docker compose up -d --wait (internal network, no published ports)",
         lambda: sh(COMPOSE + ["up", "-d", "--wait", "--wait-timeout", "300"]).stdout.strip()[-200:] or "up")
    step("network is internal", lambda: sh(["docker", "network", "inspect", "actlab-wrapped_lab_net", "--format", "internal={{.Internal}} driver={{.Driver}}"]).stdout.strip())
    step("no published ports", lambda: sh(COMPOSE + ["ps", "--format", "{{.Name}} {{.Ports}}"]).stdout.strip().replace("\n", " | "))
    step("act entrypoint log (masking + bootstrap)", lambda: [l for l in sh(COMPOSE + ["logs", "act"], check=False).stdout.splitlines() if "[act]" in l or "fingerprint" in l][:8])

    if "--proof" in sys.argv:
        env = dict(os.environ, HOST_IP=host_ip())
        def _proof(label):
            sh(COMPOSE + ["exec", "-e", f"HOST_IP={env['HOST_IP']}", "proof", "sh", "/lab/wrapper/boundary_proof.sh"], check=False, timeout=600)
            src = RUN / "results" / "boundary_proof.txt"
            dst = RUN / "results" / f"boundary_proof_{label}.txt"
            shutil.copy(src, dst)
            return dst.read_text(encoding="utf-8").count("rc=")
        step("boundary proof with ACT running", lambda: _proof("act_running"))
        step("stop ACT", lambda: sh(COMPOSE + ["stop", "act"]).returncode)
        step("boundary proof with ACT STOPPED (independence)", lambda: _proof("act_stopped"))
        step("start ACT", lambda: sh(COMPOSE + ["start", "act"]).returncode)

        def _healthy():
            # Poll the container's own healthcheck; never `up --wait` here, which would
            # re-run one-shot dependencies (the canary generator) mid-build.
            for _ in range(60):
                st = sh(["docker", "inspect", "--format", "{{.State.Health.Status}}", "actlab-wrapped-act-1"], check=False).stdout.strip()
                if st == "healthy":
                    return "healthy"
                time.sleep(2)
            return st
        step("act healthy again", _healthy)

    if "--baseline" in sys.argv:
        step("V2 baseline inside the runner", lambda: sh(COMPOSE + ["exec", "runner", "python", "/lab/harness/v2_baseline.py"], check=False, timeout=900).stdout.strip().splitlines()[-1:])

        def _actlog():
            (RUN / "logs").mkdir(parents=True, exist_ok=True)
            txt = sh(COMPOSE + ["logs", "--no-color", "act"], check=False).stdout
            (RUN / "logs" / "act_wrapped.log").write_text(txt, encoding="utf-8")
            return {"lines": len(txt.splitlines()), "canary_marker_hits": txt.count("ACTLAB-CANARY"), "tracebacks": txt.lower().count("traceback")}
        step("ACT container log captured + canary grep", _actlog)

    total = round(time.time() - t0, 2)
    (RUN / "wrapped_build_log.json").write_text(json.dumps({"total_seconds": total, "steps": steps}, indent=2, default=str), encoding="utf-8")
    print(f"WRAPPED LAB UP in {total}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
