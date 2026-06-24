"""Policy engine: evaluate database-driven policies against an action.

A policy targets a (resource, action) pair and carries a JSON ``conditions``
object. Conditions use ``<field>_<op>`` keys evaluated against the action's
input payload, e.g. ``{"amount_gt": 10000}``. An empty conditions object always
matches (a blanket rule for that resource/action).

When several policies match, the one with the highest ``priority`` wins; ties
are broken by the most restrictive decision (BLOCK > PENDING_APPROVAL > ALLOW).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ActionDecision
from app.models.policy import Policy

# Operator suffixes, ordered so multi-char ones are matched before short ones.
_OPERATORS = ("_gte", "_lte", "_gt", "_lt", "_eq", "_ne", "_in", "_contains")

# Restrictiveness ranking used to break ties between matching policies.
_RESTRICTIVENESS = {
    ActionDecision.ALLOW: 0,
    ActionDecision.PENDING_APPROVAL: 1,
    ActionDecision.BLOCK: 2,
}


@dataclass(frozen=True)
class PolicyResult:
    matched: bool
    decision: ActionDecision | None = None
    policy_id: uuid.UUID | None = None
    policy_name: str | None = None
    reason: str | None = None


def _as_number(value: Any) -> float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _check_single(field: str, op: str, expected: Any, payload: dict[str, Any]) -> bool:
    actual = payload.get(field)

    if op in ("_gt", "_gte", "_lt", "_lte"):
        a, e = _as_number(actual), _as_number(expected)
        if a is None or e is None:
            return False
        return {
            "_gt": a > e,
            "_gte": a >= e,
            "_lt": a < e,
            "_lte": a <= e,
        }[op]
    if op == "_eq":
        return actual == expected
    if op == "_ne":
        return actual != expected
    if op == "_in":
        return isinstance(expected, list) and actual in expected
    if op == "_contains":
        return isinstance(actual, (list, str)) and expected in actual
    return False


def evaluate_conditions(conditions: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Return True if every condition holds for the payload (logical AND)."""
    if not conditions:
        return True

    payload = payload or {}
    for key, expected in conditions.items():
        op = next((o for o in _OPERATORS if key.endswith(o)), None)
        if op is None:
            # No operator suffix => treat as an equality check on the field.
            if payload.get(key) != expected:
                return False
            continue
        field = key[: -len(op)]
        if not _check_single(field, op, expected, payload):
            return False
    return True


def _to_decision(value: str) -> ActionDecision:
    return ActionDecision(value.strip().upper())


def evaluate_policies(
    db: Session,
    organization_id: uuid.UUID,
    resource: str,
    action: str,
    payload: dict[str, Any],
) -> PolicyResult:
    """Find the winning enabled policy for an action, if any."""
    stmt = select(Policy).where(
        Policy.organization_id == organization_id,
        Policy.enabled.is_(True),
        Policy.resource == resource,
        Policy.action == action,
    )
    policies = list(db.execute(stmt).scalars().all())

    matches: list[Policy] = [
        p for p in policies if evaluate_conditions(p.conditions, payload)
    ]
    if not matches:
        return PolicyResult(matched=False)

    winner = max(
        matches,
        key=lambda p: (p.priority, _RESTRICTIVENESS.get(_to_decision(p.decision), 0)),
    )
    decision = _to_decision(winner.decision)
    return PolicyResult(
        matched=True,
        decision=decision,
        policy_id=winner.id,
        policy_name=winner.name,
        reason=f"Matched policy '{winner.name}' -> {decision.value}.",
    )
