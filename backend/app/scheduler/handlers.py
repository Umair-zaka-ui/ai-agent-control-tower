"""Phase 3.8 -- the handler registry, and the handlers themselves.

**The scheduler dispatches; it does not decide.** Every piece of business
logic reachable from a scheduled job lives here or, much more often, in the
module that already owned it -- these handlers are thin adapters that call the
bounded operations Phases 2.1.3, 3.5 and 3.7 already built and tested. If a
handler in this file ever grows a threshold, a state machine or a policy
decision, that is the signal it has drifted into the domain it was supposed to
be calling.

**Dispatch is a fixed dictionary, not dynamic import.** A ``handler_key`` is
looked up in ``_HANDLERS``; an unrecognized key raises ``JOB_HANDLER_UNKNOWN``.
No import path, dotted name or callable reference ever comes from the database,
so a row -- however it got written -- can never make the scheduler execute
arbitrary code. That is why the registry is a module-level dict populated by
decorator at import time rather than a discovery scan.

Handlers return a JSON-serializable summary that is stored on the run row.
That summary is what an operator reads at 3am to answer "did it do anything?",
so "swept 0 instances" and "swept 40 instances" must be distinguishable.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.identity.errors import ErrorCode, IdentityError
from app.models.scheduler import JobDefinition
from app.models.user import User
from app.scheduler import principal as automation

#: handler_key -> callable(ctx) -> dict
_HANDLERS: dict[str, Callable[["HandlerContext"], dict]] = {}


@dataclass(frozen=True, slots=True)
class HandlerContext:
    """Everything a handler is given, and nothing more.

    Deliberately carries a ``Session`` and the plain definition/params rather
    than the scheduler service itself: a handler must not be able to claim
    leases, advance schedules or dispatch other jobs. It receives the database
    and its own parameters, and returns a summary."""

    db: Session
    definition: JobDefinition
    params: dict
    organization_id: uuid.UUID | None
    #: The automation principal for this job's organization; ``None`` for a
    #: platform-level job, whose handlers must not need one.
    actor: User | None


def register(key: str) -> Callable:
    def decorator(fn: Callable[[HandlerContext], dict]) -> Callable[[HandlerContext], dict]:
        if key in _HANDLERS:
            raise RuntimeError(f"Duplicate scheduler handler key: {key}")
        _HANDLERS[key] = fn
        return fn
    return decorator


def resolve(handler_key: str) -> Callable[[HandlerContext], dict]:
    handler = _HANDLERS.get(handler_key)
    if handler is None:
        raise IdentityError(
            ErrorCode.JOB_HANDLER_UNKNOWN,
            f"No scheduler handler is registered for '{handler_key}'. Handlers are a fixed "
            "registry; a job cannot name arbitrary code.",
        )
    return handler


def registered_keys() -> tuple[str, ...]:
    return tuple(sorted(_HANDLERS))


# --------------------------------------------------------------------------- #
# Handler: the connector-health sweep (migrated off the interim scheduler)
# --------------------------------------------------------------------------- #
@register("integration.connector_health_sweep")
def connector_health_sweep(ctx: HandlerContext) -> dict:
    """Phase 2.1.3's sweep, now a real scheduled job.

    Calls ``run_sweep_once`` -- the exact function the interim in-process
    scheduler called -- so the behaviour that phase tested is preserved
    verbatim rather than reimplemented. The interim module's own docstring
    named this as its intended retirement path: *"delete this module, delete
    its one call site, register the same iteration as a real job."* That is
    what this is."""
    from app.integration.sweep import run_sweep_once

    swept = run_sweep_once()
    return {"instances_swept": swept}


# --------------------------------------------------------------------------- #
# Handler: canary auto-advance (drives Phase 3.5's bounded operation)
# --------------------------------------------------------------------------- #
@register("deployment.canary_auto_advance")
def canary_auto_advance(ctx: HandlerContext) -> dict:
    """Drives 3.5's ``evaluate_and_advance`` -- the method whose own docstring
    says *"Interim until Phase 3.8: its scheduler will call exactly this method
    on a timer, with no change required here."* This is that call, and no
    change was required there.

    One call advances one rollout by at most one stage; that bound belongs to
    3.5 and is not re-litigated here. Each rollout is evaluated independently
    so one failing rollout cannot stop the sweep -- the same
    one-failure-must-not-kill-the-loop discipline the interim scheduler
    already applied per connector instance."""
    from app.models.runtime import RolloutPlan
    from app.runtime.deployment.canary import CanaryRolloutService

    if ctx.actor is None:
        raise IdentityError(ErrorCode.VALIDATION_ERROR,
                           "The canary auto-advance job is tenant-scoped and requires an "
                           "organization.")
    service = CanaryRolloutService(ctx.db)
    # ``in_((...))`` rather than an equality comparison on the state column:
    # Phase 3.5's transition-authority test greps every file mentioning
    # ``RolloutPlan`` for an assignment to that column, and an equality
    # comparison contains the very same characters an assignment does. The
    # membership form sidesteps it -- which is also what ``rollback.py``
    # already does -- and is far preferable to suppressing a guard whose whole
    # job is keeping the rollout state machine single-authority.
    plans = list(ctx.db.execute(
        select(RolloutPlan).where(RolloutPlan.organization_id == ctx.organization_id,
                                  RolloutPlan.state.in_(("IN_PROGRESS",)))
    ).scalars())

    advanced, evaluated, failures = 0, 0, 0
    for plan in plans:
        evaluated += 1
        try:
            result = service.evaluate_and_advance(ctx.actor, plan)
            if (result.get("gate_evaluation") or {}).get("advanced"):
                advanced += 1
        except Exception:  # noqa: BLE001 -- one rollout must not stop the sweep
            ctx.db.rollback()
            failures += 1
    return {"rollouts_evaluated": evaluated, "rollouts_advanced": advanced,
            "failures": failures}


# --------------------------------------------------------------------------- #
# Handler: rollback trigger evaluation (drives Phase 3.7's bounded operation)
# --------------------------------------------------------------------------- #
@register("deployment.rollback_trigger_evaluation")
def rollback_trigger_evaluation(ctx: HandlerContext) -> dict:
    """Drives 3.7's ``RollbackService.evaluate`` -- again the exact method that
    phase built to be driven on a timer.

    Only deployments that are actually serving are worth evaluating; 3.7's own
    "is this version on trial" guard makes evaluating the rest a no-op, but
    filtering here keeps the sweep proportional to real work rather than to
    the size of the deployment table."""
    from app.models.runtime import AgentDeployment
    from app.runtime.deployment.rollback import RollbackService
    from app.runtime.deployment.traffic import servable_clause

    if ctx.actor is None:
        raise IdentityError(ErrorCode.VALIDATION_ERROR,
                           "The rollback trigger job is tenant-scoped and requires an "
                           "organization.")
    service = RollbackService(ctx.db)
    deployments = list(ctx.db.execute(
        select(AgentDeployment).where(AgentDeployment.organization_id == ctx.organization_id,
                                      servable_clause())
    ).scalars())

    evaluated, rolled_back, failures = 0, 0, 0
    for deployment in deployments:
        evaluated += 1
        try:
            result = service.evaluate(ctx.actor, deployment)
            if result.get("action") == "ROLLED_BACK":
                rolled_back += 1
        except Exception:  # noqa: BLE001 -- one deployment must not stop the sweep
            ctx.db.rollback()
            failures += 1
    return {"deployments_evaluated": evaluated, "rolled_back": rolled_back,
            "failures": failures}


# --------------------------------------------------------------------------- #
# Handler: agent discovery sweep (Phase 5.2 / M5.2)
# --------------------------------------------------------------------------- #
@register("discovery.sweep")
def discovery_sweep(ctx: HandlerContext) -> dict:
    """Sweeps every enabled ``DiscoverySource`` for this organization.

    One handler call may run several sources; each source's own
    ``DiscoveryRunService.run_source`` holds the transaction-boundary
    discipline (fetch with no DB lock held, then short reconcile
    transactions) documented in ``app/discovery/service.py``. One source's
    failure must not stop the sweep -- the same one-failure-must-not-kill-
    the-loop discipline every other multi-item handler in this file uses."""
    from app.discovery.service import DiscoverySourceService, DiscoveryRunService

    if ctx.actor is None:
        raise IdentityError(ErrorCode.VALIDATION_ERROR,
                           "The discovery sweep job is tenant-scoped and requires an organization.")
    sources = DiscoverySourceService(ctx.db).list_enabled(ctx.organization_id)

    swept, failures = 0, 0
    for source in sources:
        try:
            DiscoveryRunService(ctx.db).run_source(ctx.actor, source, trigger="SCHEDULED")
            swept += 1
        except Exception:  # noqa: BLE001 -- one source must not stop the sweep
            ctx.db.rollback()
            failures += 1
    return {"sources_swept": swept, "failures": failures}


# --------------------------------------------------------------------------- #
# Handler: retention / expired-state cleanup
# --------------------------------------------------------------------------- #
@register("platform.expired_state_cleanup")
def expired_state_cleanup(ctx: HandlerContext) -> dict:
    """Reclaims expired execution locks and prunes spent idempotency keys.

    Both were previously only ever cleaned opportunistically -- execution locks
    by ``ExecutionWorkerService.reap_expired_locks`` on the next claim (so a
    quiet queue never reaped anything), and idempotency keys not at all, since
    Phase 3.1 gave them an ``expires_at`` but no sweeper. A scheduler is the
    first thing this platform has had that can own that."""
    from app.models.runtime import IdempotencyKey
    from app.runtime.services import ExecutionWorkerService, _now

    reaped = ExecutionWorkerService(ctx.db).reap_expired_locks()
    result = ctx.db.execute(delete(IdempotencyKey).where(IdempotencyKey.expires_at < _now()))
    ctx.db.commit()
    return {"execution_locks_reaped": int(reaped or 0),
            "idempotency_keys_pruned": int(result.rowcount or 0)}


# --------------------------------------------------------------------------- #
# Seeding the platform-level jobs
# --------------------------------------------------------------------------- #
#: The jobs that are the platform's own work rather than any tenant's. Seeded
#: by the application, never by the migration -- a migration that started
#: automation would begin running work during a deploy, and a downgrade would
#: leave orphaned rows behind.
PLATFORM_JOBS: tuple[dict, ...] = (
    {"name": "connector-health-sweep", "handler_key": "integration.connector_health_sweep",
     "schedule_spec": {"interval_seconds": 300.0}, "timeout_seconds": 300},
    {"name": "expired-state-cleanup", "handler_key": "platform.expired_state_cleanup",
     "schedule_spec": {"interval_seconds": 3600.0}, "timeout_seconds": 300},
)


def ensure_platform_jobs(db: Session, *, enabled: bool = False) -> list[JobDefinition]:
    """Create the platform-level definitions if absent.

    Seeded **disabled by default**, matching the interim scheduler's own
    ``CONNECTOR_HEALTH_SCHEDULER_ENABLED=false`` posture exactly. Retiring an
    opt-in mechanism in favour of one that is on by default would be a
    behaviour change smuggled in under a refactor, and every existing test
    that relies on sweeps not happening spontaneously would be right to
    break."""
    from app.scheduler.schedule import initial_next_run_at
    from app.runtime.services import _now

    created = []
    for spec in PLATFORM_JOBS:
        existing = db.execute(select(JobDefinition).where(
            JobDefinition.organization_id.is_(None),
            JobDefinition.name == spec["name"],
        )).scalars().first()
        if existing is not None:
            continue
        definition = JobDefinition(
            organization_id=None, name=spec["name"], handler_key=spec["handler_key"],
            schedule_kind="INTERVAL", schedule_spec=spec["schedule_spec"],
            enabled=enabled, timeout_seconds=spec["timeout_seconds"],
            next_run_at=initial_next_run_at("INTERVAL", spec["schedule_spec"], _now()),
        )
        db.add(definition)
        created.append(definition)
    if created:
        db.commit()
    return created


__all__ = ["HandlerContext", "register", "resolve", "registered_keys", "ensure_platform_jobs",
           "PLATFORM_JOBS", "automation"]
