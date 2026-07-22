"""Agent Runtime & Lifecycle Management services (Phase 5.0).

Reuses rather than forks existing infrastructure: the ``agents`` table
(Phase 1/3) stays the one agent registry (see ``app/models/runtime.py``
module docstring), and every execution's RBAC/ABAC decision goes through the
same ``AuthorizationGateway`` (Phase 4.3.6) the rest of the platform uses —
its own docstring already names "agent runtime" as a caller.

The execution queue is the ``agent_executions`` table itself (§30: "Postgres
backed queue for development"): a worker claims work with
``SELECT ... FOR UPDATE SKIP LOCKED`` on ``status = 'QUEUED'``. There is no
standalone worker process in this environment — ``ExecutionRequestService``
runs the worker inline, synchronously, right after enqueueing (an "eager
queue", the same trick ``CELERY_TASK_ALWAYS_EAGER`` plays for local dev) so
the feature is fully exercised end-to-end without standing up Celery/Redis.
``ExecutionWorkerService`` itself has no knowledge of that and is equally
correct if pointed at by a real out-of-process polling loop later (see
docs/runtime/workers.md).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import jsonschema
from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.middleware.gateway import AuthorizationGateway
from app.authorization.services import AuthorizationAuditService
from app.core.enums import UserRole
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.department import Department, Team
from app.models.agent import Agent
from app.models.organization_hierarchy import Project
from app.models.runtime import (
    AgentCapability,
    AgentDefinition,
    AgentDeployment,
    AgentExecution,
    AgentTool,
    AgentVersion,
    Capability,
    DeploymentHealth,
    ExecutionAttempt,
    ExecutionLock,
    IdempotencyRecord,
    RuntimeApproval,
    RuntimeEvent,
    Tool,
    ToolCall,
)
from app.models.user import User

# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
# Phase 5.1 SRS §20 — the full 13-state registry lifecycle (supersedes the
# Phase 5.0 8-state version); the transition matrix itself lives in
# app.runtime.registry.services.AgentLifecycleService, which imports this
# constant back rather than redefining it (this module is the one every
# registry submodule already depends on, so the constant lives at the base
# of that dependency, not at the top).
AGENT_LIFECYCLE = ("DRAFT", "REGISTERED", "VALIDATING", "VALIDATION_FAILED", "VALIDATED",
                   "PENDING_APPROVAL", "REJECTED", "APPROVED", "ACTIVE", "SUSPENDED",
                   "DEPRECATED", "ARCHIVED", "RETIRED")
VERSION_LIFECYCLE = ("DRAFT", "VALIDATING", "READY_FOR_REVIEW", "APPROVED",
                     "PUBLISHED", "DEPRECATED", "REVOKED")
DEPLOYMENT_LIFECYCLE = ("CREATED", "PENDING_APPROVAL", "SCHEDULED", "DEPLOYING",
                        "HEALTH_CHECKING", "ACTIVE", "DEGRADED", "FAILED",
                        "SUSPENDED", "ROLLING_BACK", "RETIRED")
TERMINAL_EXECUTION_STATUSES = {"SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTERED",
                               "DENIED", "REJECTED", "BLOCKED", "TIMED_OUT"}
ACTIVE_EXECUTION_STATUSES = {"CREATED", "AUTHORIZING", "PENDING_APPROVAL", "QUEUED",
                             "SCHEDULED", "RUNNING"}
# §27 — the only transitions ``AgentExecution.status`` may make after its
# initial value (set at construction, not a transition). Any assignment not
# listed here is a bug, not a policy choice, so ``_set_execution_status``
# rejects it rather than trusting every call site to only ever assign a
# legal value.
_EXECUTION_TRANSITIONS: dict[str, frozenset[str]] = {
    "CREATED": frozenset({"AUTHORIZING", "CANCELLED"}),
    "AUTHORIZING": frozenset({"DENIED", "BLOCKED", "PENDING_APPROVAL", "QUEUED", "CANCELLED"}),
    "PENDING_APPROVAL": frozenset({"QUEUED", "REJECTED", "CANCELLED"}),
    "QUEUED": frozenset({"RUNNING", "CANCELLED"}),
    "SCHEDULED": frozenset({"QUEUED", "RUNNING", "CANCELLED"}),
    "RUNNING": frozenset({"SUCCEEDED", "FAILED", "QUEUED", "DEAD_LETTERED", "TIMED_OUT", "CANCELLED"}),
    "FAILED": frozenset({"QUEUED"}),
    "TIMED_OUT": frozenset({"QUEUED"}),
    "DEAD_LETTERED": frozenset({"QUEUED"}),
    # Terminal, no outgoing edges: SUCCEEDED, DENIED, BLOCKED, REJECTED, CANCELLED.
}
_PRIORITY_RANK = case(
    (AgentExecution.priority == "CRITICAL", 0),
    (AgentExecution.priority == "HIGH", 1),
    (AgentExecution.priority == "NORMAL", 2),
    (AgentExecution.priority == "LOW", 3),
    else_=2,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


_RESERVED_SLUGS = {"new", "admin", "api", "null", "undefined", "self", "system"}
_SLUG_INVALID_CHARS = re.compile(r"[^a-z0-9-]+")
_SLUG_CONSECUTIVE_HYPHENS = re.compile(r"-{2,}")


def _generate_slug(name: str) -> str:
    """SRS 5.1 §34 — lowercase, letters/numbers/hyphens only, no consecutive
    hyphens, begins with a letter or number, reserved names prohibited."""
    slug = _SLUG_INVALID_CHARS.sub("-", name.strip().lower())
    slug = _SLUG_CONSECUTIVE_HYPHENS.sub("-", slug).strip("-")[:140]
    if not slug or not slug[0].isalnum():
        slug = f"agent-{slug}" if slug else "agent"
    if slug in _RESERVED_SLUGS:
        slug = f"{slug}-agent"
    return slug


def _unique_slug(db: Session, organization_id: uuid.UUID, base_slug: str) -> str:
    slug = base_slug
    suffix = 2
    while db.execute(
        select(Agent.id).where(Agent.organization_id == organization_id, Agent.slug == slug)
    ).first() is not None:
        slug = f"{base_slug}-{suffix}"[:150]
        suffix += 1
    return slug


def _derive_org_hierarchy(db: Session, project: Project) -> dict:
    """SRS 5.1 §6.1 — business_unit_id/department_id/team_id are denormalized
    onto the agent for fast filtering (§47); when not given explicitly they
    default to the selected project's team -> department -> business unit
    chain."""
    team = db.get(Team, project.team_id)
    if team is None:
        return {}
    department = db.get(Department, team.department_id)
    return {
        "team_id": team.id,
        "department_id": department.id if department else None,
        "business_unit_id": department.business_unit_id if department else None,
    }


def _checksum(version: AgentVersion) -> str:
    canonical = {
        "configuration_snapshot": version.configuration_snapshot,
        "prompt_snapshot": version.prompt_snapshot,
        "model_configuration": version.model_configuration,
        "capabilities_snapshot": version.capabilities_snapshot,
        "tools_snapshot": version.tools_snapshot,
        "policy_snapshot": version.policy_snapshot,
    }
    blob = json.dumps(canonical, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _validate_schema(payload: dict, schema: dict, *, what: str) -> None:
    """§7.2 — validates an execution's input/output contract against the
    agent definition's JSON Schema. Raises ``VALIDATION_ERROR`` (a
    non-retryable code — see ``ExecutionWorkerService._fail_or_retry``) on
    mismatch; a malformed schema itself is also a validation error rather
    than a 500, since an admin can fix it the same way."""
    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as exc:
        raise IdentityError(ErrorCode.VALIDATION_ERROR, f"{what} does not match the agent's contract: {exc.message}")
    except jsonschema.SchemaError as exc:
        raise IdentityError(ErrorCode.VALIDATION_ERROR, f"The agent's {what} schema is invalid: {exc.message}")


def _validate_secret_references(secret_references: dict) -> None:
    """§45 — ``secret_references`` must hold reference strings
    (``"vault://production/openai/api-key"``), never raw credential values.
    Every value must parse as ``scheme://path``; anything else (a bare
    string, a number, an empty scheme) is rejected outright rather than
    silently persisted, since a raw secret pasted into this field would
    otherwise sit unencrypted in the deployment row."""
    for key, value in secret_references.items():
        if not isinstance(value, str):
            raise IdentityError(ErrorCode.SECRET_REFERENCE_INVALID,
                               f"secret_references['{key}'] must be a reference string, not {type(value).__name__}.")
        parsed = urlparse(value)
        if not parsed.scheme or not (parsed.netloc or parsed.path):
            raise IdentityError(ErrorCode.SECRET_REFERENCE_INVALID,
                               f"secret_references['{key}'] must be a 'scheme://...' reference "
                               "(e.g. 'vault://production/openai/api-key'), not a raw value.")


def _record_event(db: Session, event: AuthorizationAuditEvent, actor: "User | Agent | None", *,
                  organization_id: uuid.UUID, agent_id: uuid.UUID | None = None,
                  deployment_id: uuid.UUID | None = None,
                  execution_id: uuid.UUID | None = None,
                  severity: str = "INFO", meta: dict | None = None) -> None:
    """Dual-writes the platform audit trail and the runtime event stream
    (§51, §76) that feeds the Operations Center timeline."""
    AuthorizationAuditService(db).record_change(
        event, organization_id=organization_id, actor_id=actor.id if actor else None,
        meta=meta,
    )
    db.add(RuntimeEvent(
        organization_id=organization_id, agent_id=agent_id, deployment_id=deployment_id,
        execution_id=execution_id, event_type=event.value, severity=severity, payload=meta,
    ))


def _set_execution_status(execution: AgentExecution, to_status: str) -> None:
    """§27 — the single choke point every status change goes through. An
    illegal transition (e.g. resurrecting a SUCCEEDED execution, or
    cancelling straight from DENIED) is a bug in the caller, not a
    legitimate outcome, so this fails loudly rather than silently letting
    the row drift into a state the documented machine doesn't recognize."""
    if to_status == execution.status:
        return
    allowed = _EXECUTION_TRANSITIONS.get(execution.status, frozenset())
    if to_status not in allowed:
        raise IdentityError(
            ErrorCode.INVALID_EXECUTION_TRANSITION,
            f"Cannot move execution from {execution.status} to {to_status}.",
        )
    execution.status = to_status


# --------------------------------------------------------------------------- #
# Agent registry & lifecycle (§16, §17, §7.1, §10)
# --------------------------------------------------------------------------- #
class AgentRegistryService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AuthorizationAuditService(db)

    def get_or_404(self, actor: User, agent_id: uuid.UUID) -> Agent:
        agent = self.db.get(Agent, agent_id)
        if agent is None or agent.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.AGENT_NOT_FOUND, "Agent not found.")
        return agent

    def list(self, actor: User, *, lifecycle_status: str | None = None,
             criticality: str | None = None) -> list[Agent]:
        stmt = select(Agent).where(Agent.organization_id == actor.organization_id)
        if lifecycle_status:
            stmt = stmt.where(Agent.lifecycle_status == lifecycle_status)
        if criticality:
            stmt = stmt.where(Agent.criticality == criticality)
        return list(self.db.execute(stmt.order_by(Agent.created_at.desc())).scalars())

    def register(self, actor: User, payload: dict) -> Agent:
        """Creates the initial DRAFT row (SRS 5.1 §19.1) — distinct from the
        ``register`` *lifecycle action* (DRAFT -> REGISTERED), which is
        ``AgentLifecycleService.register`` in ``registry/services.py``."""
        from app.runtime.registry.validation import check_url_for_embedded_credentials

        definition_payload = payload.pop("definition")
        if payload.get("project_id") is not None:
            project = self.db.get(Project, payload["project_id"])
            if project is None:
                raise IdentityError(ErrorCode.VALIDATION_ERROR, "project_id does not exist.")
            derived = _derive_org_hierarchy(self.db, project)
            for field, value in derived.items():
                payload.setdefault(field, value)

        for field in ("documentation_url", "repository_url"):
            findings = check_url_for_embedded_credentials(payload.get(field), field)
            if findings:
                raise IdentityError(ErrorCode.AGENT_ENTRYPOINT_INVALID, findings[0].message)

        slug = payload.get("slug") or _generate_slug(payload["name"])
        payload["slug"] = _unique_slug(self.db, actor.organization_id, slug)

        if payload.get("external_reference"):
            conflict = self.db.execute(
                select(Agent.id).where(Agent.organization_id == actor.organization_id,
                                       Agent.external_reference == payload["external_reference"])
            ).first()
            if conflict:
                raise IdentityError(ErrorCode.AGENT_EXTERNAL_REFERENCE_CONFLICT,
                                   "external_reference is already registered in this organization.")

        agent = Agent(
            organization_id=actor.organization_id,
            agent_type=payload.get("agent_type", "ASSISTANT"),
            api_key_hash="",  # runtime-registered agents authenticate as users, not via API key
            lifecycle_status="DRAFT",
            created_by=actor.id, updated_by=actor.id,
            extra_metadata=payload.pop("metadata", None) or {},
            **{k: v for k, v in payload.items() if k not in ("agent_type", "metadata")},
        )
        self.db.add(agent)
        self.db.flush()
        definition = AgentDefinition(
            agent_id=agent.id,
            extra_metadata=definition_payload.pop("metadata", None),
            created_by=actor.id, updated_by=actor.id,
            **definition_payload,
        )
        self.db.add(definition)
        self.db.flush()
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_AGENT_REGISTERED, actor,
                     organization_id=actor.organization_id, agent_id=agent.id,
                     meta={"agent_id": str(agent.id), "name": agent.name})
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def update(self, actor: User, agent_id: uuid.UUID, payload: dict) -> Agent:
        """SRS 5.1 §53 — optimistic concurrency: the caller must supply the
        ``row_version`` they last read; a mismatch (someone else edited the
        row first) raises ``AGENT_CONCURRENT_MODIFICATION`` before anything
        is written. §19.1/§7 — only editable in ``EDITABLE_STATES``."""
        from app.runtime.registry.services import EDITABLE_STATES
        from app.runtime.registry.validation import check_url_for_embedded_credentials
        from sqlalchemy.orm.exc import StaleDataError

        agent = self.get_or_404(actor, agent_id)
        if agent.lifecycle_status not in EDITABLE_STATES:
            raise IdentityError(ErrorCode.AGENT_NOT_EDITABLE,
                               f"Agent cannot be edited while {agent.lifecycle_status}.")
        row_version = payload.pop("row_version", None)
        if row_version is not None and row_version != agent.row_version:
            raise IdentityError(ErrorCode.AGENT_CONCURRENT_MODIFICATION,
                               "This agent was modified by someone else — reload and retry.")

        for field in ("documentation_url", "repository_url"):
            if field in payload:
                findings = check_url_for_embedded_credentials(payload[field], field)
                if findings:
                    raise IdentityError(ErrorCode.AGENT_ENTRYPOINT_INVALID, findings[0].message)

        metadata = payload.pop("metadata", None)
        if metadata is not None:
            agent.extra_metadata = metadata
        for key, value in payload.items():
            setattr(agent, key, value)
        agent.updated_by = actor.id
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_AGENT_UPDATED, actor,
                     organization_id=agent.organization_id, agent_id=agent.id,
                     meta={"fields": list(payload.keys())})
        try:
            self.db.commit()
        except StaleDataError as exc:
            self.db.rollback()
            raise IdentityError(ErrorCode.AGENT_CONCURRENT_MODIFICATION,
                               "This agent was modified by someone else — reload and retry.") from exc
        self.db.refresh(agent)
        return agent


# --------------------------------------------------------------------------- #
# Agent versions (§11, §12, §17)
# --------------------------------------------------------------------------- #
class AgentVersionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_404(self, actor: User, agent_id: uuid.UUID, version_id: uuid.UUID) -> AgentVersion:
        version = self.db.get(AgentVersion, version_id)
        if version is None or version.agent_id != agent_id:
            raise IdentityError(ErrorCode.AGENT_VERSION_NOT_FOUND, "Agent version not found.")
        return version

    def list(self, agent_id: uuid.UUID) -> list[AgentVersion]:
        stmt = select(AgentVersion).where(AgentVersion.agent_id == agent_id)
        return list(self.db.execute(stmt.order_by(AgentVersion.version.desc())).scalars())

    def create(self, actor: User, agent: Agent, payload: dict) -> AgentVersion:
        definition_id = payload.pop("definition_id", None)
        if definition_id is None:
            latest = self.db.execute(
                select(AgentDefinition).where(AgentDefinition.agent_id == agent.id)
                .order_by(AgentDefinition.created_at.desc()).limit(1)
            ).scalar_one_or_none()
            if latest is None:
                raise IdentityError(ErrorCode.VALIDATION_ERROR, "Agent has no definition.")
            definition_id = latest.id
        else:
            definition = self.db.get(AgentDefinition, definition_id)
            if definition is None or definition.agent_id != agent.id:
                raise IdentityError(ErrorCode.VALIDATION_ERROR, "definition_id does not belong to this agent.")

        capability_ids = payload.pop("capability_ids", [])
        tool_ids = payload.pop("tool_ids", [])
        capabilities_snapshot = [str(c) for c in capability_ids]
        tools_snapshot = [str(t) for t in tool_ids]

        next_version = (self.db.execute(
            select(func.coalesce(func.max(AgentVersion.version), 0)).where(AgentVersion.agent_id == agent.id)
        ).scalar_one() or 0) + 1

        version = AgentVersion(
            agent_id=agent.id, definition_id=definition_id, version=next_version,
            semantic_version=payload.get("semantic_version", "0.1.0"),
            configuration_snapshot=payload.get("model_configuration", {}) or {},
            prompt_snapshot=payload.get("prompt_snapshot"),
            model_configuration=payload.get("model_configuration", {}) or {},
            capabilities_snapshot=capabilities_snapshot,
            tools_snapshot=tools_snapshot,
            policy_snapshot=payload.get("policy_snapshot"),
            release_notes=payload.get("release_notes"),
            created_by=actor.id, checksum="",
        )
        version.checksum = _checksum(version)
        self.db.add(version)
        self.db.flush()

        for capability_id in capability_ids:
            self.db.add(AgentCapability(agent_id=agent.id, agent_version_id=version.id,
                                        capability_id=capability_id, status="REQUESTED"))
        for tool_id in tool_ids:
            self.db.add(AgentTool(agent_id=agent.id, agent_version_id=version.id, tool_id=tool_id,
                                  allowed_actions=["EXECUTE"], status="REQUESTED"))

        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_VERSION_CREATED, actor,
                     organization_id=actor.organization_id, agent_id=agent.id,
                     meta={"agent_id": str(agent.id), "version": next_version})
        self.db.commit()
        self.db.refresh(version)
        return version

    def validate(self, actor: User, agent: Agent, version_id: uuid.UUID) -> AgentVersion:
        version = self.get_or_404(actor, agent.id, version_id)
        if version.status != "DRAFT":
            raise IdentityError(ErrorCode.INVALID_LIFECYCLE_TRANSITION,
                               "Only DRAFT versions can be validated.")
        errors: list[str] = []
        if not version.model_configuration or not version.model_configuration.get("provider"):
            errors.append("model_configuration.provider is required")
        if _checksum(version) != version.checksum:
            errors.append("checksum mismatch — snapshot was modified after creation")
        if errors:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "; ".join(errors))
        version.status = "READY_FOR_REVIEW"
        self.db.commit()
        self.db.refresh(version)
        return version

    def approve(self, actor: User, agent: Agent, version_id: uuid.UUID) -> AgentVersion:
        version = self.get_or_404(actor, agent.id, version_id)
        if version.status != "READY_FOR_REVIEW":
            raise IdentityError(ErrorCode.INVALID_LIFECYCLE_TRANSITION,
                               "Only versions ready for review can be approved.")
        version.status = "APPROVED"
        self.db.commit()
        self.db.refresh(version)
        return version

    def publish(self, actor: User, agent: Agent, version_id: uuid.UUID) -> AgentVersion:
        version = self.get_or_404(actor, agent.id, version_id)
        if version.status != "APPROVED":
            raise IdentityError(ErrorCode.INVALID_LIFECYCLE_TRANSITION,
                               "Only approved versions can be published.")
        if _checksum(version) != version.checksum:
            raise IdentityError(ErrorCode.AGENT_VERSION_IMMUTABLE,
                               "Checksum mismatch — version was tampered with.")
        version.status = "PUBLISHED"
        version.published_at = _now()
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_VERSION_PUBLISHED, actor,
                     organization_id=actor.organization_id, agent_id=agent.id,
                     meta={"agent_id": str(agent.id), "version_id": str(version.id)})
        self.db.commit()
        self.db.refresh(version)
        return version

    def deprecate(self, actor: User, agent: Agent, version_id: uuid.UUID) -> AgentVersion:
        version = self.get_or_404(actor, agent.id, version_id)
        if version.status != "PUBLISHED":
            raise IdentityError(ErrorCode.INVALID_LIFECYCLE_TRANSITION, "Only published versions can be deprecated.")
        version.status = "DEPRECATED"
        version.deprecated_at = _now()
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_VERSION_DEPRECATED, actor,
                     organization_id=actor.organization_id, agent_id=agent.id,
                     meta={"version_id": str(version.id)})
        self.db.commit()
        self.db.refresh(version)
        return version

    def revoke(self, actor: User, agent: Agent, version_id: uuid.UUID) -> AgentVersion:
        version = self.get_or_404(actor, agent.id, version_id)
        if version.status in ("REVOKED",):
            raise IdentityError(ErrorCode.INVALID_LIFECYCLE_TRANSITION, "Version already revoked.")
        version.status = "REVOKED"
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_VERSION_REVOKED, actor,
                     organization_id=actor.organization_id, agent_id=agent.id,
                     meta={"version_id": str(version.id)})
        self.db.commit()
        self.db.refresh(version)
        return version


# --------------------------------------------------------------------------- #
# Deployments (§14, §15, §57)
# --------------------------------------------------------------------------- #
class DeploymentService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_404(self, actor: User, deployment_id: uuid.UUID) -> AgentDeployment:
        deployment = self.db.get(AgentDeployment, deployment_id)
        if deployment is None or deployment.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.DEPLOYMENT_NOT_FOUND, "Deployment not found.")
        return deployment

    def list(self, actor: User, *, agent_id: uuid.UUID | None = None,
             status: str | None = None) -> list[AgentDeployment]:
        stmt = select(AgentDeployment).where(AgentDeployment.organization_id == actor.organization_id)
        if agent_id:
            stmt = stmt.where(AgentDeployment.agent_id == agent_id)
        if status:
            stmt = stmt.where(AgentDeployment.status == status)
        return list(self.db.execute(stmt.order_by(AgentDeployment.updated_at.desc())).scalars())

    def active_for_agent(self, principal: User | Agent, agent_id: uuid.UUID,
                         environment: str | None = None) -> AgentDeployment | None:
        stmt = (select(AgentDeployment)
               .where(AgentDeployment.organization_id == principal.organization_id,
                      AgentDeployment.agent_id == agent_id, AgentDeployment.status == "ACTIVE"))
        if environment:
            stmt = stmt.where(AgentDeployment.environment == environment)
        return self.db.execute(stmt.order_by(AgentDeployment.deployed_at.desc())).scalars().first()

    def create(self, actor: User, agent: Agent, version: AgentVersion, payload: dict) -> AgentDeployment:
        if version.status != "PUBLISHED":
            raise IdentityError(ErrorCode.AGENT_VERSION_NOT_PUBLISHED,
                               "Only published versions can be deployed.")
        _validate_secret_references(payload.get("secret_references") or {})
        deployment = AgentDeployment(
            agent_id=agent.id, agent_version_id=version.id, organization_id=actor.organization_id,
            **payload,
        )
        self.db.add(deployment)
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_CREATED, actor,
                     organization_id=actor.organization_id, agent_id=agent.id,
                     meta={"environment": deployment.environment})
        self.db.commit()
        self.db.refresh(deployment)
        return deployment

    def deploy(self, actor: User, deployment_id: uuid.UUID) -> AgentDeployment:
        """§14 RECREATE strategy — the only strategy actually executed; CANARY/
        BLUE_GREEN/ROLLING are modeled in the data but run as RECREATE (§15)."""
        deployment = self.get_or_404(actor, deployment_id)
        if deployment.status not in ("CREATED", "FAILED", "SUSPENDED"):
            raise IdentityError(ErrorCode.INVALID_LIFECYCLE_TRANSITION,
                               f"Cannot deploy from {deployment.status}.")
        agent = self.db.get(Agent, deployment.agent_id)
        if agent.criticality == "MISSION_CRITICAL" and deployment.environment == "PRODUCTION":
            existing = self.db.execute(
                select(RuntimeApproval).where(
                    RuntimeApproval.deployment_id == deployment.id,
                    RuntimeApproval.requested_action == "DEPLOYMENT",
                    RuntimeApproval.status == "APPROVED",
                )
            ).scalars().first()
            if existing is None:
                deployment.status = "PENDING_APPROVAL"
                self.db.add(RuntimeApproval(
                    organization_id=actor.organization_id, agent_id=agent.id,
                    deployment_id=deployment.id, requested_action="DEPLOYMENT",
                    risk_score=80, reason="Mission-critical production deployment requires approval.",
                    requested_by=actor.id,
                ))
                self.db.commit()
                self.db.refresh(deployment)
                return deployment
        deployment.status = "DEPLOYING"
        deployment.deployed_by = actor.id
        deployment.deployed_at = _now()
        # RECREATE: retire any other active deployment for this agent+environment.
        others = self.db.execute(
            select(AgentDeployment).where(
                AgentDeployment.agent_id == deployment.agent_id,
                AgentDeployment.environment == deployment.environment,
                AgentDeployment.id != deployment.id, AgentDeployment.status == "ACTIVE",
            )
        ).scalars().all()
        for other in others:
            other.status = "RETIRED"
            other.retired_at = _now()
        deployment.status = "HEALTH_CHECKING"
        deployment.active_replicas = deployment.desired_replicas
        deployment.health_status = "HEALTHY"
        deployment.status = "ACTIVE"
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_ACTIVE, actor,
                     organization_id=actor.organization_id, agent_id=deployment.agent_id,
                     deployment_id=deployment.id, meta={"environment": deployment.environment})
        self.db.commit()
        self.db.refresh(deployment)
        return deployment

    def suspend(self, actor: User, deployment_id: uuid.UUID) -> AgentDeployment:
        deployment = self.get_or_404(actor, deployment_id)
        if deployment.status != "ACTIVE":
            raise IdentityError(ErrorCode.DEPLOYMENT_NOT_ACTIVE, "Only active deployments can be suspended.")
        deployment.status = "SUSPENDED"
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_SUSPENDED, actor,
                     organization_id=actor.organization_id, agent_id=deployment.agent_id,
                     deployment_id=deployment.id)
        self.db.commit()
        self.db.refresh(deployment)
        return deployment

    def resume(self, actor: User, deployment_id: uuid.UUID) -> AgentDeployment:
        deployment = self.get_or_404(actor, deployment_id)
        if deployment.status != "SUSPENDED":
            raise IdentityError(ErrorCode.INVALID_LIFECYCLE_TRANSITION, "Only suspended deployments can resume.")
        deployment.status = "ACTIVE"
        self.db.commit()
        self.db.refresh(deployment)
        return deployment

    def rollback(self, actor: User, deployment_id: uuid.UUID, target_version_id: uuid.UUID) -> AgentDeployment:
        deployment = self.get_or_404(actor, deployment_id)
        target = self.db.get(AgentVersion, target_version_id)
        if target is None or target.agent_id != deployment.agent_id:
            raise IdentityError(ErrorCode.AGENT_VERSION_NOT_FOUND, "Target version not found for this agent.")
        if target.status not in ("PUBLISHED", "DEPRECATED"):
            raise IdentityError(ErrorCode.ROLLBACK_NOT_AVAILABLE,
                               "Rollback target must be a previously published version.")
        deployment.status = "ROLLING_BACK"
        deployment.agent_version_id = target.id
        deployment.status = "ACTIVE"
        deployment.updated_at = _now()
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_ROLLED_BACK, actor,
                     organization_id=actor.organization_id, agent_id=deployment.agent_id,
                     deployment_id=deployment.id, meta={"target_version": target.version})
        self.db.commit()
        self.db.refresh(deployment)
        return deployment

    def retire(self, actor: User, deployment_id: uuid.UUID) -> AgentDeployment:
        deployment = self.get_or_404(actor, deployment_id)
        deployment.status = "RETIRED"
        deployment.retired_at = _now()
        deployment.active_replicas = 0
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_RETIRED, actor,
                     organization_id=actor.organization_id, agent_id=deployment.agent_id,
                     deployment_id=deployment.id)
        self.db.commit()
        self.db.refresh(deployment)
        return deployment


# --------------------------------------------------------------------------- #
# Capabilities (§18, §19)
# --------------------------------------------------------------------------- #
class CapabilityService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_catalog(self) -> list[Capability]:
        return list(self.db.execute(select(Capability).order_by(Capability.name)).scalars())

    def create(self, payload: dict) -> Capability:
        existing = self.db.execute(select(Capability).where(Capability.name == payload["name"])).scalar_one_or_none()
        if existing is not None:
            raise IdentityError(ErrorCode.CONFLICT, "A capability with this name already exists.")
        capability = Capability(**payload)
        self.db.add(capability)
        self.db.commit()
        self.db.refresh(capability)
        return capability

    def list_for_agent(self, agent_id: uuid.UUID) -> list[AgentCapability]:
        stmt = select(AgentCapability).where(AgentCapability.agent_id == agent_id)
        return list(self.db.execute(stmt.order_by(AgentCapability.created_at.desc())).scalars())

    def assign(self, actor: User, agent: Agent, payload: dict) -> AgentCapability:
        capability = self.db.get(Capability, payload["capability_id"])
        if capability is None:
            raise IdentityError(ErrorCode.CAPABILITY_NOT_FOUND, "Capability not found.")
        assignment = AgentCapability(
            agent_id=agent.id, agent_version_id=payload.get("agent_version_id"),
            capability_id=capability.id, constraints=payload.get("constraints"),
            status="REQUESTED" if capability.requires_approval else "APPROVED",
        )
        if assignment.status == "APPROVED":
            assignment.approved_by = actor.id
            assignment.approved_at = _now()
        self.db.add(assignment)
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_CAPABILITY_ASSIGNED, actor,
                     organization_id=actor.organization_id, agent_id=agent.id,
                     meta={"capability": capability.name, "status": assignment.status})
        self.db.commit()
        self.db.refresh(assignment)
        return assignment

    def decide(self, actor: User, agent: Agent, assignment_id: uuid.UUID, *, approve: bool) -> AgentCapability:
        assignment = self.db.get(AgentCapability, assignment_id)
        if assignment is None or assignment.agent_id != agent.id:
            raise IdentityError(ErrorCode.CAPABILITY_NOT_FOUND, "Capability assignment not found.")
        assignment.status = "APPROVED" if approve else "DENIED"
        assignment.approved_by = actor.id
        assignment.approved_at = _now()
        self.db.commit()
        self.db.refresh(assignment)
        return assignment

    def revoke(self, actor: User, agent: Agent, assignment_id: uuid.UUID) -> AgentCapability:
        assignment = self.db.get(AgentCapability, assignment_id)
        if assignment is None or assignment.agent_id != agent.id:
            raise IdentityError(ErrorCode.CAPABILITY_NOT_FOUND, "Capability assignment not found.")
        assignment.status = "REVOKED"
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_CAPABILITY_REVOKED, actor,
                     organization_id=actor.organization_id, agent_id=agent.id,
                     meta={"assignment_id": str(assignment_id)})
        self.db.commit()
        self.db.refresh(assignment)
        return assignment


# --------------------------------------------------------------------------- #
# Tools (§20, §23)
# --------------------------------------------------------------------------- #
class ToolRegistryService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_catalog(self, actor: User) -> list[Tool]:
        stmt = select(Tool).where((Tool.organization_id == actor.organization_id) | (Tool.organization_id.is_(None)))
        return list(self.db.execute(stmt.order_by(Tool.name)).scalars())

    def create(self, actor: User, payload: dict) -> Tool:
        tool = Tool(organization_id=actor.organization_id, created_by=actor.id, **payload)
        self.db.add(tool)
        self.db.commit()
        self.db.refresh(tool)
        return tool

    def get_or_404(self, tool_id: uuid.UUID) -> Tool:
        tool = self.db.get(Tool, tool_id)
        if tool is None:
            raise IdentityError(ErrorCode.TOOL_NOT_FOUND, "Tool not found.")
        return tool

    def list_for_agent(self, agent_id: uuid.UUID) -> list[AgentTool]:
        stmt = select(AgentTool).where(AgentTool.agent_id == agent_id)
        return list(self.db.execute(stmt.order_by(AgentTool.created_at.desc())).scalars())

    def assign(self, actor: User, agent: Agent, payload: dict) -> AgentTool:
        tool = self.get_or_404(payload["tool_id"])
        assignment = AgentTool(
            agent_id=agent.id, agent_version_id=payload.get("agent_version_id"), tool_id=tool.id,
            allowed_actions=payload.get("allowed_actions") or ["EXECUTE"],
            constraints=payload.get("constraints"), environment=payload.get("environment"),
            status="REQUESTED" if tool.requires_approval else "APPROVED",
        )
        if assignment.status == "APPROVED":
            assignment.approved_by = actor.id
            assignment.approved_at = _now()
        self.db.add(assignment)
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_TOOL_ASSIGNED, actor,
                     organization_id=actor.organization_id, agent_id=agent.id,
                     meta={"tool": tool.name, "status": assignment.status})
        self.db.commit()
        self.db.refresh(assignment)
        return assignment

    def decide(self, actor: User, agent: Agent, assignment_id: uuid.UUID, *, approve: bool) -> AgentTool:
        assignment = self.db.get(AgentTool, assignment_id)
        if assignment is None or assignment.agent_id != agent.id:
            raise IdentityError(ErrorCode.TOOL_NOT_ASSIGNED, "Tool assignment not found.")
        assignment.status = "APPROVED" if approve else "DENIED"
        assignment.approved_by = actor.id
        assignment.approved_at = _now()
        self.db.commit()
        self.db.refresh(assignment)
        return assignment

    def revoke(self, actor: User, agent: Agent, assignment_id: uuid.UUID) -> AgentTool:
        assignment = self.db.get(AgentTool, assignment_id)
        if assignment is None or assignment.agent_id != agent.id:
            raise IdentityError(ErrorCode.TOOL_NOT_ASSIGNED, "Tool assignment not found.")
        assignment.status = "REVOKED"
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_TOOL_REVOKED, actor,
                     organization_id=actor.organization_id, agent_id=agent.id,
                     meta={"assignment_id": str(assignment_id)})
        self.db.commit()
        self.db.refresh(assignment)
        return assignment


# --------------------------------------------------------------------------- #
# Model Gateway (§40-§42) — provider-neutral, one working adapter (§4.5)
# --------------------------------------------------------------------------- #
class ModelGatewayError(IdentityError):
    pass


class ModelGatewayService:
    """§40 — the only supported provider in this environment is ``MOCK`` (a
    deterministic local adapter, always available); anything else fails
    closed with ``MODEL_PROVIDER_UNAVAILABLE`` rather than silently
    degrading — the same discipline §36 (default deny) applies to model
    providers, not just permissions. With only one real provider, ``invoke``
    has no per-provider branching yet; adding a second (OpenAI/Anthropic/
    Bedrock, §41) means giving ``invoke`` a provider dispatch and adding
    each provider's call there — additive to ``SUPPORTED_PROVIDERS`` and
    ``invoke``, not a rewrite of the surrounding gateway contract (callers
    still just get back ``(output_payload, usage)``)."""

    SUPPORTED_PROVIDERS = {"MOCK"}

    def invoke(self, version: AgentVersion, input_payload: dict) -> tuple[dict, dict]:
        config = version.model_configuration or {}
        provider = (config.get("provider") or "MOCK").upper()
        if provider not in self.SUPPORTED_PROVIDERS:
            raise ModelGatewayError(
                ErrorCode.MODEL_PROVIDER_UNAVAILABLE,
                f"Model provider '{provider}' is not configured in this environment.",
            )
        # Test/simulation hook only — lets the timeout enforcement in
        # ExecutionWorkerService be exercised deterministically without a
        # real slow provider. Never triggered by normal input.
        simulated_delay = input_payload.get("__simulate_slow_seconds__") if isinstance(input_payload, dict) else None
        if simulated_delay:
            time.sleep(float(simulated_delay))
        text_in = json.dumps(input_payload, default=str)
        input_tokens = max(1, len(text_in) // 4)
        output_text = f"[{config.get('model', 'mock-model')}] processed {len(input_payload)} input field(s)."
        output_tokens = max(1, len(output_text) // 4)
        usage = {
            "provider": provider, "model": config.get("model", "mock-model"),
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        output_payload = {"result": output_text, "echo": input_payload}
        return output_payload, usage


# --------------------------------------------------------------------------- #
# Tool Gateway (§43, §44)
# --------------------------------------------------------------------------- #
class ToolGatewayService:
    """§43 — every tool call is validated against the agent's tool
    assignment and constraints (§23) before it runs. Only the ``FUNCTION``
    tool type with the built-in ``EXECUTE``/``READ`` echo actions is
    actually executable in this environment (no outbound network/DB access
    from tool calls is wired up); every other tool type is fully modeled
    (registry, assignment, constraints, authorization) but fails closed
    with ``TOOL_ACTION_NOT_ALLOWED`` if invoked, matching §36 default deny.
    Every attempted call — allowed, denied for constraint violation, or
    denied for an unconnected tool type — is recorded as a ``ToolCall`` row
    so it's auditable regardless of outcome."""

    EXECUTABLE_ACTIONS = {"EXECUTE", "READ"}
    # §22 — Read/Write/Execute/Delete/Export/Administrative. ``read_only``
    # blocks everything but the read-ish actions.
    WRITE_ACTIONS = {"WRITE", "DELETE", "EXPORT", "ADMINISTRATIVE"}

    def invoke(self, db: Session, execution: AgentExecution, agent: Agent,
              tool_name: str, action: str, params: dict) -> ToolCall:
        tool = db.execute(select(Tool).where(
            Tool.name == tool_name,
            (Tool.organization_id == agent.organization_id) | (Tool.organization_id.is_(None)),
        )).scalars().first()
        if tool is None or not tool.enabled:
            raise IdentityError(ErrorCode.TOOL_NOT_FOUND, f"Tool '{tool_name}' not found or disabled.")
        assignment = db.execute(select(AgentTool).where(
            AgentTool.agent_id == agent.id, AgentTool.tool_id == tool.id, AgentTool.status == "APPROVED",
        )).scalars().first()
        if assignment is None:
            raise IdentityError(ErrorCode.TOOL_NOT_ASSIGNED, f"Tool '{tool_name}' is not assigned to this agent.")
        if action not in (assignment.allowed_actions or []):
            raise IdentityError(ErrorCode.TOOL_ACTION_NOT_ALLOWED,
                               f"Action '{action}' is not permitted for tool '{tool_name}'.")

        constraint_violation = self._check_constraints(db, execution, tool, assignment, action)

        started = _now()
        call = ToolCall(execution_id=execution.id, agent_id=agent.id, tool_id=tool.id, action=action,
                        input_summary=params, started_at=started)
        if constraint_violation:
            call.status = "DENIED"
            call.error_code = ErrorCode.TOOL_CONSTRAINT_VIOLATION
        elif tool.tool_type == "FUNCTION" and action in self.EXECUTABLE_ACTIONS:
            call.status = "ALLOWED"
            call.output_summary = {"echo": params}
            call.cost = 0
        else:
            call.status = "DENIED"
            call.error_code = ErrorCode.TOOL_ACTION_NOT_ALLOWED
        call.completed_at = _now()
        call.duration_ms = int((call.completed_at - started).total_seconds() * 1000)
        db.add(call)
        db.flush()
        if call.status == "DENIED":
            if constraint_violation:
                raise IdentityError(ErrorCode.TOOL_CONSTRAINT_VIOLATION, constraint_violation)
            raise IdentityError(ErrorCode.TOOL_ACTION_NOT_ALLOWED,
                               f"Tool type '{tool.tool_type}' is not connected in this environment.")
        return call

    def _check_constraints(self, db: Session, execution: AgentExecution, tool: Tool,
                           assignment: AgentTool, action: str) -> str | None:
        """Returns a violation message, or ``None`` if every constraint (§23)
        passes."""
        constraints = assignment.constraints or {}

        if constraints.get("read_only") and action in self.WRITE_ACTIONS:
            return f"Tool '{tool.name}' is read-only; action '{action}' is not permitted."

        max_calls = constraints.get("maximum_calls_per_execution")
        if max_calls is not None:
            existing = db.execute(
                select(func.count(ToolCall.id)).where(
                    ToolCall.execution_id == execution.id, ToolCall.tool_id == tool.id,
                    ToolCall.status == "ALLOWED",
                )
            ).scalar_one()
            if existing >= max_calls:
                return f"Tool '{tool.name}' call limit ({max_calls} per execution) already reached."

        allowed_domains = constraints.get("allowed_domains")
        if allowed_domains and tool.endpoint_reference:
            domain = urlparse(tool.endpoint_reference).netloc or tool.endpoint_reference
            if domain not in allowed_domains:
                return f"Endpoint domain '{domain}' is not in the allowed list for '{tool.name}'."

        return None


# --------------------------------------------------------------------------- #
# Runtime Policy Engine (§38, §46, §47, §48)
# --------------------------------------------------------------------------- #
class PolicyResult:
    def __init__(self, allowed: bool, requires_approval: bool, reason: str, code: str | None = None):
        self.allowed = allowed
        self.requires_approval = requires_approval
        self.reason = reason
        self.code = code


def _estimate_tokens(input_payload: dict) -> int:
    """Same rough heuristic ``ModelGatewayService`` uses post-hoc, applied
    pre-flight so ``maximum_tokens`` can be enforced before a model is ever
    invoked, not just recorded after the fact."""
    return max(1, len(json.dumps(input_payload, default=str)) // 4)


class RuntimePolicyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def evaluate(self, agent: Agent, version: AgentVersion, deployment: AgentDeployment,
                input_payload: dict | None = None, *,
                exclude_execution_id: uuid.UUID | None = None) -> PolicyResult:
        limits = deployment.runtime_limits or {}
        policy = version.policy_snapshot or {}

        # The execution being evaluated is already flushed (it needs an id
        # for the approval/audit rows created below in request_execution),
        # so every count here must exclude it — otherwise a request always
        # counts against its own limit before it has even been decided.
        def _exclude(stmt):
            if exclude_execution_id is not None:
                return stmt.where(AgentExecution.id != exclude_execution_id)
            return stmt

        max_concurrent = limits.get("maximum_concurrent_executions")
        if max_concurrent is not None:
            running = self.db.execute(_exclude(
                select(func.count(AgentExecution.id)).where(
                    AgentExecution.deployment_id == deployment.id,
                    AgentExecution.status.in_(["QUEUED", "RUNNING", "SCHEDULED"]),
                )
            )).scalar_one()
            if running >= max_concurrent:
                return PolicyResult(False, False, "Deployment concurrency limit reached.",
                                   ErrorCode.RUNTIME_RATE_LIMITED)

        max_per_minute = limits.get("maximum_executions_per_minute")
        if max_per_minute is not None:
            recent = self.db.execute(_exclude(
                select(func.count(AgentExecution.id)).where(
                    AgentExecution.deployment_id == deployment.id,
                    AgentExecution.created_at >= _now() - timedelta(minutes=1),
                )
            )).scalar_one()
            if recent >= max_per_minute:
                return PolicyResult(False, False, "Deployment rate limit (executions/minute) reached.",
                                   ErrorCode.RUNTIME_RATE_LIMITED)

        max_cost = limits.get("maximum_cost")
        if max_cost is not None:
            spent_today = self.db.execute(_exclude(
                select(func.coalesce(func.sum(AgentExecution.cost), 0)).where(
                    AgentExecution.deployment_id == deployment.id,
                    AgentExecution.created_at >= _now().replace(hour=0, minute=0, second=0, microsecond=0),
                )
            )).scalar_one()
            if float(spent_today) >= float(max_cost):
                return PolicyResult(False, False, "Deployment daily cost budget exhausted.",
                                   ErrorCode.RUNTIME_BUDGET_EXCEEDED)

        max_tokens = limits.get("maximum_tokens")
        if max_tokens is not None and input_payload is not None:
            if _estimate_tokens(input_payload) > max_tokens:
                return PolicyResult(False, False, "Estimated input size exceeds the per-execution token limit.",
                                   ErrorCode.RUNTIME_BUDGET_EXCEEDED)

        approved_models = policy.get("approved_models")
        model = (version.model_configuration or {}).get("model")
        if approved_models and model not in approved_models:
            return PolicyResult(False, False, f"Model '{model}' is not on the approved list.",
                               ErrorCode.MODEL_NOT_APPROVED)

        prohibited_envs = policy.get("prohibited_environments", [])
        if deployment.environment in prohibited_envs:
            return PolicyResult(False, False, f"Execution is prohibited in {deployment.environment}.",
                               ErrorCode.RUNTIME_POLICY_DENIED)

        requires_approval_envs = set(policy.get("requires_approval_environments", []))
        needs_approval = deployment.environment in requires_approval_envs or (
            agent.criticality == "MISSION_CRITICAL" and deployment.environment == "PRODUCTION"
        )
        return PolicyResult(True, needs_approval, "Runtime policy evaluation passed.")


# --------------------------------------------------------------------------- #
# Idempotency (§33)
# --------------------------------------------------------------------------- #
class IdempotencyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def check(self, principal: User | Agent, agent_id: uuid.UUID, key: str,
             request_hash: str) -> AgentExecution | None:
        record = self.db.execute(select(IdempotencyRecord).where(
            IdempotencyRecord.organization_id == principal.organization_id,
            IdempotencyRecord.agent_id == agent_id, IdempotencyRecord.idempotency_key == key,
        )).scalars().first()
        if record is None:
            return None
        if record.expires_at < _now():
            self.db.delete(record)
            self.db.flush()
            return None
        if record.request_hash != request_hash:
            raise IdentityError(ErrorCode.IDEMPOTENCY_CONFLICT,
                               "Idempotency key reused with a different request payload.")
        return self.db.get(AgentExecution, record.execution_id)

    def store(self, principal: User | Agent, agent_id: uuid.UUID, key: str, request_hash: str,
             execution_id: uuid.UUID, ttl_hours: int = 24) -> None:
        self.db.add(IdempotencyRecord(
            organization_id=principal.organization_id, identity_id=principal.id, agent_id=agent_id,
            idempotency_key=key, request_hash=request_hash, execution_id=execution_id,
            expires_at=_now() + timedelta(hours=ttl_hours),
        ))


# --------------------------------------------------------------------------- #
# Runtime Gateway / execution requests (§24-§28, §33, §56)
# --------------------------------------------------------------------------- #
def _risk_score(agent: Agent, deployment: AgentDeployment) -> int:
    score = {"LOW": 10, "MEDIUM": 30, "HIGH": 55, "MISSION_CRITICAL": 80}.get(agent.criticality, 30)
    if deployment.environment == "PRODUCTION":
        score += 15
    if agent.data_classification in ("RESTRICTED", "CONFIDENTIAL"):
        score += 10
    return min(score, 100)


class ExecutionRequestService:
    """§24 — the Runtime Gateway: the only supported entry point for
    execution. Walks Authentication -> Agent state -> Deployment -> RBAC/ABAC
    (via the existing ``AuthorizationGateway``) -> Runtime Policy -> Approval
    -> Queue, exactly as §4.4 orders it."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_404(self, actor: User, execution_id: uuid.UUID) -> AgentExecution:
        execution = self.db.get(AgentExecution, execution_id)
        if execution is None or execution.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.EXECUTION_NOT_FOUND, "Execution not found.")
        return execution

    def list(self, actor: User, *, agent_id: uuid.UUID | None = None,
             status: str | None = None, limit: int = 100) -> list[AgentExecution]:
        stmt = select(AgentExecution).where(AgentExecution.organization_id == actor.organization_id)
        if agent_id:
            stmt = stmt.where(AgentExecution.agent_id == agent_id)
        if status:
            stmt = stmt.where(AgentExecution.status == status)
        return list(self.db.execute(
            stmt.order_by(AgentExecution.created_at.desc()).limit(limit)
        ).scalars())

    def request_execution(self, actor: User, payload: dict) -> AgentExecution:
        agent = self.db.get(Agent, payload["agent_id"])
        if agent is None or agent.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.AGENT_NOT_FOUND, "Agent not found.")

        def authorize(deployment: AgentDeployment):
            # RBAC/ABAC (§4.4, §24) — the same gateway every enforcement
            # point uses; its own docstring names "agent runtime" as a caller.
            return AuthorizationGateway(self.db).authorize(
                actor, "runtime.execution.create", resource_type="agent", resource_id=agent.id,
                context={"environment": deployment.environment, "criticality": agent.criticality},
                source="API",
            )

        return self._request_execution(
            agent, payload, principal=actor, trigger_type="API",
            authorize=authorize, worker_id=f"inline-{actor.id}")

    def request_execution_as_agent(self, agent: Agent, payload: dict) -> AgentExecution:
        """§29, §31 — an agent triggering its own next run (e.g. a webhook or
        a tool re-invoking the same agent), authenticated by its own API key
        rather than a human session. Deliberately self-only: an agent may
        request an execution of *itself*, never of another agent — arbitrary
        agent-to-agent chaining is multi-agent orchestration, explicitly
        deferred (see docs/runtime/overview.md's "What's deliberately not
        here")."""
        target_id = payload.get("agent_id")
        if target_id is not None and uuid.UUID(str(target_id)) != agent.id:
            raise IdentityError(ErrorCode.PERMISSION_DENIED,
                               "An agent may only request executions of itself.")
        payload = {**payload, "agent_id": agent.id}

        def authorize(deployment: AgentDeployment):
            # §29, §31 — the agent-principal ABAC layer, not the user RBAC
            # path: an agent has no RBAC role of its own to check.
            return AuthorizationGateway(self.db).authorize_agent(
                agent, "runtime.execution.create",
                ai_context={"environment": deployment.environment, "trigger": "self",
                           "criticality": agent.criticality},
            )

        return self._request_execution(
            agent, payload, principal=agent, trigger_type="AGENT",
            authorize=authorize, worker_id=f"inline-agent-{agent.id}")

    def _request_execution(self, agent: Agent, payload: dict, *, principal: User | Agent,
                           trigger_type: str, authorize, worker_id: str) -> AgentExecution:
        if agent.lifecycle_status == "SUSPENDED":
            raise IdentityError(ErrorCode.AGENT_SUSPENDED, "Agent is suspended.")
        if agent.lifecycle_status not in ("ACTIVE",):
            raise IdentityError(ErrorCode.AGENT_NOT_ACTIVE, "Agent is not active.")

        deployment_id = payload.get("deployment_id")
        deployment = (self.db.get(AgentDeployment, deployment_id) if deployment_id
                     else DeploymentService(self.db).active_for_agent(principal, agent.id))
        if deployment is None or deployment.organization_id != agent.organization_id:
            raise IdentityError(ErrorCode.DEPLOYMENT_NOT_FOUND, "No active deployment for this agent.")
        if deployment.status != "ACTIVE":
            raise IdentityError(ErrorCode.DEPLOYMENT_NOT_ACTIVE, "Deployment is not active.")

        version = self.db.get(AgentVersion, deployment.agent_version_id)
        if version.status == "REVOKED":
            raise IdentityError(ErrorCode.AGENT_VERSION_REVOKED, "Agent version has been revoked.")
        if version.status not in ("PUBLISHED", "DEPRECATED"):
            raise IdentityError(ErrorCode.AGENT_VERSION_NOT_PUBLISHED, "Agent version is not published.")

        # §7.2 — the input contract is validated before an execution is even
        # created; an invalid request never reaches the queue.
        definition = self.db.get(AgentDefinition, version.definition_id)
        if definition.input_schema:
            _validate_schema(payload.get("input_payload", {}), definition.input_schema, what="input_payload")

        idempotency_key = payload.get("idempotency_key")
        request_hash = hashlib.sha256(
            json.dumps(payload.get("input_payload", {}), sort_keys=True, default=str).encode()
        ).hexdigest()
        if idempotency_key:
            existing = IdempotencyService(self.db).check(principal, agent.id, idempotency_key, request_hash)
            if existing is not None:
                return existing

        execution = AgentExecution(
            organization_id=agent.organization_id, agent_id=agent.id, agent_version_id=version.id,
            deployment_id=deployment.id, trigger_type=trigger_type, triggered_by_identity_id=principal.id,
            correlation_id=payload.get("correlation_id"), idempotency_key=idempotency_key,
            input_payload=payload.get("input_payload", {}), priority=payload.get("priority", "NORMAL"),
            status="AUTHORIZING",
        )
        self.db.add(execution)
        self.db.flush()

        decision = authorize(deployment)
        if not decision.allowed:
            _set_execution_status(execution, "DENIED")
            execution.decision = "DENY"
            execution.error_code = ErrorCode.RUNTIME_POLICY_DENIED
            execution.error_message = decision.reason
            execution.completed_at = _now()
            _record_event(self.db, AuthorizationAuditEvent.RUNTIME_EXECUTION_DENIED, principal,
                         organization_id=agent.organization_id, agent_id=agent.id,
                         execution_id=execution.id, severity="WARNING", meta={"reason": decision.reason})
            self.db.commit()
            self.db.refresh(execution)
            return execution

        # Runtime policy (§38, §46-§48).
        policy_result = RuntimePolicyService(self.db).evaluate(
            agent, version, deployment, input_payload=payload.get("input_payload", {}),
            exclude_execution_id=execution.id)
        if not policy_result.allowed:
            _set_execution_status(execution, "BLOCKED")
            execution.decision = "DENY"
            execution.error_code = policy_result.code
            execution.error_message = policy_result.reason
            execution.completed_at = _now()
            _record_event(self.db, AuthorizationAuditEvent.RUNTIME_LIMIT_EXCEEDED, principal,
                         organization_id=agent.organization_id, agent_id=agent.id,
                         execution_id=execution.id, severity="WARNING", meta={"reason": policy_result.reason})
            self.db.commit()
            self.db.refresh(execution)
            return execution

        execution.risk_score = _risk_score(agent, deployment)

        if policy_result.requires_approval:
            _set_execution_status(execution, "PENDING_APPROVAL")
            execution.decision = "REQUIRE_APPROVAL"
            self.db.add(RuntimeApproval(
                organization_id=agent.organization_id, agent_id=agent.id, agent_version_id=version.id,
                deployment_id=deployment.id, execution_id=execution.id, requested_action="EXECUTION",
                risk_score=execution.risk_score, reason="Runtime policy requires human approval.",
                requested_by=principal.id,
            ))
            _record_event(self.db, AuthorizationAuditEvent.RUNTIME_EXECUTION_APPROVAL_REQUIRED, principal,
                         organization_id=agent.organization_id, agent_id=agent.id, execution_id=execution.id)
            self.db.commit()
            self.db.refresh(execution)
            return execution

        _set_execution_status(execution, "QUEUED")
        execution.decision = "ALLOW"
        execution.queued_at = _now()
        if idempotency_key:
            IdempotencyService(self.db).store(principal, agent.id, idempotency_key, request_hash, execution.id)
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_EXECUTION_CREATED, principal,
                     organization_id=agent.organization_id, agent_id=agent.id, execution_id=execution.id)
        self.db.commit()
        self.db.refresh(execution)

        # Eager queue (dev mode, §30) — see module docstring.
        ExecutionWorkerService(self.db).run_once(worker_id)
        self.db.refresh(execution)
        return execution

    def cancel(self, actor: User, execution_id: uuid.UUID) -> AgentExecution:
        execution = self.get_or_404(actor, execution_id)
        if execution.status in TERMINAL_EXECUTION_STATUSES:
            raise IdentityError(ErrorCode.EXECUTION_ALREADY_COMPLETED, "Execution has already completed.")
        if execution.status in ("QUEUED", "PENDING_APPROVAL", "CREATED", "AUTHORIZING", "SCHEDULED"):
            _set_execution_status(execution, "CANCELLED")
            execution.completed_at = _now()
        execution.cancel_requested = True
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_EXECUTION_CANCELLED, actor,
                     organization_id=actor.organization_id, agent_id=execution.agent_id,
                     execution_id=execution.id)
        self.db.commit()
        self.db.refresh(execution)
        return execution

    def retry(self, actor: User, execution_id: uuid.UUID) -> AgentExecution:
        execution = self.get_or_404(actor, execution_id)
        if execution.status not in ("FAILED", "TIMED_OUT", "DEAD_LETTERED"):
            raise IdentityError(ErrorCode.INVALID_LIFECYCLE_TRANSITION,
                               "Only failed/timed-out/dead-lettered executions can be retried.")
        _set_execution_status(execution, "QUEUED")
        execution.queued_at = _now()
        execution.cancel_requested = False
        execution.error_code = None
        execution.error_message = None
        self.db.commit()
        ExecutionWorkerService(self.db).run_once(f"inline-{actor.id}")
        self.db.refresh(execution)
        return execution

    def replay(self, actor: User, execution_id: uuid.UUID) -> AgentExecution:
        original = self.get_or_404(actor, execution_id)
        clone = AgentExecution(
            organization_id=original.organization_id, agent_id=original.agent_id,
            agent_version_id=original.agent_version_id, deployment_id=original.deployment_id,
            trigger_type="REPLAY", triggered_by_identity_id=actor.id,
            parent_execution_id=original.id, input_payload=original.input_payload,
            priority=original.priority, status="QUEUED", decision="ALLOW",
            queued_at=_now(), risk_score=original.risk_score,
        )
        self.db.add(clone)
        self.db.commit()
        self.db.refresh(clone)
        ExecutionWorkerService(self.db).run_once(f"inline-{actor.id}")
        self.db.refresh(clone)
        return clone


# --------------------------------------------------------------------------- #
# Worker runtime (§31-§37)
# --------------------------------------------------------------------------- #
class ExecutionWorkerService:
    """§31, §32 — claims one queued execution with ``SELECT ... FOR UPDATE
    SKIP LOCKED`` so concurrent callers never claim the same row, runs it
    through the Model/Tool Gateways, and applies the retry policy (§34) on
    failure. Safe to call repeatedly from an out-of-process polling loop —
    see the module docstring for how this environment drives it inline."""

    DEFAULT_MAX_ATTEMPTS = 3

    def __init__(self, db: Session) -> None:
        self.db = db

    def reap_expired_locks(self) -> int:
        """§32 — recover from a worker that claimed an execution and then
        never finished (crashed, killed, network partition): its
        ``execution_locks`` lease is never renewed past ``expires_at``, so
        the execution is stuck ``RUNNING`` forever unless something notices.
        Runs the same fail-or-retry policy a normal failure would (requeue
        if attempts remain, else DEAD_LETTERED), drops the stale lock, and
        is called opportunistically at the top of every claim so no separate
        sweeper process is required in this environment."""
        stale = self.db.execute(select(ExecutionLock).where(ExecutionLock.expires_at < _now())).scalars().all()
        reaped = 0
        for lock in stale:
            execution = self.db.get(AgentExecution, lock.execution_id)
            if execution is not None and execution.status == "RUNNING":
                attempt = self.db.execute(
                    select(ExecutionAttempt).where(
                        ExecutionAttempt.execution_id == execution.id,
                        ExecutionAttempt.attempt_number == execution.attempt_count,
                        ExecutionAttempt.status == "RUNNING",
                    )
                ).scalars().first()
                if attempt is not None:
                    # _fail_or_retry already emits the terminal audit/event
                    # (DEAD_LETTERED/FAILED) when attempts are exhausted; a
                    # requeue is silent, same as any other retry.
                    self._fail_or_retry(
                        execution, attempt, "WORKER_UNAVAILABLE",
                        f"Worker '{lock.worker_id}' heartbeat expired without completing this attempt.",
                    )
                    reaped += 1
            self.db.delete(lock)
        if reaped or stale:
            self.db.commit()
        return reaped

    def claim_next(self, worker_id: str) -> AgentExecution | None:
        self.reap_expired_locks()
        stmt = (
            select(AgentExecution)
            .where(AgentExecution.status == "QUEUED")
            .order_by(_PRIORITY_RANK, AgentExecution.queued_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        execution = self.db.execute(stmt).scalars().first()
        if execution is None:
            return None
        _set_execution_status(execution, "RUNNING")
        execution.started_at = _now()
        execution.attempt_count += 1
        self.db.add(ExecutionLock(
            execution_id=execution.id, worker_id=worker_id, expires_at=_now() + timedelta(minutes=5),
        ))
        self.db.add(ExecutionAttempt(
            execution_id=execution.id, attempt_number=execution.attempt_count,
            worker_id=worker_id, status="RUNNING", started_at=_now(),
        ))
        self.db.flush()
        return execution

    def run_once(self, worker_id: str = "inline-worker") -> AgentExecution | None:
        execution = self.claim_next(worker_id)
        if execution is None:
            return None
        try:
            self._execute(execution, worker_id)
        finally:
            self.db.execute(delete(ExecutionLock).where(ExecutionLock.execution_id == execution.id))
            self.db.commit()
        return execution

    def _current_attempt(self, execution: AgentExecution) -> ExecutionAttempt:
        return self.db.execute(
            select(ExecutionAttempt).where(
                ExecutionAttempt.execution_id == execution.id,
                ExecutionAttempt.attempt_number == execution.attempt_count,
            )
        ).scalars().one()

    DEFAULT_TIMEOUT_SECONDS = 300

    def _execute(self, execution: AgentExecution, worker_id: str) -> None:
        attempt = self._current_attempt(execution)
        if execution.cancel_requested:
            _set_execution_status(execution, "CANCELLED")
            execution.completed_at = _now()
            attempt.status = "CANCELLED"
            attempt.completed_at = _now()
            return

        agent = self.db.get(Agent, execution.agent_id)
        version = self.db.get(AgentVersion, execution.agent_version_id)
        deployment = self.db.get(AgentDeployment, execution.deployment_id) if execution.deployment_id else None
        timeout_seconds = ((deployment.runtime_limits or {}).get("maximum_execution_seconds")
                          if deployment else None) or self.DEFAULT_TIMEOUT_SECONDS
        try:
            # §36 — a hung model call must not hang the worker forever. Only
            # the model invocation is time-boxed: it's pure (no DB access),
            # unlike ToolGatewayService.invoke below, which writes through
            # ``self.db`` and is not safe to run on a second thread against
            # the same (non-thread-safe) SQLAlchemy session — a timed-out
            # future is *abandoned*, not killed, so anything it touches
            # keeps running concurrently with the thread that gave up on it.
            # ThreadPoolExecutor (not signal.alarm) so this works cross-platform;
            # ``shutdown(wait=False)`` so a timeout doesn't itself block.
            pool = ThreadPoolExecutor(max_workers=1)
            try:
                future = pool.submit(ModelGatewayService().invoke, version, execution.input_payload)
                try:
                    output_payload, model_usage = future.result(timeout=timeout_seconds)
                except FutureTimeoutError:
                    raise ModelGatewayError(
                        ErrorCode.EXECUTION_TIMED_OUT,
                        f"Execution exceeded its {timeout_seconds}s time budget.",
                    ) from None
            finally:
                pool.shutdown(wait=False)

            tool_usage = {"calls": 0}
            for call_request in execution.input_payload.get("tool_calls", []) if isinstance(
                execution.input_payload, dict) else []:
                ToolGatewayService().invoke(
                    self.db, execution, agent, call_request.get("tool_name", ""),
                    call_request.get("action", "EXECUTE"), call_request.get("params", {}),
                )
                tool_usage["calls"] += 1

            definition = self.db.get(AgentDefinition, version.definition_id)
            if definition.output_schema:
                # An invalid output is the agent's own contract violation,
                # not the caller's — still non-retryable (retrying produces
                # the same output for the same input against a deterministic
                # mock model), so it reports as a normal execution failure.
                _validate_schema(output_payload, definition.output_schema, what="output_payload")

            execution.output_payload = output_payload
            execution.model_usage = model_usage
            execution.tool_usage = tool_usage
            execution.cost = float(execution.cost or 0) + model_usage["total_tokens"] * 0.000002
            _set_execution_status(execution, "SUCCEEDED")
            execution.completed_at = _now()
            execution.duration_ms = int((execution.completed_at - execution.started_at).total_seconds() * 1000)
            attempt.status = "SUCCEEDED"
            attempt.completed_at = execution.completed_at
            attempt.duration_ms = execution.duration_ms
            _record_event(self.db, AuthorizationAuditEvent.RUNTIME_EXECUTION_SUCCEEDED, None,
                         organization_id=execution.organization_id, agent_id=execution.agent_id,
                         execution_id=execution.id)
        except IdentityError as exc:
            self._fail_or_retry(execution, attempt, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001 — a worker must never crash the poll loop
            self._fail_or_retry(execution, attempt, "INTERNAL_ERROR", str(exc))

    def _fail_or_retry(self, execution: AgentExecution, attempt: ExecutionAttempt,
                       code: str, message: str) -> None:
        deployment = self.db.get(AgentDeployment, execution.deployment_id) if execution.deployment_id else None
        max_attempts = ((deployment.runtime_limits or {}).get("maximum_retries", self.DEFAULT_MAX_ATTEMPTS)
                       if deployment else self.DEFAULT_MAX_ATTEMPTS) + 1
        attempt.status = "TIMED_OUT" if code == ErrorCode.EXECUTION_TIMED_OUT else "FAILED"
        attempt.error_code = code
        attempt.error_message = message
        attempt.completed_at = _now()
        attempt.duration_ms = int((attempt.completed_at - (attempt.started_at or attempt.completed_at))
                                  .total_seconds() * 1000)
        execution.error_code = code
        execution.error_message = message
        # Denials, policy failures and input errors are never retried (§34).
        # A timeout *is* retryable (§34: "may retry only if retry policy
        # allows" — the default policy allows it) — it just reports as
        # TIMED_OUT rather than DEAD_LETTERED once attempts are exhausted,
        # so the terminal reason stays distinguishable in the UI.
        non_retryable = {ErrorCode.RUNTIME_POLICY_DENIED, ErrorCode.MODEL_NOT_APPROVED,
                         ErrorCode.TOOL_ACTION_NOT_ALLOWED, ErrorCode.TOOL_NOT_ASSIGNED,
                         ErrorCode.TOOL_NOT_FOUND, ErrorCode.TOOL_CONSTRAINT_VIOLATION,
                         ErrorCode.VALIDATION_ERROR, ErrorCode.MODEL_PROVIDER_UNAVAILABLE}
        if code in non_retryable or execution.attempt_count >= max_attempts:
            if code == ErrorCode.EXECUTION_TIMED_OUT:
                _set_execution_status(execution, "TIMED_OUT")
            else:
                _set_execution_status(
                    execution, "DEAD_LETTERED" if execution.attempt_count >= max_attempts else "FAILED")
            execution.completed_at = _now()
            _record_event(self.db, AuthorizationAuditEvent.RUNTIME_EXECUTION_DEAD_LETTERED
                         if execution.status == "DEAD_LETTERED"
                         else AuthorizationAuditEvent.RUNTIME_EXECUTION_FAILED, None,
                         organization_id=execution.organization_id, agent_id=execution.agent_id,
                         execution_id=execution.id, severity="ERROR", meta={"code": code, "message": message})
        else:
            _set_execution_status(execution, "QUEUED")
            execution.queued_at = _now()


# --------------------------------------------------------------------------- #
# Runtime approvals (§39)
# --------------------------------------------------------------------------- #
class RuntimeApprovalService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_404(self, actor: User, approval_id: uuid.UUID) -> RuntimeApproval:
        approval = self.db.get(RuntimeApproval, approval_id)
        if approval is None or approval.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.RUNTIME_APPROVAL_NOT_FOUND, "Runtime approval not found.")
        return approval

    def list(self, actor: User, *, status: str | None = None) -> list[RuntimeApproval]:
        stmt = select(RuntimeApproval).where(RuntimeApproval.organization_id == actor.organization_id)
        if status:
            stmt = stmt.where(RuntimeApproval.status == status)
        return list(self.db.execute(stmt.order_by(RuntimeApproval.created_at.desc())).scalars())

    def decide(self, actor: User, approval_id: uuid.UUID, *, decision: str,
              comment: str | None = None) -> RuntimeApproval:
        approval = self.get_or_404(actor, approval_id)
        if approval.status != "PENDING":
            raise IdentityError(ErrorCode.CONFLICT, "Approval has already been decided.")
        approval.status = decision
        approval.reviewed_by = actor.id
        approval.reviewed_at = _now()
        approval.decision_comment = comment

        if approval.requested_action == "EXECUTION" and approval.execution_id:
            execution = self.db.get(AgentExecution, approval.execution_id)
            if execution and execution.status == "PENDING_APPROVAL":
                if decision == "APPROVED":
                    _set_execution_status(execution, "QUEUED")
                    execution.decision = "ALLOW"
                    execution.queued_at = _now()
                else:
                    _set_execution_status(execution, "REJECTED")
                    execution.decision = "DENY"
                    execution.completed_at = _now()
        if approval.requested_action == "DEPLOYMENT" and approval.deployment_id:
            deployment = self.db.get(AgentDeployment, approval.deployment_id)
            if deployment and deployment.status == "PENDING_APPROVAL":
                # APPROVED -> back to CREATED so /deploy can proceed (it will
                # find this now-APPROVED RuntimeApproval and skip re-gating).
                # REJECTED -> FAILED, a terminal state that never silently
                # becomes deployable again.
                deployment.status = "FAILED" if decision == "REJECTED" else "CREATED"
        self.db.commit()
        self.db.refresh(approval)
        if (approval.requested_action == "EXECUTION" and decision == "APPROVED"
                and approval.execution_id):
            ExecutionWorkerService(self.db).run_once(f"inline-{actor.id}")
        return approval


# --------------------------------------------------------------------------- #
# Health & heartbeats (§49, §50)
# --------------------------------------------------------------------------- #
class HealthMonitoringService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def heartbeat(self, actor: User, deployment_id: uuid.UUID, payload: dict) -> DeploymentHealth:
        deployment = DeploymentService(self.db).get_or_404(actor, deployment_id)
        row = DeploymentHealth(deployment_id=deployment.id, worker_id=payload.get("worker_id"),
                               status=payload.get("status", "HEALTHY"), metrics=payload.get("metrics"))
        self.db.add(row)
        deployment.health_status = row.status
        self.db.commit()
        self.db.refresh(row)
        return row

    def deployment_health(self, actor: User, deployment_id: uuid.UUID, limit: int = 50) -> list[DeploymentHealth]:
        DeploymentService(self.db).get_or_404(actor, deployment_id)
        stmt = select(DeploymentHealth).where(DeploymentHealth.deployment_id == deployment_id)
        return list(self.db.execute(stmt.order_by(DeploymentHealth.checked_at.desc()).limit(limit)).scalars())

    def workers(self, actor: User) -> list[dict]:
        stmt = (
            select(DeploymentHealth.worker_id, func.max(DeploymentHealth.checked_at).label("last_seen"))
            .join(AgentDeployment, AgentDeployment.id == DeploymentHealth.deployment_id)
            .where(AgentDeployment.organization_id == actor.organization_id,
                  DeploymentHealth.worker_id.is_not(None))
            .group_by(DeploymentHealth.worker_id)
        )
        rows = self.db.execute(stmt).all()
        out = []
        for worker_id, last_seen in rows:
            age = (_now() - last_seen).total_seconds() if last_seen else None
            status = "OFFLINE" if age is None or age > 300 else ("DEGRADED" if age > 120 else "HEALTHY")
            out.append({"worker_id": worker_id, "last_seen": last_seen, "status": status})
        return out

    def platform_health(self, actor: User) -> dict:
        deployments = self.db.execute(
            select(AgentDeployment.health_status, func.count(AgentDeployment.id))
            .where(AgentDeployment.organization_id == actor.organization_id, AgentDeployment.status == "ACTIVE")
            .group_by(AgentDeployment.health_status)
        ).all()
        return {status: count for status, count in deployments}


# --------------------------------------------------------------------------- #
# Kill switch (§60)
# --------------------------------------------------------------------------- #
class KillSwitchService:
    """§60 — EXECUTION/AGENT/ORGANIZATION scopes are tenant-scoped (gated by
    the ordinary, per-organization ``runtime.kill_switch.execute``
    permission); PROJECT is tenant-scoped to every agent under that
    project; PLATFORM is cross-tenant and additionally requires the actor's
    legacy role to be ``SUPER_ADMIN`` — a permission granted within one
    organization must never be sufficient to halt every organization's
    executions, so platform scope checks identity, not just the RBAC grant."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _cancel_executions(self, stmt) -> int:
        executions = self.db.execute(stmt).scalars().all()
        for execution in executions:
            _set_execution_status(execution, "CANCELLED")
            execution.cancel_requested = True
            execution.completed_at = _now()
        return len(executions)

    def _suspend_deployments(self, stmt) -> None:
        for deployment in self.db.execute(stmt).scalars():
            deployment.status = "SUSPENDED"

    def activate(self, actor: User, scope: str, target_id: uuid.UUID | None, reason: str) -> dict:
        cancelled = 0
        if scope == "EXECUTION":
            execution = ExecutionRequestService(self.db).get_or_404(actor, target_id)
            if execution.status not in TERMINAL_EXECUTION_STATUSES:
                _set_execution_status(execution, "CANCELLED")
                execution.cancel_requested = True
                execution.completed_at = _now()
                cancelled = 1
        elif scope == "AGENT":
            agent = AgentRegistryService(self.db).get_or_404(actor, target_id)
            agent.lifecycle_status = "SUSPENDED"
            cancelled = self._cancel_executions(select(AgentExecution).where(
                AgentExecution.agent_id == target_id,
                AgentExecution.status.in_(ACTIVE_EXECUTION_STATUSES),
            ))
        elif scope == "PROJECT":
            project_agents = list(self.db.execute(
                select(Agent).where(Agent.project_id == target_id,
                                    Agent.organization_id == actor.organization_id)
            ).scalars())
            if not project_agents:
                raise IdentityError(ErrorCode.VALIDATION_ERROR,
                                   "No agents found under this project in your organization.")
            agent_ids = [a.id for a in project_agents]
            for project_agent in project_agents:
                project_agent.lifecycle_status = "SUSPENDED"
            cancelled = self._cancel_executions(select(AgentExecution).where(
                AgentExecution.agent_id.in_(agent_ids),
                AgentExecution.status.in_(ACTIVE_EXECUTION_STATUSES),
            ))
            self._suspend_deployments(select(AgentDeployment).where(
                AgentDeployment.agent_id.in_(agent_ids), AgentDeployment.status == "ACTIVE",
            ))
        elif scope == "ORGANIZATION":
            cancelled = self._cancel_executions(select(AgentExecution).where(
                AgentExecution.organization_id == actor.organization_id,
                AgentExecution.status.in_(ACTIVE_EXECUTION_STATUSES),
            ))
            self._suspend_deployments(select(AgentDeployment).where(
                AgentDeployment.organization_id == actor.organization_id, AgentDeployment.status == "ACTIVE",
            ))
        elif scope == "PLATFORM":
            if actor.role != UserRole.SUPER_ADMIN:
                raise IdentityError(ErrorCode.PERMISSION_DENIED,
                                   "Platform-wide kill switch requires the SUPER_ADMIN role.")
            cancelled = self._cancel_executions(select(AgentExecution).where(
                AgentExecution.status.in_(ACTIVE_EXECUTION_STATUSES),
            ))
            self._suspend_deployments(select(AgentDeployment).where(AgentDeployment.status == "ACTIVE"))
        else:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, f"Unsupported kill-switch scope: {scope}.")

        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_KILL_SWITCH_ACTIVATED, actor,
                     organization_id=actor.organization_id,
                     agent_id=target_id if scope == "AGENT" else None,
                     execution_id=target_id if scope == "EXECUTION" else None,
                     severity="CRITICAL",
                     meta={"scope": scope, "target_id": str(target_id) if target_id else "ALL", "reason": reason,
                          "executions_cancelled": cancelled})
        self.db.commit()
        return {"scope": scope, "target_id": target_id, "executions_cancelled": cancelled}


# --------------------------------------------------------------------------- #
# Dashboard (§70)
# --------------------------------------------------------------------------- #
class RuntimeDashboardService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def snapshot(self, actor: User) -> dict:
        org = actor.organization_id
        day_ago = _now() - timedelta(hours=24)
        today_start = _now().replace(hour=0, minute=0, second=0, microsecond=0)

        def count_agents(**filters):
            stmt = select(func.count(Agent.id)).where(Agent.organization_id == org)
            for key, value in filters.items():
                stmt = stmt.where(getattr(Agent, key) == value)
            return self.db.execute(stmt).scalar_one()

        def count_executions(**filters):
            stmt = select(func.count(AgentExecution.id)).where(AgentExecution.organization_id == org)
            for key, value in filters.items():
                stmt = stmt.where(getattr(AgentExecution, key) == value)
            return self.db.execute(stmt).scalar_one()

        registered_agents = count_agents()
        active_agents = count_agents(lifecycle_status="ACTIVE")
        suspended_agents = count_agents(lifecycle_status="SUSPENDED")
        active_deployments = self.db.execute(
            select(func.count(AgentDeployment.id)).where(
                AgentDeployment.organization_id == org, AgentDeployment.status == "ACTIVE")
        ).scalar_one()
        running_executions = count_executions(status="RUNNING")
        queued_executions = count_executions(status="QUEUED")
        failed_24h = self.db.execute(
            select(func.count(AgentExecution.id)).where(
                AgentExecution.organization_id == org,
                AgentExecution.status.in_(["FAILED", "DEAD_LETTERED"]),
                AgentExecution.created_at >= day_ago)
        ).scalar_one()
        succeeded_24h = self.db.execute(
            select(func.count(AgentExecution.id)).where(
                AgentExecution.organization_id == org, AgentExecution.status == "SUCCEEDED",
                AgentExecution.created_at >= day_ago)
        ).scalar_one()
        pending_approvals = self.db.execute(
            select(func.count(RuntimeApproval.id)).where(
                RuntimeApproval.organization_id == org, RuntimeApproval.status == "PENDING")
        ).scalar_one()
        cost_today = self.db.execute(
            select(func.coalesce(func.sum(AgentExecution.cost), 0)).where(
                AgentExecution.organization_id == org, AgentExecution.created_at >= today_start)
        ).scalar_one()
        total_terminal = failed_24h + succeeded_24h
        success_rate = (succeeded_24h / total_terminal * 100) if total_terminal else 100.0

        durations = self.db.execute(
            select(AgentExecution.duration_ms).where(
                AgentExecution.organization_id == org, AgentExecution.duration_ms.is_not(None))
            .order_by(AgentExecution.completed_at.desc()).limit(100)
        ).scalars().all()
        avg_execution_ms = sum(durations) / len(durations) if durations else 0.0

        queue_samples = self.db.execute(
            select(AgentExecution.queued_at, AgentExecution.started_at).where(
                AgentExecution.organization_id == org, AgentExecution.started_at.is_not(None),
                AgentExecution.queued_at.is_not(None))
            .order_by(AgentExecution.started_at.desc()).limit(100)
        ).all()
        queue_ms = [(started - queued).total_seconds() * 1000 for queued, started in queue_samples]
        avg_queue_ms = sum(queue_ms) / len(queue_ms) if queue_ms else 0.0

        trend_rows = self.db.execute(
            select(func.date_trunc("day", AgentExecution.created_at).label("day"),
                  func.count(AgentExecution.id))
            .where(AgentExecution.organization_id == org,
                  AgentExecution.created_at >= _now() - timedelta(days=7))
            .group_by("day").order_by("day")
        ).all()
        execution_trend = [{"date": day.date().isoformat(), "count": count} for day, count in trend_rows]

        status_rows = self.db.execute(
            select(AgentExecution.status, func.count(AgentExecution.id))
            .where(AgentExecution.organization_id == org).group_by(AgentExecution.status)
        ).all()
        status_distribution = [{"status": status, "count": count} for status, count in status_rows]

        return {
            "registered_agents": registered_agents, "active_agents": active_agents,
            "active_deployments": active_deployments, "running_executions": running_executions,
            "queued_executions": queued_executions, "failed_executions_24h": failed_24h,
            "pending_approvals": pending_approvals, "suspended_agents": suspended_agents,
            "cost_today": float(cost_today), "success_rate": round(success_rate, 2),
            "avg_queue_ms": round(avg_queue_ms, 2), "avg_execution_ms": round(avg_execution_ms, 2),
            "execution_trend": execution_trend, "status_distribution": status_distribution,
        }
