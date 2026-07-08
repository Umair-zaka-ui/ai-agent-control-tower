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
