"""Organization hierarchy API schemas (Phase 4.3.3 §15)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    slug: str | None = None
    status: str
    owner_id: uuid.UUID | None = None
    created_at: datetime | None = None


class OrganizationWrite(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = None
    status: str | None = None
    owner_id: uuid.UUID | None = None


class BusinessUnitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    manager_id: uuid.UUID | None = None
    status: str


class BusinessUnitWrite(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    manager_id: uuid.UUID | None = None
    status: str | None = None


class DepartmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    organization_id: uuid.UUID
    business_unit_id: uuid.UUID | None = None
    name: str
    manager_id: uuid.UUID | None = None
    status: str


class DepartmentWrite(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    manager_id: uuid.UUID | None = None
    business_unit_id: uuid.UUID | None = None
    status: str | None = None


class TeamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    department_id: uuid.UUID
    name: str
    lead_id: uuid.UUID | None = None
    status: str


class TeamWrite(BaseModel):
    department_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    lead_id: uuid.UUID | None = None
    status: str | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    team_id: uuid.UUID
    name: str
    owner_id: uuid.UUID | None = None
    status: str


class ProjectWrite(BaseModel):
    team_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    owner_id: uuid.UUID | None = None
    status: str | None = None


# --- Resource ownership (§6) ----------------------------------------------- #
class ResourceOwnershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    resource_type: str
    resource_id: uuid.UUID
    organization_id: uuid.UUID
    business_unit_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None


class ResourceOwnershipAssign(BaseModel):
    resource_type: str = Field(min_length=1, max_length=50)
    resource_id: uuid.UUID
    project_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None


class OwnershipTransfer(BaseModel):
    resource_type: str
    resource_id: uuid.UUID
    new_owner_id: uuid.UUID


# --- Delegation (§10) ------------------------------------------------------ #
class DelegationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    organization_id: uuid.UUID
    delegator_id: uuid.UUID | None = None
    delegatee_id: uuid.UUID
    scope_type: str
    scope_id: uuid.UUID | None = None
    permission: str | None = None
    created_at: datetime | None = None
    revoked_at: datetime | None = None


class DelegationCreate(BaseModel):
    delegatee_id: uuid.UUID
    scope_type: str
    scope_id: uuid.UUID | None = None
    permission: str | None = None
