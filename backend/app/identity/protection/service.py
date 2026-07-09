"""AccountProtectionService — coordinates protection during login (§6, §19, §21).

Three hooks the login flow calls:

- ``pre_check`` — *before* the password. Cheap gates that reject at the door: a
  blocked IP, an active account lock, an account parked for security review.
- ``evaluate_login_attempt`` — *after* a correct password. Scores risk, runs the
  rules engine, and returns ALLOW / CHALLENGE / REQUIRE_MFA / BLOCK / SECURITY_REVIEW.
- ``record_failure`` — after a *wrong* password. Counts failures, detects brute-force /
  credential-stuffing patterns, and locks the account when the threshold is crossed.

Every scored attempt is written to ``identity_risk_events`` and (via the coordinator's
callers) to ``login_history`` with its risk fields. Nothing here reveals *why* a login
was refused to the caller — the login route always returns a generic message (§33).
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
from app.identity.models.protection import AccountLock, IdentityRiskEvent
from app.identity.protection.alerts import SecurityAlertService
from app.identity.protection.detection import (
    BruteForceDetectionService,
    LoginAnomalyService,
    LoginSignals,
    RiskScoringService,
)
from app.identity.protection.enums import AccountLockReason, AuthDecision, RiskLevel
from app.identity.protection.lockout import AccountLockoutService
from app.identity.protection.policy import (
    BlockedIpService,
    CaptchaService,
    IdentityProtectionRuleService,
)
from app.models.user import User


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ProtectionOutcome:
    decision: AuthDecision
    risk_score: int = 0
    risk_level: RiskLevel = RiskLevel.LOW
    signals: LoginSignals | None = None
    reason: str | None = None
    retry_after_seconds: int | None = None
    captcha_required: bool = False

    @property
    def allowed(self) -> bool:
        return self.decision is AuthDecision.ALLOW


class AccountProtectionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.locks = AccountLockoutService(db)
        self.blocked_ips = BlockedIpService(db)
        self.anomaly = LoginAnomalyService(db)
        self.scoring = RiskScoringService()
        self.brute = BruteForceDetectionService(db)
        self.rules = IdentityProtectionRuleService(db)
        self.captcha = CaptchaService()
        self.alerts = SecurityAlertService(db)
        self.events = SecurityEventService(db)

    # ------------------------------------------------------------------ #
    # Pre-check (before password)
    # ------------------------------------------------------------------ #
    def pre_check(
        self,
        *,
        email: str,
        ip_address: str | None,
        user_agent: str | None,
        user: User | None,
        organization_id: uuid.UUID | None,
    ) -> ProtectionOutcome | None:
        if not settings.ACCOUNT_PROTECTION_ENABLED:
            return None

        if self.blocked_ips.is_blocked(ip_address, organization_id=organization_id):
            self._record_risk(
                user, organization_id, AuthEventType.IP_BLOCKED, 100, RiskLevel.SEVERE,
                LoginSignals(ip_address=ip_address, flags={"blocked_ip": True}),
                AuthDecision.BLOCK_IP, ip_address, user_agent,
            )
            return ProtectionOutcome(AuthDecision.BLOCK_IP, 100, RiskLevel.SEVERE, reason="ip_blocked")

        if user is not None:
            lock = self.locks.active_lock(user.id)
            if lock is not None:
                return ProtectionOutcome(
                    AuthDecision.LOCK_ACCOUNT,
                    reason="account_locked",
                    retry_after_seconds=self._retry_after(lock),
                )
            if user.status == IdentityStatus.SECURITY_REVIEW_REQUIRED.value:
                return ProtectionOutcome(AuthDecision.REQUIRE_SECURITY_REVIEW, reason="security_review")
        return None

    # ------------------------------------------------------------------ #
    # Evaluate (after correct password)
    # ------------------------------------------------------------------ #
    def evaluate_login_attempt(
        self,
        user: User,
        *,
        email: str,
        ip_address: str | None,
        user_agent: str | None,
        device_fingerprint: str | None,
        country: str | None,
        city: str | None,
        is_new_device: bool,
    ) -> ProtectionOutcome:
        organization_id = user.organization_id
        ip_blocked = self.blocked_ips.is_blocked(ip_address, organization_id=organization_id)
        signals = self.anomaly.collect(
            email=email,
            ip_address=ip_address,
            user_agent=user_agent,
            device_fingerprint=device_fingerprint,
            country=country,
            city=city,
            user=user,
            is_new_device=is_new_device,
            ip_blocked=ip_blocked,
        )
        score, level = self.scoring.score(signals)

        # Threshold-driven baseline decision (§14).
        decision = AuthDecision.ALLOW
        if score >= settings.PROTECTION_RISK_BLOCK_AT:
            decision = AuthDecision.REQUIRE_SECURITY_REVIEW
        elif score >= settings.PROTECTION_RISK_LOCK_AT:
            decision = AuthDecision.REQUIRE_MFA
        elif score >= settings.PROTECTION_RISK_CHALLENGE_AT:
            decision = AuthDecision.CHALLENGE

        # Admin rules override the baseline (§16). A rule can only make it *stricter*
        # or explicitly ALLOW; the highest-priority match wins.
        rule_match = self.rules.evaluate(organization_id, risk_score=score, risk_level=level, signals=signals)
        if rule_match is not None:
            decision = rule_match[0]

        captcha_required = self.captcha.should_challenge(signals, score)

        self._record_risk(
            user, organization_id, AuthEventType.RISK_LOGIN_DETECTED, score, level, signals,
            decision, ip_address, user_agent,
        )
        if decision is not AuthDecision.ALLOW or level in (RiskLevel.HIGH, RiskLevel.CRITICAL, RiskLevel.SEVERE):
            self.events.record(
                AuthEventType.RISK_LOGIN_DETECTED,
                auth_method=AuthMethod.PASSWORD,
                identity_type=AuthIdentityType.HUMAN_USER.value,
                organization_id=organization_id,
                identity_id=user.id,
                ip_address=ip_address,
                metadata={"risk_score": score, "risk_level": level.value, "decision": decision.value},
            )
        if decision in (AuthDecision.CHALLENGE, AuthDecision.REQUIRE_MFA):
            self.events.record(
                AuthEventType.LOGIN_CHALLENGE_REQUIRED,
                auth_method=AuthMethod.PASSWORD,
                identity_type=AuthIdentityType.HUMAN_USER.value,
                organization_id=organization_id,
                identity_id=user.id,
                ip_address=ip_address,
                metadata={"risk_score": score, "decision": decision.value},
            )
            self.alerts.high_risk_login(user, risk_level=level.value)
        if decision in (AuthDecision.BLOCK_IP, AuthDecision.DENY, AuthDecision.REQUIRE_SECURITY_REVIEW):
            self.alerts.suspicious_login_blocked(user)
        if captcha_required:
            self.events.record(
                AuthEventType.CAPTCHA_REQUIRED,
                auth_method=AuthMethod.PASSWORD,
                identity_type=AuthIdentityType.HUMAN_USER.value,
                organization_id=organization_id,
                identity_id=user.id,
                ip_address=ip_address,
                metadata={"risk_score": score},
            )

        return ProtectionOutcome(decision, score, level, signals, captcha_required=captcha_required)

    # ------------------------------------------------------------------ #
    # Record a failed password (after wrong password)
    # ------------------------------------------------------------------ #
    def record_failure(
        self,
        *,
        email: str,
        ip_address: str | None,
        user_agent: str | None,
        user: User | None,
        organization_id: uuid.UUID | None,
    ) -> ProtectionOutcome:
        """Count failures, detect attack patterns, lock at the threshold. Returns the
        outcome; the login route still surfaces a generic INVALID_CREDENTIALS for the
        failing attempt — the lock bites on the *next* attempt (§33)."""
        patterns = self.brute.detect(email=email, ip_address=ip_address)
        for pattern in patterns:
            if pattern.kind == "credential_stuffing":
                self.events.record(
                    AuthEventType.CREDENTIAL_STUFFING_DETECTED,
                    auth_method=AuthMethod.PASSWORD,
                    identity_type=AuthIdentityType.SYSTEM.value,
                    organization_id=organization_id,
                    ip_address=ip_address,
                    metadata=pattern.detail,
                )
            elif pattern.kind in ("ip_brute_force", "account_attack"):
                self.events.record(
                    AuthEventType.BRUTE_FORCE_DETECTED,
                    auth_method=AuthMethod.PASSWORD,
                    identity_type=AuthIdentityType.SYSTEM.value,
                    organization_id=organization_id,
                    ip_address=ip_address,
                    metadata=pattern.detail,
                )

        if user is None:
            return ProtectionOutcome(AuthDecision.DENY, reason="invalid_credentials")

        window = timedelta(seconds=settings.PROTECTION_LOCKOUT_WINDOW_SECONDS)
        from app.identity.protection.repositories import LoginAttemptQuery

        failures = LoginAttemptQuery(self.db).failures_for_email(email, _now() - window)
        if failures >= settings.PROTECTION_FAILED_THRESHOLD:
            reason = (
                AccountLockReason.CREDENTIAL_STUFFING_SUSPECTED
                if any(p.kind == "credential_stuffing" for p in patterns)
                else (
                    AccountLockReason.BRUTE_FORCE_DETECTED
                    if any(p.kind in ("ip_brute_force", "account_attack") for p in patterns)
                    else AccountLockReason.FAILED_LOGIN_THRESHOLD
                )
            )
            result = self.locks.lock(
                user, reason=reason, ip_address=ip_address, metadata={"failures": failures}
            )
            self.alerts.account_locked(
                user, escalated=result.escalated, retry_after_seconds=result.retry_after_seconds
            )
            return ProtectionOutcome(
                AuthDecision.LOCK_ACCOUNT,
                reason=reason.value,
                retry_after_seconds=result.retry_after_seconds,
            )
        return ProtectionOutcome(AuthDecision.DENY, reason="invalid_credentials")

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    def _record_risk(
        self,
        user: User | None,
        organization_id: uuid.UUID | None,
        event_type: AuthEventType,
        score: int,
        level: RiskLevel,
        signals: LoginSignals,
        decision: AuthDecision,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        self.db.add(
            IdentityRiskEvent(
                organization_id=organization_id,
                user_id=user.id if user else None,
                event_type=event_type.value,
                risk_score=score,
                risk_level=level.value,
                signals=signals.as_dict(),
                decision=decision.value,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        self.db.flush()

    @staticmethod
    def _retry_after(lock: AccountLock) -> int | None:
        if lock.expires_at is None:
            return None
        expires = lock.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return max(0, int((expires - _now()).total_seconds()))
