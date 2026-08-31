"""Phase 4.6 -- the export management + metrics HTTP surface (§6, §7, AC-11,
AC-12).

Two routers:

* ``/api/v1/observability/export/*`` -- read the effective export config and
  exporter health (``runtime.telemetry.view``); set the per-environment export
  target (``runtime.telemetry.export.manage``, audited, idempotent).
* ``GET /metrics`` -- Prometheus text exposition.

**The metrics endpoint's exposure model, stated:** it is authenticated
(``runtime.telemetry.view``) and **tenant-scoped** -- it returns the calling
user's organization's numbers and no one else's, and every label is a bounded
dimension, so one tenant's values can never leak to another through a label or a
series. The process-level exporter-health gauges it also emits carry no tenant
data. This is deliberately not the "open unauthenticated scrape target" model:
on a multi-tenant platform an unauthenticated ``/metrics`` is a cross-tenant
disclosure, so a collector scrapes it with a service credential like any other
authenticated API.

**No route here makes execution depend on export.** These are reads and a
config write; none of them is on, or can block, the execution path.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.models.user import User
from app.runtime.deployment.idempotency import IdempotencyService
from app.telemetry_export.metrics import MetricsCollector
from app.telemetry_export.schemas import (
    ExportConfigRead,
    ExportConfigWrite,
    ExporterHealthRead,
)
from app.telemetry_export.service import TelemetryExportService

# `runtime.telemetry.view` already guards "view runtime telemetry and execution
# traces" -- exporter health and the metrics surface are that same read, so it
# is reused rather than shadowed by a synonym (the precedent 4.2/4.4 set).
_VIEW = "runtime.telemetry.view"
# Pointing telemetry off-platform is its own act, and audited.
_MANAGE = "runtime.telemetry.export.manage"

router = APIRouter(prefix="/api/v1/observability/export", tags=["observability-export"])
metrics_router = APIRouter(tags=["observability-export"])


@router.get("/config", response_model=ExportConfigRead)
def get_export_config(
    environment_id: uuid.UUID = Query(...),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    """The effective export config for an environment -- platform defaults
    overlaid with the environment's ``telemetry_export`` policy block. Header
    values are never returned, only their names."""
    return TelemetryExportService(db).get_config(actor, environment_id)


@router.put("/config", response_model=ExportConfigRead)
def set_export_config(
    payload: ExportConfigWrite,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
):
    """Set an environment's export target (M4-4.6-FR-002/003).

    Swapping Datadog for Grafana for Splunk is this call with a different
    ``endpoint`` -- never a code change. A malformed document is rejected with
    ``EXPORT_CONFIG_INVALID`` (422); a *runtime* export failure is never an
    error here -- it is exporter-health state.

    Idempotent on ``Idempotency-Key`` (Phase 3.1's platform contract): a
    retried write must not double-audit a single operator action."""
    service = TelemetryExportService(db)

    def _apply() -> dict:
        result = service.set_config(actor, payload.environment_id, payload.as_block())
        return {"environment_id": result["environment_id"]}

    IdempotencyService(db).execute(
        organization_id=actor.organization_id,
        operation="telemetry.export.configure",
        key=idempotency_key,
        payload=payload.model_dump(mode="json"),
        fn=_apply,
    )
    return service.get_config(actor, payload.environment_id)


@router.get("/health", response_model=ExporterHealthRead)
def get_exporter_health(
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    """Is export flowing? Last error, last success, buffer/throughput counters
    (M4-4.6-FR-022). Process-local and ephemeral -- a restart resets it, which
    is honest: the buffer it describes is also gone."""
    return TelemetryExportService(db).health()


@metrics_router.get("/metrics", response_class=PlainTextResponse)
def metrics(
    window_seconds: int = Query(default=3600, ge=60, le=86_400),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    """Prometheus text exposition for the caller's organization (AC-04, AC-11).

    Bounded-cardinality labels only -- `environment`, `status`, `provider`,
    `model_category`, `error_class`, and the two behavioral-finding enums. No
    execution id, no email, no payload can appear as a label."""
    from datetime import timedelta

    body = MetricsCollector(db).render(
        actor.organization_id, window=timedelta(seconds=window_seconds)
    )
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")
