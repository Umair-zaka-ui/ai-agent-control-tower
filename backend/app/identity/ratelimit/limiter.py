"""Rate limiting for public endpoints (4.2.2.3.1 §19).

Public onboarding endpoints are the platform's only unauthenticated write surface,
which makes them the natural target for enumeration and mail-bombing. §19 asks for
5 requests / minute / IP.

**Why Postgres and not an in-process counter.** An in-memory limiter resets on every
deploy and is silently wrong the moment a second replica exists — it would report
"protected" while allowing N× the limit. Redis is the obvious home, but
[ADR-0002](../../../docs/architecture/adr/0002-postgresql-as-sole-datastore.md)
makes PostgreSQL the sole datastore, and 5 req/min over a handful of endpoints is
nowhere near a workload that justifies a second one. Revisit at
[ADR-0002's stated trigger](../../../docs/architecture/adr/0002-postgresql-as-sole-datastore.md).

**Known limitation, stated plainly.** This is a *fixed window*, not a sliding one:
a caller can make 5 requests at the end of one window and 5 at the start of the next,
i.e. 10 in a two-second span. For an anti-abuse control on registration that is
acceptable; for anything protecting a credential it would not be. The account
lockout in 4.2.2.1 is what actually protects the password, and it is a genuine
sliding window.

The limiter is **fail-closed on nothing**: if the database is unreachable the request
would already be failing for other reasons, so no special case is warranted here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.registration import RateLimitHit


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    hits: int
    limit: int
    retry_after_seconds: int


def client_ip(request: Request) -> str:
    """The caller's address.

    ``X-Forwarded-For`` is honoured **only** when the deployment declares it is
    behind a trusted proxy. Trusting it unconditionally would let any caller spoof
    their bucket by setting a header, which turns the rate limiter into decoration.
    No such proxy exists in the current deployment; see deployment gap 2.
    """
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Fixed-window counter over ``rate_limit_hits``."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def check(self, bucket: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        """Count hits in the window, record this one, and decide.

        The hit is recorded **before** the decision so a rejected request still
        counts against the caller. Otherwise a client that keeps hammering after a
        429 would silently reset its own window as old hits age out.

        Each check also **prunes its own bucket** of hits the window can no longer see.
        Without that, the table grows forever — one row per public request, and (by the
        rule above) one per *rejected* request too. The anti-abuse table would be an
        unbounded insert under exactly the flood it exists to stop. The work is bounded
        to one bucket, and the steady state is roughly ``active buckets × limit`` rows.
        """
        now = datetime.now(timezone.utc)
        since = now - timedelta(seconds=window_seconds)

        # Prune first: a stale row must neither be counted nor survive.
        self.db.execute(
            delete(RateLimitHit).where(
                RateLimitHit.bucket == bucket, RateLimitHit.created_at < since
            )
        )

        hits = int(
            self.db.execute(
                select(func.count())
                .select_from(RateLimitHit)
                .where(RateLimitHit.bucket == bucket, RateLimitHit.created_at >= since)
            ).scalar()
            or 0
        )

        self.db.add(RateLimitHit(bucket=bucket, created_at=now))

        # Pruning this bucket is not enough: a caller who rotates IP addresses creates a
        # bucket per address and never returns, so those rows would live for ever. Reap a
        # bounded batch of globally stale rows on the way past. Bounded work per request,
        # no cron required, and nothing on the hot path depends on it succeeding.
        self._sweep_batch(cutoff=since, limit=settings.RATE_LIMIT_SWEEP_BATCH)
        self.db.commit()

        if hits >= limit:
            return RateLimitDecision(False, hits, limit, window_seconds)
        return RateLimitDecision(True, hits + 1, limit, window_seconds)

    def _sweep_batch(self, *, cutoff: datetime, limit: int) -> int:
        """Delete at most ``limit`` rows older than ``cutoff``, across all buckets.

        ``ctid``-keyed so Postgres does a bounded scan-and-delete rather than locking the
        whole table. Does not commit — the caller's transaction carries it.
        """
        if limit <= 0:
            return 0
        result = self.db.execute(
            delete(RateLimitHit).where(
                RateLimitHit.id.in_(
                    select(RateLimitHit.id).where(RateLimitHit.created_at < cutoff).limit(limit)
                )
            )
        )
        return int(result.rowcount or 0)

    def sweep(self, *, older_than_seconds: int = 3600) -> int:
        """Unbounded global cleanup, for a cron or a maintenance task.

        ``check`` already prunes its own bucket and reaps a bounded batch of stale rows
        on every request, so this exists for operators who want the table empty *now*
        rather than eventually.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
        result = self.db.execute(delete(RateLimitHit).where(RateLimitHit.created_at < cutoff))
        self.db.commit()
        return int(result.rowcount or 0)


def rate_limit(
    name: str,
    *,
    limit: int | None = None,
    window_seconds: int | None = None,
):
    """FastAPI dependency factory: throttle a public endpoint by client IP.

    Usage::

        @router.post("/register", dependencies=[Depends(rate_limit("register"))])

    Raises ``RATE_LIMIT_EXCEEDED`` (HTTP 429) with a ``Retry-After`` header.
    """

    effective_limit = limit or settings.RATE_LIMIT_DEFAULT_REQUESTS
    effective_window = window_seconds or settings.RATE_LIMIT_DEFAULT_WINDOW_SECONDS

    def _dependency(request: Request, db: Session = Depends(get_db)) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        bucket = f"{name}:{client_ip(request)}"
        decision = RateLimiter(db).check(
            bucket, limit=effective_limit, window_seconds=effective_window
        )
        if not decision.allowed:
            raise IdentityError(
                ErrorCode.RATE_LIMIT_EXCEEDED,
                f"Too many requests. Try again in {decision.retry_after_seconds} seconds.",
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )

    return _dependency
