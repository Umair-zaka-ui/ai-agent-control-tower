"""The constraint set (M4-4.3-FR-010..013).

Two families live here and the difference between them is the whole point of
this phase:

**Built-in caps** (``_cap_*``) are the four loop-safety limits Phase 5.6a.3
enforced with inline ``if`` statements inside ``ToolLoopOrchestrator.run``,
plus the frozen-snapshot tool-scope check. They are platform behaviour, always
evaluated, not configurable per tenant beyond the deployment override that
already existed (``runtime_limits.maximum_loop_iterations``) — and they now
reach the loop only through this engine. They carry ``termination_reason`` and
``error_code`` so that the values written to ``agent_executions`` and the
exception raised are byte-identical to what the inline checks produced.

**Policy constraints** (``_c_*``) are the richer, configurable rules this
phase adds, read from ``runtime_governance_policies.constraints``.

Both are evaluated by the same ``evaluate()`` call at the same checkpoints.
The caps are not "the old system, still running" — they are constraints in
this one, and ``test_ac02_*`` proves no comparison against a cap survives
anywhere else.

**Evaluation order is load-bearing, not incidental.** Where two caps can breach
on the same turn, the order below reproduces exactly which one the pre-4.3 loop
reported. See ``BUILTIN_CAPS`` at the foot of this module for the derivation.
"""

from __future__ import annotations

from typing import Any, Callable

from app.identity.errors import ErrorCode
from app.runtime.governance.contract import (
    Checkpoint,
    CheckpointContext,
    Decision,
    GovernanceDecision,
    ReasonCode,
)

# A constraint's answer: nothing (this constraint does not object), or a
# decision to be attributed to whichever policy supplied the specification.
Verdict = tuple[Decision, ReasonCode, str]
PolicyConstraint = Callable[[CheckpointContext, dict], "Verdict | None"]
BuiltinCap = Callable[[CheckpointContext], "GovernanceDecision | None"]


# --------------------------------------------------------------------------- #
# Built-in caps — the four generalized loop-safety limits
# --------------------------------------------------------------------------- #
def _cap(reason_code: ReasonCode, termination_reason: str, message: str,
         error_code: str = ErrorCode.TOOL_LOOP_LIMIT_EXCEEDED) -> GovernanceDecision:
    """The ``checkpoint`` here is a placeholder: a cap can be reached from more
    than one checkpoint, and ``RuntimeGovernanceEngine.evaluate`` stamps the
    real one onto every decision it returns. Having the constraint guess would
    make the recorded checkpoint depend on a re-derivation of the caller's own
    state — the caller knows, so the caller says."""
    return GovernanceDecision(
        checkpoint=Checkpoint.BEFORE_NEXT_ITERATION,
        decision=Decision.STOP, reason_code=reason_code, reason=message,
        termination_reason=termination_reason, error_code=error_code,
    )


def _cap_max_iterations(ctx: CheckpointContext) -> GovernanceDecision | None:
    """``ACT-TLX-FR-041``, was: ``if iteration > max_iterations`` at the top of
    the loop body."""
    if ctx.iteration > ctx.max_iterations:
        return _cap(ReasonCode.LOOP_MAX_ITERATIONS, "MAX_ITERATIONS",
                    f"Tool loop exceeded the maximum of {ctx.max_iterations} iterations.")
    return None


def _cap_wall_clock(ctx: CheckpointContext) -> GovernanceDecision | None:
    """``ACT-TLX-FR-042``, was: two identical ``if`` statements — one at the top
    of the body and one after tool execution. Now one constraint reached from
    two checkpoints, which is the same thing minus the copy."""
    if ctx.elapsed_seconds > ctx.max_wall_clock_seconds:
        return _cap(ReasonCode.LOOP_WALL_CLOCK, "WALL_CLOCK",
                    "Tool loop exceeded its wall-clock budget.")
    return None


def _cap_token_budget(ctx: CheckpointContext) -> GovernanceDecision | None:
    """``ACT-TLX-FR-043``, was: ``if total_sum > TOOL_LOOP_MAX_TOTAL_TOKENS``
    at the bottom of the body."""
    if ctx.total_tokens > ctx.max_total_tokens:
        return _cap(ReasonCode.LOOP_TOKEN_BUDGET, "TOKEN_BUDGET",
                    "Tool loop exceeded its token budget.")
    return None


def _cap_tool_bound(ctx: CheckpointContext) -> GovernanceDecision | None:
    """``ACT-TLX-FR-045`` — the model may only name a tool this *published
    version* froze into its ``tools_snapshot``. Not a governance policy and
    not configurable: it is the scope boundary of the execution itself, which
    is why it is checked before any policy constraint at this checkpoint.
    """
    if not ctx.tool_bound:
        return GovernanceDecision(
            checkpoint=Checkpoint.BEFORE_TOOL_EXECUTION, decision=Decision.DENY,
            reason_code=ReasonCode.TOOL_NOT_BOUND,
            reason=f"Tool '{ctx.tool_name}' is not bound to this version.",
            termination_reason="TOOL_DENIED", error_code=ErrorCode.TOOL_NOT_BOUND_TO_VERSION,
        )
    return None


def _cap_repeated_call(ctx: CheckpointContext) -> GovernanceDecision | None:
    """``ACT-TLX-FR-048`` — the same (tool, canonicalized arguments) pair
    reaches the same outcome every time, so a repeat is non-productive by
    definition and is stopped *before* the duplicate is issued."""
    if ctx.tool_call_key is not None and ctx.tool_call_key in ctx.seen_call_keys:
        return GovernanceDecision(
            checkpoint=Checkpoint.BEFORE_TOOL_EXECUTION, decision=Decision.STOP,
            reason_code=ReasonCode.LOOP_REPEATED_CALL,
            reason=f"Tool '{ctx.tool_name}' was called again with identical arguments.",
            termination_reason="REPEATED_CALL", error_code=ErrorCode.TOOL_LOOP_LIMIT_EXCEEDED,
        )
    return None


# --------------------------------------------------------------------------- #
# Policy constraints
# --------------------------------------------------------------------------- #
def _number(spec: dict, key: str) -> float | None:
    value = spec.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _names(spec: dict, key: str) -> set[str]:
    value = spec.get(key)
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {str(item) for item in value}


def _c_max_execution_cost(ctx: CheckpointContext, spec: dict) -> Verdict | None:
    """Reads ``cost_amount`` the loop has *already* accounted through
    ``PricingService`` (M4-4.3-FR-011). Nothing is computed or reserved here —
    budgets and reservations are Phase 4.4's job, and this constraint will
    consult them when they exist."""
    ceiling = _number(spec, "max_execution_cost")
    if ceiling is not None and ctx.cost_amount >= ceiling:
        return (Decision.STOP, ReasonCode.MAX_EXECUTION_COST,
                f"Execution cost {ctx.cost_amount:.6f} reached the governed ceiling of {ceiling:.6f}.")
    return None


def _c_min_remaining_cost(ctx: CheckpointContext, spec: dict) -> Verdict | None:
    """The headroom rule, and the one that actually keeps spend *within* a
    ceiling rather than just noticing afterwards that it was passed.

    A ceiling checked after the fact can only ever report an overshoot: the
    iteration that crossed it has already been paid for. This constraint stops
    the loop while at least ``min_remaining_cost`` of headroom remains, so the
    next iteration — whose cost is unknowable in advance — is never dispatched
    against a budget that could not absorb it."""
    ceiling = _number(spec, "max_execution_cost")
    floor = _number(spec, "min_remaining_cost")
    if ceiling is None or floor is None:
        return None
    remaining = ceiling - ctx.cost_amount
    if remaining < floor:
        return (Decision.STOP, ReasonCode.MIN_REMAINING_COST,
                f"Remaining cost headroom {remaining:.6f} is below the governed minimum "
                f"of {floor:.6f}; a further iteration could exceed the ceiling.")
    return None


def _c_max_total_tokens(ctx: CheckpointContext, spec: dict) -> Verdict | None:
    ceiling = _number(spec, "max_total_tokens")
    if ceiling is not None and ctx.total_tokens >= ceiling:
        return (Decision.STOP, ReasonCode.MAX_TOTAL_TOKENS,
                f"Execution used {ctx.total_tokens} tokens, reaching the governed "
                f"maximum of {int(ceiling)}.")
    return None


def _c_max_model_calls(ctx: CheckpointContext, spec: dict) -> Verdict | None:
    ceiling = _number(spec, "max_model_calls")
    if ceiling is not None and ctx.model_calls >= ceiling:
        return (Decision.STOP, ReasonCode.MAX_MODEL_CALLS,
                f"Execution made {ctx.model_calls} model calls, reaching the governed "
                f"maximum of {int(ceiling)}.")
    return None


def _c_max_tool_calls(ctx: CheckpointContext, spec: dict) -> Verdict | None:
    ceiling = _number(spec, "max_tool_calls")
    if ceiling is not None and ctx.tool_calls >= ceiling:
        return (Decision.STOP, ReasonCode.MAX_TOOL_CALLS,
                f"Execution made {ctx.tool_calls} tool calls, reaching the governed "
                f"maximum of {int(ceiling)}.")
    return None


def _c_max_calls_per_tool(ctx: CheckpointContext, spec: dict) -> Verdict | None:
    """``max_calls_per_tool`` is either a single number applying to every tool
    or a per-tool mapping. Both shapes exist because both requests are real: a
    blanket "no tool more than three times" and "``send_email`` exactly once".
    """
    limits = spec.get("max_calls_per_tool")
    if limits is None or ctx.tool_name is None:
        return None
    if isinstance(limits, dict):
        ceiling = _number(limits, ctx.tool_name)
    else:
        ceiling = _number(spec, "max_calls_per_tool")
    if ceiling is None:
        return None
    used = ctx.calls_per_tool.get(ctx.tool_name, 0)
    if used >= ceiling:
        return (Decision.DENY, ReasonCode.MAX_CALLS_PER_TOOL,
                f"Tool '{ctx.tool_name}' has already been called {used} time(s), "
                f"reaching its governed maximum of {int(ceiling)}.")
    return None


def _c_restricted_model(ctx: CheckpointContext, spec: dict) -> Verdict | None:
    """Enforced **around** the model, at two different moments and for two
    different reasons (M4-4.3-FR-012, §10).

    ``configured_model`` is checked before the call: this version is not
    allowed to use that model, so the call is never made. ``responded_model``
    is checked after: the model that actually answered is the fact, and a
    provider that silently substituted or aliased a model must not be able to
    launder a restricted one past a check made only on intent. Neither check
    asks the model to comply with anything — the loop stops either way."""
    denied = _names(spec, "restricted_models")
    allowed = _names(spec, "allowed_models")
    for model in (ctx.responded_model, ctx.configured_model):
        if not model:
            continue
        if model in denied:
            return (Decision.STOP, ReasonCode.RESTRICTED_MODEL,
                    f"Model '{model}' is restricted by runtime governance policy.")
        if allowed and model not in allowed:
            return (Decision.STOP, ReasonCode.RESTRICTED_MODEL,
                    f"Model '{model}' is not on this policy's allowed-model list.")
    return None


def _c_restricted_tool_class(ctx: CheckpointContext, spec: dict) -> Verdict | None:
    denied = _names(spec, "restricted_tool_classes")
    if ctx.tool_class and ctx.tool_class in denied:
        return (Decision.DENY, ReasonCode.RESTRICTED_TOOL_CLASS,
                f"Tool '{ctx.tool_name}' is of restricted class '{ctx.tool_class}'.")
    denied_tools = _names(spec, "restricted_tools")
    if ctx.tool_name and ctx.tool_name in denied_tools:
        return (Decision.DENY, ReasonCode.RESTRICTED_TOOL_CLASS,
                f"Tool '{ctx.tool_name}' is restricted by runtime governance policy.")
    return None


def _c_data_sensitivity(ctx: CheckpointContext, spec: dict) -> Verdict | None:
    """Reuses the *existing* classification — ``Tool.data_classification``,
    the same column Phase 3.2's ``check_allowed_data_classifications`` reads at
    deploy time (M4-4.3-FR-013). No new taxonomy is invented here; a tool that
    a deployment-time policy would have rejected is rejected at runtime by the
    same fact about the same column."""
    if ctx.tool_data_classification is None:
        return None
    denied = _names(spec, "restricted_data_classifications")
    allowed = _names(spec, "allowed_data_classifications")
    if ctx.tool_data_classification in denied or (
            allowed and ctx.tool_data_classification not in allowed):
        return (Decision.DENY, ReasonCode.DATA_SENSITIVITY,
                f"Tool '{ctx.tool_name}' handles {ctx.tool_data_classification} data, "
                f"which this policy does not permit at runtime.")
    return None


def _c_environment_policy(ctx: CheckpointContext, spec: dict) -> Verdict | None:
    """``prohibited_environments`` — the same key
    ``RuntimePolicyService.evaluate`` and ``app.runtime.environment.policy
    .check_prohibited`` already read, deliberately reused rather than
    paralleled (M4-4.3-FR-013). A version barred from an environment at
    admission stays barred inside the loop."""
    prohibited = _names(spec, "prohibited_environments")
    if ctx.environment and ctx.environment in prohibited:
        return (Decision.STOP, ReasonCode.ENVIRONMENT_POLICY,
                f"Runtime governance policy prohibits execution in '{ctx.environment}'.")
    return None


def _c_max_execution_duration(ctx: CheckpointContext, spec: dict) -> Verdict | None:
    ceiling = _number(spec, "max_execution_duration_seconds")
    if ceiling is not None and ctx.elapsed_seconds > ceiling:
        return (Decision.STOP, ReasonCode.MAX_EXECUTION_DURATION,
                f"Execution ran for {ctx.elapsed_seconds:.1f}s, exceeding the governed "
                f"maximum of {ceiling:.1f}s.")
    return None


def _c_high_risk_action(ctx: CheckpointContext, spec: dict) -> Verdict | None:
    """A named high-risk tool raises an approval obligation rather than a
    refusal: the platform's position is not that the action is forbidden but
    that a human should own it (M4-4.3-FR-030)."""
    if ctx.tool_name and ctx.tool_name in _names(spec, "high_risk_actions"):
        return (Decision.CHALLENGE, ReasonCode.HIGH_RISK_ACTION,
                f"Tool '{ctx.tool_name}' is a governed high-risk action and requires approval.")
    return None


def _c_requires_approval(ctx: CheckpointContext, spec: dict) -> Verdict | None:
    """A policy that requires approval for the execution as a whole. Raised at
    the *first* checkpoint, before anything has been dispatched — an approval
    obligation discovered halfway through a loop can only ever be honoured
    partially (see ``RuntimeGovernanceEngine._raise_obligation``)."""
    if spec.get("requires_approval") is True and not ctx.approval_granted:
        return (Decision.CHALLENGE, ReasonCode.APPROVAL_REQUIRED,
                "Runtime governance policy requires human approval for this execution.")
    return None


def _c_criticality_requires_approval(ctx: CheckpointContext, spec: dict) -> Verdict | None:
    levels = _names(spec, "requires_approval_criticality")
    if ctx.criticality and ctx.criticality in levels and not ctx.approval_granted:
        return (Decision.CHALLENGE, ReasonCode.APPROVAL_REQUIRED,
                f"A {ctx.criticality} agent requires human approval under this policy.")
    return None


# --------------------------------------------------------------------------- #
# The checkpoint → constraint mapping
# --------------------------------------------------------------------------- #
#
# **Why ``BEFORE_NEXT_ITERATION`` lists the caps in this order.** Before this
# phase, one continuing iteration reached four inline checks in this sequence:
#
#     [end of iteration n]     wall-clock      -> WALL_CLOCK,     iterations = n
#     [end of iteration n]     token budget    -> TOKEN_BUDGET,   iterations = n
#     [top of iteration n+1]   iteration cap   -> MAX_ITERATIONS, iterations = n
#     [top of iteration n+1]   wall-clock      -> WALL_CLOCK,     iterations = n
#
# Nothing at all runs between the second and third of those, so they are one
# boundary rather than two, and the fourth is a re-check of the first. Folding
# them into a single checkpoint therefore changes no outcome *provided the
# order is preserved* -- which matters only in the corner case where two caps
# breach on the same turn, and that corner case is exactly the kind of thing a
# refactor silently inverts. Hence: wall-clock, tokens, iterations.
#
# Every cap here reports ``completed_iterations`` (= iteration - 1), which is
# the same value all four inline checks wrote.
BUILTIN_CAPS: dict[Checkpoint, tuple[BuiltinCap, ...]] = {
    Checkpoint.BEFORE_FIRST_MODEL_CALL: (_cap_max_iterations, _cap_wall_clock),
    Checkpoint.AFTER_MODEL_RESPONSE: (),
    Checkpoint.BEFORE_TOOL_EXECUTION: (_cap_tool_bound, _cap_repeated_call),
    Checkpoint.AFTER_TOOL_EXECUTION: (),
    Checkpoint.BEFORE_NEXT_ITERATION: (_cap_wall_clock, _cap_token_budget, _cap_max_iterations),
    Checkpoint.BEFORE_FINAL_OUTPUT: (),
}

POLICY_CONSTRAINTS: dict[Checkpoint, tuple[PolicyConstraint, ...]] = {
    Checkpoint.BEFORE_FIRST_MODEL_CALL: (
        _c_environment_policy, _c_restricted_model, _c_max_execution_cost,
        _c_requires_approval, _c_criticality_requires_approval,
    ),
    Checkpoint.AFTER_MODEL_RESPONSE: (
        _c_restricted_model, _c_max_total_tokens, _c_max_execution_cost,
        _c_max_execution_duration,
    ),
    Checkpoint.BEFORE_TOOL_EXECUTION: (
        _c_restricted_tool_class, _c_data_sensitivity, _c_max_tool_calls,
        _c_max_calls_per_tool, _c_min_remaining_cost, _c_high_risk_action,
    ),
    Checkpoint.AFTER_TOOL_EXECUTION: (
        _c_max_execution_cost, _c_max_execution_duration,
    ),
    Checkpoint.BEFORE_NEXT_ITERATION: (
        _c_max_execution_cost, _c_min_remaining_cost, _c_max_total_tokens,
        _c_max_model_calls, _c_max_execution_duration, _c_restricted_model,
    ),
    Checkpoint.BEFORE_FINAL_OUTPUT: (
        _c_max_execution_cost, _c_max_execution_duration,
    ),
}

# Every constraint key a policy may legitimately declare. Used by the policy
# API to reject a misspelled key loudly (GOVERNANCE_POLICY_INVALID) instead of
# storing a rule that silently never fires -- a governance control that does
# nothing is worse than one that is absent, because someone believes it works.
KNOWN_CONSTRAINT_KEYS: frozenset[str] = frozenset({
    "max_execution_cost", "min_remaining_cost", "max_total_tokens",
    "max_model_calls", "max_tool_calls", "max_calls_per_tool",
    "restricted_models", "allowed_models", "restricted_tools",
    "restricted_tool_classes", "restricted_data_classifications",
    "allowed_data_classifications", "prohibited_environments",
    "max_execution_duration_seconds", "high_risk_actions", "requires_approval",
    "requires_approval_criticality", "stop_action",
})

_NUMERIC_KEYS = frozenset({
    "max_execution_cost", "min_remaining_cost", "max_total_tokens",
    "max_model_calls", "max_tool_calls", "max_execution_duration_seconds",
})
_LIST_KEYS = frozenset({
    "restricted_models", "allowed_models", "restricted_tools",
    "restricted_tool_classes", "restricted_data_classifications",
    "allowed_data_classifications", "prohibited_environments",
    "high_risk_actions", "requires_approval_criticality",
})


def validate_constraints(spec: Any) -> list[str]:
    """Returns human-readable problems with a proposed constraint document;
    an empty list means it is well formed. Kept here, next to the constraints
    themselves, so a new constraint cannot be added without its validation
    being one screen away."""
    problems: list[str] = []
    if not isinstance(spec, dict):
        return ["constraints must be an object."]
    for key, value in spec.items():
        if key not in KNOWN_CONSTRAINT_KEYS:
            problems.append(f"Unknown constraint '{key}'.")
            continue
        if key in _NUMERIC_KEYS:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                problems.append(f"Constraint '{key}' must be a number.")
            elif value < 0:
                problems.append(f"Constraint '{key}' must not be negative.")
        elif key in _LIST_KEYS:
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                problems.append(f"Constraint '{key}' must be a list of strings.")
        elif key == "requires_approval":
            if not isinstance(value, bool):
                problems.append("Constraint 'requires_approval' must be a boolean.")
        elif key == "max_calls_per_tool":
            ok = (isinstance(value, int) and not isinstance(value, bool) and value >= 0) or (
                isinstance(value, dict)
                and all(isinstance(k, str) for k in value)
                and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0
                        for v in value.values())
            )
            if not ok:
                problems.append(
                    "Constraint 'max_calls_per_tool' must be a non-negative integer or a "
                    "mapping of tool name to non-negative integer.")
        elif key == "stop_action":
            if value not in ("NONE", "KILL_EXECUTION", "KILL_AGENT"):
                problems.append(
                    "Constraint 'stop_action' must be one of NONE, KILL_EXECUTION, KILL_AGENT.")
    return problems
