"""Phase 5.2 Part 1 SRS §3 — version comparison.

A read-only structural diff between two versions of the same agent —
scalars are compared directly, JSONB configuration fields get a
key-level added/removed/changed breakdown, and list-shaped snapshots
(capabilities/tools) are compared as sets. Works regardless of either
version's lifecycle status (a DRAFT can be compared against a PUBLISHED
version, e.g. to preview what a pending change would alter).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.identity.errors import ErrorCode, IdentityError
from app.models.runtime import (
    AgentReleaseArtifact,
    AgentReleaseChannel,
    AgentReleaseMetadata,
    AgentReleaseNote,
    AgentVersion,
)

_SCALAR_FIELDS = ("semantic_version", "status", "release_branch", "release_notes")
_DICT_FIELDS = ("configuration_snapshot", "model_configuration", "policy_snapshot")
_LIST_FIELDS = ("capabilities_snapshot", "tools_snapshot")


def _diff_dict(a: dict | None, b: dict | None) -> dict:
    a, b = a or {}, b or {}
    added = {k: v for k, v in b.items() if k not in a}
    removed = {k: v for k, v in a.items() if k not in b}
    changed = {k: {"from": a[k], "to": b[k]} for k in a if k in b and a[k] != b[k]}
    return {"added": added, "removed": removed, "changed": changed}


def _diff_list(a: list, b: list) -> dict:
    a_set, b_set = set(a or []), set(b or [])
    return {"added": sorted(b_set - a_set), "removed": sorted(a_set - b_set)}


class VersionComparisonService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def compare(self, version_a: AgentVersion, version_b: AgentVersion) -> dict:
        if version_a.agent_id != version_b.agent_id:
            raise IdentityError(ErrorCode.VALIDATION_ERROR,
                                "Versions must belong to the same agent to be compared.")

        scalars = {}
        for field in _SCALAR_FIELDS:
            a_value, b_value = getattr(version_a, field), getattr(version_b, field)
            if a_value != b_value:
                scalars[field] = {"from": a_value, "to": b_value}

        dicts = {field: _diff_dict(getattr(version_a, field), getattr(version_b, field))
                for field in _DICT_FIELDS}
        dicts = {k: v for k, v in dicts.items() if v["added"] or v["removed"] or v["changed"]}

        lists = {field: _diff_list(getattr(version_a, field), getattr(version_b, field))
                for field in _LIST_FIELDS}
        lists = {k: v for k, v in lists.items() if v["added"] or v["removed"]}

        channel_a = self.db.get(AgentReleaseChannel, version_a.release_channel_id) \
            if version_a.release_channel_id else None
        channel_b = self.db.get(AgentReleaseChannel, version_b.release_channel_id) \
            if version_b.release_channel_id else None
        if (channel_a.name if channel_a else None) != (channel_b.name if channel_b else None):
            scalars["release_channel"] = {
                "from": channel_a.name if channel_a else None, "to": channel_b.name if channel_b else None,
            }

        artifacts_a = {(a.artifact_type, a.reference) for a in self.db.query(AgentReleaseArtifact).filter(
            AgentReleaseArtifact.agent_version_id == version_a.id)}
        artifacts_b = {(a.artifact_type, a.reference) for a in self.db.query(AgentReleaseArtifact).filter(
            AgentReleaseArtifact.agent_version_id == version_b.id)}

        notes_a = {(n.category, n.note) for n in self.db.query(AgentReleaseNote).filter(
            AgentReleaseNote.agent_version_id == version_a.id)}
        notes_b = {(n.category, n.note) for n in self.db.query(AgentReleaseNote).filter(
            AgentReleaseNote.agent_version_id == version_b.id)}

        meta_a = self.db.query(AgentReleaseMetadata).filter(
            AgentReleaseMetadata.agent_version_id == version_a.id).one_or_none()
        meta_b = self.db.query(AgentReleaseMetadata).filter(
            AgentReleaseMetadata.agent_version_id == version_b.id).one_or_none()
        release_name_a = meta_a.release_name if meta_a else None
        release_name_b = meta_b.release_name if meta_b else None
        if release_name_a != release_name_b:
            scalars["release_name"] = {"from": release_name_a, "to": release_name_b}

        return {
            "version_a": {"id": str(version_a.id), "version": version_a.version,
                         "semantic_version": version_a.semantic_version},
            "version_b": {"id": str(version_b.id), "version": version_b.version,
                         "semantic_version": version_b.semantic_version},
            "scalar_changes": scalars,
            "configuration_changes": dicts,
            "list_changes": lists,
            "artifacts_added": [{"artifact_type": t, "reference": r} for t, r in sorted(artifacts_b - artifacts_a)],
            "artifacts_removed": [{"artifact_type": t, "reference": r} for t, r in sorted(artifacts_a - artifacts_b)],
            "notes_added": [{"category": c, "note": n} for c, n in sorted(notes_b - notes_a)],
            "notes_removed": [{"category": c, "note": n} for c, n in sorted(notes_a - notes_b)],
            "identical": not (scalars or dicts or lists or artifacts_a != artifacts_b or notes_a != notes_b),
        }
