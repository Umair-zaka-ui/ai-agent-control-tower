"""The runtime governance contract (M4-4.3-FR-001, FR-002).

Deliberately dependency-light: this module imports no SQLAlchemy and no
service, so the vocabulary a checkpoint speaks can be reasoned about (and
tested) without a database. ``tests/runtime/test_runtime_governance.py``
asserts that structurally, the same way Phase 4.1 asserts it of
``app.observability.trace``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.identity.errors import ErrorCode, IdentityError


class Checkpoint(str, Enum):
    """The six points inside the model→tool→model loop at which the engine is
    consulted (SRS §8-4.3). These are *insertion points into one engine*, not
    six bespoke logics — every one of them calls the same ``evaluate()``.

    The boundary each one names, in the order a single iteration reaches them:

    ``BEFORE_FIRST_MODEL_CALL``
        Top of iteration 1, before anything has been dispatched.
    ``AFTER_MODEL_RESPONSE``
        The model has answered and its usage is known — the model actually
        used, its token spend and its latency are all facts now rather than
        intentions.
    ``BEFORE_TOOL_EXECUTION``
        Per requested tool call, before it is dispatched. The last point at
        which a specific call can be refused without side effects.
    ``AFTER_TOOL_EXECUTION``
        The batch has run and its results are in the transcript.
    ``BEFORE_NEXT_ITERATION``
        Top of iteration *n>1*. Adjacent to the end of iteration *n-1*: there
        is no code between them, so they are one boundary and one checkpoint,
        not two (see ``ToolLoopOrchestrator.run``'s own note on why the caps
        that used to be checked at the bottom of the body are checked here).
    ``BEFORE_FINAL_OUTPUT``
        The model has produced a final answer and the loop is about to return
        it.
    """

    BEFORE_FIRST_MODEL_CALL = "BEFORE_FIRST_MODEL_CALL"
    AFTER_MODEL_RESPONSE = "AFTER_MODEL_RESPONSE"
    BEFORE_TOOL_EXECUTION = "BEFORE_TOOL_EXECUTION"
    AFTER_TOOL_EXECUTION = "AFTER_TOOL_EXECUTION"
    BEFORE_NEXT_ITERATION = "BEFORE_NEXT_ITERATION"
    BEFORE_FINAL_OUTPUT = "BEFORE_FINAL_OUTPUT"


class Decision(str, Enum):
    """M4-4.3-FR-001. Four outcomes, and the distinction between the last two
    is not cosmetic:

    - ``ALLOW`` — continue.
    - ``DENY`` — refuse *this specific act* (this tool call, this model). The
      loop does not continue, because a denied act that the model requested
      cannot simply be skipped: the model would be handed a transcript that
      silently omits what it asked for.
    - ``CHALLENGE`` — do not continue on the platform's own authority; raise a
      human approval obligation through the existing funnel (§4.4).
    - ``STOP`` — halt the execution. Used for loop-safety caps, ceilings, a
      kill switch, and for a mandatory checkpoint that could not be evaluated
      (fail closed, §9).
    """

    ALLOW = "ALLOW"
    DENY = "DENY"
    CHALLENGE = "CHALLENGE"
    STOP = "STOP"


class ReasonCode(str, Enum):
    """Stable machine-readable reasons, persisted in
    ``runtime_governance_decisions.reason_code`` (VARCHAR(48)).

    Stable means: an operator's saved filter, an alert rule and a runbook may
    all name one of these, so a value here is an interface. Renaming one is a
    breaking change; adding one is not.

    The four ``LOOP_*`` codes are the pre-existing termination caps
    (Phase 5.6a.3) expressed through this contract. They keep their original
    ``termination_reason`` strings on ``agent_executions`` — see
    ``GovernanceDecision.termination_reason`` for why the two vocabularies are
    deliberately not merged.
    """

    ALLOWED = "ALLOWED"

    # --- The four generalized loop-safety caps (were inline, Phase 5.6a.3) --
    LOOP_MAX_ITERATIONS = "LOOP_MAX_ITERATIONS"
    LOOP_TOKEN_BUDGET = "LOOP_TOKEN_BUDGET"
    LOOP_WALL_CLOCK = "LOOP_WALL_CLOCK"
    LOOP_REPEATED_CALL = "LOOP_REPEATED_CALL"

    # --- Scope: the model may only use what this version froze -------------
    TOOL_NOT_BOUND = "TOOL_NOT_BOUND"

    # --- Governance constraints (M4-4.3-FR-010) ----------------------------
    MAX_EXECUTION_COST = "MAX_EXECUTION_COST"
    MIN_REMAINING_COST = "MIN_REMAINING_COST"
    MAX_TOTAL_TOKENS = "MAX_TOTAL_TOKENS"
    MAX_MODEL_CALLS = "MAX_MODEL_CALLS"
    MAX_TOOL_CALLS = "MAX_TOOL_CALLS"
    MAX_CALLS_PER_TOOL = "MAX_CALLS_PER_TOOL"
    RESTRICTED_MODEL = "RESTRICTED_MODEL"
    RESTRICTED_TOOL_CLASS = "RESTRICTED_TOOL_CLASS"
    HIGH_RISK_ACTION = "HIGH_RISK_ACTION"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    ENVIRONMENT_POLICY = "ENVIRONMENT_POLICY"
    DATA_SENSITIVITY = "DATA_SENSITIVITY"
    MAX_EXECUTION_DURATION = "MAX_EXECUTION_DURATION"

    # --- Budgets (Phase 4.4). The budget itself is accounted for in
    # `app.finops`; these are the codes the *engine* reports when a budget
    # constraint decides. Enforcement stays here, in one place.
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    BUDGET_APPROVAL_REQUIRED = "BUDGET_APPROVAL_REQUIRED"

    # --- Intervention & failure --------------------------------------------
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
    CHECKPOINT_UNEVALUABLE = "CHECKPOINT_UNEVALUABLE"


class StopAction(str, Enum):
    """What a ``STOP`` additionally *does*, beyond halting this loop
    (M4-4.3-FR-030, FR-031).

    ``NONE`` is the default and the overwhelmingly common case: halting the
    execution is the intervention. The two kill variants delegate to the
    **existing** ``KillSwitchService`` — this engine implements no suspension
    of its own, and clears nothing (§19, kill-switch dominance).
    """

    NONE = "NONE"
    KILL_EXECUTION = "KILL_EXECUTION"
    KILL_AGENT = "KILL_AGENT"


# --------------------------------------------------------------------------- #
# The decision
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GovernanceDecision:
    """M4-4.3-FR-001 — one structured answer: decision + obligation + reason.

    Frozen, because a decision that a later stage could edit is not a record
    of what was decided.

    ``termination_reason`` and ``error_code`` exist so that generalizing the
    four caps into this engine changed **no observable behaviour**. They carry
    the exact legacy values the inline caps wrote (``MAX_ITERATIONS``,
    ``TOKEN_BUDGET``, ``WALL_CLOCK``, ``REPEATED_CALL``) and raised
    (``TOOL_LOOP_LIMIT_EXCEEDED``). Keeping them as fields rather than
    deriving them from ``reason_code`` is deliberate: the two vocabularies
    have different owners and different lifetimes. ``termination_reason`` is
    the execution's terminal state, written since Phase 5.6a.3 and read by
    existing clients; ``reason_code`` is this phase's governance lineage. A
    mapping table between them would have to be maintained in lockstep with
    both; a field is simply the fact.
    """

    checkpoint: Checkpoint
    decision: Decision
    reason_code: ReasonCode
    reason: str
    obligation: dict[str, Any] | None = None
    policy_id: uuid.UUID | None = None
    termination_reason: str | None = None
    error_code: str | None = None
    stop_action: StopAction = StopAction.NONE
    # True when a *configured* policy (as opposed to a built-in platform cap)
    # produced this decision. Drives what gets persisted -- see
    # ``RuntimeGovernanceEngine._is_material``.
    from_policy: bool = False

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW

    @property
    def halts(self) -> bool:
        """Anything that is not ``ALLOW`` ends this loop. A ``DENY`` of one
        tool call is not "skip that call and carry on" — see ``Decision``."""
        return self.decision is not Decision.ALLOW

    def as_dict(self) -> dict[str, Any]:
        return {
            "checkpoint": self.checkpoint.value,
            "decision": self.decision.value,
            "reason_code": self.reason_code.value,
            "reason": self.reason,
            "obligation": self.obligation,
            "policy_id": str(self.policy_id) if self.policy_id else None,
            "termination_reason": self.termination_reason,
            "error_code": self.error_code,
            "stop_action": self.stop_action.value,
        }


def allow(checkpoint: Checkpoint) -> GovernanceDecision:
    return GovernanceDecision(
        checkpoint=checkpoint, decision=Decision.ALLOW,
        reason_code=ReasonCode.ALLOWED, reason="No governance constraint applies.",
    )


# --------------------------------------------------------------------------- #
# The evaluation input
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CheckpointContext:
    """Everything a checkpoint may read, assembled by the caller.

    Frozen and explicit rather than "here is the orchestrator, help yourself":
    a constraint that could reach back into the loop could also *change* it,
    and the engine's whole claim is that it decides rather than acts. It also
    makes the plane separation checkable — there is no telemetry handle in
    this structure to read, so a governance decision cannot depend on one.

    Every field is a fact the runtime already had. Nothing here is computed
    for the engine's benefit: costs and tokens come from
    ``PricingService``/provider usage exactly as the loop already recorded
    them (M4-4.3-FR-011 — the engine reads existing cost, it does not compute
    new cost or reserve budget; budgets are Phase 4.4).
    """

    execution_id: uuid.UUID
    organization_id: uuid.UUID
    agent_id: uuid.UUID
    iteration: int
    # Iterations *completed*, the value written to
    # ``agent_executions.loop_iterations`` if this checkpoint terminates.
    completed_iterations: int
    elapsed_seconds: float
    # Running totals across the loop so far.
    total_tokens: int = 0
    cost_amount: float = 0.0
    model_calls: int = 0
    tool_calls: int = 0
    calls_per_tool: dict[str, int] = field(default_factory=dict)
    # The configured maximum for this deployment (deployment override or the
    # platform setting) -- resolved by the caller because it already has the
    # deployment loaded.
    max_iterations: int = 0
    max_wall_clock_seconds: float = 0.0
    max_total_tokens: int = 0
    # Model identity: what this version is configured to use, and (after the
    # response) what the provider actually reported using.
    configured_model: str | None = None
    responded_model: str | None = None
    provider: str | None = None
    environment: str | None = None
    environment_id: uuid.UUID | None = None
    deployment_id: uuid.UUID | None = None
    # Per-call fields, populated only at BEFORE_TOOL_EXECUTION.
    tool_name: str | None = None
    tool_bound: bool = True
    tool_data_classification: str | None = None
    tool_class: str | None = None
    tool_call_key: str | None = None
    seen_call_keys: frozenset[str] = frozenset()
    # Agent facts used by high-risk / sensitivity constraints.
    criticality: str | None = None
    risk_score: int | None = None
    trace_id: str | None = None
    # True when a human has already APPROVED an obligation for *this*
    # execution. Set by the engine at bind time, never by the caller -- see
    # ``RuntimeGovernanceEngine.bind`` for why an approval constraint that
    # could not see its own approval is a loop rather than a control.
    approval_granted: bool = False
    # --- Budget state (Phase 4.4) ------------------------------------------
    # Stamped by the engine at bind time from `app.finops`, never supplied by
    # the loop. A HARD_LIMIT/APPROVAL_REQUIRED budget with no headroom becomes
    # a *constraint the engine evaluates*, not a second thing that can stop an
    # execution -- see `_budget_constraint` in `constraints.py`.
    budget_id: uuid.UUID | None = None
    budget_name: str | None = None
    budget_mode: str | None = None
    budget_remaining: float | None = None
    budget_currency: str = "USD"
    budget_over_threshold: bool = False


# --------------------------------------------------------------------------- #
# Control-flow signals
# --------------------------------------------------------------------------- #
class GovernanceStopped(IdentityError):
    """Raised by the orchestrator when a checkpoint returns ``DENY``/``STOP``.

    An ``IdentityError`` subclass on purpose: ``ExecutionWorkerService._execute``
    already has one ``except IdentityError`` arm that records the terminal
    state and applies the retry policy, and a governance stop wants exactly
    that treatment. Introducing a second, parallel failure path through the
    worker would recreate — one layer up — the very duplication this phase
    exists to remove from the loop.
    """

    def __init__(self, decision: GovernanceDecision, completed_iterations: int = 0) -> None:
        super().__init__(decision.error_code or ErrorCode.GOVERNANCE_EXECUTION_STOPPED, decision.reason)
        self.decision = decision
        # The value written to ``agent_executions.loop_iterations``. Carried on
        # the exception rather than re-derived by the handler, because the rule
        # ("the iteration that finished" at a boundary checkpoint, "the one in
        # progress" mid-loop) is the checkpoint's own knowledge -- a handler
        # re-deriving it is a second copy that can drift from the first.
        self.completed_iterations = completed_iterations


class GovernanceChallenged(IdentityError):
    """Raised when a checkpoint returns ``CHALLENGE``.

    Distinct from ``GovernanceStopped`` because the outcome is different in
    kind: the execution is not failing, it is *waiting for a human*. The
    worker parks it in ``PENDING_APPROVAL`` rather than applying the retry
    policy — an automatic retry of something that requires an approval would
    be the platform overruling the obligation it just raised.

    ``resumable`` is the honest part. It is true only at
    ``BEFORE_FIRST_MODEL_CALL``, where nothing has been dispatched and the
    existing approval funnel's re-queue genuinely resumes the work. Later in
    the loop it is false, because this platform cannot resume a partially-run
    loop: re-running would repeat tool calls that already had their side
    effects. A non-resumable challenge still raises its obligation for a human
    — it just terminates the execution instead of parking it in a state
    nothing can move it out of.
    """

    def __init__(self, decision: GovernanceDecision, approval_id: uuid.UUID | None = None,
                 *, resumable: bool = False, completed_iterations: int = 0) -> None:
        super().__init__(ErrorCode.RUNTIME_APPROVAL_REQUIRED, decision.reason)
        self.decision = decision
        self.approval_id = approval_id
        self.resumable = resumable
        self.completed_iterations = completed_iterations
