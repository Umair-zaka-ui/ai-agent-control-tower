"""LAB DOWN -- tear the whole lab down. Nothing survives (V2 §8).

Kills every lab process recorded in lab/run/pids.json (and any stray listener
on the lab ports), removes the lab Postgres container and its data
(`docker compose down -v`), deletes LAB key material (lab/.keys) and the run
directory (canaries, logs, results). Production .keys/ and the dev database are
never touched: this script only knows the lab paths and the lab compose file.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "lab"
RUN = LAB / "run"
LAB_PORTS = (8802, 8811, 8812, 8821, 8822, 8823, 8824, 8825, 8831, 8832, 8833, 8834, 8835)


def kill_pid(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        subprocess.run(["kill", "-9", str(pid)], capture_output=True)


def stray_listeners() -> list[int]:
    if os.name != "nt":
        return []
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and "LISTENING" in line:
            addr = parts[1]
            for p in LAB_PORTS:
                if addr.endswith(f":{p}"):
                    pids.add(int(parts[-1]))
    return sorted(pids)


def main() -> int:
    report = {"killed": [], "stray_killed": [], "compose": None, "removed": []}
    pids_file = RUN / "pids.json"
    if pids_file.exists():
        for name, pid in json.loads(pids_file.read_text(encoding="utf-8")).items():
            if pid:
                kill_pid(int(pid)); report["killed"].append({name: pid})
    for pid in stray_listeners():
        kill_pid(pid); report["stray_killed"].append(pid)
    p = subprocess.run(["docker", "compose", "-f", "docker-compose.lab.yml", "down", "-v", "--remove-orphans"],
                       cwd=str(LAB), capture_output=True, text=True)
    report["compose"] = (p.stdout + p.stderr).strip()[-300:]
    for path in (LAB / ".keys", RUN):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True); report["removed"].append(str(path.relative_to(ROOT)))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
