"""Phase 5.2 (M5.2) - Agent Discovery Framework API.

Deliberately minimal, mirroring the connector-management surface's own
shape: config CRUD, run history, and finding resolution. **No route can
directly write ``agents``** -- every effect on the canonical registry flows
through ``DiscoveryRunService``/``ReconciliationService``, which themselves
go through the Phase 5.1 server-authoritative path. No speculative
discovery/graph/posture endpoints (those are 5.3+).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.discovery.adapters import registry as adapter_registry
from app.discovery.schemas import (
    DiscoveryAdapterRead,
    DiscoveryFindingRead,
    DiscoveryFindingResolveRequest,
    DiscoveryRunRead,
    DiscoverySourceCreate,
    DiscoverySourceRead,
    DiscoverySourceUpdate,
)
from app.discovery.service import DiscoveryFindingService, DiscoveryRunService, DiscoverySourceService
from app.models.user import User

router = APIRouter(prefix="/api/v1/discovery", tags=["discovery"])

_VIEW = "discovery.source.view"
_MANAGE = "discovery.source.manage"


@router.get("/adapters", response_model=list[DiscoveryAdapterRead])
def list_adapters(actor: User = Depends(require_permission(_VIEW))):
    """The registry, exhaustive by construction -- the same honesty
    ``GET /scheduler/handlers`` gives for scheduler handlers."""
    out = []
    for key in adapter_registry.registered_keys():
        d = adapter_registry.resolve(key).describe()
        out.append(DiscoveryAdapterRead(adapter_key=d.adapter_key, display_name=d.display_name,
                                        config_schema=d.config_schema, requires_secret=d.requires_secret))
    return out


@router.get("/sources", response_model=list[DiscoverySourceRead])
def list_sources(actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    return DiscoverySourceService(db).list(actor)


@router.post("/sources", response_model=DiscoverySourceRead, status_code=201)
def create_source(payload: DiscoverySourceCreate, actor: User = Depends(require_permission(_MANAGE)),
                  db: Session = Depends(get_db)):
    return DiscoverySourceService(db).create(
        actor, name=payload.name, adapter_key=payload.adapter_key, config=payload.config,
        secret=payload.secret, enabled=payload.enabled,
        missed_sweeps_before_stale=payload.missed_sweeps_before_stale)


@router.get("/sources/{source_id}", response_model=DiscoverySourceRead)
def get_source(source_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)),
               db: Session = Depends(get_db)):
    return DiscoverySourceService(db).get_or_404(actor, source_id)


@router.patch("/sources/{source_id}", response_model=DiscoverySourceRead)
def update_source(source_id: uuid.UUID, payload: DiscoverySourceUpdate,
                  actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db)):
    return DiscoverySourceService(db).update(
        actor, source_id, enabled=payload.enabled, config=payload.config, secret=payload.secret,
        missed_sweeps_before_stale=payload.missed_sweeps_before_stale)


@router.post("/sources/{source_id}/runs", response_model=DiscoveryRunRead, status_code=201)
def trigger_run(source_id: uuid.UUID,
                idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db)):
    """Manually triggers one sweep, synchronously (this environment has no
    background worker for it, the same "eager" pattern the registry's
    import/export jobs already use). ``Idempotency-Key`` reuses the Phase
    3.1 claim-then-poll contract (M5.2-AC-14): a retried request with the
    same key returns the same run rather than sweeping twice."""
    from app.runtime.deployment.idempotency import IdempotencyService

    source_service = DiscoverySourceService(db)
    source = source_service.get_or_404(actor, source_id)

    def _do() -> dict:
        run = DiscoveryRunService(db).run_source(actor, source, trigger="MANUAL")
        return {"run_id": str(run.id)}

    result, _replayed = IdempotencyService(db).execute(
        organization_id=actor.organization_id, operation="discovery.run", key=idempotency_key,
        payload={"source_id": str(source_id)}, fn=_do)
    return DiscoveryRunService(db).get_or_404(actor, uuid.UUID(result["run_id"]))


@router.get("/sources/{source_id}/runs", response_model=list[DiscoveryRunRead])
def list_runs(source_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)),
              db: Session = Depends(get_db)):
    return DiscoveryRunService(db).list_for_source(actor, source_id)


@router.get("/runs/{run_id}", response_model=DiscoveryRunRead)
def get_run(run_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)),
            db: Session = Depends(get_db)):
    return DiscoveryRunService(db).get_or_404(actor, run_id)


@router.get("/findings", response_model=list[DiscoveryFindingRead])
def list_findings(status_filter: str | None = Query(default=None, alias="status"),
                  actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    return DiscoveryFindingService(db).list(actor, status=status_filter)


@router.post("/findings/{finding_id}/resolve", response_model=DiscoveryFindingRead)
def resolve_finding(finding_id: uuid.UUID, payload: DiscoveryFindingResolveRequest,
                    actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db)):
    return DiscoveryFindingService(db).resolve(actor, finding_id, status=payload.status)
