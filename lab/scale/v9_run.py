"""V9 orchestrator - the scale ladder, then recovery, then the O-11 confirmation.

    python lab/scale/v9_run.py [--rungs 100,1000,10000,100000] [--dists realistic,worst]
                               [--skip-ladder] [--skip-recovery]

Each step is a separate interpreter (fixtures / measure / recovery bind settings
at import), every produced artifact is hash-anchored in the lab ledger before
the next step reads it, and a failing step is recorded and does not stop the
ladder. Order ends with worst/100k loaded, which is what recovery restores.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / "backend" / ".venv" / "Scripts" / "python.exe"
LEDGER = ROOT / "lab" / "harness" / "ledger.py"
RESULTS = ROOT / "lab" / "run" / "results"
LOG = ROOT / "lab" / "run" / "v9.log"


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).strftime('%H:%M:%S')}Z {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run(args: list[str], *, timeout: int = 7200) -> tuple[int, str]:
    p = subprocess.run([str(PY), *args], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    out = (p.stdout or "") + (p.stderr or "")
    tail = "\n".join(l for l in out.splitlines() if "Warning" not in l and "warnings.warn" not in l)[-4000:]
    return p.returncode, tail


def anchor(*paths: Path) -> None:
    existing = [str(p) for p in paths if p.exists()]
    if existing:
        rc, out = run([str(LEDGER), "anchor", *existing], timeout=300)
        log(f"ledger anchor rc={rc}: {out.splitlines()[-1] if out else ''}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rungs", default="100,1000,10000,100000")
    ap.add_argument("--dists", default="realistic,worst")
    ap.add_argument("--skip-ladder", action="store_true")
    ap.add_argument("--skip-recovery", action="store_true")
    a = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    if not (RESULTS / "ledger.jsonl").exists():
        rc, out = run([str(LEDGER), "init"], timeout=120)
        log(f"ledger init rc={rc} {out.strip()[-200:]}")
    summary: dict = {"started": datetime.now(timezone.utc).isoformat(), "steps": []}

    if not a.skip_ladder:
        for dist in a.dists.split(","):
            for rung in [int(x) for x in a.rungs.split(",")]:
                t = time.perf_counter()
                log(f"== fixtures dist={dist} rung={rung}")
                rc, out = run([str(ROOT / "lab/scale/fixtures.py"), "--rung", str(rung), "--dist", dist], timeout=3600)
                log(f"fixtures rc={rc} in {time.perf_counter() - t:.0f}s :: {out.splitlines()[-1] if out else ''}")
                manifest = RESULTS / f"v9_fixture_{dist}_{rung}.json"
                anchor(manifest)
                step = {"dist": dist, "rung": rung, "fixtures_rc": rc, "fixtures_s": round(time.perf_counter() - t)}
                if rc == 0 and manifest.exists():
                    t = time.perf_counter()
                    log(f"== measure dist={dist} rung={rung}")
                    rc2, out2 = run([str(ROOT / "lab/scale/measure.py"), "--manifest", str(manifest)], timeout=7200)
                    log(f"measure rc={rc2} in {time.perf_counter() - t:.0f}s")
                    for line in out2.splitlines()[-40:]:
                        log("   " + line)
                    step.update({"measure_rc": rc2, "measure_s": round(time.perf_counter() - t)})
                    anchor(RESULTS / f"v9_measure_{dist}_{rung}.json")
                else:
                    step["fixtures_error"] = out[-1500:]
                summary["steps"].append(step)
                (RESULTS / "v9_run_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")

    if not a.skip_recovery:
        t = time.perf_counter()
        log("== recovery")
        rc, out = run([str(ROOT / "lab/scale/recovery.py")], timeout=7200)
        log(f"recovery rc={rc} in {time.perf_counter() - t:.0f}s")
        for line in out.splitlines()[-60:]:
            log("   " + line)
        summary["recovery_rc"] = rc
        anchor(RESULTS / "v9_recovery.json")

    rc, out = run([str(ROOT / "lab/scale/o11_check.py")], timeout=300)
    log(f"o11 rc={rc} :: {out.splitlines()[-1] if out else ''}")
    anchor(RESULTS / "v9_o11.json")
    summary["finished"] = datetime.now(timezone.utc).isoformat()
    (RESULTS / "v9_run_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    rc, out = run([str(LEDGER), "verify"], timeout=300)
    log(f"ledger verify rc={rc} :: {out.strip().splitlines()[-1] if out.strip() else ''}")


if __name__ == "__main__":
    main()
