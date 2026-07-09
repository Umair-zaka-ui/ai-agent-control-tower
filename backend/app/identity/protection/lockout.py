"""AccountLockoutService — progressive, stateful account locks (4.2.2.3.4 §8, §29).

The ``account_locks`` row is the source of truth for "is this account locked now",
not a recomputed window. Each new lock while the account keeps failing escalates the
duration (15m → 30m → 1h → 24h); a 5th lock escalates to an indefinite
SECURITY_REVIEW_REQUIRED lock only an administrator can lift.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.identity.auth.enums import AuthEventType, AuthIdentityType, AuthMethod
from app.identity.auth.security_event_service import SecurityEventService
from app.identity.models.enums import IdentityStatus
from app.identity.models.protection import AccountLock
from app.identity.protection.enums import AccountLockReason, AccountLockStatus
from app.identity.protection.repositories import AccountLockRepository
from app.models.user import User


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass
class LockResult:
    lock: AccountLock
    escalated: bool
    retry_after_seconds: int | None


class AccountLockoutService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = AccountLockRepository(db)
        self.events = SecurityEventService(db)
        self.durations = settings.PROTECTION_LOCKOUT_DURATIONS

    # ------------------------------------------------------------------ #
    # Query — materialises expiry on read (the clock decides)
    # ------------------------------------------------------------------ #
    def active_lock(self, user_id: uuid.UUID) -> AccountLock | None:
        lock = self.repo.active_for_user(user_id)
        if lock is None:
            return None
        if lock.expires_at is not None and _aware(lock.expires_at) <= _now():
            lock.status = AccountLockStatus.EXPIRED.value
            self.db.flush()
            return None
        return lock

    def is_locked(self, user_id: uuid.UUID) -> bool:
        return self.active_lock(user_id) is not None

    # ------------------------------------------------------------------ #
    # Lock — progressive (§8)
    # ------------------------------------------------------------------ #
    def lock(
        self,
        user: User,
        *,
        reason: AccountLockReason,
        actor_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        metadata: dict | None = None,
    ) -> LockResult:
        """Create a lock, choosing the duration from how many times this account has
        already been locked. Idempotent within a lock: if one is already active it is
        returned unchanged."""
        existing = self.active_lock(user.id)
        if existing is not None:
            return LockResult(existing, escalated=False, retry_after_seconds=self._retry_after(existing))

        prior = self.repo.count_for_user(user.id)
        escalated = prior >= len(self.durations)
        now = _now()
        if escalated:
            expires_at = None  # indefinite — needs an admin / security review
            status_reason = AccountLockReason.SECURITY_POLICY.value if reason is None else reason.value
        else:
            expires_at = now + timedelta(seconds=self.durations[prior])
            status_reason = reason.value

        lock = AccountLock(
            user_id=user.id,
            organization_id=user.organization_id,
            reason=status_reason,
            status=(AccountLockStatus.ESCALATED.value if escalated else AccountLockStatus.ACTIVE.value),
            locked_at=now,
            expires_at=expires_at,
            meta={"prior_locks": prior, **(metadata or {})},
            created_at=now,
        )
        self.db.add(lock)

        if escalated:
            # A repeatedly-attacked account is parked for human review (§8, §16).
            user.status = IdentityStatus.SECURITY_REVIEW_REQUIRED.value
            user.is_active = False
        self.db.flush()

        # New event (protection layer) + the legacy AUTH_LOGIN_LOCKED that 4.2.2.1
        # tests and dashboards already key on.
        for event in (AuthEventType.ACCOUNT_LOCKED, AuthEventType.AUTH_LOGIN_LOCKED):
            self.events.record(
                event,
                auth_method=AuthMethod.PASSWORD,
                identity_type=AuthIdentityType.HUMAN_USER.value,
                organization_id=user.organization_id,
                identity_id=user.id,
                ip_address=ip_address,
                metadata={
                    "lock_id": str(lock.id),
                    "reason": status_reason,
                    "escalated": escalated,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                },
            )
        if escalated:
            self.events.record(
                AuthEventType.SECURITY_REVIEW_REQUIRED,
                auth_method=AuthMethod.PASSWORD,
                identity_type=AuthIdentityType.HUMAN_USER.value,
                organization_id=user.organization_id,
                identity_id=user.id,
                ip_address=ip_address,
                metadata={"lock_id": str(lock.id)},
            )
        return LockResult(lock, escalated=escalated, retry_after_seconds=self._retry_after(lock))

    # ------------------------------------------------------------------ #
    # Unlock — admin action (§29)
    # ------------------------------------------------------------------ #
    def unlock(
        self,
        lock: AccountLock,
        *,
        actor_id: uuid.UUID | None,
        reason: str,
        reactivate: bool = True,
    ) -> AccountLock:
        lock.status = AccountLockStatus.MANUALLY_UNLOCKED.value
        lock.unlocked_at = _now()
        lock.unlocked_by = actor_id
        lock.meta = {**(lock.meta or {}), "unlock_reason": reason}

        user = self.db.get(User, lock.user_id)
        if user is not None and reactivate and user.status in (
            IdentityStatus.SECURITY_REVIEW_REQUIRED.value,
            IdentityStatus.LOCKED.value,
        ):
            user.status = IdentityStatus.ACTIVE.value
            user.is_active = True
        self.db.flush()
        self.events.record(
            AuthEventType.ACCOUNT_UNLOCKED,
            auth_method=AuthMethod.PASSWORD,
            identity_type=AuthIdentityType.HUMAN_USER.value,
            organization_id=lock.organization_id,
            identity_id=lock.user_id,
            metadata={"lock_id": str(lock.id), "actor_id": str(actor_id) if actor_id else None, "reason": reason},
        )
        return lock

    def expire_stale(self, *, limit: int = 500) -> int:
        count = 0
        for lock in self.repo.list_active_expired(_now(), limit=limit):
            lock.status = AccountLockStatus.EXPIRED.value
            count += 1
        return count

    @staticmethod
    def _retry_after(lock: AccountLock) -> int | None:
        if lock.expires_at is None:
            return None
        return max(0, int((_aware(lock.expires_at) - _now()).total_seconds()))
