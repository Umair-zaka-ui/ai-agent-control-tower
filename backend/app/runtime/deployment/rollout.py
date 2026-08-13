"""ACT-SRS-M3 §Phase-3.5 (M3-3.5-FR-010, FR-012) -- the canary rollout's one
transition graph and its pure stage-gate logic. No I/O, no database, no ORM --
the structural twin of ``app.runtime.deployment.lifecycle`` (the deployment
lifecycle machine) and ``app.runtime.registry.services``'s own agent-lifecycle
``_TRANSITIONS``.

``app.runtime.deployment.canary.CanaryRolloutService`` is the *only* caller
permitted to act on what this module returns; nothing else in the codebase may
assign ``RolloutPlan.state`` directly (mechanically checked -- see
``tests/runtime/test_canary_rollout.py``'s grep-based test, mirroring the same
discipline Phase 3.1 established for ``AgentDeployment.lifecycle_state``).

Seven states (M3-3.5-FR-010)::

    PENDING --start--> IN_PROGRESS --(all stages cleared)--> SUCCEEDED
       |                  |  ^                |
       |                  |  |                +--> FAILED
       |             pause|  |resume
       |                  v  |
       |               PAUSED
       |                  |
       +----abort---------+----abort--> ABORTED
                          |
                          +--request-rollback--> ROLLBACK_REQUESTED

``ROLLBACK_REQUESTED`` is deliberately terminal *here*: this phase can request
a rollback as a rollout outcome (returning traffic to stable), but the governed,
configurable automatic-rollback trigger policy -- "if error rate exceeds X for
Y minutes, roll back automatically", per-tenant and rule-driven -- is Phase 3.7.
3.7 extends this state rather than duplicating it: it adds the *triggers* that
decide when to enter it, not a second rollback concept. See
docs/deployment/canary.md's "The 3.5/3.7 seam"."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# from_state -> the set of states a transition may legally land in. A flat
# dict-of-frozensets, matching ``lifecycle.py``'s own shape and for the same
# reason: a caller always names its destination directly ("abort this
# rollout"), and no two distinct real-world operations share a (from, to) pair.
_TRANSITIONS: dict[str, frozenset[str]] = {
    "PENDING": frozenset({"IN_PROGRESS", "ABORTED"}),
    "IN_PROGRESS": frozenset({"PAUSED", "SUCCEEDED", "ABORTED", "ROLLBACK_REQUESTED", "FAILED"}),
    "PAUSED": frozenset({"IN_PROGRESS", "ABORTED", "ROLLBACK_REQUESTED", "FAILED"}),
    "SUCCEEDED": frozenset(),
    "ABORTED": frozenset(),
    "ROLLBACK_REQUESTED": frozenset(),
    "FAILED": frozenset(),
}

TERMINAL_STATES: frozenset[str] = frozenset({
    "SUCCEEDED", "ABORTED", "ROLLBACK_REQUESTED", "FAILED",
})

# Health-state ordering used to decide whether a stage's ``health_requirement``
# is satisfied. INSUFFICIENT_DATA and UNKNOWN deliberately rank *below*
# UNHEALTHY rather than beside it: they are not "a bit unhealthy", they are
# "we do not know", and M3-3.5-FR-022 makes not-knowing never sufficient. A
# stage requiring UNHEALTHY-or-better (which nothing sensible does) still would
# not be satisfied by them -- see ``health_requirement_satisfied``.
_HEALTH_RANK: dict[str, int] = {
    "UNKNOWN": 0,
    "INSUFFICIENT_DATA": 0,
    "UNHEALTHY": 1,
    "DEGRADED": 2,
    "HEALTHY": 3,
}

# The two states that can never satisfy a health requirement, whatever the
# requirement is. Named separately from the ranking so the rule is explicit
# rather than an artifact of the numbers.
NON_PROVING_HEALTH_STATES: frozenset[str] = frozenset({"UNKNOWN", "INSUFFICIENT_DATA"})

# An explicit opt-out from the health gate for one stage.
#
# It exists because the alternative is worse. Health with zero observed
# executions is INSUFFICIENT_DATA -- correctly, since nothing has been proven
# -- so a stage on a low-traffic agent that genuinely has no calls yet would
# otherwise be stuck forever with no way to say "I know, advance it anyway".
# Making that an explicit, per-stage, auditable declaration is far safer than
# the tempting alternative of quietly treating "no data" as "fine", which is
# exactly the failure mode M3-3.5-FR-022 exists to prevent. A stage with
# ``NONE`` still cannot advance past a kill switch: the veto is enforced
# before gates are ever evaluated.
HEALTH_REQUIREMENT_NONE = "NONE"


def can_transition(from_state: str, to_state: str) -> bool:
    return to_state in _TRANSITIONS.get(from_state, frozenset())


def allowed_targets(from_state: str) -> frozenset[str]:
    return _TRANSITIONS.get(from_state, frozenset())


def all_states() -> tuple[str, ...]:
    return tuple(_TRANSITIONS.keys())


def health_requirement_satisfied(actual: str, required: str) -> bool:
    """M3-3.5-FR-022's safety rule, stated once.

    A thin sample is never proof of health: ``INSUFFICIENT_DATA`` (and
    ``UNKNOWN``) satisfy no requirement at all, even though a naive
    "is it bad?" check would let them through because nothing bad was
    *observed*. Nothing bad observed is not the same as nothing bad
    happening.

    A stage that declared ``health_requirement="NONE"`` waives the health
    *quality* bar -- an operator's recorded decision to gate on duration and
    samples alone. It does **not** waive ``UNKNOWN``, and the difference
    matters: INSUFFICIENT_DATA means "evaluable, but nothing proven yet",
    which an operator may legitimately choose to accept; UNKNOWN means "not
    evaluable at all" -- the candidate is suspended, killed, or has no
    servable deployment. No stage configuration may wave that through, or
    ``NONE`` would become a way to opt out of the kill switch."""
    if actual == "UNKNOWN":
        return False
    if required == HEALTH_REQUIREMENT_NONE:
        return True
    if actual in NON_PROVING_HEALTH_STATES:
        return False
    return _HEALTH_RANK.get(actual, 0) >= _HEALTH_RANK.get(required, 3)


@dataclass(frozen=True, slots=True)
class StageGateResult:
    """Why a stage may or may not advance. Carries *every* unmet reason, not
    just the first: an operator staring at a stuck canary should learn in one
    call that it needs both 40 more seconds and 12 more samples, rather than
    discovering the second only after the first clears."""

    satisfied: bool
    duration_met: bool
    samples_met: bool
    health_met: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "satisfied": self.satisfied,
            "duration_met": self.duration_met,
            "samples_met": self.samples_met,
            "health_met": self.health_met,
            "reasons": list(self.reasons),
        }


def evaluate_stage_gates(*, entered_at: datetime | None, now: datetime,
                        min_duration_seconds: int, sample_count: int, min_samples: int,
                        health_state: str, health_requirement: str) -> StageGateResult:
    """M3-3.5-FR-012 -- duration AND samples AND health, all three, pure.

    ``entered_at`` of ``None`` means the stage has not been entered yet, which
    cannot satisfy a duration gate (there is no elapsed time to measure)."""
    elapsed = (now - entered_at).total_seconds() if entered_at is not None else -1.0
    duration_met = entered_at is not None and elapsed >= min_duration_seconds
    samples_met = sample_count >= min_samples
    health_met = health_requirement_satisfied(health_state, health_requirement)

    reasons: list[str] = []
    if not duration_met:
        if entered_at is None:
            reasons.append("The stage has not been entered yet.")
        else:
            remaining = max(0, int(min_duration_seconds - elapsed))
            reasons.append(
                f"Minimum stage duration not elapsed: {int(elapsed)}s of "
                f"{min_duration_seconds}s ({remaining}s remaining)."
            )
    if not samples_met:
        reasons.append(
            f"Minimum sample count not met: {sample_count} of {min_samples} executions."
        )
    if not health_met:
        if health_state == "INSUFFICIENT_DATA":
            reasons.append(
                "Health is INSUFFICIENT_DATA: too few executions to prove the candidate "
                "healthy. A thin sample is not evidence of health."
            )
        elif health_state == "UNKNOWN":
            reasons.append(
                "Health is UNKNOWN: the candidate could not be evaluated (it may be "
                "suspended, killed, or not currently servable)."
            )
        else:
            reasons.append(
                f"Health requirement not met: candidate is {health_state}, "
                f"stage requires {health_requirement}."
            )

    return StageGateResult(
        satisfied=duration_met and samples_met and health_met,
        duration_met=duration_met, samples_met=samples_met, health_met=health_met,
        reasons=tuple(reasons),
    )
