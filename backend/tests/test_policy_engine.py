"""Unit tests for the policy engine condition evaluation (no database)."""

from __future__ import annotations

from app.core.enums import ActionDecision
from app.services.policy_engine import _to_decision, evaluate_conditions


def test_empty_conditions_always_match() -> None:
    assert evaluate_conditions({}, {"anything": 1}) is True


def test_amount_gt() -> None:
    assert evaluate_conditions({"amount_gt": 10000}, {"amount": 15000}) is True
    assert evaluate_conditions({"amount_gt": 10000}, {"amount": 5000}) is False


def test_amount_gte_and_lte() -> None:
    assert evaluate_conditions({"amount_gte": 100}, {"amount": 100}) is True
    assert evaluate_conditions({"amount_lte": 100}, {"amount": 100}) is True
    assert evaluate_conditions({"amount_lt": 100}, {"amount": 100}) is False


def test_non_numeric_amount_fails_numeric_op() -> None:
    assert evaluate_conditions({"amount_gt": 10}, {"amount": "lots"}) is False
    assert evaluate_conditions({"amount_gt": 10}, {}) is False


def test_eq_ne_in_contains() -> None:
    assert evaluate_conditions({"region_eq": "US"}, {"region": "US"}) is True
    assert evaluate_conditions({"region_ne": "US"}, {"region": "EU"}) is True
    assert evaluate_conditions({"status_in": ["A", "B"]}, {"status": "A"}) is True
    assert evaluate_conditions({"tags_contains": "vip"}, {"tags": ["vip", "x"]}) is True


def test_equality_without_operator_suffix() -> None:
    assert evaluate_conditions({"region": "US"}, {"region": "US"}) is True
    assert evaluate_conditions({"region": "US"}, {"region": "EU"}) is False


def test_all_conditions_must_hold() -> None:
    conditions = {"amount_gt": 1000, "region_eq": "US"}
    assert evaluate_conditions(conditions, {"amount": 2000, "region": "US"}) is True
    assert evaluate_conditions(conditions, {"amount": 2000, "region": "EU"}) is False


def test_to_decision_is_case_insensitive() -> None:
    assert _to_decision("pending_approval") == ActionDecision.PENDING_APPROVAL
    assert _to_decision("BLOCK") == ActionDecision.BLOCK
