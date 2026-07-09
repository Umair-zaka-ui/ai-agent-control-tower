"""Unit tests for risk scoring, levels and the rules engine (§14, §15, §16, §35)."""

from __future__ import annotations

import pytest

from app.identity.protection.detection import LoginSignals, RiskScoringService
from app.identity.protection.enums import AuthDecision, RiskLevel
from app.identity.protection.policy import AdaptiveRateLimitService, IdentityProtectionRuleService


def _signals(**flags) -> LoginSignals:
    s = LoginSignals()
    s.flags.update(flags)
    return s


@pytest.mark.parametrize(
    "score,level",
    [(0, RiskLevel.LOW), (20, RiskLevel.LOW), (21, RiskLevel.MEDIUM), (50, RiskLevel.MEDIUM),
     (51, RiskLevel.HIGH), (75, RiskLevel.HIGH), (76, RiskLevel.CRITICAL), (90, RiskLevel.CRITICAL),
     (91, RiskLevel.SEVERE), (100, RiskLevel.SEVERE)],
)
def test_risk_levels_bucket_correctly(score: int, level: RiskLevel) -> None:
    assert RiskLevel.for_score(score) is level


def test_score_sums_weights_and_caps_at_100() -> None:
    score, level = RiskScoringService.score(_signals(new_device=True, new_country=True))
    assert score == 50 and level is RiskLevel.MEDIUM

    # blocked_ip(80) + new_country(30) + impossible_travel(40) = 150 → capped at 100.
    score, level = RiskScoringService.score(
        _signals(blocked_ip=True, new_country=True, impossible_travel=True)
    )
    assert score == 100 and level is RiskLevel.SEVERE


def test_no_signals_is_zero_risk() -> None:
    score, level = RiskScoringService.score(LoginSignals())
    assert score == 0 and level is RiskLevel.LOW


def test_adaptive_rate_limit_tightens_with_risk() -> None:
    assert AdaptiveRateLimitService.adjusted_limit(10, RiskLevel.LOW) == 10
    assert AdaptiveRateLimitService.adjusted_limit(10, RiskLevel.MEDIUM) == 10
    assert AdaptiveRateLimitService.adjusted_limit(10, RiskLevel.HIGH) == 5     # -50%
    assert AdaptiveRateLimitService.adjusted_limit(10, RiskLevel.CRITICAL) == 2  # -80%
    assert AdaptiveRateLimitService.adjusted_limit(10, RiskLevel.SEVERE) == 2


# --------------------------------------------------------------------------- #
# Rules engine (§16) — clause matching without a DB
# --------------------------------------------------------------------------- #
def _facts(**kw):
    base = {"risk_score": 0, "risk_level": "LOW", "failed_attempts": 0}
    base.update(kw)
    return base


def test_rule_clause_operators() -> None:
    clause = IdentityProtectionRuleService._clause
    assert clause({"field": "risk_score", "op": "gte", "value": 50}, _facts(risk_score=60)) is True
    assert clause({"field": "risk_score", "op": "gte", "value": 50}, _facts(risk_score=40)) is False
    assert clause({"field": "impossible_travel", "op": "is_true"}, _facts(impossible_travel=True)) is True
    assert clause({"field": "impossible_travel", "op": "is_true"}, _facts()) is False
    assert clause({"field": "risk_level", "op": "in", "value": ["HIGH", "SEVERE"]}, _facts(risk_level="HIGH")) is True
    assert clause({"field": "failed_attempts", "op": "gt", "value": 3}, _facts(failed_attempts=5)) is True


def test_rule_validation_rejects_bad_decision_and_op() -> None:
    from app.identity.errors import IdentityError

    with pytest.raises(IdentityError):
        IdentityProtectionRuleService.validate([], "NOT_A_DECISION")
    with pytest.raises(IdentityError):
        IdentityProtectionRuleService.validate([{"field": "risk_score", "op": "weird", "value": 1}], "BLOCK_IP")
    # A valid one does not raise.
    IdentityProtectionRuleService.validate(
        [{"field": "risk_score", "op": "gte", "value": 90}], AuthDecision.REQUIRE_MFA.value
    )
