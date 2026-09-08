# Authority-Chain Reconstruction (Phase 5.3 / M5.3)

*Who authorized this action, under whose delegated authority, through which
identity, down to which resource* — as a first-class, deterministic,
explainable recursive query.

## It generalizes the Phase 4.2 trace

Phase 4.1/4.2 already reconstructs `human → agent → model → tool` for one
execution from its `correlation_id` and the FK structure of the existing rows
(`agent_executions`, `execution_messages`, `tool_calls`). 5.3 makes that a
**recursive query** and adds the delegation and replay prefixes:

```
[ origin ] --DELEGATES_TO*--> [ triggering identity ]   ← recursive over control_graph_edges
           --TRIGGERED-->      [ root execution ]
           --REPLAYED_AS*-->   [ this execution ]        ← recursive over parent_execution_id
           --EXECUTED_AS-->    [ agent ]
           --ACTS_AS-->        [ agent identity ]
           --INVOKED-->        [ tool ] --TARGETED--> [ external host ]
```

Nothing here is a new store of truth. The chain is the current state of the
execution / identity / delegation rows **plus** the current edges, assembled
every time (the ADR-0008 discipline — assemble from rows, do not copy them).

## Each hop names its evidence

Every hop in the response carries an `evidence` object with a `kind` and the
id of the row or edge it came from:

```json
{
  "from": {"type": "HUMAN", "id": "..."},
  "edge": "DELEGATES_TO",
  "to":   {"type": "HUMAN", "id": "...", "label": "ops@example.com"},
  "evidence": {"kind": "control_graph_edge", "id": "...", "ref_table": "delegations",
               "ref_id": "...", "scope_type": "ORGANIZATION", "permission": null}
}
```

`kind` is one of: `agent_executions.triggered_by_identity_id`,
`agent_executions.parent_execution_id`, `agent_executions.agent_id`,
`agent_identities`, `control_graph_edge`, `tool_calls`,
`tool_calls.target_host`.

## Per-hop tenant-bounded

Both recursive prefixes filter `organization_id = :tenant` at **every** step
(the delegation prefix over `control_graph_edges`, the replay prefix over
`agent_executions`). A planted cross-tenant delegation edge does **not**
extend the chain — the walk truncates at the foreign node and adds a note
(`"delegation chain truncated: a delegator does not resolve in this
tenant"`). A chain query for an execution in another tenant is `404` — no
existence leak. Proven in `test_ac06_authority_chain_cannot_cross_a_tenant_boundary`.

## Missing evidence is explicit — never "no delegation"

If the root execution has a `triggered_by_identity_id` that no longer
resolves in the tenant, or none at all (a `SYSTEM`-triggered execution), the
response sets `"complete": false` and adds a note saying so. It still
reconstructs the spine it *can* see (`EXECUTED_AS`, `ACTS_AS`, `INVOKED`,
`TARGETED`). Missing evidence for a hop is reported as *chain incomplete* —
never rendered as *no delegation occurred* (missing evidence ≠ evidence of
absence).

## Confused-deputy visibility

When a human delegates to another human who then triggers an agent, the chain
shows the whole propagation: the original authority (the delegator), the
deputy human (the delegatee), and the agent deputy — each as a `from` node on
a hop, with the delegation's scope carried from the `delegations` row it
mirrors. Revoke the delegation edge and it drops from the next
reconstruction; the `delegations` row's own lifecycle is untouched (the graph
never writes it).

## Bounded and deterministic

`max_depth` defaults to 16, hard-capped at 32 (`MAX_TRAVERSAL_DEPTH`). A
cycle in the delegation edges cannot loop the walk (the `'type:id'` path
guard). Same data ⇒ same chain, hop for hop
(`test_ac05_authority_chain_is_deterministic`).

## Audit

Reconstructing a chain writes one `GRAPH_AUTHORITY_CHAIN_RECONSTRUCTED` audit
event (who / execution id / hop count / complete). **Reading** an edge or
listing edges is not a change and is not audited. Creating or revoking a
delegation/trust edge writes `GRAPH_{DELEGATION,TRUST}_EDGE_{CREATED,REVOKED}`.
