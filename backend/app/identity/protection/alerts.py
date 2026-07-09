"""SecurityAlertService — notify users and admins of protection events (§30).

Alerts are best-effort emails on top of the always-recorded security event: a mail
failure must never break a login or a lock. Notifications are suppressed in dev/test
(NOTIFICATIONS_ENABLED=false) exactly like every other email.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.user import User
from app.services import notification_service

logger = logging.getLogger("control_tower.protection.alerts")


class SecurityAlertService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _safe_send(self, to: str, subject: str, body: str) -> None:
        try:
            notification_service.send_email(to, subject, body)
        except Exception:  # noqa: BLE001 - an alert failure must never break auth
            logger.exception("security alert to a user failed")

    def account_locked(self, user: User, *, escalated: bool, retry_after_seconds: int | None) -> None:
        when = (
            "It requires a security review before it can be used again."
            if escalated
            else f"It will unlock automatically in about {max(1, (retry_after_seconds or 0) // 60)} minutes."
        )
        self._safe_send(
            user.email,
            "Your account was locked",
            "We locked your account after repeated failed sign-in attempts.\n\n"
            f"{when}\n\nIf this was not you, contact your administrator — someone may be "
            "trying to access your account.\n",
        )

    def account_unlocked(self, user: User) -> None:
        self._safe_send(
            user.email,
            "Your account was unlocked",
            "An administrator has unlocked your account. You can sign in again.\n",
        )

    def high_risk_login(self, user: User, *, risk_level: str) -> None:
        self._safe_send(
            user.email,
            "Unusual sign-in detected",
            f"We noticed a {risk_level.lower()}-risk sign-in to your account. If this was you, "
            "no action is needed. If not, change your password and contact your administrator.\n",
        )

    def suspicious_login_blocked(self, user: User) -> None:
        self._safe_send(
            user.email,
            "A sign-in to your account was blocked",
            "We blocked a sign-in that looked unsafe. If this was you, try again from a "
            "trusted device, or contact your administrator.\n",
        )
