"""Phase 5.2 (M5.2) - Agent Discovery Framework.

A sibling of ``app.integration`` and ``app.runtime`` (not a child of either),
because it drives both: it reuses the connector-shaped adapter contract and
the sole governed network primitive (``app.integration.sdk.GovernedHttpClient``)
while writing canonical state through the runtime's Phase 5.1 agent-asset-model
seam (``app.runtime.registry.control``).

The one sentence that governs every module here: **observations are
append-only evidence, never truth; reconciliation derives canonical state
from them, and does so through the existing, server-authoritative Phase 5.1
path.** See ``docs/discovery/`` and
``docs/architecture/adr/0016-discovery-evidence-vs-canonical-truth.md``.

Modules:
  * ``adapters/`` - the ``DiscoveryAdapter`` contract + a fixed registry
    + one real reference adapter (``HTTP_AGENT_REGISTRY``). Vendor adapters
    are deferred (SRS M5.2 §5).
  * ``service.py`` - ``DiscoverySourceService`` (config CRUD) and
    ``DiscoveryRunService`` (the sweep: fetch -> normalize -> persist
    observations -> reconcile, with the external fetch holding no DB lock
    and no open transaction -- the permanent M1 deadlock rule, extended here
    for the first time to external I/O).
  * ``reconciliation.py`` - ``ReconciliationService``: deterministic
    identity matching, create/link/flag, staleness.
  * ``schemas.py`` / ``routes.py`` - the minimum additive HTTP surface.

No graph (5.3), no MCP dependency graph (5.4), no posture engine (5.5), no
threat/containment (5.6), no external gateway (5.7), no UI (5.8) -- and no
vendor-adapter catalog. This phase builds the framework and proves it against
one real, non-mocked local source.
"""
