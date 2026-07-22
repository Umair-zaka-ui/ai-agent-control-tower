"""Phase 5.2 Part 1 SRS §26, §28 — release metadata (name, justification,
window, ticket/branch/build references). One row per version, upserted."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.models.runtime import AgentReleaseMetadata, AgentVersion
from app.models.user import User
from app.runtime.services import _record_event
from app.runtime.versioning.locking import ensure_not_locked

_FIELDS = (
    "release_name", "release_description", "business_justification", "change_category",
    "release_window_start", "release_window_end", "support_end_date", "approval_ticket",
    "source_branch", "commit_reference", "build_reference", "risk_score", "documentation_url",
)


class ReleaseMetadataService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, version_id: uuid.UUID) -> AgentReleaseMetadata | None:
        return self.db.execute(
            select(AgentReleaseMetadata).where(AgentReleaseMetadata.agent_version_id == version_id)
        ).scalar_one_or_none()

    def upsert(self, actor: User, agent_id: uuid.UUID, version: AgentVersion, payload: dict
              ) -> AgentReleaseMetadata:
        ensure_not_locked(version)
        row = self.get(version.id)
        if row is None:
            row = AgentReleaseMetadata(agent_version_id=version.id)
            self.db.add(row)
        for field in _FIELDS:
            if field in payload:
                setattr(row, field, payload[field])
        self.db.flush()
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_VERSION_RELEASE_METADATA_UPDATED, actor,
                     organization_id=actor.organization_id, agent_id=agent_id,
                     meta={"version_id": str(version.id)})
        self.db.commit()
        self.db.refresh(row)
        return row
