"""Phase 5.2 Part 1 SRS §17-18 — version lineage.

Lineage pointers are index/bookkeeping metadata on ``agent_versions`` itself
(``parent_version_id``, ``rollback_target_id``, ``superseded_by_id``), not
part of the frozen snapshot document — updating them (e.g. setting an older
published version's ``superseded_by_id`` when a newer one publishes) does
not violate §14's "a snapshot must never be edited" rule, since the frozen
content those columns sit alongside on the row is untouched.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.errors import ErrorCode, IdentityError
from app.models.runtime import AgentVersion

_ROLLBACK_ELIGIBLE_STATUSES = ("PUBLISHED", "DEPRECATED")


class VersionLineageService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def link_parent(self, agent_id: uuid.UUID, version: AgentVersion) -> None:
        """§17 — every version (after the first) knows its immediate
        predecessor: the agent's latest version at the moment this one was
        created."""
        latest = self.db.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id, AgentVersion.id != version.id)
            .order_by(AgentVersion.version.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest is not None:
            version.parent_version_id = latest.id

    def mark_superseded(self, previous: AgentVersion, new: AgentVersion) -> None:
        """§18 — records which version replaced which. Purely informational:
        it does not change ``previous``'s status or block it from still
        being deployed — this platform's rollback/canary strategies (§15,
        §57) rely on multiple versions staying independently PUBLISHED (see
        ``AgentVersionService.publish``)."""
        previous.superseded_by_id = new.id

    def set_rollback_target(self, version: AgentVersion, target_id: uuid.UUID) -> AgentVersion:
        if target_id == version.id:
            raise IdentityError(ErrorCode.AGENT_VERSION_ROLLBACK_TARGET_INVALID,
                                "A version cannot be its own rollback target.")
        target = self.db.get(AgentVersion, target_id)
        if target is None or target.agent_id != version.agent_id:
            raise IdentityError(ErrorCode.AGENT_VERSION_ROLLBACK_TARGET_INVALID,
                                "Rollback target must be another version of the same agent.")
        if target.status not in _ROLLBACK_ELIGIBLE_STATUSES:
            raise IdentityError(ErrorCode.AGENT_VERSION_ROLLBACK_TARGET_INVALID,
                                "Rollback target must be a PUBLISHED or DEPRECATED version.")
        version.rollback_target_id = target.id
        return version
