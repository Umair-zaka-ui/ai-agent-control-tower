"""Phase 5.3 (M5.3) - Identity, Delegation & Trust Graph.

A sibling of ``app.runtime`` / ``app.discovery`` (not a child of either). It
builds the **relational control-graph substrate**: typed edges between
existing node rows, plus authority-chain reconstruction that generalizes the
Phase 4.2 human->agent->model->tool trace into a first-class recursive query,
plus the delegation/trust edges the later phases (5.4 dependency graph, 5.6
containment attribution, 5.7 external identity) build on.

The sentences that govern every module here:

  * **NO graph database.** Typed edges in one Postgres table
    (``control_graph_edges``) + recursive CTEs. No Neo4j, no second
    datastore, no materialized projection unless a measurement in this phase
    proves assembly too slow (it did not). See ADR-0017.
  * **Per-hop tenant-bounded traversal.** Every recursion step re-applies
    ``organization_id = :tenant``; a chain cannot cross a tenant boundary
    mid-walk even if an edge appears to connect two tenants' nodes.
  * **The graph represents; it never creates.** An edge is evidence a
    relationship exists (with a pointer back to the row that authorized it).
    Reading a chain or an edge grants nothing -- ``AuthorizationGateway``
    stays authoritative. Delegation edges mirror ``DelegationService``'s
    ``delegations`` rows; 5.3 invents no parallel delegation mechanism and no
    agent->agent autonomy.
  * **Edges reference existing rows.** A node is ``(type, id)`` resolved
    against its own table at read time -- no node state is copied.

Modules:
  * ``nodes.py``      - the ``(type, id)`` <-> table mapping + tenant-scoped
                        node resolution.
  * ``traversal.py``  - the recursive CTEs: bounded, cycle-safe, per-hop
                        tenant-bounded reachability + authority-chain
                        reconstruction + the explainable ``traverse_with_edges``
                        blast-radius walk (Phase 5.4).
  * ``service.py``    - ``ControlGraphService`` (edge management, through
                        ``AuthorizationGateway``; delegation edges mirror
                        ``DelegationService``) and ``AuthorityChainService``.
  * ``mcp.py``        - ``McpServerService`` (Phase 5.4): an MCP server as a
                        first-class dependency, represented **via the existing
                        ``Tool`` domain** (ADR-0018) - no second tool registry.
  * ``dependencies.py`` - ``DependencyGraphService`` (Phase 5.4): dependency
                        edges on the 5.3 substrate, derived from evidence
                        (OBSERVED / DECLARED) or declared through the API.
  * ``blast_radius.py`` - ``BlastRadiusService`` (Phase 5.4): "which agents can
                        reach X", "what breaks if Y is revoked", "which agents
                        depend on MCP Z", "which agents reach a resource of
                        kind K" - deterministic, explainable, per-hop
                        tenant-bounded, over the 5.3 CTE machinery.
  * ``schemas.py`` / ``routes.py`` - the additive read/query + MCP-trust surface.

Phase 5.4 adds the dependency graph. It still has NO graph database and NO
materialised projection (the §V blast-radius benchmark measured assembly well
inside budget - see docs/graph/blast-radius.md, ADR-0018). It represents and
analyses dependencies + MCP trust; it does not raise posture findings (5.5),
detect / contain threats (5.6), build the external gateway (5.7) or the UI
(5.8), or change tool execution / schema validation / egress (M1 owns those).
"""
