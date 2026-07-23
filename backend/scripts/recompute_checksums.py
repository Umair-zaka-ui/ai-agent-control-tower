"""Phase 5.2.4 SRS §2.5 — legacy checksum migration script.

Recomputes ``canonical-sha256`` checksums for every ``agent_versions`` row
(and its ``agent_version_snapshots`` row, if one exists) whose
``checksum_algorithm`` is still ``'legacy-sha256'``, and upgrades that
column once the new checksum is written.

Migration ``0027_version_signing`` deliberately does **not** touch existing
checksum values itself — silently recomputing integrity values in a schema
migration, with no audit trail of who ran it or when, is precisely what
this phase exists to prevent. This script is the explicit, operator-invoked,
auditable alternative: it prints exactly what it found and what it changed
(or would change, under ``--dry-run``) every time it runs.

Usage::

    python -m scripts.recompute_checksums --dry-run
    python -m scripts.recompute_checksums
    python -m scripts.recompute_checksums --agent-id <uuid>   # scope to one agent
"""

from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.runtime import AgentVersion, AgentVersionSnapshot
from app.runtime.services import _checksum, _legacy_checksum
from app.runtime.versioning.snapshot import _legacy_checksum_of, checksum_of


def _recompute_version(version: AgentVersion, *, dry_run: bool) -> dict:
    old_checksum = version.checksum
    legacy_verified = _legacy_checksum(version) == old_checksum
    new_checksum = _checksum(version)
    if not dry_run:
        version.checksum = new_checksum
        version.checksum_algorithm = "canonical-sha256"
    return {
        "kind": "version", "id": str(version.id),
        "old_algorithm": "legacy-sha256", "old_checksum": old_checksum,
        "new_algorithm": "canonical-sha256", "new_checksum": new_checksum,
        "legacy_checksum_verified": legacy_verified,
    }


def _recompute_snapshot(snapshot: AgentVersionSnapshot, *, dry_run: bool) -> dict:
    old_checksum = snapshot.checksum
    legacy_verified = _legacy_checksum_of(snapshot.snapshot) == old_checksum
    new_checksum = checksum_of(snapshot.snapshot)
    if not dry_run:
        snapshot.checksum = new_checksum
        snapshot.checksum_algorithm = "canonical-sha256"
    return {
        "kind": "snapshot", "id": str(snapshot.id),
        "old_algorithm": "legacy-sha256", "old_checksum": old_checksum,
        "new_algorithm": "canonical-sha256", "new_checksum": new_checksum,
        "legacy_checksum_verified": legacy_verified,
    }


def run(*, dry_run: bool, agent_id: str | None = None) -> list[dict]:
    """Returns the list of change reports (also used directly by tests, so
    the CLI's printing stays separate from the recomputation logic)."""
    db = SessionLocal()
    try:
        version_stmt = select(AgentVersion).where(AgentVersion.checksum_algorithm == "legacy-sha256")
        if agent_id:
            version_stmt = version_stmt.where(AgentVersion.agent_id == uuid.UUID(agent_id))
        versions = list(db.execute(version_stmt).scalars())
        reports = [_recompute_version(v, dry_run=dry_run) for v in versions]

        snapshot_stmt = select(AgentVersionSnapshot).where(AgentVersionSnapshot.checksum_algorithm == "legacy-sha256")
        if agent_id:
            snapshot_stmt = snapshot_stmt.join(
                AgentVersion, AgentVersion.id == AgentVersionSnapshot.agent_version_id
            ).where(AgentVersion.agent_id == uuid.UUID(agent_id))
        snapshots = list(db.execute(snapshot_stmt).scalars())
        reports += [_recompute_snapshot(s, dry_run=dry_run) for s in snapshots]

        if dry_run:
            db.rollback()
        else:
            db.commit()
        return reports
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing.")
    parser.add_argument("--agent-id", default=None, help="Limit to one agent's versions/snapshots.")
    args = parser.parse_args()

    reports = run(dry_run=args.dry_run, agent_id=args.agent_id)

    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}{len(reports)} row(s) with checksum_algorithm='legacy-sha256' found.")
    for report in reports:
        flag = "ok" if report["legacy_checksum_verified"] else "WARNING: legacy checksum did not verify!"
        print(f"  {report['kind']} {report['id']}: {report['old_checksum']} -> {report['new_checksum']} ({flag})")
    print("No changes written (dry run)." if args.dry_run else "Changes committed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
