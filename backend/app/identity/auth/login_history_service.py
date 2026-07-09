"""LoginHistoryService — record attempts and drive account lockout (SRS §10, §13, §14).

Every authentication attempt (success or failure) is written to ``login_history``.
The same table backs the lockout window: after ``LOCKOUT_THRESHOLD`` failures
within ``LOCKOUT_WINDOW``, the account is locked for the remainder of the window.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.identity.models.login_history import LoginHistory
from app.identity.repositories.login_history_repository import LoginHistoryRepository


@dataclass
class LockoutState:
    locked: bool
    failed_attempts: int
    retry_after_seconds: int | None = None


class LoginHistoryService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = LoginHistoryRepository(db)
        self.threshold = settings.AUTH_LOCKOUT_THRESHOLD
        self.window = timedelta(seconds=settings.AUTH_LOCKOUT_WINDOW_SECONDS)

    def record(
        self,
        *,
        email: str,
        success: bool,
        user_id: uuid.UUID | None = None,
        failure_reason: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        country: str | None = None,
        city: str | None = None,
        organization_id: uuid.UUID | None = None,
        device_fingerprint: str | None = None,
        risk_score: int | None = None,
        decision: str | None = None,
    ) -> LoginHistory:
        entry = LoginHistory(
            user_id=user_id,
            email=email,
            success=success,
            failure_reason=failure_reason,
            ip_address=ip_address,
            user_agent=user_agent,
            country=country,
            city=city,
            organization_id=organization_id,
            device_fingerprint=device_fingerprint,
            risk_score=risk_score,
            decision=decision,
        )
        return self.repo.add(entry)

    def lockout_state(self, email: str, *, now: datetime | None = None) -> LockoutState:
        """Compute lockout purely from recent failures in the window (SRS §10)."""
        now = now or datetime.now(timezone.utc)
        since = now - self.window
        failures = self.repo.count_recent_failures(email, since)
        if failures >= self.threshold:
            return LockoutState(
                locked=True,
                failed_attempts=failures,
                retry_after_seconds=int(self.window.total_seconds()),
            )
        return LockoutState(locked=False, failed_attempts=failures)

    def is_locked(self, email: str) -> bool:
        return self.lockout_state(email).locked

    def history(self, user_id: uuid.UUID, *, limit: int = 50) -> list[LoginHistory]:
        return self.repo.list_for_user(user_id, limit=limit)
