"""Phase 5.1 SRS §70-§73 — legacy-agent migration classification.

There is no external pre-registry system in this codebase to migrate
*from* — the ``agents`` table already **is** the one registry, and always
has been (Phase 5.0's own module docstring says as much). So "legacy agent"
here means exactly one thing: a row created under Phase 5.0's simpler
registration flow (3 fields, no mandatory ownership/identity) before this
phase shipped its richer requirements. This service classifies those rows
against the SRS §71 categories and opportunistically backfills what it can
derive (the org-hierarchy columns, from ``project_id``) without forcing any
currently-``ACTIVE`` agent out of that state — see §70's own diagram, which
ends at "Manual Review," not at an automatic state change.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.models.agent_identity import AgentIdentity
from app.models.agent import Agent
from app.models.agent_registry import AgentMigrationRecord
from app.models.organization_hierarchy import Project
from app.models.runtime import AgentDefinition
from app.models.user import User
from app.runtime.services import _derive_org_hierarchy, _now

LEGACY_SOURCE = "PHASE_5_0_REGISTRY"


class AgentMigrationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def classify_all(self, actor: User) -> list[AgentMigrationRecord]:
        """§70 — inventory, map, resolve, classify every agent in the
        organization that has no migration record yet. Idempotent: agents
        already classified in a prior run are skipped, not re-classified,
        so repeated calls are safe."""
        batch_id = f"batch-{uuid.uuid4().hex[:12]}"
        already_classified = {
            row[0] for row in self.db.execute(
                select(AgentMigrationRecord.agent_id).where(
                    AgentMigrationRecord.agent_id.in_(
                        select(Agent.id).where(Agent.organization_id == actor.organization_id)
                    )
                )
            ).all()
        }
        stmt = select(Agent).where(Agent.organization_id == actor.organization_id)
        if already_classified:
            stmt = stmt.where(Agent.id.notin_(already_classified))
        agents = list(self.db.execute(stmt).scalars())

        records = []
        for agent in agents:
            record = self._classify_one(actor, agent, batch_id)
            self.db.add(record)
            records.append(record)
        self.db.commit()
        for r in records:
            self.db.refresh(r)
        return records

    def _classify_one(self, actor: User, agent: Agent, batch_id: str) -> AgentMigrationRecord:
        warnings: list[str] = []
        status = "MIGRATION_READY"

        if agent.organization_id is None:
            status = "MISSING_ORGANIZATION"
        elif agent.owner_id is None:
            status = "MISSING_OWNER"
        elif agent.identity_id is None:
            status = "MISSING_IDENTITY"
        else:
            has_definition = self.db.execute(
                select(AgentDefinition.id).where(AgentDefinition.agent_id == agent.id).limit(1)
            ).first()
            if has_definition is None:
                status = "MISSING_DEFINITION"

        if status == "MIGRATION_READY" and not (agent.description and agent.business_purpose):
            status = "REQUIRES_MANUAL_REVIEW"
            warnings.append("description/business_purpose missing — needed for §19.2 registration "
                            "but not auto-derivable.")

        # Opportunistic backfill: org-hierarchy columns from project_id,
        # regardless of classification outcome — harmless even for agents
        # that also need manual review for other reasons.
        if agent.project_id and not (agent.business_unit_id or agent.department_id or agent.team_id):
            project = self.db.get(Project, agent.project_id)
            if project:
                derived = _derive_org_hierarchy(self.db, project)
                for field, value in derived.items():
                    if value is not None:
                        setattr(agent, field, value)
                warnings.append("business_unit_id/department_id/team_id backfilled from project_id.")

        if agent.identity_id is not None:
            identity = self.db.get(AgentIdentity, agent.identity_id)
            if identity is None or identity.status != "ACTIVE":
                status = "INVALID"
                warnings.append("identity_id references a missing or inactive identity.")

        return AgentMigrationRecord(
            agent_id=agent.id, migration_batch_id=batch_id, legacy_source=LEGACY_SOURCE,
            legacy_id=str(agent.id), migration_status=status, mapping_warnings=warnings,
            migrated_by=actor.id, migrated_at=_now(),
        )

    def list_records(self, actor: User, *, batch_id: str | None = None) -> list[AgentMigrationRecord]:
        stmt = select(AgentMigrationRecord).join(
            Agent, Agent.id == AgentMigrationRecord.agent_id
        ).where(Agent.organization_id == actor.organization_id)
        if batch_id:
            stmt = stmt.where(AgentMigrationRecord.migration_batch_id == batch_id)
        return list(self.db.execute(stmt.order_by(AgentMigrationRecord.migrated_at.desc())).scalars())
