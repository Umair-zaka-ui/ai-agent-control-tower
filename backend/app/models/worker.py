"""Phase 3.9 (ACT-SRS-M3 §Phase-3.9, §16, §21) -- the execution worker fleet.

One table. The execution *lease* is not here because M1 already built it:
``ExecutionLock`` (``app/models/runtime.py``) carries the owning worker, the
expiry and the heartbeat, with ``execution_id`` UNIQUE. That unique constraint
is the structural guarantee that no two workers successfully execute one
claimed execution, and this phase extends it rather than paralleling it.

What was genuinely missing was the *fleet*: which worker processes exist, how
much capacity each declares, and whether they are still alive. That is what
this table is, and it is the substrate rolling deployment is defined over --
the real thing Phase 3.6 correctly refused to pretend it had.

Placed in ``app/models/`` beside every other table, while the fleet's own
logic lives in ``app/workers/`` -- a sibling of ``app/scheduler/``, for the
same reason that package is a sibling rather than a child of ``app/runtime/``:
a worker process is platform infrastructure that *drives* the runtime domain,
not a service inside it.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin

#: The three states a worker process moves through (M3-3.9-FR-002).
#:
#: ``DRAINING`` is the one that carries weight. It is not "stopping soon" --
#: it is a precise, checkable contract: *claim nothing new, finish what you
#: hold*. Graceful shutdown is that state plus waiting, which is why shutdown
#: needs no separate flag and cannot disagree with drain.
WORKER_STATUSES: frozenset[str] = frozenset({"RUNNING", "DRAINING", "STOPPED"})

#: Statuses whose declared capacity is real, live capacity. A DRAINING worker
#: is deliberately excluded: it is finishing in-flight work and will claim
#: nothing more, so counting its slots would make rolling derive a step over
#: capacity that is on its way out.
LIVE_STATUSES: frozenset[str] = frozenset({"RUNNING"})


class WorkerRegistration(Base, UUIDPrimaryKeyMixin):
    """One execution-worker process, as the fleet currently understands it.

    **This row is ephemeral, and that is a design property rather than a
    limitation** (SRS §16). It describes a running operating-system process.
    After a restart or a database restore it describes a process that no
    longer exists, so the recovery path treats a lapsed ``heartbeat_at`` as
    death, not as a row to be trusted. Nothing of value is lost: the workers
    rebuild this table by re-registering within one poll interval. The thing
    that must survive -- the executions those workers were running -- lives in
    ``agent_executions`` and is fully durable.

    ``concurrency`` is what the process *declares* it can run at once, and it
    is the unit rolling measures capacity in. ``active_count`` is what it
    reports actually running, refreshed on each heartbeat; it drives
    backpressure and queue-depth reporting. The authoritative in-flight set is
    always ``execution_locks``, so ``active_count`` being briefly stale
    between heartbeats can slow a claim down but can never cause a double
    execution."""

    __tablename__ = "worker_registrations"
    __table_args__ = (
        UniqueConstraint("worker_id", name="uq_worker_registrations_worker_id"),
        CheckConstraint("status IN ('RUNNING', 'DRAINING', 'STOPPED')",
                        name="ck_worker_registrations_status"),
        CheckConstraint("concurrency > 0", name="ck_worker_registrations_concurrency"),
        CheckConstraint("active_count >= 0", name="ck_worker_registrations_active_count"),
        Index("ix_worker_registrations_stale", "heartbeat_at",
              postgresql_where=text("status <> 'STOPPED'")),
        Index("ix_worker_registrations_cohort", "cohort", "status"),
    )

    worker_id: Mapped[str] = mapped_column(String(100), nullable=False)
    #: The rolling unit. A declared label, defaulting to a single cohort so a
    #: fleet that never configures cohorts still rolls -- in one step, which
    #: is the honest description of converting an undivided fleet.
    cohort: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="RUNNING")
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"<WorkerRegistration {self.worker_id} cohort={self.cohort} "
                f"{self.status} {self.active_count}/{self.concurrency}>")
