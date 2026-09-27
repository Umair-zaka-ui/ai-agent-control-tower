"""DT1 Stage 1 - content hashes and the separate HASH_ANCHOR record (§8).

Content hashes are SHA-256 over the canonical bytes ON DISK of estate_truth,
observability_contract and agent_property_matrix. ``combined_root`` is
SHA-256 over the three hex digests concatenated in that fixed order
(truth | contract | matrix). None of the hashed artifacts contains a timestamp,
a path, or any hash of itself. The anchor record carries the hashes plus the
non-deterministic sealing facts (created_at, git_commit) and is NOT part of any
content hash - it records WHEN already-computed hashes were sealed.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from canonical import canonical_bytes, sha256_hex

ARTIFACTS = ("estate_truth.json", "observability_contract.json", "agent_property_matrix.json")
ROOT_ORDER = ("estate_truth_sha256", "observability_contract_sha256", "agent_property_matrix_sha256")


def content_hashes(art_dir: Path) -> dict:
    h = {}
    for name in ARTIFACTS:
        h[name.replace(".json", "_sha256")] = sha256_hex((art_dir / name).read_bytes())
    h["combined_root_sha256"] = sha256_hex("".join(h[k] for k in ROOT_ORDER).encode("ascii"))
    return h


def git_commit(root: Path) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True).stdout.strip()


def seal(art_dir: Path, *, root: Path, seed: str, generator_version: str, schema_grounding_version: str,
         estate_truth_schema_version: str, observability_contract_version: str, matrix_version: str, base_commit: str) -> dict:
    hashes = content_hashes(art_dir)
    anchor = {
        "anchor_version": "1.0.0", "seed": seed, "generator_version": generator_version,
        "schema_grounding_version": schema_grounding_version, "estate_truth_schema_version": estate_truth_schema_version,
        "observability_contract_version": observability_contract_version, "agent_property_matrix_version": matrix_version,
        "git_commit": git_commit(root), "base_commit": base_commit, "combined_root_order": list(ROOT_ORDER), **hashes,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "content hashes are over canonical artifact bytes and exclude this record; created_at records when they were sealed",
    }
    (art_dir / "anchor.json").write_bytes(canonical_bytes(anchor))
    return anchor


def verify(art_dir: Path) -> dict:
    anchor = json.loads((art_dir / "anchor.json").read_text(encoding="utf-8"))
    now = content_hashes(art_dir)
    diffs = {k: {"anchor": anchor.get(k), "recomputed": v} for k, v in now.items() if anchor.get(k) != v}
    return {"ok": not diffs, "differences": diffs, "anchor_created_at": anchor.get("created_at"), "git_commit": anchor.get("git_commit")}
