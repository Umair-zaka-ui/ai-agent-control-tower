"""SessionLifecycleService — create, touch, expire, revoke (SRS §4, §5, §11, §12).

**The session is the source of truth; the JWT is disposable.** Everything that
decides whether a caller may act happens here.

Two kinds of fact live on a session:

- *recorded*: ``status``, ``revoked_at``, ``revoked_reason`` — someone did this.
- *derived*: idle/absolute expiry — the clock did this.

``assert_usable`` reconciles them on every read: if the clock has run out, the
session is materialised to ``EXPIRED`` (with the right reason) and persisted, so a
listing endpoint and the hot path can never disagree about whether a session is
alive.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.identity.auth.enums import AuthEventType, AuthMethod
from app.identity.auth.security_event_service import SecurityEventService
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.enums import SessionRevocationReason, SessionStatus
from app.identity.models.session import UserSession
from app.identity.repositories.session_repository import SessionRepository


@dataclass(frozen=True)
class SessionTimings:
    idle_expires_at: datetime
    absolute_expires_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    """Postgres returns tz-aware datetimes; SQLite (tests) may not. Normalise."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class SessionLifecycleService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = SessionRepository(db)
        # A timeout is a lifecycle event that nobody else observes: it happens
        # inside this service, on a request that is about to be rejected. If this
        # service does not record it, it is never audited (SRS §26).
        self.events = SecurityEventService(db)

    # ------------------------------------------------------------------ #
    # Timing (SRS §12)
    # ------------------------------------------------------------------ #
    @staticmethod
    def compute_timings(created_at: datetime, *, remember_me: bool = False) -> SessionTimings:
        """Idle timeout always applies. "Remember me" only extends the *absolute*
        ceiling — it must never let an abandoned session live forever."""
        absolute = (
            settings.SESSION_REMEMBER_ME_SECONDS
            if remember_me
            else settings.SESSION_ABSOLUTE_TIMEOUT_SECONDS
        )
        return SessionTimings(
            idle_expires_at=created_at + timedelta(seconds=settings.SESSION_IDLE_TIMEOUT_SECONDS),
            absolute_expires_at=created_at + timedelta(seconds=absolute),
        )

    # ------------------------------------------------------------------ #
    # Create (SRS §5)
    # ------------------------------------------------------------------ #
    def create(
        self,
        user_id: uuid.UUID,
        *,
        organization_id: uuid.UUID | None = None,
        device_id: uuid.UUID | None = None,
        device_name: str | None = None,
        device_type: str | None = None,
        browser: str | None = None,
        browser_version: str | None = None,
        operating_system: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        country: str | None = None,
        city: str | None = None,
        timezone_name: str | None = None,
        login_method: str | None = None,
        remember_me: bool = False,
        security_score: int = 100,
        is_trusted: bool = False,
    ) -> UserSession:
        now = _now()
        timings = self.compute_timings(now, remember_me=remember_me)
        session = UserSession(
            user_id=user_id,
            organization_id=organization_id,
            status=SessionStatus.ACTIVE.value,
            device_id=device_id,
            device_name=device_name,
            device_type=device_type,
            browser=browser,
            browser_version=browser_version,
            operating_system=operating_system,
            ip_address=ip_address,
            user_agent=user_agent,
            country=country,
            city=city,
            timezone=timezone_name,
            login_method=login_method,
            created_at=now,
            last_seen_at=now,
            last_activity_at=now,
            idle_expires_at=timings.idle_expires_at,
            absolute_expires_at=timings.absolute_expires_at,
            security_score=security_score,
            is_trusted=is_trusted,
            # One session owns exactly one refresh-token family (SRS §7).
            refresh_token_family_id=uuid.uuid4(),
        )
        return self.repo.add(session)

    # ------------------------------------------------------------------ #
    # Usability — the hot path (SRS §5, §28)
    # ------------------------------------------------------------------ #
    def evaluate(self, session: UserSession, *, now: datetime | None = None) -> SessionStatus:
        """Pure: what state is this session *really* in right now?

        Recorded terminal states win — a revoked session does not become "expired"
        just because time passed; the reason it died must survive.

        ``IDLE`` (SRS §4, §5) is the warning zone: the session is still usable, but
        it has seen no activity for long enough that expiry is imminent. It is a
        state you discover by *observing* a session, never by the session making a
        request — a request is, by definition, activity.
        """
        now = now or _now()
        current = SessionStatus(session.status)
        if current.is_terminal():
            return current
        if _aware(session.absolute_expires_at) <= now:
            return SessionStatus.EXPIRED
        if _aware(session.idle_expires_at) <= now:
            return SessionStatus.EXPIRED
        warning_at = _aware(session.idle_expires_at) - timedelta(
            seconds=settings.SESSION_IDLE_WARNING_SECONDS
        )
        if now >= warning_at:
            return SessionStatus.IDLE
        return current

    def _materialise(self, session: UserSession, now: datetime) -> SessionStatus:
        """Persist the derived state so a listing never contradicts the hot path."""
        state = self.evaluate(session, now=now)
        if state == SessionStatus.EXPIRED and not SessionStatus(session.status).is_terminal():
            reason = (
                SessionRevocationReason.ABSOLUTE_TIMEOUT
                if _aware(session.absolute_expires_at) <= now
                else SessionRevocationReason.IDLE_TIMEOUT
            )
            self._expire(session, reason, now)
        elif state == SessionStatus.IDLE and session.status == SessionStatus.ACTIVE.value:
            session.status = SessionStatus.IDLE.value
            self.db.flush()
        return state

    def assert_usable(self, session: UserSession, *, now: datetime | None = None) -> UserSession:
        """Raise unless the session may authenticate. Materialises timeouts.

        Called on **every** authenticated request, so it does no more than one
        indexed read (already done by the caller) plus, rarely, one UPDATE.
        """
        now = now or _now()
        current = SessionStatus(session.status)

        if current == SessionStatus.SUSPICIOUS:
            raise IdentityError(
                ErrorCode.SESSION_SUSPICIOUS,
                "This session was flagged as suspicious. Please sign in again.",
            )
        if current in (SessionStatus.REVOKED, SessionStatus.TERMINATED):
            raise IdentityError(ErrorCode.SESSION_REVOKED, "Session is no longer active.")

        # Absolute first: it is the stronger statement, and a session past both
        # deadlines should be reported as ABSOLUTE_TIMEOUT, not IDLE_TIMEOUT.
        #
        # The expiry is committed *before* raising. Otherwise the request's error
        # handler rolls the transaction back and the session stays "ACTIVE" in the
        # database — so the hot path and the session-listing endpoint would report
        # different truths, and the timeout would be re-derived on every request
        # instead of recorded once.
        if _aware(session.absolute_expires_at) <= now:
            self._expire(session, SessionRevocationReason.ABSOLUTE_TIMEOUT, now)
            self.db.commit()
            raise IdentityError(ErrorCode.SESSION_EXPIRED, "Session has reached its maximum age.")

        if _aware(session.idle_expires_at) <= now:
            self._expire(session, SessionRevocationReason.IDLE_TIMEOUT, now)
            self.db.commit()
            raise IdentityError(
                ErrorCode.SESSION_IDLE_TIMEOUT, "Session expired after a period of inactivity."
            )

        return session

    def _expire(
        self, session: UserSession, reason: SessionRevocationReason, now: datetime
    ) -> UserSession:
        """Materialise a timed-out session and audit it (SRS §26).

        Two events, deliberately: ``SESSION_TIMEOUT`` is the *cause* (which clock
        ran out) and ``SESSION_EXPIRED`` is the *effect* (the state it entered).
        An analyst filtering for expiries and one filtering for timeouts are asking
        different questions, and both must find this.
        """
        session.status = SessionStatus.EXPIRED.value
        session.revoked_at = now
        session.revoked_reason = reason.value
        self.db.flush()
        self._record_session_event(
            session, AuthEventType.SESSION_TIMEOUT, {"reason": reason.value}
        )
        self._record_session_event(
            session, AuthEventType.SESSION_EXPIRED, {"reason": reason.value}
        )
        return session

    def _record_session_event(
        self,
        session: UserSession,
        event: AuthEventType,
        metadata: dict | None = None,
    ) -> None:
        self.events.record(
            event,
            auth_method=AuthMethod.JWT,
            identity_type="HUMAN_USER",
            organization_id=session.organization_id,
            identity_id=session.user_id,
            ip_address=session.ip_address,
            metadata={"session_id": str(session.id), **(metadata or {})},
        )

    # ------------------------------------------------------------------ #
    # Activity (SRS §5)
    # ------------------------------------------------------------------ #
    def touch(self, session: UserSession, *, now: datetime | None = None) -> bool:
        """Record activity and slide the idle deadline forward.

        Returns whether anything was written. Writes are throttled to at most one
        per ``SESSION_ACTIVITY_WRITE_INTERVAL_SECONDS`` — otherwise a busy client
        would issue an UPDATE on the session row for every single request, which
        turns a read-mostly hot path into a write-mostly one and creates row-level
        contention across a user's concurrent requests.

        The idle deadline is still *evaluated* on every request; only the write is
        throttled. The cost is that the effective idle timeout may overshoot by up
        to the throttle interval, which is acceptable for a 30-minute timeout.
        """
        now = now or _now()
        last = session.last_activity_at
        if last is not None:
            elapsed = (now - _aware(last)).total_seconds()
            if elapsed < settings.SESSION_ACTIVITY_WRITE_INTERVAL_SECONDS:
                return False

        session.last_seen_at = now
        session.last_activity_at = now
        session.idle_expires_at = now + timedelta(seconds=settings.SESSION_IDLE_TIMEOUT_SECONDS)
        resumed = session.status == SessionStatus.IDLE.value
        if resumed:
            session.status = SessionStatus.ACTIVE.value
        self.db.flush()
        # Audit only the *state transition*, never the sliding deadline. Emitting
        # SESSION_UPDATED on every touch would write one security event per user
        # per minute forever and drown the stream it belongs to.
        if resumed:
            self._record_session_event(
                session, AuthEventType.SESSION_UPDATED, {"from": "IDLE", "to": "ACTIVE"}
            )
        return True

    def seconds_until_idle_expiry(self, session: UserSession, *, now: datetime | None = None) -> int:
        now = now or _now()
        return max(0, int((_aware(session.idle_expires_at) - now).total_seconds()))

    # ------------------------------------------------------------------ #
    # Revoke / terminate (SRS §20)
    # ------------------------------------------------------------------ #
    def revoke(
        self,
        session: UserSession,
        reason: SessionRevocationReason,
        *,
        status: SessionStatus = SessionStatus.REVOKED,
        now: datetime | None = None,
    ) -> UserSession:
        """Idempotent. Re-revoking keeps the *original* reason: the first cause of
        death is the interesting one."""
        now = now or _now()
        if session.revoked_at is not None:
            return session
        session.status = status.value
        session.revoked_at = now
        session.revoked_reason = reason.value
        self.db.flush()
        self._invalidate_decisions(session)
        return session

    @staticmethod
    def _invalidate_decisions(session: UserSession) -> None:
        """Phase 4.3.6 §19: a revoked session invalidates the identity's cached
        authorization decisions immediately. Imported lazily — identity must
        not import authorization at module scope."""
        from app.authorization.middleware.cache import DecisionCacheService

        if session.user_id is not None:
            DecisionCacheService.invalidate_identity(session.user_id)

    def mark_suspicious(
        self, session: UserSession, reason: SessionRevocationReason, *, now: datetime | None = None
    ) -> UserSession:
        """A security signal (e.g. token reuse). Blocks the session and records why."""
        now = now or _now()
        session.status = SessionStatus.SUSPICIOUS.value
        session.security_score = 0
        if session.revoked_at is None:
            session.revoked_at = now
            session.revoked_reason = reason.value
        self.db.flush()
        self._invalidate_decisions(session)
        return session

    # ------------------------------------------------------------------ #
    # Concurrency limit (SRS §11)
    # ------------------------------------------------------------------ #
    def enforce_session_limit(self, user_id: uuid.UUID) -> list[UserSession]:
        """Revoke the oldest sessions until the user is within the limit.

        Called *before* creating the new session, so the limit is the number of
        sessions a user ends up with, not the number they had.
        """
        revoked: list[UserSession] = []
        limit = settings.SESSION_MAX_CONCURRENT
        if limit <= 0:
            return revoked
        # Leave room for the session about to be created.
        while self.repo.count_active_for_user(user_id) >= limit:
            oldest = self.repo.oldest_active_for_user(user_id)
            if oldest is None:  # pragma: no cover - defensive
                break
            self.revoke(oldest, SessionRevocationReason.SESSION_LIMIT_EXCEEDED)
            revoked.append(oldest)
        return revoked

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    def list_active(self, user_id: uuid.UUID) -> list[UserSession]:
        """Usable sessions, with timed-out ones materialised out of the list and
        idle ones marked as such."""
        now = _now()
        live: list[UserSession] = []
        for session in self.repo.list_active_for_user(user_id):
            if self._materialise(session, now) == SessionStatus.EXPIRED:
                continue
            live.append(session)
        return live

    def get_for_user(self, user_id: uuid.UUID, session_id: uuid.UUID) -> UserSession | None:
        """Scoped lookup — never confirm the existence of another user's session."""
        session = self.repo.get(session_id)
        if session is None or session.user_id != user_id:
            return None
        return session

    def reap_expired(self, *, limit: int = 500) -> int:
        """Materialise timed-out sessions in bulk. Safe to run from a cron/worker;
        ``assert_usable`` already handles them lazily on access. Returns the count
        of sessions expired."""
        now = _now()
        count = 0
        for session in self.repo.list_expired(now, limit=limit):
            if self._materialise(session, now) == SessionStatus.EXPIRED:
                count += 1
        return count
