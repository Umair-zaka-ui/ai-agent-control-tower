"""Human authentication endpoints (SRS §16).

    POST   /api/v1/auth/login       email + password  -> tokens (or MFA challenge)
    POST   /api/v1/auth/mfa/verify   challenge + code  -> tokens
    POST   /api/v1/auth/refresh      refresh token     -> rotated tokens
    POST   /api/v1/auth/logout       revoke current session
    GET    /api/v1/auth/me           current identity projection
    GET    /api/v1/auth/sessions     caller's active sessions
    DELETE /api/v1/auth/sessions/{id}  revoke one of the caller's sessions

All endpoints delegate to ``AuthenticationService`` (built in Part 4.2.1); this
module only handles HTTP concerns and never touches credentials directly.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.identity.auth.authentication_service import AuthenticationService
from app.identity.auth.context import IdentityContext
from app.identity.auth.dependency import authenticate
from app.identity.auth.enums import AuthEventType, AuthMethod, MfaMethod
from app.identity.auth.schemas import (
    LoginRequestDTO,
    LoginResponse,
    MeResponse,
    MfaVerifyRequestDTO,
    RefreshRequestDTO,
    SessionRead,
    TokenResponse,
)
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.session import UserSession
from app.models.user import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth:human"])

_TTL = settings.AUTH_ACCESS_TOKEN_TTL_SECONDS


def get_auth_service(db: Session = Depends(get_db)) -> AuthenticationService:
    return AuthenticationService(db)


def _ctx(request: Request) -> tuple[str | None, str | None, str | None]:
    ip = request.client.host if request.client else None
    return ip, request.headers.get("user-agent"), request.headers.get("x-request-id")


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequestDTO,
    request: Request,
    service: AuthenticationService = Depends(get_auth_service),
) -> LoginResponse:
    ip, ua, rid = _ctx(request)
    result = service.login(
        payload.email, payload.password, ip_address=ip, user_agent=ua, request_id=rid
    )
    if result.mfa_required:
        return LoginResponse(
            access_token="", refresh_token="", expires_in=0,
            mfa_required=True, mfa_challenge_token=result.mfa_challenge_token,
        )
    user = service.db.get(User, uuid.UUID(result.context.identity_id))
    return LoginResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=_TTL,
        user=user,
    )


@router.post("/mfa/verify", response_model=TokenResponse)
def mfa_verify(
    payload: MfaVerifyRequestDTO,
    request: Request,
    service: AuthenticationService = Depends(get_auth_service),
) -> TokenResponse:
    ip, ua, rid = _ctx(request)
    try:
        method = MfaMethod(payload.method.upper())
    except ValueError as exc:
        raise IdentityError(ErrorCode.VALIDATION_ERROR, "Unknown MFA method.") from exc
    result = service.complete_mfa(
        payload.challenge_token, method, payload.code,
        ip_address=ip, user_agent=ua, request_id=rid,
    )
    user = service.db.get(User, uuid.UUID(result.context.identity_id))
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=_TTL,
        user=user,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    payload: RefreshRequestDTO,
    request: Request,
    service: AuthenticationService = Depends(get_auth_service),
) -> TokenResponse:
    ip, ua, rid = _ctx(request)
    result = service.refresh(
        payload.refresh_token, ip_address=ip, user_agent=ua, request_id=rid
    )
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=_TTL,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def logout(
    request: Request,
    context: IdentityContext = Depends(authenticate),
    service: AuthenticationService = Depends(get_auth_service),
) -> Response:
    _, _, rid = _ctx(request)
    if context.session_id is not None:
        session = service.db.get(UserSession, uuid.UUID(context.session_id))
        if session is not None:
            service.logout(session, request_id=rid)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeResponse)
def me(
    context: IdentityContext = Depends(authenticate),
    db: Session = Depends(get_db),
) -> MeResponse:
    user = db.get(User, uuid.UUID(context.identity_id))
    if user is None:
        raise IdentityError(ErrorCode.USER_NOT_FOUND, "User does not exist.")
    return MeResponse(
        user=user,
        roles=context.roles,
        permissions=context.permissions,
        assurance_level=context.assurance_level,
        session_id=context.session_id,
    )


@router.get("/sessions", response_model=list[SessionRead])
def list_sessions(
    context: IdentityContext = Depends(authenticate),
    service: AuthenticationService = Depends(get_auth_service),
) -> list[UserSession]:
    return service.sessions.list_active(uuid.UUID(context.identity_id))


@router.delete(
    "/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def revoke_session(
    session_id: uuid.UUID,
    request: Request,
    context: IdentityContext = Depends(authenticate),
    service: AuthenticationService = Depends(get_auth_service),
) -> Response:
    session = service.db.get(UserSession, session_id)
    # Never confirm existence of another user's session.
    if session is None or str(session.user_id) != context.identity_id:
        raise IdentityError(ErrorCode.SESSION_NOT_FOUND, "Session does not exist.")
    service.sessions.revoke(session)
    service.refresh_tokens.revoke_session_family(session.id)
    service.events.record(
        AuthEventType.SESSION_REVOKED,
        auth_method=AuthMethod.JWT,
        identity_type=context.identity_type,
        identity_id=session.user_id,
        request_id=request.headers.get("x-request-id"),
        metadata={"session_id": str(session.id)},
    )
    service.db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
