"""ACT-SRS-M3 §3.1, §10 (M3-3.1-FR-001..003) -- the deployment lifecycle's one
transition graph. Pure data + two pure functions, no I/O, no database --
structural twin of ``app.integration``'s own instance lifecycle machine and
``app.runtime.registry.services``'s own ``_TRANSITIONS`` (the agent lifecycle
machine). ``app.runtime.deployment.service.DeploymentLifecycleService``
is the *only* caller permitted to act on what this module returns; nothing
else in the codebase may assign ``AgentDeployment.lifecycle_state`` directly
(mechanically checked -- see ``tests/runtime/test_deployment_lifecycle.py``'s
grep-based AC-02 test, mirroring the same runtime-never-knows discipline
Milestone 2's integration framework already established for its own domain).

Fifteen states (ACT-SRS-M3 §3.1 M3-3.1-FR-002)::

    DRAFT --submit--> VALIDATING --(pass)--> READY --(no approval)--> DEPLOYING --> ACTIVE
      ^                   |                    |                                     |  |
      |               (fail)                (approval required)                     |  |
      |                   v                    v                                     |  |
      +---------- VALIDATION_FAILED      PENDING_APPROVAL --(reject)--> REJECTED----+  |
      |                   |                    |                            |          |
      +-------------------+               (approve)                        RETIRED <---+
                           |                    v                                       |
                        RETIRED             APPROVED --deploy--> DEPLOYING --> ...       |
                                                                                          |
      ACTIVE --pause--> PAUSED --resume--> ACTIVE                                        |
      ACTIVE --supersede--> SUPERSEDED --retire--> RETIRED                               |
      ACTIVE/PAUSED/DEGRADED/FAILED/... --retire--> RETIRED  <------------------------- -+
      ACTIVE/DEGRADED --rolling_back--> ROLLING_BACK --> ACTIVE | FAILED
      DEPLOYING/ACTIVE/DEGRADED --fail--> FAILED --retire--> RETIRED

This phase (3.1) drives, end to end, with a real ``DeploymentLifecycleService``
method and an HTTP route behind it: creation (-> DRAFT), the whole happy path
through to ACTIVE, pause/resume, retire, and the DEPLOYING->FAILED failure
edge. It also *declares* -- but leaves undriven, reachable only through the
generic ``.transition()`` authority call until a later phase wires a real
route to them -- the edges a later phase owns:

- ``ACTIVE/PAUSED -> SUPERSEDED``: 3.2 (environments/promotion) drives this
  when a newer deployment is promoted into the same environment slot.
- ``ACTIVE/DEGRADED -> ROLLING_BACK`` and ``ROLLING_BACK -> ACTIVE | FAILED``:
  3.7 (rollback) drives this.
- ``ACTIVE -> DEGRADED`` and ``DEGRADED -> ACTIVE | FAILED``: 3.5's canary
  health signal, hardened in 3.7, drives this.

Every edge above is nonetheless *declared* now (M3-3.1-FR-002's "complete
machine" requirement) and is individually proven reachable-when-declared /
rejected-when-not by ``test_deployment_lifecycle.py`` -- a later phase adding
a real driver for one of these needs no change here."""

from __future__ import annotations

# from_state -> the set of states a transition may legally land in. A flat
# dict-of-frozensets (not an event-keyed mapping like Milestone 2's own
# integration-instance lifecycle machine) since a caller always names its
# destination state directly ("transition this deployment to ACTIVE") and
# no two distinct real-world operations ever share one (from, to) pair here.
_TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"VALIDATING", "RETIRED"}),
    "VALIDATING": frozenset({"READY", "VALIDATION_FAILED"}),
    "VALIDATION_FAILED": frozenset({"VALIDATING", "DRAFT", "RETIRED"}),
    "READY": frozenset({"PENDING_APPROVAL", "DEPLOYING", "RETIRED"}),
    "PENDING_APPROVAL": frozenset({"APPROVED", "REJECTED"}),
    "APPROVED": frozenset({"DEPLOYING"}),
    "REJECTED": frozenset({"DRAFT", "RETIRED"}),
    "DEPLOYING": frozenset({"ACTIVE", "FAILED"}),
    "ACTIVE": frozenset({"PAUSED", "DEGRADED", "SUPERSEDED", "ROLLING_BACK", "FAILED", "RETIRED"}),
    "PAUSED": frozenset({"ACTIVE", "SUPERSEDED", "RETIRED"}),
    "DEGRADED": frozenset({"ACTIVE", "ROLLING_BACK", "FAILED", "RETIRED"}),
    "ROLLING_BACK": frozenset({"ACTIVE", "FAILED"}),
    "FAILED": frozenset({"RETIRED"}),
    "SUPERSEDED": frozenset({"RETIRED"}),
    "RETIRED": frozenset(),
}

# States reachable by a real, wired driver this phase ships (a service method
# + an HTTP route). Every other declared edge above is reachable only via the
# generic transition authority until a later phase adds its own driver -- see
# the module docstring's table of which phase owns which.
DRIVEN_THIS_PHASE: frozenset[str] = frozenset({
    "DRAFT", "VALIDATING", "VALIDATION_FAILED", "READY", "PENDING_APPROVAL",
    "APPROVED", "REJECTED", "DEPLOYING", "ACTIVE", "PAUSED", "FAILED", "RETIRED",
})


def can_transition(from_state: str, to_state: str) -> bool:
    return to_state in _TRANSITIONS.get(from_state, frozenset())


def all_states() -> tuple[str, ...]:
    return tuple(_TRANSITIONS.keys())


def allowed_targets(from_state: str) -> frozenset[str]:
    return _TRANSITIONS.get(from_state, frozenset())
