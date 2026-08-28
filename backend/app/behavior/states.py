"""Behavioral signal states, and their relationship to Phase 3.5's health states.

**There is a genuine conflict between the build prompt and the repository here,
and this module is where it is resolved rather than papered over.**

The prompt asks for states ``NORMAL/DEGRADED/ANOMALOUS/INSUFFICIENT_DATA/
UNKNOWN`` and says, in the same sentence, *"align to the existing set — do not
fork a parallel vocabulary."* But the existing set — Phase 3.5's
``DeploymentHealthEvaluation.health_state`` — is ``HEALTHY/DEGRADED/UNHEALTHY/
INSUFFICIENT_DATA/UNKNOWN``. The proposed vocabulary differs from it in two of
five positions, so taking the prompt literally would itself be the fork it
forbids.

The resolution, and the reasoning:

**The three shared values are byte-identical and deliberately so.**
``DEGRADED``, ``INSUFFICIENT_DATA`` and ``UNKNOWN`` mean exactly what they mean
in 3.5, are spelled exactly the same, and a test asserts it. Those are the
load-bearing ones — ``INSUFFICIENT_DATA`` and ``UNKNOWN`` carry the discipline
(a thin window proves nothing; a vetoed subject is not evaluable) that this
phase is reusing, and letting them drift would be the real fork.

**The two endpoints differ because they are different claims.** Phase 3.5 asks
*"is this version fit to receive more traffic?"* — a **fitness** judgement, so
``HEALTHY``/``UNHEALTHY`` is the right axis. This phase asks *"has this agent's
behavior changed?"* — a **deviation** judgement, and the two axes genuinely come
apart:

- An agent whose p95 latency drops by 80% overnight is **anomalous** (something
  changed, and someone should know why) and in no sense unhealthy.
- An agent that has failed 30% of its calls every day for a month is
  **unhealthy** and not anomalous at all — nothing changed.

Calling the first "UNHEALTHY" would be wrong, and calling the second "NORMAL"
would be wrong. So the endpoints are named for the question this phase asks,
and the shared middle is shared exactly.

This module imports nothing. The vocabulary should be readable — and testable —
without a database, the same discipline Phase 4.1 applied to
``observability.trace`` and Phase 4.3 to ``governance.contract``.
"""

from __future__ import annotations

from enum import Enum


class SignalState(str, Enum):
    """The five states a behavioral signal can report."""

    #: Measured, within thresholds, and not meaningfully different from the
    #: baseline. Produces no finding — see ``BehavioralEvaluator.evaluate``.
    NORMAL = "NORMAL"

    #: Measurably worse or measurably shifted, but below the anomalous
    #: threshold. Spelled and meant exactly as in Phase 3.5.
    DEGRADED = "DEGRADED"

    #: The metric crossed the anomalous threshold, or diverged from its
    #: baseline by more than the configured margin.
    ANOMALOUS = "ANOMALOUS"

    #: The window held fewer samples than the minimum. **First-class, never a
    #: null and never quietly treated as NORMAL** — the discipline Phase 3.5
    #: established and the single most dangerous thing this engine could get
    #: wrong. "No failures observed" is not "no failures happen".
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

    #: Not evaluable: the subject is vetoed (suspended, killed). Distinct from
    #: INSUFFICIENT_DATA, which means "we looked and there was not enough";
    #: UNKNOWN means "looking would not have told us anything true".
    UNKNOWN = "UNKNOWN"


#: The values this vocabulary shares, character for character, with Phase 3.5's
#: ``health_state``. Asserted against the live 3.5 module by
#: ``test_ac05_the_shared_state_values_are_identical_to_35``, so a rename on
#: either side breaks the build rather than silently diverging.
SHARED_WITH_HEALTH_STATES: frozenset[str] = frozenset({
    "DEGRADED", "INSUFFICIENT_DATA", "UNKNOWN",
})

#: States that produce a persisted finding. NORMAL does not: recording every
#: quiet window would bury the ones that matter, the same materiality reasoning
#: Phase 4.3 applied to governance decisions. INSUFFICIENT_DATA and UNKNOWN
#: *do* persist, because "we could not tell" is an answer an operator asking
#: "why is there no signal here?" needs to be able to find.
REPORTABLE_STATES: frozenset[SignalState] = frozenset({
    SignalState.DEGRADED,
    SignalState.ANOMALOUS,
    SignalState.INSUFFICIENT_DATA,
    SignalState.UNKNOWN,
})
