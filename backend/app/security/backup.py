"""Phase M4.11 M4.11-FR-020..022, M4.11-FR-030 — the supported key-material
recovery archive.

A verified database dump plus a Git bundle is *not* sufficient to recover
this platform (the pre-M4.11 gap RECOVERY.md documented). This module
produces the missing piece: a self-describing copy of the encryption key
and the signing private keys, with:

- a **manifest that names the required artifacts** and records a non-secret
  fingerprint for each — never the key contents (M4.11-FR-021);
- a **SHA-256 checksum** for every artifact, so a restore can verify
  integrity before trusting the material (M4.11-FR-021);
- restore guidance (``docs/security/key-management.md``) — the archive is
  copied into place, then ``python -m app.security.keys verify`` runs the
  key-continuity check as part of the restore (M4.11-FR-022, §11).

The archive itself contains raw key bytes, so it must be stored with the
same encrypted-at-rest treatment as a database snapshot (7-Zip AES-256 to
the marked recovery target — see RECOVERY.md). This module writes the plain
files; encrypting the containing archive is the operator step, exactly as
for ``Export-ControlTowerSecrets.ps1``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.security.encryption_provider import key_fingerprint

SCHEMA_VERSION = 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _signing_key_dir() -> Path:
    return Path(settings.SIGNING_KEY_PATH)


def _encryption_key_file() -> Path:
    return Path(settings.MODEL_CREDENTIAL_ENCRYPTION_KEY_PATH)


def create_key_material_archive(destination: str | Path) -> dict:
    """Copy the required key material into ``destination`` alongside a
    manifest and checksums. Returns the manifest dict."""
    dest = Path(destination)
    keys_out = dest / "keys"
    keys_out.mkdir(parents=True, exist_ok=True)

    artifacts: list[dict] = []

    enc_file = _encryption_key_file()
    encryption_meta: dict = {"provider": settings.ENCRYPTION_KEY_PROVIDER, "present": enc_file.exists()}
    if enc_file.exists():
        target = keys_out / enc_file.name
        shutil.copy2(enc_file, target)
        encryption_meta["key_file"] = f"keys/{enc_file.name}"
        encryption_meta["fingerprint"] = key_fingerprint(enc_file.read_bytes())
        artifacts.append(
            {"name": f"keys/{enc_file.name}", "sha256": _sha256(target), "bytes": target.stat().st_size}
        )

    signing_dir = _signing_key_dir()
    signing_meta: dict = {"key_dir": str(signing_dir), "keys": []}
    if signing_dir.exists():
        for pem in sorted(signing_dir.glob("*.pem")):
            target = keys_out / pem.name
            shutil.copy2(pem, target)
            artifacts.append(
                {"name": f"keys/{pem.name}", "sha256": _sha256(target), "bytes": target.stat().st_size}
            )
            signing_meta["keys"].append(
                {"file": f"keys/{pem.name}", "public": pem.name.endswith(".pub.pem")}
            )

    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "project": "ai-agent-control-tower",
        "kind": "key-material",
        "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "encryption": encryption_meta,
        "signing": signing_meta,
        "artifacts": artifacts,
        "restore": (
            "1. decrypt this archive to a scratch dir; "
            "2. copy keys/* back into backend/.keys/ (0600); "
            "3. set backend/.env; "
            "4. run `python -m app.security.keys verify` — it must print OK before serving traffic."
        ),
    }
    (dest / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (dest / "SHA256SUMS.txt").write_text(
        "".join(f"{a['sha256']}  {a['name']}\n" for a in artifacts), encoding="utf-8"
    )
    return manifest


def verify_key_material_archive(archive_dir: str | Path) -> list[str]:
    """Check every artifact's checksum against the manifest. Returns a list
    of problems (empty == the archive is intact)."""
    root = Path(archive_dir)
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    problems: list[str] = []
    for artifact in manifest["artifacts"]:
        path = root / artifact["name"]
        if not path.exists():
            problems.append(f"missing artifact: {artifact['name']}")
            continue
        if _sha256(path) != artifact["sha256"]:
            problems.append(f"checksum mismatch: {artifact['name']}")
    return problems


def restore_key_material_archive(archive_dir: str | Path) -> list[Path]:
    """Copy the archived key files back into their configured locations.
    Refuses to overwrite an existing key file (the restore-into-unsafe-target
    safeguard, mirroring the PowerShell scripts)."""
    root = Path(archive_dir)
    problems = verify_key_material_archive(root)
    if problems:
        raise RuntimeError("key-material archive failed verification: " + "; ".join(problems))

    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    restored: list[Path] = []

    enc = manifest.get("encryption", {})
    if enc.get("key_file"):
        target = _encryption_key_file()
        if target.exists():
            raise RuntimeError(f"refusing to overwrite an existing encryption key file: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / enc["key_file"], target)
        restored.append(target)

    signing_dir = _signing_key_dir()
    for key in manifest.get("signing", {}).get("keys", []):
        target = signing_dir / Path(key["file"]).name
        if target.exists():
            continue  # public keys legitimately already exist post-DB-restore; never clobber
        signing_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / key["file"], target)
        restored.append(target)

    return restored
