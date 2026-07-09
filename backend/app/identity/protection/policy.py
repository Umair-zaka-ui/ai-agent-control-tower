"""Blocked IPs, protection rules, adaptive rate limiting and CAPTCHA (§10, §16, §28)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.identity.auth.enums import AuthEventType, AuthIdentityType, AuthMethod
from app.identity.auth.security_event_service import SecurityEventService
from app.identity.models.protection import BlockedIp, IdentityProtectionRule
from app.identity.protection.detection import LoginSignals
from app.identity.protection.enums import AuthDecision, RiskLevel
from app.identity.protection.repositories import (
    BlockedIpRepository,
    IdentityProtectionRuleRepository,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Blocked IPs (§16)
# --------------------------------------------------------------------------- #
class BlockedIpService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = BlockedIpRepository(db)
        self.events = SecurityEventService(db)

    def is_blocked(self, ip_address: str | None, *, organization_id: uuid.UUID | None) -> bool:
        if not ip_address:
            return False
        return self.repo.find_active(ip_address, organization_id=organization_id, now=_now()) is not None

    def block(
        self,
        ip_address: str,
        *,
        organization_id: uuid.UUID | None,
        reason: str | None = None,
        expires_at: datetime | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> BlockedIp:
        entry = BlockedIp(
            organization_id=organization_id,
            ip_address=ip_address,
            reason=reason,
            expires_at=expires_at,
            created_by=actor_id,
        )
        self.db.add(entry)
        self.db.flush()
        self.events.record(
            AuthEventType.IP_BLOCKED,
            auth_method=AuthMethod.PASSWORD,
            identity_type=AuthIdentityType.SYSTEM.value,
            organization_id=organization_id,
            ip_address=ip_address,
            metadata={"blocked_ip_id": str(entry.id), "reason": reason, "actor_id": str(actor_id) if actor_id else None},
        )
        return entry

    def unblock(self, entry: BlockedIp, *, actor_id: uuid.UUID | None = None) -> None:
        self.events.record(
            AuthEventType.IP_UNBLOCKED,
            auth_method=AuthMethod.PASSWORD,
            identity_type=AuthIdentityType.SYSTEM.value,
            organization_id=entry.organization_id,
            ip_address=entry.ip_address,
            metadata={"blocked_ip_id": str(entry.id), "actor_id": str(actor_id) if actor_id else None},
        )
        self.db.delete(entry)
        self.db.flush()

    def list_for_scope(self, organization_id: uuid.UUID) -> list[BlockedIp]:
        return self.repo.list_for_scope(organization_id)


# --------------------------------------------------------------------------- #
# CAPTCHA abstraction (§28) — no live provider yet
# --------------------------------------------------------------------------- #
class CaptchaService:
    """Provider-agnostic seam. ``should_challenge`` decides *when* a CAPTCHA is due;
    ``verify`` is a placeholder that a real provider (Turnstile / reCAPTCHA / hCaptcha)
    slots into. Disabled by default so it is purely additive."""

    PROVIDERS = ("turnstile", "recaptcha", "hcaptcha")

    def __init__(self) -> None:
        self.enabled = settings.PROTECTION_CAPTCHA_ENABLED

    def should_challenge(self, signals: LoginSignals, risk_score: int) -> bool:
        if not self.enabled:
            return False
        if signals.failed_attempts >= settings.PROTECTION_CAPTCHA_FAILED_ATTEMPTS:
            return True
        if risk_score >= settings.PROTECTION_CAPTCHA_RISK_AT:
            return True
        return bool(signals.flags.get("suspicious_user_agent") or signals.flags.get("blocked_ip"))

    def verify(self, token: str | None) -> bool:
        """With no provider configured this returns ``not enabled`` — i.e. it never
        blocks when CAPTCHA is off, and always "passes" until a provider is wired."""
        if not self.enabled:
            return True
        return bool(token)


# --------------------------------------------------------------------------- #
# Adaptive rate limiting (§10)
# --------------------------------------------------------------------------- #
class AdaptiveRateLimitService:
    """Tightens the base per-endpoint limit as risk rises (§10). Returns the effective
    limit; the actual counting stays in the Postgres-backed limiter."""

    @staticmethod
    def adjusted_limit(base_limit: int, risk_level: RiskLevel) -> int:
        if risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM):
            return base_limit
        if risk_level is RiskLevel.HIGH:  # suspicious → -50%
            return max(1, base_limit // 2)
        # CRITICAL / SEVERE → -80% (attack territory)
        return max(1, base_limit // 5)


# --------------------------------------------------------------------------- #
# Identity protection rules engine (§16, §27)
# --------------------------------------------------------------------------- #
class IdentityProtectionRuleService:
    """Admin-authored ``conditions → decision`` rules.

    A condition is ``{field, op, value}``. ``field`` is ``risk_score``, ``risk_level``,
    ``failed_attempts`` or any anomaly flag (``new_device``, ``impossible_travel``,
    ``blocked_ip``…). ``op`` is one of ``eq gt gte lt lte in is_true``. A rule matches
    when *all* its conditions match; the highest-priority enabled match wins.
    """

    _OPS = {"eq", "gt", "gte", "lt", "lte", "in", "is_true"}

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = IdentityProtectionRuleRepository(db)
        self.events = SecurityEventService(db)

    # ---- evaluation ---- #
    def evaluate(
        self,
        organization_id: uuid.UUID,
        *,
        risk_score: int,
        risk_level: RiskLevel,
        signals: LoginSignals,
    ) -> tuple[AuthDecision, IdentityProtectionRule] | None:
        facts = self._facts(risk_score, risk_level, signals)
        for rule in self.repo.list_enabled(organization_id):
            if self._matches(rule, facts):
                try:
                    decision = AuthDecision(rule.decision)
                except ValueError:
                    continue
                self.events.record(
                    AuthEventType.PROTECTION_RULE_TRIGGERED,
                    auth_method=AuthMethod.PASSWORD,
                    identity_type=AuthIdentityType.HUMAN_USER.value,
                    organization_id=organization_id,
                    metadata={"rule_id": str(rule.id), "rule_name": rule.name, "decision": rule.decision},
                )
                return decision, rule
        return None

    @staticmethod
    def _facts(risk_score: int, risk_level: RiskLevel, signals: LoginSignals) -> dict:
        return {
            "risk_score": risk_score,
            "risk_level": risk_level.value,
            "failed_attempts": signals.failed_attempts,
            **{flag: bool(on) for flag, on in signals.flags.items()},
        }

    def _matches(self, rule: IdentityProtectionRule, facts: dict) -> bool:
        conditions = rule.conditions or []
        if not conditions:
            return False
        return all(self._clause(c, facts) for c in conditions)

    @staticmethod
    def _clause(clause: dict, facts: dict) -> bool:
        field = clause.get("field")
        op = clause.get("op")
        value = clause.get("value")
        actual = facts.get(field)
        if op == "is_true":
            return bool(actual)
        if actual is None:
            return False
        try:
            if op == "eq":
                return actual == value
            if op == "gt":
                return actual > value
            if op == "gte":
                return actual >= value
            if op == "lt":
                return actual < value
            if op == "lte":
                return actual <= value
            if op == "in":
                return actual in (value or [])
        except TypeError:
            return False
        return False

    # ---- CRUD ---- #
    @staticmethod
    def validate(conditions: list[dict], decision: str) -> None:
        from app.identity.errors import ErrorCode, IdentityError

        try:
            AuthDecision(decision)
        except ValueError as exc:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, f"Unknown decision: {decision}") from exc
        for clause in conditions or []:
            if clause.get("op") not in IdentityProtectionRuleService._OPS:
                raise IdentityError(
                    ErrorCode.VALIDATION_ERROR, f"Unknown condition operator: {clause.get('op')}"
                )
            if not clause.get("field"):
                raise IdentityError(ErrorCode.VALIDATION_ERROR, "Each condition needs a field.")

    def create(
        self,
        organization_id: uuid.UUID,
        *,
        name: str,
        conditions: list[dict],
        decision: str,
        description: str | None = None,
        priority: int = 100,
        enabled: bool = True,
        actor_id: uuid.UUID | None = None,
    ) -> IdentityProtectionRule:
        self.validate(conditions, decision)
        rule = IdentityProtectionRule(
            organization_id=organization_id,
            name=name,
            description=description,
            conditions=conditions,
            decision=decision,
            priority=priority,
            enabled=enabled,
        )
        self.db.add(rule)
        self.db.flush()
        self._audit(AuthEventType.PROTECTION_RULE_CREATED, rule, actor_id)
        return rule

    def update(self, rule: IdentityProtectionRule, *, actor_id: uuid.UUID | None = None, **fields) -> IdentityProtectionRule:
        if "conditions" in fields or "decision" in fields:
            self.validate(
                fields.get("conditions", rule.conditions), fields.get("decision", rule.decision)
            )
        for key in ("name", "description", "conditions", "decision", "priority", "enabled"):
            if key in fields and fields[key] is not None:
                setattr(rule, key, fields[key])
        self.db.flush()
        self._audit(AuthEventType.PROTECTION_RULE_UPDATED, rule, actor_id)
        return rule

    def delete(self, rule: IdentityProtectionRule, *, actor_id: uuid.UUID | None = None) -> None:
        self._audit(AuthEventType.PROTECTION_RULE_DELETED, rule, actor_id)
        self.db.delete(rule)
        self.db.flush()

    def list_for_organization(self, organization_id: uuid.UUID) -> list[IdentityProtectionRule]:
        return self.repo.list_for_organization(organization_id)

    def _audit(self, event: AuthEventType, rule: IdentityProtectionRule, actor_id: uuid.UUID | None) -> None:
        self.events.record(
            event,
            auth_method=AuthMethod.PASSWORD,
            identity_type=AuthIdentityType.HUMAN_USER.value,
            organization_id=rule.organization_id,
            identity_id=actor_id,
            metadata={"rule_id": str(rule.id), "rule_name": rule.name},
        )
