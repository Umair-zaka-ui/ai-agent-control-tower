"""Phase 4.7 -- the SLO and alert vocabularies (ACT-SRS-M4 §4.7, §18).

**The state values are aligned to 3.5 and 4.5, and the alignment is the same
kind resolved in ``app.behavior.states``.** An SLO asks a different question
from a health evaluation or a behavioral signal -- *is this reliability
objective being met?* -- so its two "answered" endpoints are named for that
question (`MET` / `BREACHED`). But the two states that carry the discipline
this phase is reusing are spelled character-for-character as 3.5 and 4.5 spell
them:

- ``INSUFFICIENT_DATA`` -- the window held too few samples. First-class, never
  a null, never quietly `MET`. "No failures observed" is not "the objective is
  met" (M4-4.7-FR-004).
- ``UNKNOWN`` -- not evaluable: the scoped subject is vetoed (a suspended
  agent). Distinct from `INSUFFICIENT_DATA`: `UNKNOWN` means "looking would not
  have told us anything true".

A test asserts the shared values against the live 3.5/4.5 modules, so a rename
on any side breaks the build rather than drifting.

This module imports nothing -- the vocabulary is readable and testable without
a database, the discipline 4.1/4.3/4.5 each applied to their contract modules.
"""

from __future__ import annotations

from enum import Enum


class SLOState(str, Enum):
    """The four states an SLO evaluation can report."""

    #: Measured, and the observed value satisfies the objective within the
    #: error budget. Produces no alert.
    MET = "MET"

    #: Measured, and the observed value violates the objective -- the error
    #: budget for the window is spent. Raises (or sustains) an alert.
    BREACHED = "BREACHED"

    #: The window held fewer terminal samples than the minimum. First-class:
    #: reports neither MET nor BREACHED (M4-4.7-FR-004).
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

    #: Not evaluable -- the scoped subject is vetoed (e.g. an AGENT-scoped SLO
    #: whose agent is suspended). Its recent data describes the intervention,
    #: not the objective.
    UNKNOWN = "UNKNOWN"


#: Shared, character-for-character, with 3.5's ``health_state`` and 4.5's
#: ``SignalState``. ``test_ac13_the_shared_states_match_35_and_45`` asserts it.
SHARED_WITH_HEALTH_AND_BEHAVIOR: frozenset[str] = frozenset({
    "INSUFFICIENT_DATA", "UNKNOWN",
})

#: States that raise/sustain an alert. ``MET`` clears one; the two "we could
#: not tell" states neither raise nor clear -- an alert's fate should not turn
#: on a thin window.
ALERTING_STATES: frozenset[SLOState] = frozenset({SLOState.BREACHED})
CLEARING_STATES: frozenset[SLOState] = frozenset({SLOState.MET})


class AlertStatus(str, Enum):
    """The alert lifecycle (M4-4.7-FR-011). Linear with one shortcut:
    OPEN → ACKNOWLEDGED → RESOLVED, and any non-terminal state → SUPPRESSED.

    - ``OPEN`` -- the condition is active and unhandled.
    - ``ACKNOWLEDGED`` -- an operator has seen it; the condition may still be
      active.
    - ``RESOLVED`` -- the condition cleared (by an operator, or automatically
      when a later evaluation reports the objective met). A resolved alert can
      **re-open** on recurrence (M4-4.7-FR-013).
    - ``SUPPRESSED`` -- an operator has decided this condition is known/expected
      and does not want it re-raised. Unlike RESOLVED, a suppressed alert is
      **not** re-opened on recurrence -- that is the point of suppressing it.
    """

    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    SUPPRESSED = "SUPPRESSED"


#: The states in which an alert is "active" -- the ones the partial unique
#: dedup index covers, so one ongoing condition is one active alert.
ACTIVE_ALERT_STATUSES: frozenset[str] = frozenset({"OPEN", "ACKNOWLEDGED"})

#: Valid transitions. A transition not listed here is ``ALERT_TRANSITION_INVALID``
#: (e.g. resolving an already-resolved alert, acknowledging a suppressed one).
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "OPEN": frozenset({"ACKNOWLEDGED", "RESOLVED", "SUPPRESSED"}),
    "ACKNOWLEDGED": frozenset({"RESOLVED", "SUPPRESSED"}),
    "RESOLVED": frozenset({"OPEN"}),          # re-open on recurrence only
    "SUPPRESSED": frozenset({"OPEN"}),        # an operator un-suppresses by letting it recur? no -- see AlertService
}


class AlertSeverity(str, Enum):
    """M4-4.7-FR-010. Ordered; a recurrence may raise severity but never lowers
    it silently."""

    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


_SEVERITY_ORDER = {s.value: i for i, s in enumerate(AlertSeverity)}


def max_severity(a: str, b: str) -> str:
    return a if _SEVERITY_ORDER.get(a, 0) >= _SEVERITY_ORDER.get(b, 0) else b


class AlertSource(str, Enum):
    """What kind of evidence raised an alert (M4-4.7-FR-010, FR-012). The
    evidence itself stays in its own table (``slo_evaluations`` /
    ``behavioral_findings``); ``source`` + ``source_id`` point at it. One
    lifecycle, two evidence sources -- not two parallel concepts (§18)."""

    SLO = "SLO"
    BEHAVIORAL = "BEHAVIORAL"
