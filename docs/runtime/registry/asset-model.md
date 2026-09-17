# Universal agent asset model + control state (Phase 5.1 / M5.1)

Milestone 5 needs ACT's one canonical `agents` registry to describe agents it
did **not** create — discovered, claimed, registered, governed, unknown — not
only native agents. M5.1 adds four additive dimensions to `agents` (never a
second table) and a safe, server-authoritative claim workflow. It builds *no*
discovery, graph, posture, threat, gateway or UI machinery — those are later
phases. It only makes the model able to **say** the truth.

## The four dimensions (all on `agents`)

| Column | Question it answers | Native default |
|---|---|---|
| `control_state` | What relationship and **real enforcement authority** does ACT have over this agent? | `GOVERNED` |
| `origin_category` | Provenance category: `NATIVE` / `EXTERNAL` / `UNKNOWN`. `CHECK`-constrained. | `NATIVE` |
| `origin_provider` | Soft platform/vendor identifier (`ACT_NATIVE`, `MICROSOFT`, `AWS`, `GOOGLE`, `OPENAI`, `ANTHROPIC`, `LANGGRAPH`, `CREWAI`, `CUSTOM`, `UNKNOWN`, …). A plain string — **not** a DB enum. | `ACT_NATIVE` |
| discovery metadata | `first_observed_at`, `last_observed_at`, `discovery_source_ref`, `discovery_confidence` — **columns only**; Phase 5.2 populates them. | `NULL` |

### `control_state` is NOT `lifecycle_status`

`lifecycle_status` (the existing 13-state machine — `DRAFT → … → RETIRED`)
answers *"what operational lifecycle state is this native agent in?"*.
`control_state` answers a **different** question: *"what can ACT actually
do to this agent?"*. They are orthogonal and both live on every row:

- a native agent is `GOVERNED` (control) and may be in **any** `lifecycle_status`;
- a discovered external agent is `DISCOVERED` (control) with `lifecycle_status`
  `DRAFT` — the record makes no claim that ACT executes it or ever will.

The 13-state machine and its ~27 consumers (deployment gating, runtime
governance, the kill switch, cost, SLOs) are **unchanged** by M5.1.

### `control_state` progression

```
non-native (EXTERNAL / UNKNOWN):
DISCOVERED ──claim──▶ CLAIMED ◀──▶ REGISTERED          (never GOVERNED)

native (NATIVE):
GOVERNED                                                (always; no transitions)
```

- **DISCOVERED** — ACT knows the agent exists. **No authority.** No governance
  or enforcement affordance.
- **CLAIMED** — an authorized user has taken *responsibility*. Still **not**
  governed.
- **REGISTERED** — brought under ACT's registry / policy scope. The terminal
  control state for an agent ACT does not run; Phase 5.7's enforcement modes
  describe ACT's reach from here (a GATEWAY_ENFORCED agent lives at REGISTERED).
- **GOVERNED** — ACT runs and enforces the agent. **True of `NATIVE` agents
  only, in every lifecycle state, and never reachable by request** (ADR-0023,
  Validation Gate V0.2). It is the column Phase 5.6's containment gate and
  Phase 5.7's `NATIVE_ENFORCED` are derived from, so it must be a fact, not a
  declaration. A request for it on a non-native agent — or a request to move a
  native agent anywhere else — is refused with
  `CONTROL_STATE_ORIGIN_INCOMPATIBLE` (409) and audited as
  `RUNTIME_AGENT_CONTROL_STATE_REJECTED`. *(Until V0.2 this document said an
  external agent reaches GOVERNED "once 5.7 attaches a NATIVE or GATEWAY
  enforcement mode"; 5.7 built no such operation, and ADR-0021 had already
  refused the GATEWAY half.)*

`DISCOVERED` / `CLAIMED` never imply ACT can govern or stop the agent.

## Server-authoritative — never client-settable

`control_state` and `origin_*` are **absent from every write schema**
(`AgentRegistrationCreate`, `AgentRegistryUpdate`). A client that puts
`control_state: GOVERNED` in a `POST` or `PATCH` body is ignored — the field
never reaches the row. `control_state` moves only through:

| Endpoint | Permission | What it does |
|---|---|---|
| `POST /agents/{id}/claim` | `runtime.agent.claim` | `DISCOVERED → CLAIMED`; sets the business owner; writes `agent_ownership_history`; idempotent via `Idempotency-Key`. |
| `POST /agents/{id}/control-state` | `runtime.agent.control.manage` | `CLAIMED ↔ REGISTERED` for non-native agents; never to or from `GOVERNED` (ADR-0023). Refusals are audited. |
| `GET /agents/{id}/control-state` | `runtime.agent.view` | Read the asset-model snapshot. |

Both mutations authorize through the existing `AuthorizationGateway`, lock the
agent row `FOR UPDATE` (concurrent claims/transitions serialise — one wins, the
rest get a deterministic `AGENT_CLAIM_CONFLICT` / `CONTROL_STATE_TRANSITION_INVALID`,
never a torn state), are tenant-scoped by `get_or_404` (cross-tenant → **404**,
no existence leak; in-tenant-unpermitted → **403**), and write the existing
audit trail (`RUNTIME_AGENT_CLAIMED`, `RUNTIME_AGENT_CONTROL_STATE_CHANGED`) with
no secret in the payload.

## Provenance vs. `registration_source`

`registration_source` (`MANUAL` / `IMPORT`, pre-existing) records *how the row
was created*. `origin_category` records *where the agent came from*. A native
agent bulk-imported from a CSV is `registration_source=IMPORT` **and**
`origin_category=NATIVE`. They are different axes; M5.1 adds the second, reuses
the first untouched.

## Claiming ≠ governance

Claiming transitions `control_state` toward `CLAIMED` (responsibility). It does
**not** confer `GOVERNED` (enforcement). Governance enrollment is a separate,
later, deliberate `control-state` transition, and for an external agent the
enforcement that makes `GOVERNED` meaningful is Phase 5.7.

## Backfill

Migration `0054_agent_asset_model` is additive, reversible and downgrade-tested.
Every pre-existing agent row *is* a native agent ACT already governs — there is
no weak-signal inference — so the migration adds the three NOT-NULL columns with
a server default (instant on a large table) and then an explicit, idempotent
`UPDATE` restates that truth for every pre-existing row. Discovery metadata is
left `NULL`.

## What 5.2+ builds on this

`AgentProvenanceService.record_external_agent(...)` is the seam Phase 5.2's
discovery and reconciliation will call to create an `EXTERNAL`/`UNKNOWN`,
`DISCOVERED` record. M5.1 exposes no HTTP route for it and discovers, observes
and reconciles nothing itself.
