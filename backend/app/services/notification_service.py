"""Notification service - email notifications via SMTP (Mailtrap in dev).

Designed to be called from FastAPI ``BackgroundTasks`` so the request returns
immediately. If ``NOTIFICATIONS_ENABLED`` is false (the default for local dev),
sends are logged and skipped so nothing breaks without an SMTP server.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger("control_tower.notifications")


def send_email(to: list[str] | str, subject: str, body: str) -> None:
    """Send a plaintext email. Never raises - failures are logged."""
    recipients = [to] if isinstance(to, str) else list(to)
    recipients = [r for r in recipients if r]
    if not recipients:
        return

    if not settings.NOTIFICATIONS_ENABLED:
        logger.info("[notifications disabled] would email %s: %s", recipients, subject)
        return

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
    except Exception:  # pragma: no cover - network/SMTP failures must not break requests
        logger.exception("Failed to send notification email to %s", recipients)


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
