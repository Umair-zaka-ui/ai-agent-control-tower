"""Phase 5.1 SRS §11 — mandatory machine-identity association, with the
eligibility enforcement Phase 5.0 stored but never checked (``AgentIdentity``
had no uniqueness constraint and its ``status``/``expires_at`` were never
read anywhere — see docs/runtime/registry/identity-association.md).

``AgentIdentity.agent_id`` is NOT NULL and now unique (§11.1 — one identity
per agent) — an identity always belongs to exactly one agent, and no second
row can ever exist for that same agent. So "associate an existing eligible
identity" (SRS §11.2) means an identity already created against *this* agent
(e.g. via the identity module) is now being pointed at by the registry's
``agents.identity_id`` for lifecycle gating; it does not mean pulling from
an unassigned pool. And "replace" (credential rotation) can't mean pointing
at a second pre-existing row for the same agent — there can never be one
under the unique constraint — so it rotates the *existing* row's credential
fields in place instead, keeping the same identity ``id``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.agent_identity import AgentIdentity
from app.models.agent import Agent
from app.models.user import User
from app.runtime.services import _record_event


class AgentIdentityAssociationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _check_eligible(self, agent: Agent, identity: AgentIdentity | None) -> None:
        if identity is None or identity.agent_id != agent.id:
            raise IdentityError(ErrorCode.AGENT_IDENTITY_SCOPE_MISMATCH,
                               "Identity does not belong to this agent.")
        if identity.status != "ACTIVE":
            raise IdentityError(ErrorCode.AGENT_IDENTITY_INVALID, f"Identity is {identity.status}, not ACTIVE.")
        if identity.expires_at and identity.expires_at <= datetime.now(timezone.utc):
            raise IdentityError(ErrorCode.AGENT_IDENTITY_INVALID, "Identity has expired.")

    def associate(self, actor: User, agent: Agent, identity_id: uuid.UUID) -> Agent:
        identity = self.db.get(AgentIdentity, identity_id)
        self._check_eligible(agent, identity)
        if agent.identity_id is not None and agent.identity_id != identity_id:
            raise IdentityError(ErrorCode.AGENT_IDENTITY_ALREADY_ASSIGNED,
                               "This agent already has an associated identity; use replace to change it.")
        agent.identity_id = identity.id
        agent.updated_by = actor.id
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_AGENT_IDENTITY_ASSOCIATED, actor,
                     organization_id=agent.organization_id, agent_id=agent.id,
                     meta={"identity_id": str(identity.id)})
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def create_and_associate(self, actor: User, agent: Agent, *, client_id: str,
                             credential_type: str = "API_KEY",
                             expires_at: datetime | None = None) -> Agent:
        # §11.1 — one identity per agent (DB-enforced via a unique
        # constraint on agent_id); reject before hitting that constraint
        # with a clear error rather than a raw IntegrityError.
        already = self.db.execute(
            select(AgentIdentity).where(AgentIdentity.agent_id == agent.id)
        ).scalar_one_or_none()
        if already is not None:
            raise IdentityError(ErrorCode.AGENT_IDENTITY_ALREADY_ASSIGNED,
                               "This agent already has a machine identity; use replace to rotate it.")
        existing = self.db.execute(
            select(AgentIdentity).where(AgentIdentity.client_id == client_id)
        ).scalar_one_or_none()
        if existing is not None:
            raise IdentityError(ErrorCode.CONFLICT, "client_id is already in use.")
        identity = AgentIdentity(
            agent_id=agent.id, client_id=client_id, credential_type=credential_type,
            status="ACTIVE", expires_at=expires_at,
        )
        self.db.add(identity)
        self.db.flush()
        agent.identity_id = identity.id
        agent.updated_by = actor.id
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_AGENT_IDENTITY_ASSOCIATED, actor,
                     organization_id=agent.organization_id, agent_id=agent.id,
                     meta={"identity_id": str(identity.id), "created": True})
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def replace(self, actor: User, agent: Agent, *, client_id: str, credential_type: str = "API_KEY",
               expires_at: datetime | None = None, reason: str) -> Agent:
        if agent.identity_id is None:
            raise IdentityError(ErrorCode.AGENT_IDENTITY_REQUIRED,
                               "This agent has no identity to replace; use create-and-associate first.")
        identity = self.db.get(AgentIdentity, agent.identity_id)
        if identity is None or identity.agent_id != agent.id:
            raise IdentityError(ErrorCode.AGENT_IDENTITY_SCOPE_MISMATCH,
                               "Identity does not belong to this agent.")
        conflict = self.db.execute(
            select(AgentIdentity).where(AgentIdentity.client_id == client_id, AgentIdentity.id != identity.id)
        ).scalar_one_or_none()
        if conflict is not None:
            raise IdentityError(ErrorCode.CONFLICT, "client_id is already in use.")

        previous_client_id = identity.client_id
        identity.client_id = client_id
        identity.credential_type = credential_type
        identity.expires_at = expires_at
        identity.status = "ACTIVE"
        agent.updated_by = actor.id
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_AGENT_IDENTITY_REPLACED, actor,
                     organization_id=agent.organization_id, agent_id=agent.id,
                     meta={"identity_id": str(identity.id), "previous_client_id": previous_client_id,
                          "reason": reason})
        self.db.commit()
        self.db.refresh(agent)
        return agent
