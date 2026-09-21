"""EVIDENCE-HASH LEDGER (V3 prerequisite, from V2.1 §J).

An append-only hash chain over every V3 result/evidence file, so a
host-initiated channel (docker exec, the bind mount) cannot silently alter a
recorded result without breaking the chain. This is LAB TOOLING -- it imports
nothing from ACT and governs nothing in ACT; it only anchors the lab's own
evidence.

Each entry:  {seq, ts, path, sha256, prev, entry_hash}
  sha256      = SHA-256 of the file's bytes at anchor time
  prev        = entry_hash of the previous entry ("" for the genesis entry)
  entry_hash  = SHA-256 over "seq|ts|path|sha256|prev"

The chain lives at lab/run/results/ledger.jsonl (one JSON object per line).
`verify` recomputes every entry_hash and re-hashes every still-present file;
a mismatch is reported, never silently repaired.

Usage:
    python lab/harness/ledger.py init
    python lab/harness/ledger.py anchor <file> [<file> ...]
    python lab/harness/ledger.py verify
    python lab/harness/ledger.py active     # exit 0 iff the chain exists and verifies
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

RUN = Path(__file__).resolve().parents[1] / "run"
RES = RUN / "results"
LEDGER = RES / "ledger.jsonl"


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _entry_hash(seq: int, ts: str, path: str, sha: str, prev: str) -> str:
    return hashlib.sha256(f"{seq}|{ts}|{path}|{sha}|{prev}".encode()).hexdigest()


def _read() -> list[dict]:
    if not LEDGER.exists():
        return []
    return [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(RUN.parents[1]))
    except ValueError:
        return str(p.resolve())


def init() -> int:
    RES.mkdir(parents=True, exist_ok=True)
    if LEDGER.exists():
        print(f"ledger already present: {len(_read())} entries")
        return 0
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    genesis = {"seq": 0, "ts": ts, "path": "GENESIS", "sha256": _sha256_bytes(b"ACTLAB-V3-LEDGER-GENESIS"),
               "prev": ""}
    genesis["entry_hash"] = _entry_hash(0, ts, "GENESIS", genesis["sha256"], "")
    LEDGER.write_text(json.dumps(genesis) + "\n", encoding="utf-8")
    print(f"ledger initialised at {_rel(LEDGER)} (genesis {genesis['entry_hash'][:16]})")
    return 0


def anchor(paths: list[str]) -> int:
    entries = _read()
    if not entries:
        init()
        entries = _read()
    seq = entries[-1]["seq"]
    prev = entries[-1]["entry_hash"]
    added = []
    with LEDGER.open("a", encoding="utf-8") as fh:
        for p in paths:
            fp = Path(p)
            if not fp.exists():
                print(f"  SKIP (absent): {p}")
                continue
            seq += 1
            ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            sha = _sha256_bytes(fp.read_bytes())
            rel = _rel(fp)
            eh = _entry_hash(seq, ts, rel, sha, prev)
            rec = {"seq": seq, "ts": ts, "path": rel, "sha256": sha, "prev": prev, "entry_hash": eh}
            fh.write(json.dumps(rec) + "\n")
            prev = eh
            added.append(rel)
            print(f"  anchored #{seq} {rel} sha={sha[:16]} entry={eh[:16]}")
    print(f"anchored {len(added)} file(s); head={prev[:16]}")
    return 0


def verify() -> int:
    entries = _read()
    if not entries:
        print("VERIFY FAIL: no ledger")
        return 1
    ok = True
    prev = ""
    for e in entries:
        expect = _entry_hash(e["seq"], e["ts"], e["path"], e["sha256"], prev)
        if expect != e["entry_hash"]:
            print(f"CHAIN BREAK at seq {e['seq']} ({e['path']}): entry_hash mismatch")
            ok = False
        if e["prev"] != prev:
            print(f"CHAIN BREAK at seq {e['seq']}: prev pointer mismatch")
            ok = False
        prev = e["entry_hash"]
        if e["path"] not in ("GENESIS",):
            fp = RUN.parents[1] / e["path"]
            if fp.exists():
                cur = _sha256_bytes(fp.read_bytes())
                if cur != e["sha256"]:
                    print(f"FILE ALTERED after anchor: {e['path']} (anchored {e['sha256'][:16]}, now {cur[:16]})")
                    ok = False
            else:
                print(f"NOTE: anchored file no longer present: {e['path']}")
    if ok:
        print(f"VERIFY OK: {len(entries)} entries, head={prev[:16]}, chain intact, all present files match")
        return 0
    return 1


def active() -> int:
    if not LEDGER.exists():
        print("ledger INACTIVE (absent)")
        return 1
    return verify()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "init":
        return init()
    if cmd == "anchor":
        return anchor(sys.argv[2:])
    if cmd == "verify":
        return verify()
    if cmd == "active":
        return active()
    print(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
