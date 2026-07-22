"""Phase 5.2 Part 1 SRS §14, §21 — the shared immutability gate.

Release metadata, artifacts and release notes may all be attached while a
version is still being prepared (DRAFT through APPROVED); once it reaches
PUBLISHED — and forever after, through DEPRECATED/REVOKED/RETIRED — the
snapshot built at publish time is the permanent record, so no further
additions are allowed (§14: "Forbidden: Edit, Patch, Delete, Overwrite").
"""

from __future__ import annotations

from app.identity.errors import ErrorCode, IdentityError
from app.models.runtime import AgentVersion

LOCKED_STATUSES = ("PUBLISHED", "DEPRECATED", "REVOKED", "RETIRED")


def ensure_not_locked(version: AgentVersion) -> None:
    if version.status in LOCKED_STATUSES:
        raise IdentityError(ErrorCode.AGENT_VERSION_SNAPSHOT_LOCKED,
                            f"Version is {version.status} — release details are frozen and can no "
                            "longer be added to.")
