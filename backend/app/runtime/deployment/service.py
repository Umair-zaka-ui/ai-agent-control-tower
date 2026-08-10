"""ACT-SRS-M3 §3.1 (M3-3.1-FR-001..031) -- ``DeploymentLifecycleService``, the
single authority on ``AgentDeployment.lifecycle_state``. No other module in
this codebase may assign that column (mechanically checked -- AC-02, see
``tests/runtime/test_deployment_lifecycle.py``).

Deliberately does not touch ``AgentDeployment.status`` (the pre-existing,
narrower Phase 5.0 field) or any of the legacy ``DeploymentService`` methods
in ``app.runtime.services`` -- ``deploy``/``suspend``/``resume``/``rollback``/
``retire`` there are unchanged, and every execution-path read of
``deployment.status`` (``_request_execution`` in that same module) is
untouched, per this phase's explicit scope boundary: the version resolver and
execution gate that would make ``lifecycle_state`` matter for execution is
Phase 3.4's own, single, deliberate change to that path.

Ruling #6 (agent suspension/kill integration): the platform's existing
mechanism is ``Agent.lifecycle_status`` reaching ``"SUSPENDED"`` -- driven
either by ``AgentLifecycleService`` (``app.runtime.registry.services``, the
ordinary agent lifecycle transition) or directly by ``KillSwitchService``
(``app.runtime.services``, §60) for an operator-triggered kill. This service
*reads* that field (``_assert_can_reach_active`` below) every time a
deployment would reach ``ACTIVE``; it never writes it and never introduces a
second suspension concept."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.authorization.enums import AuthorizationAuditEvent
from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.runtime import AgentDeployment, AgentVersion, DeploymentEvent, Environment, RuntimeApproval
from app.models.user import User
from app.runtime.deployment import lifecycle
from app.runtime.deployment.idempotency import IdempotencyService
from app.runtime.environment import policy as environment_policy
from app.runtime.services import DeploymentService, _now, _record_event

# One default audit event per lifecycle state, used whenever a caller (in
# particular the generic ``/lifecycle/transition`` route, which accepts an
# arbitrary declared ``to_state``) doesn't name a more specific one. Every
# state has an entry so ``transition()`` never has to guess or crash, even
# for a state this phase declares but does not yet drive (DEGRADED/
# ROLLING_BACK/SUPERSEDED -- see ``lifecycle.py``'s module docstring for which
# later phase drives each).
_DEFAULT_EVENT_FOR_STATE: dict[str, AuthorizationAuditEvent] = {
    "DRAFT": AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_CREATED,
    "VALIDATING": AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_VALIDATING,
    "VALIDATION_FAILED": AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_VALIDATION_FAILED,
    "READY": AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_READY,
    "PENDING_APPROVAL": AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_PENDING_APPROVAL,
    "APPROVED": AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_APPROVED,
    "REJECTED": AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_REJECTED,
    "DEPLOYING": AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_DEPLOYING,
    "ACTIVE": AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_ACTIVE,
    "PAUSED": AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_PAUSED,
    "DEGRADED": AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_DEGRADED,
    "ROLLING_BACK": AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_ROLLING_BACK,
    "FAILED": AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_FAILED,
    "SUPERSEDED": AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_SUPERSEDED,
    "RETIRED": AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_RETIRED,
}


class DeploymentLifecycleService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Lookup (delegates to the pre-existing, unchanged tenant-scoped query)
    # ------------------------------------------------------------------ #
    def get_or_404(self, actor: User, deployment_id: uuid.UUID) -> AgentDeployment:
        return DeploymentService(self.db).get_or_404(actor, deployment_id)

    def list_events(self, actor: User, deployment_id: uuid.UUID) -> list[DeploymentEvent]:
        deployment = self.get_or_404(actor, deployment_id)
        stmt = (select(DeploymentEvent)
               .where(DeploymentEvent.deployment_id == deployment.id)
               .order_by(DeploymentEvent.created_at.asc()))
        return list(self.db.execute(stmt).scalars())

    # ------------------------------------------------------------------ #
    # Ruling #6 + approval precondition (M3-3.1-FR-006, FR-020, FR-021)
    # ------------------------------------------------------------------ #
    def _requires_deployment_approval(self, agent: Agent, deployment: AgentDeployment) -> bool:
        version = self.db.get(AgentVersion, deployment.agent_version_id)
        policy = (version.policy_snapshot or {}) if version is not None else {}
        requires_approval_envs = set(policy.get("requires_approval_environments", []))
        if (deployment.environment in requires_approval_envs
               or (agent.criticality == "MISSION_CRITICAL" and deployment.environment == "PRODUCTION")):
            return True
        # Phase 3.2 (ACT-SRS-M3 §3.2 FR-011) -- a governed ``Environment``
        # entity may itself demand approval (production-class, or its own
        # policy's ``requires_approval`` flag), independent of the two
        # legacy checks above. Read through the exact same single
        # approval-reroute funnel this method already feeds -- never a
        # second, parallel approval path.
        if deployment.environment_id is not None:
            environment = self.db.get(Environment, deployment.environment_id)
            if environment is not None and environment_policy.requires_approval(environment):
                return True
        return False

    def _approved_deployment_approval(self, deployment: AgentDeployment) -> RuntimeApproval | None:
        return self.db.execute(select(RuntimeApproval).where(
            RuntimeApproval.deployment_id == deployment.id,
            RuntimeApproval.requested_action == "DEPLOYMENT",
            RuntimeApproval.status == "APPROVED",
        )).scalars().first()

    def _assert_can_reach_active(self, agent: Agent, deployment: AgentDeployment) -> None:
        if agent.lifecycle_status == "SUSPENDED":
            raise IdentityError(ErrorCode.DEPLOYMENT_AGENT_SUSPENDED,
                               "Cannot activate a deployment whose agent is suspended.")
        if self._requires_deployment_approval(agent, deployment):
            if self._approved_deployment_approval(deployment) is None:
                raise IdentityError(
                    ErrorCode.DEPLOYMENT_INVALID_TRANSITION,
                    "This deployment requires an approved runtime_approvals record "
                    "before it can become ACTIVE.",
                )

    # ------------------------------------------------------------------ #
    # The one transition authority (M3-3.1-FR-001..005)
    # ------------------------------------------------------------------ #
    def transition(self, actor: User, deployment: AgentDeployment, to_state: str, *,
                   event: AuthorizationAuditEvent | None = None, reason: str | None = None,
                   expected_revision: int | None = None) -> AgentDeployment:
        from_state = deployment.lifecycle_state
        if not lifecycle.can_transition(from_state, to_state):
            raise IdentityError(ErrorCode.DEPLOYMENT_INVALID_TRANSITION,
                               f"Cannot move deployment from {from_state} to {to_state}.")
        # Client-supplied optimistic-locking precondition (an "If-Match"
        # style check against what the caller last read) -- distinct from,
        # and in addition to, the database-level compare-and-swap below.
        if expected_revision is not None and deployment.revision != expected_revision:
            raise IdentityError(ErrorCode.DEPLOYMENT_REVISION_CONFLICT,
                               "This deployment was modified by another request; reload and retry.")

        if to_state == "ACTIVE":
            agent = self.db.get(Agent, deployment.agent_id)
            self._assert_can_reach_active(agent, deployment)

        deployment.lifecycle_state = to_state
        deployment.state_reason = reason
        resolved_event = event or _DEFAULT_EVENT_FOR_STATE[to_state]
        try:
            # ``AgentDeployment.__mapper_args__["version_id_col"]`` makes the
            # eventual UPDATE for this row carry ``WHERE revision = <the
            # value loaded into this session>`` and auto-increment it -- the
            # real, database-level compare-and-swap that makes AC-05's
            # concurrent-writer race actually safe, independent of the
            # manual check above. SQLAlchemy may raise ``StaleDataError`` as
            # early as the *first* flush after the assignment above (e.g.
            # ``_record_event``'s own, unrelated insert below can trigger
            # one) -- so the whole sequence from the assignment through the
            # final commit is one try block, not just the commit itself.
            self.db.add(DeploymentEvent(
                deployment_id=deployment.id, organization_id=deployment.organization_id,
                from_state=from_state, to_state=to_state, event_type=resolved_event.value,
                reason=reason, actor_id=actor.id if actor else None,
            ))
            _record_event(self.db, resolved_event, actor, organization_id=deployment.organization_id,
                         agent_id=deployment.agent_id, deployment_id=deployment.id,
                         meta={"from": from_state, "to": to_state, "reason": reason})
            self.db.commit()
        except StaleDataError:
            self.db.rollback()
            raise IdentityError(ErrorCode.DEPLOYMENT_REVISION_CONFLICT,
                               "This deployment was modified by another request; reload and retry.") from None
        self.db.refresh(deployment)
        return deployment

    # ------------------------------------------------------------------ #
    # Create (M3-3.1-FR-010..013 idempotency contract applied)
    # ------------------------------------------------------------------ #
    def create(self, actor: User, agent: Agent, version: AgentVersion, payload: dict, *,
              idempotency_key: str | None = None) -> tuple[dict, bool]:
        from app.runtime.schemas import DeploymentRead  # local import: schemas is a leaf module

        def _do() -> dict:
            deployment = DeploymentService(self.db).create(actor, agent, version, payload)
            # ``lifecycle_state`` already defaults to "DRAFT" at INSERT (the
            # column default) -- nothing to assign here, only to record.
            if deployment.environment_id is None:
                # Phase 3.2 (ACT-SRS-M3 §3.2 FR-002) -- best-effort,
                # opportunistic string->row resolution for the legacy,
                # string-only create path (``PromotionService.promote``
                # already sets ``environment_id`` directly via ``payload``
                # and never reaches here). A local import -- ``app.runtime.
                # environment.service`` imports this module's own
                # ``DeploymentLifecycleService``, so a module-level import
                # here would be circular.
                from app.runtime.environment.service import EnvironmentService
                environment = EnvironmentService(self.db).get_by_name(actor.organization_id, deployment.environment)
                if environment is not None:
                    deployment.environment_id = environment.id
            self.db.add(DeploymentEvent(
                deployment_id=deployment.id, organization_id=deployment.organization_id,
                from_state=None, to_state="DRAFT",
                event_type=AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_CREATED.value,
                actor_id=actor.id,
            ))
            self.db.commit()
            self.db.refresh(deployment)
            return DeploymentRead.model_validate(deployment).model_dump(mode="json")

        request_payload = {**payload, "agent_id": str(agent.id), "agent_version_id": str(version.id)}
        return IdempotencyService(self.db).execute(
            organization_id=actor.organization_id, operation="deployment.create",
            key=idempotency_key, payload=request_payload, fn=_do,
        )

    # ------------------------------------------------------------------ #
    # Convenience drivers this phase owns (M3-3.1-FR-002's happy path)
    # ------------------------------------------------------------------ #
    def start_deploying(self, actor: User, deployment: AgentDeployment, *,
                        reason: str | None = None, expected_revision: int | None = None) -> AgentDeployment:
        """READY|APPROVED -> ... -> ACTIVE, synchronous end to end (there is
        no distributed worker/scheduler in this phase -- ``docs/runtime/workers.md``'s
        precedent already runs the platform's execution queue inline for the
        same reason). Mirrors the legacy ``DeploymentService.deploy()``'s own
        approval-reroute shape (§14) for the *new* machine, without touching
        that method: a deployment whose environment/policy requires approval
        and has none yet lands in PENDING_APPROVAL (creating the
        ``runtime_approvals`` row) instead of proceeding -- never an error,
        exactly like the precedent it mirrors."""
        agent = self.db.get(Agent, deployment.agent_id)
        # Phase 3.2 (ACT-SRS-M3 §3.2 FR-011) -- the single deploy/promote-time
        # environment-policy choke point. Covers both a plain deploy *and* a
        # promotion (``PromotionService.promote`` creates its new deployment
        # and calls this same method) -- never duplicated at a second call
        # site. A deployment with no governed ``environment_id`` yet (still
        # possible for the legacy string-only create path when the target
        # organization has no environment row matching that string) skips
        # this check entirely rather than failing closed on metadata that
        # doesn't exist -- see docs/deployment/environments.md.
        if deployment.environment_id is not None:
            environment = self.db.get(Environment, deployment.environment_id)
            if environment is not None:
                version_for_policy = self.db.get(AgentVersion, deployment.agent_version_id)
                violation = environment_policy.evaluate(
                    self.db, environment, version_for_policy, agent.id, exclude_deployment_id=deployment.id)
                if violation is not None:
                    raise IdentityError(violation.code, violation.message)
        if deployment.lifecycle_state == "READY" and self._requires_deployment_approval(agent, deployment):
            if self._approved_deployment_approval(deployment) is None:
                self.db.add(RuntimeApproval(
                    organization_id=deployment.organization_id, agent_id=agent.id,
                    deployment_id=deployment.id, requested_action="DEPLOYMENT",
                    risk_score=80, reason=reason or "Deployment requires approval before activation.",
                    requested_by=actor.id,
                ))
                return self.transition(actor, deployment, "PENDING_APPROVAL", reason=reason,
                                       expected_revision=expected_revision)

        deployment = self.transition(actor, deployment, "DEPLOYING", reason=reason,
                                     expected_revision=expected_revision)
        deployment.deployed_by = actor.id
        deployment.deployed_at = _now()
        return self.transition(actor, deployment, "ACTIVE", reason=reason)

    def pause(self, actor: User, deployment: AgentDeployment, *, reason: str | None = None,
             expected_revision: int | None = None) -> AgentDeployment:
        return self.transition(actor, deployment, "PAUSED", reason=reason, expected_revision=expected_revision)

    def resume(self, actor: User, deployment: AgentDeployment, *, reason: str | None = None,
              expected_revision: int | None = None) -> AgentDeployment:
        return self.transition(actor, deployment, "ACTIVE",
                               event=AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_RESUMED,
                               reason=reason, expected_revision=expected_revision)

    def retire(self, actor: User, deployment: AgentDeployment, *, reason: str | None = None,
              expected_revision: int | None = None) -> AgentDeployment:
        return self.transition(actor, deployment, "RETIRED", reason=reason, expected_revision=expected_revision)

    def mark_failed(self, actor: User, deployment: AgentDeployment, *,
                    reason: str | None = None) -> AgentDeployment:
        return self.transition(actor, deployment, "FAILED", reason=reason)

    # ------------------------------------------------------------------ #
    # Approval integration (M3-3.1-FR-006) -- called additively from
    # RuntimeApprovalService.decide(), alongside (never instead of) that
    # method's own pre-existing ``.status`` handling.
    # ------------------------------------------------------------------ #
    def apply_approval_decision(self, actor: User, deployment: AgentDeployment,
                                decision: str) -> AgentDeployment | None:
        if deployment.lifecycle_state != "PENDING_APPROVAL":
            return None
        to_state = "APPROVED" if decision == "APPROVED" else "REJECTED"
        return self.transition(actor, deployment, to_state)
