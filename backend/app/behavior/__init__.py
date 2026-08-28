"""Phase 4.5 (ACT-SRS-M4 §4.5, Gate L) — behavioral signals and runtime
anomaly detection.

A sibling of ``app/runtime``, ``app/observability`` and ``app/finops``, for the
same reason those are: the dependency direction should be visible in the import
graph rather than only asserted.

**Deterministic and explainable, or not emitted.** §4.5 forbids opaque anomaly
scoring, and the reason is worth stating rather than merely obeying: *"this
agent is 0.87 anomalous"* is unauditable, unappealable and ungovernable — a
regulated tenant cannot act on it, dispute it, or show a regulator why it fired.
Every rule in this package is arithmetic over a window, and every finding
carries the numbers that produced it: the metric, both window bounds with their
sample counts, the observed value, the threshold and/or baseline, and the
crossing in words. A signal that cannot explain itself is not emitted.

**The engine shape is Phase 3.5's, reused rather than forked.** Veto →
sufficiency → threshold → baseline, with ``INSUFFICIENT_DATA`` first-class. The
baseline axis differs — 3.5 compares a candidate version against the stable one
over the same window; this compares an agent against itself over the preceding
window — because they answer different questions, but the order and the
discipline are the same. See ``app.behavior.states`` for the vocabulary
alignment, which shares three of five values character for character.

**A finding is a signal, never enforcement.** Nothing here writes an execution's
status, raises a governance exception, or reaches the kill switch. Phase 4.3's
``RuntimeGovernanceEngine`` remains the only thing on this platform that can
stop an execution, and a test asserts that structurally. A future policy could
*read* these findings; that would still route enforcement through 4.3.

**Emission is non-gating** (§9). An evaluation that fails produces no finding —
it never produces a STOP. Behavioral signals are telemetry-plane, and the
telemetry plane fails open.

Modules:

- ``states`` — the five signal states and their relationship to 3.5's.
  Imports nothing.
- ``signals`` — the deterministic rules and their thresholds. Pure functions of
  ``(candidate, baseline, thresholds)``; no session, no clock, no globals.
- ``engine`` — aggregation, the 3.5 evaluation order, idempotent persistence.
- ``schemas`` / ``routes`` — the read and on-demand-evaluate API.
"""

from app.behavior.engine import BehavioralEvaluator, EvaluationResult  # noqa: F401
from app.behavior.signals import SIGNAL_TYPES, SignalResult, WindowMetrics  # noqa: F401
from app.behavior.states import SignalState  # noqa: F401

__all__ = [
    "SIGNAL_TYPES",
    "BehavioralEvaluator",
    "EvaluationResult",
    "SignalResult",
    "SignalState",
    "WindowMetrics",
]
