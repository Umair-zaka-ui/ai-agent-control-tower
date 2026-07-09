"""PasswordPolicyService — validation, strength, expiration (SRS §5, §8, §11, §19).

A stable facade over the single-source policy in
:mod:`app.identity.security.passwords` (ADR-0004), plus the time-based rules
(expiration, minimum age, warning windows) that read from settings. Defining the
policy here instead would fork it away from the registration/login paths that
already import the security module; this class only *composes* it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.identity.security import passwords as policy
from app.models.user import User


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class PasswordPolicyService:
    """Stateless. The complexity gate lives in the security module; this adds the
    lifecycle rules and the read-only projections the API and UI need."""

    # ------------------------------- complexity ------------------------------ #
    @staticmethod
    def validate(password: str, *, user: User | None = None, **identity: str | None) -> None:
        """Enforce complexity (SRS §7, §9). Raises ``PasswordPolicyError``.

        When a ``user`` is given, its email/name/organization are fed to the policy
        so the password cannot contain them (§7)."""
        ctx = dict(identity)
        if user is not None:
            ctx.setdefault("email", user.email)
            ctx.setdefault("name", user.name)
        policy.validate_password(password, **ctx)

    @staticmethod
    def strength(password: str, *, user: User | None = None, **identity: str | None) -> dict[str, object]:
        ctx = dict(identity)
        if user is not None:
            ctx.setdefault("email", user.email)
            ctx.setdefault("name", user.name)
        return policy.estimate_strength(password, **ctx)

    @staticmethod
    def describe() -> dict[str, object]:
        """The active policy as data (SRS §5), for ``GET /password-policy``."""
        data = policy.policy_description()
        data.update(
            {
                "history_depth": settings.PASSWORD_HISTORY_DEPTH,
                "max_age_days": settings.PASSWORD_MAX_AGE_DAYS,
                "min_age_hours": settings.PASSWORD_MIN_AGE_HOURS,
                "expiry_warning_days": list(settings.PASSWORD_EXPIRY_WARNING_DAYS),
                "temp_password_ttl_hours": settings.TEMP_PASSWORD_TTL_HOURS,
            }
        )
        return data

    # ------------------------------- expiration ------------------------------ #
    @staticmethod
    def expires_at_from(changed_at: datetime) -> datetime | None:
        """The deadline for a password set at ``changed_at``; ``None`` if disabled."""
        if settings.PASSWORD_MAX_AGE_DAYS <= 0:
            return None
        return _aware(changed_at) + timedelta(days=settings.PASSWORD_MAX_AGE_DAYS)

    @staticmethod
    def is_expired(user: User, *, at: datetime | None = None) -> bool:
        if user.password_expires_at is None:
            return False
        return (at or _now()) >= _aware(user.password_expires_at)

    @staticmethod
    def days_until_expiry(user: User, *, at: datetime | None = None) -> int | None:
        if user.password_expires_at is None:
            return None
        seconds = (_aware(user.password_expires_at) - (at or _now())).total_seconds()
        if seconds <= 0:
            return 0
        # Round up: with hours left it should read "1 day", not "0 days" (expired).
        import math

        return math.ceil(seconds / 86400)

    @classmethod
    def is_in_warning_window(cls, user: User, *, at: datetime | None = None) -> bool:
        days = cls.days_until_expiry(user, at=at)
        if days is None:
            return False
        warn_from = max(settings.PASSWORD_EXPIRY_WARNING_DAYS)
        return 0 < days <= warn_from

    @staticmethod
    def min_age_ok(user: User, *, at: datetime | None = None) -> bool:
        """False if the password was changed too recently to change again (SRS §6).

        A password that has never been changed, or a temporary one flagged
        ``must_change_password``, is always changeable — the min-age rule exists to
        stop cycling through history, not to trap a user with a temp password."""
        if user.must_change_password or user.password_changed_at is None:
            return True
        if settings.PASSWORD_MIN_AGE_HOURS <= 0:
            return True
        earliest = _aware(user.password_changed_at) + timedelta(hours=settings.PASSWORD_MIN_AGE_HOURS)
        return (at or _now()) >= earliest

    @classmethod
    def change_required(cls, user: User) -> bool:
        """Must this user change their password before using the app (SRS §11, §13)?"""
        return bool(user.must_change_password) or cls.is_expired(user)

    @classmethod
    def expiration_status(cls, user: User) -> dict[str, object]:
        """Read-only projection for ``GET /password-expiration`` and the dashboard."""
        return {
            "expires_at": user.password_expires_at.isoformat() if user.password_expires_at else None,
            "changed_at": user.password_changed_at.isoformat() if user.password_changed_at else None,
            "days_until_expiry": cls.days_until_expiry(user),
            "is_expired": cls.is_expired(user),
            "in_warning_window": cls.is_in_warning_window(user),
            "must_change": bool(user.must_change_password),
            "change_required": cls.change_required(user),
        }
