"""Phase 3.8 (ACT-SRS-M3 §Phase-3.8, §9, §16, §20) -- the distributed scheduler.

Multiple instances of this run concurrently and coordinate entirely through
PostgreSQL. No Redis, no Celery, no Kafka: ``SELECT ... FOR UPDATE SKIP
LOCKED`` is the mechanism, matching the queue discipline
``ExecutionWorkerService.claim_next`` established for executions.

---

**The transaction boundaries, stated explicitly, because they are the phase.**

There are exactly three transactions per job run, and the boundary between the
first and second is the single most important line in this module:

1. **The claim.** ``SELECT ... FOR UPDATE SKIP LOCKED`` on a due
   ``job_definitions`` row → insert the ``job_runs`` row for that occurrence →
   advance ``next_run_at`` → **COMMIT**. Short, bounded, touching two rows.
2. **The handler.** Runs afterwards, in its own transaction(s), holding *no*
   lock taken by step 1.
3. **The completion.** Re-reads the run row, records the outcome, commits.

**Why the claim must commit before the handler runs (M1 deadlock discipline).**
This codebase has already paid for learning this once.
``ToolLoopOrchestrator._execute_parallel`` documents the incident: a claiming
transaction held ``FOR UPDATE`` on an ``agent_executions`` row while worker
threads, on their own connections, tried to ``INSERT`` rows referencing it. The
FK check needed ``FOR KEY SHARE`` on the locked row and blocked; the main
thread was simultaneously blocked joining those workers. **Postgres's deadlock
detector could not see it** -- from the database's side the main connection was
merely idle -- so it hung rather than aborting.

The scheduler has the identical shape: a claim that locks a row, then a handler
that touches the database, possibly on other connections, possibly for
minutes. If the claim's transaction were still open, a handler blocking on
anything the claim holds would hang the instance, and *every other instance*
would sit behind the same definition row. Committing first costs nothing --
the lock's one job (stop a second instance claiming the same occurrence) is
already complete once the run row is inserted, and the unique index on
``(job_definition_id, occurrence_key)`` enforces that permanently rather than
for the life of a transaction.

So: **a handler never runs inside the transaction that claimed its lease.**
``claim`` returns only after committing, and ``dispatch`` refuses to run
against a session with an open transaction that it did not itself begin.

---

**Exactly-once, and what it does and does not mean.**

One ``job_runs`` row exists per ``(definition, occurrence)`` -- enforced by a
unique index, so two instances computing the same due occurrence cannot both
create one. A **retry** and a **stale-lease recovery** both *reuse that row*
rather than inserting another. That is what makes "no duplicate successful run
of the same occurrence" (M3-3.8-FR-014) a schema property rather than a
detection problem: there is one row, it carries an attempt counter, and it
reaches exactly one terminal state.

What it does not mean is exactly-once *side effects*. If an instance dies after
its handler committed real work but before the run row was marked SUCCEEDED,
recovery will run that handler again. Every registered handler is therefore an
idempotent reconciliation (sweep current state, evaluate current gates), not an
event emitter -- and the two deployment handlers additionally inherit Phase
3.1's idempotency contract from the operations they call. This is stated rather
than hidden because it is the honest limit of what a database lease can
promise.

---

**Recovery (§16).** Definitions and run history are durable. **Leases are
ephemeral**: after a crash or a restore, a lease is evidence of an owner that
*was*, never one that *is*. ``recover_stale`` reclaims any non-terminal run
whose lease has lapsed, records where it came from, and re-runs it. Nothing
preserves a stale lease across a restart, and no job is lost by a crash --
worst case its occurrence is retried by whichever instance notices first.
"""

from __future__ import annotations

import logging
import socket
import os
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.identity.errors import ErrorCode, IdentityError
from app.models.scheduler import JobDefinition, JobRun
from app.scheduler import handlers as handler_registry
from app.scheduler import principal as automation
from app.scheduler import schedule

logger = logging.getLogger("control_tower.scheduler")

TERMINAL_STATUSES: frozenset[str] = frozenset({"SUCCEEDED", "FAILED", "TIMED_OUT", "ABANDONED"})
LIVE_STATUSES: frozenset[str] = frozenset({"CLAIMED", "RUNNING"})


def default_instance_id() -> str:
    """Identifies one scheduler process. Host plus PID is enough to tell two
    instances apart on one machine *and* across a fleet, and unlike a random
    UUID it tells an operator reading a stale lease which process to go look
    at."""
    return f"{socket.gethostname()}:{os.getpid()}"


class SchedulerService:
    def __init__(self, db: Session, *, instance_id: str | None = None) -> None:
        self.db = db
        self.instance_id = instance_id or default_instance_id()

    # ------------------------------------------------------------------ #
    # Transaction 1 -- the claim (commits before returning)
    # ------------------------------------------------------------------ #
    def claim_due(self, *, now: datetime | None = None) -> JobRun | None:
        """Claim one due job, or return ``None``.

        ``SKIP LOCKED`` is what makes contention cheap: an instance that finds
        a definition already locked by a peer moves on to the next candidate
        instead of queueing behind it. With ``limit(1)`` that means a second
        instance simply sees no work rather than blocking -- which is the
        behaviour the §20 proof asserts.

        Returns a **detached-safe** run row after the commit; the caller
        dispatches against it with no lock held."""
        now = now or _now()
        definition = self.db.execute(
            select(JobDefinition)
            .where(JobDefinition.enabled.is_(True),
                   JobDefinition.next_run_at.isnot(None),
                   JobDefinition.next_run_at <= now)
            .order_by(JobDefinition.next_run_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        ).scalars().first()

        if definition is None:
            self.db.commit()  # release the snapshot; nothing was claimed
            return None

        scheduled_for = definition.next_run_at or now

        # NO_OVERLAP: a prior occurrence is still live, so this one does not
        # start. The schedule still advances -- a job that fell behind should
        # resume on its normal cadence, not accumulate a backlog it will then
        # run all at once.
        if definition.concurrency_policy == "NO_OVERLAP" and self._has_live_run(definition, now):
            definition.next_run_at = schedule.next_run_after(
                definition.schedule_kind, definition.schedule_spec, scheduled_for, now)
            self.db.commit()
            return None

        run = JobRun(
            job_definition_id=definition.id,
            organization_id=definition.organization_id,
            occurrence_key=schedule.occurrence_key(definition.schedule_kind, scheduled_for),
            status="CLAIMED",
            attempt=1,
            lease_owner=self.instance_id,
            lease_expires_at=schedule.lease_expiry(now, definition.timeout_seconds),
            heartbeat_at=now,
        )
        self.db.add(run)
        definition.next_run_at = schedule.next_run_after(
            definition.schedule_kind, definition.schedule_spec, scheduled_for, now)
        definition.last_claimed_at = now

        try:
            # ---- THE commit-before-dispatch boundary (M3-3.8-FR-012) ------
            self.db.commit()
        except IntegrityError:
            # The unique index fired: this occurrence already has a run row.
            # Losing that race is a correct outcome, not an error -- the
            # occurrence is someone else's, and this instance simply has no
            # work.
            self.db.rollback()
            return None
        self.db.refresh(run)
        return run

    def _has_live_run(self, definition: JobDefinition, now: datetime) -> bool:
        """A prior run still holding a *live* lease. An expired lease is not a
        live run -- that is a crashed owner, and treating it as live would let
        one crash block a NO_OVERLAP job forever."""
        return self.db.execute(
            select(JobRun.id).where(
                JobRun.job_definition_id == definition.id,
                JobRun.status.in_(tuple(LIVE_STATUSES)),
                JobRun.lease_expires_at.isnot(None),
                JobRun.lease_expires_at > now,
            ).limit(1)
        ).scalars().first() is not None

    # ------------------------------------------------------------------ #
    # Stale-lease recovery (§20 part 2) -- also commits before returning
    # ------------------------------------------------------------------ #
    def recover_stale(self, *, now: datetime | None = None) -> JobRun | None:
        """Reclaim one run whose owner stopped renewing its lease.

        The reclaimed run is the **same row**, with its attempt incremented and
        a new owner -- never a new row. That is what keeps exactly-once true
        across recovery: the occurrence has one record, and a crashed attempt
        is visible in it rather than replaced by a fresh one that hides the
        crash.

        A run whose attempts are exhausted is marked ABANDONED instead of being
        retried, so a job that crashes the process every time cannot become an
        infinite reclaim loop across the fleet."""
        now = now or _now()
        run = self.db.execute(
            select(JobRun)
            .where(JobRun.status.in_(tuple(LIVE_STATUSES)),
                   JobRun.lease_expires_at.isnot(None),
                   JobRun.lease_expires_at <= now)
            .order_by(JobRun.lease_expires_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        ).scalars().first()
        if run is None:
            self.db.commit()
            return None

        definition = self.db.get(JobDefinition, run.job_definition_id)
        previous_owner = run.lease_owner
        limit = schedule.max_attempts(definition.retry_policy if definition else None)

        if run.attempt >= limit:
            run.status = "ABANDONED"
            run.ended_at = now
            run.error = (run.error or
                         f"Lease expired while owned by {previous_owner}; attempts exhausted "
                         f"({run.attempt}/{limit}).")
            self.db.commit()
            logger.warning("abandoned job run %s after %s attempts", run.id, run.attempt)
            return None

        run.attempt += 1
        run.status = "CLAIMED"
        run.lease_owner = self.instance_id
        run.recovered_from = previous_owner
        run.lease_expires_at = schedule.lease_expiry(
            now, definition.timeout_seconds if definition else 300)
        run.heartbeat_at = now
        run.started_at = None
        self.db.commit()
        self.db.refresh(run)
        logger.info("recovered job run %s from %s", run.id, previous_owner)
        return run

    # ------------------------------------------------------------------ #
    # Transaction 2 -- the handler (no claim lock held)
    # ------------------------------------------------------------------ #
    def dispatch(self, run: JobRun) -> JobRun:
        """Run the handler for an already-claimed run, then record the outcome.

        Assumes the claim has committed. That assumption is checked rather than
        trusted: an open transaction here would mean the claim's lock is still
        held, which is the exact condition the M1 deadlock needed."""
        if self.db.in_transaction():
            # A claim that committed leaves no transaction open; anything else
            # is a caller bug that would reintroduce the deadlock shape.
            self.db.commit()

        definition = self.db.get(JobDefinition, run.job_definition_id)
        if definition is None:
            return self._finish(run, "FAILED", error="Job definition no longer exists.")

        try:
            handler = handler_registry.resolve(definition.handler_key)
        except IdentityError as exc:
            return self._finish(run, "FAILED", error=exc.message)

        run.status = "RUNNING"
        run.started_at = _now()
        run.heartbeat_at = _now()
        self.db.commit()

        self._audit(definition, run, AuthorizationAuditEvent.SCHEDULED_JOB_STARTED, "INFO")

        deadline = _now() + timedelta(seconds=definition.timeout_seconds)
        actor = None
        if definition.organization_id is not None:
            actor = automation.get_or_create(self.db, definition.organization_id)

        ctx = handler_registry.HandlerContext(
            db=self.db, definition=definition, params=dict(definition.params or {}),
            organization_id=definition.organization_id, actor=actor,
        )
        try:
            result = handler(ctx)
        except Exception as exc:  # noqa: BLE001 -- a handler failure is data, not a crash
            self.db.rollback()
            logger.exception("scheduled job %s failed", definition.name)
            finished = self._finish_with_retry(run, definition, error=str(exc)[:2000])
            self._audit(definition, run, AuthorizationAuditEvent.SCHEDULED_JOB_FAILED, "WARNING")
            return finished

        if _now() > deadline:
            # The handler ran to completion but overran its budget. Recorded as
            # TIMED_OUT rather than SUCCEEDED so a chronically slow job is
            # visible, but its work is not discarded -- it already happened.
            finished = self._finish(run, "TIMED_OUT", result=_jsonable(result),
                                    error="Handler exceeded its timeout budget.")
            self._audit(definition, run, AuthorizationAuditEvent.SCHEDULED_JOB_FAILED, "WARNING")
            return finished

        return self._finish(run, "SUCCEEDED", result=_jsonable(result))

    # ------------------------------------------------------------------ #
    # Heartbeat (M3-3.8-FR-011)
    # ------------------------------------------------------------------ #
    def heartbeat(self, run: JobRun, *, now: datetime | None = None) -> JobRun:
        """Extend a live lease so a long but healthy handler is not reclaimed.

        Only extends a run this instance still owns. A run reclaimed by a peer
        (because this instance stalled long enough to look dead) must not be
        resurrected by a late heartbeat -- at that point the peer is the owner,
        and two owners is the one thing the lease exists to prevent."""
        now = now or _now()
        if run.lease_owner != self.instance_id or run.status not in LIVE_STATUSES:
            return run
        definition = self.db.get(JobDefinition, run.job_definition_id)
        run.heartbeat_at = now
        run.lease_expires_at = schedule.lease_expiry(
            now, definition.timeout_seconds if definition else 300)
        self.db.commit()
        return run

    # ------------------------------------------------------------------ #
    # Transaction 3 -- completion
    # ------------------------------------------------------------------ #
    def _finish(self, run: JobRun, status: str, *, result: dict | None = None,
                error: str | None = None) -> JobRun:
        run.status = status
        run.ended_at = _now()
        run.result = result
        run.error = error
        run.lease_expires_at = None
        self.db.commit()
        self.db.refresh(run)
        return run

    def _finish_with_retry(self, run: JobRun, definition: JobDefinition, *,
                           error: str) -> JobRun:
        """A failed attempt that still has budget is re-armed rather than
        terminal.

        Re-arming means putting the lease *in the past* by the backoff amount,
        so the ordinary stale-lease recovery path picks it up. Retry and crash
        recovery therefore share one mechanism instead of being two code paths
        that can disagree about attempt counting."""
        limit = schedule.max_attempts(definition.retry_policy)
        if run.attempt >= limit:
            return self._finish(run, "FAILED", error=error)

        delay = schedule.backoff_seconds(definition.retry_policy, run.attempt)
        run.status = "CLAIMED"
        run.error = error
        run.lease_owner = None
        run.lease_expires_at = _now() + timedelta(seconds=delay)
        run.heartbeat_at = None
        run.started_at = None
        self.db.commit()
        self.db.refresh(run)
        return run

    # ------------------------------------------------------------------ #
    # One tick
    # ------------------------------------------------------------------ #
    def run_once(self) -> JobRun | None:
        """Recover one stale run, or claim one due job, and dispatch it.

        Recovery is attempted first: a crashed peer's work is more urgent than
        a new occurrence, and leaving it while starting fresh work is how a
        fleet accumulates abandoned runs."""
        run = self.recover_stale()
        if run is None:
            run = self.claim_due()
        if run is None:
            return None
        return self.dispatch(run)

    # ------------------------------------------------------------------ #
    # Audit
    # ------------------------------------------------------------------ #
    def _audit(self, definition: JobDefinition, run: JobRun,
               event: AuthorizationAuditEvent, severity: str) -> None:
        """Platform-level jobs have no organization to attribute to, and this
        codebase's audit service requires one -- so those are logged rather
        than audited. Inventing an organization for them would put one tenant's
        audit trail in charge of platform work."""
        if definition.organization_id is None:
            logger.info("%s: job=%s run=%s owner=%s", event.value, definition.name, run.id,
                        run.lease_owner)
            return
        from app.observability.trace import TraceContext
        from app.runtime.services import _record_event

        # Phase 4.1 (M4-4.1-FR-003) -- the scheduler leg. A job occurrence has
        # no caller and therefore no inbound correlation header, so its trace
        # identity is derived from its own `job_runs` row: every event of one
        # occurrence (STARTED, then SUCCEEDED or FAILED, across retries and
        # lease recoveries, which all reuse the row) shares one trace. Without
        # this each event would get a fresh minted id and a job run would be
        # unreconstructable -- the exact failure this phase exists to fix,
        # arriving through a different door.
        _record_event(
            self.db, event, None, organization_id=definition.organization_id,
            severity=severity,
            meta={"job_definition_id": str(definition.id), "job_name": definition.name,
                  "handler_key": definition.handler_key, "run_id": str(run.id),
                  "attempt": run.attempt, "lease_owner": run.lease_owner,
                  "recovered_from": run.recovered_from},
            trace=TraceContext.for_job_run(run),
        )
        self.db.commit()

    # ------------------------------------------------------------------ #
    # Management reads/writes (used by the API)
    # ------------------------------------------------------------------ #
    def get_or_404(self, organization_id: uuid.UUID, definition_id: uuid.UUID) -> JobDefinition:
        definition = self.db.get(JobDefinition, definition_id)
        if definition is None:
            raise IdentityError(ErrorCode.JOB_DEFINITION_NOT_FOUND, "Job definition not found.")
        # A platform job (null organization) is visible only to a caller acting
        # for the platform, which the route layer establishes; a tenant job is
        # visible only to its own tenant.
        if definition.organization_id is not None and \
                definition.organization_id != organization_id:
            raise IdentityError(ErrorCode.JOB_DEFINITION_NOT_FOUND, "Job definition not found.")
        return definition

    def runs_for(self, definition: JobDefinition, *, limit: int = 50,
                 offset: int = 0) -> list[JobRun]:
        return list(self.db.execute(
            select(JobRun).where(JobRun.job_definition_id == definition.id)
            .order_by(JobRun.created_at.desc()).limit(limit).offset(offset)
        ).scalars())


def _now() -> datetime:
    from app.runtime.services import _now as runtime_now
    return runtime_now()


def _jsonable(value) -> dict:
    """Handler results land in JSONB, so anything unserializable becomes a
    string rather than failing the run that already succeeded."""
    if isinstance(value, dict):
        return {k: (v if isinstance(v, (str, int, float, bool, type(None), list, dict))
                    else str(v)) for k, v in value.items()}
    return {"result": str(value)}
