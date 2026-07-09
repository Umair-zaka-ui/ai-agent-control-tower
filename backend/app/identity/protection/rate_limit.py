"""Adaptive rate limiting for the login endpoint (4.2.2.3.4 §10).

The base per-IP limit tightens as an IP looks more like an attacker: an address with
many recent failed logins is throttled harder than a clean one. This is the concrete
wiring of ``AdaptiveRateLimitService`` onto the live limiter — the login endpoint had
no limiter before this part; the base is §10's 5/min/IP.

Risk is derived *before* the password from a cheap read (recent failures from this IP),
because the rate-limit decision must happen before any credential work.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.identity.errors import ErrorCode, IdentityError
from app.identity.protection.enums import RiskLevel
from app.identity.protection.policy import AdaptiveRateLimitService
from app.identity.protection.repositories import LoginAttemptQuery
from app.identity.ratelimit.limiter import RateLimiter, client_ip


def _risk_level_from_failures(failures: int) -> RiskLevel:
    """A pre-password risk proxy from recent failures by this IP.

    Deliberately coarse: it only needs to pick a rate-limit tier, not to score a login.
    The full risk model runs after the password succeeds.
    """
    if failures >= settings.PROTECTION_BRUTEFORCE_IP_THRESHOLD:
        return RiskLevel.SEVERE          # −80%
    if failures >= settings.PROTECTION_FAILED_THRESHOLD:
        return RiskLevel.HIGH            # −50%
    return RiskLevel.LOW                 # base


def adaptive_login_rate_limit(request: Request, db: Session = Depends(get_db)) -> None:
    """FastAPI dependency: throttle ``/login`` by IP, tightening under risk (§10)."""
    if not settings.RATE_LIMIT_ENABLED:
        return

    ip = client_ip(request)
    window = settings.PROTECTION_LOCKOUT_WINDOW_SECONDS
    since = datetime.now(timezone.utc) - timedelta(seconds=window)
    failures = LoginAttemptQuery(db).failures_from_ip(ip, since)

    base = settings.RATE_LIMIT_DEFAULT_REQUESTS
    level = _risk_level_from_failures(failures)
    effective_limit = AdaptiveRateLimitService.adjusted_limit(base, level)

    decision = RateLimiter(db).check(
        f"login:{ip}",
        limit=effective_limit,
        window_seconds=settings.RATE_LIMIT_DEFAULT_WINDOW_SECONDS,
    )
    if not decision.allowed:
        # Generic message (§33): never reveal that the tightening is risk-driven.
        raise IdentityError(
            ErrorCode.TOO_MANY_ATTEMPTS,
            f"Too many sign-in attempts. Try again in {decision.retry_after_seconds} seconds.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )
