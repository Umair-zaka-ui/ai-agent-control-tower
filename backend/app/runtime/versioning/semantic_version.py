"""Phase 5.2 Part 1 SRS §15-16 — semantic versioning rules.

Phase 5.0 accepted any ``semantic_version`` string with no validation ("not
parsed or validated against SemVer rules" — see docs/runtime/versioning.md).
This closes that gap: every new version's ``semantic_version`` must be a
valid MAJOR.MINOR.PATCH triple, strictly greater than every other version
already recorded for the same agent (§16: "cannot decrease", "cannot publish
duplicate versions"). "Cannot skip existing versions" (§16) is read as "no
duplicates, no re-use" rather than a ban on jumping several MAJOR/MINOR
numbers at once, which is normal, intentional SemVer usage.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.errors import ErrorCode, IdentityError
from app.models.runtime import AgentVersion

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse_semver(value: str) -> tuple[int, int, int]:
    match = _SEMVER_RE.match((value or "").strip())
    if not match:
        raise IdentityError(ErrorCode.AGENT_VERSION_INVALID_SEMVER,
                            f"'{value}' is not a valid MAJOR.MINOR.PATCH semantic version.")
    a, b, c = match.groups()
    return (int(a), int(b), int(c))


class SemanticVersionService:
    """§15-16 — validates a new version's ``semantic_version`` against every
    other version already recorded for the same agent."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def next_default(self, agent_id: uuid.UUID) -> str:
        """No ``semantic_version`` supplied: bump the patch digit of the
        highest existing one (or start at ``0.1.0`` for the agent's first
        version)."""
        existing = self._existing(agent_id)
        if not existing:
            return "0.1.0"
        major, minor, patch = max(existing)
        return f"{major}.{minor}.{patch + 1}"

    def validate_new(self, agent_id: uuid.UUID, semantic_version: str) -> None:
        """Raises if ``semantic_version`` is malformed, a duplicate, or not
        strictly greater than every existing version for this agent."""
        candidate = parse_semver(semantic_version)
        existing = self._existing(agent_id)
        if candidate in existing:
            raise IdentityError(ErrorCode.AGENT_VERSION_SEMVER_NOT_INCREASING,
                                f"Version {semantic_version} already exists for this agent.")
        if existing and candidate < max(existing):
            current = ".".join(str(part) for part in max(existing))
            raise IdentityError(ErrorCode.AGENT_VERSION_SEMVER_NOT_INCREASING,
                                f"Version {semantic_version} must be greater than the agent's "
                                f"current highest version ({current}).")

    def _existing(self, agent_id: uuid.UUID) -> set[tuple[int, int, int]]:
        rows = self.db.execute(
            select(AgentVersion.semantic_version).where(AgentVersion.agent_id == agent_id)
        ).scalars().all()
        result: set[tuple[int, int, int]] = set()
        for raw in rows:
            match = _SEMVER_RE.match((raw or "").strip())
            if match:
                a, b, c = match.groups()
                result.add((int(a), int(b), int(c)))
        return result
