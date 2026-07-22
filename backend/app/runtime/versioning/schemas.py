"""Pydantic schemas for the Phase 5.2 Part 1 versioning foundation."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.runtime.versioning.artifacts import ARTIFACT_TYPES
from app.runtime.versioning.notes import NOTE_CATEGORIES

_ARTIFACT_TYPE = Field(pattern="^(" + "|".join(ARTIFACT_TYPES) + ")$")
_NOTE_CATEGORY = Field(default="CHANGED", pattern="^(" + "|".join(NOTE_CATEGORIES) + ")$")


class ReleaseChannelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    is_default: bool
    created_at: datetime


class VersionSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_version_id: uuid.UUID
    snapshot: dict
    checksum: str
    created_at: datetime


class ReleaseMetadataUpsert(BaseModel):
    release_name: str | None = Field(default=None, max_length=255)
    release_description: str | None = None
    business_justification: str | None = None
    change_category: str | None = Field(default=None, pattern="^(MAJOR|MINOR|PATCH|HOTFIX)$")
    release_window_start: datetime | None = None
    release_window_end: datetime | None = None
    support_end_date: datetime | None = None
    approval_ticket: str | None = Field(default=None, max_length=100)
    source_branch: str | None = Field(default=None, max_length=200)
    commit_reference: str | None = Field(default=None, max_length=100)
    build_reference: str | None = Field(default=None, max_length=200)
    risk_score: int | None = Field(default=None, ge=0, le=100)
    documentation_url: str | None = Field(default=None, max_length=500)


class ReleaseMetadataRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_version_id: uuid.UUID
    release_name: str | None
    release_description: str | None
    business_justification: str | None
    change_category: str | None
    release_window_start: datetime | None
    release_window_end: datetime | None
    support_end_date: datetime | None
    approval_ticket: str | None
    source_branch: str | None
    commit_reference: str | None
    build_reference: str | None
    risk_score: int | None
    documentation_url: str | None
    created_at: datetime
    updated_at: datetime


class ReleaseArtifactCreate(BaseModel):
    artifact_type: str = _ARTIFACT_TYPE
    reference: str = Field(min_length=1, max_length=500)


class ReleaseArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_version_id: uuid.UUID
    artifact_type: str
    reference: str
    created_by: uuid.UUID | None
    created_at: datetime


class ReleaseNoteCreate(BaseModel):
    category: str = _NOTE_CATEGORY
    note: str = Field(min_length=1)


class ReleaseNoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_version_id: uuid.UUID
    category: str
    note: str
    created_by: uuid.UUID | None
    created_at: datetime


class VersionStatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_version_id: uuid.UUID
    previous_status: str | None
    new_status: str
    reason: str | None
    changed_by: uuid.UUID | None
    created_at: datetime


class RollbackTargetRequest(BaseModel):
    target_version_id: uuid.UUID


class RevokeVersionRequest(BaseModel):
    reason: str | None = None


class VersionComparisonRead(BaseModel):
    version_a: dict
    version_b: dict
    scalar_changes: dict
    configuration_changes: dict
    list_changes: dict
    artifacts_added: list[dict]
    artifacts_removed: list[dict]
    notes_added: list[dict]
    notes_removed: list[dict]
    identical: bool


class ReadinessCheckRead(BaseModel):
    name: str
    passed: bool
    message: str
    skipped: bool = False


class VersionReadinessRead(BaseModel):
    ready: bool
    checks: list[ReadinessCheckRead]
