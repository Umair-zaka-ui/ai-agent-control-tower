"""Phase 3.9 -- the execution worker fleet: registration, liveness, capacity.

This module knows *which worker processes exist*. It deliberately does not
know how to run an execution -- that is M1's ``ExecutionWorkerService``, which
this phase does not modify beyond moving one transaction boundary. Keeping the
two apart is what lets the preservation mandate be checked rather than merely
asserted: if fleet management could reach into execution behaviour, "the M1
suite still passes" would be a much weaker statement than it is.

**What this module is for, beyond observability.** Three things depend on it:

1. *Backpressure* -- a worker at capacity must not claim more work, and queue
   depth must be reportable to whoever is deciding whether to add workers.
2. *Recovery* -- a worker that stops heartbeating is dead, and the executions
   it was holding must come back (SRS §16, M3-3.9-FR-020/021).
3. *Rolling* -- the fleet is the substrate rolling deployment is defined over.
   Its cohorts and their real capacity are what make a rolling step a genuine
   capacity event instead of a number moving. See
   ``app.runtime.deployment.rolling``.

**The honest limit on liveness.** ``heartbeat_at`` is a *last known* time, not
a guarantee. A worker that is alive but wedged (blocked on a network call that
never returns) keeps heartbeating from its own loop only if the loop still
runs; a worker whose process is frozen stops. So staleness detects dead and
frozen processes, and does not detect a live process making no progress. That
second failure is what the per-execution timeout is for, and conflating the
two would make each worse at its job -- the same distinction Phase 3.8 drew
between a lease and a timeout.
"""

from __future__ import annotations

import socket
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.core.config import settings
from app.identity.errors import ErrorCode, IdentityError
from app.models.runtime import AgentExecution, ExecutionLock
from app.models.worker import LIVE_STATUSES, WorkerRegistration

#: Statuses an execution can sit in while waiting for a worker. Queue depth is
#: reported over exactly this set so "depth" means "work nobody has yet",
#: never "work in progress".
QUEUED_STATUS = "QUEUED"
RUNNING_STATUS = "RUNNING"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def default_worker_id() -> str:
    """A worker identity that is stable within a process and unique across
    them.

    Host plus a random suffix rather than host plus PID: PIDs are reused by
    the operating system, and a reused PID after a crash would let a new
    process silently inherit a dead one's registration -- and with it, that
    registration's apparent liveness."""
    return f"{socket.gethostname()[:60]}-{uuid.uuid4().hex[:8]}"


class WorkerFleetService:
    """Fleet membership and capacity. One instance per session, like every
    other service here."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ----------------------------------------------------------------- #
    # Membership (M3-3.9-FR-001, FR-002)
    # ----------------------------------------------------------------- #
    def register(self, worker_id: str, *, cohort: str | None = None,
                 concurrency: int | None = None, hostname: str | None = None,
                 now: datetime | None = None) -> WorkerRegistration:
        """Announce a worker process, or re-announce an existing one.

        An upsert rather than an insert, because ``worker_id`` is UNIQUE and a
        restarted process is *the same worker* returning, not a new one. The
        alternative -- a row per start -- would make the fleet view a history
        of process launches, and would make capacity arithmetic count dead
        processes. A re-registration also resets ``status`` to RUNNING: a
        process that has just started is by definition not draining, whatever
        the row said about its predecessor."""
        moment = now or _now()
        worker = self.find(worker_id)
        if worker is None:
            worker = WorkerRegistration(
                worker_id=worker_id,
                cohort=cohort or settings.WORKER_COHORT,
                concurrency=concurrency or settings.WORKER_CONCURRENCY,
                hostname=hostname or socket.gethostname()[:255],
                status="RUNNING", active_count=0,
                heartbeat_at=moment, registered_at=moment,
            )
            self.db.add(worker)
        else:
            worker.cohort = cohort or worker.cohort
            worker.concurrency = concurrency or worker.concurrency
            worker.hostname = hostname or worker.hostname
            worker.status = "RUNNING"
            worker.active_count = 0
            worker.stopped_at = None
            worker.heartbeat_at = moment
            worker.registered_at = moment
        self.db.commit()
        self.db.refresh(worker)
        return worker

    def find(self, worker_id: str) -> WorkerRegistration | None:
        return self.db.execute(
            select(WorkerRegistration).where(WorkerRegistration.worker_id == worker_id)
        ).scalars().first()

    def get_or_404(self, worker_id: str) -> WorkerRegistration:
        worker = self.find(worker_id)
        if worker is None:
            raise IdentityError(ErrorCode.WORKER_NOT_FOUND,
                                f"No worker is registered with id {worker_id!r}.")
        return worker

    def heartbeat(self, worker_id: str, *, active_count: int | None = None,
                  now: datetime | None = None) -> WorkerRegistration:
        """Refresh liveness (M3-3.9-FR-004).

        Deliberately does **not** resurrect a STOPPED worker. A stopped
        registration is a statement that the process is gone; if it is in fact
        alive it must re-``register``, which is an explicit act. Letting a
        heartbeat quietly undo a stop would make drain-then-stop racy."""
        worker = self.get_or_404(worker_id)
        if worker.status == "STOPPED":
            raise IdentityError(
                ErrorCode.WORKER_INVALID_STATE,
                f"Worker {worker_id!r} is STOPPED; a stopped worker must re-register "
                "rather than heartbeat back into the fleet.",
            )
        worker.heartbeat_at = now or _now()
        if active_count is not None:
            worker.active_count = max(0, active_count)
        self.db.commit()
        return worker

    def drain(self, worker_id: str, *, actor_organization_id: uuid.UUID | None = None,
              actor_id: uuid.UUID | None = None) -> WorkerRegistration:
        """Stop claiming new work; keep finishing what is held (FR-002).

        Idempotent: draining an already-draining worker is a no-op rather than
        an error, because the caller's intent is already satisfied and an
        operator retrying a drain during an incident should not be punished
        for it."""
        worker = self.get_or_404(worker_id)
        if worker.status == "STOPPED":
            raise IdentityError(
                ErrorCode.WORKER_INVALID_STATE,
                f"Worker {worker_id!r} is already STOPPED and cannot be drained.",
            )
        if worker.status != "DRAINING":
            worker.status = "DRAINING"
            self._audit(AuthorizationAuditEvent.WORKER_DRAINING, worker,
                        organization_id=actor_organization_id, actor_id=actor_id)
        self.db.commit()
        return worker

    def stop(self, worker_id: str, *, now: datetime | None = None) -> WorkerRegistration:
        """Mark a worker gone. Called by the process itself on shutdown, and
        by the staleness sweep on a process that stopped saying anything."""
        worker = self.get_or_404(worker_id)
        worker.status = "STOPPED"
        worker.active_count = 0
        worker.stopped_at = now or _now()
        self.db.commit()
        return worker

    def list_workers(self, *, include_stopped: bool = False) -> list[WorkerRegistration]:
        stmt = select(WorkerRegistration)
        if not include_stopped:
            stmt = stmt.where(WorkerRegistration.status != "STOPPED")
        return list(self.db.execute(
            stmt.order_by(WorkerRegistration.cohort, WorkerRegistration.worker_id)
        ).scalars())

    # ----------------------------------------------------------------- #
    # Liveness & recovery (M3-3.9-FR-004, FR-020, FR-021)
    # ----------------------------------------------------------------- #
    def stale_cutoff(self, now: datetime | None = None) -> datetime:
        return (now or _now()) - timedelta(seconds=settings.WORKER_STALE_AFTER_SECONDS)

    def stale_workers(self, *, now: datetime | None = None) -> list[WorkerRegistration]:
        return list(self.db.execute(
            select(WorkerRegistration).where(
                WorkerRegistration.status != "STOPPED",
                WorkerRegistration.heartbeat_at < self.stale_cutoff(now),
            )
        ).scalars())

    def reap_stale_workers(self, *, now: datetime | None = None) -> int:
        """Mark processes that stopped heartbeating as STOPPED, and audit the
        executions they were holding.

        **This does not itself release those executions**, and the split is
        deliberate. M1's ``ExecutionWorkerService.reap_expired_locks`` already
        owns execution recovery: it applies the real retry policy, writes the
        attempt record, and emits the terminal audit. Reimplementing any of
        that here would create a second recovery path that could disagree with
        the first about whether an execution had attempts left -- and two
        components disagreeing about that is how an execution gets run twice
        or dropped entirely. So this marks the *worker* dead and leaves the
        *work* to the component that already knows the rules.

        The two are correctly ordered by their own clocks rather than by
        calling one from the other: a worker goes stale after
        ``WORKER_STALE_AFTER_SECONDS`` of silence, and its locks expire on
        their own ``expires_at``. Whichever fires first, the outcome is the
        same, and neither can leave an execution owned by a process that no
        longer exists."""
        moment = now or _now()
        reaped = 0
        for worker in self.stale_workers(now=moment):
            held = list(self.db.execute(
                select(ExecutionLock).where(ExecutionLock.worker_id == worker.worker_id)
            ).scalars())
            for lock in held:
                execution = self.db.get(AgentExecution, lock.execution_id)
                if execution is None:
                    continue
                # Attributed to the execution's own tenant -- the only
                # organization this platform-level event has any honest claim
                # to. Same rule Phase 3.8 applied to platform-level jobs.
                self._audit(
                    AuthorizationAuditEvent.WORKER_STALE_RECOVERED, worker,
                    organization_id=execution.organization_id,
                    severity="WARNING",
                    extra={"execution_id": str(execution.id),
                           "last_heartbeat_at": worker.heartbeat_at.isoformat()},
                )
            worker.status = "STOPPED"
            worker.active_count = 0
            worker.stopped_at = moment
            reaped += 1
        if reaped:
            self.db.commit()
        return reaped

    # ----------------------------------------------------------------- #
    # Capacity & backpressure (M3-3.9-FR-014)
    # ----------------------------------------------------------------- #
    def queue_depth(self) -> dict:
        """What the fleet is facing, and what it can take.

        ``queued`` counts work nobody has claimed; ``running`` counts work
        in flight. They are read from ``agent_executions`` rather than summed
        from worker rows because that is the authoritative answer -- a worker
        row can be stale by up to one heartbeat interval, and a queue-depth
        number that lags is exactly the number an autoscaler must not act on."""
        counts = dict(self.db.execute(
            select(AgentExecution.status, func.count(AgentExecution.id))
            .where(AgentExecution.status.in_((QUEUED_STATUS, RUNNING_STATUS)))
            .group_by(AgentExecution.status)
        ).all())
        live = self.list_workers()
        running = [w for w in live if w.status in LIVE_STATUSES]
        capacity = sum(w.concurrency for w in running)
        active = sum(w.active_count for w in running)
        return {
            "queued": int(counts.get(QUEUED_STATUS, 0)),
            "running": int(counts.get(RUNNING_STATUS, 0)),
            "workers": len(live),
            "workers_accepting_work": len(running),
            "capacity": capacity,
            "active": active,
            "available_slots": max(0, capacity - active),
        }

    def capacity_by_cohort(self, *, now: datetime | None = None) -> dict[str, int]:
        """Live declared capacity per cohort -- the numbers rolling derives
        its step sizes from.

        Only RUNNING, non-stale workers count. A DRAINING worker is finishing
        up and will claim nothing more, and a stale one is gone; including
        either would let rolling compute a step over capacity that does not
        exist, which is the precise failure mode SRS §3.6 warns about."""
        cutoff = self.stale_cutoff(now)
        rows = self.db.execute(
            select(WorkerRegistration.cohort, func.sum(WorkerRegistration.concurrency))
            .where(WorkerRegistration.status.in_(tuple(LIVE_STATUSES)),
                   WorkerRegistration.heartbeat_at >= cutoff)
            .group_by(WorkerRegistration.cohort)
        ).all()
        return {cohort: int(total or 0) for cohort, total in rows}

    # ----------------------------------------------------------------- #
    def _audit(self, event: AuthorizationAuditEvent, worker: WorkerRegistration, *,
               organization_id: uuid.UUID | None, actor_id: uuid.UUID | None = None,
               severity: str = "INFO", extra: dict | None = None) -> None:
        """Audit, when there is a tenant to attribute the event to.

        A worker process registering or draining itself belongs to no
        organization, and this codebase's audit service requires one. Phase
        3.8 met the same wall with platform-level jobs and resolved it the
        same way: record what can be honestly attributed, and do not
        manufacture a tenant for what cannot. The fleet API makes the
        unattributed facts observable instead."""
        if organization_id is None:
            return
        from app.runtime.services import _record_event

        meta = {"worker_id": worker.worker_id, "cohort": worker.cohort,
                "status": worker.status, "concurrency": worker.concurrency}
        if actor_id is not None:
            meta["actor_id"] = str(actor_id)
        if extra:
            meta.update(extra)
        _record_event(self.db, event, None, organization_id=organization_id,
                      severity=severity, meta=meta)
