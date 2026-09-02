"""Phase M4.11 — the operator CLI for key material.

    python -m app.security.keys status     # install mode + provider state (no secrets)
    python -m app.security.keys verify      # run the fail-loud integrity check; exit 1 on failure
    python -m app.security.keys bootstrap   # provision fresh key material — NEW installs only
    python -m app.security.keys backup DIR  # write the recovery archive to DIR
    python -m app.security.keys rotate-encryption  # print a new key + the rotation procedure

None of these ever print a key, a secret, or a Fernet token. ``verify`` is
the command a restore runbook calls after the database and key files are in
place (docs/security/key-management.md).
"""

from __future__ import annotations

import argparse
import sys

from app.core.database import SessionLocal


def _status(db) -> int:
    from app.security.encryption_provider import get_encryption_key_provider
    from app.security.install_mode import detect_install_mode

    report = detect_install_mode(db)
    print(f"install mode:            {report.mode.value}  ({report.reason})")
    print(f"bootstrap marker:        {'present' if report.bootstrap_marker else 'ABSENT'}")
    print(f"encrypted-state tables:  {', '.join(report.encrypted_state_tables) or '(none)'}")
    print(f"signed-state tables:     {', '.join(report.signed_state_tables) or '(none)'}")
    try:
        print(f"encryption provider:     {get_encryption_key_provider().describe()}")
    except Exception as exc:  # noqa: BLE001 - status must not itself crash
        print(f"encryption provider:     unavailable ({type(exc).__name__})")
    return 0


def _verify(db) -> int:
    from app.security.errors import KeyMaterialError
    from app.security.key_integrity import verify_key_material

    try:
        report = verify_key_material(db)
    except KeyMaterialError as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 1
    print(f"OK    {report.as_log_line()}")
    return 0


def _bootstrap(db) -> int:
    from app.security.bootstrap import bootstrap_key_material
    from app.security.errors import KeyMaterialError

    try:
        result = bootstrap_key_material(db)
    except KeyMaterialError as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 1
    verb = "adopted the present" if result.adopted_existing_key else "provisioned fresh"
    print(f"{verb} key material and recorded the bootstrap marker:")
    print(f"  encryption: provider={result.encryption_provider} fingerprint={result.encryption_fingerprint}")
    print(
        f"  signing:    key_id={result.signing_key_id} v{result.signing_key_version} "
        f"public_fingerprint={result.signing_public_key_fingerprint}"
    )
    print("back this up now: python -m app.security.keys backup <recovery-target>")
    return 0


def _backup(db, dest: str) -> int:
    from app.security.backup import create_key_material_archive

    manifest = create_key_material_archive(dest)
    print(f"wrote key-material archive to {dest}")
    for artifact in manifest["artifacts"]:
        print(f"  {artifact['name']:40s} sha256={artifact['sha256']}")
    print("store this on the marked recovery target with the same encrypted-at-rest treatment as a snapshot.")
    return 0


def _rotate_encryption(db) -> int:
    from cryptography.fernet import Fernet

    from app.security.encryption_provider import get_encryption_key_provider, key_fingerprint

    new_key = Fernet.generate_key()
    current = get_encryption_key_provider()
    print("encryption-key rotation (no re-encryption required up front):")
    print(f"  1. set MODEL_CREDENTIAL_ENCRYPTION_KEY to the NEW key (fingerprint {key_fingerprint(new_key)})")
    if current.is_present():
        print(f"  2. move the CURRENT key (fingerprint {current.fingerprint()}) into MODEL_CREDENTIAL_ENCRYPTION_KEYS")
    print("  3. restart — the startup check registers a canary for the new key and keeps decrypting old data")
    print("  4. new writes use the new key; re-encrypt lazily on next write, or run a background re-encrypt pass")
    print(f"NEW KEY: {new_key.decode()}")
    print("(shown once — store it in the recovery archive and a password manager; it will not be shown again)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.security.keys")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("verify")
    sub.add_parser("bootstrap")
    backup = sub.add_parser("backup")
    backup.add_argument("destination")
    sub.add_parser("rotate-encryption")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.command == "status":
            return _status(db)
        if args.command == "verify":
            return _verify(db)
        if args.command == "bootstrap":
            return _bootstrap(db)
        if args.command == "backup":
            return _backup(db, args.destination)
        if args.command == "rotate-encryption":
            return _rotate_encryption(db)
        return 2
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
