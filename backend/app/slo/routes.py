"""Phase 4.7 -- the SLO and alert HTTP surface (§6, §7, AC-05, AC-14).

**No route here enforces or notifies.** SLO evaluation and the alert lifecycle
are read + management endpoints; Phase 4.3's governance engine remains the only
thing that can stop an execution, and nothing on this platform delivers an
alert anywhere -- these are queryable records a future integration consumes.

``POST /slos/evaluate`` is the **interim** trigger, idempotent and bounded, for
Phase 3.8's scheduler to adopt -- the same pattern 4.5, 3.7 and 3.5 built. No
scheduler is built here.

Mounted on the existing ``/api/v1/runtime`` prefix (the 4.3/4.4/4.5 precedent),
never a second namespace.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.authorization.enums import AuthorizationAuditEvent
from app.identity.errors import ErrorCode, IdentityError
from app.models.runtime import RuntimeAlert, SLOEvaluation
from app.models.user import User
from app.runtime.deployment.idempotency import IdempotencyService
from app.runtime.services import _record_event
from app.slo.alerts import AlertService
from app.slo.definitions import SLODefinitionError, SLOService
from app.slo.pipeline import run_slo_evaluation
from app.slo.schemas import (
    AlertRead,
    AlertTransitionRequest,
    SLOCreate,
    SLOEvaluationRead,
    SLORead,
    SLOUpdate,
)
from app.slo.states import AlertSource, AlertStatus

router = APIRouter(prefix="/api/v1/runtime", tags=["slos-alerts"])

# Reading an SLO / its evaluations / an alert is a derived-telemetry read, the
# same plane 4.2/4.4/4.5 read -- so `runtime.telemetry.view` is reused, not
# shadowed. Management is separate: `runtime.slo.manage` for objectives,
# `runtime.alert.manage` for the alert queue.
_VIEW = "runtime.telemetry.view"
_SLO_MANAGE = "runtime.slo.manage"
_ALERT_MANAGE = "runtime.alert.manage"

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


# --------------------------------------------------------------------------- #
# SLO definitions
# --------------------------------------------------------------------------- #
@router.get("/slos", response_model=list[SLORead])
def list_slos(
    enabled: bool | None = Query(default=None),
    sli: str | None = Query(default=None),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    return SLOService(db).list(actor.organization_id, enabled=enabled, sli=sli)


@router.post("/slos", response_model=SLORead, status_code=status.HTTP_201_CREATED)
def create_slo(
    payload: SLOCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_permission(_SLO_MANAGE)),
    db: Session = Depends(get_db),
):
    service = SLOService(db)

    def _create() -> dict:
        try:
            row = service.create(actor.organization_id, actor.id, payload.model_dump(mode="json"))
        except SLODefinitionError as exc:
            raise IdentityError(ErrorCode.SLO_DEFINITION_INVALID, str(exc)) from exc
        _record_event(db, AuthorizationAuditEvent.RUNTIME_SLO_CONFIGURED, actor,
                      organization_id=actor.organization_id,
                      meta={"action": "created", "slo_id": str(row.id),
                            "sli": row.sli, "name": row.name})
        db.commit()
        return {"slo_id": str(row.id)}

    result, _replayed = IdempotencyService(db).execute(
        organization_id=actor.organization_id, operation="slo.create",
        key=idempotency_key, payload=payload.model_dump(mode="json"), fn=_create,
    )
    return service.get_or_none(actor.organization_id, uuid.UUID(result["slo_id"]))


@router.post("/slos/evaluate")
def evaluate_slos(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_permission(_SLO_MANAGE)),
    db: Session = Depends(get_db),
):
    """Run one evaluation cycle now (M4-4.7-FR-030).

    **Interim, and marked as such**: Phase 3.8's distributed scheduler is what
    should drive this on a timer. Idempotent -- ``(slo_id, window)`` evaluations
    dedup, and one ongoing condition is one active alert -- so adopting it there
    is a registration, not a rewrite. Non-gating: a failure produces no
    evaluation and no alert and cannot affect an execution (§9)."""
    def _run() -> dict:
        return run_slo_evaluation(db, organization_id=actor.organization_id)

    body, _replayed = IdempotencyService(db).execute(
        organization_id=actor.organization_id, operation="slo.evaluate",
        key=idempotency_key, payload={}, fn=_run,
    )
    return body


@router.get("/slos/{slo_id}", response_model=SLORead)
def get_slo(
    slo_id: uuid.UUID,
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    row = SLOService(db).get_or_none(actor.organization_id, slo_id)
    if row is None:
        raise IdentityError(ErrorCode.SLO_NOT_FOUND, "SLO not found.")
    return row


@router.patch("/slos/{slo_id}", response_model=SLORead)
def update_slo(
    slo_id: uuid.UUID,
    payload: SLOUpdate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_permission(_SLO_MANAGE)),
    db: Session = Depends(get_db),
):
    service = SLOService(db)
    row = service.get_or_none(actor.organization_id, slo_id)
    if row is None:
        raise IdentityError(ErrorCode.SLO_NOT_FOUND, "SLO not found.")
    changes = payload.model_dump(mode="json", exclude_unset=True)

    def _update() -> dict:
        try:
            service.update(row, changes)
        except SLODefinitionError as exc:
            raise IdentityError(ErrorCode.SLO_DEFINITION_INVALID, str(exc)) from exc
        _record_event(db, AuthorizationAuditEvent.RUNTIME_SLO_CONFIGURED, actor,
                      organization_id=actor.organization_id,
                      meta={"action": "updated", "slo_id": str(row.id),
                            "fields": sorted(changes)})
        db.commit()
        return {"slo_id": str(row.id)}

    IdempotencyService(db).execute(
        organization_id=actor.organization_id, operation="slo.update",
        key=idempotency_key, payload=changes, fn=_update,
    )
    return service.get_or_none(actor.organization_id, slo_id)


@router.delete("/slos/{slo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_slo(
    slo_id: uuid.UUID,
    actor: User = Depends(require_permission(_SLO_MANAGE)),
    db: Session = Depends(get_db),
):
    service = SLOService(db)
    row = service.get_or_none(actor.organization_id, slo_id)
    if row is None:
        raise IdentityError(ErrorCode.SLO_NOT_FOUND, "SLO not found.")
    _record_event(db, AuthorizationAuditEvent.RUNTIME_SLO_CONFIGURED, actor,
                  organization_id=actor.organization_id,
                  meta={"action": "deleted", "slo_id": str(row.id), "name": row.name})
    service.delete(row)
    db.commit()


@router.get("/slos/{slo_id}/evaluations", response_model=list[SLOEvaluationRead])
def slo_evaluations(
    slo_id: uuid.UUID,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    """Evaluation history (newest first) with observed value, state and error-
    budget consumption (M4-4.7-FR-003, AC-02)."""
    if SLOService(db).get_or_none(actor.organization_id, slo_id) is None:
        raise IdentityError(ErrorCode.SLO_NOT_FOUND, "SLO not found.")
    return list(db.execute(
        select(SLOEvaluation)
        .where(SLOEvaluation.slo_id == slo_id,
               SLOEvaluation.organization_id == actor.organization_id)
        .order_by(SLOEvaluation.evaluated_at.desc())
        .limit(limit)
    ).scalars())


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #
@router.get("/alerts", response_model=list[AlertRead])
def list_alerts(
    status_: str | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
    source: str | None = Query(default=None),
    agent_id: uuid.UUID | None = Query(default=None),
    slo_id: uuid.UUID | None = Query(default=None),
    opened_after: datetime | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    if status_ is not None and status_ not in {s.value for s in AlertStatus}:
        raise IdentityError(ErrorCode.VALIDATION_ERROR, f"Unknown status {status_!r}.")
    if source is not None and source not in {s.value for s in AlertSource}:
        raise IdentityError(ErrorCode.VALIDATION_ERROR, f"Unknown source {source!r}.")

    stmt = select(RuntimeAlert).where(RuntimeAlert.organization_id == actor.organization_id)
    if status_:
        stmt = stmt.where(RuntimeAlert.status == status_)
    if severity:
        stmt = stmt.where(RuntimeAlert.severity == severity)
    if source:
        stmt = stmt.where(RuntimeAlert.source == source)
    if agent_id:
        stmt = stmt.where(RuntimeAlert.agent_id == agent_id)
    if slo_id:
        stmt = stmt.where(RuntimeAlert.slo_id == slo_id)
    if opened_after:
        stmt = stmt.where(RuntimeAlert.opened_at >= opened_after)
    return list(db.execute(
        stmt.order_by(RuntimeAlert.opened_at.desc(), RuntimeAlert.id.desc())
        .limit(limit).offset(offset)
    ).scalars())


@router.get("/alerts/{alert_id}", response_model=AlertRead)
def get_alert(
    alert_id: uuid.UUID,
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    alert = _alert_or_404(db, actor, alert_id)
    return alert


def _alert_or_404(db: Session, actor: User, alert_id: uuid.UUID) -> RuntimeAlert:
    alert = db.get(RuntimeAlert, alert_id)
    if alert is None or alert.organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.ALERT_NOT_FOUND, "Alert not found.")
    return alert


def _transition(db: Session, actor: User, alert_id: uuid.UUID, target: str,
                note: str | None) -> RuntimeAlert:
    alert = _alert_or_404(db, actor, alert_id)
    return AlertService(db).transition(alert, target, actor.id, note=note)


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertRead)
def acknowledge_alert(
    alert_id: uuid.UUID,
    payload: AlertTransitionRequest | None = None,
    actor: User = Depends(require_permission(_ALERT_MANAGE)),
    db: Session = Depends(get_db),
):
    return _transition(db, actor, alert_id, AlertStatus.ACKNOWLEDGED.value,
                       payload.note if payload else None)


@router.post("/alerts/{alert_id}/resolve", response_model=AlertRead)
def resolve_alert(
    alert_id: uuid.UUID,
    payload: AlertTransitionRequest | None = None,
    actor: User = Depends(require_permission(_ALERT_MANAGE)),
    db: Session = Depends(get_db),
):
    return _transition(db, actor, alert_id, AlertStatus.RESOLVED.value,
                       payload.note if payload else None)


@router.post("/alerts/{alert_id}/suppress", response_model=AlertRead)
def suppress_alert(
    alert_id: uuid.UUID,
    payload: AlertTransitionRequest | None = None,
    actor: User = Depends(require_permission(_ALERT_MANAGE)),
    db: Session = Depends(get_db),
):
    return _transition(db, actor, alert_id, AlertStatus.SUPPRESSED.value,
                       payload.note if payload else None)
