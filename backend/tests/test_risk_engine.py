"""Unit tests for the risk engine V2 (no database required)."""

from __future__ import annotations

import pytest

from app.services.risk_engine import calculate_risk_breakdown, calculate_risk_score


@pytest.mark.parametrize(
    "resource,action,payload,expected",
    [
        # action_score + resource_score [+ modifiers]
        ("APPOINTMENT", "CREATE", {}, 25),          # 20 + 5
        ("CLAIM", "SUBMIT_CLAIM", {}, 75),          # 65 + 10
        ("CLAIM", "READ", {}, 20),                  # 10 + 10
        ("PATIENT_RECORD", "READ", {}, 45),         # 10 + 15 + PHI 20
        ("PATIENT_RECORD", "UPDATE_RECORD", {}, 75),  # 40 + 15 + PHI 20
        ("MEDICATION", "RECOMMEND", {}, 85),        # 50 + 15 + PHI 20
        ("CLAIM", "DELETE_RECORD", {}, 100),        # 90 + 10
    ],
)
def test_scores(resource, action, payload, expected) -> None:
    assert calculate_risk_score(resource, action, payload) == expected


def test_unknown_action_uses_default() -> None:
    # 70 (unknown) + 10 (CLAIM)
    assert calculate_risk_score("CLAIM", "DO_WEIRD_THING", {}) == 80


def test_high_amount_modifier_applies() -> None:
    # 65 + 10 + HIGH_AMOUNT 10
    assert calculate_risk_score("CLAIM", "SUBMIT_CLAIM", {"amount": 50_000}) == 85


def test_small_amount_no_modifier() -> None:
    assert calculate_risk_score("CLAIM", "SUBMIT_CLAIM", {"amount": 1_200}) == 75


def test_score_is_clamped_to_100() -> None:
    # 95 + 20 (PAYMENT) would be 115 -> clamps to 100
    assert calculate_risk_score("PAYMENT", "TRANSFER_MONEY", {}) == 100


def test_breakdown_is_transparent() -> None:
    b = calculate_risk_breakdown("PATIENT_RECORD", "UPDATE_RECORD", {"amount": 20_000})
    assert b.action_score == 40
    assert b.resource_score == 15
    assert b.modifiers == {"PHI_ACCESS": 20, "HIGH_AMOUNT": 10}
    assert b.score == 85


def test_case_insensitive() -> None:
    assert calculate_risk_score("claim", "submit_claim", {}) == 75
