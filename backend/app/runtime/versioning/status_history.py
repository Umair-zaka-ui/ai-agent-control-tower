"""Phase 5.2 Part 1 SRS §19, §25 — the version lifecycle transition ledger.

Mirrors ``AgentLifecycleEvent`` (Phase 5.1 registry lifecycle) for versions:
every transition — including the initial ``None -> DRAFT`` at creation —
gets its own immutable row.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.runtime import AgentVersionStatusHistory


def record_status_change(db: Session, version_id: uuid.UUID, *, previous_status: str | None,
                         new_status: str, changed_by: uuid.UUID | None,
                         reason: str | None = None) -> AgentVersionStatusHistory:
    row = AgentVersionStatusHistory(agent_version_id=version_id, previous_status=previous_status,
                                    new_status=new_status, reason=reason, changed_by=changed_by)
    db.add(row)
    return row


def list_status_history(db: Session, version_id: uuid.UUID) -> list[AgentVersionStatusHistory]:
    stmt = select(AgentVersionStatusHistory).where(AgentVersionStatusHistory.agent_version_id == version_id)
    return list(db.execute(stmt.order_by(AgentVersionStatusHistory.created_at.desc())).scalars())
