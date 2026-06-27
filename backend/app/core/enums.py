"""Enumerations shared between SQLAlchemy models and Pydantic schemas."""

from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    REVIEWER = "REVIEWER"
    VIEWER = "VIEWER"


class AgentStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"
    BLOCKED = "BLOCKED"


class RiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AgentHealth(str, enum.Enum):
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    OFFLINE = "OFFLINE"


class ActionDecision(str, enum.Enum):
    """Outcome produced by the decision engine for an agent action."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    PENDING_APPROVAL = "PENDING_APPROVAL"


class ActionStatus(str, enum.Enum):
    """Lifecycle status of a stored agent action."""

    CREATED = "CREATED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    BLOCKED = "BLOCKED"


class ApprovalDecision(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ActorType(str, enum.Enum):
    USER = "USER"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"


# --------------------------------------------------------------------------- #
# Phase 2 enums
# --------------------------------------------------------------------------- #
class ApiKeyStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class ApprovalPriority(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# --------------------------------------------------------------------------- #
# Phase 3 Part 3.3 enums (policy management)
# --------------------------------------------------------------------------- #
class PolicySeverity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PolicyStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    ARCHIVED = "ARCHIVED"
