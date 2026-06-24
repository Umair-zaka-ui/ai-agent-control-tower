"""Risk engine V2.

Combines three signals into a single 0-100 score:

    risk = clamp( action_score + resource_score + sum(modifiers) )

* action_score   - the dominant signal (what is being done)
* resource_score - a smaller adjustment (what it is being done to)
* modifiers      - contextual bumps (e.g. PHI access, very large amounts)

The function keeps the Phase 1 signature so existing callers/tests still work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# --- Action scores (dominant signal) --------------------------------------- #
ACTION_SCORES: dict[str, int] = {
    "READ": 10,
    "READ_RECORD": 10,
    "READ_PROFILE": 10,
    "VIEW": 10,
    "LIST": 10,
    "CREATE": 20,
    "SEND_EMAIL": 30,
    "CANCEL": 35,
    "UPDATE": 40,
    "UPDATE_RECORD": 40,
    "RECOMMEND": 50,
    "SUBMIT": 65,
    "SUBMIT_CLAIM": 65,
    "DELETE": 90,
    "DELETE_RECORD": 90,
    "TRANSFER_MONEY": 95,
}
UNKNOWN_ACTION_SCORE = 70

# --- Resource scores (smaller adjustment) ---------------------------------- #
RESOURCE_SCORES: dict[str, int] = {
    "APPOINTMENT": 5,
    "CLAIM": 10,
    "PATIENT_RECORD": 15,
    "DIAGNOSIS": 15,
    "MEDICATION": 15,
    "PAYMENT": 20,
}
DEFAULT_RESOURCE_SCORE = 5

# --- Contextual modifiers --------------------------------------------------- #
# Resources that constitute Protected Health Information access.
PHI_RESOURCES = {"PATIENT_RECORD", "DIAGNOSIS", "MEDICATION"}
PHI_MODIFIER = 20

HIGH_AMOUNT_THRESHOLD = 10_000
HIGH_AMOUNT_MODIFIER = 10


@dataclass(frozen=True)
class RiskBreakdown:
    """Transparent breakdown of how a score was derived (useful for audit)."""

    score: int
    action_score: int
    resource_score: int
    modifiers: dict[str, int]


def _clamp(value: int) -> int:
    return max(0, min(100, value))


def calculate_risk_breakdown(
    resource: str,
    action: str,
    input_payload: dict[str, Any] | None = None,
) -> RiskBreakdown:
    payload = input_payload or {}

    action_score = ACTION_SCORES.get(action.strip().upper(), UNKNOWN_ACTION_SCORE)
    resource_key = resource.strip().upper()
    resource_score = RESOURCE_SCORES.get(resource_key, DEFAULT_RESOURCE_SCORE)

    modifiers: dict[str, int] = {}
    if resource_key in PHI_RESOURCES or payload.get("phi") is True:
        modifiers["PHI_ACCESS"] = PHI_MODIFIER

    amount = payload.get("amount")
    if isinstance(amount, (int, float)) and not isinstance(amount, bool) and amount > HIGH_AMOUNT_THRESHOLD:
        modifiers["HIGH_AMOUNT"] = HIGH_AMOUNT_MODIFIER

    total = _clamp(action_score + resource_score + sum(modifiers.values()))
    return RiskBreakdown(
        score=total,
        action_score=action_score,
        resource_score=resource_score,
        modifiers=modifiers,
    )


def calculate_risk_score(
    resource: str,
    action: str,
    input_payload: dict[str, Any] | None = None,
) -> int:
    """Return an integer risk score in the range 0-100 for an attempted action."""
    return calculate_risk_breakdown(resource, action, input_payload).score
