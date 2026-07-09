"""Account-protection enumerations (4.2.2.3.4 §7, §8, §14)."""

from __future__ import annotations

import enum


class AuthDecision(str, enum.Enum):
    """The verdict the protection layer returns for a login attempt (§7).

    ``ALLOW`` issues tokens; everything else stops the normal flow. The mapping to
    HTTP happens at the login route.
    """

    ALLOW = "ALLOW"
    DENY = "DENY"
    CHALLENGE = "CHALLENGE"
    LOCK_ACCOUNT = "LOCK_ACCOUNT"
    BLOCK_IP = "BLOCK_IP"
    REQUIRE_PASSWORD_RESET = "REQUIRE_PASSWORD_RESET"
    REQUIRE_MFA = "REQUIRE_MFA"
    REQUIRE_SECURITY_REVIEW = "REQUIRE_SECURITY_REVIEW"


class RiskLevel(str, enum.Enum):
    """0–100 risk score bucketed into levels (§14)."""

    LOW = "LOW"           # 0–20   → allow
    MEDIUM = "MEDIUM"     # 21–50  → allow + log
    HIGH = "HIGH"         # 51–75  → challenge
    CRITICAL = "CRITICAL" # 76–90  → lock or MFA
    SEVERE = "SEVERE"     # 91–100 → block + security review

    @classmethod
    def for_score(cls, score: int) -> "RiskLevel":
        if score <= 20:
            return cls.LOW
        if score <= 50:
            return cls.MEDIUM
        if score <= 75:
            return cls.HIGH
        if score <= 90:
            return cls.CRITICAL
        return cls.SEVERE


class AccountLockStatus(str, enum.Enum):
    """Lifecycle of an ``account_locks`` row (§17).

    ``EXPIRED`` is *derived* (the clock ran out); ``MANUALLY_UNLOCKED``/``ESCALATED``
    are *recorded* facts. Recorded facts win — an escalated lock does not silently
    "expire".
    """

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    MANUALLY_UNLOCKED = "MANUALLY_UNLOCKED"
    ESCALATED = "ESCALATED"


class AccountLockReason(str, enum.Enum):
    """Why an account is locked (§8)."""

    FAILED_LOGIN_THRESHOLD = "FAILED_LOGIN_THRESHOLD"
    BRUTE_FORCE_DETECTED = "BRUTE_FORCE_DETECTED"
    CREDENTIAL_STUFFING_SUSPECTED = "CREDENTIAL_STUFFING_SUSPECTED"
    ADMIN_LOCKED = "ADMIN_LOCKED"
    SECURITY_POLICY = "SECURITY_POLICY"
    TOKEN_REUSE = "TOKEN_REUSE"
    SUSPICIOUS_ACTIVITY = "SUSPICIOUS_ACTIVITY"
