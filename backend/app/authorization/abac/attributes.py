"""ABAC attribute system (Phase 4.3.5 §5, §18–§20).

- ``AttributeRegistryService`` — the central catalog; only registered, enabled
  attributes may appear in policies (§20, §40.4). System attributes are seeded
  idempotently.
- Attribute providers — one per category, each returning a normalized dict of
  fully-qualified attribute names (``identity.id``, ``resource.contains_phi``).
- ``AttributeContextBuilder`` — assembles the complete evaluation context from
  the providers plus request-supplied context; controllers never hand-build
  policy dictionaries (§18).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.abac.enums import (
    AttributeCategory,
    AttributeDataType as DT,
    AttributeSensitivity,
    Operator,
)
from app.identity.errors import ErrorCode, IdentityError
from app.models.abac import AttributeDefinition
from app.models.rbac import Role, UserRole
from app.models.resource_authorization import ProtectedResource
from app.models.user import User

# --------------------------------------------------------------------------- #
# Default operators per data type
# --------------------------------------------------------------------------- #
_PRESENCE = [Operator.EXISTS.value, Operator.NOT_EXISTS.value]
_EQ = [Operator.EQUALS.value, Operator.NOT_EQUALS.value]
_MEMBER = [Operator.IN.value, Operator.NOT_IN.value]
_ORDERED = [
    Operator.GREATER_THAN.value, Operator.GREATER_THAN_OR_EQUAL.value,
    Operator.LESS_THAN.value, Operator.LESS_THAN_OR_EQUAL.value, Operator.BETWEEN.value,
]
_TEXT = [
    Operator.CONTAINS.value, Operator.NOT_CONTAINS.value, Operator.STARTS_WITH.value,
    Operator.ENDS_WITH.value, Operator.MATCHES_REGEX.value,
]

OPERATORS_BY_TYPE: dict[str, list[str]] = {
    DT.BOOLEAN.value: _EQ + _PRESENCE,
    DT.STRING.value: _EQ + _MEMBER + _TEXT + _PRESENCE,
    DT.INTEGER.value: _EQ + _MEMBER + _ORDERED + _PRESENCE,
    DT.DECIMAL.value: _EQ + _MEMBER + _ORDERED + _PRESENCE,
    DT.DATETIME.value: _EQ + _ORDERED + _PRESENCE,
    DT.DATE.value: _EQ + _ORDERED + _PRESENCE,
    DT.TIME.value: _EQ + _ORDERED + _PRESENCE,
    DT.ARRAY.value: [Operator.CONTAINS.value, Operator.NOT_CONTAINS.value] + _EQ + _PRESENCE,
    DT.SET.value: [Operator.CONTAINS.value, Operator.NOT_CONTAINS.value] + _EQ + _PRESENCE,
    DT.OBJECT.value: _PRESENCE,
    DT.NULL.value: _PRESENCE,
}

# --------------------------------------------------------------------------- #
# System attribute catalog (§5) — (name, category, type, sensitivity, description)
# --------------------------------------------------------------------------- #
_S = AttributeCategory.SUBJECT.value
_R = AttributeCategory.RESOURCE.value
_A = AttributeCategory.ACTION.value
_E = AttributeCategory.ENVIRONMENT.value
_I = AttributeCategory.AI.value
_PUB = AttributeSensitivity.PUBLIC.value
_INT = AttributeSensitivity.INTERNAL.value
_RES = AttributeSensitivity.RESTRICTED.value

SYSTEM_ATTRIBUTES: list[tuple[str, str, str, str, str]] = [
    # Subject (§5.1)
    ("identity.id", _S, DT.STRING.value, _INT, "The requesting identity's id"),
    ("identity.type", _S, DT.STRING.value, _PUB, "HUMAN_USER / AI_AGENT / SERVICE_ACCOUNT / EXTERNAL_CLIENT / SYSTEM"),
    ("identity.status", _S, DT.STRING.value, _INT, "Identity lifecycle status"),
    ("identity.roles", _S, DT.ARRAY.value, _INT, "Assigned role names"),
    ("identity.organization_id", _S, DT.STRING.value, _INT, "Tenant id"),
    ("identity.department_id", _S, DT.STRING.value, _INT, "Department id"),
    ("identity.team_id", _S, DT.STRING.value, _INT, "Team id"),
    ("identity.job_title", _S, DT.STRING.value, _INT, "Job title"),
    ("identity.employment_type", _S, DT.STRING.value, _INT, "Employment type"),
    ("identity.clearance_level", _S, DT.STRING.value, _RES, "Security clearance"),
    ("identity.country", _S, DT.STRING.value, _INT, "Country of the identity"),
    ("identity.risk_score", _S, DT.INTEGER.value, _RES, "Latest session/login risk score (0-100)"),
    ("identity.mfa_verified", _S, DT.BOOLEAN.value, _INT, "Strong authentication verified"),
    ("identity.device_trusted", _S, DT.BOOLEAN.value, _INT, "Requesting device is trusted"),
    ("identity.session_age", _S, DT.INTEGER.value, _INT, "Session age in minutes"),
    ("identity.account_age_days", _S, DT.INTEGER.value, _INT, "Days since account creation"),
    # Resource (§5.2)
    ("resource.id", _R, DT.STRING.value, _INT, "Resource id"),
    ("resource.type", _R, DT.STRING.value, _PUB, "Resource type"),
    ("resource.owner_id", _R, DT.STRING.value, _INT, "Resource owner"),
    ("resource.organization_id", _R, DT.STRING.value, _INT, "Resource tenant"),
    ("resource.department_id", _R, DT.STRING.value, _INT, "Resource department (hierarchy path)"),
    ("resource.team_id", _R, DT.STRING.value, _INT, "Resource team (hierarchy path)"),
    ("resource.project_id", _R, DT.STRING.value, _INT, "Resource project"),
    ("resource.classification", _R, DT.STRING.value, _INT, "PUBLIC / INTERNAL / CONFIDENTIAL / RESTRICTED / REGULATED"),
    ("resource.sensitivity", _R, DT.STRING.value, _INT, "LOW / MEDIUM / HIGH / CRITICAL"),
    ("resource.environment", _R, DT.STRING.value, _PUB, "Deployment environment"),
    ("resource.status", _R, DT.STRING.value, _PUB, "Resource status"),
    ("resource.visibility", _R, DT.STRING.value, _PUB, "4.3.4 visibility level"),
    ("resource.tags", _R, DT.ARRAY.value, _INT, "Free-form tags"),
    ("resource.contains_pii", _R, DT.BOOLEAN.value, _RES, "Holds personally identifiable information"),
    ("resource.contains_phi", _R, DT.BOOLEAN.value, _RES, "Holds protected health information"),
    ("resource.contains_financial_data", _R, DT.BOOLEAN.value, _RES, "Holds financial data"),
    ("resource.model_provider", _R, DT.STRING.value, _PUB, "AI model provider"),
    ("resource.model_name", _R, DT.STRING.value, _PUB, "AI model name"),
    ("resource.risk_level", _R, DT.STRING.value, _INT, "Assessed resource risk level"),
    # Action (§5.3)
    ("action.name", _A, DT.STRING.value, _PUB, "Requested permission/action code"),
    ("action.category", _A, DT.STRING.value, _PUB, "Action family (code prefix)"),
    ("action.read_only", _A, DT.BOOLEAN.value, _PUB, "Non-mutating action"),
    ("action.destructive", _A, DT.BOOLEAN.value, _PUB, "Deletes or irreversibly changes data"),
    ("action.external_effect", _A, DT.BOOLEAN.value, _INT, "Has effects outside the platform"),
    ("action.estimated_cost", _A, DT.DECIMAL.value, _INT, "Estimated execution cost"),
    ("action.data_export", _A, DT.BOOLEAN.value, _INT, "Exports data out of the platform"),
    ("action.bulk_operation", _A, DT.BOOLEAN.value, _INT, "Operates on many targets"),
    ("action.target_count", _A, DT.INTEGER.value, _INT, "Number of targets (e.g. export rows)"),
    ("action.execution_mode", _A, DT.STRING.value, _PUB, "Interactive / background / scheduled"),
    # Environment (§5.4)
    ("environment.timestamp", _E, DT.DATETIME.value, _PUB, "Evaluation time (UTC)"),
    ("environment.day_of_week", _E, DT.STRING.value, _PUB, "MONDAY..SUNDAY (UTC)"),
    ("environment.business_hours", _E, DT.BOOLEAN.value, _PUB, "Mon-Fri 09:00-17:00 UTC"),
    ("environment.ip_address", _E, DT.STRING.value, _RES, "Caller IP"),
    ("environment.country", _E, DT.STRING.value, _INT, "Caller country"),
    ("environment.network_zone", _E, DT.STRING.value, _INT, "CORPORATE / TRUSTED_VPN / PARTNER / PUBLIC / UNKNOWN / BLOCKED"),
    ("environment.device_trust", _E, DT.STRING.value, _INT, "TRUSTED / UNTRUSTED / UNKNOWN"),
    ("environment.session_risk", _E, DT.INTEGER.value, _RES, "Session risk score (0-100)"),
    ("environment.request_risk", _E, DT.INTEGER.value, _RES, "Request risk score (0-100)"),
    ("environment.production", _E, DT.BOOLEAN.value, _PUB, "Production environment"),
    ("environment.incident_active", _E, DT.BOOLEAN.value, _INT, "Security incident in progress"),
    ("environment.emergency_mode", _E, DT.BOOLEAN.value, _INT, "Emergency mode engaged"),
    ("environment.vpn_detected", _E, DT.BOOLEAN.value, _INT, "VPN detected"),
    ("environment.request_id", _E, DT.STRING.value, _PUB, "Request correlation id"),
    # AI (§5.5)
    ("ai.agent_id", _I, DT.STRING.value, _INT, "Acting agent id"),
    ("ai.agent_type", _I, DT.STRING.value, _PUB, "Agent type"),
    ("ai.model_provider", _I, DT.STRING.value, _PUB, "Model provider"),
    ("ai.model_name", _I, DT.STRING.value, _PUB, "Model name"),
    ("ai.model_risk_class", _I, DT.STRING.value, _INT, "Model risk classification"),
    ("ai.prompt_classification", _I, DT.STRING.value, _INT, "Prompt content classification"),
    ("ai.output_classification", _I, DT.STRING.value, _INT, "Output content classification"),
    ("ai.confidence_score", _I, DT.DECIMAL.value, _INT, "Model confidence (0-1)"),
    ("ai.hallucination_score", _I, DT.DECIMAL.value, _INT, "Hallucination risk (0-1)"),
    ("ai.toxicity_score", _I, DT.DECIMAL.value, _INT, "Toxicity score (0-1)"),
    ("ai.pii_detected", _I, DT.BOOLEAN.value, _RES, "PII detected in prompt/output"),
    ("ai.phi_detected", _I, DT.BOOLEAN.value, _RES, "PHI detected in prompt/output"),
    ("ai.tool_name", _I, DT.STRING.value, _PUB, "Tool being invoked"),
    ("ai.tool_risk", _I, DT.STRING.value, _INT, "Tool risk level"),
    ("ai.autonomy_level", _I, DT.STRING.value, _INT, "ASSISTIVE..CRITICAL_AUTONOMOUS"),
    ("ai.execution_cost", _I, DT.DECIMAL.value, _INT, "Estimated execution cost"),
    ("ai.external_side_effect", _I, DT.BOOLEAN.value, _INT, "Produces external side effects"),
    ("ai.evaluation_score", _I, DT.DECIMAL.value, _INT, "Agent evaluation score"),
]


# --------------------------------------------------------------------------- #
# Registry service (§20)
# --------------------------------------------------------------------------- #
class AttributeRegistryService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def ensure_system_attributes(self) -> None:
        """Idempotently seed the §5 system catalog."""
        existing = {n for (n,) in self.db.execute(select(AttributeDefinition.name)).all()}
        added = False
        for name, category, data_type, sensitivity, description in SYSTEM_ATTRIBUTES:
            if name in existing:
                continue
            self.db.add(AttributeDefinition(
                name=name, category=category, data_type=data_type,
                description=description, sensitivity=sensitivity,
                supported_operators=OPERATORS_BY_TYPE.get(data_type, _PRESENCE),
                source="system", is_system=True, enabled=True,
            ))
            added = True
        if added:
            self.db.flush()

    def list(self, *, category: str | None = None) -> list[AttributeDefinition]:
        self.ensure_system_attributes()
        q = select(AttributeDefinition).order_by(AttributeDefinition.name)
        if category:
            q = q.where(AttributeDefinition.category == category.upper())
        return list(self.db.execute(q).scalars())

    def by_name(self, name: str) -> AttributeDefinition | None:
        self.ensure_system_attributes()
        return self.db.execute(
            select(AttributeDefinition).where(AttributeDefinition.name == name)
        ).scalar_one_or_none()

    def catalog(self) -> dict[str, AttributeDefinition]:
        return {d.name: d for d in self.list()}

    def create(self, actor_id: uuid.UUID, *, name: str, category: str, data_type: str,
               description: str | None, sensitivity: str,
               supported_operators: list[str] | None) -> AttributeDefinition:
        try:
            AttributeCategory(category.upper())
            DT(data_type.upper())
            AttributeSensitivity(sensitivity.upper())
        except ValueError as exc:
            raise IdentityError(ErrorCode.VALIDATION_ERROR,
                                "Unknown category, data type or sensitivity.") from exc
        if self.by_name(name) is not None:
            raise IdentityError(ErrorCode.ABAC_POLICY_CONFLICT,
                                "An attribute with this name already exists.")
        d = AttributeDefinition(
            name=name, category=category.upper(), data_type=data_type.upper(),
            description=description, sensitivity=sensitivity.upper(),
            supported_operators=supported_operators or OPERATORS_BY_TYPE.get(data_type.upper(), _PRESENCE),
            source="custom", is_system=False, enabled=True,
        )
        self.db.add(d)
        self.db.flush()
        return d

    def update(self, definition_id: uuid.UUID, *, description: str | None,
               sensitivity: str | None, supported_operators: list[str] | None,
               enabled: bool | None) -> AttributeDefinition:
        d = self.db.get(AttributeDefinition, definition_id)
        if d is None:
            raise IdentityError(ErrorCode.ABAC_ATTRIBUTE_NOT_FOUND, "Attribute not found.")
        if description is not None:
            d.description = description
        if sensitivity is not None:
            d.sensitivity = sensitivity.upper()
        if supported_operators is not None:
            d.supported_operators = supported_operators
        if enabled is not None and not d.is_system:
            d.enabled = enabled
        self.db.flush()
        return d


# --------------------------------------------------------------------------- #
# Context (§18) + providers (§19)
# --------------------------------------------------------------------------- #
@dataclass
class AuthorizationAttributeContext:
    """§18 — the normalized evaluation context. Keys inside each dict are
    fully-qualified attribute names."""

    subject: dict[str, Any] = field(default_factory=dict)
    resource: dict[str, Any] = field(default_factory=dict)
    action: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    ai: dict[str, Any] = field(default_factory=dict)

    def flat(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for part in (self.subject, self.resource, self.action, self.environment, self.ai):
            merged.update(part)
        return merged


class SubjectAttributeProvider:
    def __init__(self, db: Session) -> None:
        self.db = db

    def collect(self, user: User) -> dict[str, Any]:
        from app.identity.models.login_history import LoginHistory

        roles = [
            name for (name,) in self.db.execute(
                select(Role.name).join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user.id)
            ).all()
        ]
        roles.append(f"legacy:{user.role.value}")
        risk = self.db.execute(
            select(LoginHistory.risk_score).where(LoginHistory.user_id == user.id)
            .order_by(LoginHistory.created_at.desc()).limit(1)
        ).scalar_one_or_none()
        attrs: dict[str, Any] = {
            "identity.id": str(user.id),
            "identity.type": "HUMAN_USER",
            "identity.status": user.status,
            "identity.roles": roles,
            "identity.organization_id": str(user.organization_id) if user.organization_id else None,
            "identity.department_id": str(user.department_id) if user.department_id else None,
        }
        if user.created_at is not None:
            created = user.created_at if user.created_at.tzinfo else user.created_at.replace(tzinfo=timezone.utc)
            attrs["identity.account_age_days"] = (datetime.now(timezone.utc) - created).days
        if risk is not None:
            attrs["identity.risk_score"] = int(risk)
        return {k: v for k, v in attrs.items() if v is not None}


class ResourceAttributeProvider:
    def __init__(self, db: Session) -> None:
        self.db = db

    def collect(self, resource: ProtectedResource | None) -> dict[str, Any]:
        if resource is None:
            return {}
        from app.authorization.hierarchy.services import ResourceOwnershipService

        path = ResourceOwnershipService(self.db).resolve_path(
            resource.resource_type, resource.resource_id
        ) or {}
        attrs: dict[str, Any] = {
            "resource.id": str(resource.resource_id),
            "resource.type": resource.resource_type,
            "resource.owner_id": str(resource.owner_id),
            "resource.organization_id": str(resource.organization_id),
            "resource.status": resource.status,
            "resource.visibility": resource.visibility,
        }
        for key in ("department_id", "team_id", "project_id"):
            if path.get(key):
                attrs[f"resource.{key}"] = str(path[key])
        return attrs


class ActionAttributeProvider:
    _READ_ACTIONS = {"view", "read", "list", "get"}
    _DESTRUCTIVE = {"delete", "purge", "destroy"}
    _EXPORTS = {"export", "download"}

    def collect(self, action: str) -> dict[str, Any]:
        suffix = action.rsplit(".", 1)[-1].lower()
        return {
            "action.name": action,
            "action.category": action.split(".", 1)[0] if "." in action else action,
            "action.read_only": suffix in self._READ_ACTIONS,
            "action.destructive": suffix in self._DESTRUCTIVE,
            "action.data_export": suffix in self._EXPORTS,
        }


class EnvironmentAttributeProvider:
    _DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]

    def collect(self, *, ip_address: str | None = None, request_id: str | None = None,
                correlation_id: str | None = None) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        attrs: dict[str, Any] = {
            "environment.timestamp": now.isoformat(),
            "environment.day_of_week": self._DAYS[now.weekday()],
            "environment.business_hours": now.weekday() < 5 and 9 <= now.hour < 17,
        }
        if ip_address:
            attrs["environment.ip_address"] = ip_address
        if request_id:
            attrs["environment.request_id"] = request_id
        if correlation_id:
            attrs["environment.correlation_id"] = correlation_id
        return attrs


class AIAttributeProvider:
    """AI attributes (§5.5) originate at the calling gateway (agent runtime,
    model invocation, evaluation pipeline) and arrive as request context."""

    def collect(self) -> dict[str, Any]:
        return {}


class AttributeContextBuilder:
    """§18, §24 — the single place evaluation contexts are assembled. Request
    context is merged on top of provider output, category by category; keys are
    dotted attribute names, so a caller can never smuggle a different
    category's attribute into an override dict."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def build(
        self,
        user: User,
        action: str,
        resource: ProtectedResource | None = None,
        *,
        ip_address: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> AuthorizationAttributeContext:
        ctx = AuthorizationAttributeContext(
            subject=SubjectAttributeProvider(self.db).collect(user),
            resource=ResourceAttributeProvider(self.db).collect(resource),
            action=ActionAttributeProvider().collect(action),
            environment=EnvironmentAttributeProvider().collect(
                ip_address=ip_address, request_id=request_id, correlation_id=correlation_id
            ),
            ai=AIAttributeProvider().collect(),
        )
        for name, value in (overrides or {}).items():
            prefix = name.split(".", 1)[0]
            bucket = {
                "identity": ctx.subject, "resource": ctx.resource, "action": ctx.action,
                "environment": ctx.environment, "ai": ctx.ai,
            }.get(prefix)
            if bucket is not None:
                bucket[name] = value
        return ctx
