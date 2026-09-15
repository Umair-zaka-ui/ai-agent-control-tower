"""Phase 5.7 (M5.7) - setting an external agent's enforcement mode,
server-authoritatively.

**Server-authoritative** here means the same thing Phase 5.1 made it mean for
``control_state``: the value a client sends is a *request*, validated against
a transition matrix and the agent's real situation, never written through. In
addition -- and this is the structural half -- the strongest mode is not
writable at all. ``NATIVE_ENFORCED`` is excluded from the column's CHECK
constraint, so the only way an agent reaches it is by actually being
``control_state='GOVERNED'``, which is Phase 5.1's own server-authoritative
path and not reachable from here. There is no code in this phase that can
make ACT claim full enforcement.

The transitions that *are* allowed are all between modes with no reach or
boundary-only reach, so any of them may follow any other -- an operator
re-classifying an external agent is a normal, reversible act. What is checked
is that the target is truthful for this agent: raising an agent to
GATEWAY_ENFORCED asserts that ACT's boundary really is where its capability
calls go, and dropping it back below that immediately ends that claim -- which
is why the service revokes the grants that depended on it in the same
transaction.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.services import AuthorizationAuditService
from app.bridge.modes import (
    NATIVE_CONTROL_STATE,
    SETTABLE_MODES,
    describe,
    effective_mode,
)
from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.bridge import ExternalCapabilityGrant
from app.models.user import User


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EnforcementModeService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_404(self, actor: User, agent_id: uuid.UUID) -> Agent:
        agent = self.db.get(Agent, agent_id)
        if agent is None or agent.organization_id != actor.organization_id:
            # 404, never 403 -- a cross-tenant probe learns nothing.
            raise IdentityError(ErrorCode.EXTERNAL_SUBJECT_NOT_FOUND,
                                "No such agent in this organization.")
        return agent

    def read(self, actor: User, agent_id: uuid.UUID) -> dict:
        return describe(self.get_or_404(actor, agent_id))

    def set_mode(self, actor: User, agent_id: uuid.UUID, *, target_mode: str,
                 reason: str | None = None) -> dict:
        agent = self.get_or_404(actor, agent_id)
        previous = effective_mode(agent)

        if target_mode not in SETTABLE_MODES:
            if target_mode == "NATIVE_ENFORCED":
                raise IdentityError(
                    ErrorCode.EXTERNAL_MODE_NOT_SETTABLE,
                    "NATIVE_ENFORCED cannot be assigned. It is not a label -- it means ACT "
                    "actually runs and enforces this agent, and it is derived from "
                    f"control_state == {NATIVE_CONTROL_STATE!r}. Bring the agent under ACT's "
                    "control through the agent control-state workflow instead.",
                )
            raise IdentityError(ErrorCode.EXTERNAL_MODE_UNKNOWN,
                                f"{target_mode!r} is not an assignable enforcement mode.")

        if agent.control_state == NATIVE_CONTROL_STATE:
            raise IdentityError(
                ErrorCode.EXTERNAL_MODE_TRANSITION_INVALID,
                "This agent is GOVERNED -- ACT runs and enforces it, so its enforcement mode "
                "is NATIVE_ENFORCED as a matter of fact. Recording a weaker mode would "
                "understate the control ACT genuinely has. Change its control_state instead.",
            )

        if previous == target_mode:
            # Idempotent: re-asserting the current mode is not an error, and
            # must not emit a transition audit event that never happened.
            return describe(agent)

        agent.external_enforcement_mode = target_mode

        # Dropping below GATEWAY_ENFORCED ends the claim that ACT authorizes
        # this agent's boundary calls. Leaving live grants behind would leave
        # credentials for a boundary that, for this agent, now enforces
        # nothing -- so they are revoked here, in the same transaction.
        revoked: list[str] = []
        if previous == "GATEWAY_ENFORCED" and target_mode != "GATEWAY_ENFORCED":
            for grant in self.db.execute(
                select(ExternalCapabilityGrant).where(
                    ExternalCapabilityGrant.agent_id == agent.id,
                    ExternalCapabilityGrant.revoked_at.is_(None),
                )
            ).scalars():
                grant.revoked_at = _now()
                grant.revoked_by = actor.id
                grant.revocation_reason = (
                    f"Enforcement mode changed from GATEWAY_ENFORCED to {target_mode}; "
                    "ACT no longer authorizes this agent's boundary calls.")
                revoked.append(str(grant.id))

        AuthorizationAuditService(self.db).record_change(
            AuthorizationAuditEvent.EXTERNAL_ENFORCEMENT_MODE_CHANGED,
            organization_id=agent.organization_id, actor_id=actor.id, identity_id=agent.id,
            meta={"agent_id": str(agent.id), "previous_mode": previous,
                  "new_mode": target_mode, "control_state": agent.control_state,
                  "reason": reason, "grants_revoked": revoked},
        )
        self.db.commit()
        self.db.refresh(agent)
        return describe(agent)


__all__ = ["EnforcementModeService"]
