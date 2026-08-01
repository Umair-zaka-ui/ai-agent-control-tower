"""Enterprise Integration Framework API (Phase 2.1.1 SRS §7) — /api/v1/integration."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.database import get_db
from app.integration.schemas import (
    ConnectorDisableRequest,
    ConnectorInstanceConfigure,
    ConnectorInstanceCreate,
    ConnectorInstanceRead,
    ConnectorLifecycleEventRead,
    ConnectorTypeRead,
)
from app.integration.service import ConnectorService
from app.models.user import User

router = APIRouter(prefix="/api/v1/integration", tags=["integration"])

_VIEW = "integration.connector.view"
_MANAGE = "integration.connector.manage"


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
