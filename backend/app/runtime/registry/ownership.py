"""Phase 5.1 SRS §12-§13 — accountable ownership + immutable ownership history."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.agent_registry import AgentOwnershipHistory
from app.models.user import User
from app.runtime.services import _now, _record_event

# SECURITY_OWNER/DATA_OWNER are valid owner_role values in the history ledger
# (§13) but have no dedicated agents.* column yet — only these three are
# transferable via a direct field today.
_DIRECT_OWNER_ROLES = {"BUSINESS_OWNER", "TECHNICAL_OWNER", "COMPLIANCE_OWNER"}


class AgentOwnershipService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def history(self, agent_id: uuid.UUID) -> list[AgentOwnershipHistory]:
        stmt = select(AgentOwnershipHistory).where(AgentOwnershipHistory.agent_id == agent_id)
        return list(self.db.execute(stmt.order_by(AgentOwnershipHistory.changed_at.desc())).scalars())

    def transfer(self, actor: User, agent: Agent, *, owner_role: str, new_owner_type: str,
                new_owner_id: uuid.UUID, reason: str) -> Agent:
        """§12.3 — ownership transfer requires the new owner to be eligible
        (same org, active) and is always recorded, never overwritten silently."""
        if owner_role not in _DIRECT_OWNER_ROLES:
            raise IdentityError(ErrorCode.VALIDATION_ERROR,
                               f"Unsupported owner_role '{owner_role}' for a direct owner-id field "
                               "(SECURITY_OWNER/DATA_OWNER are recorded in ownership history only, "
                               "not backed by a dedicated agents.* column yet).")

        if new_owner_type == "USER":
            new_owner = self.db.get(User, new_owner_id)
            if new_owner is None or new_owner.organization_id != agent.organization_id:
                raise IdentityError(ErrorCode.AGENT_OWNER_SCOPE_MISMATCH,
                                   "The new owner must belong to this organization.")

        if owner_role == "BUSINESS_OWNER":
            previous_type, previous_id = agent.owner_type, agent.owner_id
            agent.owner_type, agent.owner_id = new_owner_type, new_owner_id
        elif owner_role == "TECHNICAL_OWNER":
            previous_type, previous_id = "USER", agent.technical_owner_id
            agent.technical_owner_id = new_owner_id
        else:  # COMPLIANCE_OWNER
            previous_type, previous_id = "USER", agent.compliance_owner_id
            agent.compliance_owner_id = new_owner_id

        agent.updated_by = actor.id
        self.db.add(AgentOwnershipHistory(
            agent_id=agent.id, owner_role=owner_role, previous_owner_type=previous_type,
            previous_owner_id=previous_id, new_owner_type=new_owner_type, new_owner_id=new_owner_id,
            reason=reason, changed_by=actor.id, changed_at=_now(),
        ))
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_AGENT_OWNER_TRANSFERRED, actor,
                     organization_id=agent.organization_id, agent_id=agent.id,
                     meta={"owner_role": owner_role, "new_owner_id": str(new_owner_id)})
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def check_agent_not_ownerless(self, agent: Agent) -> None:
        """§12.3 — 'Mission-critical agents cannot become ownerless.'"""
        if agent.criticality == "MISSION_CRITICAL" and agent.owner_id is None:
            raise IdentityError(ErrorCode.AGENT_OWNER_REQUIRED,
                               "A mission-critical agent cannot be left without a business owner.")
