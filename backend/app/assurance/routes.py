"""Phase 5.9 (M5.9) - the assurance HTTP surface, under ``/api/v1/assurance``.

**Export is a distinct, stronger permission.** Reading an assurance result and
extracting a portable bundle of an organization's control evidence are different
acts with different blast radii: the bundle leaves ACT, and once it has left,
ACT's tenant isolation and audit no longer protect it. ``assurance.export`` is
therefore never implied by ``assurance.view`` or ``assurance.manage`` — the same
reasoning that made ``containment.execute`` its own code in 5.6 and
``external_grant.issue`` its own in 5.7.

**Nothing here enforces anything.** Assurance reads evidence and reports what it
shows. The only writes are evaluation results, and a documented exception, both
of which are records *about* evidence rather than evidence itself.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.assurance import frameworks
from app.assurance.controls import ASSURANCE_CATALOG_VERSION, CONTROLS
from app.assurance.schemas import (
    EvaluationRead,
    EvidenceBundleResponse,
    ExceptionRequest,
    TenantEvaluateResponse,
)
from app.assurance.service import AssuranceService
from app.models.user import User

router = APIRouter(prefix="/api/v1/assurance", tags=["assurance"])

_VIEW = "assurance.view"
_MANAGE = "assurance.manage"
_EXPORT = "assurance.export"


@router.get("/controls", response_model=list[dict])
def list_controls(actor: User = Depends(require_permission(_VIEW))):
    """The catalog: what ACT can evidence, and which rows it reads to do it."""
    return [{
        "id": c.id, "question": c.question, "evidence_source": c.evidence_source,
        "scope": c.scope, "version": c.version,
        "catalog_version": ASSURANCE_CATALOG_VERSION,
    } for c in CONTROLS]


@router.get("/frameworks", response_model=list[dict])
def list_frameworks(actor: User = Depends(require_permission(_VIEW))):
    """The frameworks ACT maps evidence to — each carrying the scope note that
    says what the mapping is and is not."""
    return [{
        "id": f.id, "name": f.name, "revision": f.revision, "scope_note": f.scope_note,
        "mapped_controls": len(frameworks.mappings_for(f.id)),
        "mapping_version": frameworks.MAPPING_VERSION,
    } for f in frameworks.FRAMEWORKS]


@router.get("/frameworks/{framework_id}", response_model=dict)
def framework_report(framework_id: str,
                     actor: User = Depends(require_permission(_VIEW)),
                     db: Session = Depends(get_db)):
    """Evidence mapped to one framework's controls.

    Returns mappings and evaluations — never a score, a coverage percentage or
    a status. The response carries its own disclaimer so the caveat travels
    with the data rather than living only in a UI label.
    """
    return AssuranceService(db).framework_report(actor, framework_id)


@router.get("/evaluations", response_model=list[EvaluationRead])
def list_evaluations(subject_id: uuid.UUID | None = Query(default=None),
                     control_id: str | None = Query(default=None),
                     result: str | None = Query(default=None),
                     limit: int = Query(default=500, ge=1, le=5000),
                     actor: User = Depends(require_permission(_VIEW)),
                     db: Session = Depends(get_db)):
    return AssuranceService(db).evaluations(
        actor, subject_id=subject_id, control_id=control_id, result=result, limit=limit)


@router.post("/agents/{agent_id}/evaluate", response_model=list[EvaluationRead])
def evaluate_agent(agent_id: uuid.UUID,
                   actor: User = Depends(require_permission(_MANAGE)),
                   db: Session = Depends(get_db)):
    service = AssuranceService(db)
    agent = service._agent_or_404(actor, agent_id)
    return service.evaluate_agent(actor, agent)


@router.post("/evaluate", response_model=TenantEvaluateResponse)
def evaluate_tenant(actor: User = Depends(require_permission(_MANAGE)),
                    db: Session = Depends(get_db)):
    """Evaluate every agent. Idempotent, and the registered 3.8 handler's entry
    point — no new scheduler."""
    return AssuranceService(db).evaluate_tenant(actor).as_dict()


@router.post("/evaluations/{evaluation_id}/exception", response_model=EvaluationRead)
def record_exception(evaluation_id: uuid.UUID, payload: ExceptionRequest,
                     actor: User = Depends(require_permission(_MANAGE)),
                     db: Session = Depends(get_db)):
    """Document an accepted risk. **The result does not change** — a FAIL with
    an exception still reads FAIL, and the exception records who accepted it
    and why, so an auditor sees both."""
    return AssuranceService(db).record_exception(actor, evaluation_id, reason=payload.reason)


@router.post("/export", response_model=EvidenceBundleResponse)
def export_bundle(framework_id: str | None = Query(default=None),
                  subject_id: uuid.UUID | None = Query(default=None),
                  actor: User = Depends(require_permission(_EXPORT)),
                  db: Session = Depends(get_db)):
    """Export a tenant-scoped evidence bundle, DSSE-signed where signing is
    available and explicitly labelled unsigned where it is not."""
    return AssuranceService(db).export_bundle(
        actor, framework_id=framework_id, subject_id=subject_id)


__all__ = ["router"]
