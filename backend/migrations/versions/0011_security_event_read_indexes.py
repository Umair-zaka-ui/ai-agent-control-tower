"""Phase 4 Part 4.2.2.2 - indexes for the security-event read path.

``security_events`` was a write-only table: 5k+ rows, indexed only on the columns
the *writer* happened to touch (``event_type``, ``organization_id``, ``request_id``).
Now that administrators can read it (DoD §32 "…and audit user sessions"), the
queries that matter are:

1. "the org's events, newest first"          → (organization_id, created_at DESC)
2. "everything this identity did"            → (actor_id, created_at DESC)
3. "the full history of ONE session"         → expression index on meta->>'session_id'

(3) is the query behind "who revoked this session, when, and why?". Without the
expression index it is a sequential scan plus a JSONB extraction on every row —
fine at 5k rows, pathological at 5M, and audit tables only grow.

Indexes only; no data or schema change. Safe to re-run.

Revision ID: 0011_security_event_read_indexes
Revises: 0010_session_admin_permissions
"""

from __future__ import annotations

from alembic import op

revision: str = "0011_security_event_read_indexes"
down_revision: str | None = "0010_session_admin_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Org-scoped chronological listing — the default view.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_security_events_org_created
            ON security_events (organization_id, created_at DESC)
        """
    )
    # 2. "What did this identity do?" — actor timeline.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_security_events_actor_created
            ON security_events (actor_id, created_at DESC)
        """
    )
    # 3. "What happened to this session?" — expression index on the JSONB key we
    #    stamp on every session/device/token event.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_security_events_session_id
            ON security_events ((meta ->> 'session_id'))
        """
    )
    # 4. Event-type + time, for "show me every TOKEN_REUSE_DETECTED this month".
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_security_events_type_created
            ON security_events (event_type, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_security_events_type_created")
    op.execute("DROP INDEX IF EXISTS ix_security_events_session_id")
    op.execute("DROP INDEX IF EXISTS ix_security_events_actor_created")
    op.execute("DROP INDEX IF EXISTS ix_security_events_org_created")
