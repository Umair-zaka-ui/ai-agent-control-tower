"""Repositories for the machine identity aggregates (SRS §16).

Agent identities, service accounts and external clients — the non-human
identities — each get their own repository so the service layer never touches
the database directly.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.identity.models.agent_identity import AgentIdentity
from app.identity.models.external_client import ExternalClient
from app.identity.models.service_account import ServiceAccount
from app.identity.repositories.base import BaseRepository


class AgentIdentityRepository(BaseRepository[AgentIdentity]):
    model = AgentIdentity

    def list_by_agent(self, agent_id: uuid.UUID) -> list[AgentIdentity]:
        return list(
            self.db.execute(
                select(AgentIdentity).where(AgentIdentity.agent_id == agent_id)
            ).scalars().all()
        )

    def get_by_client_id(self, client_id: str) -> AgentIdentity | None:
        return self.db.execute(
            select(AgentIdentity).where(AgentIdentity.client_id == client_id)
        ).scalar_one_or_none()


class ServiceAccountRepository(BaseRepository[ServiceAccount]):
    model = ServiceAccount

    def list_by_organization(self, organization_id: uuid.UUID) -> list[ServiceAccount]:
        stmt = (
            select(ServiceAccount)
            .where(ServiceAccount.organization_id == organization_id)
            .order_by(ServiceAccount.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())


class ExternalClientRepository(BaseRepository[ExternalClient]):
    model = ExternalClient

    def list_by_organization(self, organization_id: uuid.UUID) -> list[ExternalClient]:
        stmt = (
            select(ExternalClient)
            .where(ExternalClient.organization_id == organization_id)
            .order_by(ExternalClient.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_by_client_id(self, client_id: str) -> ExternalClient | None:
        return self.db.execute(
            select(ExternalClient).where(ExternalClient.client_id == client_id)
        ).scalar_one_or_none()
