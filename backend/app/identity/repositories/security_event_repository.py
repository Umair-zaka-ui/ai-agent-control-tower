"""Security-event repository — the read path over ``security_events`` (SRS §26).

Every query is **organization-scoped**: `security_events.organization_id` is the
tenancy boundary and there is no method here that can be called without it. That is
deliberate — an audit reader that can accidentally omit the tenant filter is a
cross-tenant breach waiting for a typo.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.identity.models.security_event import SecurityEvent
from app.identity.repositories.base import BaseRepository


class SecurityEventRepository(BaseRepository[SecurityEvent]):
    model = SecurityEvent

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ------------------------------------------------------------------ #
    # Filtering
    # ------------------------------------------------------------------ #
    @staticmethod
    def _filtered(
        organization_id: uuid.UUID,
        *,
        event_type: str | None = None,
        event_types: list[str] | None = None,
        actor_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> Select:
        stmt = select(SecurityEvent).where(SecurityEvent.organization_id == organization_id)
        if event_type:
            stmt = stmt.where(SecurityEvent.event_type == event_type)
        if event_types:
            stmt = stmt.where(SecurityEvent.event_type.in_(event_types))
        if actor_id is not None:
            stmt = stmt.where(SecurityEvent.actor_id == actor_id)
        if session_id is not None:
            # Matches the expression index `((meta ->> 'session_id'))` created in
            # migration 0011. Using the `->>` text extraction (not `@>`) is what
            # lets Postgres use it.
            stmt = stmt.where(SecurityEvent.meta["session_id"].astext == str(session_id))
        if since is not None:
            stmt = stmt.where(SecurityEvent.created_at >= since)
        if until is not None:
            stmt = stmt.where(SecurityEvent.created_at <= until)
        return stmt

    def list_for_organization(
        self,
        organization_id: uuid.UUID,
        *,
        event_type: str | None = None,
        event_types: list[str] | None = None,
        actor_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SecurityEvent]:
        """Newest first — an audit reader always wants the most recent first."""
        stmt = (
            self._filtered(
                organization_id,
                event_type=event_type,
                event_types=event_types,
                actor_id=actor_id,
                session_id=session_id,
                since=since,
                until=until,
            )
            .order_by(SecurityEvent.created_at.desc(), SecurityEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.execute(stmt).scalars().all())

    def count_for_organization(
        self,
        organization_id: uuid.UUID,
        *,
        event_type: str | None = None,
        event_types: list[str] | None = None,
        actor_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> int:
        inner = self._filtered(
            organization_id,
            event_type=event_type,
            event_types=event_types,
            actor_id=actor_id,
            session_id=session_id,
            since=since,
            until=until,
        ).subquery()
        return int(self.db.execute(select(func.count()).select_from(inner)).scalar() or 0)

    def list_for_session(
        self, organization_id: uuid.UUID, session_id: uuid.UUID, *, limit: int = 200
    ) -> list[SecurityEvent]:
        """The full history of one session, **oldest first** — a timeline is read
        forwards. This is the "who revoked it, when, and why?" query."""
        stmt = (
            self._filtered(organization_id, session_id=session_id)
            .order_by(SecurityEvent.created_at.asc(), SecurityEvent.id.asc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_for_actor(
        self, organization_id: uuid.UUID, actor_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[SecurityEvent]:
        return self.list_for_organization(
            organization_id, actor_id=actor_id, limit=limit, offset=offset
        )

    def distinct_event_types(self, organization_id: uuid.UUID) -> list[str]:
        """Powers the filter dropdown — only types this org has actually produced."""
        stmt = (
            select(SecurityEvent.event_type)
            .where(SecurityEvent.organization_id == organization_id)
            .distinct()
            .order_by(SecurityEvent.event_type)
        )
        return list(self.db.execute(stmt).scalars().all())
