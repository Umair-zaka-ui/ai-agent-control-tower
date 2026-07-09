"""Enterprise account protection & risk-based authentication (Phase 4 Part 4.2.2.3.4).

Authentication is no longer binary. Around the existing password check the platform
now evaluates risk, detects abuse, locks accounts progressively, blocks IPs, runs
admin protection rules, and records a complete audit trail — while never revealing to
an attacker *why* a login was refused.
"""

from app.identity.protection.detection import (
    BruteForceDetectionService,
    LoginAnomalyService,
    LoginSignals,
    RiskScoringService,
)
from app.identity.protection.enums import (
    AccountLockReason,
    AccountLockStatus,
    AuthDecision,
    RiskLevel,
)
from app.identity.protection.lockout import AccountLockoutService
from app.identity.protection.policy import (
    AdaptiveRateLimitService,
    BlockedIpService,
    CaptchaService,
    IdentityProtectionRuleService,
)
from app.identity.protection.service import AccountProtectionService, ProtectionOutcome

__all__ = [
    "AccountProtectionService",
    "ProtectionOutcome",
    "AccountLockoutService",
    "BlockedIpService",
    "CaptchaService",
    "IdentityProtectionRuleService",
    "AdaptiveRateLimitService",
    "RiskScoringService",
    "LoginAnomalyService",
    "BruteForceDetectionService",
    "LoginSignals",
    "AuthDecision",
    "RiskLevel",
    "AccountLockReason",
    "AccountLockStatus",
]
