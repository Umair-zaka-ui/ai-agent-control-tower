"""Phase 3.8 (ACT-SRS-M3 §Phase-3.8, §16, §20) -- distributed scheduler models.

A deliberately small model: what to run (``JobDefinition``) and one row per
scheduled occurrence of it (``JobRun``, which carries its own lease). See
migration ``0043_distributed_scheduler`` for why lease and attempt are columns
here rather than tables of their own.

These live in ``app/models/`` beside every other table, but the scheduler's own
logic lives in ``app/scheduler/`` -- a **sibling** of ``app/runtime/`` and
``app/integration/``, not a child of either. That placement is forced rather
than stylistic: the scheduler must register a connector-health handler, and
Milestone 2's mechanically-enforced runtime-never-knows rule fails the build if
the word "connector" appears anywhere under ``app/runtime/``. A scheduler that
drives both domains cannot live inside either one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class JobDefinition(Base, UUIDPrimaryKeyMixin):
    """What to run, when, and under which policies.

    ``handler_key`` names an entry in the code-side registry
    (``app.scheduler.handlers``), never an import path or a dotted callable.
    That is a security property, not a convenience: a row in this table can
    never cause arbitrary code to execute, because dispatch resolves through a
    fixed dictionary and an unrecognized key raises ``JOB_HANDLER_UNKNOWN``
    rather than importing anything.

    ``organization_id`` is nullable, unlike almost every other tenant-scoped
    table in this schema. Null means a **platform-level** job -- the
    connector-health sweep and retention cleanup are genuinely not any one
    tenant's work, and inventing a tenant for them would be worse than
    modelling the distinction honestly.

    ``next_run_at`` is stored rather than derived on each poll so the due scan
    is one indexed range query. Every scheduler instance runs that query on
    every tick, so the difference between an index and per-row schedule
    arithmetic is the difference between a scheduler that scales with instance
    count and one that does not.
    """

    __tablename__ = "job_definitions"
    __table_args__ = (
        CheckConstraint("schedule_kind IN ('INTERVAL', 'ONE_TIME')",
                        name="ck_job_definitions_schedule_kind"),
        CheckConstraint("concurrency_policy IN ('NO_OVERLAP', 'ALLOW')",
                        name="ck_job_definitions_concurrency"),
        CheckConstraint("timeout_seconds > 0", name="ck_job_definitions_timeout"),
        UniqueConstraint("organization_id", "name", name="uq_job_definitions_org_name"),
        Index("ix_job_definitions_due", "next_run_at", postgresql_where=None),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    handler_key: Mapped[str] = mapped_column(String(64), nullable=False)
    schedule_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="INTERVAL")
    schedule_spec: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    retry_policy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    concurrency_policy: Mapped[str] = mapped_column(String(16), nullable=False,
                                                    default="NO_OVERLAP")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                             nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class JobRun(Base, UUIDPrimaryKeyMixin):
    """One row per scheduled *occurrence*, carrying its own lease.

    ``uq_job_runs_occurrence`` on ``(job_definition_id, occurrence_key)`` is
    the exactly-once guarantee (M3-3.8-FR-014). Two instances that compute the
    same due occurrence cannot both create a run for it: the second INSERT
    loses to the unique index. The database decides the race, not application
    timing -- the same primitive Phase 3.4 used for
    ``uq_traffic_allocations_current`` and 3.7 for ``uq_rollback_events_dedup``.

    **A retry reuses this row rather than creating a new one**, and so does a
    stale-lease recovery. That is what makes exactly-once structural: however
    many instances touch an occurrence, and however many times it is attempted,
    there is one row and it reaches exactly one terminal state. A design that
    inserted a fresh run per attempt would have had to define "duplicate
    successful run" as something to detect afterwards rather than something the
    schema forbids.

    ``lease_owner``/``lease_expires_at``/``heartbeat_at`` are the lease. It is
    **ephemeral state** in ``RECOVERY.md``'s sense: after a crash or a restore,
    a lease is evidence of an owner that *was*, never of one that *is*, and the
    recovery scan treats it accordingly.

    ``recovered_from`` records the instance id a run was reclaimed from, so a
    reclaimed job is distinguishable after the fact from one that simply ran --
    an operator debugging a flapping instance needs to see that difference.
    """

    __tablename__ = "job_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('CLAIMED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'TIMED_OUT', 'ABANDONED')",
            name="ck_job_runs_status"),
        UniqueConstraint("job_definition_id", "occurrence_key", name="uq_job_runs_occurrence"),
        Index("ix_job_runs_definition_created", "job_definition_id", "created_at"),
    )

    job_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_definitions.id", ondelete="CASCADE"), nullable=False,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True,
    )
    occurrence_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="CLAIMED")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lease_owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                              nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    recovered_from: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
