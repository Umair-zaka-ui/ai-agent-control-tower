"""Phase 3.9 -- the execution worker process (M3-3.9-FR-001..014).

A worker is a loop around three things it does not implement: the fleet
(``app.workers.fleet``), the claim (``ExecutionWorkerService.claim_next``) and
the execution (``ExecutionWorkerService.run_once``). That is the whole design,
and the thinness is the point -- **distributing execution must not change
execution**, so this module contains no execution logic whatsoever. There is
no provider call here, no tool loop, no retry policy, no cost arithmetic and
no governance check. Every one of those stayed exactly where M1 put it, which
is why the M1 suite passes unchanged.

**The transaction discipline.** Each claimed execution runs on its own
``Session``, and the claim commits before the execution begins (see
``ExecutionWorkerService.claim_next``). So a worker running N concurrent
executions holds N sessions and zero locks taken at claim time. Two workers
can never both run one execution -- not because they take turns politely, but
because ``execution_locks.execution_id`` is UNIQUE and the row is no longer
``QUEUED`` once claimed.

**Why threads and not processes.** Concurrency here is I/O-bound waiting on
model and tool HTTP calls, which releases the GIL; and ``ToolLoopOrchestrator``
already runs parallel tool calls on threads with per-thread sessions, so this
reuses a threading model the codebase has already proven rather than
introducing a second one. Horizontal scale is more worker *processes*, which
is what the fleet is for.

**The honest limit on exactly-once**, stated as plainly as Phase 3.8 stated
its own: what this guarantees is exactly-once *dispatch*, not exactly-once
side effects. A worker that dies after its execution has called a tool but
before the result is committed will have that execution recovered and
retried, and the tool will have been called twice. M1 already faced this and
answered it where the answer belongs -- ``ToolGatewayService`` knows which
tools are idempotent -- and this phase does not weaken that answer, but it
cannot promise more than the layer beneath it delivers.
"""

from __future__ import annotations

import logging
import signal
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.worker import WorkerRegistration
from app.workers.fleet import WorkerFleetService, default_worker_id

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionWorker:
    """One worker process's state and loop.

    Instantiating does not register: ``start()`` does, so a test can build a
    worker, inspect it, and decide whether it should ever join the fleet."""

    def __init__(self, *, worker_id: str | None = None, cohort: str | None = None,
                 concurrency: int | None = None, session_factory=SessionLocal) -> None:
        self.worker_id = worker_id or default_worker_id()
        self.cohort = cohort or settings.WORKER_COHORT
        self.concurrency = concurrency or settings.WORKER_CONCURRENCY
        self._session_factory = session_factory
        #: Local view of fleet status. Authoritative for *this* process's
        #: behaviour; the database row is authoritative for what operators
        #: see and for what an API drain requests. ``refresh()`` reconciles
        #: them, which is how a remote drain actually reaches this loop.
        self.status = "RUNNING"
        self._active = 0
        self._active_lock = threading.Lock()
        self._stop_requested = threading.Event()
        self._pool: ThreadPoolExecutor | None = None

    # ----------------------------------------------------------------- #
    # Fleet membership
    # ----------------------------------------------------------------- #
    def _session(self):
        return self._session_factory()

    def start(self) -> WorkerRegistration:
        """Join the fleet (M3-3.9-FR-001)."""
        db = self._session()
        try:
            worker = WorkerFleetService(db).register(
                self.worker_id, cohort=self.cohort, concurrency=self.concurrency)
            self.status = "RUNNING"
            self._stop_requested.clear()
            logger.info("worker %s registered (cohort=%s concurrency=%d)",
                        self.worker_id, self.cohort, self.concurrency)
            return worker
        finally:
            db.close()

    def heartbeat(self) -> None:
        """Report liveness and in-flight count (M3-3.9-FR-004)."""
        db = self._session()
        try:
            WorkerFleetService(db).heartbeat(self.worker_id, active_count=self.active_count)
        finally:
            db.close()

    def refresh(self) -> str:
        """Reconcile local status with the fleet row.

        This is the mechanism that makes ``POST /workers/{id}/drain`` do
        something to a *running process* rather than only to a database row.
        An operator's drain lands in the row; the next refresh moves it into
        this loop, which then stops claiming. Deliberately one-directional
        towards draining: this method will pick up a DRAINING or STOPPED
        instruction, but will not promote itself back to RUNNING, because
        undoing an operator's drain from inside the process being drained is
        never the right resolution of that disagreement."""
        db = self._session()
        try:
            worker = WorkerFleetService(db).find(self.worker_id)
            if worker is not None and worker.status in ("DRAINING", "STOPPED"):
                self.status = worker.status
            return self.status
        finally:
            db.close()

    def drain(self) -> None:
        """Stop claiming; keep finishing (M3-3.9-FR-002)."""
        self.status = "DRAINING"
        db = self._session()
        try:
            WorkerFleetService(db).drain(self.worker_id)
        finally:
            db.close()

    def stop(self) -> None:
        """Leave the fleet. In-flight work is *not* abandoned here -- see
        ``shutdown`` for the graceful sequence."""
        self.status = "STOPPED"
        db = self._session()
        try:
            fleet = WorkerFleetService(db)
            if fleet.find(self.worker_id) is not None:
                fleet.stop(self.worker_id)
        finally:
            db.close()

    def shutdown(self, *, timeout: float | None = None) -> None:
        """Graceful shutdown (M3-3.9-FR-002): drain, finish, leave.

        Drain first so nothing new is claimed while we are waiting, then wait
        for in-flight executions, then mark the worker gone. Doing it in any
        other order either abandons work that was about to succeed or leaves a
        window in which a shutting-down worker claims fresh work."""
        self._stop_requested.set()
        if self.status == "RUNNING":
            self.drain()
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=False)
        self.stop()

    # ----------------------------------------------------------------- #
    # Capacity (M3-3.9-FR-003, FR-014)
    # ----------------------------------------------------------------- #
    @property
    def active_count(self) -> int:
        with self._active_lock:
            return self._active

    @property
    def available_slots(self) -> int:
        """Backpressure, expressed as a number rather than a policy.

        A DRAINING or STOPPED worker reports zero regardless of how idle it
        is: 'has spare capacity' and 'should take more work' are different
        questions, and only the second one governs claiming."""
        if self.status != "RUNNING":
            return 0
        return max(0, self.concurrency - self.active_count)

    def _acquire_slot(self) -> bool:
        with self._active_lock:
            if self.status != "RUNNING" or self._active >= self.concurrency:
                return False
            self._active += 1
            return True

    def _release_slot(self) -> None:
        with self._active_lock:
            self._active = max(0, self._active - 1)

    # ----------------------------------------------------------------- #
    # Claim & execute (M3-3.9-FR-010..013)
    # ----------------------------------------------------------------- #
    def claim_and_run(self) -> uuid.UUID | None:
        """Claim at most one execution and run it to completion, here, now.

        Synchronous and on the calling thread. This is what each concurrency
        slot does, and it is also the single-slot worker's entire behaviour.

        The session is opened and closed inside this call rather than held on
        the worker, because concurrent slots must not share a ``Session`` --
        the same constraint that already governs ``ToolLoopOrchestrator``'s
        parallel tool calls.

        Returns the execution's id, or ``None`` if the queue had nothing for
        this worker. Exceptions are deliberately not caught: M1's ``_execute``
        already converts every execution failure into a recorded terminal
        state, so anything reaching here is a defect in the worker itself and
        must be visible rather than swallowed into a silent poll loop."""
        if not self._acquire_slot():
            return None
        db = self._session()
        try:
            from app.runtime.services import ExecutionWorkerService

            execution = ExecutionWorkerService(db).run_once(self.worker_id)
            return execution.id if execution is not None else None
        finally:
            db.close()
            self._release_slot()

    def tick(self) -> int:
        """One poll: fill every free slot, return how many were dispatched.

        Stops at the first empty claim rather than trying every slot: if the
        queue had nothing a moment ago it almost certainly has nothing now,
        and hammering it once per slot per tick turns an idle fleet into a
        load generator."""
        if self.status != "RUNNING":
            return 0
        dispatched = 0
        for _ in range(self.available_slots):
            if self._pool is None:
                self._pool = ThreadPoolExecutor(
                    max_workers=self.concurrency,
                    thread_name_prefix=f"exec-{self.worker_id[:16]}")
            if not self._claim_available():
                break
            self._pool.submit(self._run_slot)
            dispatched += 1
        return dispatched

    def _claim_available(self) -> bool:
        """Is there queued work this worker could take right now?

        A cheap existence check before occupying a thread. It is advisory --
        the row it saw may be claimed by a peer microseconds later -- and that
        is fine: the claim itself is the authority, and losing this race
        costs one no-op ``claim_next``."""
        from sqlalchemy import select

        from app.models.runtime import AgentExecution

        db = self._session()
        try:
            return db.execute(
                select(AgentExecution.id).where(AgentExecution.status == "QUEUED").limit(1)
            ).first() is not None
        finally:
            db.close()

    def _run_slot(self) -> None:
        try:
            self.claim_and_run()
        except Exception:  # noqa: BLE001 -- a failing slot must not kill the pool
            logger.exception("worker %s: execution slot failed", self.worker_id)

    # ----------------------------------------------------------------- #
    # The loop
    # ----------------------------------------------------------------- #
    def run(self, *, max_ticks: int | None = None,
            poll_interval: float | None = None) -> int:
        """Poll until stopped, or for ``max_ticks`` iterations.

        ``max_ticks`` exists so tests and operators can run a bounded loop;
        without it the worker runs until signalled."""
        interval = poll_interval if poll_interval is not None else settings.WORKER_POLL_INTERVAL_SECONDS
        ticks = 0
        while not self._stop_requested.is_set():
            if max_ticks is not None and ticks >= max_ticks:
                break
            ticks += 1
            try:
                self.heartbeat()
                if self.refresh() != "RUNNING":
                    break
                self.tick()
                self._reap()
            except Exception:  # noqa: BLE001 -- one bad tick must not end the fleet member
                logger.exception("worker %s: tick failed", self.worker_id)
            self._stop_requested.wait(interval)
        return ticks

    def _reap(self) -> None:
        """Recover peers that stopped heartbeating (M3-3.9-FR-020/021).

        Every worker reaps, rather than one designated leader doing it. A
        leader would need an election, and an election needs exactly the
        distributed coordination this platform deliberately does not have.
        Concurrent reaping is harmless: the operations are idempotent state
        reconciliations, and whichever worker gets there first simply finds
        nothing left for the others to do."""
        db = self._session()
        try:
            WorkerFleetService(db).reap_stale_workers()
        finally:
            db.close()

    def install_signal_handlers(self) -> None:  # pragma: no cover - process-level
        def _handle(signum, _frame):
            logger.info("worker %s: signal %s -- draining", self.worker_id, signum)
            self._stop_requested.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handle)
            except (ValueError, OSError):
                pass  # not on the main thread, or unsupported on this platform
