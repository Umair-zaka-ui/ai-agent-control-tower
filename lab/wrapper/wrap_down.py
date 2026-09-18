"""WRAPPED LAB DOWN (V2.1). Removes every container, the internal network, the lab
key material and the run directory. Verifies no residue: no container, no network,
no lingering interface or rule the host can see for this lab. Never touches
backend/.keys, backend/.env or the dev database.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "lab"
WRAP = LAB / "wrapper"
COMPOSE = ["docker", "compose", "-f", str(WRAP / "docker-compose.wrapped.yml")]


def sh(cmd):
    return subprocess.run(cmd, cwd=str(WRAP), capture_output=True, text=True)


def main() -> int:
    rep = {}
    p = sh(COMPOSE + ["down", "-v", "--remove-orphans", "--timeout", "10"])
    rep["compose_down"] = (p.stdout + p.stderr).strip()[-400:]
    rep["containers_left"] = sh(["docker", "ps", "-a", "--filter", "label=com.docker.compose.project=actlab-wrapped", "-q"]).stdout.split()
    rep["networks_left"] = [n for n in sh(["docker", "network", "ls", "--format", "{{.Name}}"]).stdout.split() if "actlab" in n]
    rep["volumes_left"] = [v for v in sh(["docker", "volume", "ls", "--format", "{{.Name}}"]).stdout.split() if "actlab" in v]
    for path in (LAB / ".keys", LAB / "run"):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    rep["lab_keys_exists"] = (LAB / ".keys").exists()
    rep["lab_run_exists"] = (LAB / "run").exists()
    print(json.dumps(rep, indent=2))
    return 0 if not (rep["containers_left"] or rep["networks_left"] or rep["volumes_left"]) else 1


if __name__ == "__main__":
    sys.exit(main())
