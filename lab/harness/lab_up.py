"""LAB UP -- build the whole V2 lab from committed artifacts (V2 §8).

    python lab/harness/lab_up.py            # full build
    python lab/harness/lab_up.py --otlp-down  # observability in down-collector mode

Steps (each timed and written to lab/run/build_log.json):
  1. docker compose up (lab PostgreSQL 17, loopback-only, two databases)
  2. generate canaries (lab/run/canaries.json)
  3. alembic upgrade head against act_lab, with the LAB env only
  4. bootstrap LAB key material into the fresh DB (ENCRYPTION_KEY_ALLOW_BOOTSTRAP=true
     for this single command only; the running ACT keeps it false)
  5. start host processes, all bound to 127.0.0.1: canary zone, registry, OTLP
     collector, five MCP servers, ACT (uvicorn, port 8802, lab env)
  6. wait for readiness; write lab/run/pids.json

The host must have: Docker, Python venv at backend/.venv (ACT's own), Node >= 20.
ACT is started from backend/ with the lab env file; production .env is NOT loaded
because every variable it would supply is overridden by lab/env/act-lab.env
values exported into the process environment (pydantic-settings: env beats .env).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "lab"
RUN = LAB / "run"
BACKEND = ROOT / "backend"
PY = str(BACKEND / ".venv" / "Scripts" / "python.exe") if os.name == "nt" else str(BACKEND / ".venv" / "bin" / "python")
ACT_PORT = 8802


def lab_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL",)}
    for line in (LAB / "env" / "act-lab.env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    env["PYTHONUNBUFFERED"] = "1"
    return env


def run(cmd, cwd, env=None, check=True, timeout=600):
    p = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise SystemExit(f"FAILED: {' '.join(cmd)}\n{p.stdout[-2000:]}\n{p.stderr[-2000:]}")
    return p


def spawn(name, cmd, cwd, env=None):
    (RUN / "logs").mkdir(parents=True, exist_ok=True)
    log = open(RUN / "logs" / f"{name}.log", "ab")
    kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}
    p = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=log, stderr=subprocess.STDOUT, **kw)
    return p.pid


def wait_http(url, seconds=60):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status < 500:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def wait_file(path: Path, seconds=30):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(0.25)
    return False


def main() -> int:
    t0 = time.time()
    steps = []
    RUN.mkdir(parents=True, exist_ok=True)
    env = lab_env()

    def step(name, fn):
        s = time.time()
        r = fn()
        steps.append({"step": name, "seconds": round(time.time() - s, 2), "result": r})
        print(f"[{steps[-1]['seconds']:>6.2f}s] {name}: {r}", flush=True)

    # 1. Postgres (docker)
    def _db():
        run(["docker", "compose", "-f", "docker-compose.lab.yml", "up", "-d", "--wait"], LAB, timeout=300)
        return "lab_db up (127.0.0.1:5433)"
    step("docker compose up lab_db", _db)

    # 2. canaries
    step("generate canaries", lambda: run([PY, str(LAB / "canaries.py")], LAB).stdout.strip())

    # 3. schema
    step("alembic upgrade head (act_lab)", lambda: run([PY, "-m", "alembic", "upgrade", "head"], BACKEND, env=env).stdout.strip().splitlines()[-1:] or "ok")

    # 4. lab keys (bootstrap gate ON for this one command only)
    def _keys():
        (LAB / ".keys").mkdir(exist_ok=True)
        e = dict(env, ENCRYPTION_KEY_ALLOW_BOOTSTRAP="true")
        p = run([PY, "-m", "app.security.keys", "bootstrap"], BACKEND, env=e, check=False)
        status = run([PY, "-m", "app.security.keys", "status"], BACKEND, env=env, check=False).stdout
        return {"bootstrap_rc": p.returncode, "bootstrap_out": (p.stdout + p.stderr)[-400:].strip(), "status": status.strip()}
    step("bootstrap LAB key material", _keys)

    # 5. host processes
    pids = {}
    def _svc():
        pids["canary_zone"] = spawn("canary_zone", [PY, str(LAB / "services" / "canary_zone.py")], LAB, env)
        pids["registry"] = spawn("registry", [PY, str(LAB / "services" / "registry.py")], LAB, env)
        if "--otlp-down" in sys.argv:
            run([PY, str(LAB / "services" / "otlp_collector.py"), "--down"], LAB)
            pids["otlp_collector"] = None
        else:
            pids["otlp_collector"] = spawn("otlp_collector", [PY, str(LAB / "services" / "otlp_collector.py")], LAB, env)
        for v in ("trusted", "unknown", "risky", "impersonator", "rugpull"):
            pids[f"mcp_{v}"] = spawn(f"mcp_{v}", [PY, str(LAB / "mcp" / "mcp_server.py"), v], LAB, env)
        pids["act"] = spawn("act", [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(ACT_PORT), "--log-level", "info"], BACKEND, env)
        return pids
    step("start lab processes", _svc)

    def _ready():
        ok = {
            "canary_zone": wait_file(RUN / "canary_zone.ready"),
            "registry": wait_http("http://127.0.0.1:8811/agents"),
            "mcp_trusted": wait_http("http://127.0.0.1:8831/manifest"),
            "act": wait_http(f"http://127.0.0.1:{ACT_PORT}/docs", 120),
        }
        if "--otlp-down" not in sys.argv:
            ok["otlp_collector"] = wait_file(RUN / "otlp_collector.ready")
        return ok
    step("readiness", _ready)

    (RUN / "pids.json").write_text(json.dumps(pids, indent=2), encoding="utf-8")
    total = round(time.time() - t0, 2)
    (RUN / "build_log.json").write_text(json.dumps({"total_seconds": total, "steps": steps, "act_base": f"http://127.0.0.1:{ACT_PORT}"}, indent=2), encoding="utf-8")
    print(f"LAB UP in {total}s -> http://127.0.0.1:{ACT_PORT}", flush=True)
    failed = [k for k, v in steps[-1]["result"].items() if not v]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
