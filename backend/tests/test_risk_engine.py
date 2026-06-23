"""Unit tests for the risk engine (no database required)."""

from __future__ import annotations

import pytest

from app.services.risk_engine import calculate_risk_score


@pytest.mark.parametrize(
    "action,expected",
    [
        ("READ", 10),
        ("READ_PROFILE", 10),
        ("CREATE", 30),
        ("SEND_EMAIL", 35),
        ("UPDATE_RECORD", 55),
        ("SUBMIT_CLAIM", 75),
        ("DELETE_RECORD", 90),
        ("TRANSFER_MONEY", 95),
    ],
)
def test_known_action_scores(action: str, expected: int) -> None:
    assert calculate_risk_score("ANY", action, {}) == expected


def test_unknown_action_scores_high() -> None:
    assert calculate_risk_score("ANY", "DO_SOMETHING_WEIRD", {}) == 85


def test_action_matching_is_case_insensitive() -> None:
    assert calculate_risk_score("claim", "submit_claim", {}) == 75


def test_large_amount_bumps_score_but_is_clamped() -> None:
    # SUBMIT_CLAIM (75) + 10 bump = 85, still <= 100.
    assert calculate_risk_score("CLAIM", "SUBMIT_CLAIM", {"amount": 50_000}) == 85


def test_small_amount_does_not_bump() -> None:
    assert calculate_risk_score("CLAIM", "SUBMIT_CLAIM", {"amount": 1_200}) == 75
