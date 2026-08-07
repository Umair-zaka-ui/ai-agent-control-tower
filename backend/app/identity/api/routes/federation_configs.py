"""Identity federation configuration admin endpoints (Phase 2.3.1,
``ACT-INT-FR-185``).

Every route is scoped to the caller's own organization implicitly (from
``current_user.organization_id``) — there is no cross-org path parameter
to guard, mirroring ``organizations.py``'s own "the caller's own
organization" pattern. Gated by the new ``identity.federation.view``/
``identity.federation.manage`` permissions (``ACT-PLT-NFR-001`` — a
config belonging to a different organization is a plain 404, indistin­
guishable from one that does not exist)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status

from app.identity.api.deps import get_db, require_permission
from app.identity.federation.schemas import (
    FederationConfigCreate,
    FederationConfigRead,
    FederationConfigTestResult,
    FederationConfigUpdate,
)
from app.identity.federation.service import FederationService
from app.identity.models.federation import FederationConfig
from app.models.user import User
from sqlalchemy.orm import Session

router = APIRouter(prefix="/federation/configs", tags=["identity:federation"])


def _read(config: FederationConfig) -> FederationConfigRead:
    return FederationConfigRead(
        id=config.id, organization_id=config.organization_id, protocol=config.protocol,
        provider_type=config.provider_type, display_name=config.display_name,
        configuration=config.configuration, jit_provisioning_enabled=config.jit_provisioning_enabled,
        claim_mappings=config.claim_mappings, default_role_id=config.default_role_id, status=config.status,
        created_at=config.created_at, updated_at=config.updated_at,
        has_client_secret=config.encrypted_client_secret is not None,
    )


@router.get("", response_model=list[FederationConfigRead])
def list_configs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("identity.federation.view")),
) -> list[FederationConfigRead]:
    configs = FederationService(db).list_configs(current_user.organization_id)
    return [_read(c) for c in configs]


@router.post("", response_model=FederationConfigRead, status_code=201)
def create_config(
    payload: FederationConfigCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("identity.federation.manage")),
) -> FederationConfigRead:
    config = FederationService(db).create_config(
        current_user, current_user.organization_id, protocol=payload.protocol,
        provider_type=payload.provider_type, display_name=payload.display_name,
        configuration=payload.configuration, client_secret=payload.client_secret,
        jit_provisioning_enabled=payload.jit_provisioning_enabled,
        claim_mappings=payload.claim_mappings, default_role_id=payload.default_role_id,
    )
    return _read(config)


@router.get("/{config_id}", response_model=FederationConfigRead)
def get_config(
    config_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("identity.federation.view")),
) -> FederationConfigRead:
    config = FederationService(db).get_config(current_user.organization_id, config_id)
    return _read(config)


@router.put("/{config_id}", response_model=FederationConfigRead)
def update_config(
    config_id: uuid.UUID,
    payload: FederationConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("identity.federation.manage")),
) -> FederationConfigRead:
    config = FederationService(db).update_config(
        current_user.organization_id, config_id, **payload.model_dump(exclude_unset=True),
    )
    return _read(config)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_config(
    config_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("identity.federation.manage")),
) -> Response:
    FederationService(db).delete_config(current_user.organization_id, config_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{config_id}/test", response_model=FederationConfigTestResult)
def test_config(
    config_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("identity.federation.manage")),
) -> FederationConfigTestResult:
    result = FederationService(db).test_config(current_user.organization_id, config_id)
    return FederationConfigTestResult(**result)
