"""InvitationService — create, validate, resend, revoke (4.2.2.3.1 §7, §8).

Mirrors the session-lifecycle discipline of Part 4.2.2.2:

- ``EXPIRED`` is a *derived* fact the clock decides; ``ACCEPTED``/``CANCELLED`` are
  *recorded* facts someone caused. Recorded facts win, and the derived one is
  **materialised** on read so a listing endpoint and the accept path never disagree
  about whether an invitation is alive.
- The token is single-use, hashed at rest, and never compared in Python.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.identity.auth.enums import AuthEventType
from app.identity.email import EmailService
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.enums import InvitationStatus, RegistrationMode
from app.identity.models.registration import Invitation
from app.identity.registration.audit import RegistrationAuditService, RequestContext
from app.identity.registration.tokens import generate_invitation_token
from app.identity.repositories.registration_repositories import InvitationRepository
from app.models.organization import Organization
from app.models.rbac import Role
from app.models.user import User


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass
class IssuedInvitation:
    invitation: Invitation
    token: str  # plaintext, emailed once
    email_sent: bool


class InvitationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = InvitationRepository(db)
        self.emails = EmailService()
        self.audit = RegistrationAuditService(db)
        self.ttl = timedelta(seconds=settings.INVITATION_TTL_SECONDS)

    # ------------------------------------------------------------------ #
    # Create (§8)
    # ------------------------------------------------------------------ #
    def create(
        self,
        *,
        organization_id: uuid.UUID,
        email: str,
        invited_by: User,
        role_id: uuid.UUID | None = None,
        department_id: uuid.UUID | None = None,
        team_id: uuid.UUID | None = None,
        context: RequestContext | None = None,
    ) -> IssuedInvitation:
        email = email.strip().lower()

        # §3 mode 2: in ADMIN_ONLY the administrator creates accounts directly, so
        # inviting is not merely unnecessary -- it is the wrong door, and allowing it
        # would make the organization's stated policy a lie.
        organization = self.db.get(Organization, organization_id)
        if organization is not None:
            mode = RegistrationMode(organization.registration_mode)
            if mode is RegistrationMode.ADMIN_ONLY:
                self.audit.record(
                    AuthEventType.REGISTRATION_BLOCKED,
                    organization_id=organization_id,
                    target_email=email,
                    actor_id=invited_by.id,
                    context=context,
                    metadata={"registration_mode": mode.value, "reason": "invitations_disabled"},
                )
                self.db.commit()
                raise IdentityError(
                    ErrorCode.REGISTRATION_DISABLED,
                    "This organization provisions accounts directly; invitations are disabled.",
                )

        # An existing member does not need an invitation. This is an *authenticated*
        # admin endpoint, so telling the admin "they're already here" leaks nothing —
        # the enumeration rule in §14 governs the public endpoints.
        existing_user = self.db.query(User).filter(User.email == email).first()
        if existing_user is not None:
            raise IdentityError(
                ErrorCode.USER_ALREADY_EXISTS, "That email already belongs to a user."
            )

        # Re-inviting is idempotent from the admin's point of view: supersede the live
        # invitation rather than colliding with the partial unique index.
        live = self.repo.get_pending_for_email(organization_id, email)
        if live is not None:
            if self._is_expired(live):
                self._materialise_expired(live)
            else:
                return self.resend(live, actor=invited_by, context=context)

        plaintext, hashed = generate_invitation_token()
        now = _now()
        invitation = Invitation(
            organization_id=organization_id,
            email=email,
            role_id=role_id,
            department_id=department_id,
            team_id=team_id,
            invited_by=invited_by.id,
            token_hash=hashed,
            status=InvitationStatus.PENDING.value,
            expires_at=now + self.ttl,
            created_at=now,
            last_sent_at=now,
        )
        self.repo.add(invitation)

        self.audit.record(
            AuthEventType.INVITATION_CREATED,
            organization_id=organization_id,
            target_email=email,
            actor_id=invited_by.id,
            context=context,
            metadata={
                "invitation_id": str(invitation.id),
                "role_id": str(role_id) if role_id else None,
                "expires_at": invitation.expires_at.isoformat(),
            },
        )

        sent = self._send(invitation, plaintext)
        self.audit.record(
            AuthEventType.INVITATION_SENT,
            organization_id=organization_id,
            target_email=email,
            actor_id=invited_by.id,
            context=context,
            metadata={"invitation_id": str(invitation.id), "delivered": sent},
        )
        self.db.commit()
        return IssuedInvitation(invitation, plaintext, sent)

    # ------------------------------------------------------------------ #
    # Validate (§8) — used by the public GET /invitations/{token}
    # ------------------------------------------------------------------ #
    def validate(self, plaintext: str) -> Invitation:
        """Resolve a token to a live invitation, or raise the *specific* reason.

        A user staring at a dead link must be told which kind of dead it is: expired
        links can be re-requested, cancelled ones cannot, and an already-accepted one
        means "you already have an account, go and sign in". One generic 404 for all
        three would be a worse product and no more secure — the token is unguessable,
        so possessing it already proves the holder was sent it.
        """
        invitation = self.repo.get_by_token(plaintext)
        if invitation is None:
            raise IdentityError(ErrorCode.INVITATION_NOT_FOUND, "Invitation does not exist.")

        status = InvitationStatus(invitation.status)
        if status is InvitationStatus.ACCEPTED:
            raise IdentityError(
                ErrorCode.INVITATION_ALREADY_USED, "This invitation has already been used."
            )
        if status is InvitationStatus.CANCELLED:
            raise IdentityError(
                ErrorCode.INVITATION_CANCELLED, "This invitation was cancelled."
            )
        if status is InvitationStatus.EXPIRED or self._is_expired(invitation):
            self._materialise_expired(invitation)
            self.db.commit()
            raise IdentityError(ErrorCode.INVITATION_EXPIRED, "This invitation has expired.")

        return invitation

    # ------------------------------------------------------------------ #
    # Accept — called inside the registration transaction
    # ------------------------------------------------------------------ #
    def mark_accepted(
        self, invitation: Invitation, *, user_id: uuid.UUID, context: RequestContext | None = None
    ) -> Invitation:
        invitation.status = InvitationStatus.ACCEPTED.value
        invitation.accepted_at = _now()
        self.db.flush()
        self.audit.record(
            AuthEventType.INVITATION_ACCEPTED,
            organization_id=invitation.organization_id,
            target_email=invitation.email,
            actor_id=user_id,
            context=context,
            metadata={"invitation_id": str(invitation.id)},
        )
        return invitation

    # ------------------------------------------------------------------ #
    # Resend (§7) — rotates the token so the old link dies
    # ------------------------------------------------------------------ #
    def resend(
        self, invitation: Invitation, *, actor: User, context: RequestContext | None = None
    ) -> IssuedInvitation:
        if InvitationStatus(invitation.status) is not InvitationStatus.PENDING:
            raise IdentityError(
                ErrorCode.INVITATION_ALREADY_USED, "Only a pending invitation can be resent."
            )

        # Rotate. Leaving the old token alive would mean a resend *adds* a valid link
        # rather than replacing one, and "single use" would quietly become "N uses".
        plaintext, hashed = generate_invitation_token()
        now = _now()
        invitation.token_hash = hashed
        invitation.expires_at = now + self.ttl
        invitation.resent_count += 1
        invitation.last_sent_at = now
        self.db.flush()

        sent = self._send(invitation, plaintext)
        self.audit.record(
            AuthEventType.INVITATION_RESENT,
            organization_id=invitation.organization_id,
            target_email=invitation.email,
            actor_id=actor.id,
            context=context,
            metadata={
                "invitation_id": str(invitation.id),
                "resent_count": invitation.resent_count,
                "delivered": sent,
            },
        )
        self.audit.record(
            AuthEventType.INVITATION_SENT,
            organization_id=invitation.organization_id,
            target_email=invitation.email,
            actor_id=actor.id,
            context=context,
            metadata={"invitation_id": str(invitation.id), "delivered": sent},
        )
        self.db.commit()
        return IssuedInvitation(invitation, plaintext, sent)

    # ------------------------------------------------------------------ #
    # Cancel (§7)
    # ------------------------------------------------------------------ #
    def cancel(
        self, invitation: Invitation, *, actor: User, context: RequestContext | None = None
    ) -> Invitation:
        if InvitationStatus(invitation.status) is InvitationStatus.ACCEPTED:
            raise IdentityError(
                ErrorCode.INVITATION_ALREADY_USED,
                "That invitation was already accepted; suspend the user instead.",
            )
        if InvitationStatus(invitation.status) is InvitationStatus.CANCELLED:
            return invitation  # idempotent

        invitation.status = InvitationStatus.CANCELLED.value
        invitation.cancelled_at = _now()
        self.db.flush()
        self.audit.record(
            AuthEventType.INVITATION_CANCELLED,
            organization_id=invitation.organization_id,
            target_email=invitation.email,
            actor_id=actor.id,
            context=context,
            metadata={"invitation_id": str(invitation.id)},
        )
        self.db.commit()
        return invitation

    # ------------------------------------------------------------------ #
    # Listing / expiry
    # ------------------------------------------------------------------ #
    def list_for_organization(
        self, organization_id: uuid.UUID, *, status: str | None = None, limit: int = 100
    ) -> list[Invitation]:
        """List an organization's invitations, reaping its expired ones first.

        The reap covers the **whole organization**, not just the rows on this page.
        Materialising only the current page would leave the database disagreeing with
        itself the moment an administrator filtered or paginated: a row absent from this
        response would stay ``PENDING`` for ever while its clock had long run out.
        """
        self.reap_expired(organization_id=organization_id)
        return self.repo.list_for_organization(organization_id, status=status, limit=limit)

    def reap_expired(self, *, organization_id: uuid.UUID | None = None, limit: int = 500) -> int:
        """Bulk-materialise expired invitations, optionally scoped to one organization.

        Called by ``list_for_organization`` on every admin read, and safe to run from a
        cron for the tenants nobody is looking at. ``validate`` still handles a single
        expired link lazily, so no read path can ever see a live-looking corpse.
        """
        rows = self.repo.list_expired_pending(
            _now(), organization_id=organization_id, limit=limit
        )
        for invitation in rows:
            self._materialise_expired(invitation)
        if rows:
            self.db.commit()
        return len(rows)

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    @staticmethod
    def _is_expired(invitation: Invitation, *, now: datetime | None = None) -> bool:
        return _aware(invitation.expires_at) <= (now or _now())

    def _materialise_expired(self, invitation: Invitation) -> None:
        """Record the clock's verdict — **once**.

        Without this guard, every read of an already-expired link re-emits
        ``INVITATION_EXPIRED``: the audit stream fills with duplicates, and anyone can
        make us write unbounded rows by hitting a dead *public* link in a loop. The
        event marks a state *transition*, not a state.
        """
        if InvitationStatus(invitation.status) is not InvitationStatus.PENDING:
            return
        invitation.status = InvitationStatus.EXPIRED.value
        self.db.flush()
        self.audit.record(
            AuthEventType.INVITATION_EXPIRED,
            organization_id=invitation.organization_id,
            target_email=invitation.email,
            actor_id=None,
            metadata={"invitation_id": str(invitation.id)},
        )

    def _send(self, invitation: Invitation, plaintext: str) -> bool:
        organization = self.db.get(Organization, invitation.organization_id)
        role = self.db.get(Role, invitation.role_id) if invitation.role_id else None
        inviter = self.db.get(User, invitation.invited_by) if invitation.invited_by else None
        result = self.emails.send_invitation(
            invitation.email,
            organization_name=organization.name if organization else "your organization",
            role_name=role.name if role else None,
            invited_by_name=inviter.name if inviter else None,
            token=plaintext,
            expires_in_days=max(1, settings.INVITATION_TTL_SECONDS // 86400),
        )
        return result.sent
