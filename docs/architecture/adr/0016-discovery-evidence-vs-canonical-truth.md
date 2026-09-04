# ADR-0016 — Discovery observations are append-only evidence; only reconciliation derives canonical truth

- **Status:** Accepted
- **Date:** 2026-09-05
- **Deciders:** Phase 5.2 / M5.2 (Milestone 5 — Universal Agent Control & Security Fabric)
- **Supersedes:** —
- **Relates to:** ADR-0015 (the M5.1 universal agent asset model and
  control-state dimension), ADR-0008 (telemetry as a derived plane — the
  precedent this ADR generalises from "observability" to "external truth"),
  the Phase 3.8 scheduler's commit-before-dispatch discipline, the Phase
  2.1.x connector framework.

## Context

Milestone 5.1 gave `agents` the vocabulary to describe an agent ACT did not
create: `origin_category`, `control_state`, and discovery-metadata
placeholders. M5.2 is the first phase that actually reaches outside ACT to
populate them — which means, for the first time, **data from a system ACT
does not control** can influence the canonical inventory.

Two failure modes were live risks going in:

1. **A hostile or merely wrong external source corrupting the inventory
   directly.** If a discovery adapter could write `agents` itself, a
   compromised or misconfigured source could rename, re-own, or fabricate
   agents with no intermediate judgment.
2. **Reintroducing the M1 deadlock on a new surface.** Milestone 1's
   parallel tool dispatch once held a `FOR UPDATE` lock across worker I/O
   and hung invisibly to Postgres's own deadlock detector. A discovery sweep
   has the identical shape — a claim/read, then a slow external call, then a
   database write — and reaching out to a real network for the first time in
   this milestone made it the most likely place to make that mistake again.

## Decision

**Observations are evidence, never truth. Reconciliation is the only code
that derives canonical state, and it always does so through the existing
Phase 5.1 server-authoritative path.**

1. **`discovery_observations` is a separate, append-only table** —
   `UPDATE`/`DELETE` revoked from `PUBLIC` at the database level (mirroring
   migration `0047`'s `runtime_governance_decisions` precedent). No adapter,
   and no code outside `ReconciliationService`, ever writes `agents` on
   discovery's behalf.
2. **Reconciliation's decision is deterministic and explainable.** The sole
   identity signal is an exact `(organization_id, external_reference)` match;
   confidence is a plain number an adapter reports, compared against one
   fixed threshold (`0.75`). No fuzzy matching, no ML score, in this phase.
3. **Three outcomes only: CREATE, LINK, or FLAG.** Below the confidence
   threshold, or on a conflict with a NATIVE agent, the result is a
   `discovery_findings` row for a human — never an automatic merge or split.
4. **A LINK never touches ownership, `control_state`, or
   `lifecycle_status`** — only discovery metadata
   (`last_observed_at`/`discovery_confidence`/`discovery_source_ref`).
5. **A discovered agent is `control_state=DISCOVERED`, never presented as
   controllable** — discovery grants visibility, not authority (SRS §2.2).
6. **No database lock or open transaction is held across
   `adapter.fetch()`.** Structurally enforced: `DiscoveryAdapter.fetch()`'s
   signature accepts no `Session` at all, so an adapter has nothing to hold
   a lock with even if it tried. `DiscoveryRunService.run_source` has three
   short transactions (start → fetch (no session in scope) → persist +
   reconcile), the same shape Phase 3.8's `SchedulerService` already proved
   safe for its own claim/dispatch boundary.
7. **Sweeps reuse the existing scheduler** (`discovery.sweep`, a registered
   Phase 3.8 handler) — no second scheduling mechanism.
8. **One reference adapter, not a vendor catalog.** `HTTP_AGENT_REGISTRY`
   proves the framework against a real, non-mocked local HTTP server; every
   real vendor integration (Azure AI Foundry, AWS Bedrock Agents,
   LangGraph/CrewAI, Kubernetes, MCP, …) is deferred to future phases,
   registered the same way, without changing this framework.

## Consequences

### Positive
- A hostile or malfunctioning source can, at worst, produce a finding for a
  human to review — it cannot rename, re-own, silently merge, or delete a
  canonical agent, and it cannot escalate a discovered agent to governable.
- The M1 deadlock shape is proven absent on this new external-I/O surface
  both structurally (no `Session` in the adapter contract) and behaviorally
  (a held-open real HTTP response does not block a concurrent `FOR UPDATE`
  on the same source row).
- Staleness is honest: a source that stops reporting an agent raises a
  reviewable finding, never a silent deletion or an equally silent "still
  fine" — unknown is not safe, and missing evidence is not health.
- The framework is proven against a real external process, not only
  in-process mocks, closing the physical-validation gap M5.1 left open for
  this milestone.

### Negative / accepted cost
- Matching is deliberately blunt (exact identifier match only). A source
  that reuses or reassigns external identifiers, or an agent renamed at the
  source without a stable id, will not automatically reconcile — it will
  either miss (treated as new) or, if the id persists, link correctly, but
  fuzzy identity resolution is not attempted. Documented as a future
  extension, not built here.
- Reconciliation runs synchronously inside the sweep; a source with very
  many changed agents in one run serializes through one process's
  reconciliation loop. Acceptable at this phase's scale (bounded by
  `max_pages`/`page_size`); a queue-based reconciliation stage is a future
  option if volume grows.
- The manual-trigger API runs a sweep synchronously in the request
  (mirroring the registry's own import/export "eager" precedent, since this
  environment has no background worker) — a very slow or degraded source
  makes that one HTTP request slow, though the platform itself is
  unaffected and the sweep completes/fails cleanly either way.

### Residual risk
- `missed_sweeps_before_stale` is a simple sweep-count policy, not a
  wall-clock SLA; a source configured with a very long scheduler interval
  will take proportionally long to raise a staleness finding. Documented,
  tunable per source.
- The reference adapter's confidence is a fixed `1.00` (its source is
  treated as authoritative). A future vendor adapter reporting a genuinely
  heuristic/derived listing needs to choose a lower, still deterministic,
  source-class-derived confidence — this ADR does not yet prescribe how that
  number should be chosen for a non-authoritative source; revisit when the
  first such adapter is built.

## Revisit when

- **A second reference or vendor adapter is built** — confirm the
  confidence convention (what does a non-authoritative source report?) and
  extend `docs/discovery/reconciliation.md` rather than special-casing it in
  code.
- **Fuzzy/similarity matching is requested** — it needs its own ADR: a
  scoring function that is deterministic and reconstructable from its
  inputs, the same standard this one sets for exact matching.
- **Phase 5.7 (external governance gateway) attaches enforcement modes** —
  confirm a `GOVERNED` external agent's audit trail can still distinguish
  "discovered and enrolled" from "native," and that nothing here assumed
  `DISCOVERED`/`CLAIMED` agents would never reach real enforcement.
