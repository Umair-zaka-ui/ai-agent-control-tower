"""Phase 5.1 SRS §18-§21 — the full registry lifecycle state machine, and
§36-§38/§56 agent search.

Supersedes ``app.runtime.services.AgentRegistryService``'s collapsed 8-state
``_transition`` (DRAFT/VALIDATED/APPROVED/ACTIVE/SUSPENDED/DEPRECATED/
ARCHIVED/RETIRED, each transition borrowing a neighbor's audit event) with
the full 13-state matrix and one dedicated audit event per action. Agent
*creation* (the initial DRAFT row) stays ``AgentRegistryService.register()``
— the SRS itself keeps these as two different operations: ``POST /agents``
creates the draft, ``POST /agents/{id}/register`` is a lifecycle action that
moves it out of DRAFT.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.agent_registry import AgentLifecycleEvent
from app.models.user import User
from app.runtime.registry.ownership import AgentOwnershipService
from app.runtime.registry.validation import AgentValidationService, has_blocking_findings
from app.runtime.services import AGENT_LIFECYCLE, _now, _record_event

__all__ = ["AGENT_LIFECYCLE", "AgentLifecycleService", "AgentSearchService", "EDITABLE_STATES"]

# SRS §20 — the full transition matrix, replacing the Phase 5.0 8-state one.
_TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"REGISTERED", "ARCHIVED"}),
    "REGISTERED": frozenset({"VALIDATING", "DRAFT", "ARCHIVED"}),
    "VALIDATING": frozenset({"VALIDATED", "VALIDATION_FAILED"}),
    "VALIDATION_FAILED": frozenset({"DRAFT", "REGISTERED", "VALIDATING", "ARCHIVED"}),
    "VALIDATED": frozenset({"PENDING_APPROVAL", "REGISTERED", "ARCHIVED"}),
    "PENDING_APPROVAL": frozenset({"APPROVED", "REJECTED"}),
    "REJECTED": frozenset({"DRAFT", "REGISTERED", "ARCHIVED"}),
    "APPROVED": frozenset({"ACTIVE", "ARCHIVED"}),
    "ACTIVE": frozenset({"SUSPENDED", "DEPRECATED", "RETIRED"}),
    "SUSPENDED": frozenset({"ACTIVE", "DEPRECATED", "RETIRED"}),
    "DEPRECATED": frozenset({"ACTIVE", "ARCHIVED", "RETIRED"}),
    "ARCHIVED": frozenset({"DRAFT"}),
    "RETIRED": frozenset(),
}

# States in which the agent record and its definition remain editable (§7,
# §19.1, §19.4, §19.7).
EDITABLE_STATES = frozenset({"DRAFT", "REGISTERED", "VALIDATION_FAILED", "REJECTED"})

_TIMESTAMP_FIELD = {
    "VALIDATED": "validated_at", "APPROVED": "approved_at", "ACTIVE": "activated_at",
    "SUSPENDED": "suspended_at", "ARCHIVED": "archived_at", "RETIRED": "retired_at",
}


class AgentLifecycleService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.ownership = AgentOwnershipService(db)

    def _transition(self, agent: Agent, to_status: str, *, actor: User, event: AuthorizationAuditEvent,
                    reason: str | None = None, request_id: str | None = None,
                    correlation_id: str | None = None, approved_by: uuid.UUID | None = None,
                    authorization_decision_id: uuid.UUID | None = None) -> Agent:
        allowed = _TRANSITIONS.get(agent.lifecycle_status, frozenset())
        if to_status not in allowed:
            raise IdentityError(ErrorCode.AGENT_TRANSITION_NOT_ALLOWED,
                               f"Cannot move agent from {agent.lifecycle_status} to {to_status}.")
        previous = agent.lifecycle_status
        agent.lifecycle_status = to_status
        agent.updated_by = actor.id
        field = _TIMESTAMP_FIELD.get(to_status)
        if field:
            setattr(agent, field, _now())

        self.db.add(AgentLifecycleEvent(
            agent_id=agent.id, organization_id=agent.organization_id, previous_status=previous,
            new_status=to_status, reason=reason, requested_by=actor.id, approved_by=approved_by,
            authorization_decision_id=authorization_decision_id,
            request_id=request_id or str(uuid.uuid4()), correlation_id=correlation_id or str(uuid.uuid4()),
        ))
        _record_event(self.db, event, actor, organization_id=agent.organization_id, agent_id=agent.id,
                     meta={"from": previous, "to": to_status, "reason": reason})
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def register(self, actor: User, agent: Agent, **ctx) -> Agent:
        """DRAFT|VALIDATION_FAILED|REJECTED -> REGISTERED (§19.2) — minimum
        required information has been submitted. §32.4 — confirmed
        duplicates block registration outright; an unreviewed likely
        duplicate blocks until a reviewer decides (any decision clears it,
        including "justified separate agent"); a merely possible duplicate
        is a warning only, surfaced via the match list, and never blocks."""
        if not (agent.name and agent.description and agent.business_purpose and agent.owner_id):
            raise IdentityError(ErrorCode.AGENT_DEFINITION_REQUIRED,
                               "name, description, business_purpose and an owner are required "
                               "before registration.")
        from app.runtime.registry.duplicates import AgentDuplicateDetectionService

        duplicates = AgentDuplicateDetectionService(self.db)
        duplicates.check(actor, agent)
        blocking = duplicates.blocking_match(agent.id)
        if blocking is not None:
            code = (ErrorCode.AGENT_DUPLICATE_CONFIRMED if blocking.status == "CONFIRMED_DUPLICATE"
                   else ErrorCode.AGENT_DUPLICATE_REVIEW_REQUIRED)
            raise IdentityError(code,
                               "A confirmed or unreviewed likely duplicate exists for this agent; "
                               "resolve it from the Duplicates page before registering.")
        return self._transition(agent, "REGISTERED", actor=actor,
                                event=AuthorizationAuditEvent.RUNTIME_AGENT_REGISTERED, **ctx)

    def start_validation(self, actor: User, agent: Agent, **ctx) -> tuple[Agent, "AgentValidationRun"]:  # noqa: F821
        """REGISTERED|VALIDATION_FAILED -> VALIDATING -> VALIDATED|VALIDATION_FAILED
        (§19.3-§19.5), run synchronously within one call (this environment has
        no async validation queue — see docs/runtime/registry/validation.md)."""
        if agent.lifecycle_status not in ("REGISTERED", "VALIDATION_FAILED"):
            raise IdentityError(ErrorCode.AGENT_TRANSITION_NOT_ALLOWED,
                               f"Cannot validate an agent in {agent.lifecycle_status}.")
        self._transition(agent, "VALIDATING", actor=actor,
                         event=AuthorizationAuditEvent.RUNTIME_AGENT_VALIDATION_STARTED, **ctx)
        run = AgentValidationService(self.db).run(actor, agent)
        if has_blocking_findings(run) or run.status == "FAILED":
            self._transition(agent, "VALIDATION_FAILED", actor=actor,
                             event=AuthorizationAuditEvent.RUNTIME_AGENT_VALIDATION_FAILED, **ctx)
        else:
            self._transition(agent, "VALIDATED", actor=actor,
                             event=AuthorizationAuditEvent.RUNTIME_AGENT_VALIDATION_PASSED, **ctx)
        return agent, run

    def submit_for_approval(self, actor: User, agent: Agent, **ctx) -> Agent:
        """VALIDATED -> PENDING_APPROVAL (§19.6) — only a passing validation
        run may be submitted."""
        latest = self._latest_validation_run(agent.id)
        if latest is None or latest.status != "PASSED":
            raise IdentityError(ErrorCode.AGENT_VALIDATION_FAILED,
                               "The agent must have a passing validation run before it can be "
                               "submitted for approval.")
        return self._transition(agent, "PENDING_APPROVAL", actor=actor,
                                event=AuthorizationAuditEvent.RUNTIME_AGENT_APPROVAL_REQUESTED, **ctx)

    def approve(self, actor: User, agent: Agent, **ctx) -> Agent:
        """PENDING_APPROVAL -> APPROVED (§19.8)."""
        return self._transition(agent, "APPROVED", actor=actor, approved_by=actor.id,
                                event=AuthorizationAuditEvent.RUNTIME_AGENT_APPROVED, **ctx)

    def reject(self, actor: User, agent: Agent, *, reason: str, **ctx) -> Agent:
        """PENDING_APPROVAL -> REJECTED (§19.7) — a reason is mandatory."""
        if not reason or not reason.strip():
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "A reason is required to reject registration.")
        return self._transition(agent, "REJECTED", actor=actor, reason=reason,
                                event=AuthorizationAuditEvent.RUNTIME_AGENT_REJECTED, **ctx)

    def activate(self, actor: User, agent: Agent, **ctx) -> Agent:
        """APPROVED -> ACTIVE (§19.9) — every §84 Definition-of-Done gate
        (identity, ownership) is enforced here, the last checkpoint before an
        agent becomes eligible for versioning/deployment/execution. The
        transition-legality check runs first, so an agent that isn't even
        APPROVED yet fails with ``AGENT_TRANSITION_NOT_ALLOWED`` rather than
        a confusing identity/ownership error about a state it can't reach
        anyway."""
        if "ACTIVE" not in _TRANSITIONS.get(agent.lifecycle_status, frozenset()):
            raise IdentityError(ErrorCode.AGENT_TRANSITION_NOT_ALLOWED,
                               f"Cannot move agent from {agent.lifecycle_status} to ACTIVE.")
        if agent.identity_id is None:
            raise IdentityError(ErrorCode.AGENT_IDENTITY_REQUIRED,
                               "A machine identity is required before activation.")
        self.ownership.check_agent_not_ownerless(agent)
        if agent.criticality == "MISSION_CRITICAL" and agent.compliance_owner_id is None:
            raise IdentityError(ErrorCode.AGENT_OWNER_REQUIRED,
                               "A compliance owner is required to activate a mission-critical agent.")
        return self._transition(agent, "ACTIVE", actor=actor,
                                event=AuthorizationAuditEvent.RUNTIME_AGENT_ACTIVATED, **ctx)

    def suspend(self, actor: User, agent: Agent, **ctx) -> Agent:
        """ACTIVE -> SUSPENDED (§19.10)."""
        return self._transition(agent, "SUSPENDED", actor=actor,
                                event=AuthorizationAuditEvent.RUNTIME_AGENT_SUSPENDED, **ctx)

    def resume(self, actor: User, agent: Agent, **ctx) -> Agent:
        """SUSPENDED -> ACTIVE — distinct verb/event from ``activate`` even
        though both land on ACTIVE, matching SRS §67's separate
        AGENT_ACTIVATED/AGENT_RESUMED audit events."""
        return self._transition(agent, "ACTIVE", actor=actor,
                                event=AuthorizationAuditEvent.RUNTIME_AGENT_RESUMED, **ctx)

    def deprecate(self, actor: User, agent: Agent, **ctx) -> Agent:
        """ACTIVE|SUSPENDED -> DEPRECATED (§19.11)."""
        return self._transition(agent, "DEPRECATED", actor=actor,
                                event=AuthorizationAuditEvent.RUNTIME_AGENT_DEPRECATED, **ctx)

    def archive(self, actor: User, agent: Agent, **ctx) -> Agent:
        """-> ARCHIVED (§19.12) — allowed from most non-terminal states per
        the §20 matrix."""
        return self._transition(agent, "ARCHIVED", actor=actor,
                                event=AuthorizationAuditEvent.RUNTIME_AGENT_ARCHIVED, **ctx)

    def restore(self, actor: User, agent: Agent, **ctx) -> Agent:
        """ARCHIVED -> DRAFT (§20) — 'only when restoration is authorized':
        gated by the ``runtime.agent.restore`` permission at the route
        layer, same as every other lifecycle action."""
        return self._transition(agent, "DRAFT", actor=actor,
                                event=AuthorizationAuditEvent.RUNTIME_AGENT_RESTORED, **ctx)

    def retire(self, actor: User, agent: Agent, **ctx) -> Agent:
        """ACTIVE|SUSPENDED|DEPRECATED -> RETIRED (§19.13) — permanent;
        history is retained (§74), the row itself is never deleted."""
        return self._transition(agent, "RETIRED", actor=actor,
                                event=AuthorizationAuditEvent.RUNTIME_AGENT_RETIRED, **ctx)

    def _latest_validation_run(self, agent_id: uuid.UUID):
        from app.models.agent_registry import AgentValidationRun
        return self.db.execute(
            select(AgentValidationRun).where(AgentValidationRun.agent_id == agent_id)
            .order_by(AgentValidationRun.created_at.desc()).limit(1)
        ).scalar_one_or_none()


class AgentSearchService:
    """SRS §36-§38, §56 — inventory search/filtering. The query builder
    lives here rather than in a separate ``search/`` module (it's a handful
    of ``.where()`` clauses, not an engine)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def search(self, actor: User, *, query: str | None = None, project_id: uuid.UUID | None = None,
              owner_id: uuid.UUID | None = None, status: str | None = None, agent_type: str | None = None,
              framework: str | None = None, criticality: str | None = None, risk_level: str | None = None,
              data_classification: str | None = None, autonomy_level: str | None = None,
              tags: list[str] | None = None, created_from: datetime | None = None,
              created_to: datetime | None = None, updated_from: datetime | None = None,
              updated_to: datetime | None = None, page: int = 1, page_size: int = 50,
              sort: str = "-created_at") -> tuple[list[Agent], int]:
        stmt = select(Agent).where(Agent.organization_id == actor.organization_id)
        if query:
            like = f"%{query}%"
            stmt = stmt.where(or_(Agent.name.ilike(like), Agent.description.ilike(like),
                                  Agent.business_purpose.ilike(like), Agent.slug.ilike(like)))
        if project_id:
            stmt = stmt.where(Agent.project_id == project_id)
        if owner_id:
            stmt = stmt.where(Agent.owner_id == owner_id)
        if status:
            stmt = stmt.where(Agent.lifecycle_status == status)
        if agent_type:
            stmt = stmt.where(Agent.agent_type == agent_type)
        if framework:
            from sqlalchemy import exists

            from app.models.runtime import AgentDefinition
            stmt = stmt.where(exists().where(
                AgentDefinition.agent_id == Agent.id, AgentDefinition.framework == framework))
        if criticality:
            stmt = stmt.where(Agent.criticality == criticality)
        if risk_level:
            stmt = stmt.where(Agent.risk_level == risk_level)
        if data_classification:
            stmt = stmt.where(Agent.data_classification == data_classification)
        if autonomy_level:
            stmt = stmt.where(Agent.autonomy_level == autonomy_level)
        if tags:
            stmt = stmt.where(Agent.tags.contains(tags))
        if created_from:
            stmt = stmt.where(Agent.created_at >= created_from)
        if created_to:
            stmt = stmt.where(Agent.created_at <= created_to)
        if updated_from:
            stmt = stmt.where(Agent.updated_at >= updated_from)
        if updated_to:
            stmt = stmt.where(Agent.updated_at <= updated_to)

        total = self.db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

        descending = sort.startswith("-")
        sort_field = sort.lstrip("-")
        column = getattr(Agent, sort_field, Agent.created_at)
        stmt = stmt.order_by(column.desc() if descending else column.asc())
        stmt = stmt.offset((max(page, 1) - 1) * page_size).limit(page_size)
        rows = list(self.db.execute(stmt).scalars())
        return rows, total

    # SRS §37 — named inventory views, expressed as filter presets.
    VIEWS: dict[str, dict] = {
        "PENDING_VALIDATION": {"status": "REGISTERED"},
        "PENDING_APPROVAL": {"status": "PENDING_APPROVAL"},
        "ACTIVE": {"status": "ACTIVE"},
        "SUSPENDED": {"status": "SUSPENDED"},
        "ARCHIVED": {"status": "ARCHIVED"},
        "RETIRED": {"status": "RETIRED"},
        "HIGH_RISK": {"risk_level": "HIGH"},
        "MISSION_CRITICAL": {"criticality": "MISSION_CRITICAL"},
    }

    def view(self, actor: User, name: str, *, page: int = 1, page_size: int = 50) -> tuple[list[Agent], int]:
        if name == "MY_AGENTS":
            return self.search(actor, owner_id=actor.id, page=page, page_size=page_size)
        if name == "ORPHANED":
            stmt = select(Agent).where(Agent.organization_id == actor.organization_id,
                                       Agent.owner_id.is_(None))
            total = self.db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
            rows = list(self.db.execute(
                stmt.order_by(Agent.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
            ).scalars())
            return rows, total
        if name == "RECENTLY_UPDATED":
            stmt = select(Agent).where(Agent.organization_id == actor.organization_id)
            total = self.db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
            rows = list(self.db.execute(
                stmt.order_by(Agent.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
            ).scalars())
            return rows, total
        preset = self.VIEWS.get(name)
        if preset is None:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, f"Unknown inventory view '{name}'.")
        return self.search(actor, page=page, page_size=page_size, **preset)
