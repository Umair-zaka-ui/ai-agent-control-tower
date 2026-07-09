"""Risk scoring, anomaly detection and brute-force detection (4.2.2.3.4 §9–§15).

These are pure-ish analysers: they read history and the current attempt and return
*signals* and a *score*. They never decide the outcome — that is the rules engine and
the coordinator. Keeping detection separate from decision means the weights can be
tuned and the signals audited without touching the enforcement path.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.identity.protection.enums import RiskLevel
from app.identity.protection.repositories import LoginAttemptQuery
from app.models.user import User


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


# Risk weights (§15). Kept as data so scoring is transparent and testable.
RISK_WEIGHTS: dict[str, int] = {
    "new_device": 20,
    "new_country": 30,
    "impossible_travel": 40,
    "failed_attempts_gt_3": 20,
    "failed_attempts_gt_5": 40,
    "blocked_ip": 80,
    "suspicious_user_agent": 25,
    "recent_password_reset": 10,
    "account_newly_created": 10,
    "old_inactive_account": 20,
}


@dataclass
class LoginSignals:
    """Everything observed about one login attempt (§11), plus the derived anomaly
    flags (§12). Serialised onto the risk event so an analyst sees the evidence."""

    ip_address: str | None = None
    user_agent: str | None = None
    device_fingerprint: str | None = None
    country: str | None = None
    city: str | None = None
    failed_attempts: int = 0
    # Anomaly flags (§12, §13).
    flags: dict[str, bool] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "ip_address": self.ip_address,
            "country": self.country,
            "city": self.city,
            "failed_attempts": self.failed_attempts,
            **{k: v for k, v in self.flags.items() if v},
        }


class LoginAnomalyService:
    """Derives the anomaly flags for an attempt (§12, §13)."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.attempts = LoginAttemptQuery(db)

    def collect(
        self,
        *,
        email: str,
        ip_address: str | None,
        user_agent: str | None,
        device_fingerprint: str | None,
        country: str | None,
        city: str | None,
        user: User | None,
        is_new_device: bool,
        ip_blocked: bool = False,
    ) -> LoginSignals:
        window = timedelta(seconds=settings.PROTECTION_LOCKOUT_WINDOW_SECONDS)
        failed = self.attempts.failures_for_email(email, _now() - window)
        signals = LoginSignals(
            ip_address=ip_address,
            user_agent=user_agent,
            device_fingerprint=device_fingerprint,
            country=country,
            city=city,
            failed_attempts=failed,
        )
        flags = signals.flags

        # "New" is only meaningful against a baseline. On a user's first-ever
        # successful login every device and country is new by definition, so scoring
        # those as risky would flag every new account and train operators to ignore
        # the signal. The same discipline as SessionSecurityService.assess_login.
        has_baseline = user is not None and self.attempts.last_success(email) is not None

        flags["suspicious_user_agent"] = self._suspicious_ua(user_agent)
        flags["failed_attempts_gt_3"] = failed > 3
        flags["failed_attempts_gt_5"] = failed > 5
        flags["blocked_ip"] = ip_blocked

        if user is not None:
            flags["recent_password_reset"] = self._recent_password_reset(user.id)
            flags["account_newly_created"] = self._account_new(user)
        if has_baseline:
            flags["new_device"] = bool(is_new_device)
            flags["new_country"] = self._new_country(email, country)
            flags["impossible_travel"] = self._impossible_travel(email, country)
            flags["old_inactive_account"] = self._account_stale(email)
        return signals

    # --- individual detectors ---------------------------------------- #
    @staticmethod
    def _suspicious_ua(user_agent: str | None) -> bool:
        if not user_agent or len(user_agent) < 8:
            return True
        lowered = user_agent.lower()
        return any(bot in lowered for bot in ("curl", "python-requests", "wget", "scrapy", "httpclient"))

    def _new_country(self, email: str, country: str | None) -> bool:
        if not country:
            return False
        last = self.attempts.last_success(email)
        # On the first-ever success there is no baseline, so nothing is "new".
        return last is not None and (last.country or "") != country

    def _impossible_travel(self, email: str, country: str | None) -> bool:
        """§13 simple model: a different country from the last success within 2 hours."""
        if not country:
            return False
        last = self.attempts.last_success(email)
        if last is None or not last.country or last.country == country:
            return False
        elapsed = _now() - _aware(last.created_at)
        return elapsed < timedelta(seconds=settings.PROTECTION_IMPOSSIBLE_TRAVEL_SECONDS)

    def _recent_password_reset(self, user_id: uuid.UUID) -> bool:
        from app.identity.models.recovery import PasswordResetRequest
        from sqlalchemy import select

        since = _now() - timedelta(hours=24)
        stmt = (
            select(PasswordResetRequest.id)
            .where(PasswordResetRequest.user_id == user_id, PasswordResetRequest.created_at >= since)
            .limit(1)
        )
        return self.db.execute(stmt).scalars().first() is not None

    @staticmethod
    def _account_new(user: User) -> bool:
        created = getattr(user, "created_at", None)
        return bool(created and _now() - _aware(created) < timedelta(days=1))

    def _account_stale(self, email: str) -> bool:
        last = self.attempts.last_success(email)
        return bool(last and _now() - _aware(last.created_at) > timedelta(days=90))


class RiskScoringService:
    """Turns anomaly flags into a 0–100 score and a level (§14, §15). Pure function of
    its input; <50ms and side-effect free."""

    @staticmethod
    def score(signals: LoginSignals) -> tuple[int, RiskLevel]:
        total = sum(RISK_WEIGHTS[flag] for flag, on in signals.flags.items() if on and flag in RISK_WEIGHTS)
        total = max(0, min(100, total))  # cap (§15)
        return total, RiskLevel.for_score(total)


@dataclass
class BruteForcePattern:
    kind: str          # "account_attack" | "ip_brute_force" | "credential_stuffing"
    detail: dict


class BruteForceDetectionService:
    """Detects attack patterns from login-attempt history (§9)."""

    def __init__(self, db: Session) -> None:
        self.attempts = LoginAttemptQuery(db)
        self.window = timedelta(seconds=settings.PROTECTION_LOCKOUT_WINDOW_SECONDS)

    def detect(self, *, email: str, ip_address: str | None) -> list[BruteForcePattern]:
        patterns: list[BruteForcePattern] = []
        since = _now() - self.window

        account_failures = self.attempts.failures_for_email(email, since)
        if account_failures >= settings.PROTECTION_FAILED_THRESHOLD:
            patterns.append(BruteForcePattern("account_attack", {"email": email, "failures": account_failures}))

        if ip_address:
            ip_failures = self.attempts.failures_from_ip(ip_address, since)
            if ip_failures >= settings.PROTECTION_BRUTEFORCE_IP_THRESHOLD:
                patterns.append(BruteForcePattern("ip_brute_force", {"ip": ip_address, "failures": ip_failures}))

            distinct_accounts = self.attempts.distinct_accounts_failed_from_ip(ip_address, since)
            if distinct_accounts >= settings.PROTECTION_STUFFING_DISTINCT_ACCOUNTS:
                patterns.append(
                    BruteForcePattern("credential_stuffing", {"ip": ip_address, "accounts": distinct_accounts})
                )
        return patterns
