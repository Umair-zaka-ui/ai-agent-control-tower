"""Phase 5.2 Part 1 SRS §3, §30 — promotion readiness.

A read-only diagnostic: evaluates §30's "Version Readiness" checklist and
reports which conditions are (and aren't) met, without changing anything.
Compatibility analysis is explicitly deferred to Part 3 (§30's own
footnote) — that check is reported as skipped, never as a failure, so it
can never block readiness on work this part doesn't do.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.runtime import (
    AgentDefinition,
    AgentReleaseArtifact,
    AgentReleaseChannel,
    AgentReleaseMetadata,
    AgentVersion,
)
from app.runtime.versioning.snapshot import build_snapshot


class VersionReadinessService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def check(self, agent: Agent, version: AgentVersion) -> dict:
        from app.runtime.registry.validation import has_blocking_findings
        from app.runtime.services import _checksum

        checks: list[dict] = []

        def add(name: str, passed: bool, message: str, *, skipped: bool = False) -> None:
            checks.append({"name": name, "passed": passed, "message": message, "skipped": skipped})

        # §30 "Snapshot creation succeeds" — a dry run; never persisted.
        try:
            definition = self.db.get(AgentDefinition, version.definition_id)
            channel = (self.db.get(AgentReleaseChannel, version.release_channel_id)
                      if version.release_channel_id else None)
            metadata = self.db.execute(
                select(AgentReleaseMetadata).where(AgentReleaseMetadata.agent_version_id == version.id)
            ).scalar_one_or_none()
            artifacts = list(self.db.execute(
                select(AgentReleaseArtifact).where(AgentReleaseArtifact.agent_version_id == version.id)
            ).scalars())
            build_snapshot(agent, definition, version, release_channel=channel, release_metadata=metadata,
                           artifacts=artifacts, notes=[], publisher_id=None)
            add("snapshot_creation", True, "The release snapshot can be built.")
        except Exception as exc:  # noqa: BLE001 — reported as a failed check, not raised
            add("snapshot_creation", False, f"Snapshot could not be built: {exc}")

        # §30 "Validation passes" — the same checks AgentVersionService.validate() runs.
        errors = []
        if not version.model_configuration or not version.model_configuration.get("provider"):
            errors.append("model_configuration.provider is required")
        if _checksum(version) != version.checksum:
            errors.append("checksum mismatch — snapshot was modified after creation")
        add("validation_passed", not errors, "; ".join(errors) or "model_configuration and checksum are valid.")

        # §30 "Required metadata is complete".
        meta = self.db.execute(
            select(AgentReleaseMetadata).where(AgentReleaseMetadata.agent_version_id == version.id)
        ).scalar_one_or_none()
        metadata_ok = bool(meta and meta.release_name and meta.change_category)
        add("metadata_complete", metadata_ok,
           "release_name and change_category are set." if metadata_ok
           else "Attach release metadata with at least release_name and change_category.")

        # §30 "Required owners are assigned".
        add("owners_assigned", agent.owner_id is not None,
           "Business owner is assigned." if agent.owner_id else "Agent has no business owner.")

        # §30 "Registry status is Active".
        add("registry_active", agent.lifecycle_status == "ACTIVE",
           "Agent is ACTIVE." if agent.lifecycle_status == "ACTIVE"
           else f"Agent is {agent.lifecycle_status}, not ACTIVE.")

        # §30 "No blocking governance findings exist" — reuses the Phase 5.1
        # registry validation engine's most recent run for this agent.
        from app.models.agent_registry import AgentValidationRun
        latest_run = self.db.execute(
            select(AgentValidationRun).where(AgentValidationRun.agent_id == agent.id)
            .order_by(AgentValidationRun.created_at.desc()).limit(1)
        ).scalar_one_or_none()
        blocking = latest_run is not None and has_blocking_findings(latest_run)
        add("no_blocking_governance_findings", not blocking,
           "No blocking findings." if not blocking else "The latest agent validation run has blocking findings.")

        # §30 "Required artifacts are present".
        artifact_count = len(self.db.execute(
            select(AgentReleaseArtifact.id).where(AgentReleaseArtifact.agent_version_id == version.id)
        ).all())
        add("artifacts_present", artifact_count > 0,
           f"{artifact_count} artifact(s) attached." if artifact_count
           else "No release artifacts attached yet.")

        # §30 "Compatibility analysis completes successfully (implemented in Part 3)".
        add("compatibility_analysis", True,
           "Deferred to Part 3 — not evaluated in this part.", skipped=True)

        # §30 "Approval prerequisites are satisfied".
        approved = version.status in ("APPROVED", "PUBLISHED", "DEPRECATED") or version.reviewed_by is not None
        add("approval_prerequisites_satisfied", approved,
           "Version has been approved." if approved else "Version has not yet been approved.")

        ready = all(c["passed"] for c in checks if not c["skipped"])
        return {"ready": ready, "checks": checks}
