"""Phase 5.7 (M5.7) - the four enforcement modes and, for each, **exactly
what ACT can and cannot do**. This module is the honesty contract of the
phase; everything else in ``app/bridge`` is bound by it.

**The mode is derived, not asserted.** ``effective_mode()`` is the only
function that answers "what enforcement does ACT have over this agent", and
it reads two things:

    control_state == 'GOVERNED'          ->  NATIVE_ENFORCED
    otherwise                            ->  external_enforcement_mode
                                             (NULL means OBSERVED)

``agents.control_state`` is Phase 5.1's server-authoritative signal and the
*same* signal Phase 5.6's truthful-containment gate reads. Deriving the mode
from it -- rather than storing a fourth value that could drift -- is what
makes it impossible for a row to claim NATIVE enforcement that 5.6 would
then refuse to perform. The column's CHECK constraint does the other half:
``'NATIVE_ENFORCED'`` is **not a storable value**, so full enforcement cannot
be written into the database at all. It has to be *true*.

**Why a GATEWAY_ENFORCED external agent is NOT ``control_state='GOVERNED'``.**
M5.1's column comment anticipated that external agents would reach GOVERNED
"at NATIVE/GATEWAY enforcement, which is Phase 5.7". Building 5.7 showed that
would have been a false claim, so this phase deliberately does not do it:
``GOVERNED`` means *ACT runs and enforces this agent*, which is exactly what
Phase 5.6 relies on when it terminates an execution or trips the kill switch.
An external agent at GATEWAY_ENFORCED is not run by ACT -- ACT can refuse its
*boundary calls* and nothing more. Marking it GOVERNED would make 5.6's
``SUSPEND_AGENT`` report success for an agent it cannot suspend. So a
GATEWAY_ENFORCED agent sits at ``REGISTERED`` (under ACT's registry and policy
scope) and 5.6 keeps refusing enforcement-requiring containment on it --
correctly, because ACT genuinely cannot terminate it. See
``docs/bridge/enforcement-modes.md`` and ADR-0021.

**The reach of GATEWAY_ENFORCED, stated once.** ACT authorizes or denies the
capability calls the external agent *routes through ACT*. ACT does **not**
control, observe or constrain what that agent does by any other path. ACT
does not proxy its model calls or its network traffic and makes no claim
about them. The honest sentence is "ACT authorizes this agent's calls through
ACT's gateway", never "ACT governs this agent".
"""

from __future__ import annotations

from dataclasses import dataclass

#: Every mode, weakest reach first. The order is meaningful: index is a
#: monotonically non-decreasing measure of reach, and ``_rank`` below relies
#: on it for the "a transition must be deliberate" check.
ENFORCEMENT_MODES: tuple[str, ...] = (
    "OBSERVED",
    "ADVISORY",
    "GATEWAY_ENFORCED",
    "NATIVE_ENFORCED",
)

#: The subset an operator may actually write (see the module docstring).
SETTABLE_MODES: tuple[str, ...] = ("OBSERVED", "ADVISORY", "GATEWAY_ENFORCED")

#: The one control_state that means ACT really runs and enforces the agent.
#: Identical to ``app.threat.containment._ENFORCEABLE_CONTROL_STATE`` by
#: intent -- both answer the same question from the same column.
NATIVE_CONTROL_STATE = "GOVERNED"


@dataclass(frozen=True)
class ModeReach:
    """What one mode truthfully guarantees.

    ``display`` is the *only* sentence any API or UI is permitted to use for
    this mode. ``test_ac03_*`` asserts that no display string for a
    non-native mode contains a claim of governing or controlling the agent
    itself -- the over-claim this phase exists to prevent.
    """

    mode: str
    display: str
    #: Can ACT refuse a capability call the agent routes through ACT?
    reaches_boundary_calls: bool
    #: Can ACT stop, suspend or terminate the agent itself?
    reaches_agent_execution: bool
    #: Does ACT evaluate policy for this agent at all?
    evaluates_policy: bool
    #: Does ACT produce a recommendation a human can act on?
    emits_recommendation: bool
    #: One line naming what ACT explicitly cannot do. Displayed alongside
    #: ``display`` wherever a mode is shown; never omitted.
    limits: str


REACH: dict[str, ModeReach] = {
    "OBSERVED": ModeReach(
        mode="OBSERVED",
        display="ACT observes this agent.",
        reaches_boundary_calls=False,
        reaches_agent_execution=False,
        evaluates_policy=False,
        emits_recommendation=False,
        limits=("ACT performs no enforcement of any kind on this agent. It ingests "
                "events as evidence and cannot deny, stop or constrain anything it does."),
    ),
    "ADVISORY": ModeReach(
        mode="ADVISORY",
        display="ACT evaluates policy for this agent and recommends.",
        reaches_boundary_calls=False,
        reaches_agent_execution=False,
        evaluates_policy=True,
        emits_recommendation=True,
        limits=("ACT performs no enforcement on this agent. A recommendation is advice "
                "for a human; nothing is denied, stopped or constrained by ACT."),
    ),
    "GATEWAY_ENFORCED": ModeReach(
        mode="GATEWAY_ENFORCED",
        display="ACT authorizes this agent's capability calls that route through ACT's gateway.",
        reaches_boundary_calls=True,
        reaches_agent_execution=False,
        evaluates_policy=True,
        emits_recommendation=True,
        limits=("ACT's reach is the boundary only. ACT does not run this agent and cannot "
                "stop it. Anything it does that does not route through ACT's gateway -- its "
                "model calls, its network traffic, any other tool it holds -- is outside "
                "ACT's control, and ACT makes no claim about it."),
    ),
    "NATIVE_ENFORCED": ModeReach(
        mode="NATIVE_ENFORCED",
        display="ACT runs this agent and enforces it in full.",
        reaches_boundary_calls=True,
        reaches_agent_execution=True,
        evaluates_policy=True,
        emits_recommendation=True,
        limits=("None beyond the platform's own: the Phase 4.3 runtime governance engine "
                "and the kill switch apply to every execution."),
    ),
}


def effective_mode(agent) -> str:
    """The one place a mode is decided. Never takes a caller's word for it.

    ``GOVERNED`` is the single signal for full enforcement (Phase 5.1, and the
    same one Phase 5.6 gates containment on). Everything else falls back to
    the stored external mode, and an unset external mode means the weakest
    truthful claim: ACT has seen this agent and can do nothing to it.
    """
    if agent.control_state == NATIVE_CONTROL_STATE:
        return "NATIVE_ENFORCED"
    return agent.external_enforcement_mode or "OBSERVED"


def reach_of(agent) -> ModeReach:
    return REACH[effective_mode(agent)]


def enforces_boundary_calls(agent) -> bool:
    """True only where ACT can genuinely refuse a call at the boundary."""
    return REACH[effective_mode(agent)].reaches_boundary_calls


def describe(agent) -> dict:
    """The truthful, serializable description of this agent's governance.

    ``limits`` is part of the payload, not an optional extra: a client that
    renders ``display`` without it would be presenting a claim without its
    bound, which is the failure mode this phase exists to prevent.
    """
    mode = effective_mode(agent)
    r = REACH[mode]
    return {
        "enforcement_mode": mode,
        "control_state": agent.control_state,
        "display": r.display,
        "limits": r.limits,
        "reaches_boundary_calls": r.reaches_boundary_calls,
        "reaches_agent_execution": r.reaches_agent_execution,
        "evaluates_policy": r.evaluates_policy,
        "derived_from_control_state": mode == "NATIVE_ENFORCED",
    }


__all__ = [
    "ENFORCEMENT_MODES",
    "SETTABLE_MODES",
    "NATIVE_CONTROL_STATE",
    "ModeReach",
    "REACH",
    "effective_mode",
    "reach_of",
    "enforces_boundary_calls",
    "describe",
]
