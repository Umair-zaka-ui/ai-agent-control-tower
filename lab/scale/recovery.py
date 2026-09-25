"""V9 recovery orchestrator (§6): M4.11/M4.11a key continuity + M5 durable
state under a REAL dump/restore, on lab keys and lab databases only.

    python lab/scale/recovery.py [--scale-db act_v9] [--manifest lab/run/results/v9_fixture_worst_100000.json]

Writes lab/run/results/v9_recovery.json (no secrets). Every scenario runs in
its own interpreter (recovery_step.py) with its own DB + key directory.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import labenv  # noqa: E402

ROOT = labenv.ROOT
PY = ROOT / "backend" / ".venv" / "Scripts" / "python.exe"
STEP = ROOT / "lab" / "scale" / "recovery_step.py"
RECDIR = ROOT / "lab" / "run" / "recovery"
KBASE = ROOT / "lab" / ".keys" / "v9rec"
SUPER_ENV = {**os.environ, "PGPASSWORD": labenv.PG_SUPER[1]}
APP_ENV = {**os.environ, "PGPASSWORD": labenv.APP_PW}
REPORT: dict = {"scenarios": {}, "timings_s": {}}


def log(msg: str) -> None:
    print(msg, flush=True)


def psql(sql: str, db: str = "postgres") -> str:
    p = subprocess.run([str(labenv.PG_BIN / "psql.exe"), "-h", labenv.PG_HOST, "-p", labenv.PG_PORT, "-U", "postgres",
                        "-d", db, "-tA", "-c", sql], env=SUPER_ENV, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr[-400:])
    return p.stdout.strip()


def fresh_db(name: str) -> None:
    psql(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{name}' AND pid<>pg_backend_pid()")
    psql(f"DROP DATABASE IF EXISTS {name}")
    psql(f"CREATE DATABASE {name} OWNER {labenv.APP_USER}")


def migrate(name: str) -> None:
    env = {**os.environ, "DATABASE_URL": labenv.db_url(name)}
    p = subprocess.run([str(PY), "-m", "alembic", "upgrade", "head"], cwd=str(ROOT / "backend"), env=env,
                       capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr[-600:])


def step(name: str, db: str, keys: Path, extra: dict | None = None, expect: dict | None = None) -> dict:
    env = {**os.environ}
    if expect:
        env["V9_EXPECT"] = json.dumps(expect)
    args = [str(PY), str(STEP), name, db, str(keys)]
    if extra:
        args.append(json.dumps(extra))
    p = subprocess.run(args, cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    line = next((l for l in (p.stdout or "").splitlines() if l.startswith("V9JSON ")), None)
    if line is None:
        tail = "\n".join(l for l in ((p.stdout or "") + (p.stderr or "")).splitlines() if "Warning" not in l)[-1200:]
        return {"error": f"step {name} rc={p.returncode}", "tail": tail}
    return json.loads(line[len("V9JSON "):])


def pg_dump(db: str, dest: Path, exclude_data: list[str] | None = None) -> float:
    t = time.perf_counter()
    args = [str(labenv.PG_BIN / "pg_dump.exe"), "-h", labenv.PG_HOST, "-p", labenv.PG_PORT, "-U", "postgres", "-Fc",
            "-f", str(dest)]
    for tname in exclude_data or []:
        args += ["--exclude-table-data", tname]
    p = subprocess.run(args + [db], env=SUPER_ENV, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr[-600:])
    return round(time.perf_counter() - t, 1)


def pg_restore(dump: Path, db: str, jobs: int = 4) -> float:
    t = time.perf_counter()
    p = subprocess.run([str(labenv.PG_BIN / "pg_restore.exe"), "-h", labenv.PG_HOST, "-p", labenv.PG_PORT, "-U", labenv.APP_USER,
                        "-d", db, "-j", str(jobs), "--no-owner", "--no-privileges", str(dump)], env=APP_ENV,
                       capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr[-800:])
    return round(time.perf_counter() - t, 1)


def keys_dir(name: str, *, copy_from: Path | None = None, content: dict | None = None) -> Path:
    d = KBASE / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    if copy_from:
        for f in copy_from.glob("*"):
            if f.is_file():
                shutil.copy2(f, d / f.name)
    for fn, data in (content or {}).items():
        (d / fn).write_bytes(data)
    return d


def scrub(d: dict) -> dict:
    d = dict(d)
    d.pop("secrets", None)
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale-db", default="act_v9")
    ap.add_argument("--manifest", default=str(labenv.RESULTS / "v9_fixture_worst_100000.json"))
    a = ap.parse_args()
    RECDIR.mkdir(parents=True, exist_ok=True)
    good = keys_dir("good")

    # ---- small install: bootstrap -> seed ciphertext + signature -> backup ----
    t = time.perf_counter()
    fresh_db("act_v9_rec"); migrate("act_v9_rec")
    REPORT["scenarios"]["bootstrap"] = step("bootstrap", "act_v9_rec", good)
    seed = step("seed", "act_v9_rec", good)
    REPORT["scenarios"]["seed"] = scrub(seed)
    archive = RECDIR / "key-archive"
    if archive.exists():
        shutil.rmtree(archive)
    REPORT["scenarios"]["backup"] = step("backup", "act_v9_rec", good, {"dest": str(archive)})
    dump_small = RECDIR / "act_v9_rec.dump"
    REPORT["timings_s"]["pg_dump_small"] = pg_dump("act_v9_rec", dump_small)
    log(f"bootstrap/seed/backup done in {time.perf_counter() - t:.0f}s")

    # ---- R1: restore WITH the key (from the archive) ----
    fresh_db("act_v9_r1"); REPORT["timings_s"]["pg_restore_small_r1"] = pg_restore(dump_small, "act_v9_r1")
    restored = keys_dir("restored")
    REPORT["scenarios"]["restore_keys_from_archive"] = step("restore_keys", "act_v9_r1", restored, {"archive": str(archive)})
    REPORT["scenarios"]["R1_restore_with_key"] = step("verify_with_key", "act_v9_r1", restored, expect=seed)
    log(f"R1: {json.dumps(REPORT['scenarios']['R1_restore_with_key'])[:400]}")

    # ---- R2: restore WITHOUT the key -> must fail loud, never regenerate ----
    fresh_db("act_v9_r2"); REPORT["timings_s"]["pg_restore_small_r2"] = pg_restore(dump_small, "act_v9_r2")
    empty = keys_dir("empty")
    REPORT["scenarios"]["R2_restore_without_key"] = step("verify_without_key", "act_v9_r2", empty)
    log(f"R2: {json.dumps(REPORT['scenarios']['R2_restore_without_key'])[:600]}")

    # ---- R4: wrong / malformed / unavailable-provider keys on the restored DB ----
    from cryptography.fernet import Fernet
    variants = {
        "wrong_key": (keys_dir("wrong", copy_from=good, content={"model_credentials.key": Fernet.generate_key()}), {}),
        "malformed_key": (keys_dir("malformed", copy_from=good, content={"model_credentials.key": b"not-a-fernet-key"}), {}),
        "unknown_provider": (keys_dir("unknownprov", copy_from=good), {"ENCRYPTION_KEY_PROVIDER": "VAULT"}),
    }
    dirpath = keys_dir("dirpath", copy_from=good)
    (dirpath / "model_credentials.key").unlink()
    (dirpath / "model_credentials.key").mkdir()
    variants["key_path_is_directory"] = (dirpath, {})
    for name, (kd, env) in variants.items():
        REPORT["scenarios"][f"R4_{name}"] = step("verify_variant", "act_v9_r2", kd, {"variant": name, "env": env})
        log(f"R4 {name}: {json.dumps(REPORT['scenarios'][f'R4_{name}'])[:300]}")

    # ---- R3: zero-ciphertext established install (marker only) ----
    fresh_db("act_v9_r3"); migrate("act_v9_r3")
    REPORT["scenarios"]["R3_marker_only_zero_ciphertext"] = step("marker_only", "act_v9_r3", keys_dir("r3", copy_from=good))
    r3_nokey = keys_dir("r3nokey")
    REPORT["scenarios"]["R3_marker_only_key_absent"] = step("verify_without_key", "act_v9_r3", r3_nokey)
    log(f"R3: {json.dumps(REPORT['scenarios']['R3_marker_only_zero_ciphertext'])[:400]}")

    # ---- M5 durable state + 100k inventory restore ----
    mp = Path(a.manifest)
    if not mp.is_absolute():
        mp = ROOT / mp
    manifest = str(mp) if mp.exists() else None
    scale = a.scale_db
    REPORT["scenarios"]["seed_transient"] = step("seed_transient", scale, good)
    seeded_at = time.time()
    REPORT["scenarios"]["snapshot_before"] = step("durable_snapshot", scale, good, {"manifest": manifest} if manifest else None)
    # ---- disk guard: the restore is a full second copy on the same (nearly full) host disk ----
    for name in ("act_v9_r1", "act_v9_r2", "act_v9_r3", "act_v9_rec"):
        psql(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{name}' AND pid<>pg_backend_pid()")
        psql(f"DROP DATABASE IF EXISTS {name}")
    dump_small.unlink(missing_ok=True)
    db_bytes = int(psql(f"SELECT pg_database_size('{scale}')"))
    sizes = {n: int(b) for n, b in (l.split("|") for l in psql(
        "SELECT relname || '|' || pg_total_relation_size(oid) FROM pg_class WHERE relkind='r' AND relnamespace='public'::regnamespace "
        "ORDER BY pg_total_relation_size(oid) DESC LIMIT 12", scale).splitlines() if l)}
    free = shutil.disk_usage(str(ROOT)).free
    excluded: list[str] = []
    # history-class tables, never the §6 durable set (inventory, ownership, edges, findings, policies, grants,
    # assurance, discovery-source config, budgets, alerts); excluded only while the copy would not fit
    for cand in ("external_gateway_calls", "agent_executions", "execution_attempts", "discovery_observations"):
        need = (db_bytes - sum(sizes.get(x, 0) for x in excluded)) * 1.35 + 1.5e9
        if free >= need:
            break
        excluded.append(cand)
    need = (db_bytes - sum(sizes.get(x, 0) for x in excluded)) * 1.35 + 1.5e9
    REPORT["scenarios"]["disk_guard"] = {"free_gb": round(free / 1e9, 2), "db_gb": round(db_bytes / 1e9, 2),
                                         "need_gb": round(need / 1e9, 2), "largest_tables_mb": {k: round(v / 1e6) for k, v in sizes.items()},
                                         "excluded_table_data": excluded, "fits": free >= need}
    log(f"disk guard: {REPORT['scenarios']['disk_guard']}")
    if free < need:
        REPORT["scenarios"]["scale_restore"] = {"skipped": True, "reason": "insufficient host disk even after excluding history tables"}
        dump_big = None
    else:
        dump_big = RECDIR / f"{scale}.dump"
        REPORT["timings_s"]["pg_dump_scale"] = pg_dump(scale, dump_big, exclude_data=excluded)
        REPORT["timings_s"]["dump_scale_mb"] = round(dump_big.stat().st_size / 1e6, 1)
        fresh_db("act_v9_r100k")
        REPORT["timings_s"]["pg_restore_scale_r100k"] = pg_restore(dump_big, "act_v9_r100k", jobs=2)
        dump_big.unlink(missing_ok=True)   # reclaim space before the snapshot
        psql("ANALYZE", "act_v9_r100k")
    if dump_big is None:
        REPORT["scenarios"]["snapshot_after"] = {"tables": {}, "skipped": True}
    else:
        REPORT["scenarios"]["snapshot_after"] = step("durable_snapshot", "act_v9_r100k", good, {"manifest": manifest} if manifest else None)
    b, af = REPORT["scenarios"]["snapshot_before"], REPORT["scenarios"]["snapshot_after"]
    diff = {}
    if "tables" in b and "tables" in af:
        for tname, v in b["tables"].items():
            if tname in excluded:
                continue   # history data deliberately not dumped (disk guard) - recorded, not compared
            if af["tables"].get(tname) != v:
                diff[tname] = {"before": v, "after": af["tables"].get(tname)}
    REPORT["scenarios"]["durable_state_diff"] = {"tables_compared": len(b.get("tables", {})), "differences": diff,
                                                "identical": not diff,
                                                "open_alerts_preserved": b.get("open_alerts") == af.get("open_alerts"),
                                                "budgets_preserved": b.get("budget_limit_sum") == af.get("budget_limit_sum"),
                                                "open_posture_findings_preserved": b.get("open_posture_findings") == af.get("open_posture_findings"),
                                                "hub_blast_radius_consistent": b.get("hub_blast_radius_agents") == af.get("hub_blast_radius_agents")}
    log(f"durable diff: {json.dumps(REPORT['scenarios']['durable_state_diff'])[:500]}")
    wait = 95 - (time.time() - seeded_at)
    if wait > 0:
        log(f"waiting {wait:.0f}s for the restored heartbeats to age past WORKER_STALE_AFTER_SECONDS")
        time.sleep(wait)
    REPORT["scenarios"]["phantom_workers_after_restore"] = (step("phantom_workers", "act_v9_r100k", good) if dump_big is not None
                                                          else {"skipped": True})
    log(f"phantom: {json.dumps(REPORT['scenarios']['phantom_workers_after_restore'])[:400]}")

    for name in ("act_v9_r1", "act_v9_r2", "act_v9_r3", "act_v9_r100k", "act_v9_rec"):
        try:
            psql(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{name}' AND pid<>pg_backend_pid()")
            psql(f"DROP DATABASE IF EXISTS {name}")
        except Exception as exc:  # noqa: BLE001
            REPORT.setdefault("cleanup_errors", []).append(f"{name}: {exc}")
    dump_small.unlink(missing_ok=True)
    if dump_big is not None:
        dump_big.unlink(missing_ok=True)
    (labenv.RESULTS / "v9_recovery.json").write_text(json.dumps(REPORT, indent=1, default=str), encoding="utf-8")
    log("wrote v9_recovery.json")


if __name__ == "__main__":
    main()
