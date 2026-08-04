"""Enterprise Integration Framework API (Phase 2.1.1 SRS §7, Phase 2.1.2
SRS §7) — /api/v1/integration."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.database import get_db
from app.integration.auth import registry as auth_registry
from app.integration.auth.service import ConnectorCredentialService
from app.integration.errors import ConnectorHealthCheckFailedError
from app.integration.health import ConnectorHealthService
from app.integration.schemas import (
    AuthSchemeRead,
    ConnectorCredentialRead,
    ConnectorCredentialUpsert,
    ConnectorCredentialValidationResult,
    ConnectorDisableRequest,
    ConnectorHealthCheckRead,
    ConnectorHealthRead,
    ConnectorInstanceConfigure,
    ConnectorInstanceCreate,
    ConnectorInstanceRead,
    ConnectorLifecycleEventRead,
    ConnectorTypeRead,
    OAuthCallbackRequest,
    OAuthCallbackResult,
)
from app.integration.service import ConnectorService
from app.models.user import User

router = APIRouter(prefix="/api/v1/integration", tags=["integration"])

_VIEW = "integration.connector.view"
_MANAGE = "integration.connector.manage"
# Phase 2.1.2 reuses the 2.1.1 connector permissions rather than adding a
# finer `integration.credential.manage` -- a credential is a property of
# a connector instance, not a separate resource with its own access
# policy, and no requirement in the SRS asked for a finer split (unlike,
# e.g., `runtime.provider.view` vs `.manage`, which predates this and
# was itself Milestone 1's own call). Stated per the build prompt's own
# "add one only if genuinely warranted" instruction.


@router.get("/connector-types", response_model=list[ConnectorTypeRead])
def list_connector_types(actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    return ConnectorService(db).types.list_types()


@router.get("/connectors", response_model=list[ConnectorInstanceRead])
def list_connectors(actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    return ConnectorService(db).list_for_org(actor.organization_id)


@router.post("/connectors", response_model=ConnectorInstanceRead, status_code=201)
def create_connector(payload: ConnectorInstanceCreate, actor: User = Depends(require_permission(_MANAGE)),
                     db: Session = Depends(get_db)):
    return ConnectorService(db).create_instance(
        actor, actor.organization_id, connector_type=payload.connector_type, version=payload.version,
        name=payload.name, configuration=payload.configuration,
    )


@router.get("/connectors/{instance_id}", response_model=ConnectorInstanceRead)
def get_connector(instance_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)),
                  db: Session = Depends(get_db)):
    return ConnectorService(db).get_or_404(actor.organization_id, instance_id)


@router.patch("/connectors/{instance_id}", response_model=ConnectorInstanceRead)
def configure_connector(instance_id: uuid.UUID, payload: ConnectorInstanceConfigure,
                        actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db)):
    return ConnectorService(db).update_configuration(
        actor, actor.organization_id, instance_id, payload.configuration,
    )


@router.post("/connectors/{instance_id}/activate", response_model=ConnectorInstanceRead)
def activate_connector(instance_id: uuid.UUID, actor: User = Depends(require_permission(_MANAGE)),
                       db: Session = Depends(get_db)):
    return ConnectorService(db).activate(actor, actor.organization_id, instance_id)


@router.post("/connectors/{instance_id}/disable", response_model=ConnectorInstanceRead)
def disable_connector(instance_id: uuid.UUID, payload: ConnectorDisableRequest = ConnectorDisableRequest(),
                      actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db)):
    return ConnectorService(db).disable(actor, actor.organization_id, instance_id, reason=payload.reason)


@router.get("/connectors/{instance_id}/events", response_model=list[ConnectorLifecycleEventRead])
def list_connector_events(instance_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)),
                          db: Session = Depends(get_db)):
    return ConnectorService(db).list_events(actor.organization_id, instance_id)


# --------------------------------------------------------------------------- #
# Phase 2.1.2 — Connector Authentication Framework
# --------------------------------------------------------------------------- #
@router.get("/auth-schemes", response_model=list[AuthSchemeRead])
def list_auth_schemes(actor: User = Depends(require_permission(_VIEW))):
    return [
        AuthSchemeRead(identifier=identifier, required_fields=list(auth_registry.resolve(identifier).required_fields()))
        for identifier in auth_registry.registered_identifiers()
    ]


@router.get("/connectors/{instance_id}/credentials", response_model=list[ConnectorCredentialRead])
def list_connector_credentials(instance_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)),
                               db: Session = Depends(get_db)):
    ConnectorService(db).get_or_404(actor.organization_id, instance_id)  # tenant-scope check (AC-08 precedent)
    return ConnectorCredentialService(db).list_for_instance(actor.organization_id, instance_id)


@router.put("/connectors/{instance_id}/credentials", response_model=ConnectorCredentialRead)
def upsert_connector_credential(instance_id: uuid.UUID, payload: ConnectorCredentialUpsert,
                                actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db)):
    ConnectorService(db).get_or_404(actor.organization_id, instance_id)
    return ConnectorCredentialService(db).store(
        actor, actor.organization_id, instance_id, payload.auth_scheme, payload.credential,
    )


@router.delete("/connectors/{instance_id}/credentials", status_code=status.HTTP_204_NO_CONTENT)
def delete_connector_credential(instance_id: uuid.UUID, auth_scheme: str = Query(...),
                                actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db)):
    ConnectorService(db).get_or_404(actor.organization_id, instance_id)
    ConnectorCredentialService(db).delete(actor, actor.organization_id, instance_id, auth_scheme)


@router.post("/connectors/{instance_id}/credentials/validate", response_model=ConnectorCredentialValidationResult)
def validate_connector_credential(instance_id: uuid.UUID, auth_scheme: str = Query(...),
                                  actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db)):
    ConnectorService(db).get_or_404(actor.organization_id, instance_id)
    return ConnectorCredentialService(db).validate(actor, actor.organization_id, instance_id, auth_scheme)


@router.get("/connectors/{instance_id}/oauth/callback", response_model=OAuthCallbackResult)
def oauth_callback_get(instance_id: uuid.UUID, code: str = Query(...), state: str | None = Query(default=None),
                       actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db)):
    """The redirect-style entry point a real OAuth2 provider would send
    the user's browser back to (``?code=...&state=...``). Requires
    authentication like every other route here — a real deployment's
    frontend proxies this through an authenticated session; unauthenticated
    public callback handling is out of scope for this backend-only
    sub-phase (see ``docs/integration/connectors.md``)."""
    instance = ConnectorService(db).get_or_404(actor.organization_id, instance_id)
    ConnectorCredentialService(db).complete_authorization_code_exchange(instance, code=code)
    return OAuthCallbackResult(status="connected", connector_instance_id=instance_id,
                               auth_scheme="OAUTH2_AUTHORIZATION_CODE")


@router.post("/connectors/{instance_id}/oauth/callback", response_model=OAuthCallbackResult)
def oauth_callback_post(instance_id: uuid.UUID, payload: OAuthCallbackRequest,
                        actor: User = Depends(require_permission(_MANAGE)), db: Session = Depends(get_db)):
    """Manual/API-driven equivalent of the ``GET`` redirect entry point —
    same underlying exchange, useful for a caller that already has the
    code (e.g. a CLI, or a test) without simulating a browser redirect."""
    instance = ConnectorService(db).get_or_404(actor.organization_id, instance_id)
    ConnectorCredentialService(db).complete_authorization_code_exchange(instance, code=payload.code)
    return OAuthCallbackResult(status="connected", connector_instance_id=instance_id,
                               auth_scheme="OAUTH2_AUTHORIZATION_CODE")


# --------------------------------------------------------------------------- #
# Phase 2.1.3 — Connector Registry & Health
# --------------------------------------------------------------------------- #
@router.get("/connectors/{instance_id}/health", response_model=ConnectorHealthRead)
def get_connector_health(instance_id: uuid.UUID, actor: User = Depends(require_permission(_VIEW)),
                         db: Session = Depends(get_db)):
    """The cached current status — no check is run here, only read."""
    instance = ConnectorService(db).get_or_404(actor.organization_id, instance_id)
    return ConnectorHealthRead(
        connector_instance_id=instance.id, lifecycle_state=instance.lifecycle_state,
        current_health=instance.current_health, last_health_check_at=instance.last_health_check_at,
    )


@router.post("/connectors/{instance_id}/health/check", response_model=ConnectorHealthCheckRead)
def run_connector_health_check(instance_id: uuid.UUID, actor: User = Depends(require_permission(_MANAGE)),
                               db: Session = Depends(get_db)):
    """Runs an on-demand check, records it, and drives any lifecycle
    transition. A completed check — healthy or not — returns 200 with
    the result; a check that could not complete at all raises
    ``CONNECTOR_HEALTH_CHECK_FAILED`` (502), distinct from a completed
    ``UNHEALTHY`` result (``ACT-INT-FR-042``, AC-09)."""
    row = ConnectorHealthService(db).check(actor, actor.organization_id, instance_id, check_type="ON_DEMAND")
    if row.result == "ERROR":
        raise ConnectorHealthCheckFailedError(row.reason or "unknown error")
    return row


@router.get("/connectors/{instance_id}/health/history", response_model=list[ConnectorHealthCheckRead])
def list_connector_health_history(instance_id: uuid.UUID, limit: int = Query(default=50, ge=1, le=200),
                                  offset: int = Query(default=0, ge=0),
                                  actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db)):
    return ConnectorHealthService(db).history(actor.organization_id, instance_id, limit=limit, offset=offset)
