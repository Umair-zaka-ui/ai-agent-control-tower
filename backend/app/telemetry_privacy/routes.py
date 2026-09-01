"""Phase 4.8 -- the telemetry-privacy HTTP surface (§6, §7, §8).

Two routers:

- ``router`` on ``/api/v1/runtime/telemetry`` -- capture-policy CRUD, the
  explainable effective-mode resolver, retention-policy config, and the
  interim, idempotent, 3.8-schedulable retention sweep.
- ``content_router`` on ``/api/v1/observability`` -- the **trace-content view**,
  gated by ``runtime.trace.content.view`` (distinct from and strictly stronger
  than the 4.2 metadata view) and **audited on every call**
  (``RUNTIME_TRACE_CONTENT_VIEWED``).

**Nothing here enforces or notifies.** A capture or retention operation never
stops or alters an execution (§9); the content view is an ordinary indexed read
plus a governed, idempotent materialisation.

**404 vs 403 discipline** (§6): a trace that does not exist *for this tenant* is
404 (cross-tenant existence is never leaked); a trace that does exist for the
tenant but whose caller lacks the content permission is 403
(``TRACE_CONTENT_ACCESS_DENIED``). The trace is resolved *before* the content
permission is checked, so the two cases stay distinct.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.authorization.enums import AuthorizationAuditEvent
from app.identity.errors import ErrorCode, IdentityError
from app.models.runtime import AgentExecution
from app.models.user import User
from app.observability.explorer import TraceExplorer
from app.runtime.deployment.idempotency import IdempotencyService
from app.runtime.services import _record_event
from app.services.rbac_service import user_has_permission
from app.telemetry_privacy.content import TraceContentService
from app.telemetry_privacy.policy import (
    CapturePolicyError,
    CapturePolicyService,
    resolve_capture_mode,
)
from app.telemetry_privacy.retention import (
    RetentionPolicyError,
    RetentionPolicyService,
    RetentionSweeper,
)
from app.telemetry_privacy.schemas import (
    CapturePolicyCreate,
    CapturePolicyRead,
    CapturePolicyUpdate,
    RetentionPolicyWrite,
)

router = APIRouter(prefix="/api/v1/runtime/telemetry", tags=["telemetry-privacy"])
content_router = APIRouter(prefix="/api/v1/observability", tags=["observability"])

_POLICY_VIEW = "runtime.telemetry_policy.view"
_POLICY_MANAGE = "runtime.telemetry_policy.manage"
_METADATA_VIEW = "runtime.telemetry.view"
_CONTENT_VIEW = "runtime.trace.content.view"


# --------------------------------------------------------------------------- #
# Capture policies
# --------------------------------------------------------------------------- #
@router.get("/capture-policies", response_model=list[CapturePolicyRead])
def list_capture_policies(
    actor: User = Depends(require_permission(_POLICY_VIEW)),
    db: Session = Depends(get_db),
):
    return CapturePolicyService(db).list(actor.organization_id)


@router.post("/capture-policies", response_model=CapturePolicyRead,
             status_code=status.HTTP_201_CREATED)
def create_capture_policy(
    payload: CapturePolicyCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_permission(_POLICY_MANAGE)),
    db: Session = Depends(get_db),
):
    service = CapturePolicyService(db)

    def _create() -> dict:
        try:
            row = service.create(actor.organization_id, actor.id,
                                 payload.model_dump(mode="json"))
        except CapturePolicyError as exc:
            raise IdentityError(ErrorCode.TELEMETRY_POLICY_INVALID, str(exc)) from exc
        _record_event(db, AuthorizationAuditEvent.RUNTIME_TELEMETRY_POLICY_CHANGED, actor,
                      organization_id=actor.organization_id,
                      meta={"action": "capture_policy_created", "policy_id": str(row.id),
                            "mode": row.mode,
                            "scope": {"environment_id": str(row.environment_id) if row.environment_id else None,
                                      "agent_id": str(row.agent_id) if row.agent_id else None,
                                      "classification": row.classification}})
        db.commit()
        return {"policy_id": str(row.id)}

    result, _replayed = IdempotencyService(db).execute(
        organization_id=actor.organization_id, operation="telemetry.capture_policy.create",
        key=idempotency_key, payload=payload.model_dump(mode="json"), fn=_create,
    )
    return service.get_or_none(actor.organization_id, uuid.UUID(result["policy_id"]))


@router.get("/capture-policies/{policy_id}", response_model=CapturePolicyRead)
def get_capture_policy(
    policy_id: uuid.UUID,
    actor: User = Depends(require_permission(_POLICY_VIEW)),
    db: Session = Depends(get_db),
):
    row = CapturePolicyService(db).get_or_none(actor.organization_id, policy_id)
    if row is None:
        raise IdentityError(ErrorCode.TELEMETRY_POLICY_NOT_FOUND, "Capture policy not found.")
    return row


@router.patch("/capture-policies/{policy_id}", response_model=CapturePolicyRead)
def update_capture_policy(
    policy_id: uuid.UUID,
    payload: CapturePolicyUpdate,
    actor: User = Depends(require_permission(_POLICY_MANAGE)),
    db: Session = Depends(get_db),
):
    service = CapturePolicyService(db)
    row = service.get_or_none(actor.organization_id, policy_id)
    if row is None:
        raise IdentityError(ErrorCode.TELEMETRY_POLICY_NOT_FOUND, "Capture policy not found.")
    changes = payload.model_dump(mode="json", exclude_unset=True)
    try:
        service.update(row, changes)
    except CapturePolicyError as exc:
        raise IdentityError(ErrorCode.TELEMETRY_POLICY_INVALID, str(exc)) from exc
    _record_event(db, AuthorizationAuditEvent.RUNTIME_TELEMETRY_POLICY_CHANGED, actor,
                  organization_id=actor.organization_id,
                  meta={"action": "capture_policy_updated", "policy_id": str(row.id),
                        "fields": sorted(changes), "mode": row.mode})
    db.commit()
    return service.get_or_none(actor.organization_id, policy_id)


@router.delete("/capture-policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_capture_policy(
    policy_id: uuid.UUID,
    actor: User = Depends(require_permission(_POLICY_MANAGE)),
    db: Session = Depends(get_db),
):
    service = CapturePolicyService(db)
    row = service.get_or_none(actor.organization_id, policy_id)
    if row is None:
        raise IdentityError(ErrorCode.TELEMETRY_POLICY_NOT_FOUND, "Capture policy not found.")
    _record_event(db, AuthorizationAuditEvent.RUNTIME_TELEMETRY_POLICY_CHANGED, actor,
                  organization_id=actor.organization_id,
                  meta={"action": "capture_policy_deleted", "policy_id": str(row.id)})
    service.delete(row)
    db.commit()


@router.get("/effective-mode")
def effective_mode(
    environment_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    classification: str | None = None,
    actor: User = Depends(require_permission(_POLICY_VIEW)),
    db: Session = Depends(get_db),
):
    """Resolve the effective capture mode for a scope, fully explained
    (M4-4.8-FR-003)."""
    return resolve_capture_mode(
        db, organization_id=actor.organization_id, environment_id=environment_id,
        agent_id=agent_id,
        classification=classification.upper() if classification else None,
    ).as_dict()


# --------------------------------------------------------------------------- #
# Retention policies
# --------------------------------------------------------------------------- #
@router.get("/retention-policies")
def list_retention_policies(
    actor: User = Depends(require_permission(_POLICY_VIEW)),
    db: Session = Depends(get_db),
):
    """The effective retention for every telemetry class (tenant row or
    platform default), with each class's floor and whether it is retain-only."""
    return RetentionPolicyService(db).effective(actor.organization_id)


@router.post("/retention-policies")
def set_retention_policy(
    payload: RetentionPolicyWrite,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_permission(_POLICY_MANAGE)),
    db: Session = Depends(get_db),
):
    service = RetentionPolicyService(db)

    def _set() -> dict:
        try:
            row = service.upsert(actor.organization_id, actor.id,
                                 payload.model_dump(mode="json"))
        except RetentionPolicyError as exc:
            raise IdentityError(ErrorCode.RETENTION_POLICY_INVALID, str(exc)) from exc
        _record_event(db, AuthorizationAuditEvent.RUNTIME_TELEMETRY_POLICY_CHANGED, actor,
                      organization_id=actor.organization_id,
                      meta={"action": "retention_policy_set",
                            "telemetry_class": row.telemetry_class,
                            "retention_days": row.retention_days})
        db.commit()
        return {"telemetry_class": row.telemetry_class,
                "retention_days": row.retention_days}

    result, _replayed = IdempotencyService(db).execute(
        organization_id=actor.organization_id, operation="telemetry.retention_policy.set",
        key=idempotency_key, payload=payload.model_dump(mode="json"), fn=_set,
    )
    return result


@router.post("/retention/run")
def run_retention(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_permission(_POLICY_MANAGE)),
    db: Session = Depends(get_db),
):
    """Expire telemetry that has outlived its per-class retention
    (M4-4.8-FR-031, FR-033).

    **Interim, and marked as such**: Phase 3.8's distributed scheduler is what
    should drive this on a timer. Idempotent and bounded -- it deletes in
    committed batches and a second run continues where the first stopped, so
    adopting it there is a registration, not a rewrite. Non-gating: it touches
    only telemetry tables and cannot affect an execution (§9). Governance and
    financial evidence are retain-only and are never deleted."""
    def _run() -> dict:
        result = RetentionSweeper(db).run(actor.organization_id)
        if result.total_deleted:
            _record_event(db, AuthorizationAuditEvent.RUNTIME_TELEMETRY_RETENTION_RUN, actor,
                          organization_id=actor.organization_id,
                          meta={"total_deleted": result.total_deleted,
                                "by_class": {c.telemetry_class: c.deleted
                                             for c in result.classes if c.deleted}})
            db.commit()
        return result.as_dict()

    body, _replayed = IdempotencyService(db).execute(
        organization_id=actor.organization_id, operation="telemetry.retention.run",
        key=idempotency_key, payload={}, fn=_run,
    )
    return body


# --------------------------------------------------------------------------- #
# Trace content -- the distinct, stronger, audited read (§4.3)
# --------------------------------------------------------------------------- #
@content_router.get("/traces/{trace_id}/content")
def get_trace_content(
    trace_id: str,
    actor: User = Depends(require_permission(_METADATA_VIEW)),
    db: Session = Depends(get_db),
):
    """Trace **content** -- prompts, tool arguments, tool results, model output
    -- governed by capture policy and gated by ``runtime.trace.content.view``
    (M4-4.8-FR-020..022).

    Metadata view alone does not grant this. The dependency above only
    establishes the caller may see *this trace exists*; the content permission
    is checked here, after the trace resolves, so an in-tenant caller without
    it gets 403 while a cross-tenant trace id gets 404.

    Every successful content view is audited (``RUNTIME_TRACE_CONTENT_VIEWED``),
    recording the actor and the resources -- never the content itself."""
    executions: list[AgentExecution] = TraceExplorer(db).find_by_trace_id(
        actor.organization_id, trace_id)
    if not executions:
        raise IdentityError(ErrorCode.TRACE_NOT_FOUND, "Trace not found.")

    if not user_has_permission(db, actor, _CONTENT_VIEW):
        raise IdentityError(
            ErrorCode.TRACE_CONTENT_ACCESS_DENIED,
            "Viewing trace content requires the runtime.trace.content.view "
            "permission, which is separate from and stronger than the metadata "
            "trace view.")

    service = TraceContentService(db)
    views = [service.view(actor.organization_id, execution) for execution in executions]

    _record_event(db, AuthorizationAuditEvent.RUNTIME_TRACE_CONTENT_VIEWED, actor,
                  organization_id=actor.organization_id,
                  execution_id=executions[0].id,
                  meta={"trace_id": trace_id,
                        "execution_ids": [str(e.id) for e in executions],
                        "modes": sorted({v["mode"] for v in views})})
    db.commit()

    return {"trace_id": trace_id, "executions": len(views), "traces": views}
