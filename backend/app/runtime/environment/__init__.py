"""ACT-SRS-M3 §3.2 -- governed, tenant-scoped environments and the promotion
paths between them. Sibling to ``app.runtime.deployment`` (Phase 3.1):
that package owns *state within one deployment's own lifecycle*; this one
owns *which environment a deployment targets, what that environment
requires, and how a version's deployment eligibility moves between
environments* (``app.runtime.environment.policy`` for evaluation,
``app.runtime.environment.service`` for the entities and the promotion
operation itself).

Deliberately does not touch, fork, or widen anything on the Milestone 1
execution path (traffic allocation, the version resolver, the execution
gate) -- those are Phase 3.4's own, single, deliberate change; see
docs/deployment/environments.md for the exact boundary."""

from __future__ import annotations
