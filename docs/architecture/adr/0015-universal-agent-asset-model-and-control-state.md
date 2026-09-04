# ADR-0015 — One canonical agent registry describes the whole spectrum; control state is a distinct dimension from lifecycle

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Phase 5.1 / M5.1 (Milestone 5 — Universal Agent Control & Security Fabric)
- **Supersedes:** —
- **Relates to:** the Phase 5.1 Enterprise Agent Registry (the `agents` table and
  its 13-state `lifecycle_status` machine), `AgentOwnershipHistory`,
  `AuthorizationGateway`, ADR-0002 (PostgreSQL as sole datastore). Prerequisite
  for every later Milestone 5 phase (discovery 5.2, graph 5.3, MCP 5.4, posture
  5.5, threat/containment 5.6, external gateway 5.7, command center 5.8).

## Context

Milestone 5 requires ACT's registry to describe agents it did **not** create:
agents discovered in a cloud tenant, agents an owner has claimed but ACT cannot
yet enforce anything against, agents brought under policy scope, and agents ACT
genuinely governs. Before M5.1 the `agents` table could only describe a native
agent — one ACT registered, versioned, signed, deployed and executes.

Two facts constrain the solution:

1. **There must be exactly one canonical agent registry.** A second table
   (`external_agents`, `discovered_agents`, `agents_v2`) would fork every
   downstream consumer — authorization, ownership, audit, deployment, cost — and
   the whole milestone exists to give a CISO *one* inventory.
2. **`lifecycle_status` must not be overloaded.** The existing 13-state machine
   (`DRAFT → … → RETIRED`) is read by ~27 modules — deployment gating, runtime
   governance, the kill switch, cost, SLOs. It answers *"what operational
   lifecycle state is this native agent in?"*. It cannot also answer *"what
   enforcement authority does ACT have over this agent?"* without either
   breaking native agents or producing untruthful control state.

## Options considered

### Option A — a parallel `external_agents` table
- Pros: native code path completely untouched.
- Cons: two registries to keep in sync; every consumer must union them; a claimed
  external agent that becomes governed would have to *move tables*. Rejected by
  the milestone's own non-goals.

### Option B — overload `lifecycle_status` with new states (`DISCOVERED`, `CLAIMED`)
- Pros: no new column.
- Cons: a discovered external agent has no meaningful *operational* lifecycle, and
  every existing consumer of `lifecycle_status` would suddenly see states it was
  never written to handle. Conflates two orthogonal questions.

### Option C — additive columns on `agents`: a distinct `control_state` dimension + soft provenance
- Pros: one registry; `lifecycle_status` and its consumers untouched;
  `control_state` and `lifecycle_status` coexist on every row and are read
  independently; a claimed agent that becomes governed just changes a column.
- Cons: two state fields on one row (a reader must know which question each
  answers); the backfill must assert a fact about every existing row.

## Decision

We chose **Option C**.

`agents` gains four additive dimensions, backfilled so every pre-existing row
states the truth (it *is* a native, governed agent):

| Column | Meaning | Native default |
|---|---|---|
| `control_state` | `DISCOVERED → CLAIMED → REGISTERED → GOVERNED` — the relationship and **real enforcement authority** ACT has. | `GOVERNED` |
| `origin_category` | `NATIVE` / `EXTERNAL` / `UNKNOWN` — provenance category (small, stable, `CHECK`-constrained). | `NATIVE` |
| `origin_provider` | soft platform/vendor string (`ACT_NATIVE`, `MICROSOFT`, `LANGGRAPH`, …) — **not** a DB enum, so a new vendor is never a migration. | `ACT_NATIVE` |
| discovery metadata | `first_observed_at` / `last_observed_at` / `discovery_source_ref` / `discovery_confidence` — **columns only**; Phase 5.2 populates them. | `NULL` |

`control_state` is **server-authoritative**. It is absent from every write
schema (`AgentRegistrationCreate`, `AgentRegistryUpdate`), so a client cannot
mass-assign it. It moves only through two dedicated endpoints that authorize
via the existing `AuthorizationGateway`, lock the row `FOR UPDATE`, validate the
transition against a fixed matrix, write the existing `AgentOwnershipHistory`
ledger and the existing audit trail, and are tenant-scoped by the caller's
`get_or_404` (cross-tenant → 404, no existence leak):

- `POST /agents/{id}/claim` — an authorized user takes **responsibility** for a
  `DISCOVERED` agent. Advances to `CLAIMED`, **never** `GOVERNED`. Idempotent via
  `Idempotency-Key`.
- `POST /agents/{id}/control-state` — `CLAIMED → REGISTERED → GOVERNED` and the
  safe reverses. Enrolling into `GOVERNED` requires an accountable owner.

`DISCOVERED` / `CLAIMED` never imply ACT can govern or stop the agent — the
enforcement mode that would make an external agent genuinely governable is Phase
5.7's job; M5.1 only makes the model able to *say* the truth.

Ownership reuses the three existing owner columns, `AgentOwnershipHistory` (whose
ledger vocabulary already includes `SECURITY_OWNER` / `DATA_OWNER`), and the
org/user/team hierarchy. The gap analysis found no genuine gap: business
sponsor = `owner_id`, operating team = `team_id`, approving authority =
`AgentOwnershipHistory.approved_by` + the lifecycle-event ledger. **No new
ownership table.**

Provenance is deliberately *not* `registration_source` (which already exists and
means *how the row was created* — `MANUAL` / `IMPORT` — orthogonal to *where the
agent came from*; a native agent imported from a CSV is still `NATIVE`).

## Consequences

### Positive
- One inventory. Every downstream consumer (authorization, ownership, audit,
  deployment, cost) sees native and external agents through the same table.
- The 13-state lifecycle machine and its ~27 consumers are byte-for-byte
  unchanged; a dedicated test asserts orthogonality on a native row carrying
  both fields.
- A new vendor is a new `origin_provider` string — zero schema churn.
- 5.2 discovery has its seam (`AgentProvenanceService.record_external_agent`) and
  its columns already migrated onto the hot registry, so it need not re-migrate.

### Negative / accepted cost
- Two state fields on one row. A reader must know that `lifecycle_status`
  answers the operational question and `control_state` answers the authority
  question. Documented in `docs/runtime/registry/asset-model.md` and enforced by
  test, but it is a real cognitive cost.
- The backfill asserts a fact ("every existing agent is native and governed").
  That is true *today* — there is no external agent in any installation yet —
  but the migration encodes it rather than deriving it.

### Residual risk
- `control_state` and `origin_category` carry `CHECK` constraints; `origin_provider`
  does not. A typo'd provider string is accepted. Acceptable: the provider is
  informational until 5.2 reconciliation, which will normalise it.
- The generic `control-state` endpoint cannot *produce* `CLAIMED` (that needs
  owner context only `claim` carries). A caller who tries gets a clear
  `CONTROL_STATE_TRANSITION_INVALID` pointing at `claim`, but it is a two-call
  path where one might be expected.

## Revisit when

- **Phase 5.7 attaches enforcement modes.** `GOVERNED` will need to distinguish
  *native* governance from *gateway* governance of an external agent; confirm the
  `control_state` vocabulary still fits or gains a sibling `enforcement_mode`
  column rather than more `control_state` values.
- **An agent legitimately needs multiple external identities.** `external_reference`
  is single-valued today; a satellite table (never a parallel registry) would be
  the move.
- **Ownership roles outgrow the three columns + history ledger** — e.g. a
  regulator requires a distinct, queryable "approving authority" per agent. Then
  a thin additive ownership-role satellite, not a wider `agents` row.
