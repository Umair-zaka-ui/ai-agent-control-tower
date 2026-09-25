"""O-11 confirmation (informational, §9): does the backend image build context
still embed key material? Structural check on the current tree - no image is
built, nothing is modified."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def main() -> None:
    di = BACKEND / ".dockerignore"
    patterns = [l.strip() for l in di.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")] \
        if di.exists() else []
    excludes_keys = any(p.rstrip("/") in (".keys", "**/.keys", "backend/.keys") or p.startswith(".keys") for p in patterns)
    dockerfile = BACKEND / "Dockerfile"
    copies = [l.strip() for l in dockerfile.read_text(encoding="utf-8").splitlines() if re.match(r"^(COPY|ADD)\b", l.strip())] \
        if dockerfile.exists() else []
    copies_all = any(re.match(r"^COPY\s+\.\s+\.", c) or re.match(r"^COPY\s+\.\s+/", c) for c in copies)
    compose = ROOT / "docker-compose.yml"
    ctx = re.findall(r"build:\s*(\S+)", compose.read_text(encoding="utf-8")) if compose.exists() else []
    keys = BACKEND / ".keys"
    files = list(keys.glob("*")) if keys.exists() else []
    private = [f for f in files if f.name.endswith(".pem") and not f.name.endswith(".pub.pem")]
    residue = [f for f in files if f.name.startswith("test-")]
    size_mb = round(sum(f.stat().st_size for f in files) / 1e6, 1)
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8") if (ROOT / ".gitignore").exists() else ""
    out = {
        "dockerignore_path": str(di.relative_to(ROOT)) if di.exists() else None,
        "dockerignore_patterns": patterns,
        "dockerignore_excludes_keys": excludes_keys,
        "dockerfile_copy_lines": copies,
        "dockerfile_copies_whole_context": copies_all,
        "compose_build_contexts": ctx,
        "keys_dir_exists": keys.exists(),
        "keys_dir_files": len(files),
        "keys_dir_private_pems": len(private),
        "keys_dir_has_encryption_key": (keys / "model_credentials.key").exists(),
        "keys_dir_test_residue_files": len(residue),
        "keys_dir_size_mb": size_mb,
        "git_ignores_keys": ".keys/" in gitignore,
        "o11_stands": (not excludes_keys) and copies_all and keys.exists() and (len(private) > 0 or (keys / "model_credentials.key").exists()),
    }
    (ROOT / "lab" / "run" / "results" / "v9_o11.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("dockerignore_excludes_keys", "dockerfile_copies_whole_context", "keys_dir_files",
                                          "keys_dir_private_pems", "keys_dir_test_residue_files", "keys_dir_size_mb", "o11_stands")}))


if __name__ == "__main__":
    main()
