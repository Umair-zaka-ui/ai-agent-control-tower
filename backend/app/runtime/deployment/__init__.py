"""Phase 3.1 (ACT-SRS-M3 §3.1) -- the deployment lifecycle domain.

Sibling to ``app.runtime.registry`` (the agent lifecycle) and
``app.runtime.versioning`` (the version lifecycle), not a replacement for
either: a deployment references one agent version into one environment, and
this package governs *that* row's own 15-state lifecycle
(``agent_deployments.lifecycle_state``), never the version's or the agent's.

Four modules, mirroring the module split Milestone 2's own integration
framework already established (pure graph / reusable cross-cutting service /
the one authority):

- ``lifecycle.py`` -- the pure transition graph, no I/O, structural twin of
  ``app.integration.lifecycle`` and ``app.runtime.registry.services``'
  ``_TRANSITIONS``.
- ``idempotency.py`` -- the generic ``Idempotency-Key`` contract (ACT-SRS-M3
  §3.1 FR-010..013), deliberately not deployment-specific so 3.2/3.4/3.5/3.7
  can reuse it without redefining it.
- ``service.py`` -- ``DeploymentLifecycleService``, the single authority
  that ever writes ``agent_deployments.lifecycle_state``.
"""
