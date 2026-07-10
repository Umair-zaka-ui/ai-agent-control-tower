"""Authorization API schemas (Phase 4.3.1 §20)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# --- Permission groups ----------------------------------------------------- #
class PermissionGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    display_name: str
    description: str | None = None
    sort_order: int


# --- Permissions ----------------------------------------------------------- #
class PermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    display_name: str | None = None
    description: str | None = None
    group_id: uuid.UUID | None = None
    resource_type: str | None = None
    action: str | None = None
    is_system: bool
    created_at: datetime | None = None


class PermissionCreate(BaseModel):
    code: str = Field(min_length=3, max_length=100)
    display_name: str | None = None
    description: str | None = None
    group_id: uuid.UUID | None = None


class PermissionUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    group_id: uuid.UUID | None = None


# --- Roles ----------------------------------------------------------------- #
class RoleRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    name: str
    display_name: str | None = None
    description: str | None = None
    category: str
    status: str
    is_system: bool
    is_assignable: bool
    priority: int
    permissions: list[str] = []
    denied_permissions: list[str] = []
    assignment_count: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    display_name: str | None = None
    description: str | None = None
    category: str = "CUSTOM"
    priority: int = Field(default=50, ge=0, le=100)
    permissions: list[str] = []
    # Explicit DENY grants (§16) — a deny always wins over any allow.
    denied_permissions: list[str] = []


class RoleUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    priority: int | None = Field(default=None, ge=0, le=100)
    status: str | None = None
    permissions: list[str] | None = None
    denied_permissions: list[str] | None = None


class EffectivePermissionsRead(BaseModel):
    role_id: uuid.UUID
    permissions: list[str]


# --- Role assignments ------------------------------------------------------ #
class RoleAssignmentCreate(BaseModel):
    user_id: uuid.UUID
    role_id: uuid.UUID
    scope: str = "GLOBAL"
    department_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    expires_at: datetime | None = None


class RoleAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    role_id: uuid.UUID
    scope: str
    organization_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    expires_at: datetime | None = None
    assigned_by: uuid.UUID | None = None
    created_at: datetime | None = None


# --- Role hierarchy -------------------------------------------------------- #
class RoleHierarchyCreate(BaseModel):
    parent_role_id: uuid.UUID
    child_role_id: uuid.UUID


class RoleHierarchyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    parent_role_id: uuid.UUID
    child_role_id: uuid.UUID
    created_at: datetime | None = None


# --- Permission engine: authorization check (§22) -------------------------- #
class AuthorizationCheckRequest(BaseModel):
    permission: str = Field(min_length=1, max_length=100)
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None


class AuthorizationCheckResponse(BaseModel):
    allowed: bool
    permission: str
    reason: str
    scope: str | None = None
    source_role: str | None = None
    evaluation_time_ms: float | None = None
    cache_hit: bool | None = None


# --- Authorization audit --------------------------------------------------- #
class AuthorizationAuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    actor_id: uuid.UUID | None = None
    identity_id: uuid.UUID | None = None
    event_type: str
    permission: str | None = None
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    decision: str | None = None
    reason: str | None = None
    meta: dict | None = None
    created_at: datetime | None = None
