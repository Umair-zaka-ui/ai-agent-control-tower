"""Phase 4.3 (ACT-SRS-M4 §8-4.3, §9, §17, §19) — the Runtime Governance
Enforcement Engine: the one place that decides whether an execution may
continue, evaluated at six checkpoints inside the model→tool→model loop.

**This package is the governance plane, and the governance plane fails
closed.** That is the deliberate inverse of ``app.observability`` (Phases
4.1/4.2), which is the telemetry plane and fails *open*. The two now live
inches apart inside one loop, so the distinction is stated wherever it can
be confused:

===============  ==================================  ========================
Plane            Failure posture                     Where
===============  ==================================  ========================
Governance       **Closed** — a mandatory checkpoint  ``app.runtime.governance``
                 that cannot be evaluated STOPs the
                 execution (§9).
Telemetry        **Open** — a failed write is
                 swallowed; the execution proceeds    ``app.observability``
                 unchanged (§9).
===============  ==================================  ========================

A governance decision never reads the telemetry plane, and a telemetry
failure never changes a governance decision. Both directions are tested
(``test_ac07_*`` in ``tests/runtime/test_runtime_governance.py``).

**One enforcement path.** Before this phase the tool loop enforced four
termination caps inline (iteration / wall-clock / token-budget /
repeated-identical-call, Phase 5.6a.3). Those comparisons no longer exist in
``ToolLoopOrchestrator``: they are constraints inside this engine, reached
through the same ``evaluate()`` call as every richer constraint. There is
exactly one place that answers "may this loop continue", which is the point —
two enforcement systems that could disagree about whether to stop an
execution is the failure mode this design exists to prevent.

**Not a second authorization system.** ``AuthorizationGateway`` stays
authoritative for *may this principal act*; this engine answers *may this
execution continue*, inside a request that gateway already authorized. The
engine is never consulted in place of it and never grants anything.

Modules:

- ``contract`` — the checkpoint/decision vocabulary and the frozen
  ``GovernanceDecision``. Imports no SQLAlchemy.
- ``constraints`` — the constraint implementations, including the four
  generalized loop caps.
- ``engine`` — ``RuntimeGovernanceEngine``: resolution, evaluation,
  fail-closed, persistence, audit, kill-switch trigger.
- ``policies`` — ``GovernancePolicyService``: CRUD and most-specific-wins
  scope resolution.
- ``schemas`` / ``routes`` — the management and read API.
"""

from app.runtime.governance.contract import (  # noqa: F401
    Checkpoint,
    CheckpointContext,
    Decision,
    GovernanceChallenged,
    GovernanceDecision,
    GovernanceStopped,
    ReasonCode,
    StopAction,
)
from app.runtime.governance.engine import RuntimeGovernanceEngine  # noqa: F401
from app.runtime.governance.policies import GovernancePolicyService  # noqa: F401

__all__ = [
    "Checkpoint",
    "CheckpointContext",
    "Decision",
    "GovernanceChallenged",
    "GovernanceDecision",
    "GovernancePolicyService",
    "GovernanceStopped",
    "ReasonCode",
    "RuntimeGovernanceEngine",
    "StopAction",
]
