"""Phase 3.8 -- scheduler management API.

Deliberately small. The scheduler is a **process**, not an HTTP service: the
claim/dispatch loop is ``python -m app.scheduler.runner``, and nothing here can
trigger a job run. These endpoints manage *definitions* and read *history*.

That separation is a safety property rather than an aesthetic one. If an HTTP
route could dispatch a job, an authenticated caller could bypass the lease
entirely -- running a handler with no occurrence row, no lease, and no
protection against a peer running it simultaneously. Every path to execution
goes through ``SchedulerService`` on a scheduler instance, which is the only
place the exactly-once guarantee holds.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.authorization.enums import AuthorizationAuditEvent
from app.identity.errors import ErrorCode, IdentityError
from app.models.scheduler import JobDefinition, JobRun
from app.models.user import User
from app.scheduler import handlers as handler_registry
from app.scheduler import schedule
from app.scheduler.service import SchedulerService

router = APIRouter(prefix="/api/v1/runtime/scheduler", tags=["scheduler"])

_VIEW = "runtime.scheduler.view"
_MANAGE = "runtime.scheduler.manage"


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class JobDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None
    name: str
    handler_key: str
    schedule_kind: str
    schedule_spec: dict
    params: dict
    enabled: bool
    timeout_seconds: int
    retry_policy: dict
    concurrency_policy: str
    next_run_at: object | None = None
    last_claimed_at: object | None = None


class JobDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    handler_key: str = Field(min_length=1, max_length=64)
    schedule_kind: str = "INTERVAL"
    schedule_spec: dict = Field(default_factory=dict)
    params: dict = Field(default_factory=dict)
    enabled: bool = True
    timeout_seconds: int = Field(default=300, gt=0)
    retry_policy: dict = Field(default_factory=dict)
    concurrency_policy: str = "NO_OVERLAP"


class JobDefinitionUpdate(BaseModel):
    enabled: bool | None = None
    schedule_spec: dict | None = None
    params: dict | None = None
    timeout_seconds: int | None = Field(default=None, gt=0)
    retry_policy: dict | None = None
    concurrency_policy: str | None = None


class JobRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_definition_id: uuid.UUID
    occurrence_key: str
    status: str
    attempt: int
    lease_owner: str | None
    lease_expires_at: object | None = None
    heartbeat_at: object | None = None
    started_at: object | None = None
    ended_at: object | None = None
    result: dict | None
    error: str | None
    recovered_from: str | None


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@router.get("/jobs", response_model=list[JobDefinitionRead])
def list_jobs(actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    """This organization's jobs, plus the platform-level ones.

    Platform jobs are readable by any authenticated viewer because their
    *existence* is operational context every tenant benefits from seeing (a
    tenant debugging stale connector health should be able to tell whether the
    sweep is even enabled). They are not editable here -- see ``update_job``."""
    return list(db.execute(
        select(JobDefinition).where(
            (JobDefinition.organization_id == actor.organization_id)
            | (JobDefinition.organization_id.is_(None))
        ).order_by(JobDefinition.name.asc())
    ).scalars())


@router.post("/jobs", response_model=JobDefinitionRead, status_code=201)
def create_job(payload: JobDefinitionCreate,
               actor: User = Depends(require_permission(_MANAGE)),
               db: Session = Depends(get_db)):
    """Always tenant-scoped. A caller cannot create a platform-level job
    through the API -- those are seeded by the platform itself, and letting a
    tenant mint work that runs outside every tenant boundary would be a
    privilege-escalation route dressed as a convenience."""
    if payload.handler_key not in handler_registry.registered_keys():
        raise IdentityError(
            ErrorCode.JOB_HANDLER_UNKNOWN,
            f"'{payload.handler_key}' is not a registered handler. Known handlers: "
            f"{', '.join(handler_registry.registered_keys())}.")
    if payload.schedule_kind not in schedule.SCHEDULE_KINDS:
        raise IdentityError(
            ErrorCode.VALIDATION_ERROR,
            f"schedule_kind must be one of {sorted(schedule.SCHEDULE_KINDS)}.")

    from app.runtime.services import _now, _record_event

    now = _now()
    definition = JobDefinition(
        organization_id=actor.organization_id,
        name=payload.name,
        handler_key=payload.handler_key,
        schedule_kind=payload.schedule_kind,
        schedule_spec=payload.schedule_spec,
        params=payload.params,
        enabled=payload.enabled,
        timeout_seconds=payload.timeout_seconds,
        retry_policy=payload.retry_policy,
        concurrency_policy=payload.concurrency_policy,
        next_run_at=schedule.initial_next_run_at(payload.schedule_kind, payload.schedule_spec,
                                                 now) if payload.enabled else None,
        created_by=actor.id,
    )
    db.add(definition)
    _record_event(db, AuthorizationAuditEvent.SCHEDULED_JOB_STARTED, actor,
                 organization_id=actor.organization_id, severity="INFO",
                 meta={"action": "created", "job_name": payload.name,
                       "handler_key": payload.handler_key, "enabled": payload.enabled})
    db.commit()
    db.refresh(definition)
    return definition


@router.get("/jobs/{definition_id}", response_model=JobDefinitionRead)
def get_job(definition_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)),
            db: Session = Depends(get_db)):
    return SchedulerService(db).get_or_404(actor.organization_id, definition_id)


@router.patch("/jobs/{definition_id}", response_model=JobDefinitionRead)
def update_job(definition_id: uuid.UUID, payload: JobDefinitionUpdate,
               actor: User = Depends(require_permission(_MANAGE)),
               db: Session = Depends(get_db)):
    """Enable/disable and edit. A platform-level job is **not** editable by a
    tenant even though it is visible to them: it runs outside any tenant's
    boundary, so no tenant's administrator is the right authority to disable
    it."""
    from app.runtime.services import _now, _record_event

    service = SchedulerService(db)
    definition = service.get_or_404(actor.organization_id, definition_id)
    if definition.organization_id is None:
        raise IdentityError(
            ErrorCode.PERMISSION_DENIED,
            "Platform-level scheduled jobs cannot be modified by a tenant administrator.")

    if payload.schedule_spec is not None:
        definition.schedule_spec = payload.schedule_spec
    if payload.params is not None:
        definition.params = payload.params
    if payload.timeout_seconds is not None:
        definition.timeout_seconds = payload.timeout_seconds
    if payload.retry_policy is not None:
        definition.retry_policy = payload.retry_policy
    if payload.concurrency_policy is not None:
        definition.concurrency_policy = payload.concurrency_policy
    if payload.enabled is not None:
        definition.enabled = payload.enabled
        # Re-enabling re-arms the schedule from now rather than resuming a
        # ``next_run_at`` that may be far in the past -- otherwise a job
        # disabled for a week would fire the instant it came back.
        definition.next_run_at = schedule.initial_next_run_at(
            definition.schedule_kind, definition.schedule_spec, _now()
        ) if payload.enabled else None

    _record_event(db, AuthorizationAuditEvent.SCHEDULED_JOB_STARTED, actor,
                 organization_id=actor.organization_id, severity="INFO",
                 meta={"action": "updated", "job_name": definition.name,
                       "enabled": definition.enabled})
    db.commit()
    db.refresh(definition)
    return definition


@router.get("/jobs/{definition_id}/runs", response_model=list[JobRunRead])
def list_runs(definition_id: uuid.UUID, limit: int = 50, offset: int = 0,
              actor: User = Depends(require_permission(_VIEW)),
              db: Session = Depends(get_db)):
    service = SchedulerService(db)
    definition = service.get_or_404(actor.organization_id, definition_id)
    return service.runs_for(definition, limit=limit, offset=offset)


@router.get("/handlers", response_model=list[str])
def list_handlers(actor: User = Depends(require_permission(_VIEW))):
    """The registry, so an operator creating a job can see what may be named.
    Also the honest answer to "what can this scheduler actually run" -- the
    list is exhaustive by construction."""
    return list(handler_registry.registered_keys())
