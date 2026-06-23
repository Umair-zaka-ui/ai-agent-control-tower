"""Risk engine.

A deliberately simple, deterministic Phase 1 scorer. The score is driven by the
action being attempted, with a small adjustment for obviously sensitive payloads
(e.g. very large money amounts). Scores are clamped to the 0-100 range.
"""

from __future__ import annotations

from typing import Any

# Base risk per action. Keys are matched case-insensitively.
ACTION_RISK_SCORES: dict[str, int] = {
    "READ": 10,
    "READ_PROFILE": 10,
    "VIEW": 10,
    "CREATE": 30,
    "SEND_EMAIL": 35,
    "CANCEL": 40,
    "UPDATE": 55,
    "UPDATE_RECORD": 55,
    "RECOMMEND": 70,
    "SUBMIT_CLAIM": 75,
    "SUBMIT": 75,
    "DELETE": 90,
    "DELETE_RECORD": 90,
    "TRANSFER_MONEY": 95,
}

# Score used when the action is not recognised - unknown actions are risky.
UNKNOWN_ACTION_SCORE = 85

# Payloads with a money ``amount`` above this threshold get a small risk bump.
HIGH_AMOUNT_THRESHOLD = 10_000
HIGH_AMOUNT_BUMP = 10


def _clamp(score: int) -> int:
    return max(0, min(100, score))


def calculate_risk_score(
    resource: str,
    action: str,
    input_payload: dict[str, Any] | None = None,
) -> int:
    """Return an integer risk score in the range 0-100 for an attempted action."""
    base = ACTION_RISK_SCORES.get(action.strip().upper(), UNKNOWN_ACTION_SCORE)

    bump = 0
    if input_payload:
        amount = input_payload.get("amount")
        if isinstance(amount, (int, float)) and amount > HIGH_AMOUNT_THRESHOLD:
            bump += HIGH_AMOUNT_BUMP

    return _clamp(base + bump)
