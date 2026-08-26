"""``RuntimeGovernanceEngine`` — the one place that decides whether an
execution may continue (M4-4.3-FR-001..004, FR-020..022, FR-030..032,
FR-040..042).

Read ``app.runtime.governance``'s package docstring first; it states the two
rules this module exists to hold apart (governance fails closed, telemetry
fails open) and the one-enforcement-path framing.

**Transaction discipline — the commit-before-dispatch invariant (§9, AC-10).**
Every checkpoint here does exactly two kinds of database work:

1. one plain, **non-locking** ``SELECT`` of the execution's own kill state, and
2. for a *material* decision only, one ``INSERT`` into
   ``runtime_governance_decisions``.

No statement in this module takes ``FOR UPDATE``/``FOR NO KEY UPDATE``, and
``test_ac10_*`` asserts that structurally over the AST as well as behaviourally
against a real second connection. The only lock a checkpoint can cause is the
foreign-key ``KEY SHARE`` on this execution's own ``agent_executions`` row,
implied by the decision INSERT — which is precisely the lock
``ToolLoopOrchestrator._append_message`` has already been taking on every turn
since Phase 5.6a.3, and which is *compatible* with the ``KEY SHARE`` a
tool-executing thread needs to insert its ``tool_calls`` row. The M1 deadlock
required a ``FOR UPDATE`` held across dispatch; nothing here can produce one.

**Policy is snapshotted once per execution, not re-read per checkpoint.** The
consistency rule (§9) is: *an execution is governed by the policy set in force
when its loop began.* A policy edited mid-flight applies to executions that
start after it. The alternative — re-resolving at each checkpoint — would let a
tightened policy stop an execution at iteration 5 having permitted iterations 1
through 4 under looser rules, producing a half-governed execution and a
decision lineage that cannot be read as a single story. It also keeps six
checkpoints per iteration off the query path.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.errors import ErrorCode
from app.models.agent import Agent
from app.models.runtime import (
    AgentExecution,
    RuntimeApproval,
    RuntimeGovernanceDecision,
    RuntimeGovernancePolicy,
)
from app.runtime.governance.constraints import BUILTIN_CAPS, POLICY_CONSTRAINTS
from app.runtime.governance.contract import (
    Checkpoint,
    CheckpointContext,
    Decision,
    GovernanceChallenged,
    GovernanceDecision,
    GovernanceStopped,
    ReasonCode,
    StopAction,
    allow,
)
from app.runtime.governance.policies import GovernancePolicyService

logger = logging.getLogger(__name__)

# Statuses that mean this execution has been killed or cancelled out from under
# the loop. Kept local and explicit rather than imported from the worker's own
# terminal-status set: the question here is narrower ("has intervention
# happened"), and a future addition to the worker's terminal set should not
# silently change what the governance engine treats as a kill.
_KILLED_STATUSES = frozenset({"CANCELLED", "DENIED", "BLOCKED"})


class RuntimeGovernanceEngine:
    """One engine, six checkpoints, one enforcement path.

    Instantiated once per execution attempt by ``ToolLoopOrchestrator`` and
    bound to that execution, so the policy snapshot and the resolved scope are
    established exactly once.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._policies: tuple[RuntimeGovernancePolicy, ...] = ()
        self._bound = False
        # Fail-closed latch. Set when policy resolution itself failed, which is
        # unevaluable in the strongest sense: we do not merely not know what
        # the policies say, we do not know whether a *mandatory* one applies.
        self._unevaluable: str | None = None
        self._approval_granted = False

    # ------------------------------------------------------------------ #
    # Binding
    # ------------------------------------------------------------------ #
    def bind(self, execution: AgentExecution, *, environment_id: uuid.UUID | None,
             agent_id: uuid.UUID | None) -> "RuntimeGovernanceEngine":
        """Resolve and snapshot the policy set for this execution.

        A failure here does **not** raise. It latches ``_unevaluable``, and the
        first checkpoint turns that into a ``STOP`` — so the failure surfaces
        as a governance decision with a reason and a persisted record, rather
        than as an unexplained exception from the middle of the worker. Failing
        closed and failing *legibly* are not the same requirement, and this
        phase owes both.

        It also resolves, once, whether a human has **already approved** an
        obligation for this execution. Without that, the existing approval
        funnel would re-queue an approved execution straight back into the
        checkpoint that challenged it, which would challenge again -- an
        approval loop rather than an approval. One query per attempt, not one
        per checkpoint."""
        self._approval_granted = self._has_approval(execution)
        try:
            self._policies = tuple(GovernancePolicyService(self.db).resolve(
                execution.organization_id, environment_id=environment_id, agent_id=agent_id))
        except Exception as exc:  # noqa: BLE001 -- §9: governance fails CLOSED
            logger.warning("Runtime governance policy resolution failed for execution %s: %s",
                           execution.id, exc)
            self._policies = ()
            self._unevaluable = (
                "Runtime governance policy could not be resolved, so whether a mandatory "
                "policy applies to this execution is unknown.")
        self._bound = True
        return self

    def _has_approval(self, execution: AgentExecution) -> bool:
        """Has a human already granted an obligation raised for this
        execution? A failure here is read as *not approved*, which is the
        conservative direction: an unreadable approval must not be able to
        satisfy a control by defaulting to yes."""
        try:
            return self.db.execute(
                select(RuntimeApproval.id).where(
                    RuntimeApproval.execution_id == execution.id,
                    RuntimeApproval.status == "APPROVED",
                ).limit(1)
            ).first() is not None
        except Exception:  # noqa: BLE001
            return False

    @property
    def policies(self) -> tuple[RuntimeGovernancePolicy, ...]:
        return self._policies

    # ------------------------------------------------------------------ #
    # Evaluation
    # ------------------------------------------------------------------ #
    def evaluate(self, checkpoint: Checkpoint, ctx: CheckpointContext) -> GovernanceDecision:
        """M4-4.3-FR-001/002 — the single entry point every checkpoint uses.

        Order of consideration, and each position is a decision:

        1. **Kill switch first.** §19 gives the kill switch dominance over
           everything, so nothing this engine could conclude may be reached
           before asking whether one has fired. It is also the only input here
           that another connection can change mid-loop.
        2. **Fail-closed latch**, if policy resolution failed at ``bind``.
        3. **Built-in caps**, in the order documented in ``constraints``.
           Platform loop-safety comes before tenant configuration because a
           tenant policy must not be able to extend a platform cap by
           objecting first and terminating with a different reason.
        4. **Policy constraints**, most specific policy first.
        """
        try:
            killed = self._kill_state(ctx)
        except Exception as exc:  # noqa: BLE001 -- §9: governance fails CLOSED
            logger.warning("Kill-switch state unreadable at %s for execution %s: %s",
                           checkpoint.value, ctx.execution_id, exc)
            return self._record(self._unevaluable_decision(
                checkpoint, "Kill-switch state could not be read at this checkpoint."), ctx)
        if killed is not None:
            return self._record(replace(killed, checkpoint=checkpoint), ctx)

        if self._unevaluable is not None:
            return self._record(
                self._unevaluable_decision(checkpoint, self._unevaluable), ctx)

        for cap in BUILTIN_CAPS[checkpoint]:
            try:
                decision = cap(ctx)
            except Exception as exc:  # noqa: BLE001 -- §9: a cap is mandatory by definition
                logger.warning("Built-in cap %s failed at %s: %s", cap.__name__, checkpoint.value, exc)
                return self._record(self._unevaluable_decision(
                    checkpoint, f"A mandatory loop-safety cap ({cap.__name__}) could not be "
                                f"evaluated at this checkpoint."), ctx)
            if decision is not None:
                return self._record(replace(decision, checkpoint=checkpoint), ctx)

        # Stamped by the engine rather than supplied by the caller: whether an
        # obligation has been granted is the engine's own bookkeeping, and a
        # loop that had to remember to pass it would eventually forget.
        ctx = replace(ctx, approval_granted=self._approval_granted)
        for policy in self._policies:
            decision = self._evaluate_policy(policy, checkpoint, ctx)
            if decision is not None:
                return self._record(decision, ctx)

        return self._record(allow(checkpoint), ctx)

    def _evaluate_policy(self, policy: RuntimeGovernancePolicy, checkpoint: Checkpoint,
                         ctx: CheckpointContext) -> GovernanceDecision | None:
        """M4-4.3-FR-020/021 — where the mandatory flag earns its keep.

        A policy that cannot be evaluated is not the same event depending on
        how it was configured, and that asymmetry is the whole design: a
        **mandatory** policy that cannot be evaluated STOPs, because "we could
        not check the rule you told us was non-negotiable" is not a reason to
        proceed. A non-mandatory one is logged and skipped, because an advisory
        rule that halts production the moment it misbehaves is a worse control
        than no rule at all."""
        spec = policy.constraints if isinstance(policy.constraints, dict) else {}
        stop_action = self._stop_action(spec)
        for constraint in POLICY_CONSTRAINTS[checkpoint]:
            try:
                verdict = constraint(ctx, spec)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Governance constraint %s of policy %s failed at %s: %s",
                               constraint.__name__, policy.id, checkpoint.value, exc)
                if policy.mandatory:
                    return self._unevaluable_decision(
                        checkpoint,
                        f"Mandatory governance policy '{policy.name}' could not be evaluated "
                        f"at this checkpoint.", policy_id=policy.id)
                continue
            if verdict is None:
                continue
            decision, reason_code, reason = verdict
            return GovernanceDecision(
                checkpoint=checkpoint, decision=decision, reason_code=reason_code,
                reason=reason, policy_id=policy.id, from_policy=True,
                obligation=self._obligation(decision, reason_code, ctx),
                termination_reason="GOVERNANCE_STOP" if decision is Decision.STOP else (
                    "GOVERNANCE_DENY" if decision is Decision.DENY else "GOVERNANCE_CHALLENGE"),
                error_code=self._error_code(decision),
                stop_action=stop_action if decision is Decision.STOP else StopAction.NONE,
            )
        return None

    # ------------------------------------------------------------------ #
    # Enforcement — the orchestrator's single-line insertion point
    # ------------------------------------------------------------------ #
    def enforce(self, checkpoint: Checkpoint, ctx: CheckpointContext) -> GovernanceDecision:
        """Evaluate, record, and raise if the decision halts the loop.

        This is what the six checkpoint sites call, so each site is one line
        and none of them contains a policy comparison of its own. A caller
        cannot accidentally evaluate without recording, or record without
        acting — which is what "one enforcement path" has to mean in practice.
        """
        decision = self.evaluate(checkpoint, ctx)
        if not decision.halts:
            return decision
        if decision.decision is Decision.CHALLENGE:
            approval_id = self._raise_obligation(decision, ctx)
            raise GovernanceChallenged(
                decision, approval_id,
                resumable=checkpoint is Checkpoint.BEFORE_FIRST_MODEL_CALL,
                completed_iterations=ctx.completed_iterations)
        self._trigger_kill_switch(decision, ctx)
        raise GovernanceStopped(decision, ctx.completed_iterations)

    # ------------------------------------------------------------------ #
    # Kill switch (§19)
    # ------------------------------------------------------------------ #
    def _kill_state(self, ctx: CheckpointContext) -> GovernanceDecision | None:
        """One non-locking read, deliberately issued fresh at every checkpoint
        rather than trusting the in-session copy of the execution.

        A kill fired by an operator arrives on a *different connection*, so the
        ORM identity map cannot see it. Under READ COMMITTED this statement
        does, which is the difference between "the engine never advances past a
        kill" being true and being merely intended (AC-09)."""
        row = self.db.execute(
            select(AgentExecution.cancel_requested, AgentExecution.status, Agent.lifecycle_status)
            .join(Agent, Agent.id == AgentExecution.agent_id)
            .where(AgentExecution.id == ctx.execution_id)
        ).first()
        if row is None:
            return None
        cancel_requested, status, lifecycle_status = row
        if not (cancel_requested or status in _KILLED_STATUSES or lifecycle_status == "SUSPENDED"):
            return None
        return GovernanceDecision(
            checkpoint=Checkpoint.BEFORE_FIRST_MODEL_CALL,  # stamped by the caller
            decision=Decision.STOP, reason_code=ReasonCode.KILL_SWITCH_ACTIVE,
            reason="Execution has been stopped by an operator intervention.",
            termination_reason="KILL_SWITCH", error_code=ErrorCode.KILL_SWITCH_ACTIVE,
        )

    def _trigger_kill_switch(self, decision: GovernanceDecision, ctx: CheckpointContext) -> None:
        """M4-4.3-FR-031 — a STOP that warrants suspension triggers the
        **existing** ``KillSwitchService``.

        Two things this deliberately does not do. It does not implement a
        suspend of its own: the cancellation and deployment-suspension logic,
        the ``RUNTIME_KILL_SWITCH_ACTIVATED`` audit event and the scope rules
        all stay in ``KillSwitchService``, and this calls into them. And it
        never *clears* a kill — there is no code path in this package that
        writes ``lifecycle_status = 'ACTIVE'`` or ``cancel_requested = False``,
        which ``test_ac08_*`` asserts over the AST rather than by inspection.

        Best-effort by construction: the loop is already stopping, and a kill
        trigger that failed must not convert a clean governance stop into an
        unhandled worker exception. The stop stands either way."""
        if decision.stop_action is StopAction.NONE:
            return
        try:
            from app.runtime.services import KillSwitchService

            scope = "AGENT" if decision.stop_action is StopAction.KILL_AGENT else "EXECUTION"
            target = ctx.agent_id if scope == "AGENT" else ctx.execution_id
            KillSwitchService(self.db).activate_system(
                organization_id=ctx.organization_id, scope=scope, target_id=target,
                reason=f"Runtime governance: {decision.reason_code.value} — {decision.reason}",
                origin="runtime_governance",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Governance-triggered kill switch failed for execution %s: %s",
                           ctx.execution_id, exc)

    # ------------------------------------------------------------------ #
    # Obligations (§4.4)
    # ------------------------------------------------------------------ #
    def _raise_obligation(self, decision: GovernanceDecision, ctx: CheckpointContext) -> uuid.UUID | None:
        """M4-4.3-FR-032 — a CHALLENGE raises its obligation through the
        **existing** approval funnel: a ``RuntimeApproval`` row, the same table
        and the same ``RuntimeApprovalService.decide`` review path every other
        approval on this platform uses. No second approval mechanism.

        ``requested_action`` differs by checkpoint, and honestly so. At
        ``BEFORE_FIRST_MODEL_CALL`` nothing has been dispatched, so this is an
        ``EXECUTION`` approval and the existing funnel's own re-queue on
        approval is exactly right — the execution resumes by starting.

        Later in the loop it is a ``POLICY_EXCEPTION`` instead, because this
        platform has no way to resume a partially-run loop, and pretending
        otherwise would be worse than saying so: re-queuing would re-run tool
        calls that already had their side effects, and parking the execution in
        ``PENDING_APPROVAL`` when nothing can move it out again would strand
        it. So the obligation is raised for a human to act on and the execution
        terminates with an explicit reason."""
        resumable = decision.checkpoint is Checkpoint.BEFORE_FIRST_MODEL_CALL
        approval = RuntimeApproval(
            organization_id=ctx.organization_id, agent_id=ctx.agent_id,
            deployment_id=ctx.deployment_id, execution_id=ctx.execution_id,
            requested_action="EXECUTION" if resumable else "POLICY_EXCEPTION",
            risk_score=ctx.risk_score, reason=decision.reason,
            matched_policies=[str(decision.policy_id)] if decision.policy_id else [],
            request_summary={
                "checkpoint": decision.checkpoint.value,
                "reason_code": decision.reason_code.value,
                "iteration": ctx.iteration,
                "resumable": resumable,
            },
        )
        self.db.add(approval)
        self.db.flush()
        return approval.id

    @staticmethod
    def _obligation(decision: Decision, reason_code: ReasonCode,
                    ctx: CheckpointContext) -> dict | None:
        if decision is not Decision.CHALLENGE:
            return None
        return {
            "type": "APPROVAL",
            "reason_code": reason_code.value,
            "tool_name": ctx.tool_name,
            "iteration": ctx.iteration,
        }

    # ------------------------------------------------------------------ #
    # Persistence & audit (§4.5, §17)
    # ------------------------------------------------------------------ #
    def _record(self, decision: GovernanceDecision, ctx: CheckpointContext) -> GovernanceDecision:
        if not self._is_material(decision):
            return decision
        try:
            self.db.add(RuntimeGovernanceDecision(
                organization_id=ctx.organization_id, execution_id=ctx.execution_id,
                trace_id=ctx.trace_id, checkpoint=decision.checkpoint.value,
                decision=decision.decision.value, reason_code=decision.reason_code.value,
                reason=decision.reason, obligation=decision.obligation,
                policy_id=decision.policy_id, iteration=ctx.iteration,
            ))
            self.db.flush()
        except Exception as exc:  # noqa: BLE001
            # A failed *record* of a decision does not change the decision. The
            # decision has already been made from domain state; losing its
            # lineage row degrades the audit trail, and the audit write below
            # is the compliance record that must not be lost. Turning this into
            # a STOP would mean a storage hiccup could halt executions that
            # governance had just allowed -- fail-closed governs *evaluation*,
            # not bookkeeping about an evaluation that already succeeded.
            logger.warning("Governance decision row could not be persisted for execution %s: %s",
                           ctx.execution_id, exc)
        self._audit(decision, ctx)
        return decision

    @staticmethod
    def _is_material(decision: GovernanceDecision) -> bool:
        """M4-4.3-FR-040 — "each *material* evaluation persists".

        Material means: anything that is not a plain ALLOW, plus the ALLOW at
        ``BEFORE_FINAL_OUTPUT``. Recording all six checkpoints on every
        iteration would write roughly sixty rows for a ten-iteration execution
        to say "nothing happened" sixty times, which buries the rows that
        matter. Keeping the terminal ALLOW means the table still carries
        positive evidence that the engine ran and permitted the result, rather
        than only evidence of refusals — an empty decision history would
        otherwise be indistinguishable from an engine that never ran."""
        return decision.halts or decision.checkpoint is Checkpoint.BEFORE_FINAL_OUTPUT

    def _audit(self, decision: GovernanceDecision, ctx: CheckpointContext) -> None:
        """§17 — reuses the platform audit trail unchanged.

        Note what goes into ``meta``: codes, the checkpoint, the policy id and
        the iteration. No payload, no tool arguments, no model output — nothing
        that could carry a secret into the audit record (§10)."""
        from app.authorization.enums import AuthorizationAuditEvent
        from app.runtime.services import _record_event

        meta = {
            "checkpoint": decision.checkpoint.value,
            "decision": decision.decision.value,
            "reason_code": decision.reason_code.value,
            "policy_id": str(decision.policy_id) if decision.policy_id else None,
            "iteration": ctx.iteration,
        }
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_POLICY_EVALUATED, None,
                      organization_id=ctx.organization_id, agent_id=ctx.agent_id,
                      deployment_id=ctx.deployment_id, execution_id=ctx.execution_id,
                      severity="INFO" if decision.allowed else "WARNING", meta=meta)
        if decision.decision in (Decision.STOP, Decision.DENY):
            _record_event(self.db, AuthorizationAuditEvent.RUNTIME_EXECUTION_STOPPED, None,
                          organization_id=ctx.organization_id, agent_id=ctx.agent_id,
                          deployment_id=ctx.deployment_id, execution_id=ctx.execution_id,
                          severity="CRITICAL", meta=meta)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _unevaluable_decision(checkpoint: Checkpoint, reason: str,
                              policy_id: uuid.UUID | None = None) -> GovernanceDecision:
        """M4-4.3-FR-020 — the fail-closed decision itself.

        It is a ``STOP`` and not a ``DENY`` because nothing was refused: the
        platform could not tell, and the governance plane's answer to "could
        not tell" is to stop. The reason code says exactly that, so an operator
        reading the lineage sees an evaluation failure rather than a rule they
        will go looking for and never find."""
        return GovernanceDecision(
            checkpoint=checkpoint, decision=Decision.STOP,
            reason_code=ReasonCode.CHECKPOINT_UNEVALUABLE, reason=reason,
            policy_id=policy_id, termination_reason="GOVERNANCE_UNEVALUABLE",
            error_code=ErrorCode.GOVERNANCE_CHECKPOINT_UNEVALUABLE,
        )

    @staticmethod
    def _error_code(decision: Decision) -> str:
        if decision is Decision.CHALLENGE:
            return ErrorCode.RUNTIME_APPROVAL_REQUIRED
        return ErrorCode.GOVERNANCE_EXECUTION_STOPPED

    @staticmethod
    def _stop_action(spec: dict) -> StopAction:
        try:
            return StopAction(spec.get("stop_action") or "NONE")
        except ValueError:
            return StopAction.NONE
