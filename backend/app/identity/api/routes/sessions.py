"""Administrative session & device management (SRS 4.2.2.2 §17, §18, §32).

The self-service surface lives at ``/api/v1/auth/*`` and is scoped to the caller.
These endpoints are the **administrator's** view: they address *other* users'
sessions, so they are permission-gated and scoped to the caller's organization.

    GET  /api/v1/identity/sessions?user_id=                      session.view
    GET  /api/v1/identity/sessions/{id}                          session.view
    POST /api/v1/identity/sessions/{id}/revoke                   session.revoke
    POST /api/v1/identity/users/{user_id}/sessions/revoke-all    session.revoke
    GET  /api/v1/identity/users/{user_id}/devices                session.view
    GET  /api/v1/identity/security-events                        session.view
    GET  /api/v1/identity/security-events/types                  session.view
    GET  /api/v1/identity/sessions/{id}/events                   session.view

Cross-organization access is impossible: every target is resolved through the
caller's ``organization_id``, and a target outside it reports ``USER_NOT_FOUND`` —
never "exists, but not yours".
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.identity.api.deps import get_db, get_request_id, require_permission
from app.identity.auth.device_service import DeviceService
from app.identity.auth.enums import AuthEventType, AuthMethod
from app.identity.auth.refresh_rotation_service import RefreshRotationService
from app.identity.auth.schemas import (
    DeviceRead,
    SecurityEventPage,
    SecurityEventRead,
    SessionDetail,
)
from app.identity.auth.security_event_service import SecurityEventService
from app.identity.auth.session_lifecycle_service import SessionLifecycleService
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.enums import SessionRevocationReason, SessionSecurityBand
from app.identity.models.security_event import SecurityEvent
from app.identity.models.session import UserSession
from app.identity.repositories.security_event_repository import SecurityEventRepository
from app.identity.repositories.user_repository import UserRepository
from app.identity.schemas.identity import SessionRead
from app.models.user import User

router = APIRouter(tags=["identity:sessions"])


class AdminRevokeRequest(BaseModel):
    """Why the administrator is ending this session. Defaults to ADMIN_REVOKED."""

    reason: str | None = None


class AdminRevokeResponse(BaseModel):
    revoked_session_ids: list[uuid.UUID] = Field(default_factory=list)


def _target_user(db: Session, actor: User, user_id: uuid.UUID) -> User:
    """Resolve a target user inside the actor's organization, or 404."""
    target = UserRepository(db).get(user_id)
    if target is None or target.organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.USER_NOT_FOUND, "User does not exist.")
    return target


def _target_session(db: Session, actor: User, session_id: uuid.UUID) -> UserSession:
    session = db.get(UserSession, session_id)
    if session is None:
        raise IdentityError(ErrorCode.SESSION_NOT_FOUND, "Session does not exist.")
    # Scope through the session's *owner*, not the session's denormalised
    # organization_id, so a stale column can never widen access.
    _target_user(db, actor, session.user_id)
    return session


def _revoke(
    db: Session,
    session: UserSession,
    reason: SessionRevocationReason,
    *,
    actor: User,
    request_id: str | None,
) -> None:
    """Revoke one session + its refresh-token family, and record who did it."""
    SessionLifecycleService(db).revoke(session, reason)
    RefreshRotationService(db).revoke_family(session.refresh_token_family_id)
    SecurityEventService(db).record(
        AuthEventType.SESSION_REVOKED,
        auth_method=AuthMethod.JWT,
        identity_type="HUMAN_USER",
        organization_id=session.organization_id,
        identity_id=session.user_id,
        request_id=request_id,
        metadata={
            "session_id": str(session.id),
            "reason": reason.value,
            # Subject is the user; actor is the administrator. An audit record of a
            # force-logout that omits who pulled the trigger is not an audit record.
            "actor_id": str(actor.id),
            "actor_email": actor.email,
        },
    )


# --------------------------------------------------------------------------- #
# Read (SRS §18)
# --------------------------------------------------------------------------- #
@router.get("/sessions", response_model=list[SessionRead])
def list_sessions(
    user_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("session.view")),
):
    """Active sessions for a user in the caller's organization."""
    _target_user(db, actor, user_id)
    sessions = SessionLifecycleService(db).list_active(user_id)
    db.commit()  # list_active materialises timed-out / idle sessions
    return sessions


@router.get("/sessions/{session_id}", response_model=SessionDetail)
def get_session(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("session.view")),
) -> SessionDetail:
    session = _target_session(db, actor, session_id)
    dto = SessionDetail.model_validate(session)
    dto.security_band = SessionSecurityBand.for_score(session.security_score).value
    return dto


@router.get("/users/{user_id}/devices", response_model=list[DeviceRead])
def list_user_devices(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("session.view")),
) -> list[DeviceRead]:
    _target_user(db, actor, user_id)
    return [DeviceRead.model_validate(d) for d in DeviceService(db).list_for_user(user_id)]


# --------------------------------------------------------------------------- #
# Force-logout (SRS §17)
# --------------------------------------------------------------------------- #
def _reason_from(payload: AdminRevokeRequest | None) -> SessionRevocationReason:
    if payload is None or not payload.reason:
        return SessionRevocationReason.ADMIN_REVOKED
    try:
        return SessionRevocationReason(payload.reason.upper())
    except ValueError as exc:
        raise IdentityError(ErrorCode.VALIDATION_ERROR, "Unknown revocation reason.") from exc


@router.post("/sessions/{session_id}/revoke", response_model=SessionRead)
def admin_revoke_session(
    session_id: uuid.UUID,
    payload: AdminRevokeRequest | None = None,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("session.revoke")),
    request_id: str | None = Depends(get_request_id),
):
    """Force-logout a single session. Takes effect on that device's next request."""
    session = _target_session(db, actor, session_id)
    _revoke(db, session, _reason_from(payload), actor=actor, request_id=request_id)
    db.commit()
    return session


@router.post("/users/{user_id}/sessions/revoke-all", response_model=AdminRevokeResponse)
def admin_revoke_all_sessions(
    user_id: uuid.UUID,
    payload: AdminRevokeRequest | None = None,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("session.revoke")),
    request_id: str | None = Depends(get_request_id),
) -> AdminRevokeResponse:
    """Sign a user out of every device — the "compromised account" response.

    Distinct from disabling the account (which also revokes sessions): this ends
    the sessions while leaving the identity able to sign back in, e.g. after a
    forced password reset.
    """
    _target_user(db, actor, user_id)
    reason = _reason_from(payload)
    lifecycle = SessionLifecycleService(db)
    revoked: list[uuid.UUID] = []
    for session in lifecycle.list_active(user_id):
        _revoke(db, session, reason, actor=actor, request_id=request_id)
        revoked.append(session.id)
    db.commit()
    return AdminRevokeResponse(revoked_session_ids=revoked)


# --------------------------------------------------------------------------- #
# Audit the security-event stream (SRS §26; DoD §32 "…and audit user sessions")
# --------------------------------------------------------------------------- #
@router.get("/security-events", response_model=SecurityEventPage)
def list_security_events(
    db: Session = Depends(get_db),
    # `session.view`, not `audit.view`: every built-in role — including VIEWER —
    # holds `audit.view`, and this stream carries other people's IP addresses,
    # devices and login history. If you may see whose sessions exist, you may see
    # their events; otherwise you may not.
    actor: User = Depends(require_permission("session.view")),
    event_type: str | None = Query(default=None, description="Exact event type, e.g. SESSION_REVOKED"),
    actor_id: uuid.UUID | None = Query(default=None, description="Filter to one identity's actions"),
    session_id: uuid.UUID | None = Query(default=None, description="Filter to one session"),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> SecurityEventPage:
    """The organization's security-event stream, newest first.

    Scoped to the caller's organization by the repository — there is no code path
    here that can query another tenant's events.
    """
    repo = SecurityEventRepository(db)
    filters = dict(
        event_type=event_type, actor_id=actor_id, session_id=session_id, since=since, until=until
    )
    items = repo.list_for_organization(
        actor.organization_id, limit=limit, offset=offset, **filters
    )
    total = repo.count_for_organization(actor.organization_id, **filters)
    return SecurityEventPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/security-events/types", response_model=list[str])
def list_security_event_types(
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("session.view")),
) -> list[str]:
    """Event types this organization has actually produced — powers the filter."""
    return SecurityEventRepository(db).distinct_event_types(actor.organization_id)


@router.get("/sessions/{session_id}/events", response_model=list[SecurityEventRead])
def list_session_events(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("session.view")),
) -> list[SecurityEvent]:
    """One session's full history, oldest first — a timeline is read forwards.

    This is the "who revoked this session, when, and why?" query. It resolves the
    session through its owner first, so a session in another organization is a 404
    rather than an empty list (which would confirm the id exists).
    """
    _target_session(db, actor, session_id)
    return SecurityEventRepository(db).list_for_session(actor.organization_id, session_id)
