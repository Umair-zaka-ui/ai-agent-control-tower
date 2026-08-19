"""Phase 3.9 -- execution worker fleet API.

Deliberately small, and deliberately incapable of one thing: **no route here
can run an execution.** The fleet is observable and steerable through HTTP;
work is claimed only by a worker process, only through
``ExecutionWorkerService.claim_next``, only under a committed lease.

That is the same safety property Phase 3.8 built into the scheduler API, and
it matters more here. If an HTTP route could dispatch an execution, an
authenticated caller could run agent work with no lease, no worker identity
and no protection against a real worker running the same execution
concurrently -- which would defeat ``execution_locks``' unique constraint by
simply never taking one.

Registration is likewise not exposed. A worker registers itself, from inside
the process, as part of starting up; an HTTP endpoint that let anything else
create a registration would let a caller inject phantom capacity into the
fleet -- and rolling derives real step weights from that capacity, so phantom
workers would produce a rolling deployment that moves production traffic onto
machines that do not exist.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.models.user import User
from app.workers.fleet import WorkerFleetService

# Mounted at /fleet, not /workers, and the reason is a real collision rather
# than taste. ``GET /api/v1/runtime/workers`` and ``POST .../workers/reap``
# have existed since M1: the first reports worker *activity* derived from
# execution attempts, the second reaps expired execution locks. Both are still
# correct and still used. This phase manages a different thing -- registered
# worker *processes* and their declared capacity -- so it nests beside them
# rather than taking their paths over, exactly as Phase 3.7 nested under
# /deployments/{id}/rollback/... rather than seizing the Phase 5.0 /rollback
# endpoint. (The build prompt's §6 sketched these as /api/v1/workers; the
# repository's runtime API is uniformly /api/v1/runtime/..., and that prefix
# was already taken. Reported rather than silently redesigned.)
router = APIRouter(prefix="/api/v1/runtime/fleet", tags=["workers"])

_VIEW = "runtime.worker.view"
_MANAGE = "runtime.worker.manage"


class WorkerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    worker_id: str
    cohort: str
    status: str
    concurrency: int
    active_count: int
    hostname: str | None
    heartbeat_at: object | None = None
    registered_at: object | None = None
    stopped_at: object | None = None


class FleetRead(BaseModel):
    workers: list[WorkerRead]
    #: Live declared capacity per cohort -- the numbers a rolling deployment
    #: derives its step weights from, exposed so an operator can predict the
    #: shape of a rollout before starting one.
    capacity_by_cohort: dict[str, int]


class QueueDepthRead(BaseModel):
    queued: int
    running: int
    workers: int
    workers_accepting_work: int
    capacity: int
    active: int
    available_slots: int


@router.get("", response_model=FleetRead)
def list_fleet(include_stopped: bool = False,
               actor: User = Depends(require_permission(_VIEW)),
               db: Session = Depends(get_db)) -> FleetRead:
    """M3-3.9-FR-001 -- the fleet, as it currently is.

    Platform-scoped rather than tenant-scoped, because workers are: one worker
    serves every tenant's queue by position, exactly as M1's claim query has
    always done. Filtering this by the caller's organization would invent a
    per-tenant fleet that does not exist."""
    fleet = WorkerFleetService(db)
    return FleetRead(
        workers=[WorkerRead.model_validate(w)
                 for w in fleet.list_workers(include_stopped=include_stopped)],
        capacity_by_cohort=fleet.capacity_by_cohort(),
    )


@router.get("/queue-depth", response_model=QueueDepthRead)
def queue_depth(actor: User = Depends(require_permission(_VIEW)),
                db: Session = Depends(get_db)) -> QueueDepthRead:
    """M3-3.9-FR-014 -- backpressure, as numbers someone can act on.

    Sits at the fleet root rather than under ``/workers/`` because it is a
    property of the queue and the fleet together, not of any one worker."""
    return QueueDepthRead(**WorkerFleetService(db).queue_depth())


@router.get("/workers/{worker_id}", response_model=WorkerRead)
def get_worker(worker_id: str,
               actor: User = Depends(require_permission(_VIEW)),
               db: Session = Depends(get_db)) -> WorkerRead:
    return WorkerRead.model_validate(WorkerFleetService(db).get_or_404(worker_id))


@router.post("/workers/{worker_id}/drain", response_model=WorkerRead)
def drain_worker(worker_id: str,
                 actor: User = Depends(require_permission(_MANAGE)),
                 db: Session = Depends(get_db)) -> WorkerRead:
    """M3-3.9-FR-002 -- ask a worker to stop taking new work.

    This writes the *request*; the worker acts on it when it next reconciles
    (``ExecutionWorker.refresh``), within one poll interval. It is not a kill:
    executions already in flight run to completion, which is the whole
    difference between draining a worker and losing one."""
    worker = WorkerFleetService(db).drain(
        worker_id, actor_organization_id=actor.organization_id, actor_id=actor.id)
    return WorkerRead.model_validate(worker)


@router.post("/reap", response_model=QueueDepthRead)
def reap_stale(actor: User = Depends(require_permission(_MANAGE)),
               db: Session = Depends(get_db)) -> QueueDepthRead:
    """Run the staleness sweep now instead of waiting for a worker's next
    tick (M3-3.9-FR-020).

    An operator-facing convenience during an incident, not a required part of
    the recovery path: every worker sweeps on every tick, so a fleet with any
    live member recovers without this. It exists for the case that has no live
    member -- the fleet is entirely down and someone needs the stuck
    executions released before starting a replacement."""
    fleet = WorkerFleetService(db)
    fleet.reap_stale_workers()
    return QueueDepthRead(**fleet.queue_depth())
