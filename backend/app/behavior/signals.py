"""The deterministic signal rules (M4-4.5-FR-001, FR-002, FR-010).

**Every rule in this module is arithmetic over a window.** There is no model,
no training, no learned threshold, and no score whose derivation cannot be
written on a whiteboard. That is not a stylistic preference — §4.5 forbids
opaque scoring outright, and the reason is worth stating once:

    "This agent is 0.87 anomalous" is unauditable, unappealable and
    ungovernable. A regulated tenant cannot act on it, cannot dispute it, and
    cannot show a regulator why it fired. "Tool `send_email` failed 34% of 118
    calls this week against a 3% baseline over the previous four weeks" is all
    three.

So every rule returns not just a state but the numbers that produced it, and
the finding carries them. A signal that cannot explain itself is not emitted.

Each rule is a pure function of ``(candidate, baseline, thresholds)`` — it takes
no session, reads no clock, and touches nothing global, which is what makes
"same data ⇒ same finding" testable rather than aspirational.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.behavior.states import SignalState

# --------------------------------------------------------------------------- #
# Thresholds
# --------------------------------------------------------------------------- #
# Platform defaults, overridable per environment through
# ``Environment.policy["behavioral_thresholds"]`` -- the same
# policy-carries-the-override pattern Phase 3.3 established for preflight and
# Phase 3.5 for canary health, rather than a third configuration mechanism.
#
# The absolute thresholds are deliberately *looser* than 3.5's canary
# equivalents. A canary is a candidate asking for more traffic and should be
# judged strictly; a production agent that has been running for months is being
# watched for *change*, and flagging it at a 5% error rate it has always had
# would produce a permanent alarm nobody reads.
DEFAULT_THRESHOLDS: dict[str, float] = {
    # --- absolute rates -------------------------------------------------- #
    "degraded_error_rate": 0.10,
    "anomalous_error_rate": 0.30,
    "degraded_denial_rate": 0.10,
    "anomalous_denial_rate": 0.30,
    "degraded_tool_failure_rate": 0.15,
    "anomalous_tool_failure_rate": 0.40,
    # --- relative drift, as a ratio against the baseline ------------------ #
    # 1.5 = "50% worse than it used to be". Ratios rather than absolute
    # deltas because latency and cost have no universal scale: 200ms is a
    # catastrophe for one agent and excellent for another.
    "degraded_drift_ratio": 1.5,
    "anomalous_drift_ratio": 3.0,
    # Baseline error-rate divergence in absolute percentage points. Narrower
    # than the absolute threshold on purpose -- the same reasoning Phase 3.5
    # documented for `baseline_error_rate_margin`: if the margin were as wide
    # as the absolute rule, it could never fire on its own.
    "baseline_error_rate_margin": 0.05,
    # --- loop behaviour --------------------------------------------------- #
    # Fraction of executions terminating on a loop-safety cap rather than
    # completing. A model that has started looping is behaving differently
    # even when every execution still "succeeds" from the caller's view.
    "degraded_cap_termination_rate": 0.10,
    "anomalous_cap_termination_rate": 0.25,
    # --- sufficiency ------------------------------------------------------ #
    "min_samples": 20.0,
    "min_baseline_samples": 20.0,
    "min_tool_calls": 10.0,
}

# Termination reasons that mean a loop-safety cap fired rather than the model
# finishing. Read from Phase 5.6a.3's own vocabulary plus Phase 4.3's, never a
# parallel list -- `test_ac05_*` asserts these are the values the loop writes.
CAP_TERMINATIONS: frozenset[str] = frozenset({
    "MAX_ITERATIONS", "TOKEN_BUDGET", "WALL_CLOCK", "REPEATED_CALL",
})


def thresholds_for(policy: dict | None) -> dict[str, float]:
    """Environment overrides merged over the platform defaults. An unknown key
    is ignored rather than accepted: a misspelled threshold that silently did
    nothing would be a control someone believes is configured."""
    merged = dict(DEFAULT_THRESHOLDS)
    overrides = (policy or {}).get("behavioral_thresholds") or {}
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            if key in DEFAULT_THRESHOLDS and isinstance(value, (int, float)):
                merged[key] = float(value)
    return merged


# --------------------------------------------------------------------------- #
# The window
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class WindowMetrics:
    """Everything measured about one agent over one window.

    Computed once and handed to every rule, rather than each rule issuing its
    own query: seven signals over two windows would otherwise be fourteen
    aggregations of the same rows."""

    sample_count: int = 0
    succeeded: int = 0
    failed: int = 0
    timed_out: int = 0
    denied: int = 0
    avg_duration_ms: float | None = None
    p95_duration_ms: float | None = None
    avg_cost: float | None = None
    total_cost: float = 0.0
    avg_loop_iterations: float | None = None
    cap_terminations: int = 0
    termination_reasons: dict[str, int] = field(default_factory=dict)
    error_codes: dict[str, int] = field(default_factory=dict)
    models: dict[str, int] = field(default_factory=dict)
    providers: dict[str, int] = field(default_factory=dict)
    # tool id -> (calls, failures, tool name)
    tools: dict[str, tuple[int, int, str]] = field(default_factory=dict)

    @property
    def error_rate(self) -> float:
        return (self.failed + self.timed_out) / self.sample_count if self.sample_count else 0.0

    @property
    def denial_rate(self) -> float:
        return self.denied / self.sample_count if self.sample_count else 0.0

    @property
    def cap_termination_rate(self) -> float:
        return self.cap_terminations / self.sample_count if self.sample_count else 0.0

    @property
    def tool_call_count(self) -> int:
        return sum(calls for calls, _f, _n in self.tools.values())

    @property
    def tool_failure_count(self) -> int:
        return sum(failures for _c, failures, _n in self.tools.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "sample_count": self.sample_count,
            "succeeded": self.succeeded, "failed": self.failed,
            "timed_out": self.timed_out, "denied": self.denied,
            "error_rate": round(self.error_rate, 6),
            "denial_rate": round(self.denial_rate, 6),
            "avg_duration_ms": self.avg_duration_ms,
            "p95_duration_ms": self.p95_duration_ms,
            "avg_cost": self.avg_cost, "total_cost": round(self.total_cost, 8),
            "avg_loop_iterations": self.avg_loop_iterations,
            "cap_termination_rate": round(self.cap_termination_rate, 6),
            "termination_reasons": dict(self.termination_reasons),
            "error_codes": dict(self.error_codes),
        }


@dataclass(frozen=True)
class SignalResult:
    """One rule's verdict, carrying everything needed to explain it.

    ``observed``/``threshold``/``baseline`` are the three numbers an operator
    checks the arithmetic with, and ``reason`` states the crossing in words.
    A rule that cannot fill these in returns ``NORMAL`` rather than guessing —
    which is the structural reason no unexplainable finding can exist."""

    signal_type: str
    metric: str
    state: SignalState
    reason: str
    observed: float | None = None
    threshold: float | None = None
    baseline: float | None = None
    attribution: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)


Rule = Callable[[WindowMetrics, "WindowMetrics | None", dict], SignalResult]


def _normal(signal_type: str, metric: str, reason: str,
            observed: float | None = None) -> SignalResult:
    return SignalResult(signal_type=signal_type, metric=metric,
                        state=SignalState.NORMAL, reason=reason, observed=observed)


def _rate_rule(signal_type: str, metric: str, label: str, observed: float,
               baseline: float | None, thresholds: dict, *,
               degraded_key: str, anomalous_key: str,
               attribution: dict | None = None,
               evidence: dict | None = None) -> SignalResult:
    """The shared shape for every rate signal: absolute thresholds first, then
    the baseline. Same order as Phase 3.5's ``_classify`` then
    ``_apply_baseline`` — a candidate that is bad in absolute terms is bad
    whatever it used to be, and a candidate that is fine in absolute terms can
    still have moved."""
    attribution = attribution or {}
    evidence = evidence or {}
    anomalous, degraded = thresholds[anomalous_key], thresholds[degraded_key]

    if observed >= anomalous:
        return SignalResult(
            signal_type=signal_type, metric=metric, state=SignalState.ANOMALOUS,
            reason=(f"{label} {observed:.1%} is at or above the anomalous threshold "
                    f"{anomalous:.1%}."),
            observed=observed, threshold=anomalous, baseline=baseline,
            attribution=attribution, evidence=evidence)
    if observed >= degraded:
        return SignalResult(
            signal_type=signal_type, metric=metric, state=SignalState.DEGRADED,
            reason=(f"{label} {observed:.1%} is at or above the degraded threshold "
                    f"{degraded:.1%}."),
            observed=observed, threshold=degraded, baseline=baseline,
            attribution=attribution, evidence=evidence)

    if baseline is not None:
        margin = thresholds["baseline_error_rate_margin"]
        if observed - baseline >= margin:
            return SignalResult(
                signal_type=signal_type, metric=metric, state=SignalState.DEGRADED,
                reason=(f"{label} {observed:.1%} is {observed - baseline:.1%} above its "
                        f"baseline of {baseline:.1%}, exceeding the {margin:.1%} margin — "
                        f"within absolute thresholds, but measurably changed."),
                observed=observed, threshold=margin, baseline=baseline,
                attribution=attribution, evidence=evidence)

    return _normal(signal_type, metric,
                   f"{label} {observed:.1%} is within all thresholds.", observed)


def _drift_rule(signal_type: str, metric: str, label: str, unit: str,
                observed: float | None, baseline: float | None,
                thresholds: dict, *, attribution: dict | None = None) -> SignalResult:
    """Ratio drift against a baseline. Used for latency and cost, which have no
    universal scale — 200ms is a disaster for one agent and excellent for
    another, so only the *change* is meaningful.

    Drift in **either direction** is reported. A metric that halves overnight
    is not good news to be filtered out; it usually means the agent stopped
    doing something it used to do. This is where a behavioral signal genuinely
    differs from a health signal, which only cares about getting worse."""
    attribution = attribution or {}
    if observed is None or baseline is None or baseline <= 0:
        return SignalResult(
            signal_type=signal_type, metric=metric, state=SignalState.NORMAL,
            reason=("No baseline available for comparison; drift is only meaningful "
                    "against a prior window."),
            observed=observed, baseline=baseline, attribution=attribution)

    ratio = observed / baseline
    inverse = baseline / observed if observed > 0 else float("inf")
    worst = max(ratio, inverse)
    direction = "increased" if ratio >= 1 else "decreased"

    for key, state in (("anomalous_drift_ratio", SignalState.ANOMALOUS),
                       ("degraded_drift_ratio", SignalState.DEGRADED)):
        if worst >= thresholds[key]:
            return SignalResult(
                signal_type=signal_type, metric=metric, state=state,
                reason=(f"{label} {direction} from {baseline:,.2f}{unit} to "
                        f"{observed:,.2f}{unit} — a {worst:.2f}x change, at or above the "
                        f"{thresholds[key]:.2f}x threshold."),
                observed=observed, threshold=thresholds[key], baseline=baseline,
                attribution=attribution,
                evidence={"ratio": round(ratio, 6), "direction": direction})

    return SignalResult(
        signal_type=signal_type, metric=metric, state=SignalState.NORMAL,
        reason=(f"{label} {observed:,.2f}{unit} against a baseline of "
                f"{baseline:,.2f}{unit} — a {worst:.2f}x change, within thresholds."),
        observed=observed, threshold=thresholds["degraded_drift_ratio"], baseline=baseline,
        attribution=attribution)


def _dominant(counts: dict[str, int]) -> dict[str, Any]:
    """Attribution for a signal whose cause is one value among many. Names the
    most frequent contributor and its share, because "errors are up" is far
    less useful than "errors are up and 82% of them are RATE_LIMITED"."""
    if not counts:
        return {}
    total = sum(counts.values()) or 1
    key, count = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
    return {"dominant": key, "dominant_count": count,
            "dominant_share": round(count / total, 4), "breakdown": dict(counts)}


# --------------------------------------------------------------------------- #
# The rules
# --------------------------------------------------------------------------- #
def error_rate_shift(candidate: WindowMetrics, baseline: WindowMetrics | None,
                     thresholds: dict) -> SignalResult:
    attribution: dict[str, Any] = {}
    if candidate.error_codes:
        attribution["error_code"] = _dominant(candidate.error_codes)
    if candidate.models:
        attribution["model"] = _dominant(candidate.models)
    if candidate.providers:
        attribution["provider"] = _dominant(candidate.providers)
    return _rate_rule(
        "error_rate_shift", "error_rate", "Error rate", candidate.error_rate,
        baseline.error_rate if baseline else None, thresholds,
        degraded_key="degraded_error_rate", anomalous_key="anomalous_error_rate",
        attribution=attribution,
        evidence={"failed": candidate.failed, "timed_out": candidate.timed_out,
                  "sample_count": candidate.sample_count})


def policy_denial_surge(candidate: WindowMetrics, baseline: WindowMetrics | None,
                        thresholds: dict) -> SignalResult:
    return _rate_rule(
        "policy_denial_surge", "denial_rate", "Policy-denial rate", candidate.denial_rate,
        baseline.denial_rate if baseline else None, thresholds,
        degraded_key="degraded_denial_rate", anomalous_key="anomalous_denial_rate",
        evidence={"denied": candidate.denied, "sample_count": candidate.sample_count})


def latency_drift(candidate: WindowMetrics, baseline: WindowMetrics | None,
                  thresholds: dict) -> SignalResult:
    attribution = {}
    if candidate.models:
        attribution["model"] = _dominant(candidate.models)
    if candidate.providers:
        attribution["provider"] = _dominant(candidate.providers)
    return _drift_rule(
        "latency_drift", "p95_duration_ms", "p95 latency", "ms",
        candidate.p95_duration_ms, baseline.p95_duration_ms if baseline else None,
        thresholds, attribution=attribution)


def cost_drift(candidate: WindowMetrics, baseline: WindowMetrics | None,
               thresholds: dict) -> SignalResult:
    """**Per-execution** cost, which is what makes this complementary to Phase
    4.4's spend anomaly rather than a duplicate of it.

    4.4 asks *"did this tenant spend more money this period than usual?"* —
    absolute dollars, tenant-scoped, a FinOps question. This asks *"did this
    agent start costing more per run?"* — normalized per unit of work,
    agent-scoped, a behavioral question. They come apart in both directions,
    which is the test that proves the boundary: an agent whose per-execution
    cost doubles while its traffic halves shows **no** 4.4 anomaly and a clear
    4.5 drift; a traffic spike at unchanged per-execution cost shows the
    reverse."""
    attribution = {}
    if candidate.models:
        attribution["model"] = _dominant(candidate.models)
    return _drift_rule(
        "cost_drift", "avg_cost_per_execution", "Cost per execution", "",
        candidate.avg_cost, baseline.avg_cost if baseline else None,
        thresholds, attribution=attribution)


def tool_failure_spike(candidate: WindowMetrics, baseline: WindowMetrics | None,
                       thresholds: dict) -> SignalResult:
    """Per-tool, and the worst offender is what is reported.

    An aggregate tool-failure rate across every tool an agent uses hides the
    thing an operator needs: one broken integration among five healthy ones
    barely moves the average. So each tool is rated on its own and the finding
    names it."""
    minimum = int(thresholds["min_tool_calls"])
    worst: SignalResult | None = None

    for tool_id, (calls, failures, name) in sorted(candidate.tools.items()):
        if calls < minimum:
            continue
        rate = failures / calls
        base_rate = None
        if baseline and tool_id in baseline.tools:
            base_calls, base_failures, _ = baseline.tools[tool_id]
            if base_calls >= minimum:
                base_rate = base_failures / base_calls
        result = _rate_rule(
            "tool_failure_spike", "tool_failure_rate", f"Tool '{name}' failure rate",
            rate, base_rate, thresholds,
            degraded_key="degraded_tool_failure_rate",
            anomalous_key="anomalous_tool_failure_rate",
            attribution={"tool_id": tool_id, "tool_name": name},
            evidence={"calls": calls, "failures": failures})
        if worst is None or _severity(result.state) > _severity(worst.state):
            worst = result

    if worst is None:
        total = candidate.tool_call_count
        return _normal("tool_failure_spike", "tool_failure_rate",
                       (f"No tool reached the {minimum}-call minimum in this window "
                        f"({total} tool calls across {len(candidate.tools)} tool(s)); "
                        "a thin sample is not evidence of a failing tool."))
    return worst


def tool_pattern_shift(candidate: WindowMetrics, baseline: WindowMetrics | None,
                       thresholds: dict) -> SignalResult:
    """Which tools an agent reaches for, not how often they fail.

    Measured as the total-variation distance between the candidate's tool mix
    and the baseline's — half the sum of absolute differences in each tool's
    share, which lands in [0, 1] and is 0 for an identical mix and 1 for a
    completely disjoint one. Chosen because it is a *stated arithmetic
    operation on two distributions* that an operator can recompute by hand from
    the breakdown in the finding, which a distance with a less obvious
    derivation would not be.

    A tool an agent has never used before appearing at 40% of its calls is a
    real behavioral change even when nothing fails."""
    if not baseline or not baseline.tools or not candidate.tools:
        return _normal("tool_pattern_shift", "tool_mix_distance",
                       "No baseline tool mix to compare against.")

    def shares(metrics: WindowMetrics) -> dict[str, float]:
        total = metrics.tool_call_count or 1
        return {tid: calls / total for tid, (calls, _f, _n) in metrics.tools.items()}

    now, before = shares(candidate), shares(baseline)
    distance = sum(abs(now.get(t, 0.0) - before.get(t, 0.0))
                   for t in set(now) | set(before)) / 2

    new_tools = sorted(set(now) - set(before))
    dropped = sorted(set(before) - set(now))
    names = {tid: name for tid, (_c, _f, name) in candidate.tools.items()}
    evidence = {
        "candidate_mix": {names.get(t, t): round(v, 4) for t, v in sorted(now.items())},
        "baseline_mix": {t: round(v, 4) for t, v in sorted(before.items())},
        "new_tools": [names.get(t, t) for t in new_tools],
        "dropped_tools": dropped,
    }

    for key, state in (("anomalous_drift_ratio", SignalState.ANOMALOUS),
                       ("degraded_drift_ratio", SignalState.DEGRADED)):
        # The drift ratios are reused as distance thresholds by dividing: a
        # 3.0x ratio means a distance of 1/3, a 1.5x means 2/3. Reusing the
        # configured knobs rather than adding two more the operator would have
        # to learn separately.
        limit = 1.0 / thresholds[key]
        if distance >= limit:
            detail = ""
            if new_tools:
                detail = (f" Tools not used in the baseline window: "
                          f"{', '.join(names.get(t, t) for t in new_tools)}.")
            return SignalResult(
                signal_type="tool_pattern_shift", metric="tool_mix_distance", state=state,
                reason=(f"Tool mix moved {distance:.2f} (total-variation distance) from the "
                        f"baseline window, at or above the {limit:.2f} threshold.{detail}"),
                observed=distance, threshold=limit, baseline=0.0, evidence=evidence)

    return SignalResult(
        signal_type="tool_pattern_shift", metric="tool_mix_distance",
        state=SignalState.NORMAL,
        reason=f"Tool mix moved {distance:.2f} from the baseline window — within thresholds.",
        observed=distance, threshold=1.0 / thresholds["degraded_drift_ratio"],
        baseline=0.0, evidence=evidence)


def loop_termination_anomaly(candidate: WindowMetrics, baseline: WindowMetrics | None,
                             thresholds: dict) -> SignalResult:
    """How often the loop is stopped by a safety cap rather than finishing.

    A rising cap-termination rate is a behavioral change even when every
    execution still reports success to its caller: the model has started
    looping, retrying, or burning its token budget, and Phase 5.6a.3's caps are
    absorbing it. The caps working as designed is exactly why this is not
    visible in the error rate."""
    return _rate_rule(
        "loop_termination_anomaly", "cap_termination_rate",
        "Loop-safety cap termination rate", candidate.cap_termination_rate,
        baseline.cap_termination_rate if baseline else None, thresholds,
        degraded_key="degraded_cap_termination_rate",
        anomalous_key="anomalous_cap_termination_rate",
        attribution=_dominant({k: v for k, v in candidate.termination_reasons.items()
                               if k in CAP_TERMINATIONS}),
        evidence={"cap_terminations": candidate.cap_terminations,
                  "termination_reasons": dict(candidate.termination_reasons),
                  "avg_loop_iterations": candidate.avg_loop_iterations})


def _severity(state: SignalState) -> int:
    return {SignalState.NORMAL: 0, SignalState.UNKNOWN: 1,
            SignalState.INSUFFICIENT_DATA: 2, SignalState.DEGRADED: 3,
            SignalState.ANOMALOUS: 4}[state]


#: Every rule, in a stable order. Iterated by the evaluator; the order is fixed
#: so that a run over identical data produces findings in an identical
#: sequence — part of what "deterministic" has to mean in practice.
RULES: tuple[Rule, ...] = (
    error_rate_shift,
    latency_drift,
    cost_drift,
    tool_failure_spike,
    tool_pattern_shift,
    policy_denial_surge,
    loop_termination_anomaly,
)

SIGNAL_TYPES: tuple[str, ...] = (
    "error_rate_shift", "latency_drift", "cost_drift", "tool_failure_spike",
    "tool_pattern_shift", "policy_denial_surge", "loop_termination_anomaly",
)
