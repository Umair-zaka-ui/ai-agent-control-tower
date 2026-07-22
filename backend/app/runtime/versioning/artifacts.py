"""Phase 5.2 Part 1 SRS §27 — release artifact references.

References only (an OCI image digest, a git commit SHA, a build pipeline
ID, ...) — no binaries are embedded or stored. Many per version.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.models.runtime import AgentReleaseArtifact, AgentVersion
from app.models.user import User
from app.runtime.services import _record_event
from app.runtime.versioning.locking import ensure_not_locked

ARTIFACT_TYPES = (
    "OCI_IMAGE_DIGEST", "GIT_COMMIT_SHA", "BUILD_PIPELINE_ID", "MODEL_PACKAGE",
    "PROMPT_PACKAGE", "CONFIG_BUNDLE", "SBOM_REFERENCE", "SIGNATURE_REFERENCE",
)


class ReleaseArtifactService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, version_id: uuid.UUID) -> list[AgentReleaseArtifact]:
        stmt = select(AgentReleaseArtifact).where(AgentReleaseArtifact.agent_version_id == version_id)
        return list(self.db.execute(stmt.order_by(AgentReleaseArtifact.created_at.desc())).scalars())

    def add(self, actor: User, agent_id: uuid.UUID, version: AgentVersion, *,
           artifact_type: str, reference: str) -> AgentReleaseArtifact:
        ensure_not_locked(version)
        artifact = AgentReleaseArtifact(agent_version_id=version.id, artifact_type=artifact_type,
                                        reference=reference, created_by=actor.id)
        self.db.add(artifact)
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_VERSION_ARTIFACT_ADDED, actor,
                     organization_id=actor.organization_id, agent_id=agent_id,
                     meta={"version_id": str(version.id), "artifact_type": artifact_type})
        self.db.commit()
        self.db.refresh(artifact)
        return artifact
