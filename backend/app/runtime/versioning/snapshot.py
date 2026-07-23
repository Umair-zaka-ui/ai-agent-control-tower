"""Phase 5.2 Part 1 SRS §10-14 — the snapshot builder.

Builds the complete, frozen document a version's checksum covers: registry
identity, technical definition, runtime configuration, and everything
attached under release management (metadata, artifacts, notes) at the
moment of publish — the true immutability boundary (§21 "Published Version:
Immutable. Read-only."). Built and stored exactly once, at ``publish()``
(see ``app/runtime/services.py::AgentVersionService.publish``), never
rebuilt or edited afterward (§14: "Forbidden: Edit, Patch, Delete, Overwrite").

Per §12 ("A snapshot must never reference mutable records... copy values"),
every field below is copied by value from the row at build time — nothing
here is a foreign-key reference resolved lazily on read.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.runtime import (
    AgentDefinition,
    AgentReleaseArtifact,
    AgentReleaseChannel,
    AgentReleaseMetadata,
    AgentReleaseNote,
    AgentVersion,
    AgentVersionSnapshot,
)


def build_snapshot(agent: Agent, definition: AgentDefinition, version: AgentVersion, *,
                   release_channel: AgentReleaseChannel | None,
                   release_metadata: AgentReleaseMetadata | None,
                   artifacts: list[AgentReleaseArtifact],
                   notes: list[AgentReleaseNote], publisher_id: uuid.UUID | None) -> dict:
    return {
        "identity": {
            "agent_id": str(agent.id),
            "agent_name": agent.name,
            "organization_id": str(agent.organization_id),
            "project_id": str(agent.project_id) if agent.project_id else None,
            "owner_id": str(agent.owner_id) if agent.owner_id else None,
            "criticality": agent.criticality,
            "data_classification": agent.data_classification,
        },
        "definition": {
            "framework": definition.framework,
            "framework_version": definition.framework_version,
            "entrypoint_type": definition.entrypoint_type,
            "entrypoint": definition.entrypoint,
            "runtime_language": definition.runtime_language,
            "system_instructions": definition.system_instructions,
            "configuration_schema": definition.configuration_schema,
            "input_schema": definition.input_schema,
            "output_schema": definition.output_schema,
        },
        "runtime": {
            "model_configuration": version.model_configuration,
            "configuration_snapshot": version.configuration_snapshot,
            "prompt_snapshot": version.prompt_snapshot,
            "capabilities_snapshot": version.capabilities_snapshot,
            "tools_snapshot": version.tools_snapshot,
            "policy_snapshot": version.policy_snapshot,
        },
        "release": {
            "version": version.version,
            "semantic_version": version.semantic_version,
            "release_channel": release_channel.name if release_channel else None,
            "release_branch": version.release_branch,
            "release_notes_summary": version.release_notes,
            "release_metadata": {
                "release_name": release_metadata.release_name,
                "release_description": release_metadata.release_description,
                "business_justification": release_metadata.business_justification,
                "change_category": release_metadata.change_category,
                # Phase 5.2.4 — ISO-8601 strings, not raw datetime objects: the
                # old checksum_of() tolerated the latter via json.dumps(...,
                # default=str), which silently used Python's non-portable
                # str(datetime) formatting. canonical.py refuses to guess a
                # portable representation for an unsupported type, so the
                # producer (here) must hand it one.
                "release_window_start": (release_metadata.release_window_start.isoformat()
                                        if release_metadata.release_window_start else None),
                "release_window_end": (release_metadata.release_window_end.isoformat()
                                      if release_metadata.release_window_end else None),
                "support_end_date": (release_metadata.support_end_date.isoformat()
                                    if release_metadata.support_end_date else None),
                "approval_ticket": release_metadata.approval_ticket,
                "source_branch": release_metadata.source_branch,
                "commit_reference": release_metadata.commit_reference,
                "build_reference": release_metadata.build_reference,
                "risk_score": release_metadata.risk_score,
                "documentation_url": release_metadata.documentation_url,
            } if release_metadata else None,
            "artifacts": [{"artifact_type": a.artifact_type, "reference": a.reference} for a in artifacts],
            "notes": [{"category": n.category, "note": n.note} for n in notes],
            "publisher": str(publisher_id) if publisher_id else None,
            "created_time": version.created_at.isoformat() if version.created_at else None,
        },
    }


def _legacy_checksum_of(snapshot: dict) -> str:
    """Deprecated (Phase 5.2.4) — the original snapshot-checksum routine.
    Kept only to verify snapshot rows whose ``checksum_algorithm`` is still
    ``'legacy-sha256'``; see ``app/runtime/services.py::_legacy_checksum``
    for the equivalent on the version row itself."""
    blob = json.dumps(snapshot, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def checksum_of(snapshot: dict) -> str:
    """Phase 5.2.4 — ``canonical-sha256`` digest of the frozen snapshot
    document. Every value in ``snapshot`` must already be a portable,
    JSON-native representation (ISO-8601 strings for dates — see
    ``build_snapshot()`` above — no raw floats); ``canonical.py`` raises
    rather than guessing a representation for anything else."""
    from app.runtime.versioning import canonical

    return canonical.digest(canonical.stringify_floats(snapshot))


class SnapshotBuilderService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def build_and_store(self, agent: Agent, definition: AgentDefinition, version: AgentVersion,
                        *, release_channel: AgentReleaseChannel | None, publisher_id: uuid.UUID | None
                        ) -> AgentVersionSnapshot:
        release_metadata = self.db.execute(
            select(AgentReleaseMetadata).where(AgentReleaseMetadata.agent_version_id == version.id)
        ).scalar_one_or_none()
        artifacts = list(self.db.execute(
            select(AgentReleaseArtifact).where(AgentReleaseArtifact.agent_version_id == version.id)
        ).scalars())
        notes = list(self.db.execute(
            select(AgentReleaseNote).where(AgentReleaseNote.agent_version_id == version.id)
        ).scalars())

        document = build_snapshot(agent, definition, version, release_channel=release_channel,
                                  release_metadata=release_metadata, artifacts=artifacts, notes=notes,
                                  publisher_id=publisher_id)
        checksum = checksum_of(document)
        snapshot = AgentVersionSnapshot(agent_version_id=version.id, snapshot=document, checksum=checksum,
                                        checksum_algorithm="canonical-sha256")
        self.db.add(snapshot)
        self.db.flush()
        version.snapshot_reference = f"snapshot:{snapshot.id}"
        return snapshot
