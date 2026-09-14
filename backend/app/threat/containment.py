"""Phase 5.6 (M5.6) - ``ContainmentOrchestrator``: routes a containment
action to the **one existing authority** that can actually perform it.
Implements no enforcement of its own (AST-proven, ``test_ac04``).

**The action -> authority map (ADR-0020, exhaustive — there is no eighth
action):**

======================  =====================  ============================================
action_type             authority               real call
======================  =====================  ============================================
TERMINATE_EXECUTION     KILL_SWITCH             ``KillSwitchService`` scope EXECUTION
SUSPEND_AGENT           KILL_SWITCH             ``KillSwitchService`` scope AGENT
DENY_TOOL               TOOL_LIFECYCLE          ``ToolRegistryService.revoke`` (an AgentTool grant)
REVOKE_CAPABILITY       CAPABILITY_LIFECYCLE    ``CapabilityService.revoke`` (an AgentCapability grant)
ISOLATE_CREDENTIAL      CREDENTIAL_LIFECYCLE    ``app.services.api_key_service.revoke_key``
DISABLE_INTEGRATION     CONNECTOR_LIFECYCLE     ``ConnectorService.disable``
REQUIRE_APPROVAL        GOVERNANCE_POLICY       ``GovernancePolicyService.create`` (a real,
                                                 mandatory, agent-scoped CHALLENGE policy — the
                                                 same ``requires_approval`` constraint the 4.3
                                                 engine's own checkpoints read)
======================  =====================  ============================================

**Truthful containment (the honesty spine).** Capability is derived from
exactly one signal, ``agents.control_state`` — ``GOVERNED`` means ACT is the
system actually running/enforcing this agent; anything else (``DISCOVERED``/
``CLAIMED``/``REGISTERED``) means it is not, and every enforcement-requiring
action is **truthfully refused** (``status='REFUSED'``, a real
``refusal_reason``) rather than attempted. There is no code path that
fabricates a success for a non-``GOVERNED`` agent.

**Kill-switch dominance.** This module contains no branch that sets
``lifecycle_status`` back to ``'ACTIVE'`` or ``cancel_requested`` back to
``False`` — the same AST property ``app.runtime.governance`` proves for
itself (``test_ac06``). ``SUSPEND_AGENT``/``TERMINATE_EXECUTION`` are marked
``reversible=False`` for exactly this reason: this module never un-suspends.

**Commit-before-dispatch.** None of the seven authorities above perform
network or model I/O — every one is a plain ORM write + commit. There is
therefore no lock to hold across an external call; the AST proof
(``test_ac07``) additionally confirms no statement in this package uses
``with_for_update`` or writes ``FOR UPDATE`` into raw SQL, so the M1 deadlock
shape cannot arise here even if a future authority gains external I/O.

**Automated invocation uses the existing automation principal**
(``app.scheduler.principal``, Phase 3.8) — the same non-human, unusable-login,
per-organization ``User`` row every scheduled job already acts under. No new
"system identity" concept.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.services import AuthorizationAuditService
from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.threat import ContainmentAction
from app.models.user import User

#: The only signal truthful containment reads. GOVERNED = ACT actually
#: executes/enforces this agent. Anything else -> every enforcement-requiring
#: action is truthfully absent.
_ENFORCEABLE_CONTROL_STATE = "GOVERNED"

_AUTHORITY_FOR: dict[str, str] = {
    "TERMINATE_EXECUTION": "KILL_SWITCH",
    "SUSPEND_AGENT": "KILL_SWITCH",
    "DENY_TOOL": "TOOL_LIFECYCLE",
    "REVOKE_CAPABILITY": "CAPABILITY_LIFECYCLE",
    "ISOLATE_CREDENTIAL": "CREDENTIAL_LIFECYCLE",
    "DISABLE_INTEGRATION": "CONNECTOR_LIFECYCLE",
    "REQUIRE_APPROVAL": "GOVERNANCE_POLICY",
}

#: Whether this module can reverse the action through the SAME authority's
#: own reverse operation. SUSPEND_AGENT/TERMINATE_EXECUTION are False by
#: construction (kill-switch dominance: this module never un-suspends).
#: ISOLATE_CREDENTIAL is False because revoking a credential has no reverse
#: (re-issuing is a new credential, not a revert of this one).
_REVERSIBLE = {
    "TERMINATE_EXECUTION": False,
    "SUSPEND_AGENT": False,
    "DENY_TOOL": True,
    "REVOKE_CAPABILITY": True,
    "ISOLATE_CREDENTIAL": False,
    "DISABLE_INTEGRATION": True,
    "REQUIRE_APPROVAL": True,
}

# Every action this module offers is dangerous by construction (it reaches an
# enforcement authority), so every one requires explicit confirmation before
# the real authority is invoked. There is no "safe" containment action that
# skips this.
_REQUIRES_CONFIRMATION = True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_safe(value):
    """The authorities this module calls return plain dicts meant for a
    Python caller, not a JSONB column -- ``KillSwitchService.activate*``
    hands back a raw ``target_id: uuid.UUID``, for instance. This makes
    whatever a real authority returns storable verbatim in ``result``/
    ``authority_ref`` without each dispatch branch having to know that."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


class ContainmentRefused(Exception):
    """Raised only for the caller's convenience when it wants an exception
    rather than reading ``ContainmentAction.status``. The HTTP layer catches
    this and renders it; nothing about truthful refusal is exceptional in the
    data model itself (a REFUSED row is a normal, complete, honest record)."""

    def __init__(self, action: ContainmentAction) -> None:
        self.action = action
        super().__init__(action.refusal_reason)


class ContainmentOrchestrator:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    def truthful_capability(self, agent: Agent) -> tuple[bool, str | None]:
        """The one place capability is decided. Nothing else in this package
        may attempt an authority call without going through this."""
        if agent.control_state == _ENFORCEABLE_CONTROL_STATE:
            return True, None
        return False, (
            f"ACT has no enforcement authority over this agent "
            f"(control_state={agent.control_state!r}, requires {_ENFORCEABLE_CONTROL_STATE!r}). "
            "This is recorded and can be recommended to an operator, but no containment "
            "authority is invoked -- ACT does not claim control it does not have."
        )

    def _get_agent(self, organization_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
        agent = self.db.get(Agent, agent_id)
        if agent is None or agent.organization_id != organization_id:
            raise IdentityError(ErrorCode.AGENT_NOT_FOUND, "Agent not found in this organization.")
        return agent

    def _automation_actor(self, organization_id: uuid.UUID) -> User:
        from app.scheduler import principal as automation

        return automation.get_or_create(self.db, organization_id)

    # ------------------------------------------------------------------ #
    def execute(
        self, *, organization_id: uuid.UUID, agent_id: uuid.UUID, action_type: str,
        trigger: str, reason: str, operator: User | None = None,
        target_id: uuid.UUID | None = None, threat_finding_id: uuid.UUID | None = None,
        confirm: bool = False,
    ) -> ContainmentAction:
        """The single entry point. ``trigger`` is ``THREAT`` (automated,
        ``operator`` is None, the automation principal is used to invoke any
        authority that needs an actor) or ``OPERATOR`` (a human; ``operator``
        is required and is who the record attributes the decision to).

        Returns the ``ContainmentAction`` row in every case -- REFUSED,
        PENDING_CONFIRMATION, EXECUTED or FAILED are all complete, honest
        outcomes, never an exception for the normal paths."""
        if action_type not in _AUTHORITY_FOR:
            raise IdentityError(ErrorCode.CONTAINMENT_ACTION_UNKNOWN,
                               f"'{action_type}' is not a containment action.")
        if trigger not in ("THREAT", "OPERATOR"):
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "trigger must be THREAT or OPERATOR.")
        if trigger == "OPERATOR" and operator is None:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "An operator-triggered action needs an actor.")

        agent = self._get_agent(organization_id, agent_id)
        authority = _AUTHORITY_FOR[action_type]
        automated = trigger == "THREAT"

        # The record is created and committed first, in whatever state this
        # call can immediately determine (REFUSED / PENDING_CONFIRMATION /
        # about to attempt). It is a stable, persisted row *before* any
        # authority is ever invoked, so a failure inside the authority call
        # rolls back only that call's own partial writes -- never this row's
        # existence, which the subsequent UPDATE (in its own transaction)
        # then finishes honestly (EXECUTED or FAILED).
        record = ContainmentAction(
            organization_id=organization_id, action_type=action_type, authority=authority,
            trigger=trigger, threat_finding_id=threat_finding_id,
            triggered_by_user_id=operator.id if operator else None, automated=automated,
            agent_id=agent.id, target_type=_TARGET_TYPE.get(action_type), target_id=target_id,
            control_state_at_time=agent.control_state, reason=reason,
            requires_confirmation=_REQUIRES_CONFIRMATION, reversible=_REVERSIBLE[action_type],
            status="RECOMMENDED",
        )

        capable, refusal = self.truthful_capability(agent)
        if not capable:
            record.status = "REFUSED"
            record.refusal_reason = refusal
            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)
            self._audit(AuthorizationAuditEvent.CONTAINMENT_ACTION_REFUSED, organization_id,
                        operator, record, meta={"refusal_reason": refusal})
            self.db.commit()
            return record

        if not confirm:
            record.status = "PENDING_CONFIRMATION"
            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)
            self._audit(AuthorizationAuditEvent.CONTAINMENT_ACTION_QUEUED, organization_id,
                        operator, record, meta={})
            self.db.commit()
            return record

        record.status = "PENDING_CONFIRMATION"
        record.confirmed_by = operator.id if operator else None
        record.confirmed_at = _now()
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        record_id = record.id

        actor_for_call = operator or self._automation_actor(organization_id)
        try:
            authority_ref, result = self._invoke(
                action_type, organization_id=organization_id, agent=agent,
                actor=actor_for_call, target_id=target_id, automated=automated, reason=reason,
            )
        except Exception as exc:  # noqa: BLE001 -- a mandatory containment that fails must say so
            self.db.rollback()
            record = self.db.get(ContainmentAction, record_id)
            record.status = "FAILED"
            record.result = {"error": str(exc), "error_class": exc.__class__.__name__}
            self._audit(AuthorizationAuditEvent.CONTAINMENT_ACTION_FAILED, organization_id,
                        operator, record, meta={"error": str(exc)})
            self.db.commit()
            self.db.refresh(record)
            return record

        # The authority call above already committed its own change (every
        # authority method commits or flushes on success). Re-fetch the
        # record fresh and finish it in its own transaction.
        record = self.db.get(ContainmentAction, record_id)
        record.status = "EXECUTED"
        record.authority_ref = _json_safe(authority_ref)
        record.result = _json_safe(result)
        self._audit(AuthorizationAuditEvent.CONTAINMENT_ACTION_EXECUTED, organization_id,
                    operator, record, meta={"authority_ref": authority_ref})
        self.db.commit()
        self.db.refresh(record)
        return record

    # ------------------------------------------------------------------ #
    # The action -> authority dispatch. Every branch calls an existing
    # service method; none implements enforcement itself.
    # ------------------------------------------------------------------ #
    def _invoke(self, action_type: str, *, organization_id: uuid.UUID, agent: Agent,
               actor: User, target_id: uuid.UUID | None, automated: bool,
               reason: str) -> tuple[dict, dict]:
        if action_type == "TERMINATE_EXECUTION":
            return self._terminate_execution(organization_id, target_id, actor, automated, reason)
        if action_type == "SUSPEND_AGENT":
            return self._suspend_agent(organization_id, agent, actor, automated, reason)
        if action_type == "DENY_TOOL":
            return self._deny_tool(actor, agent, target_id)
        if action_type == "REVOKE_CAPABILITY":
            return self._revoke_capability(actor, agent, target_id)
        if action_type == "ISOLATE_CREDENTIAL":
            return self._isolate_credential(agent, target_id)
        if action_type == "DISABLE_INTEGRATION":
            return self._disable_integration(actor, organization_id, target_id, reason)
        if action_type == "REQUIRE_APPROVAL":
            return self._require_approval(actor, agent, reason)
        raise IdentityError(ErrorCode.CONTAINMENT_ACTION_UNKNOWN, f"Unhandled action '{action_type}'.")

    def _terminate_execution(self, organization_id, target_id, actor, automated, reason):
        from app.runtime.services import KillSwitchService

        if target_id is None:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "TERMINATE_EXECUTION needs target_id.")
        svc = KillSwitchService(self.db)
        if automated:
            out = svc.activate_system(organization_id=organization_id, scope="EXECUTION",
                                      target_id=target_id, reason=reason, origin="threat_containment")
        else:
            out = svc.activate(actor, "EXECUTION", target_id, reason)
        return {"table": "agent_executions", "id": str(target_id)}, out

    def _suspend_agent(self, organization_id, agent, actor, automated, reason):
        from app.runtime.services import KillSwitchService

        svc = KillSwitchService(self.db)
        if automated:
            out = svc.activate_system(organization_id=organization_id, scope="AGENT",
                                      target_id=agent.id, reason=reason, origin="threat_containment")
        else:
            out = svc.activate(actor, "AGENT", agent.id, reason)
        return {"table": "agents", "id": str(agent.id)}, out

    def _deny_tool(self, actor, agent, target_id):
        from app.runtime.services import ToolRegistryService

        if target_id is None:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "DENY_TOOL needs target_id (an AgentTool assignment).")
        assignment = ToolRegistryService(self.db).revoke(actor, agent, target_id)
        return {"table": "agent_tools", "id": str(assignment.id)}, {"status": assignment.status}

    def _revoke_capability(self, actor, agent, target_id):
        from app.runtime.services import CapabilityService

        if target_id is None:
            raise IdentityError(ErrorCode.VALIDATION_ERROR,
                               "REVOKE_CAPABILITY needs target_id (an AgentCapability assignment).")
        assignment = CapabilityService(self.db).revoke(actor, agent, target_id)
        return {"table": "agent_capabilities", "id": str(assignment.id)}, {"status": assignment.status}

    def _isolate_credential(self, agent, target_id):
        from app.models.api_key import AgentApiKey
        from app.services.api_key_service import revoke_key

        if target_id is None:
            raise IdentityError(ErrorCode.VALIDATION_ERROR,
                               "ISOLATE_CREDENTIAL needs target_id (an agent API key).")
        record = self.db.get(AgentApiKey, target_id)
        if record is None or record.agent_id != agent.id:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "That credential does not belong to this agent.")
        revoke_key(self.db, record)
        self.db.flush()
        return {"table": "agent_api_keys", "id": str(record.id)}, {"status": str(record.status)}

    def _disable_integration(self, actor, organization_id, target_id, reason):
        from app.integration.service import ConnectorService

        if target_id is None:
            raise IdentityError(ErrorCode.VALIDATION_ERROR,
                               "DISABLE_INTEGRATION needs target_id (a connector instance).")
        instance = ConnectorService(self.db).disable(actor, organization_id, target_id, reason=reason)
        return {"table": "connector_instances", "id": str(instance.id)}, {"lifecycle_state": instance.lifecycle_state}

    def _require_approval(self, actor, agent, reason):
        from app.runtime.governance.policies import GovernancePolicyService

        name = f"threat-containment-require-approval-{agent.id}"
        policy = GovernancePolicyService(self.db).create(actor, {
            "agent_id": agent.id, "name": name[:128],
            "description": f"Containment: {reason}"[:2000],
            "constraints": {"requires_approval": True},
            "mandatory": True, "enabled": True,
        })
        return {"table": "runtime_governance_policies", "id": str(policy.id)}, {"policy_id": str(policy.id)}

    # ------------------------------------------------------------------ #
    # Revert -- only for actions this module marked reversible, and only
    # through the SAME authority's own reverse operation. Never used for
    # SUSPEND_AGENT/TERMINATE_EXECUTION (kill-switch dominance).
    # ------------------------------------------------------------------ #
    def revert(self, actor: User, action: ContainmentAction) -> ContainmentAction:
        if not action.reversible:
            raise IdentityError(ErrorCode.CONTAINMENT_ACTION_NOT_REVERSIBLE,
                               f"A {action.action_type} containment action is not reversible.")
        if action.status != "EXECUTED":
            raise IdentityError(ErrorCode.CONTAINMENT_ACTION_NOT_REVERSIBLE,
                               "Only an executed containment action can be reverted.")
        agent = self._get_agent(action.organization_id, action.agent_id)
        if action.action_type == "DENY_TOOL":
            from app.runtime.services import ToolRegistryService

            ToolRegistryService(self.db).decide(actor, agent, action.target_id, approve=True)
        elif action.action_type == "REVOKE_CAPABILITY":
            from app.runtime.services import CapabilityService

            CapabilityService(self.db).decide(actor, agent, action.target_id, approve=True)
        elif action.action_type == "DISABLE_INTEGRATION":
            # disabled -> configured -> active: the real lifecycle has no
            # direct disabled -> active transition (disable is only valid
            # from active), so reverting genuinely takes the same two steps
            # an operator would take (app/integration/lifecycle.py).
            from app.integration.service import ConnectorService

            svc = ConnectorService(self.db)
            instance = svc.get_or_404(action.organization_id, action.target_id)
            svc.update_configuration(actor, action.organization_id, action.target_id,
                                     instance.configuration)
            svc.activate(actor, action.organization_id, action.target_id)
        elif action.action_type == "REQUIRE_APPROVAL":
            from app.runtime.governance.policies import GovernancePolicyService

            policy_id = uuid.UUID((action.authority_ref or {}).get("id"))
            GovernancePolicyService(self.db).update(actor, policy_id, {"enabled": False})
        else:  # pragma: no cover -- guarded by `reversible` above
            raise IdentityError(ErrorCode.CONTAINMENT_ACTION_NOT_REVERSIBLE,
                               f"No reverse operation for {action.action_type}.")

        action.status = "REVERTED"
        action.reverted_at = _now()
        action.reverted_by = actor.id
        self._audit(AuthorizationAuditEvent.CONTAINMENT_ACTION_REVERTED, action.organization_id,
                    actor, action, meta={})
        self.db.commit()
        self.db.refresh(action)
        return action

    # ------------------------------------------------------------------ #
    def _audit(self, event: AuthorizationAuditEvent, organization_id: uuid.UUID,
               operator: User | None, record: ContainmentAction, *, meta: dict) -> None:
        AuthorizationAuditService(self.db).record_change(
            event, organization_id=organization_id, actor_id=operator.id if operator else None,
            meta={
                "action_type": record.action_type, "authority": record.authority,
                "trigger": record.trigger, "automated": record.automated,
                "agent_id": str(record.agent_id), "control_state_at_time": record.control_state_at_time,
                **meta,
            },
        )


_TARGET_TYPE: dict[str, str | None] = {
    "TERMINATE_EXECUTION": "EXECUTION",
    "SUSPEND_AGENT": None,
    "DENY_TOOL": "AGENT_TOOL",
    "REVOKE_CAPABILITY": "AGENT_CAPABILITY",
    "ISOLATE_CREDENTIAL": "AGENT_API_KEY",
    "DISABLE_INTEGRATION": "CONNECTOR_INSTANCE",
    "REQUIRE_APPROVAL": None,
}


__all__ = ["ContainmentOrchestrator", "ContainmentRefused"]
