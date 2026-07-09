"""Human authentication + session lifecycle endpoints (SRS §16, §23).

    POST   /api/v1/auth/login                email + password  -> tokens (or MFA challenge)
    POST   /api/v1/auth/mfa/verify           challenge + code  -> tokens
    POST   /api/v1/auth/refresh              refresh token     -> rotated tokens
    POST   /api/v1/auth/logout               revoke current session (or all)
    GET    /api/v1/auth/me                   current identity projection
    GET    /api/v1/auth/sessions             caller's active sessions
    GET    /api/v1/auth/sessions/{id}        one session (forensic detail)
    POST   /api/v1/auth/sessions/{id}/revoke force-logout one session
    DELETE /api/v1/auth/sessions/{id}        alias of revoke (REST convenience)
    GET    /api/v1/auth/devices              caller's known devices
    POST   /api/v1/auth/devices/{id}/trust   mark a device trusted
    POST   /api/v1/auth/devices/{id}/block   block a device

All endpoints delegate to the services; this module only handles HTTP concerns and
never touches credentials directly.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.identity.auth.authentication_service import AuthenticationService, RequestClient
from app.identity.auth.context import IdentityContext
from app.identity.auth.dependency import authenticate
from app.identity.auth.enums import AuthEventType, AuthMethod, MfaMethod
from app.identity.protection.rate_limit import adaptive_login_rate_limit
from app.identity.auth.schemas import (
    DeviceRead,
    SecurityEventRead,
    LoginRequestDTO,
    LoginResponse,
    LogoutRequest,
    LogoutResponse,
    MeResponse,
    MfaVerifyRequestDTO,
    RefreshRequestDTO,
    RevokeSessionRequest,
    SessionDetail,
    SessionRead,
    TokenResponse,
)
from app.identity.errors import ErrorCode, IdentityError
from app.identity.repositories.security_event_repository import SecurityEventRepository
from app.identity.models.enums import (
    SessionRevocationReason,
    SessionSecurityBand,
)
from app.identity.models.security_event import SecurityEvent
from app.identity.models.session import UserSession
from app.models.user import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth:human"])

_TTL = settings.AUTH_ACCESS_TOKEN_TTL_SECONDS


def get_auth_service(db: Session = Depends(get_db)) -> AuthenticationService:
    return AuthenticationService(db)


def _client(request: Request) -> RequestClient:
    """Everything we can learn about the caller from one request.

    ``country``/``city``/``timezone`` come from edge headers a reverse proxy or CDN
    sets (Cloudflare-style). They are absent in the current deployment, so risk
    scoring degrades gracefully rather than guessing.
    """
    return RequestClient(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=request.headers.get("x-request-id"),
        device_id_header=request.headers.get("x-device-id"),
        country=request.headers.get("cf-ipcountry") or request.headers.get("x-geo-country"),
        city=request.headers.get("x-geo-city"),
        timezone_name=request.headers.get("x-geo-timezone"),
    )


def _session_read(session: UserSession, *, current_session_id: str | None) -> SessionRead:
    dto = SessionRead.model_validate(session)
    dto.is_current = current_session_id is not None and str(session.id) == current_session_id
    dto.security_band = SessionSecurityBand.for_score(session.security_score).value
    return dto


def _require_own_session(
    service: AuthenticationService, context: IdentityContext, session_id: uuid.UUID
) -> UserSession:
    """Scoped lookup. Never confirm the existence of another user's session —
    a 404 for "not yours" and "not found" must be indistinguishable."""
    session = service.sessions.get_for_user(uuid.UUID(context.identity_id), session_id)
    if session is None:
        raise IdentityError(ErrorCode.SESSION_NOT_FOUND, "Session does not exist.")
    return session


# --------------------------------------------------------------------------- #
# Login / MFA / refresh
# --------------------------------------------------------------------------- #
@router.post(
    "/login",
    response_model=LoginResponse,
    dependencies=[Depends(adaptive_login_rate_limit)],
)
def login(
    payload: LoginRequestDTO,
    request: Request,
    service: AuthenticationService = Depends(get_auth_service),
) -> LoginResponse:
    result = service.login(
        payload.email,
        payload.password,
        client=_client(request),
        remember_me=payload.remember_me,
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
        session_id=str(result.session_id),
        security_score=result.security_score,
        is_new_device=result.is_new_device,
        idle_timeout_seconds=settings.SESSION_IDLE_TIMEOUT_SECONDS,
        idle_warning_seconds=settings.SESSION_IDLE_WARNING_SECONDS,
        password_change_required=result.password_change_required,
    )


@router.post("/mfa/verify", response_model=TokenResponse)
def mfa_verify(
    payload: MfaVerifyRequestDTO,
    request: Request,
    service: AuthenticationService = Depends(get_auth_service),
) -> TokenResponse:
    client = _client(request)
    try:
        method = MfaMethod(payload.method.upper())
    except ValueError as exc:
        raise IdentityError(ErrorCode.VALIDATION_ERROR, "Unknown MFA method.") from exc
    result = service.complete_mfa(
        payload.challenge_token, method, payload.code,
        ip_address=client.ip_address, user_agent=client.user_agent, request_id=client.request_id,
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
    client = _client(request)
    result = service.refresh(
        payload.refresh_token,
        ip_address=client.ip_address,
        user_agent=client.user_agent,
        request_id=client.request_id,
    )
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=_TTL,
    )


# --------------------------------------------------------------------------- #
# Logout (SRS §16, §24)
# --------------------------------------------------------------------------- #
@router.post("/logout", response_model=LogoutResponse)
def logout(
    request: Request,
    payload: LogoutRequest | None = None,
    context: IdentityContext = Depends(authenticate),
    service: AuthenticationService = Depends(get_auth_service),
) -> LogoutResponse:
    """Revoke the current session, or every session for the caller.

    Returns 200 with the revoked ids rather than 204: "log out all devices" is a
    security action and the user is entitled to see what it did.
    """
    payload = payload or LogoutRequest()
    request_id = request.headers.get("x-request-id")
    user_id = uuid.UUID(context.identity_id)

    if payload.all_devices:
        revoked = service.logout_all(user_id, request_id=request_id)
        return LogoutResponse(revoked_session_ids=revoked)

    if context.session_id is None:
        # Legacy token: nothing to revoke server-side.
        return LogoutResponse(revoked_session_ids=[])

    session = service.db.get(UserSession, uuid.UUID(context.session_id))
    if session is None:
        return LogoutResponse(revoked_session_ids=[])
    service.logout(session, request_id=request_id)
    return LogoutResponse(revoked_session_ids=[session.id])


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


# --------------------------------------------------------------------------- #
# Session listing / revocation (SRS §17, §18, §19, §23)
# --------------------------------------------------------------------------- #
@router.get("/sessions", response_model=list[SessionRead])
def list_sessions(
    context: IdentityContext = Depends(authenticate),
    service: AuthenticationService = Depends(get_auth_service),
) -> list[SessionRead]:
    sessions = service.sessions.list_active(uuid.UUID(context.identity_id))
    service.db.commit()  # ``list_active`` may have materialised timed-out sessions
    return [_session_read(s, current_session_id=context.session_id) for s in sessions]


@router.get("/sessions/{session_id}", response_model=SessionDetail)
def get_session(
    session_id: uuid.UUID,
    context: IdentityContext = Depends(authenticate),
    service: AuthenticationService = Depends(get_auth_service),
) -> SessionDetail:
    session = _require_own_session(service, context, session_id)
    dto = SessionDetail.model_validate(session)
    dto.is_current = str(session.id) == (context.session_id or "")
    dto.security_band = SessionSecurityBand.for_score(session.security_score).value
    return dto


@router.post("/sessions/{session_id}/revoke", response_model=SessionRead)
def revoke_session(
    session_id: uuid.UUID,
    request: Request,
    payload: RevokeSessionRequest | None = None,
    context: IdentityContext = Depends(authenticate),
    service: AuthenticationService = Depends(get_auth_service),
) -> SessionRead:
    """Force-logout one session (SRS §17).

    Revoking your *own current* session is allowed — it is simply a logout — but
    the UI must confirm first (SRS §19); the API does not second-guess an explicit
    request.
    """
    session = _require_own_session(service, context, session_id)
    reason = SessionRevocationReason.USER_LOGOUT
    if payload and payload.reason:
        try:
            reason = SessionRevocationReason(payload.reason.upper())
        except ValueError as exc:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "Unknown revocation reason.") from exc
    service.revoke_session(
        session,
        reason,
        actor_id=uuid.UUID(context.identity_id),
        request_id=request.headers.get("x-request-id"),
    )
    return _session_read(session, current_session_id=context.session_id)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT,
               response_class=Response)
def delete_session(
    session_id: uuid.UUID,
    request: Request,
    context: IdentityContext = Depends(authenticate),
    service: AuthenticationService = Depends(get_auth_service),
) -> Response:
    """RESTful alias of ``/revoke``. Sessions are never hard-deleted — the row is
    the audit record — so this revokes."""
    session = _require_own_session(service, context, session_id)
    service.revoke_session(
        session,
        SessionRevocationReason.USER_LOGOUT,
        actor_id=uuid.UUID(context.identity_id),
        request_id=request.headers.get("x-request-id"),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Devices (SRS §13, §14, §23)
# --------------------------------------------------------------------------- #
def _current_device_id(service: AuthenticationService, context: IdentityContext) -> uuid.UUID | None:
    if context.session_id is None:
        return None
    session = service.db.get(UserSession, uuid.UUID(context.session_id))
    return session.device_id if session else None


@router.get("/devices", response_model=list[DeviceRead])
def list_devices(
    context: IdentityContext = Depends(authenticate),
    service: AuthenticationService = Depends(get_auth_service),
) -> list[DeviceRead]:
    current = _current_device_id(service, context)
    devices = service.devices.list_for_user(uuid.UUID(context.identity_id))
    out: list[DeviceRead] = []
    for device in devices:
        dto = DeviceRead.model_validate(device)
        dto.is_current = current is not None and device.id == current
        out.append(dto)
    return out


@router.post("/devices/{device_id}/trust", response_model=DeviceRead)
def trust_device(
    device_id: uuid.UUID,
    request: Request,
    context: IdentityContext = Depends(authenticate),
    service: AuthenticationService = Depends(get_auth_service),
) -> DeviceRead:
    device = service.devices.get_for_user(uuid.UUID(context.identity_id), device_id)
    if device is None:
        raise IdentityError(ErrorCode.DEVICE_NOT_FOUND, "Device does not exist.")
    service.devices.trust(device)
    service.events.record(
        AuthEventType.DEVICE_TRUSTED,
        auth_method=AuthMethod.JWT,
        identity_type=context.identity_type,
        organization_id=uuid.UUID(context.organization_id) if context.organization_id else None,
        identity_id=uuid.UUID(context.identity_id),
        request_id=request.headers.get("x-request-id"),
        metadata={"device_id": str(device.id)},
    )
    service.db.commit()
    return DeviceRead.model_validate(device)


@router.get("/security-events", response_model=list[SecurityEventRead])
def my_security_events(
    context: IdentityContext = Depends(authenticate),
    db: Session = Depends(get_db),
    limit: int = 50,
) -> list[SecurityEvent]:
    """The caller's own recent security activity (SRS §25, §26).

    Scoped to `actor_id = me`. A user is entitled to see the logins, device
    registrations, token rotations and revocations recorded against their own
    identity — that is how they notice an intrusion. They are entitled to see
    nobody else's, so this never accepts an `actor_id` parameter.
    """
    if context.organization_id is None:
        return []
    return SecurityEventRepository(db).list_for_actor(
        uuid.UUID(context.organization_id),
        uuid.UUID(context.identity_id),
        limit=min(max(limit, 1), 200),
    )


@router.post("/devices/{device_id}/block", response_model=DeviceRead)
def block_device(
    device_id: uuid.UUID,
    request: Request,
    context: IdentityContext = Depends(authenticate),
    service: AuthenticationService = Depends(get_auth_service),
) -> DeviceRead:
    """Block a device and kill everything it is currently running.

    Blocking without revoking the device's live sessions would be theatre: the
    attacker keeps their session and merely cannot start a new one.
    """
    user_id = uuid.UUID(context.identity_id)
    device = service.devices.get_for_user(user_id, device_id)
    if device is None:
        raise IdentityError(ErrorCode.DEVICE_NOT_FOUND, "Device does not exist.")
    service.devices.block(device)
    for session in service.sessions.list_active(user_id):
        if session.device_id == device.id:
            service.sessions.revoke(session, SessionRevocationReason.SECURITY_EVENT)
            service.refresh_tokens.revoke_family(session.refresh_token_family_id)
    service.events.record(
        AuthEventType.DEVICE_BLOCKED,
        auth_method=AuthMethod.JWT,
        identity_type=context.identity_type,
        organization_id=uuid.UUID(context.organization_id) if context.organization_id else None,
        identity_id=user_id,
        request_id=request.headers.get("x-request-id"),
        metadata={"device_id": str(device.id)},
    )
    service.db.commit()
    return DeviceRead.model_validate(device)
