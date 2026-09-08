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
  * ``edges.py``      - edge/derived-edge assembly helpers.
  * ``traversal.py``  - the recursive CTEs: bounded, cycle-safe, per-hop
                        tenant-bounded reachability + authority-chain
                        reconstruction.
  * ``service.py``    - ``ControlGraphService`` (edge management, through
                        ``AuthorizationGateway``; delegation edges mirror
                        ``DelegationService``) and ``AuthorityChainService``.
  * ``schemas.py`` / ``routes.py`` - the minimal additive read/query surface.

No dependency graph (5.4), no posture (5.5), no threat/containment (5.6), no
external gateway (5.7), no UI (5.8).
"""
