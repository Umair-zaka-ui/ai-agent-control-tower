"""Phase 5.2 Part 1 SRS §28 — structured, categorized release notes.

Distinct from ``AgentVersion.release_notes`` (a Phase 5.0 free-text summary
field, kept as-is for backward compatibility); many categorized entries per
version here.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.models.runtime import AgentReleaseNote, AgentVersion
from app.models.user import User
from app.runtime.services import _record_event
from app.runtime.versioning.locking import ensure_not_locked

NOTE_CATEGORIES = ("ADDED", "CHANGED", "FIXED", "REMOVED", "SECURITY", "DEPRECATED")


class ReleaseNoteService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, version_id: uuid.UUID) -> list[AgentReleaseNote]:
        stmt = select(AgentReleaseNote).where(AgentReleaseNote.agent_version_id == version_id)
        return list(self.db.execute(stmt.order_by(AgentReleaseNote.created_at.desc())).scalars())

    def add(self, actor: User, agent_id: uuid.UUID, version: AgentVersion, *,
           category: str, note: str) -> AgentReleaseNote:
        ensure_not_locked(version)
        row = AgentReleaseNote(agent_version_id=version.id, category=category, note=note,
                               created_by=actor.id)
        self.db.add(row)
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_VERSION_NOTE_ADDED, actor,
                     organization_id=actor.organization_id, agent_id=agent_id,
                     meta={"version_id": str(version.id), "category": category})
        self.db.commit()
        self.db.refresh(row)
        return row
