"""Transactional email for onboarding (4.2.2.3.1 §6, §8, §12).

Wraps the platform's ``notification_service.send_email`` so the identity layer has
one place that knows what an invitation email looks like, and so a failure to send
is a *typed outcome* rather than an exception that aborts a database transaction
halfway through account creation.

**Sending is best-effort and never rolls back the account.** If SMTP is down, the
user is left in ``REGISTERED``/``EMAIL_PENDING`` with a valid token in the database
and can be re-sent to. Losing the account because a mail server hiccuped would be
strictly worse than leaving it un-emailed.

**The token appears in the link, never in a log.** ``notification_service`` logs only
the subject and recipients, never the body. Our own failure logs redact the address.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote

from app.core.config import settings
from app.services import notification_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailResult:
    """What happened to the message. Callers record this, not an exception.

    ``sent`` means it reached its configured sink, which keeps the onboarding state
    machine moving in development. ``suppressed`` means that sink was the dev outbox, not
    a mail server -- the truth the UI needs so it never tells a user to check an inbox
    that will stay empty.
    """

    sent: bool
    suppressed: bool = False
    error: str | None = None


def invitation_url(token: str) -> str:
    """The link an invitee clicks. Carries the opaque token, never an internal id."""
    return f"{settings.APP_BASE_URL.rstrip('/')}/invite/{quote(token, safe='')}"


def verification_url(token: str) -> str:
    return f"{settings.APP_BASE_URL.rstrip('/')}/verify-email/{quote(token, safe='')}"


def reset_url(token: str) -> str:
    """The link a user clicks to reset their password (4.2.2.3.3 §10)."""
    return f"{settings.APP_BASE_URL.rstrip('/')}/reset-password/{quote(token, safe='')}"


def new_email_verification_url(token: str) -> str:
    """The link sent to a *new* address to confirm an email change (§12)."""
    return f"{settings.APP_BASE_URL.rstrip('/')}/verify-new-email/{quote(token, safe='')}"


def _send(to: str, subject: str, body: str, *, what: str) -> EmailResult:
    """``send_email`` never raises and returns whether the message was accepted.

    The try/except is belt-and-braces: a mail failure must never abort onboarding
    halfway through account creation.
    """
    suppressed = not notification_service.delivery_enabled()
    try:
        delivered = notification_service.send_email(to, subject, body)
    except Exception as exc:  # noqa: BLE001 - a mail failure must not abort onboarding
        logger.warning("%s email to %s failed: %s", what, _redact_email(to), exc)
        return EmailResult(sent=False, suppressed=suppressed, error=str(exc))
    if not delivered:
        logger.warning("%s email to %s was not delivered", what, _redact_email(to))
        return EmailResult(sent=False, suppressed=suppressed, error="delivery failed")
    return EmailResult(sent=True, suppressed=suppressed)


def _redact_email(email: str) -> str:
    """``ada@example.com`` -> ``a***@example.com``. Enough to correlate, not to harvest."""
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    return f"{local[:1]}***@{domain}"


class EmailService:
    """Renders and dispatches the onboarding emails."""

    def send_invitation(
        self,
        to: str,
        *,
        organization_name: str,
        role_name: str | None,
        invited_by_name: str | None,
        token: str,
        expires_in_days: int,
    ) -> EmailResult:
        url = invitation_url(token)
        inviter = f"{invited_by_name} has invited you" if invited_by_name else "You have been invited"
        role_line = f"Role: {role_name}\n" if role_name else ""
        body = (
            f"{inviter} to join {organization_name} on AI Agent Control Tower.\n\n"
            f"{role_line}"
            f"Accept your invitation:\n{url}\n\n"
            f"This link expires in {expires_in_days} days and can be used once.\n"
            f"If you were not expecting this invitation, you can ignore this email.\n"
        )
        return _send(to, f"You're invited to {organization_name}", body, what="invitation")

    def send_verification(
        self, to: str, *, first_name: str | None, token: str, expires_in_hours: int
    ) -> EmailResult:
        url = verification_url(token)
        greeting = f"Hi {first_name}," if first_name else "Hi,"
        body = (
            f"{greeting}\n\n"
            f"Confirm your email address to activate your account:\n{url}\n\n"
            f"This link expires in {expires_in_hours} hours and can be used once.\n"
            f"If you did not create this account, you can ignore this email.\n"
        )
        return _send(to, "Confirm your email address", body, what="verification")

    def send_pending_approval_notice(self, to: str, *, organization_name: str) -> EmailResult:
        body = (
            f"Your email address is confirmed.\n\n"
            f"An administrator of {organization_name} must approve your account before "
            f"you can sign in. You will be emailed when that happens.\n"
        )
        return _send(to, "Your account is awaiting approval", body, what="pending-approval")

    def send_account_activated(self, to: str, *, organization_name: str) -> EmailResult:
        body = (
            f"Your account at {organization_name} is active. You can now sign in:\n"
            f"{settings.APP_BASE_URL.rstrip('/')}/login\n"
        )
        return _send(to, "Your account is active", body, what="activation")

    # --- Recovery (4.2.2.3.3 §16, §17) ------------------------------------- #
    def send_password_reset(
        self, to: str, *, first_name: str | None, token: str, expires_in_minutes: int
    ) -> EmailResult:
        url = reset_url(token)
        greeting = f"Hi {first_name}," if first_name else "Hi,"
        body = (
            f"{greeting}\n\n"
            f"We received a request to reset your password. Choose a new one here:\n{url}\n\n"
            f"This link expires in {expires_in_minutes} minutes and can be used once.\n"
            f"If you did not request this, you can ignore this email — your password is "
            f"unchanged. You may want to review your account security.\n"
        )
        return _send(to, "Reset your password", body, what="password-reset")

    def send_password_changed_alert(self, to: str) -> EmailResult:
        """After a successful reset/change (§17). A recovery alert: if the user did
        not do this, it is their signal that the account may be compromised."""
        body = (
            "Your password was just changed.\n\n"
            "If this was you, no action is needed. If it was not, contact your "
            "administrator immediately — someone may have access to your account.\n"
        )
        return _send(to, "Your password was changed", body, what="password-changed")

    def send_email_change_verification(
        self, to_new: str, *, first_name: str | None, token: str, expires_in_hours: int
    ) -> EmailResult:
        url = new_email_verification_url(token)
        greeting = f"Hi {first_name}," if first_name else "Hi,"
        body = (
            f"{greeting}\n\n"
            f"Confirm this address to make it the new email for your account:\n{url}\n\n"
            f"This link expires in {expires_in_hours} hours and can be used once.\n"
            f"Until you confirm, your current email address stays in effect.\n"
        )
        return _send(to_new, "Confirm your new email address", body, what="email-change")

    def send_email_changed_alert(self, to_old: str, *, new_email: str) -> EmailResult:
        """Sent to the OLD address when an email change is verified (§17). The old
        mailbox is the one an attacker does not control, so this is where the alarm
        must ring."""
        body = (
            f"The email address on your account was changed to {new_email}.\n\n"
            f"If you did not make this change, contact your administrator immediately.\n"
        )
        return _send(to_old, "Your account email was changed", body, what="email-changed")
