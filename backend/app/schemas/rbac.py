"""RBAC schemas: roles, permissions and role assignment."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RbacPermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    description: str | None


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None
    name: str
    description: str | None
    is_system: bool
    created_at: datetime
    updated_at: datetime


class RoleWithPermissions(RoleRead):
    permissions: list[str] = Field(default_factory=list)


class AssignRoleRequest(BaseModel):
    role_id: uuid.UUID


class MyPermissionsResponse(BaseModel):
    role: str
    permissions: list[str]
