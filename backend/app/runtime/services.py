"""Agent Runtime & Lifecycle Management services (Phase 5.0).

Reuses rather than forks existing infrastructure: the ``agents`` table
(Phase 1/3) stays the one agent registry (see ``app/models/runtime.py``
module docstring), and every execution's RBAC/ABAC decision goes through the
same ``AuthorizationGateway`` (Phase 4.3.6) the rest of the platform uses —
its own docstring already names "agent runtime" as a caller.

The execution queue is the ``agent_executions`` table itself (§30: "Postgres
backed queue for development"): a worker claims work with
``SELECT ... FOR UPDATE SKIP LOCKED`` on ``status = 'QUEUED'``.

**Phase 3.9 made the standalone worker process real** (``app/workers/``,
``python -m app.workers.runner``). ``ExecutionWorkerService`` is unchanged in
what it *does* -- the model→tool→model loop, governance, retry policy, cost
and audit are all exactly as M1 built them -- and changed in exactly one
place: ``claim_next`` now **commits** the claim instead of flushing it, so no
database lock is held across model or tool network I/O. Read that method's
docstring before touching anything in this area; it is the transaction
boundary the whole fleet depends on.

``ExecutionRequestService`` still runs a worker inline, synchronously, right
after enqueueing (an "eager queue", the same trick
``CELERY_TASK_ALWAYS_EAGER`` plays for local dev). That path is retained
rather than retired: it is what makes an execution's result available in the
API response, and every M1/M2 test drives it. The two are the same engine
reached two ways -- inline for request-scoped execution, out-of-process for
fleet execution -- which is why distributing execution required no change to
execution itself. See docs/deployment/workers.md and
docs/runtime/workers-and-queue.md.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import jsonschema
from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.middleware.gateway import AuthorizationGateway
from app.authorization.services import AuthorizationAuditService
from app.core.config import settings
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
    AgentReleaseChannel,
    AgentTool,
    AgentVersion,
    AgentVersionSnapshot,
    Capability,
    DeploymentHealth,
    ExecutionAttempt,
    ExecutionLock,
    ExecutionMessage,
    IdempotencyRecord,
    ModelPricing,
    ProviderCredential,
    RuntimeApproval,
    Tool,
    ToolCall,
    ToolCredential,
)
from app.models.user import User
# Phase 4.3 -- the runtime governance engine. Imported at module level, which
# is safe in this direction only: nothing in `app.runtime.governance` imports
# this module at import time. The two places the engine needs `_record_event`
# and `KillSwitchService` from here use function-local imports precisely to
# keep that one-way (see engine._audit / engine._trigger_kill_switch).
from app.runtime.governance.contract import (
    Checkpoint,
    CheckpointContext,
    GovernanceChallenged,
    GovernanceStopped,
)
from app.runtime.governance.engine import RuntimeGovernanceEngine
from app.runtime.providers.errors import ProviderRequestFailedError
from app.runtime.providers.types import RETRYABLE_PROVIDER_ERROR_CLASSES, ProviderErrorClass

logger = logging.getLogger(__name__)

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
                     "PUBLISHED", "DEPRECATED", "REVOKED", "RETIRED")
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
    # Phase 4.3 added the last two edges. Before the runtime governance engine
    # existed, nothing could intervene in an execution that was already
    # RUNNING -- it ran to one of its own conclusions. A governance CHALLENGE
    # raised at the very first checkpoint now parks it in PENDING_APPROVAL (the
    # existing approval funnel resumes it from QUEUED, and nothing has been
    # dispatched yet so resuming is honest); a challenge raised later, which
    # this platform has no way to resume mid-loop, ends it in the same terminal
    # BLOCKED state a policy refusal at admission already uses.
    "RUNNING": frozenset({"SUCCEEDED", "FAILED", "QUEUED", "DEAD_LETTERED", "TIMED_OUT",
                          "CANCELLED", "PENDING_APPROVAL", "BLOCKED"}),
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


def _legacy_checksum(version: AgentVersion) -> str:
    """Deprecated (Phase 5.2.4) — Phase 5.0/5.2 Part 1's original checksum
    routine. Kept only to verify rows whose ``checksum_algorithm`` is still
    ``'legacy-sha256'``; never used to compute a new version's checksum.
    Depends on ``json.dumps``'s default key-ordering/Unicode/whitespace
    behavior, which is not a stable, cross-language contract — see
    ``app/runtime/versioning/canonical.py``'s module docstring for why that
    made this routine unfit for anything a signature would ever cover."""
    canonical_dict = {
        "configuration_snapshot": version.configuration_snapshot,
        "prompt_snapshot": version.prompt_snapshot,
        "model_configuration": version.model_configuration,
        "capabilities_snapshot": version.capabilities_snapshot,
        "tools_snapshot": version.tools_snapshot,
        "policy_snapshot": version.policy_snapshot,
    }
    blob = json.dumps(canonical_dict, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _checksum(version: AgentVersion) -> str:
    """Phase 5.2.4 — ``canonical-sha256`` checksum of a version's per-field
    snapshot columns. Every new version uses this (see ``create()`` setting
    ``checksum_algorithm``); ``_legacy_checksum`` above remains only to
    verify rows created before this phase shipped."""
    from app.runtime.versioning import canonical

    payload = canonical.stringify_floats({
        "configuration_snapshot": version.configuration_snapshot,
        "prompt_snapshot": version.prompt_snapshot,
        "model_configuration": version.model_configuration,
        "capabilities_snapshot": version.capabilities_snapshot,
        "tools_snapshot": version.tools_snapshot,
        "policy_snapshot": version.policy_snapshot,
    })
    return canonical.digest(payload)


def _verify_checksum(version: AgentVersion) -> bool:
    """Branches on ``checksum_algorithm`` so legacy rows verify with the
    legacy routine and canonical-sha256 rows with the new one — the single
    choke point every tamper check goes through (``validate()``,
    ``publish()``, the readiness dry-run)."""
    if version.checksum_algorithm == "legacy-sha256":
        return _legacy_checksum(version) == version.checksum
    return _checksum(version) == version.checksum


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
                  severity: str = "INFO", meta: dict | None = None,
                  trace: "TraceContext | None" = None) -> None:
    """Writes the platform audit trail and the runtime telemetry stream
    (§51, §76) that feeds the Operations Center timeline.

    **These are two planes, not one write with two destinations** (ACT-SRS-M4
    §5), and Phase 4.1 made the difference load-bearing rather than incidental:

    - The **audit** write is the compliance record. It must not be lossy and it
      must not be filtered, so it still raises on failure and still receives
      ``meta`` exactly as the caller supplied it.
    - The **telemetry** write is derived and best-effort. It goes through
      ``app.observability.events.emit_event``, which scrubs the payload, drops
      content and private reasoning under the METADATA_ONLY baseline, attaches
      the trace identity, and **never raises** (§9). A telemetry failure
      degrades observability; it does not fail the execution that caused it.

    Before 4.1 the telemetry row was a raw ``db.add`` of the unfiltered
    ``meta`` with ``correlation_id`` left null on every row. Both of those are
    fixed here, at the one place every runtime event goes through."""
    AuthorizationAuditService(db).record_change(
        event, organization_id=organization_id, actor_id=actor.id if actor else None,
        meta=meta,
    )
    _emit_telemetry(db, event, organization_id=organization_id, agent_id=agent_id,
                   deployment_id=deployment_id, execution_id=execution_id,
                   severity=severity, meta=meta, trace=trace)


def _emit_telemetry(db: Session, event: AuthorizationAuditEvent, *,
                    organization_id: uuid.UUID, agent_id: uuid.UUID | None,
                    deployment_id: uuid.UUID | None, execution_id: uuid.UUID | None,
                    severity: str, meta: dict | None,
                    trace: "TraceContext | None" = None) -> None:
    """The telemetry half of :func:`_record_event`. Never raises.

    The whole body is inside the guard, not just the write. Resolving the trace
    identity requires reading the execution, and a lookup that fails must be as
    harmless as an insert that fails -- otherwise the fail-open property would
    hold for the easy case and not for the real one."""
    try:
        from app.observability.events import Outcome, emit_event
        from app.observability.trace import SpanKind, TraceContext, new_trace_id

        # A primary-key `get` on a row this transaction almost always already
        # holds, so this is an identity-map hit rather than a query on the hot
        # path (§25). The `or` chain never leaves a telemetry row without a
        # trace: an event with no execution still belongs to *something*.
        execution = db.get(AgentExecution, execution_id) if execution_id else None
        if execution is not None:
            trace = TraceContext.for_execution(execution)
            span = trace.root_span(SpanKind.EXECUTION, execution.id)
        else:
            # No execution. Either the caller supplied a trace of its own (the
            # scheduler does -- every event of one job occurrence must share
            # one trace, not get a fresh random id each time), or this event
            # genuinely stands alone and gets a trace of its own so it is at
            # least findable.
            trace = trace or TraceContext(trace_id=new_trace_id())
            span = None
            trace = trace.with_attributes(
                organization_id=organization_id, agent_id=agent_id,
                deployment_id=deployment_id,
            )
        emit_event(
            db, event_type=event.value,
            outcome=Outcome.FAILURE if severity in ("ERROR", "CRITICAL") else Outcome.INFO,
            trace=trace, span=span, payload=meta, severity=severity,
        )
    except Exception:  # noqa: BLE001 -- §9: telemetry never gates execution
        logger.warning("telemetry: could not record runtime event %r", event.value,
                      exc_info=True)


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


def _routing_key(payload: dict, principal: "User | Agent") -> str | None:
    """Phase 3.4 (M3-3.4-FR-012) — the stable key the version resolver routes
    on, or ``None`` for an ordinary weighted (random) draw.

    Stickiness is **opt-in**, in this precedence: an explicit ``routing_key``,
    else the request's ``correlation_id`` (a caller that already threads a
    correlation id through a conversation gets consistent version selection
    for free). Deliberately *not* defaulted to the principal's id: that would
    silently make every request from one user sticky, which would quietly
    defeat the point of a percentage rollout for a small user base — the
    caller says when a session must not flip versions mid-flight."""
    explicit = payload.get("routing_key")
    if explicit:
        return str(explicit)
    correlation_id = payload.get("correlation_id")
    if correlation_id:
        return str(correlation_id)
    return None


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
        from app.runtime.versioning.channels import ReleaseChannelService
        from app.runtime.versioning.lineage import VersionLineageService
        from app.runtime.versioning.semantic_version import SemanticVersionService
        from app.runtime.versioning.status_history import record_status_change

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

        # Phase 5.2 Part 1 §15-16 — semantic versioning rules: validated if
        # supplied, auto-derived (monotonic patch bump) if not.
        semver_service = SemanticVersionService(self.db)
        semantic_version = payload.get("semantic_version")
        if semantic_version:
            semver_service.validate_new(agent.id, semantic_version)
        else:
            semantic_version = semver_service.next_default(agent.id)

        # §9, §26 — release channel (defaults to the catalog's default, STABLE).
        channel_service = ReleaseChannelService(self.db)
        channel_service.ensure_seeded()
        channel_name = payload.pop("release_channel", None)
        channel = channel_service.get_by_name(channel_name) if channel_name else channel_service.default()

        version = AgentVersion(
            agent_id=agent.id, definition_id=definition_id, version=next_version,
            semantic_version=semantic_version,
            configuration_snapshot=payload.get("model_configuration", {}) or {},
            prompt_snapshot=payload.get("prompt_snapshot"),
            model_configuration=payload.get("model_configuration", {}) or {},
            capabilities_snapshot=capabilities_snapshot,
            tools_snapshot=tools_snapshot,
            policy_snapshot=payload.get("policy_snapshot"),
            release_notes=payload.get("release_notes"),
            release_channel_id=channel.id,
            created_by=actor.id, checksum="",
            # Phase 5.2.4 — every new version is canonical-sha256; the column's
            # server_default of 'legacy-sha256' exists only to backfill rows
            # that existed before this phase, never to be the default for new ones.
            checksum_algorithm="canonical-sha256",
        )
        version.checksum = _checksum(version)
        self.db.add(version)
        self.db.flush()

        # §17 — link to the agent's immediately-preceding version.
        VersionLineageService(self.db).link_parent(agent.id, version)

        for capability_id in capability_ids:
            self.db.add(AgentCapability(agent_id=agent.id, agent_version_id=version.id,
                                        capability_id=capability_id, status="REQUESTED"))
        for tool_id in tool_ids:
            self.db.add(AgentTool(agent_id=agent.id, agent_version_id=version.id, tool_id=tool_id,
                                  allowed_actions=["EXECUTE"], status="REQUESTED"))

        record_status_change(self.db, version.id, previous_status=None, new_status="DRAFT",
                             changed_by=actor.id)
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_VERSION_CREATED, actor,
                     organization_id=actor.organization_id, agent_id=agent.id,
                     meta={"agent_id": str(agent.id), "version": next_version})
        self.db.commit()
        self.db.refresh(version)
        return version

    def validate(self, actor: User, agent: Agent, version_id: uuid.UUID) -> AgentVersion:
        from app.runtime.versioning.status_history import record_status_change

        version = self.get_or_404(actor, agent.id, version_id)
        if version.status != "DRAFT":
            raise IdentityError(ErrorCode.INVALID_LIFECYCLE_TRANSITION,
                               "Only DRAFT versions can be validated.")
        errors: list[str] = []
        if not version.model_configuration or not version.model_configuration.get("provider"):
            errors.append("model_configuration.provider is required")
        if not _verify_checksum(version):
            errors.append("checksum mismatch — snapshot was modified after creation")
        if errors:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "; ".join(errors))
        record_status_change(self.db, version.id, previous_status=version.status,
                             new_status="READY_FOR_REVIEW", changed_by=actor.id)
        version.status = "READY_FOR_REVIEW"
        self.db.commit()
        self.db.refresh(version)
        return version

    def approve(self, actor: User, agent: Agent, version_id: uuid.UUID) -> AgentVersion:
        from app.runtime.versioning.status_history import record_status_change

        version = self.get_or_404(actor, agent.id, version_id)
        if version.status != "READY_FOR_REVIEW":
            raise IdentityError(ErrorCode.INVALID_LIFECYCLE_TRANSITION,
                               "Only versions ready for review can be approved.")
        record_status_change(self.db, version.id, previous_status=version.status,
                             new_status="APPROVED", changed_by=actor.id)
        version.status = "APPROVED"
        version.reviewed_by = actor.id
        self.db.commit()
        self.db.refresh(version)
        return version

    def publish(self, actor: User, agent: Agent, version_id: uuid.UUID, *,
               correlation_id: str | None = None, source_ip: str | None = None) -> AgentVersion:
        from app.runtime.versioning.attestation import AttestationService
        from app.runtime.versioning.snapshot import SnapshotBuilderService
        from app.runtime.versioning.status_history import record_status_change

        version = self.get_or_404(actor, agent.id, version_id)
        if version.status != "APPROVED":
            raise IdentityError(ErrorCode.INVALID_LIFECYCLE_TRANSITION,
                               "Only approved versions can be published.")
        if not _verify_checksum(version):
            raise IdentityError(ErrorCode.AGENT_VERSION_IMMUTABLE,
                               "Checksum mismatch — version was tampered with.")
        # §30's "cannot publish two active releases" is a release-process
        # rule, not enforced as a hard block here: this platform's rollback
        # and canary/blue-green deployment strategies (§15, §57) *require*
        # multiple versions to be simultaneously PUBLISHED — a Deployment,
        # not a Version's status, tracks which one is live in a given
        # environment (see docs/runtime/deployments.md). Lineage still
        # records supersession (below) so the "what replaced what" question
        # always has an answer without blocking legitimate multi-version
        # deployment topologies.
        definition = self.db.get(AgentDefinition, version.definition_id)
        channel = self.db.get(AgentReleaseChannel, version.release_channel_id) if version.release_channel_id else None
        snapshot = SnapshotBuilderService(self.db).build_and_store(agent, definition, version,
                                                                   release_channel=channel, publisher_id=actor.id)

        record_status_change(self.db, version.id, previous_status=version.status,
                             new_status="PUBLISHED", changed_by=actor.id)
        version.status = "PUBLISHED"
        version.published_at = _now()

        # §18 — mark the direct predecessor superseded once this one
        # publishes, if it's already been deprecated (informational pointer
        # only; it does not resurrect or change the predecessor's status).
        if version.parent_version_id is not None:
            parent = self.db.get(AgentVersion, version.parent_version_id)
            if parent is not None and parent.status == "DEPRECATED" and parent.superseded_by_id is None:
                parent.superseded_by_id = version.id

        # Phase 5.2.4 — sign the frozen snapshot. Deliberately NOT wrapped in
        # try/except, unlike 5.2.6's advisory compatibility analysis below:
        # an unsigned published version is an integrity hole
        # (ACT-VER-NFR-004, fail-closed), so a signing failure must raise
        # out of publish() entirely. Nothing above has been committed yet,
        # so the exception propagating here means the whole transaction is
        # discarded when the request's session closes — the version never
        # reaches PUBLISHED. See docs/runtime/versioning.md for why this is
        # the opposite policy from compatibility analysis's failure handling.
        AttestationService(self.db).build_and_sign(agent, version, snapshot_digest=snapshot.checksum,
                                                   publisher_id=actor.id, correlation_id=correlation_id,
                                                   source_ip=source_ip)

        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_VERSION_PUBLISHED, actor,
                     organization_id=actor.organization_id, agent_id=agent.id,
                     meta={"agent_id": str(agent.id), "version_id": str(version.id)})
        self.db.commit()
        self.db.refresh(version)

        # Phase 5.2.6 — compatibility analysis is advisory (see
        # docs/runtime/versioning.md); the publish itself is already durably
        # committed above, so a bug in the analyzer can only fail its own
        # best-effort follow-up, never make a version unpublishable.
        try:
            from app.runtime.versioning.compatibility import CompatibilityAnalysisService

            CompatibilityAnalysisService(self.db).analyze(version.id)
            self.db.refresh(version)
        except Exception:
            self.db.rollback()
            logger.exception("Compatibility analysis failed for version %s during publish.", version.id)

        return version

    def deprecate(self, actor: User, agent: Agent, version_id: uuid.UUID) -> AgentVersion:
        from app.runtime.versioning.status_history import record_status_change

        version = self.get_or_404(actor, agent.id, version_id)
        if version.status != "PUBLISHED":
            raise IdentityError(ErrorCode.INVALID_LIFECYCLE_TRANSITION, "Only published versions can be deprecated.")
        record_status_change(self.db, version.id, previous_status=version.status,
                             new_status="DEPRECATED", changed_by=actor.id)
        version.status = "DEPRECATED"
        version.deprecated_at = _now()
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_VERSION_DEPRECATED, actor,
                     organization_id=actor.organization_id, agent_id=agent.id,
                     meta={"version_id": str(version.id)})
        self.db.commit()
        self.db.refresh(version)
        return version

    def revoke(self, actor: User, agent: Agent, version_id: uuid.UUID, *, reason: str | None = None) -> AgentVersion:
        from app.runtime.versioning.status_history import record_status_change

        version = self.get_or_404(actor, agent.id, version_id)
        if version.status in ("REVOKED", "RETIRED"):
            raise IdentityError(ErrorCode.INVALID_LIFECYCLE_TRANSITION,
                               f"Version cannot be revoked while {version.status}.")
        record_status_change(self.db, version.id, previous_status=version.status,
                             new_status="REVOKED", changed_by=actor.id, reason=reason)
        version.status = "REVOKED"
        version.revoked_reason = reason
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_VERSION_REVOKED, actor,
                     organization_id=actor.organization_id, agent_id=agent.id,
                     meta={"version_id": str(version.id)})
        self.db.commit()
        self.db.refresh(version)
        return version

    def retire(self, actor: User, agent: Agent, version_id: uuid.UUID) -> AgentVersion:
        """Phase 5.2 Part 1 §24 — historical only; terminal. Reachable only
        from DEPRECATED, matching §25's lifecycle diagram (there is no
        Revoked -> Retired edge — REVOKED is its own terminal, emergency
        state)."""
        from app.runtime.versioning.status_history import record_status_change

        version = self.get_or_404(actor, agent.id, version_id)
        if version.status != "DEPRECATED":
            raise IdentityError(ErrorCode.INVALID_LIFECYCLE_TRANSITION,
                               "Only deprecated versions can be retired.")
        record_status_change(self.db, version.id, previous_status=version.status,
                             new_status="RETIRED", changed_by=actor.id)
        version.status = "RETIRED"
        version.retired_at = _now()
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_VERSION_RETIRED, actor,
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
# Pricing (Phase 5.7a.3 SRS ACT-MDL-FR-084..089)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CostResult:
    """The result of one cost calculation — attributed to a specific
    provider/model/pricing-version pair (``ACT-MDL-FR-088``/``FR-089``),
    never an unattributed number."""

    amount: float
    currency: str
    pricing_version: str | None


class PricingService:
    """§ACT-MDL-FR-084 — per-provider, per-model pricing with effective
    dating, following the runtime domain's established pattern (a service
    with ``db: Session``, direct ORM queries, no repository layer — §7,
    §10.10). A price change is never an ``UPDATE``: ``set_price`` inserts
    a new row and closes the prior one's ``effective_to``, which is what
    keeps an already-computed historical execution's cost accurate after a
    price changes (``ACT-MDL-FR-085``)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def resolve_price(self, provider: str, model: str, at: datetime) -> ModelPricing | None:
        return self.db.execute(
            select(ModelPricing).where(
                ModelPricing.provider == provider, ModelPricing.model_name == model,
                ModelPricing.effective_from <= at,
                or_(ModelPricing.effective_to.is_(None), ModelPricing.effective_to > at),
            ).order_by(ModelPricing.effective_from.desc())
        ).scalars().first()

    def calculate_cost(self, *, provider: str, model: str, prompt_tokens: int, completion_tokens: int,
                       at: datetime) -> CostResult:
        pricing = self.resolve_price(provider, model, at)
        if pricing is None:
            # ACT-MDL-FR-087 — no pricing row for this provider/model (the
            # ordinary case for MOCK, or a real provider pointed at a
            # self-hosted/local endpoint) means this call has a definite,
            # known cost: zero. Not "unknown" — there is nothing to meter.
            return CostResult(amount=0.0, currency="USD", pricing_version=None)
        amount = (
            (prompt_tokens / 1000) * float(pricing.prompt_cost_per_1k)
            + (completion_tokens / 1000) * float(pricing.completion_cost_per_1k)
        )
        return CostResult(amount=round(amount, 8), currency=pricing.currency, pricing_version=pricing.pricing_version)

    def set_price(self, *, provider: str, model: str, prompt_cost_per_1k: float, completion_cost_per_1k: float,
                  pricing_version: str, effective_from: datetime, currency: str = "USD") -> ModelPricing:
        """Closes whatever row is currently open (``effective_to IS
        NULL``) for this ``(provider, model)`` at ``effective_from``, then
        inserts the new price as a new row. Never mutates an existing
        row's price in place — that is what AC-16/AC-17 (a price change
        must not retroactively alter an already-computed historical cost)
        depend on."""
        prior = self.db.execute(
            select(ModelPricing).where(
                ModelPricing.provider == provider, ModelPricing.model_name == model,
                ModelPricing.effective_to.is_(None),
            )
        ).scalars().first()
        if prior is not None:
            prior.effective_to = effective_from
        new_row = ModelPricing(
            provider=provider, model_name=model,
            prompt_cost_per_1k=prompt_cost_per_1k, completion_cost_per_1k=completion_cost_per_1k,
            currency=currency, pricing_version=pricing_version, effective_from=effective_from,
        )
        self.db.add(new_row)
        self.db.flush()
        return new_row


# --------------------------------------------------------------------------- #
# Provider credentials (Phase 5.7a.5 SRS ACT-MDL-FR-080..083)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ProviderCredentialInfo:
    """Everything about a stored credential *except* the value —
    ``ACT-MDL-FR-081``. The only shape ``get_metadata``/``list_for_org``
    (and, transitively, the read API) ever return."""

    id: uuid.UUID
    organization_id: uuid.UUID
    provider: str
    secret_hint: str
    base_url: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None
    last_used_at: datetime | None


@dataclass(frozen=True)
class ResolvedCredential:
    """What ``ModelGatewayService.invoke()`` actually needs to reach a
    provider — an ``api_key`` (possibly ``None``, valid for a credential-
    free local provider, ``ACT-MDL-FR-083``) and an optional per-
    organization ``base_url`` override. Deliberately just two plain,
    immutable fields with no database handle: this crosses the
    ``ThreadPoolExecutor`` boundary into ``ModelGatewayService.invoke()``
    (see ``ExecutionWorkerService._execute``'s own comment on why the
    model call runs on a second thread against no shared, non-thread-safe
    ``Session``) — resolution itself always happens first, synchronously,
    on the worker's own thread, and only this plain value crosses over."""

    api_key: str | None
    base_url: str | None


@dataclass(frozen=True)
class CredentialTestResult:
    success: bool
    error_class: str | None
    message: str


class ProviderCredentialService:
    """§ACT-MDL-FR-080..083 — per-organization, per-provider model-provider
    credential storage, encrypted at rest, following the runtime domain's
    established pattern (a service with ``db: Session``, direct ORM
    queries, no repository layer — §7, §10.10).

    A dedicated table (``provider_credentials``), not the pre-existing
    ``AgentDeployment.secret_references`` JSONB field: ``secret_references``
    is a free-form dict of *reference strings* (`"vault://..."`) with no
    actual storage or resolution behind it at all — see
    ``_validate_secret_references`` above, which only checks the string
    *looks like* a reference — and it is scoped to one deployment, not one
    organization. A provider credential needs dedicated columns
    (``provider``, ``secret_hint``, ``base_url``, ``status``) and org-wide
    scope (one org, one deployment or a hundred, shares the same provider
    key), which is a distinct enough concern to warrant its own table
    rather than overloading a field designed for a different purpose.

    **Resolution order (``ACT-MDL-FR-082``, explicit)**: (1) this
    organization's own stored, ``ACTIVE`` credential for the provider, (2)
    ``settings.MODEL_PROVIDER_API_KEYS`` as a fallback default, (3) no
    credential at all — valid for a local provider (``ACT-MDL-FR-083``); a
    *real* provider that then fails authentication with none configured is
    translated to ``PROVIDER_CREDENTIAL_REQUIRED`` by
    ``ModelGatewayService.invoke`` (see there), not raised here — this
    service has no way to know in advance whether a given provider
    endpoint actually requires one."""

    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _to_metadata(row: ProviderCredential) -> ProviderCredentialInfo:
        return ProviderCredentialInfo(
            id=row.id, organization_id=row.organization_id, provider=row.provider,
            secret_hint=row.secret_hint, base_url=row.base_url, status=row.status,
            created_at=row.created_at, updated_at=row.updated_at,
            created_by=row.created_by, last_used_at=row.last_used_at,
        )

    def _get_row(self, organization_id: uuid.UUID, provider: str) -> ProviderCredential | None:
        return self.db.execute(
            select(ProviderCredential).where(
                ProviderCredential.organization_id == organization_id,
                ProviderCredential.provider == provider,
            )
        ).scalars().first()

    def get_or_404(self, organization_id: uuid.UUID, provider: str) -> ProviderCredential:
        row = self._get_row(organization_id, provider)
        if row is None:
            raise IdentityError(ErrorCode.PROVIDER_CREDENTIAL_NOT_FOUND,
                               f"No credential configured for provider '{provider}'.")
        return row

    def list_for_org(self, organization_id: uuid.UUID) -> list[ProviderCredentialInfo]:
        rows = self.db.execute(
            select(ProviderCredential).where(ProviderCredential.organization_id == organization_id)
            .order_by(ProviderCredential.provider)
        ).scalars().all()
        return [self._to_metadata(row) for row in rows]

    def get_metadata(self, organization_id: uuid.UUID, provider: str) -> ProviderCredentialInfo:
        return self._to_metadata(self.get_or_404(organization_id, provider))

    def store(self, actor: User, organization_id: uuid.UUID, provider: str, secret: str, *,
             base_url: str | None = None) -> ProviderCredentialInfo:
        """Upsert — creates or replaces-and-re-encrypts (``AC-16``). Never
        mutates an existing row's ciphertext through anything other than
        this method, and never returns the plaintext."""
        from app.runtime.providers.credential_crypto import encrypt_secret, mask_hint

        row = self._get_row(organization_id, provider)
        encrypted = encrypt_secret(secret)
        hint = mask_hint(secret)
        if row is None:
            row = ProviderCredential(
                organization_id=organization_id, provider=provider, encrypted_secret=encrypted,
                secret_hint=hint, base_url=base_url, status="ACTIVE", created_by=actor.id,
            )
            self.db.add(row)
        else:
            row.encrypted_secret = encrypted
            row.secret_hint = hint
            row.base_url = base_url
            row.status = "ACTIVE"
        self.db.flush()
        # ACT-MDL-FR-081 -- meta carries the provider identifier only, never
        # the secret or its ciphertext.
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_PROVIDER_CREDENTIAL_UPDATED, actor,
                     organization_id=organization_id, meta={"provider": provider})
        self.db.commit()
        self.db.refresh(row)
        return self._to_metadata(row)

    def delete(self, actor: User, organization_id: uuid.UUID, provider: str) -> None:
        row = self.get_or_404(organization_id, provider)
        self.db.delete(row)
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_PROVIDER_CREDENTIAL_DELETED, actor,
                     organization_id=organization_id, meta={"provider": provider})
        self.db.commit()

    def resolve_secret(self, organization_id: uuid.UUID, provider: str) -> ResolvedCredential:
        """The one place a stored credential is decrypted. The plaintext
        is returned to the caller (which hands it straight into the
        ``api_key`` forwarding path already established in 5.7a.2) and is
        never assigned onto ``self`` or any persisted object."""
        from app.runtime.providers.credential_crypto import decrypt_secret

        row = self._get_row(organization_id, provider)
        if row is not None and row.status == "ACTIVE":
            row.last_used_at = _now()
            return ResolvedCredential(api_key=decrypt_secret(row.encrypted_secret), base_url=row.base_url)
        fallback = settings.MODEL_PROVIDER_API_KEYS.get(provider)
        return ResolvedCredential(api_key=fallback, base_url=None)

    def resolve_for_version(self, organization_id: uuid.UUID, version: AgentVersion) -> ResolvedCredential:
        config = version.model_configuration or {}
        provider_name = (config.get("provider") or settings.MODEL_DEFAULT_PROVIDER).upper()
        return self.resolve_secret(organization_id, provider_name)

    def test(self, organization_id: uuid.UUID, provider: str) -> CredentialTestResult:
        """``ACT-MDL-FR-080``'s validation endpoint — a minimal real call
        through the stored credential, classified via the 5.7a.4 taxonomy,
        never returning the credential itself."""
        from app.runtime.providers.registry import resolve as resolve_provider
        from app.runtime.providers.errors import ProviderRequestFailedError
        from app.runtime.providers.types import ModelMessage, ModelRequest

        resolved = self.resolve_secret(organization_id, provider)
        try:
            instance = resolve_provider(
                provider, base_url=resolved.base_url or settings.MODEL_PROVIDER_BASE_URLS.get(provider),
                api_key=resolved.api_key,
            )
        except IdentityError as exc:
            return CredentialTestResult(success=False, error_class=None, message=exc.message)

        try:
            instance.complete(ModelRequest(messages=(ModelMessage(role="user", content="ping"),)))
        except ProviderRequestFailedError as exc:
            return CredentialTestResult(success=False, error_class=exc.error_class.value, message=exc.message)
        return CredentialTestResult(success=True, error_class=None, message="Credential test succeeded.")


# --------------------------------------------------------------------------- #
# Provider resilience — retry & circuit breaking (Phase 5.7a.4 SRS
# ACT-MDL-FR-060..069)
# --------------------------------------------------------------------------- #
# Retry policy decides *whether* to retry, from the adapter's own
# classification (``ProviderErrorClass``) — it lives here, not in
# ``openai_compatible.py``, so a future second adapter inherits the exact
# same retry/backoff/circuit-breaker behavior with no new retry code of its
# own, provided it classifies into the same provider-neutral taxonomy
# (``ACT-MDL-FR-006``'s "no wire vocabulary crosses the adapter boundary"
# extends to this: retry policy must never need to know an adapter's wire
# format).
class _CircuitState:
    """Generic per-identifier circuit-breaker state -- three-state (closed/
    open/half-open) exactly as ACT-MDL-FR-067 defined it, with nothing
    provider-specific anywhere in this class. Phase 5.6a.2 reuses it
    unchanged for tools, under its own store/settings (see
    ``_tool_circuit_state`` below) rather than duplicating it."""

    __slots__ = ("failure_count", "opened_at")

    def __init__(self) -> None:
        self.failure_count = 0
        self.opened_at: float | None = None


def _circuit_is_open(identifier: str, store: dict[str, _CircuitState], *, cooldown_seconds: float) -> bool:
    """The neutral core Phase 5.6a.2 extracted out of ``_circuit_before_
    call`` below. 5.7a.4 built the *state machine* itself generically
    (keyed by a plain string identifier, no provider-specific data), but
    coupled "what happens when open" directly into the check -- raising
    ``ProviderRequestFailedError``, which is genuinely model-specific and
    could not be reused as-is for tools (a failed tool call must never
    raise past the single call; see ``ToolGatewayService._invoke_http``).
    This is the reusable half of that function; each call site supplies
    its own "what to do when open" behavior on top."""
    state = store.setdefault(identifier, _CircuitState())
    if state.opened_at is None:
        return False
    return (time.monotonic() - state.opened_at) < cooldown_seconds  # else: half-open, let it through


def _circuit_note_success(identifier: str, store: dict[str, _CircuitState]) -> None:
    state = store.setdefault(identifier, _CircuitState())
    state.failure_count = 0
    state.opened_at = None


def _circuit_note_failure(identifier: str, store: dict[str, _CircuitState], *, failure_threshold: int) -> None:
    state = store.setdefault(identifier, _CircuitState())
    state.failure_count += 1
    if state.failure_count >= failure_threshold:
        state.opened_at = time.monotonic()


def _backoff_delay(attempt: int, *, retry_after_seconds: float | None, base_delay: float, max_delay: float) -> float:
    """The neutral core Phase 5.6a.2 extracted out of ``_provider_backoff_
    delay`` below -- pure math, parameterized by the caller's own base/cap
    rather than reading ``settings.MODEL_PROVIDER_RETRY_*`` directly, so
    the tool path can supply its own ``TOOL_RETRY_*`` settings through the
    exact same "equal jitter" formula (ACT-MDL-FR-063/064) instead of
    reimplementing it. A caller-supplied ``retry_after_seconds`` (e.g. a
    provider's ``Retry-After`` header) always wins over computed backoff."""
    if retry_after_seconds is not None:
        return max(retry_after_seconds, 0.0)
    half = min(max_delay, base_delay * (2 ** attempt)) / 2
    return half + random.uniform(0, half)


# --------------------------------------------------------------------------- #
# Provider (model) circuit breaker -- Phase 5.7a.4. Public surface
# (``_circuit_before_call``/``_circuit_record_success``/``_circuit_record_
# failure``/``_provider_backoff_delay``/``reset_provider_circuit_breakers``)
# unchanged: same signatures, same behavior, now implemented on top of the
# neutral core above instead of duplicating the state machine.
# --------------------------------------------------------------------------- #
# ACT-MDL-FR-067 — per-provider identifier, in-process, not persisted
# anywhere -- a fresh process starts every provider closed; see
# docs/runtime/providers.md's "known limitation" for why (Milestone 3's
# distributed worker model would need a shared store; not this phase's job).
_provider_circuit_state: dict[str, _CircuitState] = {}


def reset_provider_circuit_breakers() -> None:
    """Test-only reset hook for the module-level circuit-breaker state,
    which would otherwise leak between tests that reuse the same provider
    identifier (most tests instead sidestep this by using a unique
    identifier per test, matching this codebase's existing convention for
    other global registries/catalogs)."""
    _provider_circuit_state.clear()


def _circuit_before_call(provider_name: str) -> None:
    """ACT-MDL-FR-067, AC-16 — raises (failing fast, no call made) if this
    provider's circuit is currently open."""
    if _circuit_is_open(provider_name, _provider_circuit_state,
                        cooldown_seconds=settings.MODEL_PROVIDER_CIRCUIT_COOLDOWN_SECONDS):
        raise ProviderRequestFailedError(
            provider_name, "circuit breaker is open for this provider -- failing fast without calling it",
            error_class=ProviderErrorClass.PROVIDER_UNAVAILABLE,
        )


def _circuit_record_success(provider_name: str) -> None:
    """AC-17 — a success (including the one probing half-open call) closes
    the circuit."""
    _circuit_note_success(provider_name, _provider_circuit_state)


def _circuit_record_failure(provider_name: str) -> None:
    """AC-15 — opens the circuit once consecutive failures reach the
    configured threshold; a failure while already open (the half-open probe
    failing again) re-opens it, restarting the cooldown."""
    _circuit_note_failure(provider_name, _provider_circuit_state,
                          failure_threshold=settings.MODEL_PROVIDER_CIRCUIT_FAILURE_THRESHOLD)


def _provider_backoff_delay(attempt: int, *, retry_after_seconds: float | None) -> float:
    """ACT-MDL-FR-063, FR-064 — a provider-supplied ``Retry-After`` always
    wins over computed backoff. Otherwise: "equal jitter" -- delay = half +
    uniform(0, half), where half = min(MAX_DELAY, BASE_DELAY * 2**attempt) /
    2. This keeps the deterministic floor (``half``) strictly increasing
    across attempts (until the cap), so a backoff test can assert ordering
    without needing a fixed random seed, while still adding genuine
    randomized jitter on top of that floor."""
    return _backoff_delay(attempt, retry_after_seconds=retry_after_seconds,
                          base_delay=settings.MODEL_PROVIDER_RETRY_BASE_DELAY_SECONDS,
                          max_delay=settings.MODEL_PROVIDER_RETRY_MAX_DELAY_SECONDS)


# --------------------------------------------------------------------------- #
# Tool circuit breaker -- Phase 5.6a.2 SRS ACT-TLX-FR-027. Same neutral
# core as the provider breaker above, own store and own (TOOL_CIRCUIT_*)
# settings so a burst of tool failures can never trip a model provider's
# breaker or vice versa. Keyed by ``str(tool.id)`` -- a separate dict, not
# a shared namespace with ``_provider_circuit_state``, so no prefix is
# needed to avoid a name collision between a tool and a provider identifier.
# --------------------------------------------------------------------------- #
_tool_circuit_state: dict[str, _CircuitState] = {}


def reset_tool_circuit_breakers() -> None:
    """Test-only reset hook, mirroring ``reset_provider_circuit_breakers``."""
    _tool_circuit_state.clear()


def _tool_circuit_is_open(tool_identifier: str) -> bool:
    return _circuit_is_open(tool_identifier, _tool_circuit_state,
                            cooldown_seconds=settings.TOOL_CIRCUIT_COOLDOWN_SECONDS)


def _tool_circuit_record_success(tool_identifier: str) -> None:
    _circuit_note_success(tool_identifier, _tool_circuit_state)


def _tool_circuit_record_failure(tool_identifier: str) -> None:
    _circuit_note_failure(tool_identifier, _tool_circuit_state,
                          failure_threshold=settings.TOOL_CIRCUIT_FAILURE_THRESHOLD)


def _tool_backoff_delay(attempt: int, *, retry_after_seconds: float | None = None) -> float:
    return _backoff_delay(attempt, retry_after_seconds=retry_after_seconds,
                          base_delay=settings.TOOL_RETRY_BASE_DELAY_SECONDS,
                          max_delay=settings.TOOL_RETRY_MAX_DELAY_SECONDS)


# --------------------------------------------------------------------------- #
# Model Gateway (§40-§42) — provider-neutral, one working adapter (§4.5)
# --------------------------------------------------------------------------- #
class ModelGatewayError(IdentityError):
    pass


class ModelGatewayService:
    """§40 — Phase 5.7a.1 SRS ACT-MDL-FR-004, FR-005: ``invoke()`` selects a
    provider from the version's frozen ``model_configuration`` (never from
    mutable agent/deployment state) and delegates to
    ``app.runtime.providers.registry.resolve()`` — an unregistered
    provider still fails closed with ``MODEL_PROVIDER_UNAVAILABLE``
    (``ModelGatewayError``, unchanged), the same discipline §36 (default
    deny) applies everywhere else. ``MOCK`` is the only registered provider
    today; adding a second (OpenAI/Anthropic/Bedrock, §41, Phase 5.7a.2) is
    additive — one more ``register()`` call in ``providers/registry.py`` —
    not a change to this method's signature or the ``(output_payload,
    usage)`` contract every caller (``ExecutionWorkerService``) already
    depends on.

    This method is the translation boundary between the execution
    pipeline's legacy ``dict``-shaped ``input_payload``/``(output_payload,
    usage)`` contract and the provider-neutral ``ModelRequest``/
    ``ModelResponse`` types every provider actually speaks
    (``app.runtime.providers.types``) — the whole input payload becomes one
    user message; a provider's response content and token counts become
    the legacy ``output_payload``/``usage`` shape. See
    ``docs/runtime/providers.md`` for why this split exists.

    Phase 5.7a.3 (``ACT-MDL-FR-040..049``) added real streaming and token/
    cost accounting, without changing this signature or the
    ``(output_payload, usage)`` contract for any caller that doesn't ask
    for streaming: ``invoke(version, input_payload)`` with no ``stream``
    argument behaves for every existing caller exactly as it did before —
    ``config.get("stream", False)`` defaults every pre-5.7a.3
    ``model_configuration`` to the non-streaming path (``AC-07``). Opting
    a version into streaming is ``model_configuration = {..., "stream":
    true}``; ``usage`` grows several new keys either way (token/cost/
    timing accounting applies identically to both paths) but keeps every
    key existing callers already read."""

    def invoke(self, version: AgentVersion, input_payload: dict, *, stream: bool | None = None,
              resolved_credential: ResolvedCredential | None = None,
              conversation: "tuple | None" = None,
              tools: "tuple | None" = None) -> tuple[dict, dict]:
        """``resolved_credential`` (Phase 5.7a.5, ``ACT-MDL-FR-082``) is
        resolved by the *caller* — ``ExecutionWorkerService._execute``,
        synchronously, on the worker's own thread, via
        ``ProviderCredentialService`` — and handed in as a plain,
        immutable value. This method itself never touches a database: it
        may run inside a ``ThreadPoolExecutor`` (see the caller's own
        comment on why), and a live SQLAlchemy ``Session`` is not safe to
        share across threads. ``None`` (every pre-5.7a.5 caller) falls
        back to ``settings.MODEL_PROVIDER_API_KEYS``/``MODEL_PROVIDER_
        BASE_URLS`` exactly as before — this parameter is purely additive.

        ``conversation``/``tools`` (Phase 5.6a.3, ``ACT-TLX-FR-040``) are
        both purely additive, mirroring ``resolved_credential``'s own
        pattern exactly: every pre-5.6a.3 caller passes neither and gets
        bit-for-bit the same single-user-message request this method
        always built from ``input_payload``. ``ToolLoopOrchestrator`` is
        the only caller that ever supplies them — ``conversation`` is the
        full accumulated transcript (initial user message, prior assistant/
        tool turns) as a tuple of ``ModelMessage``, and ``tools`` is the
        set of ``ModelToolDefinition`` bound to this version's frozen
        ``tools_snapshot``, built fresh by the orchestrator every call (a
        provider that doesn't declare ``supports_tools`` in ``describe()``
        — ``MOCK``, always — simply never receives any, so nothing about
        MOCK's behavior changes here either). ``input_payload`` is still
        threaded through unchanged for the returned ``output_payload``'s
        ``"echo"`` field and the simulated-delay test hook below, even when
        ``conversation`` overrides what's actually sent as messages."""
        from app.runtime.providers.registry import resolve as resolve_provider
        from app.runtime.providers.types import ModelMessage, ModelRequest, ProviderErrorClass

        config = version.model_configuration or {}
        provider_name = (config.get("provider") or settings.MODEL_DEFAULT_PROVIDER).upper()
        api_key = (resolved_credential.api_key if resolved_credential is not None
                  else settings.MODEL_PROVIDER_API_KEYS.get(provider_name))
        base_url = (
            (resolved_credential.base_url if resolved_credential is not None else None)
            or settings.MODEL_PROVIDER_BASE_URLS.get(provider_name)
        )
        try:
            provider = resolve_provider(
                provider_name, base_url=base_url, model=config.get("model"), api_key=api_key,
            )
        except IdentityError as exc:
            # Preserve the pre-abstraction exception type callers/tests catch.
            raise ModelGatewayError(exc.code, exc.message) from exc

        # Test/simulation hook only — lets the timeout enforcement in
        # ExecutionWorkerService be exercised deterministically without a
        # real slow provider. Never triggered by normal input.
        simulated_delay = input_payload.get("__simulate_slow_seconds__") if isinstance(input_payload, dict) else None
        if simulated_delay:
            time.sleep(float(simulated_delay))

        messages = conversation if conversation is not None else (
            ModelMessage(role="user", content=json.dumps(input_payload, default=str)),
        )
        # ACT-MDL-FR-009 -- never offer tools to a provider that hasn't
        # declared it supports them (validate_capabilities() would raise
        # anyway; checked here too so a provider without tool support is
        # simply never asked, rather than every caller needing to know to
        # gate this itself).
        offered_tools = tools if (tools and provider.describe().supports_tools) else ()
        request = ModelRequest(
            messages=messages, tools=offered_tools,
            sampling_parameters={k: v for k, v in config.items() if k not in ("provider", "model", "stream")},
        )

        should_stream = config.get("stream", False) if stream is None else stream
        if should_stream:
            return self._invoke_streaming(provider, provider_name, config, request, input_payload)

        start = time.monotonic()
        try:
            response = self._complete_with_resilience(provider, provider_name, request)
        except ProviderRequestFailedError as exc:
            # ACT-MDL-FR-083/AC-09 — a real provider rejecting an
            # unauthenticated call (AUTHENTICATION_FAILED) is a more
            # actionable, specific condition when *this organization never
            # configured a credential at all* than when one was configured
            # but wrong: the former is "go configure one," the latter is
            # "your configured value is wrong." Only the first case is
            # translated; a credential that was present and still rejected
            # stays AUTHENTICATION_FAILED, unchanged from 5.7a.4.
            if exc.error_class == ProviderErrorClass.AUTHENTICATION_FAILED and not api_key:
                raise ModelGatewayError(
                    ErrorCode.PROVIDER_CREDENTIAL_REQUIRED,
                    f"Provider '{provider_name}' requires a credential and none is configured "
                    "for this organization.",
                ) from exc
            raise
        generation_duration_ms = int((time.monotonic() - start) * 1000)

        usage = {
            "provider": provider_name, "model": config.get("model", "mock-model"),
            "input_tokens": response.raw_usage.get("input_tokens", 0),
            "output_tokens": response.raw_usage.get("output_tokens", 0),
            "total_tokens": response.raw_usage.get("total_tokens", 0),
            "token_accounting_complete": bool(response.raw_usage),
            "was_streamed": False,
            "stream_interrupted": False,
            "interruption_reason": None,
            "time_to_first_token_ms": None,
            "generation_duration_ms": generation_duration_ms,
            "finish_reason": response.finish_reason.value,
            # Phase 5.6a.3 (ACT-TLX-FR-040) -- a new, additive key; every
            # pre-5.6a.3 reader of this dict simply never looks at it. Empty
            # whenever the model didn't request a tool this turn (every
            # existing caller/test, always, since none ever supplies
            # `tools`). Plain, JSON-safe shape -- never the frozen
            # ModelToolCall dataclass itself.
            "tool_calls": [{"id": c.id, "name": c.name, "arguments": dict(c.arguments)}
                          for c in response.tool_calls],
        }
        output_payload = {"result": response.content, "echo": input_payload}
        return output_payload, usage

    def _complete_with_resilience(self, provider, provider_name: str, request):
        """Phase 5.7a.4 ``ACT-MDL-FR-060..068`` — wraps a single non-
        streaming ``provider.complete()`` call with the per-provider
        circuit breaker and, for a transient classification only, retry
        with backoff. Lives here (the service layer), not in the adapter:
        the adapter classifies (``ProviderRequestFailedError.error_class``),
        this decides whether that classification is worth retrying — the
        same retry code applies unchanged to any future adapter that
        classifies into the same taxonomy.

        Entirely contained within one call — every retry here happens
        inside the single ``execution_attempts`` row the caller
        (``ExecutionWorkerService``) already writes for this attempt; the
        pre-existing, unrelated execution-level retry (a fresh worker claim
        after this raises) is untouched and still applies on top for
        transient classes, per its own existing policy."""
        _circuit_before_call(provider_name)
        max_retries = settings.MODEL_PROVIDER_MAX_RETRIES
        attempt = 0
        while True:
            try:
                response = provider.complete(request)
            except ProviderRequestFailedError as exc:
                _circuit_record_failure(provider_name)
                if exc.error_class not in RETRYABLE_PROVIDER_ERROR_CLASSES or attempt >= max_retries:
                    raise
                time.sleep(_provider_backoff_delay(attempt, retry_after_seconds=exc.retry_after_seconds))
                attempt += 1
                continue
            _circuit_record_success(provider_name)
            return response

    def _stream_once(self, provider, provider_name: str, config: dict, request, input_payload: dict,
                     ) -> tuple[dict, dict, bool, ProviderErrorClass | None, float | None]:
        """``ACT-MDL-FR-041..043, FR-048, FR-049`` — consumes
        ``provider.stream()`` chunk by chunk (never buffering the whole
        response before starting), measuring time-to-first-token and total
        generation duration, enforcing ``MODEL_STREAM_MAX_DURATION_SECONDS``
        by simply no longer calling ``next()`` on the generator once the
        budget is exceeded (the abandoned generator's own ``with``-managed
        HTTP connection is closed on garbage collection — see
        ``OpenAICompatibleProvider.stream()``), and reassembling the
        consumed chunks into the same ``(output_payload, usage)`` shape the
        non-streaming path returns.

        Returns one extra tuple element beyond ``(output_payload, usage)``
        (Phase 5.7a.4): whether *this one attempt's* interruption is
        retryable pre-first-token, plus the classification/retry-after that
        decision was based on — consumed only by ``_invoke_streaming``'s
        retry loop, never returned to ``invoke()``'s own caller."""
        from app.runtime.providers.types import FinishReason, assemble_response

        start = time.monotonic()
        time_to_first_token_ms: int | None = None
        chunks = []
        max_duration = settings.MODEL_STREAM_MAX_DURATION_SECONDS
        truncated_by_duration = False
        for chunk in provider.stream(request):
            if time_to_first_token_ms is None and chunk.content:
                time_to_first_token_ms = int((time.monotonic() - start) * 1000)
            chunks.append(chunk)
            if (time.monotonic() - start) > max_duration:
                truncated_by_duration = True
                break

        generation_duration_ms = int((time.monotonic() - start) * 1000)
        assembled = assemble_response(chunks) if chunks else None
        provider_signaled_error = (
            not truncated_by_duration and assembled is not None and assembled.finish_reason == FinishReason.ERROR
        )
        stream_interrupted = truncated_by_duration or provider_signaled_error

        error_class = None
        retry_after_seconds = None
        if truncated_by_duration:
            interruption_reason = f"Stream exceeded the maximum response duration of {max_duration}s."
            reported_finish_reason = None
        elif provider_signaled_error:
            interruption_reason = "Provider stream ended unexpectedly (connection error or malformed response)."
            reported_finish_reason = FinishReason.ERROR.value
            error_class = assembled.error_class
            retry_after_seconds = assembled.retry_after_seconds
        else:
            interruption_reason = None
            reported_finish_reason = assembled.finish_reason.value if assembled else None

        raw_usage = assembled.raw_usage if assembled else {}
        usage = {
            "provider": provider_name, "model": config.get("model", "mock-model"),
            "input_tokens": raw_usage.get("input_tokens", 0),
            "output_tokens": raw_usage.get("output_tokens", 0),
            "total_tokens": raw_usage.get("total_tokens", 0),
            "token_accounting_complete": bool(raw_usage),
            "was_streamed": True,
            "stream_interrupted": stream_interrupted,
            "interruption_reason": interruption_reason,
            "time_to_first_token_ms": time_to_first_token_ms,
            "generation_duration_ms": generation_duration_ms,
            "finish_reason": reported_finish_reason,
        }
        output_payload = {"result": assembled.content if assembled else "", "echo": input_payload}

        # ACT-MDL-FR-061/FR-062 -- retryable only if nothing was ever
        # emitted yet (a caller that already received partial content must
        # not have it silently discarded by a retry) *and* the platform's
        # own duration cutoff isn't the cause (retrying that would just hit
        # the same cutoff again -- it's a policy limit, not a provider
        # failure) *and* the classification itself is transient.
        retryable_pre_first_token = (
            stream_interrupted and time_to_first_token_ms is None and not truncated_by_duration
            and error_class in RETRYABLE_PROVIDER_ERROR_CLASSES
        )
        return output_payload, usage, retryable_pre_first_token, error_class, retry_after_seconds

    def _invoke_streaming(self, provider, provider_name: str, config: dict, request, input_payload: dict,
                         ) -> tuple[dict, dict]:
        """Phase 5.7a.4 — wraps ``_stream_once`` with the same per-provider
        circuit breaker and transient-class retry ``_complete_with_
        resilience`` applies to ``complete()``, honoring the streaming
        retry boundary (``ACT-MDL-FR-061..064``): only a pre-first-token,
        transiently-classified interruption retries (a fresh
        ``provider.stream(request)`` call); anything else — content already
        emitted, a non-transient class, the duration cutoff, or attempts
        exhausted — returns exactly what ``_stream_once`` produced, exactly
        as this method always has."""
        _circuit_before_call(provider_name)
        max_retries = settings.MODEL_PROVIDER_MAX_RETRIES
        attempt = 0
        while True:
            output_payload, usage, retryable, error_class, retry_after_seconds = self._stream_once(
                provider, provider_name, config, request, input_payload)
            if retryable and attempt < max_retries:
                _circuit_record_failure(provider_name)
                time.sleep(_provider_backoff_delay(attempt, retry_after_seconds=retry_after_seconds))
                attempt += 1
                continue
            if usage["stream_interrupted"]:
                _circuit_record_failure(provider_name)
            else:
                _circuit_record_success(provider_name)
            return output_payload, usage


# --------------------------------------------------------------------------- #
# Tool schema validation & HTTP-failure classification (Phase 5.6a.2 SRS
# ACT-TLX-FR-020..028)
# --------------------------------------------------------------------------- #
def _tool_schema_violation(instance, schema: dict | None) -> dict | None:
    """Validates ``instance`` against ``schema`` using the same
    ``jsonschema`` library (and the tool's own already-declared JSON-Schema
    parameters — ACT-TLX-FR-020's "reuse the existing schema language, not
    a new one") ``_validate_schema`` above uses for the agent-level input/
    output contract. Returns ``None`` -- valid, *or* no schema declared at
    all (§10.15 raise-don't-guess: absence of a schema is not itself a
    violation) -- or a structured, model-readable description of the first
    violation ``jsonschema`` reports."""
    if not schema:
        return None
    try:
        jsonschema.validate(instance=instance, schema=schema)
    except jsonschema.ValidationError as exc:
        return {"message": exc.message, "path": list(exc.absolute_path), "schema_path": list(exc.absolute_schema_path)}
    except jsonschema.SchemaError as exc:
        return {"message": f"The tool's declared schema is invalid: {exc.message}", "path": [], "schema_path": []}
    return None


def _classify_tool_http_status(status_code: int) -> ProviderErrorClass:
    """Phase 5.6a.2 — reuses the exact status-code boundaries
    ``openai_compatible._classify_status_error`` established for the model
    side (429 / 401,403 / 5xx / other 4xx), minus the two model-specific
    body-text markers (context-length / content-filter) that have no
    meaning for an arbitrary third-party HTTP tool's response."""
    if status_code == 429:
        return ProviderErrorClass.RATE_LIMITED
    if status_code in (401, 403):
        return ProviderErrorClass.AUTHENTICATION_FAILED
    if status_code >= 500:
        return ProviderErrorClass.PROVIDER_UNAVAILABLE
    if status_code >= 400:
        return ProviderErrorClass.INVALID_REQUEST
    return ProviderErrorClass.UNKNOWN


def _classify_tool_execution_failure(result) -> tuple[ProviderErrorClass, str]:
    """Maps a completed (already egress-*allowed*) ``HttpExecutionResult``
    that was not a plain success onto the **same** ``ProviderErrorClass``
    taxonomy 5.7a.4 built for model calls (AC-12) plus this sub-phase's own
    ``ErrorCode``. ``REDIRECT_DEPTH_EXCEEDED``/``RESPONSE_TOO_LARGE`` have
    no natural bucket in an eight-class taxonomy built for model-provider
    failures — both deliberately map to ``UNKNOWN``: ``UNKNOWN`` is already
    guaranteed never to retry (``RETRYABLE_PROVIDER_ERROR_CLASSES``), which
    is the correct behavior for both (retrying either reaches an identical
    outcome every time against the same target — there is nothing transient
    about a response that is simply too large, or a redirect chain that
    simply loops)."""
    if result.error == "TIMEOUT":
        return ProviderErrorClass.TIMEOUT, ErrorCode.TOOL_TIMEOUT
    if result.error == "RESPONSE_TOO_LARGE":
        return ProviderErrorClass.UNKNOWN, ErrorCode.TOOL_RESPONSE_TOO_LARGE
    if result.error and result.error.startswith("TRANSPORT_ERROR"):
        return ProviderErrorClass.PROVIDER_UNAVAILABLE, ErrorCode.TOOL_EXECUTION_FAILED
    if result.error in ("REDIRECT_DEPTH_EXCEEDED", "REDIRECT_MISSING_LOCATION"):
        return ProviderErrorClass.UNKNOWN, ErrorCode.TOOL_EXECUTION_FAILED
    if result.status is not None:
        return _classify_tool_http_status(result.status), ErrorCode.TOOL_EXECUTION_FAILED
    return ProviderErrorClass.UNKNOWN, ErrorCode.TOOL_EXECUTION_FAILED


# --------------------------------------------------------------------------- #
# Tool credentials (Phase 5.6a.1 SRS ACT-TLX-FR-012)
# --------------------------------------------------------------------------- #
class ToolCredentialService:
    """Per-organization, per-tool credential storage for the HTTP action,
    encrypted at rest — the same storage pattern and encryption utility
    (``app/runtime/providers/credential_crypto.py``) Phase 5.7a.5 built for
    model-provider credentials, reused directly rather than duplicated. A
    deliberately smaller surface than ``ProviderCredentialService``: no
    fallback chain, no ``base_url`` override, no CRUD API in this
    sub-phase (§7 of the build prompt: "likely no new HTTP surface") —
    just ``store``/``resolve_secret``/``delete``, sufficient for what
    ``ToolGatewayService``'s HTTP branch needs. A future sub-phase can add
    a management API the same way 5.7a.5 added one for provider
    credentials, without changing this storage layer."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _get_row(self, organization_id: uuid.UUID, tool_id: uuid.UUID) -> ToolCredential | None:
        return self.db.execute(
            select(ToolCredential).where(
                ToolCredential.organization_id == organization_id, ToolCredential.tool_id == tool_id,
            )
        ).scalars().first()

    def store(self, actor: User, organization_id: uuid.UUID, tool_id: uuid.UUID, secret: str) -> ToolCredential:
        from app.runtime.providers.credential_crypto import encrypt_secret, mask_hint

        row = self._get_row(organization_id, tool_id)
        encrypted, hint = encrypt_secret(secret), mask_hint(secret)
        if row is None:
            row = ToolCredential(organization_id=organization_id, tool_id=tool_id, encrypted_secret=encrypted,
                                 secret_hint=hint, status="ACTIVE", created_by=actor.id)
            self.db.add(row)
        else:
            row.encrypted_secret = encrypted
            row.secret_hint = hint
            row.status = "ACTIVE"
        self.db.commit()
        self.db.refresh(row)
        return row

    def resolve_secret(self, organization_id: uuid.UUID, tool_id: uuid.UUID) -> str | None:
        """The one place a stored tool credential is decrypted. Returns
        ``None`` (not an error) when nothing is configured — a tool
        declaring ``requires_credential`` with nothing stored is a
        configuration gap the HTTP executor surfaces as a normal request
        failure (no ``Authorization`` header reaches the remote side),
        never a crash."""
        from app.runtime.providers.credential_crypto import decrypt_secret

        row = self._get_row(organization_id, tool_id)
        if row is None or row.status != "ACTIVE":
            return None
        return decrypt_secret(row.encrypted_secret)

    def delete(self, actor: User, organization_id: uuid.UUID, tool_id: uuid.UUID) -> None:
        row = self._get_row(organization_id, tool_id)
        if row is not None:
            self.db.delete(row)
            self.db.commit()


# --------------------------------------------------------------------------- #
# Tool Gateway (§43, §44)
# --------------------------------------------------------------------------- #
class ToolGatewayService:
    """§43 — every tool call is validated against the agent's tool
    assignment and constraints (§23) before it runs. ``FUNCTION``'s
    built-in ``EXECUTE``/``READ`` echo actions, and (Phase 5.6a.1) the
    ``HTTP`` action, are the only tool types actually executable in this
    environment; every other tool type is fully modeled (registry,
    assignment, constraints, authorization) but fails closed with
    ``TOOL_ACTION_NOT_ALLOWED`` if invoked, matching §36 default deny.
    Every attempted call — allowed, denied for constraint violation, denied
    at the egress boundary, or denied for an unconnected tool type — is
    recorded as a ``ToolCall`` row so it's auditable regardless of outcome.

    **The HTTP action's egress allowlist, per-tool caps, and input/output
    schema are all read from the frozen version snapshot, never from the
    live, mutable ``Tool`` row** — see ``_frozen_tool_entry`` — matching
    this platform's existing rule that every tool invocation is verified
    against what the *version* actually declared, not whatever a tool has
    since been edited to (Phase 5.2 immutability). See
    ``docs/runtime/gateways.md``'s "Egress control" and "Schema validation
    & resilience" sections for the full SSRF defense and retry/circuit-
    breaker design this class relies on (``app/runtime/tools/egress_
    guard.py``/``http_executor.py``/``concurrency.py``)."""

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
        entry = self._frozen_tool_entry(db, execution, tool)
        # Phase 5.6a.2 (ACT-TLX-FR-020, FR-021, AC-02, AC-04) -- argument
        # validation runs before *anything* else that could have a side
        # effect (before FUNCTION's echo, and before the HTTP branch even
        # builds an EgressPolicy, let alone resolves DNS) -- no point
        # evaluating egress for a call whose arguments are already invalid.
        # Constraint violations still take precedence: an action this
        # agent isn't authorized for at all is rejected before its
        # arguments are even looked at.
        input_violation = None if constraint_violation else _tool_schema_violation(
            params, (entry or {}).get("input_schema"))

        if constraint_violation:
            call.status = "DENIED"
            call.error_code = ErrorCode.TOOL_CONSTRAINT_VIOLATION
        elif input_violation is not None:
            call.status = "FAILED"
            call.error_code = ErrorCode.TOOL_SCHEMA_INVALID
            call.error_class = ProviderErrorClass.INVALID_REQUEST.value
            call.attempt_number = 1
            call.validation_error = json.dumps(input_violation)
        elif tool.tool_type == "FUNCTION" and action in self.EXECUTABLE_ACTIONS:
            call.status = "ALLOWED"
            call.output_summary = {"echo": params}
            call.attempt_number = 1
            call.cost = 0
        elif tool.tool_type == "HTTP" and action in self.EXECUTABLE_ACTIONS:
            call = self._invoke_http(db, execution, agent, tool, call, params, entry)
        else:
            call.status = "DENIED"
            call.error_code = ErrorCode.TOOL_ACTION_NOT_ALLOWED
        call.completed_at = _now()
        # `call` may have been reassigned to a fresh row for a later retry
        # attempt (see `_invoke_http`) -- always measure against *that*
        # row's own `started_at`, never the outer `started` from before the
        # whole (possibly multi-attempt) invocation began.
        call.duration_ms = int((call.completed_at - (call.started_at or started)).total_seconds() * 1000)
        db.add(call)
        db.flush()
        if call.status == "FAILED":
            # Phase 5.6a.2 (ACT-TLX-FR-028, AC-20) -- unlike a ``DENIED``
            # call (a governance/authorization/egress-policy fact, unchanged
            # from before this sub-phase), a ``FAILED`` call is the outcome
            # of an *attempted* invocation: a schema violation, an
            # exhausted retry, a timeout, an oversized response, an open
            # circuit, or a concurrency-ceiling rejection. None of these
            # abort the execution -- the structured error lives on this row
            # (``error_code``/``error_class``/``validation_error``) for a
            # future model turn (5.6a.3's loop) to read and act on.
            _record_event(db, AuthorizationAuditEvent.RUNTIME_TOOL_FAILED, None,
                         organization_id=agent.organization_id, agent_id=agent.id, execution_id=execution.id,
                         meta={"tool": tool.name, "error_code": call.error_code, "error_class": call.error_class})
        elif call.status == "DENIED":
            if constraint_violation:
                raise IdentityError(ErrorCode.TOOL_CONSTRAINT_VIOLATION, constraint_violation)
            if call.error_code == ErrorCode.TOOL_EGRESS_DENIED:
                # ACT-TLX-FR-069-equivalent for tools: the *reason* lives on
                # the ToolCall row (egress_denied_reason) and the security
                # event below for an admin to inspect -- the message an
                # untrusted caller/model sees never repeats the target host,
                # resolved IP, or any other topology detail (§7).
                raise IdentityError(ErrorCode.TOOL_EGRESS_DENIED,
                                   f"Outbound request from tool '{tool_name}' was denied by egress policy.")
            raise IdentityError(ErrorCode.TOOL_ACTION_NOT_ALLOWED,
                               f"Tool type '{tool.tool_type}' is not connected in this environment.")
        return call

    def _frozen_tool_entry(self, db: Session, execution: AgentExecution, tool: Tool) -> dict | None:
        """``ACT-TLX-FR-004``/``ACT-TLX-FR-020``/``AC-10``/``AC-16``/
        ``AC-28`` — every per-tool declaration this sub-phase and 5.6a.1
        enforce (the HTTP egress policy, the input/output schema, the
        idempotency flag, the size/timeout caps) comes from the *frozen*
        snapshot document built at publish time (``SnapshotBuilderService``),
        never from the live, mutable ``Tool`` row directly: returns
        ``None`` both when the version has no snapshot yet (cannot happen
        for anything actually executing — see docs/runtime/gateways.md)
        and, more importantly, when this specific tool was never part of
        ``tools_snapshot`` at publish time at all — a tool an agent was
        assigned *after* publish, or removed from the version's frozen
        tool list, has no entry here and is treated as declaring nothing
        (no schema to validate against; the HTTP branch separately treats
        a missing/empty entry as an outright denial, exactly as a tool
        call must be "verified against tools_snapshot.\")"""
        snapshot_row = db.execute(
            select(AgentVersionSnapshot).where(AgentVersionSnapshot.agent_version_id == execution.agent_version_id)
        ).scalars().first()
        if snapshot_row is None:
            return None
        tool_configs = ((snapshot_row.snapshot or {}).get("runtime") or {}).get("tool_configs") or {}
        return tool_configs.get(str(tool.id))

    def _invoke_http(self, db: Session, execution: AgentExecution, agent: Agent, tool: Tool,
                     call: ToolCall, params: dict, entry: dict | None) -> ToolCall:
        """Returns the ``ToolCall`` row representing the *final* attempt —
        ``call`` itself for a call that never retries, or a fresh row (with
        its own ``attempt_number``) when ``call``'s own attempt failed
        transiently and the tool is declared idempotent. Every non-final
        attempt is flushed here directly (it needs to be durable before the
        next attempt's backoff sleep); only the final row is left for
        ``invoke()`` above to finish (``completed_at``/``duration_ms``/
        ``db.add``/``db.flush``), exactly as every other branch there
        already works.

        Never raises for anything this method itself decides (an egress
        denial, a schema-invalid response, an exhausted retry, a timeout, a
        too-large response, an open circuit, a concurrency-ceiling
        rejection) -- ``invoke()`` is still the single place a ``DENIED``
        call becomes an exception, and (Phase 5.6a.2) a ``FAILED`` call
        never does."""
        from app.runtime.tools.concurrency import ToolConcurrencyLimitExceeded, track as track_concurrency
        from app.runtime.tools.egress_guard import DEFAULT_MAX_REDIRECTS, EgressPolicy
        from app.runtime.tools.http_executor import (
            DEFAULT_MAX_RESPONSE_BYTES,
            DEFAULT_TIMEOUT_SECONDS,
            execute_http_tool,
            redact_body,
            redact_headers,
        )

        http_config = (entry or {}).get("http_config")
        if not http_config or not http_config.get("allowed_hosts"):
            call.status = "DENIED"
            call.error_code = ErrorCode.TOOL_ACTION_NOT_ALLOWED
            return call

        policy = EgressPolicy(
            allowed_hosts=frozenset(http_config.get("allowed_hosts") or ()),
            allow_plaintext_http=bool(http_config.get("allow_plaintext_http", False)),
            local_dev_hosts=frozenset(http_config.get("local_dev_hosts") or ()),
            max_redirects=int(http_config.get("max_redirects", DEFAULT_MAX_REDIRECTS)),
        )
        sensitive_headers = frozenset(http_config.get("sensitive_headers") or ())
        sensitive_body_fields = frozenset(http_config.get("sensitive_body_fields") or ())
        # ACT-TLX-FR-010 -- the HTTP method is derived from the already-
        # authorized `action` (or a tool-fixed override), never from `params`:
        # a model asking for "READ" can never smuggle in a DELETE.
        method = http_config.get("method") or ("GET" if call.action == "READ" else "POST")
        # ACT-TLX-FR-023/024/026, AC-10 -- all three read from the frozen
        # snapshot copy (`_frozen_http_config` in snapshot.py already
        # defaulted `timeout_seconds` in from the tool's own column at
        # publish time), never from the live `Tool` row at execution time.
        timeout_seconds = float(http_config.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
        max_response_bytes = int(http_config.get("max_response_bytes", DEFAULT_MAX_RESPONSE_BYTES))
        idempotent = bool(http_config.get("idempotent", False))
        output_schema = (entry or {}).get("output_schema")

        headers: dict[str, str] = {}
        if http_config.get("requires_credential"):
            secret = ToolCredentialService(db).resolve_secret(agent.organization_id, tool.id)
            if secret:
                header_name = http_config.get("credential_header", "Authorization")
                scheme = http_config.get("credential_scheme", "Bearer")
                headers[header_name] = f"{scheme} {secret}" if scheme else secret

        # ACT-TLX-FR-013/AC-24 -- record which headers were actually sent,
        # redacted, so an admin auditing this call can see *that* a
        # credential was attached without ever seeing its value.
        call.input_summary = {**(call.input_summary or {}), "_request_headers": redact_headers(
            headers, sensitive_headers)} if headers else call.input_summary

        # ACT-TLX-FR-010 -- only the path/query/body of `params` (model-
        # influenceable) ever reach the request; the host always comes from
        # `tool.endpoint_reference` (the tool's own declared, allowlisted
        # base) via `_build_target_url`'s deliberate refusal to resolve an
        # absolute URL supplied here against that base.
        path = params.get("path") if isinstance(params, dict) else None
        query = params.get("query") if isinstance(params, dict) else None
        body = params.get("body") if isinstance(params, dict) else None

        tool_identifier = str(tool.id)
        # ACT-TLX-FR-027, AC-19 -- checked once, before the retry loop even
        # starts (mirroring `_complete_with_resilience`'s own call pattern
        # exactly: the model-side breaker isn't re-checked between retries
        # either, since a failure inside this same call already updates the
        # state via `_tool_circuit_record_failure` below, and re-opening
        # mid-loop would just be this same check repeated for no new
        # information).
        circuit_open = _tool_circuit_is_open(tool_identifier)
        max_retries = settings.TOOL_MAX_RETRIES
        max_concurrent = settings.TOOL_MAX_CONCURRENT_REQUESTS_PER_EXECUTION

        current = call
        attempt = 0
        while True:
            current.attempt_number = attempt + 1
            attempt_started = current.started_at or _now()

            if circuit_open:
                current.status = "FAILED"
                current.error_code = ErrorCode.TOOL_EXECUTION_FAILED
                current.error_class = ProviderErrorClass.PROVIDER_UNAVAILABLE.value
                current.output_summary = {
                    "error": "circuit_open",
                    "message": f"Tool '{tool.name}' circuit breaker is open; failing fast without a request.",
                }
                return current

            try:
                with track_concurrency(execution.id, limit=max_concurrent):
                    result = execute_http_tool(
                        method=method, base_url=tool.endpoint_reference or "", path=path, query=query,
                        headers=headers, json_body=body, policy=policy,
                        sensitive_headers=sensitive_headers, sensitive_body_fields=sensitive_body_fields,
                        max_response_bytes=max_response_bytes, timeout_seconds=timeout_seconds,
                    )
            except ToolConcurrencyLimitExceeded as exc:
                current.status = "FAILED"
                current.error_code = ErrorCode.TOOL_CONCURRENCY_LIMIT_EXCEEDED
                current.output_summary = {"error": "concurrency_limit_exceeded", "message": str(exc)}
                return current

            decision = result.egress_decision
            current.target_host = decision.host
            current.http_method = method
            current.egress_decision = "ALLOWED" if decision.allowed else "DENIED"
            current.egress_denied_reason = decision.reason

            if not decision.allowed:
                # Unchanged from 5.6a.1 -- an egress denial is a policy
                # fact about the target, never retried, and never touches
                # the circuit breaker (a different concern; see
                # docs/runtime/gateways.md).
                current.status = "DENIED"
                current.error_code = ErrorCode.TOOL_EGRESS_DENIED
                _record_event(db, AuthorizationAuditEvent.RUNTIME_TOOL_EGRESS_DENIED, None,
                             organization_id=agent.organization_id, agent_id=agent.id, execution_id=execution.id,
                             severity="CRITICAL",
                             meta={"tool": tool.name, "host": decision.host, "reason": decision.reason})
                return current

            current.target_path = (path or "")[:2048] if path else None
            current.http_status = result.status
            current.request_bytes = result.request_bytes
            current.response_bytes = result.response_bytes

            parsed_body = None
            if result.response_body_redacted:
                try:
                    parsed_body = json.loads(result.response_body_redacted)
                except ValueError:
                    parsed_body = None

            succeeded = result.error is None and result.status is not None and result.status < 400
            if succeeded:
                # ACT-TLX-FR-022/AC-05/AC-06 -- validated only when the
                # tool declared an output schema; absent one, this is a
                # no-op (never guessed at). A violation here is never
                # retried (it isn't a transient failure) and never touches
                # the circuit breaker (the target responded correctly by
                # its own lights; it's this platform's contract check that
                # failed, not the target's reliability).
                output_violation = _tool_schema_violation(parsed_body, output_schema)
                if output_violation is not None:
                    current.status = "FAILED"
                    current.error_code = ErrorCode.TOOL_SCHEMA_INVALID
                    current.error_class = ProviderErrorClass.INVALID_REQUEST.value
                    current.validation_error = json.dumps(output_violation)
                    current.output_summary = {"status": result.status, "truncated": result.truncated}
                    return current

                current.status = "ALLOWED"
                current.cost = 0
                current.output_summary = {
                    "status": result.status,
                    "body": redact_body(parsed_body, sensitive_body_fields) if isinstance(parsed_body, dict) else None,
                    "truncated": result.truncated,
                    "error": result.error,
                }
                _tool_circuit_record_success(tool_identifier)
                _record_event(db, AuthorizationAuditEvent.RUNTIME_TOOL_INVOKED, None,
                             organization_id=agent.organization_id, agent_id=agent.id, execution_id=execution.id,
                             meta={"tool": tool.name, "host": decision.host, "status": result.status})
                return current

            # ACT-TLX-FR-025/FR-026, AC-12..17 -- a transient, HTTP-level
            # failure. Classified into the *same* taxonomy 5.7a.4 built for
            # model calls; retried only if this tool is declared idempotent
            # (never inferred from `method` -- undeclared means no, per
            # ACT-TLX-FR-026) and the classification is one of the three
            # retryable classes, using the same backoff formula and the
            # same per-tool circuit breaker as every other attempt.
            error_class, error_code = _classify_tool_execution_failure(result)
            current.error_class = error_class.value
            current.error_code = error_code
            current.output_summary = {"status": result.status, "truncated": result.truncated, "error": result.error}
            _tool_circuit_record_failure(tool_identifier)

            retryable = idempotent and error_class in RETRYABLE_PROVIDER_ERROR_CLASSES
            if retryable and attempt < max_retries:
                current.status = "FAILED"
                current.completed_at = _now()
                current.duration_ms = int((current.completed_at - attempt_started).total_seconds() * 1000)
                db.add(current)
                db.flush()
                time.sleep(_tool_backoff_delay(attempt, retry_after_seconds=result.retry_after_seconds))
                attempt += 1
                current = ToolCall(execution_id=execution.id, agent_id=agent.id, tool_id=tool.id,
                                   action=call.action, input_summary=call.input_summary, started_at=_now())
                continue

            current.status = "FAILED"
            return current

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

    def request_execution(self, actor: User, payload: dict, *,
                          trace: "TraceContext | None" = None) -> AgentExecution:
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
            authorize=authorize, worker_id=f"inline-{actor.id}", trace=trace)

    def request_execution_as_agent(self, agent: Agent, payload: dict, *,
                                   trace: "TraceContext | None" = None) -> AgentExecution:
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
            authorize=authorize, worker_id=f"inline-agent-{agent.id}", trace=trace)

    def _request_execution(self, agent: Agent, payload: dict, *, principal: User | Agent,
                           trigger_type: str, authorize, worker_id: str,
                           trace: "TraceContext | None" = None) -> AgentExecution:
        if agent.lifecycle_status == "SUSPENDED":
            raise IdentityError(ErrorCode.AGENT_SUSPENDED, "Agent is suspended.")
        if agent.lifecycle_status not in ("ACTIVE",):
            raise IdentityError(ErrorCode.AGENT_NOT_ACTIVE, "Agent is not active.")

        # Phase 3.4 (ACT-SRS-M3 §Phase-3.4) -- THE version resolver and
        # ruling #4's execution gate: Milestone 3's single, deliberate change
        # to this path. What was a direct 1:1 read of the active deployment's
        # own ``agent_version_id`` now resolves (agent, environment) through
        # the deployment's traffic allocation to one immutable version.
        #
        # The gate itself is not new here: this method has always required an
        # active deployment (the two raises now living in
        # ``VersionResolver.resolve``, with their original error codes and
        # HTTP statuses preserved verbatim). What 3.4 adds is *weighted
        # resolution* and the new fail-closed ``NO_ACTIVE_DEPLOYMENT`` mode
        # for an allocation whose versions have all stopped serving.
        #
        # Everything below this block is untouched. In particular the
        # ``authorize(deployment)`` call further down still runs, on the
        # resolved deployment, exactly as before -- the resolver selects a
        # version and returns; it never dispatches and never authorizes.
        # See app.runtime.deployment.resolver's module docstring.
        from app.runtime.deployment.resolver import VersionResolver

        try:
            resolution = VersionResolver(self.db).resolve(
                agent,
                deployment_id=payload.get("deployment_id"),
                environment=payload.get("environment"),
                routing_key=_routing_key(payload, principal),
            )
        except IdentityError as exc:
            # §8 -- the fail-closed rejection is observable. There is no
            # execution row to hang this off (the gate runs before one is
            # created, by design: a rejected request must not leave a
            # phantom execution behind), so it is recorded against the agent.
            _record_event(self.db, AuthorizationAuditEvent.RUNTIME_EXECUTION_NO_ACTIVE_DEPLOYMENT,
                         principal, organization_id=agent.organization_id, agent_id=agent.id,
                         severity="WARNING",
                         meta={"code": str(exc.code),
                              "environment": payload.get("environment"),
                              "deployment_id": str(payload.get("deployment_id") or "") or None})
            self.db.commit()
            raise
        deployment = resolution.deployment
        version = resolution.version
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

        # Phase 4.1 (M4-4.1-FR-002) -- the first leg of trace propagation, and
        # the one that was broken. Until now `correlation_id` came *only* from
        # the request body, so unless a caller explicitly put one there the
        # column stayed null: 74,395 of 74,619 executions in the development
        # database had no trace identity at all.
        #
        # Precedence is deliberate: an explicit body field still wins, because
        # a caller that names its own correlation means it. Otherwise the
        # `x-correlation-id` header joins this execution to the caller's
        # existing trace, and failing both, a fresh id is minted so that every
        # execution from here on is findable.
        #
        # Note what is *not* touched: `_routing_key` above already read
        # `payload["correlation_id"]` for Phase 3.4 sticky version resolution,
        # and it still reads exactly that. The header-derived and minted ids
        # never enter `payload`, so version selection is bit-identical to
        # before this phase -- an auto-minted correlation must not silently
        # turn every request into a sticky one.
        correlation_id = payload.get("correlation_id") or (trace.trace_id if trace else None)
        execution = AgentExecution(
            organization_id=agent.organization_id, agent_id=agent.id, agent_version_id=version.id,
            deployment_id=deployment.id, trigger_type=trigger_type, triggered_by_identity_id=principal.id,
            correlation_id=correlation_id, request_id=trace.request_id if trace else None,
            idempotency_key=idempotency_key,
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
# Model-driven tool invocation loop (Phase 5.6a.3 SRS ACT-TLX-FR-040..049)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class _LoopToolCall:
    """One tool call the model requested this turn — the plain, JSON-safe
    shape ``ModelGatewayService.invoke()``'s ``usage["tool_calls"]`` already
    returns, never the frozen ``ModelToolCall`` dataclass itself (this
    module has no reason to import the provider types just for this)."""

    id: str
    name: str
    arguments: dict


@dataclass(frozen=True, slots=True)
class _ToolCallSnapshot:
    """A plain, immutable snapshot of one ``ToolCall`` row's outcome —
    crosses out of a per-thread ``Session`` about to close (see
    ``ToolLoopOrchestrator._execute_parallel``) the same "plain value, not
    a live ORM object" discipline ``ResolvedCredential`` already
    established for crossing the model-call thread boundary."""

    status: str
    error_code: str | None
    error_class: str | None
    output_summary: dict | None
    validation_error: str | None


class ToolLoopOrchestrator:
    """Milestone 1's completion piece — the orchestration layer connecting
    ``ModelGatewayService`` and ``ToolGatewayService``: the model requests
    a tool, the platform executes it (through the exact same
    authorization/validation/resilience path 5.6a.1/5.6a.2 already built —
    ``ToolGatewayService.invoke()`` is called completely unchanged, whether
    sequentially or, for a parallel-safe batch, through a fresh ``Session``
    per call), the result is appended to the conversation, and the model is
    called again — until a final answer or one of four independent
    termination conditions (``ACT-TLX-FR-041..043, FR-048``) ends it.

    **A single-turn execution behaves exactly as before this phase
    (AC-02).** When this version has no tools bound, or its configured
    provider doesn't declare ``supports_tools`` (``MOCK``, always — see
    ``ModelGatewayService.invoke()``), no tools are ever offered to the
    model; it returns ``finish_reason=STOP`` on the first call, exactly as
    it always has, and this loop ends immediately with
    ``termination_reason="COMPLETED"``, ``loop_iterations=1``. Every
    5.6a.1/5.6a.2 test uses ``MOCK`` with the pre-existing, *separate*
    explicit ``input_payload["tool_calls"]`` mechanism (still handled by
    ``ExecutionWorkerService._execute`` immediately after this returns,
    completely untouched) — this orchestrator never sees or touches that
    field; its own ``tool_usage["calls"]`` counts only tool calls the
    *model itself* requested, staying ``0`` for every one of those tests.

    §10.4 is preserved by construction: the only thing this loop can ever
    call is ``ToolGatewayService.invoke()``, bound to this version's frozen
    ``tools_snapshot`` — never another agent, never an arbitrary execution
    request. There is no code path here that reaches
    ``ExecutionRequestService`` at all."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def run(self, execution: AgentExecution, agent: Agent, version: AgentVersion,
           resolved_credential: ResolvedCredential | None, *, timeout_seconds: float,
           ) -> tuple[dict, dict, dict]:
        from app.observability.trace import trace_id_for
        from app.runtime.providers.types import ModelMessage, ModelToolDefinition

        input_payload = execution.input_payload if isinstance(execution.input_payload, dict) else {}
        tool_entries = self._frozen_tool_entries(execution)
        tool_defs = tuple(
            ModelToolDefinition(name=name, description=entry.get("description") or "",
                                parameters=(entry.get("input_schema") or {}))
            for name, (_, entry) in tool_entries.items()
        )

        # ---------------------------------------------------------------- #
        # Phase 4.3 -- THE enforcement path. Bound once per attempt, so the
        # policy set is snapshotted for the whole loop (see
        # RuntimeGovernanceEngine's docstring on why an execution is governed
        # by the policies in force when it began rather than re-resolved at
        # every checkpoint).
        # ---------------------------------------------------------------- #
        deployment = self.db.get(AgentDeployment, execution.deployment_id) if execution.deployment_id else None
        governance = RuntimeGovernanceEngine(self.db).bind(
            execution,
            environment_id=deployment.environment_id if deployment else None,
            agent_id=execution.agent_id,
        )
        classifications = self._tool_classifications(tool_entries)
        trace_id = trace_id_for(execution)

        conversation: list = [ModelMessage(role="user", content=json.dumps(input_payload, default=str))]
        self._append_message(execution, sequence=0, role="user",
                            content=json.dumps(input_payload, default=str), loop_iteration=0)

        seen_calls: set[str] = set()
        max_iterations = self._max_iterations(execution)
        loop_start = time.monotonic()
        prompt_sum = completion_sum = total_sum = 0
        cost_sum = 0.0
        model_call_count = 0
        tool_call_count = 0
        calls_per_tool: dict[str, int] = {}
        accounting_complete = True
        last_usage: dict | None = None
        sequence = 1
        iteration = 0

        def check(checkpoint: Checkpoint, **overrides) -> None:
            """The checkpoint insertion point -- one line at each of the six
            sites, and the only thing any of them does.

            Note what is *not* here: no comparison, no limit, no cap. Every one
            of those now lives in the engine, which is what makes "one
            enforcement path" a structural property of this file rather than a
            claim about it (``test_ac02_*`` asserts it over the AST).

            ``completed_iterations`` differs by checkpoint because it always
            did: the top-of-loop caps reported the iteration that had *finished*
            (``iteration - 1``), while the mid-loop tool checks reported the one
            in progress. Preserving that distinction is what keeps
            ``agent_executions.loop_iterations`` byte-identical to its pre-4.3
            value for every one of the four caps."""
            at_iteration_boundary = checkpoint in (
                Checkpoint.BEFORE_FIRST_MODEL_CALL, Checkpoint.BEFORE_NEXT_ITERATION)
            fields = dict(
                execution_id=execution.id, organization_id=execution.organization_id,
                agent_id=execution.agent_id, iteration=iteration,
                completed_iterations=max(iteration - 1, 0) if at_iteration_boundary else iteration,
                elapsed_seconds=time.monotonic() - loop_start,
                total_tokens=total_sum, cost_amount=cost_sum,
                model_calls=model_call_count, tool_calls=tool_call_count,
                calls_per_tool=dict(calls_per_tool),
                max_iterations=max_iterations,
                max_wall_clock_seconds=settings.TOOL_LOOP_MAX_WALL_CLOCK_SECONDS,
                max_total_tokens=settings.TOOL_LOOP_MAX_TOTAL_TOKENS,
                configured_model=(version.model_configuration or {}).get("model"),
                environment=deployment.environment if deployment else None,
                environment_id=deployment.environment_id if deployment else None,
                deployment_id=execution.deployment_id,
                criticality=agent.criticality, risk_score=execution.risk_score,
                trace_id=trace_id, seen_call_keys=frozenset(seen_calls),
            )
            fields.update(overrides)
            governance.enforce(checkpoint, CheckpointContext(**fields))

        pool = ThreadPoolExecutor(max_workers=1)
        try:
            while True:
                iteration += 1
                # --- CHECKPOINT 1 / 5 -------------------------------------- #
                # One site, two identities. At iteration 1 nothing has been
                # dispatched; from iteration 2 on, this is the same boundary the
                # end of the previous iteration reached, with no code in
                # between -- so it is one checkpoint rather than two, and the
                # wall-clock and token-budget checks that used to sit at the
                # bottom of this body are evaluated here instead, in the order
                # that reproduces exactly which cap the pre-4.3 loop reported
                # when two breached on the same turn (see
                # app.runtime.governance.constraints.BUILTIN_CAPS).
                check(Checkpoint.BEFORE_FIRST_MODEL_CALL if iteration == 1
                      else Checkpoint.BEFORE_NEXT_ITERATION)

                turn_start = time.monotonic()
                future = pool.submit(ModelGatewayService().invoke, version, input_payload,
                                    resolved_credential=resolved_credential,
                                    conversation=tuple(conversation), tools=tool_defs)
                try:
                    output_payload, usage = future.result(timeout=timeout_seconds)
                except FutureTimeoutError:
                    raise ModelGatewayError(
                        ErrorCode.EXECUTION_TIMED_OUT, f"Execution exceeded its {timeout_seconds}s time budget.",
                    ) from None
                turn_duration_ms = int((time.monotonic() - turn_start) * 1000)
                last_usage = usage
                model_call_count += 1

                turn_complete = usage.get("token_accounting_complete", True)
                accounting_complete = accounting_complete and turn_complete
                turn_cost = None
                if turn_complete:
                    prompt_sum += usage["input_tokens"]
                    completion_sum += usage["output_tokens"]
                    total_sum += usage["total_tokens"]
                    turn_cost = PricingService(self.db).calculate_cost(
                        provider=usage["provider"], model=usage["model"],
                        prompt_tokens=usage["input_tokens"], completion_tokens=usage["output_tokens"], at=_now(),
                    ).amount
                    # Phase 4.3 (M4-4.3-FR-011) -- the running total the cost
                    # checkpoints read. Nothing new is computed for governance:
                    # this is the same per-turn figure PricingService just
                    # produced for the transcript row below, summed. Budgets
                    # and reservations are Phase 4.4's.
                    cost_sum += float(turn_cost or 0)

                tool_calls_requested = usage.get("tool_calls") or []
                self._append_message(
                    execution, sequence=sequence, role="assistant", loop_iteration=iteration,
                    content=output_payload.get("result", ""),
                    tool_calls_requested=tool_calls_requested or None,
                    prompt_tokens=usage.get("input_tokens") if turn_complete else None,
                    completion_tokens=usage.get("output_tokens") if turn_complete else None,
                    total_tokens=usage.get("total_tokens") if turn_complete else None,
                    cost_amount=turn_cost, duration_ms=turn_duration_ms,
                )
                sequence += 1
                conversation.append(ModelMessage(role="assistant", content=output_payload.get("result", "")))

                # --- CHECKPOINT 2 ------------------------------------------ #
                # `responded_model` is whatever the gateway reports as the
                # model that answered -- today the configured one, since
                # ModelGatewayService echoes it back, but the after-position is
                # the only place a provider-resolved model (an alias, a version
                # pin, a fallback) could ever be observed. See
                # _c_restricted_model on why the redundancy is deliberate.
                check(Checkpoint.AFTER_MODEL_RESPONSE,
                      responded_model=usage.get("model"), provider=usage.get("provider"))

                if usage.get("finish_reason") != "TOOL_CALLS" or not tool_calls_requested:
                    # --- CHECKPOINT 6 -------------------------------------- #
                    check(Checkpoint.BEFORE_FINAL_OUTPUT,
                          responded_model=usage.get("model"), provider=usage.get("provider"))
                    self._terminate(execution, "COMPLETED", iteration)
                    tool_usage = {"calls": self._loop_tool_call_count(execution)}
                    model_usage = self._aggregate_usage(last_usage, prompt_sum, completion_sum, total_sum,
                                                        accounting_complete)
                    return output_payload, model_usage, tool_usage

                # --- Tool requests this turn ------------------------------ #
                calls = [_LoopToolCall(id=c["id"], name=c["name"], arguments=c["arguments"])
                        for c in tool_calls_requested]
                for call in calls:
                    # --- CHECKPOINT 3 -------------------------------------- #
                    # Per call, before dispatch -- the last point at which a
                    # specific call can be refused without side effects.
                    #
                    # The frozen-snapshot scope check (ACT-TLX-FR-045: the
                    # model cannot invent a tool, or reach one bound to the
                    # agent but not to *this* published version) and the
                    # repeated-identical-call cap (ACT-TLX-FR-048) are now
                    # constraints inside the engine, evaluated in this same
                    # order and producing the same TOOL_DENIED / REPEATED_CALL
                    # terminations they always did.
                    entry = tool_entries.get(call.name)
                    key = self._canonical_key(call.name, call.arguments)
                    check(Checkpoint.BEFORE_TOOL_EXECUTION,
                          tool_name=call.name, tool_bound=entry is not None,
                          tool_class=(entry[1].get("tool_type") if entry else None),
                          tool_data_classification=(classifications.get(entry[0]) if entry else None),
                          tool_call_key=key)
                    seen_calls.add(key)

                snapshots = self._execute_calls(execution, agent, tool_entries, calls, iteration)
                for call, snapshot in zip(calls, snapshots):
                    result_payload = self._tool_result_payload(snapshot)
                    content = json.dumps(result_payload, default=str)
                    self._append_message(execution, sequence=sequence, role="tool", loop_iteration=iteration,
                                        content=content, tool_call_id=call.id, tool_name=call.name)
                    sequence += 1
                    conversation.append(ModelMessage(role="tool", content=content, tool_call_id=call.id))
                    tool_call_count += 1
                    calls_per_tool[call.name] = calls_per_tool.get(call.name, 0) + 1

                # --- CHECKPOINT 4 ------------------------------------------ #
                check(Checkpoint.AFTER_TOOL_EXECUTION)
                # The wall-clock and token-budget checks that used to sit here
                # are evaluated at the top of the next iteration instead --
                # the adjacent half of the same boundary. See CHECKPOINT 1/5.
        except (GovernanceStopped, GovernanceChallenged) as exc:
            # The loop's terminal bookkeeping, unchanged: the same
            # `loop_iterations` and `termination_reason` the inline caps wrote,
            # now taken from the decision that produced them. Re-raised so the
            # worker applies its existing retry / approval handling.
            self._terminate(execution, exc.decision.termination_reason or "GOVERNANCE_STOP",
                            exc.completed_iterations)
            raise
        finally:
            pool.shutdown(wait=False)

    # ------------------------------------------------------------------ #
    # Snapshot / binding helpers
    # ------------------------------------------------------------------ #
    def _frozen_tool_entries(self, execution: AgentExecution) -> dict[str, tuple[str, dict]]:
        """``ACT-TLX-FR-045`` — every tool the model may request this
        execution, keyed by name, read from the *frozen* version snapshot
        exactly the way ``ToolGatewayService._frozen_tool_entry`` already
        does for a single tool — never from live, mutable ``Tool``/
        ``AgentTool`` state. A tool assigned to the agent but not included
        in this version's ``tools_snapshot`` at publish time has no entry
        here and is rejected as ``TOOL_NOT_BOUND_TO_VERSION`` if the model
        names it."""
        snapshot_row = self.db.execute(
            select(AgentVersionSnapshot).where(AgentVersionSnapshot.agent_version_id == execution.agent_version_id)
        ).scalars().first()
        if snapshot_row is None:
            return {}
        tool_configs = ((snapshot_row.snapshot or {}).get("runtime") or {}).get("tool_configs") or {}
        return {entry["name"]: (tool_id, entry) for tool_id, entry in tool_configs.items()}

    def _tool_classifications(self, tool_entries: dict) -> dict[str, str]:
        """Phase 4.3 (M4-4.3-FR-013) -- ``Tool.data_classification`` for every
        tool this version froze, read **once per execution** rather than at
        each checkpoint.

        It is not in the frozen ``tools_snapshot`` (Phase 5.2.4 froze the
        tool's callable shape, not its classification), so it has to come from
        the live row -- the same column, and the same read,
        ``app.runtime.environment.policy`` already performs at deploy time. One
        query at loop start keeps a governance constraint off the per-call
        query path (§25)."""
        tool_ids = [tool_id for tool_id, _ in tool_entries.values()]
        if not tool_ids:
            return {}
        rows = self.db.execute(
            select(Tool.id, Tool.data_classification).where(Tool.id.in_(tool_ids))
        ).all()
        return {str(tool_id): classification for tool_id, classification in rows}

    def _max_iterations(self, execution: AgentExecution) -> int:
        deployment = self.db.get(AgentDeployment, execution.deployment_id) if execution.deployment_id else None
        return ((deployment.runtime_limits or {}).get("maximum_loop_iterations")
                if deployment else None) or settings.TOOL_LOOP_MAX_ITERATIONS

    @staticmethod
    def _canonical_key(name: str, arguments: dict) -> str:
        """``ACT-TLX-FR-048`` — reuses Phase 5.2.4's canonical serialization
        (the same discipline that makes a version's checksum reproducible)
        so two calls with the same arguments in a different key order, or
        a float argument, still compare equal."""
        from app.runtime.versioning import canonical

        return canonical.digest(canonical.stringify_floats({"tool": name, "arguments": arguments}))

    # ------------------------------------------------------------------ #
    # Transcript / accounting
    # ------------------------------------------------------------------ #
    def _append_message(self, execution: AgentExecution, *, sequence: int, role: str, loop_iteration: int,
                        content: str | None = None, tool_call_id: str | None = None, tool_name: str | None = None,
                        tool_calls_requested: list | None = None, prompt_tokens: int | None = None,
                        completion_tokens: int | None = None, total_tokens: int | None = None,
                        cost_amount: float | None = None, duration_ms: int | None = None) -> None:
        self.db.add(ExecutionMessage(
            execution_id=execution.id, sequence=sequence, role=role, content=content,
            tool_call_id=tool_call_id, tool_name=tool_name, tool_calls_requested=tool_calls_requested,
            loop_iteration=loop_iteration, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            total_tokens=total_tokens, cost_amount=cost_amount, duration_ms=duration_ms,
        ))
        self.db.flush()
        if role == "assistant":
            _record_event(self.db, AuthorizationAuditEvent.RUNTIME_LOOP_ITERATION, None,
                         organization_id=execution.organization_id, agent_id=execution.agent_id,
                         execution_id=execution.id, meta={"loop_iteration": loop_iteration})

    def _terminate(self, execution: AgentExecution, reason: str, iterations: int) -> None:
        execution.loop_iterations = iterations
        execution.termination_reason = reason
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_LOOP_TERMINATED, None,
                     organization_id=execution.organization_id, agent_id=execution.agent_id,
                     execution_id=execution.id, severity="INFO" if reason == "COMPLETED" else "CRITICAL",
                     meta={"reason": reason, "iterations": iterations})

    def _loop_tool_call_count(self, execution: AgentExecution) -> int:
        return self.db.execute(
            select(func.count(ToolCall.id)).where(
                ToolCall.execution_id == execution.id, ToolCall.loop_iteration.is_not(None))
        ).scalar_one()

    @staticmethod
    def _aggregate_usage(last_usage: dict, prompt_sum: int, completion_sum: int, total_sum: int,
                         complete: bool) -> dict:
        """The final ``model_usage`` this loop returns, matching the exact
        shape ``ModelGatewayService.invoke()`` always has -- ``_execute()``
        downstream reads it exactly as it does for a single-turn call
        (``AC-06``). Token fields are the *sum* across every iteration;
        everything else (``provider``/``model``/``finish_reason``/
        ``was_streamed``/etc.) reflects the *last* iteration, the one that
        actually produced the final answer."""
        usage = dict(last_usage)
        if complete:
            usage["input_tokens"] = prompt_sum
            usage["output_tokens"] = completion_sum
            usage["total_tokens"] = total_sum
        usage["token_accounting_complete"] = complete
        return usage

    # ------------------------------------------------------------------ #
    # Tool execution — sequential or parallel, always through
    # ToolGatewayService.invoke() unchanged
    # ------------------------------------------------------------------ #
    def _execute_calls(self, execution: AgentExecution, agent: Agent, tool_entries: dict,
                      calls: list[_LoopToolCall], iteration: int) -> list[_ToolCallSnapshot]:
        """``ACT-TLX-FR-044`` — a batch of more than one call runs
        concurrently only when *every* tool in it is declared idempotent
        (``ACT-TLX-FR-026``'s flag, reused here for a second purpose: safe
        to run more than once is the same property as safe to run
        alongside its siblings without a coordination guarantee). A single
        non-idempotent tool anywhere in the batch drops the *entire* batch
        to sequential, model-given order — conservative by design (``AC-18``),
        never assumed parallel-safe by default."""
        if len(calls) > 1 and all(self._is_idempotent(tool_entries[c.name][1]) for c in calls):
            return self._execute_parallel(execution, agent, calls, iteration)
        return self._execute_sequential(execution, agent, calls, iteration)

    @staticmethod
    def _is_idempotent(entry: dict) -> bool:
        if entry.get("tool_type") == "HTTP":
            return bool((entry.get("http_config") or {}).get("idempotent", False))
        return True  # FUNCTION/echo -- no real side effect to duplicate

    def _execute_sequential(self, execution: AgentExecution, agent: Agent, calls: list[_LoopToolCall],
                           iteration: int) -> list[_ToolCallSnapshot]:
        results = []
        for call in calls:
            row = ToolGatewayService().invoke(self.db, execution, agent, call.name, "EXECUTE", call.arguments)
            row.loop_iteration = iteration
            self.db.flush()
            results.append(self._snapshot(row))
        return results

    def _execute_parallel(self, execution: AgentExecution, agent: Agent, calls: list[_LoopToolCall],
                         iteration: int) -> list[_ToolCallSnapshot]:
        """Real concurrency, finally contending ``concurrency.py``'s
        per-execution ceiling (``ACT-TLX-FR-029``, wired but never
        exercised before this phase). Each call runs on its own thread with
        its *own*, fresh ``Session`` — a live SQLAlchemy ``Session`` is not
        safe to share across threads (the same pre-existing constraint
        that already keeps model invocation off ``self.db``); only a plain
        ``_ToolCallSnapshot`` crosses back out, never the ORM row itself.
        Results are collected by original submission index, not completion
        order, so they always reassemble in the model's expected order
        (``ACT-TLX-FR-044``) regardless of which call actually finishes
        first.

        **Why ``self.db`` is committed before spawning any thread.** This
        commit was, until Phase 3.9, the fix for a specific deadlock, and
        the reasoning is preserved here because it is the reasoning that
        eventually reshaped the whole execution path.

        ``claim_next`` used to claim this execution's row with
        ``SELECT ... FOR UPDATE SKIP LOCKED`` and hold that lock for the
        entire attempt. But once a fresh per-thread ``Session`` tries to
        ``INSERT INTO tool_calls`` (which references this same, still
        locked ``agent_executions`` row via a foreign key), Postgres's FK
        check needs a ``FOR KEY SHARE`` lock on that row -- which
        conflicts with the still-held ``FOR UPDATE`` and blocks. Meanwhile
        the *main* thread is blocked inside ``future.result()`` waiting for
        that same worker to finish: a genuine deadlock between an
        application-level thread-join and a database-level lock wait that
        Postgres's own deadlock detector cannot see (from its side, the
        main connection looks merely idle, not waiting on anything).

        Phase 3.9 moved that commit up to the claim itself
        (M3-3.9-FR-011), because a worker fleet reproduces this exact
        shape at scale and a per-call workaround does not survive it. So
        by the time this method runs there is no claim lock left to
        release, and this commit is now a flush boundary rather than a
        deadlock fix -- kept because the per-thread sessions must still see
        this execution's committed state, and removing it would make that
        depend on whatever the caller happened to have committed. The
        safety argument is unchanged either way: ``claim_next`` already
        transitioned this row out of ``QUEUED``, so nothing is protected by
        holding anything here. ``SessionLocal`` is configured
        ``expire_on_commit=False`` (``app/core/database.py``), so
        ``execution``/``agent`` stay fully usable on the main thread
        afterward with no re-fetch needed."""
        from app.core.database import SessionLocal

        self.db.commit()

        def worker(call: _LoopToolCall) -> _ToolCallSnapshot:
            thread_db = SessionLocal()
            try:
                thread_execution = thread_db.get(AgentExecution, execution.id)
                thread_agent = thread_db.get(Agent, agent.id)
                row = ToolGatewayService().invoke(
                    thread_db, thread_execution, thread_agent, call.name, "EXECUTE", call.arguments)
                row.loop_iteration = iteration
                thread_db.commit()
                return self._snapshot(row)
            except IdentityError:
                thread_db.commit()  # persist whatever ToolGatewayService already wrote before raising
                raise
            finally:
                thread_db.close()

        results: list[_ToolCallSnapshot | None] = [None] * len(calls)
        first_error: IdentityError | None = None
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:
            future_index = {pool.submit(worker, call): index for index, call in enumerate(calls)}
            for future, index in future_index.items():
                try:
                    results[index] = future.result()
                except IdentityError as exc:
                    if first_error is None:
                        first_error = exc
        if first_error is not None:
            raise first_error
        return results

    @staticmethod
    def _snapshot(row: ToolCall) -> _ToolCallSnapshot:
        return _ToolCallSnapshot(status=row.status, error_code=row.error_code, error_class=row.error_class,
                                 output_summary=row.output_summary, validation_error=row.validation_error)

    @staticmethod
    def _tool_result_payload(snapshot: _ToolCallSnapshot) -> dict:
        """``ACT-TLX-FR-021``/5.6a.2's structured-error shape, fed back to
        the model as the content of a ``role="tool"`` message — a
        successful call's ``output_summary`` (the actual tool result) or,
        for ``FAILED``/``DENIED``, the same ``error_code``/``error_class``/
        ``validation_error`` an admin already sees on the ``ToolCall`` row,
        so the model can act on precisely what went wrong."""
        if snapshot.status == "ALLOWED":
            return {"status": snapshot.status, "result": snapshot.output_summary}
        payload = {"status": snapshot.status, "error_code": snapshot.error_code, "error_class": snapshot.error_class}
        if snapshot.validation_error:
            try:
                payload["validation_error"] = json.loads(snapshot.validation_error)
            except ValueError:
                payload["validation_error"] = snapshot.validation_error
        return payload


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
        """§31/§32 -- take ownership of exactly one queued execution.

        **The claim commits before this returns** (Phase 3.9,
        M3-3.9-FR-011). That single line is the most consequential thing in
        this phase, so it is worth stating why it is not merely a tidy-up.

        Until Phase 3.9 this method ``flush``\\ ed. The ``FOR UPDATE`` lock
        taken by the query above was therefore held for the entire attempt --
        every model call, every tool call, every byte of network I/O -- and
        released only when ``run_once``'s ``finally`` finally committed. That
        was survivable while a single inline caller drove the worker. It is
        not survivable with a fleet, and the failure it produces is one this
        codebase has already been bitten by once:
        ``ToolLoopOrchestrator._execute_parallel`` had to commit ``self.db``
        by hand before spawning tool threads, because a fresh session
        inserting a ``tool_calls`` row needs ``FOR KEY SHARE`` on this very
        ``agent_executions`` row, which the still-held ``FOR UPDATE``
        blocks -- while the main thread sits in ``future.result()`` waiting
        for that same worker. A thread-join waiting on a database lock wait is
        a genuine deadlock that Postgres's detector cannot see, because from
        its side the main connection looks idle rather than blocked.

        Committing here dissolves that whole class of bug at the source
        instead of working around it one call site at a time: after this
        returns, the worker holds **no** database lock, and the long,
        network-bound part of the attempt runs against an unlocked row.

        Committing is safe precisely because the lock has already done its one
        job by this point. It existed to stop a second worker claiming the
        same row, and the row is no longer ``QUEUED`` -- the committed status
        change is what excludes it now, permanently rather than for the
        duration of a transaction. The ``execution_locks`` row (``execution_id``
        UNIQUE) is the durable owner record that replaces the transient lock,
        and ``SessionLocal`` is configured ``expire_on_commit=False``
        (``app/core/database.py``), so ``execution`` stays usable afterwards
        with no re-fetch.

        The one real behavioural difference, stated plainly: a worker that
        dies mid-attempt used to have its claim rolled back by the database,
        putting the execution straight back to ``QUEUED``. Now the claim is
        committed, so the execution stays ``RUNNING`` until its lease expires
        and ``reap_expired_locks`` applies the retry policy. Recovery is
        therefore slower by at most one lease, and in exchange it is
        *observable* -- there is a durable record of who held what and for how
        long, which is the difference between a fleet you can operate and one
        you can only guess about."""
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
        # ------------------------------------------------------------------ #
        # Phase 3.9 -- THE commit-before-dispatch boundary on the execution
        # path. Nothing below this line in an attempt holds a database lock
        # taken above it. See this method's docstring.
        # ------------------------------------------------------------------ #
        self.db.commit()
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
        # Phase 5.7a.5 (ACT-MDL-FR-082) — resolved synchronously, on this
        # (the worker's own) thread, using self.db, *before* anything is
        # handed to the thread pool below: only the resulting plain,
        # immutable ResolvedCredential value crosses into the pooled
        # thread, never the session itself.
        resolved_credential = ProviderCredentialService(self.db).resolve_for_version(
            execution.organization_id, version)
        try:
            # §36 — a hung model call must not hang the worker forever; the
            # per-call timeout below still bounds *each* model invocation
            # exactly as it always has. Phase 5.6a.3's own, new, additional
            # cap (settings.TOOL_LOOP_MAX_WALL_CLOCK_SECONDS) bounds the
            # *whole* loop across every iteration — see
            # ToolLoopOrchestrator.run().
            output_payload, model_usage, tool_usage = ToolLoopOrchestrator(self.db).run(
                execution, agent, version, resolved_credential, timeout_seconds=timeout_seconds,
            )

            # --- Pre-existing explicit `input_payload["tool_calls"]`
            # mechanism (Phase 5.0, predates the model-driven loop) --
            # completely unchanged: still handled here, still counted
            # separately from whatever the model itself requested above.
            # Every 5.6a.1/5.6a.2 test drives execution through exactly
            # this field with the MOCK provider (which the loop above
            # never offers tools to — see ToolLoopOrchestrator's own
            # docstring), so this path, and those tests, are untouched.
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

            # --- Phase 5.7a.3: streaming/accounting/cost (ACT-MDL-FR-045..049,
            # FR-084..089) --------------------------------------------------
            token_accounting_complete = model_usage.get("token_accounting_complete", True)
            execution.token_accounting_complete = token_accounting_complete
            execution.was_streamed = model_usage.get("was_streamed", False)
            execution.stream_interrupted = model_usage.get("stream_interrupted", False)
            execution.time_to_first_token_ms = model_usage.get("time_to_first_token_ms")
            execution.generation_duration_ms = model_usage.get("generation_duration_ms")
            execution.finish_reason = model_usage.get("finish_reason")

            if token_accounting_complete:
                # ACT-MDL-FR-046 — never estimate: null-not-zero when the
                # provider didn't report usage, checked just above.
                execution.prompt_tokens = model_usage["input_tokens"]
                execution.completion_tokens = model_usage["output_tokens"]
                execution.total_tokens = model_usage["total_tokens"]
            else:
                execution.prompt_tokens = None
                execution.completion_tokens = None
                execution.total_tokens = None

            attempt.prompt_tokens = execution.prompt_tokens
            attempt.completion_tokens = execution.completion_tokens
            attempt.total_tokens = execution.total_tokens
            attempt.token_accounting_complete = token_accounting_complete

            if token_accounting_complete:
                cost_result = PricingService(self.db).calculate_cost(
                    provider=model_usage["provider"], model=model_usage["model"],
                    prompt_tokens=execution.prompt_tokens, completion_tokens=execution.completion_tokens,
                    at=_now(),
                )
                execution.cost_amount = cost_result.amount
                execution.cost_currency = cost_result.currency
                execution.pricing_version = cost_result.pricing_version
                execution.cost_is_estimated = False
                # Legacy, non-nullable column — kept in sync with the new,
                # nullable cost_amount rather than dropped, since existing
                # callers/tests still read execution.cost directly.
                execution.cost = float(execution.cost or 0) + cost_result.amount
            else:
                execution.cost_amount = None
                execution.cost_currency = "USD"
                execution.pricing_version = None
                execution.cost_is_estimated = False

            _set_execution_status(execution, "SUCCEEDED")
            execution.completed_at = _now()
            execution.duration_ms = int((execution.completed_at - execution.started_at).total_seconds() * 1000)
            attempt.status = "SUCCEEDED"
            attempt.completed_at = execution.completed_at
            attempt.duration_ms = execution.duration_ms
            _record_event(self.db, AuthorizationAuditEvent.RUNTIME_EXECUTION_SUCCEEDED, None,
                         organization_id=execution.organization_id, agent_id=execution.agent_id,
                         execution_id=execution.id)
        except GovernanceChallenged as exc:
            # Phase 4.3 (M4-4.3-FR-030/032) -- listed *before* the IdentityError
            # arm below (which it subclasses) because a challenge is not a
            # failure and must not reach the retry policy: automatically
            # retrying something the platform just said needs a human would be
            # the platform overruling the obligation it had raised.
            self._park_for_approval(execution, attempt, exc)
        except IdentityError as exc:
            # Phase 5.7a.4 (§5) — a classified provider failure
            # (``ProviderRequestFailedError.error_class``, e.g. "RATE_
            # LIMITED") is recorded in this existing ``error_code`` column
            # in place of the generic ``MODEL_PROVIDER_REQUEST_FAILED`` it
            # would otherwise carry, so the taxonomy is visible on the row
            # without a new column. Every other ``IdentityError`` is
            # unaffected -- ``error_class`` simply isn't there.
            error_class = getattr(exc, "error_class", None)
            code = error_class.value if error_class is not None else exc.code
            self._fail_or_retry(execution, attempt, code, exc.message)
        except Exception as exc:  # noqa: BLE001 — a worker must never crash the poll loop
            self._fail_or_retry(execution, attempt, "INTERNAL_ERROR", str(exc))

    def _park_for_approval(self, execution: AgentExecution, attempt: ExecutionAttempt,
                           exc: GovernanceChallenged) -> None:
        """Phase 4.3 -- what a governance ``CHALLENGE`` does to the execution
        row. The approval obligation itself has already been raised by the
        engine, through the existing ``RuntimeApproval`` funnel.

        Two outcomes, and the difference is a capability statement rather than
        a preference. A challenge raised at the *first* checkpoint parks the
        execution in ``PENDING_APPROVAL``: nothing has been dispatched, so the
        funnel's existing "approve -> QUEUED -> run" path resumes it honestly.
        A challenge raised later cannot be resumed -- this platform has no way
        to re-enter a partially-run loop, and re-queuing would re-execute tool
        calls that already had their side effects -- so it terminates in
        ``BLOCKED``, the same terminal state an admission-time policy refusal
        uses, with the obligation still standing for a human to act on.

        Parking an execution in a state nothing could move it out of would be
        the worst of the three, which is why the non-resumable case ends
        rather than waits."""
        attempt.error_code = exc.code
        attempt.error_message = exc.message
        attempt.completed_at = _now()
        attempt.duration_ms = int((attempt.completed_at - (attempt.started_at or attempt.completed_at))
                                  .total_seconds() * 1000)
        execution.error_code = exc.code
        execution.error_message = exc.message
        execution.decision = "REQUIRE_APPROVAL"
        if exc.resumable:
            attempt.status = "CANCELLED"
            _set_execution_status(execution, "PENDING_APPROVAL")
        else:
            attempt.status = "FAILED"
            _set_execution_status(execution, "BLOCKED")
            execution.completed_at = _now()
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_EXECUTION_APPROVAL_REQUIRED, None,
                     organization_id=execution.organization_id, agent_id=execution.agent_id,
                     execution_id=execution.id, severity="WARNING",
                     meta={"checkpoint": exc.decision.checkpoint.value,
                          "reason_code": exc.decision.reason_code.value,
                          "approval_id": str(exc.approval_id) if exc.approval_id else None,
                          "resumable": exc.resumable})

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
        # Phase 5.7a.4 (``ACT-MDL-FR-062``) — a *classified* provider
        # failure's non-retryable classes are added here by value (plain
        # strings, matching ``code``'s own shape) so this outer, execution-
        # level retry (a fresh worker claim) never contradicts the platform
        # rule "never retry these" just because the inner, same-call retry
        # in ``ModelGatewayService`` already gave up on a *different*
        # (transient) classification. RATE_LIMITED/PROVIDER_UNAVAILABLE/
        # TIMEOUT are deliberately *not* added here -- they stay retryable
        # at this outer layer too, same as before this classification
        # existed (see docs/runtime/providers.md's two-tier retry note).
        non_retryable = {ErrorCode.RUNTIME_POLICY_DENIED, ErrorCode.MODEL_NOT_APPROVED,
                         ErrorCode.TOOL_ACTION_NOT_ALLOWED, ErrorCode.TOOL_NOT_ASSIGNED,
                         ErrorCode.TOOL_NOT_FOUND, ErrorCode.TOOL_CONSTRAINT_VIOLATION,
                         # Phase 5.6a.1 -- an egress denial is a policy fact about the
                         # target (or the tool's declared allowlist), not a transient
                         # failure; retrying reaches the same denial every time.
                         ErrorCode.TOOL_EGRESS_DENIED,
                         ErrorCode.VALIDATION_ERROR, ErrorCode.MODEL_PROVIDER_UNAVAILABLE,
                         # Phase 5.7a.5 — a missing credential needs an admin to configure
                         # one via the API, not an automatic requeue; same treatment as
                         # TOOL_NOT_ASSIGNED just above (a setup problem, not a transient one).
                         ErrorCode.PROVIDER_CREDENTIAL_REQUIRED,
                         # Phase 5.6a.3 -- a model naming a tool outside this version's
                         # frozen tools_snapshot is a scope violation, not a transient
                         # failure (same treatment as TOOL_NOT_ASSIGNED); a loop-safety
                         # cap breach (iteration/token/wall-clock/repeated-call) reaches
                         # the identical outcome on any retry.
                         ErrorCode.TOOL_NOT_BOUND_TO_VERSION, ErrorCode.TOOL_LOOP_LIMIT_EXCEEDED,
                         # Phase 4.3 -- a governance STOP reaches the identical
                         # decision on any retry (the ceiling is still the
                         # ceiling, the model is still restricted), so retrying
                         # would only burn attempts. KILL_SWITCH_ACTIVE is here
                         # for a stronger reason: an automatic retry past a kill
                         # would be automation overruling an operator, which
                         # §19's kill-switch dominance forbids outright.
                         #
                         # GOVERNANCE_CHECKPOINT_UNEVALUABLE is deliberately
                         # *not* in this set. Fail-closed says an unevaluable
                         # mandatory checkpoint stops this attempt; it does not
                         # say the condition is permanent, and a transient
                         # dependency failure is exactly what the retry policy
                         # exists for.
                         ErrorCode.GOVERNANCE_EXECUTION_STOPPED, ErrorCode.KILL_SWITCH_ACTIVE,
                         ProviderErrorClass.CONTENT_FILTERED.value, ProviderErrorClass.CONTEXT_LENGTH_EXCEEDED.value,
                         ProviderErrorClass.AUTHENTICATION_FAILED.value, ProviderErrorClass.INVALID_REQUEST.value,
                         ProviderErrorClass.UNKNOWN.value}
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
            # Phase 3.1 -- additively drives the *new* lifecycle_state machine
            # too, alongside (never instead of) the legacy .status handling
            # just above. A no-op for a deployment never routed through the
            # new PENDING_APPROVAL state (see DeploymentLifecycleService
            # .apply_approval_decision's own docstring).
            if deployment:
                from app.runtime.deployment.service import DeploymentLifecycleService
                DeploymentLifecycleService(self.db).apply_approval_decision(actor, deployment, decision)
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

    def activate_system(self, *, organization_id: uuid.UUID, scope: str,
                        target_id: uuid.UUID | None, reason: str,
                        origin: str = "system") -> dict:
        """Phase 4.3 (M4-4.3-FR-031) -- the kill switch triggered by the
        platform itself rather than by a person, currently only by
        ``RuntimeGovernanceEngine`` when a governance STOP warrants suspension.

        **This is an entry point into the existing mechanism, not a second
        one.** It calls the very same ``_cancel_executions`` and
        ``_suspend_deployments`` ``activate`` calls, sets the same columns, and
        writes the same ``RUNTIME_KILL_SWITCH_ACTIVATED`` audit event -- the
        one thing it cannot reuse is ``activate`` itself, which requires a
        ``User`` for the tenant scoping and the SUPER_ADMIN check on PLATFORM
        scope. There is no operator here to check, so instead of inventing a
        synthetic one this method restricts itself to the two scopes an
        automated trigger may legitimately reach:

        - ``EXECUTION`` -- cancel the one execution that breached.
        - ``AGENT`` -- suspend the agent and cancel its active executions.

        ``PROJECT``, ``ORGANIZATION`` and ``PLATFORM`` are deliberately
        unreachable from automation. A rule misconfigured by one tenant must
        not be able to halt a project, an organization, or the platform; those
        scopes stay behind a human with the permission to use them.

        The tenant boundary is enforced on the target rather than inherited
        from an actor: an execution or agent in another organization is simply
        not found, so a governance policy cannot reach outside its own tenant
        even if it were handed a foreign id.

        **Never clears a kill.** This method only ever moves state towards
        stopped -- there is no branch here, or anywhere in
        ``app.runtime.governance``, that sets ``lifecycle_status`` back to
        ``ACTIVE`` or ``cancel_requested`` back to ``False`` (§19, 3.7:
        kill-switch dominance)."""
        if scope not in ("EXECUTION", "AGENT"):
            raise IdentityError(
                ErrorCode.VALIDATION_ERROR,
                f"Scope '{scope}' cannot be activated by automation; it requires an operator.")
        cancelled = 0
        if scope == "EXECUTION":
            execution = self.db.get(AgentExecution, target_id)
            if execution is None or execution.organization_id != organization_id:
                raise IdentityError(ErrorCode.EXECUTION_NOT_FOUND, "Execution not found.")
            if execution.status not in TERMINAL_EXECUTION_STATUSES:
                _set_execution_status(execution, "CANCELLED")
                execution.cancel_requested = True
                execution.completed_at = _now()
                cancelled = 1
        else:
            agent = self.db.get(Agent, target_id)
            if agent is None or agent.organization_id != organization_id:
                raise IdentityError(ErrorCode.AGENT_NOT_FOUND, "Agent not found.")
            agent.lifecycle_status = "SUSPENDED"
            cancelled = self._cancel_executions(select(AgentExecution).where(
                AgentExecution.agent_id == agent.id,
                AgentExecution.status.in_(ACTIVE_EXECUTION_STATUSES),
            ))

        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_KILL_SWITCH_ACTIVATED, None,
                     organization_id=organization_id,
                     agent_id=target_id if scope == "AGENT" else None,
                     execution_id=target_id if scope == "EXECUTION" else None,
                     severity="CRITICAL",
                     meta={"scope": scope, "target_id": str(target_id) if target_id else "ALL",
                          "reason": reason, "executions_cancelled": cancelled, "origin": origin})
        self.db.flush()
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
