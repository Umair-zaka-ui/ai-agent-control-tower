"""RegistrationService — the onboarding orchestrator (4.2.2.3.1 §7, §8).

Composes invitation, provisioning, verification, email and audit. This is the only
place a human account is created from a public request.

The lifecycle (§4) is walked one transition at a time, and **every state is really
persisted**:

    INVITED → REGISTERED → EMAIL_PENDING → EMAIL_VERIFIED → ACTIVE

- ``REGISTERED``     the account exists; the verification email has not gone out yet.
                     A user *stays* here when SMTP fails, which is precisely when an
                     operator needs to see it. ``resend-verification`` retries from here.
- ``EMAIL_PENDING``  the email is out. Cannot sign in.
- ``EMAIL_VERIFIED`` the address is proven. In ``SELF_SERVICE`` mode this is where the
                     account waits for an administrator. In ``INVITE_ONLY`` the admin
                     already approved by inviting, so activation follows in the same
                     transaction — both transitions audited.

Enumeration (§14): the public endpoints never reveal whether an email is registered.
``resend-verification`` returns the same generic acknowledgement for a known address,
an unknown address, and an address that is already verified.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.auth.enums import AuthEventType
from app.identity.email import EmailService
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.enums import IdentityStatus, RegistrationMode, can_transition
from app.identity.registration.audit import RegistrationAuditService, RequestContext
from app.identity.registration.invitation_service import InvitationService
from app.identity.registration.provisioning_service import (
    ProvisionRequest,
    UserProvisioningService,
)
from app.identity.registration.verification_service import EmailVerificationService
from app.identity.security.passwords import PasswordPolicyError
from app.models.organization import Organization
from app.models.user import User


@dataclass
class RegistrationResult:
    user: User
    email_sent: bool
    status: IdentityStatus
    requires_approval: bool


class RegistrationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.invitations = InvitationService(db)
        self.provisioning = UserProvisioningService(db)
        self.verification = EmailVerificationService(db)
        self.emails = EmailService()
        self.audit = RegistrationAuditService(db)

    # ------------------------------------------------------------------ #
    # Register (§8, §10, §11)
    # ------------------------------------------------------------------ #
    def register_from_invitation(
        self,
        *,
        token: str,
        first_name: str,
        last_name: str,
        password: str,
        phone: str | None = None,
        timezone: str | None = None,
        language: str | None = None,
        job_title: str | None = None,
        context: RequestContext | None = None,
    ) -> RegistrationResult:
        """Mode 1 (§3): the invitee sets a password and the account is created.

        The email address comes from the **invitation**, never from the request body
        (§11). Accepting a caller-supplied email would let anyone holding a link
        register an arbitrary address into the organization.
        """
        invitation = self.invitations.validate(token)

        # Race: two tabs, one link. The unique index on users.email is the real guard;
        # this check turns a 500 into a clear 409.
        if self._email_taken(invitation.email):
            raise IdentityError(
                ErrorCode.USER_ALREADY_EXISTS, "An account already exists for that email."
            )

        user = self._provision(
            organization_id=invitation.organization_id,
            email=invitation.email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role_id=invitation.role_id,
            department_id=invitation.department_id,
            phone=phone,
            timezone=timezone,
            language=language,
            job_title=job_title,
        )

        self.invitations.mark_accepted(invitation, user_id=user.id, context=context)
        self.audit.record(
            AuthEventType.USER_REGISTERED,
            organization_id=user.organization_id,
            target_email=user.email,
            actor_id=user.id,
            context=context,
            metadata={"mode": "INVITATION", "invitation_id": str(invitation.id)},
        )
        self._record_password_created(user, context=context, mode="INVITATION")

        sent = self._start_verification(user, context=context)
        self.db.commit()
        return RegistrationResult(user, sent, IdentityStatus(user.status), requires_approval=False)

    def register_self_service(
        self,
        *,
        organization_id: uuid.UUID,
        email: str,
        first_name: str,
        last_name: str,
        password: str,
        phone: str | None = None,
        timezone: str | None = None,
        language: str | None = None,
        context: RequestContext | None = None,
    ) -> RegistrationResult:
        """Mode 3 (§3): disabled by default; verification *and* approval still required."""
        organization = self.db.get(Organization, organization_id)
        if organization is None:
            raise IdentityError(ErrorCode.ORGANIZATION_NOT_FOUND, "Organization does not exist.")

        mode = RegistrationMode(organization.registration_mode)
        if mode is not RegistrationMode.SELF_SERVICE:
            self.audit.record(
                AuthEventType.REGISTRATION_BLOCKED,
                organization_id=organization_id,
                target_email=email,
                context=context,
                metadata={"registration_mode": mode.value},
            )
            self.db.commit()
            raise IdentityError(
                ErrorCode.REGISTRATION_DISABLED,
                "Self-registration is not enabled for this organization.",
            )

        if self._email_taken(email):
            raise IdentityError(
                ErrorCode.USER_ALREADY_EXISTS, "An account already exists for that email."
            )

        user = self._provision(
            organization_id=organization_id,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role_id=None,  # self-registered users get VIEWER until an admin says otherwise
            department_id=None,
            phone=phone,
            timezone=timezone,
            language=language,
            job_title=None,
        )
        self.audit.record(
            AuthEventType.USER_REGISTERED,
            organization_id=user.organization_id,
            target_email=user.email,
            actor_id=user.id,
            context=context,
            metadata={"mode": "SELF_SERVICE"},
        )
        self._record_password_created(user, context=context, mode="SELF_SERVICE")
        sent = self._start_verification(user, context=context)
        self.db.commit()
        return RegistrationResult(user, sent, IdentityStatus(user.status), requires_approval=True)

    # ------------------------------------------------------------------ #
    # Verify (§12)
    # ------------------------------------------------------------------ #
    def verify_email(self, token: str, *, context: RequestContext | None = None) -> RegistrationResult:
        """Redeem the token, then activate — or park the account for approval."""
        user = self.verification.redeem(token, context=context)
        self._transition(user, IdentityStatus.EMAIL_VERIFIED)

        organization = self.db.get(Organization, user.organization_id)
        mode = RegistrationMode(organization.registration_mode) if organization else RegistrationMode.INVITE_ONLY
        org_name = organization.name if organization else "your organization"

        if mode is RegistrationMode.SELF_SERVICE:
            # The address is proven; a human still has to say yes (§3 mode 3).
            self.audit.record(
                AuthEventType.ACCOUNT_PENDING_APPROVAL,
                organization_id=user.organization_id,
                target_email=user.email,
                actor_id=user.id,
                context=context,
            )
            self.emails.send_pending_approval_notice(user.email, organization_name=org_name)
            self.db.commit()
            return RegistrationResult(user, True, IdentityStatus.EMAIL_VERIFIED, requires_approval=True)

        self.activate(user, context=context)
        self.db.commit()
        return RegistrationResult(user, True, IdentityStatus.ACTIVE, requires_approval=False)

    def resend_verification(self, email: str, *, context: RequestContext | None = None) -> None:
        """Always succeeds from the caller's point of view (§14).

        A response that differs for "unknown address" versus "already verified" turns
        this endpoint into an account-existence oracle. It is rate limited (§19), but a
        rate limit slows enumeration; it does not prevent it.
        """
        user = self.db.execute(
            select(User).where(User.email == email.strip().lower())
        ).scalar_one_or_none()
        if user is None:
            return
        if self.verification.is_verified(user.id):
            return
        if IdentityStatus(user.status) not in (
            IdentityStatus.REGISTERED,
            IdentityStatus.EMAIL_PENDING,
        ):
            return

        issued = self.verification.issue(user, context=context)
        if issued.email_sent and IdentityStatus(user.status) is IdentityStatus.REGISTERED:
            self._transition(user, IdentityStatus.EMAIL_PENDING)
        self.db.commit()

    # ------------------------------------------------------------------ #
    # Activation (§4, §13)
    # ------------------------------------------------------------------ #
    def activate(self, user: User, *, context: RequestContext | None = None) -> User:
        """EMAIL_VERIFIED → ACTIVE. The account may now sign in."""
        self._transition(user, IdentityStatus.ACTIVE)
        user.is_active = True
        self.db.flush()

        organization = self.db.get(Organization, user.organization_id)
        self.audit.record(
            AuthEventType.ACCOUNT_ACTIVATED,
            organization_id=user.organization_id,
            target_email=user.email,
            actor_id=user.id,
            context=context,
        )
        self.emails.send_account_activated(
            user.email, organization_name=organization.name if organization else "your organization"
        )
        return user

    def approve(self, user: User, *, actor_id: uuid.UUID, context: RequestContext | None = None) -> User:
        """Administrator approval for a self-registered, email-verified account."""
        if IdentityStatus(user.status) is not IdentityStatus.EMAIL_VERIFIED:
            raise IdentityError(
                ErrorCode.INVALID_LIFECYCLE_TRANSITION,
                "Only an email-verified account awaiting approval can be approved.",
            )
        self.activate(user, context=context)
        self.db.commit()
        return user

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    def _email_taken(self, email: str) -> bool:
        stmt = select(User.id).where(User.email == email.strip().lower())
        return self.db.execute(stmt).scalars().first() is not None

    def _provision(self, **kwargs) -> User:
        try:
            user = self.provisioning.provision(
                ProvisionRequest(**kwargs), status=IdentityStatus.REGISTERED
            )
        except PasswordPolicyError as exc:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
        self.provisioning.initialize_preferences(
            user, timezone=kwargs.get("timezone"), language=kwargs.get("language")
        )
        return user

    def _record_password_created(
        self, user: User, *, context: RequestContext | None, mode: str
    ) -> None:
        """A real credential was set at registration (Part 4.2.2.3.2 §18).

        SSO/SCIM identities have no password (the UNUSABLE sentinel), so no
        credential event is due for them.
        """
        from app.core.security import is_unusable_password

        if is_unusable_password(user.password_hash):
            return
        self.audit.record(
            AuthEventType.PASSWORD_CREATED,
            organization_id=user.organization_id,
            target_email=user.email,
            actor_id=user.id,
            context=context,
            metadata={"mode": mode},
        )

    def _start_verification(self, user: User, *, context: RequestContext | None) -> bool:
        """Issue + send the verification token, then advance REGISTERED → EMAIL_PENDING.

        The transition happens **only if the email left the building**. A user stuck in
        REGISTERED is the signal that mail is broken — which is exactly the state an
        operator needs to be able to see and a resend needs to retry from.
        """
        issued = self.verification.issue(user, context=context)
        if issued.email_sent:
            self._transition(user, IdentityStatus.EMAIL_PENDING)
        return issued.email_sent

    def _transition(self, user: User, target: IdentityStatus) -> None:
        current = IdentityStatus(user.status)
        if current is target:
            return
        if not can_transition(current, target):
            raise IdentityError(
                ErrorCode.INVALID_LIFECYCLE_TRANSITION,
                f"Cannot move an identity from {current.value} to {target.value}.",
            )
        user.status = target.value
        user.is_active = target is IdentityStatus.ACTIVE
        self.db.flush()
