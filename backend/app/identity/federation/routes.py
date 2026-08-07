"""Federated login endpoints (Phase 2.3.1, ACT-INT-FR-180).

    GET      /api/v1/auth/federation/{org}/{config}/login     redirect to the IdP
    GET      /api/v1/auth/federation/{org}/callback           OIDC callback (code exchange)
    POST     /api/v1/auth/federation/{org}/saml/acs            SAML assertion consumer service
    GET      /api/v1/auth/federation/{org}/{config}/metadata   SP metadata (SAML)

These four are unauthenticated by nature — they *establish* authentication,
the same way ``/api/v1/auth/login`` is. The CSRF/replay protections live one
layer down, inside ``FederationService`` (the signed state/RelayState
token) — this module only handles HTTP concerns, exactly as
``auth/routes.py``'s own module docstring states for local login."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.identity.auth.schemas import TokenResponse
from app.identity.federation.schemas import OidcCallbackRequest
from app.identity.federation.service import FederatedLoginResult, FederationService
from app.models.user import User

router = APIRouter(prefix="/api/v1/auth/federation", tags=["auth:federation"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _result_to_response(db: Session, result: FederatedLoginResult) -> TokenResponse:
    from app.core.config import settings

    user = db.get(User, uuid.UUID(result.context.identity_id))
    return TokenResponse(
        access_token=result.access_token, refresh_token=result.refresh_token,
        expires_in=settings.AUTH_ACCESS_TOKEN_TTL_SECONDS, user=user,
    )


@router.get("/{organization_id}/{config_id}/login")
def start_login(
    organization_id: uuid.UUID, config_id: uuid.UUID, request: Request, db: Session = Depends(get_db),
) -> Response:
    service = FederationService(db)
    config = service.get_config(organization_id, config_id)
    if config.protocol == "OIDC":
        redirect_uri = str(request.url_for("oidc_callback", organization_id=organization_id))
        url = service.start_oidc_login(organization_id, config_id, redirect_uri=redirect_uri)
    else:
        url = service.start_saml_login(organization_id, config_id)
    return Response(status_code=302, headers={"Location": url})


@router.get("/{organization_id}/callback", name="oidc_callback")
def oidc_callback(
    organization_id: uuid.UUID, request: Request, code: str, state: str, db: Session = Depends(get_db),
) -> TokenResponse:
    service = FederationService(db)
    redirect_uri = str(request.url_for("oidc_callback", organization_id=organization_id))
    # ``config_id`` is not part of this URL -- it is recovered from the
    # verified state token itself (see FederationService.handle_oidc_callback
    # / service.py's own module docstring on stateless CSRF/replay defense).
    result = service.handle_oidc_callback_by_state(
        organization_id, code=code, state=state, redirect_uri=redirect_uri,
        ip_address=_client_ip(request), user_agent=request.headers.get("user-agent"),
        request_id=request.headers.get("x-request-id"),
    )
    return _result_to_response(db, result)


@router.post("/{organization_id}/saml/acs")
async def saml_acs(organization_id: uuid.UUID, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    form = await request.form()
    saml_response = form.get("SAMLResponse")
    relay_state = form.get("RelayState")
    service = FederationService(db)
    result = service.handle_saml_acs_by_relay_state(
        organization_id, saml_response=saml_response, relay_state=relay_state, request=request,
        ip_address=_client_ip(request), user_agent=request.headers.get("user-agent"),
        request_id=request.headers.get("x-request-id"),
    )
    return _result_to_response(db, result)


@router.get("/{organization_id}/{config_id}/metadata")
def sp_metadata(organization_id: uuid.UUID, config_id: uuid.UUID, db: Session = Depends(get_db)) -> Response:
    service = FederationService(db)
    xml = service.sp_metadata(organization_id, config_id)
    return Response(content=xml, media_type="application/xml")
