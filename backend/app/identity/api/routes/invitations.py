"""Invitation endpoints (4.2.2.3.1 §15).

    POST /api/v1/identity/invitations            invitation.manage
    GET  /api/v1/identity/invitations            invitation.view
    POST /api/v1/identity/invitations/resend     invitation.manage
    POST /api/v1/identity/invitations/cancel     invitation.manage
    GET  /api/v1/identity/invitations/{token}    PUBLIC, rate limited

The last one is public by necessity: the invitee has no account yet. It is the only
unauthenticated route in this file, it is rate limited (§19), and it returns a
*preview* — organization, role, department, expiry — never internal ids.

Route order matters: ``/invitations/resend`` and ``/invitations/cancel`` are declared
before ``/invitations/{token}``, or FastAPI would match "resend" as a token.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.identity.api.deps import get_db, require_permission
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.enums import InvitationStatus
from app.identity.models.registration import Invitation
from app.identity.ratelimit import rate_limit
from app.identity.registration import InvitationService, RequestContext
from app.identity.registration.schemas import (
    InvitationActionRequest,
    InvitationCreateRequest,
    InvitationPreview,
    InvitationRead,
)
from app.identity.models.department import Department
from app.models.organization import Organization
from app.models.rbac import Role
from app.models.user import User

router = APIRouter(prefix="/invitations", tags=["identity:invitations"])


def _context(request: Request) -> RequestContext:
    return RequestContext(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=request.headers.get("x-request-id"),
        correlation_id=request.headers.get("x-correlation-id"),
    )


def _read(invitation: Invitation) -> InvitationRead:
    dto = InvitationRead.model_validate(invitation)
    dto.is_expired = InvitationStatus(invitation.status) is InvitationStatus.EXPIRED
    return dto


def _owned(db: Session, actor: User, invitation_id: uuid.UUID) -> Invitation:
    """Resolve an invitation inside the actor's organization, or 404.

    Never confirms that an invitation exists in another tenant.
    """
    invitation = db.get(Invitation, invitation_id)
    if invitation is None or invitation.organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.INVITATION_NOT_FOUND, "Invitation does not exist.")
    return invitation


class EmailDeliveryStatus(BaseModel):
    """Whether invitation emails actually leave the building (SRS §6).

    The UI needs this: with ``NOTIFICATIONS_ENABLED=false`` an invitation is created and
    its link is written to a development outbox, not emailed. Showing a plain "PENDING"
    invitation implies a message is in flight, and the invitee waits for ever.
    """

    enabled: bool
    outbox_path: str | None = None


# --------------------------------------------------------------------------- #
# Administrative
# --------------------------------------------------------------------------- #
@router.post("", response_model=InvitationRead, status_code=status.HTTP_201_CREATED)
def create_invitation(
    payload: InvitationCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("invitation.manage")),
) -> InvitationRead:
    """Invite one email address into the caller's organization.

    Re-inviting a live invitation is idempotent: it resends with a fresh token rather
    than colliding with the one-live-invitation-per-address index.
    """
    if payload.role_id is not None:
        role = db.get(Role, payload.role_id)
        if role is None or (
            role.organization_id is not None and role.organization_id != actor.organization_id
        ):
            raise IdentityError(ErrorCode.ROLE_NOT_FOUND, "Role does not exist.")
    if payload.department_id is not None:
        department = db.get(Department, payload.department_id)
        if department is None or department.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.DEPARTMENT_NOT_FOUND, "Department does not exist.")

    issued = InvitationService(db).create(
        organization_id=actor.organization_id,
        email=payload.email,
        invited_by=actor,
        role_id=payload.role_id,
        department_id=payload.department_id,
        team_id=payload.team_id,
        context=_context(request),
    )
    return _read(issued.invitation)


@router.get("", response_model=list[InvitationRead])
def list_invitations(
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("invitation.view")),
    invitation_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[InvitationRead]:
    """Invitations for the caller's organization. Expiry is materialised on read."""
    rows = InvitationService(db).list_for_organization(
        actor.organization_id, status=invitation_status, limit=limit
    )
    return [_read(r) for r in rows]


@router.post("/resend", response_model=InvitationRead)
def resend_invitation(
    payload: InvitationActionRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("invitation.manage")),
) -> InvitationRead:
    """Rotate the token and send a fresh link. The previous link stops working."""
    invitation = _owned(db, actor, payload.invitation_id)
    issued = InvitationService(db).resend(invitation, actor=actor, context=_context(request))
    return _read(issued.invitation)


@router.post("/cancel", response_model=InvitationRead)
def cancel_invitation(
    payload: InvitationActionRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("invitation.manage")),
) -> InvitationRead:
    """Revoke an invitation. The link dies immediately."""
    invitation = _owned(db, actor, payload.invitation_id)
    cancelled = InvitationService(db).cancel(invitation, actor=actor, context=_context(request))
    return _read(cancelled)


# --------------------------------------------------------------------------- #
# Public: preview an invitation (§17). Declared last so it cannot shadow the
# literal paths above.
# --------------------------------------------------------------------------- #
@router.get(
    "/{token}",
    response_model=InvitationPreview,
    dependencies=[Depends(rate_limit("invitation_preview"))],
)
def preview_invitation(token: str, db: Session = Depends(get_db)) -> InvitationPreview:
    """Show the invitee what they are accepting.

    Raises the *specific* reason a link is dead — expired, cancelled, already used —
    so the UI can offer the right next step. Possession of an unguessable token already
    proves the holder was sent it, so this reveals nothing they did not have.
    """
    invitation = InvitationService(db).validate(token)
    organization = db.get(Organization, invitation.organization_id)
    role = db.get(Role, invitation.role_id) if invitation.role_id else None
    department = db.get(Department, invitation.department_id) if invitation.department_id else None
    inviter = db.get(User, invitation.invited_by) if invitation.invited_by else None

    return InvitationPreview(
        email=invitation.email,
        organization_name=organization.name if organization else "your organization",
        role_name=role.name if role else None,
        department_name=department.name if department else None,
        invited_by_name=inviter.name if inviter else None,
        expires_at=invitation.expires_at,
    )


# --------------------------------------------------------------------------- #
# Administrator approval for self-registered accounts (§3 mode 3).
#
# Lives here rather than in users.py because it is the last step of the *onboarding*
# workflow, not a general lifecycle transition: it only ever moves an account from
# EMAIL_VERIFIED to ACTIVE, and only for the self-service mode that parked it there.
# Without it, SELF_SERVICE mode is a dead end and §3 mode 3 is unimplementable.
# --------------------------------------------------------------------------- #
approval_router = APIRouter(prefix="/users", tags=["identity:invitations"])


@approval_router.post("/{user_id}/approve", status_code=status.HTTP_200_OK)
def approve_registration(
    user_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("user.create")),
) -> dict[str, str]:
    """Approve a self-registered, email-verified account. It may then sign in."""
    from app.identity.registration import RegistrationService

    target = db.get(User, user_id)
    if target is None or target.organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.USER_NOT_FOUND, "User does not exist.")

    RegistrationService(db).approve(target, actor_id=actor.id, context=_context(request))
    return {"status": target.status, "email": target.email}


# --------------------------------------------------------------------------- #
# Is email actually being sent? (SRS §6)
#
# Its own router because the one above is prefixed `/invitations`, and this is a
# property of the deployment, not of any invitation.
# --------------------------------------------------------------------------- #
email_router = APIRouter(tags=["identity:invitations"])


@email_router.get("/email-delivery", response_model=EmailDeliveryStatus)
def email_delivery_status(
    actor: User = Depends(require_permission("invitation.view")),
) -> EmailDeliveryStatus:
    """Tell the UI whether invitation emails leave the building.

    Permission-gated because it reveals a filesystem path. With delivery disabled the
    Invitations panel must say so: a plain "PENDING" row implies a message is in flight,
    and the invitee waits for ever for mail that was written to a file.
    """
    from app.services import notification_service

    path = notification_service.outbox_path()
    return EmailDeliveryStatus(
        enabled=notification_service.delivery_enabled(),
        outbox_path=str(path) if path else None,
    )
