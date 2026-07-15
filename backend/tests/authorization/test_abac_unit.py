"""Phase 4.3.5 unit tests (§42) — operators, type validation, regex safety,
nested condition evaluation, combining algorithms, obligations."""

from __future__ import annotations

import time

from app.authorization.abac.conditions import ConditionEvaluator
from app.authorization.abac.engine import CombiningAlgorithmService, MatchedPolicy, ObligationService
from app.authorization.abac.enums import CombiningAlgorithm as CA, Operator as Op
from app.authorization.abac.operators import (
    OperatorRegistry,
    validate_condition_value,
    validate_regex_pattern,
)


# --- Every comparison operator (§9, §42) ------------------------------------ #
def test_all_comparison_operators() -> None:
    cases = [
        (Op.EQUALS, "a", "a", True), (Op.EQUALS, 1, 2, False),
        (Op.NOT_EQUALS, "a", "b", True),
        (Op.IN, "b", ["a", "b"], True), (Op.IN, "c", ["a", "b"], False),
        (Op.NOT_IN, "c", ["a", "b"], True),
        (Op.CONTAINS, ["x", "y"], "x", True), (Op.CONTAINS, "hello", "ell", True),
        (Op.NOT_CONTAINS, ["x"], "z", True),
        (Op.GREATER_THAN, 82, 70, True), (Op.GREATER_THAN, 50, 70, False),
        (Op.GREATER_THAN_OR_EQUAL, 70, 70, True),
        (Op.LESS_THAN, 5, 10, True),
        (Op.LESS_THAN_OR_EQUAL, 10, 10, True),
        (Op.STARTS_WITH, "agent.execute", "agent.", True),
        (Op.ENDS_WITH, "dataset.export", ".export", True),
        (Op.MATCHES_REGEX, "gpt-4o", r"^gpt-", True),
        (Op.BETWEEN, 50, [10, 90], True), (Op.BETWEEN, 95, [10, 90], False),
    ]
    for op, actual, expected, want in cases:
        got = OperatorRegistry.apply(op.value, actual, expected)
        assert got is want, f"{op.value}({actual!r}, {expected!r}) = {got}, wanted {want}"


def test_datetime_and_numeric_coercion() -> None:
    assert OperatorRegistry.apply("GREATER_THAN", "2026-07-15T10:00:00", "2026-07-15T09:00:00")
    assert OperatorRegistry.apply("BETWEEN", "2026-07-15",
                                  ["2026-01-01", "2026-12-31"])
    assert OperatorRegistry.apply("GREATER_THAN_OR_EQUAL", 70.0, 70)


def test_unregistered_operator_never_matches() -> None:
    assert OperatorRegistry.apply("EXEC_CODE", "x", "x") is False
    assert not OperatorRegistry.is_registered("__import__")


# --- Type validation (§10) ----------------------------------------------------- #
def test_type_validation_rejects_invalid_comparisons() -> None:
    # risk_score > "high" — an integer compared to a string must fail (§10).
    assert validate_condition_value("GREATER_THAN", "high", "INTEGER") is not None
    assert validate_condition_value("GREATER_THAN", 70, "INTEGER") is None
    assert validate_condition_value("EQUALS", "yes", "BOOLEAN") is not None
    assert validate_condition_value("EQUALS", True, "BOOLEAN") is None
    assert validate_condition_value("IN", "not-a-list", "STRING") is not None
    assert validate_condition_value("IN", ["a", "b"], "STRING") is None
    assert validate_condition_value("BETWEEN", [1], "INTEGER") is not None
    assert validate_condition_value("BETWEEN", [1, 9], "INTEGER") is None
    assert validate_condition_value("GREATER_THAN", True, "BOOLEAN") is not None
    assert validate_condition_value("EXISTS", None, "STRING") is None  # takes no value


# --- Regex safety (§40, §42) ------------------------------------------------------ #
def test_regex_guard_rejects_redos_patterns() -> None:
    assert validate_regex_pattern(r"(a+)+$") is not None, "nested quantifier must be rejected"
    assert validate_regex_pattern(r"(\d*)*x") is not None
    assert validate_regex_pattern("x" * 300) is not None, "over-long pattern must be rejected"
    assert validate_regex_pattern(r"[unclosed") is not None
    assert validate_regex_pattern(r"^gpt-\d+$") is None

    # Even if an unsafe pattern reached runtime it must not execute.
    started = time.perf_counter()
    assert OperatorRegistry.apply("MATCHES_REGEX", "a" * 40 + "!", r"(a+)+$") is False
    assert (time.perf_counter() - started) < 0.5


# --- Nested conditions (§9) ---------------------------------------------------------- #
CTX = {
    "resource.contains_phi": True,
    "environment.device_trust": "UNKNOWN",
    "identity.department_id": "finance",
    "environment.business_hours": False,
    "identity.roles": ["ROLE_SECURITY_ADMIN"],
    "identity.risk_score": 82,
}


def test_nested_all_any_not() -> None:
    tree = {
        "all": [
            {"attribute": "identity.department_id", "operator": "EQUALS", "value": "finance"},
            {"any": [
                {"attribute": "environment.business_hours", "operator": "EQUALS", "value": True},
                {"attribute": "identity.roles", "operator": "CONTAINS",
                 "value": "ROLE_SECURITY_ADMIN"},
            ]},
            {"not": {"attribute": "identity.risk_score", "operator": "LESS_THAN", "value": 10}},
        ]
    }
    ok, trace = ConditionEvaluator.evaluate(tree, CTX)
    assert ok is True
    assert len(trace.results) == 4  # every leaf traced, no short-circuit inside ANY


def test_missing_attribute_fails_leaf_but_exists_operators_work() -> None:
    ok, trace = ConditionEvaluator.evaluate(
        {"attribute": "ai.autonomy_level", "operator": "EQUALS", "value": "AUTONOMOUS"}, CTX)
    assert ok is False
    assert "ai.autonomy_level" in trace.missing_attributes

    ok, _ = ConditionEvaluator.evaluate(
        {"attribute": "ai.autonomy_level", "operator": "NOT_EXISTS"}, CTX)
    assert ok is True
    ok, _ = ConditionEvaluator.evaluate(
        {"attribute": "resource.contains_phi", "operator": "EXISTS"}, CTX)
    assert ok is True


def test_empty_conditions_match_and_depth_is_measured() -> None:
    ok, _ = ConditionEvaluator.evaluate(None, CTX)
    assert ok is True
    deep = {"attribute": "identity.risk_score", "operator": "EXISTS"}
    for _ in range(5):
        deep = {"not": deep}
    assert ConditionEvaluator.depth_of(deep) == 6
    assert len(ConditionEvaluator.leaves_of(deep)) == 1


# --- Combining algorithms (§13, §14) ----------------------------------------------------- #
def _m(effect: str, priority: int = 100, name: str = "p", obligations: dict | None = None):
    from app.authorization.abac.conditions import ConditionTrace

    return MatchedPolicy(policy={
        "id": name, "name": name, "effect": effect, "priority": priority,
        "combining_algorithm": "DENY_OVERRIDES", "obligations": obligations or {},
    }, trace=ConditionTrace())


def test_deny_overrides_precedence() -> None:
    # §14 — deny beats approval beats allow.
    matched = [_m("ALLOW"), _m("REQUIRE_APPROVAL"), _m("DENY")]
    effect, winning = CombiningAlgorithmService.combine(matched, CA.DENY_OVERRIDES.value)
    assert effect == "DENY" and winning["name"] == "p"

    matched = [_m("ALLOW"), _m("REQUIRE_APPROVAL")]
    effect, _ = CombiningAlgorithmService.combine(matched, CA.DENY_OVERRIDES.value)
    assert effect == "REQUIRE_APPROVAL"

    matched = [_m("ALLOW"), _m("REQUIRE_MFA"), _m("REQUIRE_APPROVAL")]
    effect, _ = CombiningAlgorithmService.combine(matched, CA.DENY_OVERRIDES.value)
    assert effect == "REQUIRE_APPROVAL", "approval outranks MFA"


def test_other_combining_algorithms() -> None:
    matched = [_m("DENY", name="a"), _m("ALLOW", name="b")]
    effect, _ = CombiningAlgorithmService.combine(matched, CA.ALLOW_OVERRIDES.value)
    assert effect == "ALLOW"

    effect, winning = CombiningAlgorithmService.combine(matched, CA.FIRST_APPLICABLE.value)
    assert effect == "DENY" and winning["name"] == "a"

    matched = [_m("DENY", priority=10, name="low"), _m("ALLOW", priority=500, name="high")]
    effect, winning = CombiningAlgorithmService.combine(matched, CA.HIGHEST_PRIORITY.value)
    assert effect == "ALLOW" and winning["name"] == "high"

    matched = [_m("ALLOW"), _m("ALLOW")]
    effect, _ = CombiningAlgorithmService.combine(matched, CA.ALL_MUST_ALLOW.value)
    assert effect == "ALLOW"
    matched = [_m("ALLOW"), _m("REQUIRE_MFA")]
    effect, _ = CombiningAlgorithmService.combine(matched, CA.ALL_MUST_ALLOW.value)
    assert effect == "REQUIRE_MFA"


def test_log_only_never_decides() -> None:
    matched = [_m("LOG_ONLY")]
    effect, winning = CombiningAlgorithmService.combine(matched, CA.DENY_OVERRIDES.value)
    assert effect == "NOT_APPLICABLE" and winning is None


# --- Obligations (§8) -------------------------------------------------------------------- #
def test_obligations_normalized_per_effect() -> None:
    matched = [
        _m("REQUIRE_APPROVAL", obligations={"priority": "CRITICAL",
                                            "reviewer_role": "ROLE_AI_REVIEWER"}),
        _m("MASK_FIELDS", obligations={"fields": ["ssn", "medical_record_number"]}),
        _m("LIMIT_ACTION", obligations={"maximum_export_rows": 1000}),
        _m("REQUIRE_MFA"), _m("REQUIRE_JUSTIFICATION"), _m("LOG_ONLY"),
    ]
    obligations = ObligationService.build("REQUIRE_APPROVAL", matched)
    types = {o["type"] for o in obligations}
    assert types == {"CREATE_APPROVAL", "MASK_FIELDS", "LIMIT_ACTION",
                     "REQUIRE_MFA", "REQUIRE_JUSTIFICATION", "LOG_ONLY"}
    approval = next(o for o in obligations if o["type"] == "CREATE_APPROVAL")
    assert approval["priority"] == "CRITICAL"
    assert approval["reviewer_role"] == "ROLE_AI_REVIEWER"
    mask = next(o for o in obligations if o["type"] == "MASK_FIELDS")
    assert mask["fields"] == ["ssn", "medical_record_number"]
    limit = next(o for o in obligations if o["type"] == "LIMIT_ACTION")
    assert limit["limits"] == {"maximum_export_rows": 1000}


def test_deny_strips_challenge_obligations() -> None:
    matched = [_m("DENY"), _m("REQUIRE_APPROVAL"), _m("LOG_ONLY")]
    obligations = ObligationService.build("DENY", matched)
    assert {o["type"] for o in obligations} == {"LOG_ONLY"}
