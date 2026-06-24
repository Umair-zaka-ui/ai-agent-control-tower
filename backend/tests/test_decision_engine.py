"""Unit tests for the decision engine (no database required)."""

from __future__ import annotations

import uuid

from app.core.enums import ActionDecision, AgentStatus
from app.models.agent import Agent
from app.services.decision_engine import make_decision
from app.services.permission_engine import PermissionResult
from app.services.policy_engine import PolicyResult

ALLOWED = PermissionResult(allowed=True, reason="ok")
DENIED = PermissionResult(allowed=False, reason="no rule")


def _agent(status: AgentStatus = AgentStatus.ACTIVE) -> Agent:
    return Agent(name="t", agent_type="t", api_key_hash="x", status=status)


def test_inactive_agent_is_blocked() -> None:
    result = make_decision(_agent(AgentStatus.INACTIVE), ALLOWED, 10)
    assert result.decision == ActionDecision.BLOCK


def test_missing_permission_is_blocked() -> None:
    result = make_decision(_agent(), DENIED, 10)
    assert result.decision == ActionDecision.BLOCK


def test_low_risk_is_allowed() -> None:
    result = make_decision(_agent(), ALLOWED, 40)
    assert result.decision == ActionDecision.ALLOW


def test_medium_risk_needs_approval() -> None:
    result = make_decision(_agent(), ALLOWED, 75)
    assert result.decision == ActionDecision.PENDING_APPROVAL


def test_boundary_41_needs_approval() -> None:
    assert make_decision(_agent(), ALLOWED, 41).decision == ActionDecision.PENDING_APPROVAL


def test_boundary_80_needs_approval() -> None:
    assert make_decision(_agent(), ALLOWED, 80).decision == ActionDecision.PENDING_APPROVAL


def test_high_risk_is_blocked() -> None:
    result = make_decision(_agent(), ALLOWED, 81)
    assert result.decision == ActionDecision.BLOCK


def test_matching_policy_overrides_low_risk() -> None:
    policy = PolicyResult(
        matched=True,
        decision=ActionDecision.PENDING_APPROVAL,
        policy_id=uuid.uuid4(),
        policy_name="Large Claim Approval",
        reason="matched",
    )
    result = make_decision(_agent(), ALLOWED, 10, policy)
    assert result.decision == ActionDecision.PENDING_APPROVAL
    assert result.matched_policy_name == "Large Claim Approval"


def test_matching_block_policy_overrides_low_risk() -> None:
    policy = PolicyResult(
        matched=True, decision=ActionDecision.BLOCK, policy_name="Block Huge Claim"
    )
    result = make_decision(_agent(), ALLOWED, 10, policy)
    assert result.decision == ActionDecision.BLOCK


def test_permission_denied_beats_policy() -> None:
    policy = PolicyResult(matched=True, decision=ActionDecision.ALLOW, policy_name="x")
    result = make_decision(_agent(), DENIED, 10, policy)
    assert result.decision == ActionDecision.BLOCK
