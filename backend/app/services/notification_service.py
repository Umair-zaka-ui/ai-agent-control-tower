"""Notification service - email notifications via SMTP (Mailtrap in dev).

Designed to be called from FastAPI ``BackgroundTasks`` so the request returns
immediately. When ``NOTIFICATIONS_ENABLED`` is false (the default for local dev), sends
are **suppressed** rather than attempted -- nothing breaks without an SMTP server.

Suppressed does not mean discarded. An onboarding email carries the *only* copy of a
single-use token: the database stores nothing but its SHA-256. Logging the subject and
throwing the body away meant every invitation created in development was permanently
unacceptable, and there was no way to recover the link. Suppressed messages are therefore
appended to a **development outbox** file, which the developer can read.
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger("control_tower.notifications")


def delivery_enabled() -> bool:
    """True when messages are actually handed to an SMTP server."""
    return settings.NOTIFICATIONS_ENABLED


def outbox_path() -> Path | None:
    """The development outbox, or ``None`` when mail is really being sent."""
    if delivery_enabled():
        return None
    return Path(settings.EMAIL_DEV_OUTBOX_PATH)


def _write_to_outbox(recipients: list[str], subject: str, body: str) -> bool:
    """Append a suppressed message, body included, to the development outbox.

    Guarded by ``delivery_enabled()``: this file holds plaintext invitation and
    verification tokens, and a deployment that actually sends mail must never produce it.
    """
    path = outbox_path()
    if path is None:  # pragma: no cover - guarded by the caller too
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                f"\n{'=' * 78}\n"
                f"date:    {stamp}\n"
                f"to:      {', '.join(recipients)}\n"
                f"subject: {subject}\n"
                f"{'-' * 78}\n"
                f"{body}\n"
            )
    except OSError as exc:  # pragma: no cover - disk full, permissions, ...
        logger.warning("could not write to the dev outbox %s: %s", path, exc)
        return False
    return True


def send_email(to: list[str] | str, subject: str, body: str) -> bool:
    """Send a plaintext email. Never raises.

    Returns whether the message reached its configured sink -- a real SMTP server, or
    the development outbox. Callers that must record the outcome (onboarding emails carry
    the only copy of a single-use token) need to distinguish that from "silently dropped".
    Callers that do not care may keep ignoring the return value.

    ``EmailService`` additionally reports *how* it was delivered, so the UI can say
    "email delivery is disabled" instead of telling a user to check an inbox that will
    stay empty.
    """
    recipients = [to] if isinstance(to, str) else list(to)
    recipients = [r for r in recipients if r]
    if not recipients:
        return False

    if not delivery_enabled():
        # Subject and recipients only. The body holds the links, and logs get shipped.
        logger.info("[email suppressed -> dev outbox] %s: %s", recipients, subject)
        return _write_to_outbox(recipients, subject, body)

    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            if settings.SMTP_USERNAME:
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.send_message(message)
        logger.info("Sent notification to %s: %s", recipients, subject)
        return True
    except Exception:  # pragma: no cover - network/SMTP failures must not break requests
        logger.exception("Failed to send notification email to %s", recipients)
        return False


# --------------------------------------------------------------------------- #
# Event helpers (build subject/body for each notification type)
# --------------------------------------------------------------------------- #
def notify_approval_requested(
    recipients: list[str], *, agent_name: str, resource: str, action: str, risk_score: int
) -> None:
    send_email(
        recipients,
        subject=f"[Control Tower] Approval needed: {agent_name} {resource}/{action}",
        body=(
            f"Agent '{agent_name}' attempted {action} on {resource} (risk {risk_score}).\n"
            "It requires human approval. Review it in the approval queue."
        ),
    )


def notify_approval_decided(
    recipients: list[str], *, decision: str, resource: str, action: str, comment: str | None
) -> None:
    send_email(
        recipients,
        subject=f"[Control Tower] Action {decision}: {resource}/{action}",
        body=(
            f"An approval for {action} on {resource} was {decision}.\n"
            f"Reviewer comment: {comment or '(none)'}"
        ),
    )


def notify_agent_suspended(recipients: list[str], *, agent_name: str) -> None:
    send_email(
        recipients,
        subject=f"[Control Tower] Agent suspended: {agent_name}",
        body=f"Agent '{agent_name}' has been suspended and can no longer perform actions.",
    )


def notify_policy_violation(
    recipients: list[str], *, agent_name: str, policy_name: str, resource: str, action: str
) -> None:
    send_email(
        recipients,
        subject=f"[Control Tower] Policy triggered: {policy_name}",
        body=(
            f"Agent '{agent_name}' triggered policy '{policy_name}' on "
            f"{resource}/{action}."
        ),
    )
