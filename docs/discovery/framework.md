# Agent Discovery Framework (Phase 5.2 / M5.2)

The first Milestone 5 phase that reaches outside ACT. 5.1 laid the canonical
asset model (`origin_category`, `control_state`, discovery-metadata
placeholders) on `agents`. 5.2 builds the vendor-neutral framework that
populates it: adapters that observe agents in external systems, append-only
**observations** (evidence, not truth), and **reconciliation** that *derives*
canonical `agents` state from that evidence.

Ships the framework **plus one real reference adapter**
(`HTTP_AGENT_REGISTRY`) for a genuine, non-mocked proof. The vendor catalog
(Azure AI Foundry, AWS Bedrock Agents, LangGraph/CrewAI, Kubernetes, a real
MCP server, …) is explicitly deferred — see [Reference vs. vendor
adapters](#reference-vs-vendor-adapters).

## The flow

```
DiscoverySource (config) → DiscoveryRun (scheduled via 3.8 / manual)
  → adapter.fetch() via GovernedHttpClient   [EXTERNAL I/O — no DB lock held]
  → normalize → DiscoveryObservation (append-only, scrubbed)   [short txn]
  → ReconciliationService:                                     [short txn(s)]
      confident match     → LINK   (discovery metadata only, never authoritative fields)
      no match             → CREATE (new agent, control_state=DISCOVERED, via the 5.1 service)
      ambiguous/conflict  → FLAG   (a discovery_findings row — no silent merge/split)
  → staleness: missing from enough sweeps → a STALE_AGENT finding (never a deletion)
```

## No DB lock or open transaction across external I/O

**The permanent M1 deadlock rule**, load-bearing here for the first time in
Milestone 5. `ToolLoopOrchestrator`'s parallel-dispatch deadlock and the 3.8
scheduler's `SchedulerService` (`claim` commits before `dispatch` runs a
handler) are the two prior incidents/disciplines this phase extends to
*external* I/O: a discovery adapter's `fetch()` call must never run while any
database lock or open transaction is held.

**Structural guarantee, not just discipline**: `DiscoveryAdapter.fetch()`'s
signature accepts no `Session`/`db` parameter at all — an adapter has no
object to touch the database with even if it wanted to
(`app/discovery/adapters/base.py`). `test_ac06_adapter_fetch_signature_never_accepts_a_session`
asserts this via `inspect.signature` over every registered adapter.

**Behavioral proof, not only structural**:
`test_ac06_no_lock_held_across_the_external_fetch_behavioral` holds a real
local HTTP server's response open (blocking the fetch mid-flight) and, from a
*separate* database session, issues a real `SELECT ... FOR UPDATE` against
the very `discovery_sources` row the sweep is using — and it completes
immediately. If the sweep held a lock across the fetch, this would hang for
the duration of the held-open response (the exact M1 deadlock shape).

`DiscoveryRunService.run_source` (`app/discovery/service.py`) has three short
transactions per run — start (commit), fetch (no session in scope at all),
persist + reconcile (each its own short commit) — documented in that
module's own docstring, mirroring `app/scheduler/service.py`'s own "the
transaction boundaries are the phase" discipline exactly.

## The adapter contract

`app/discovery/adapters/base.py`'s `DiscoveryAdapter` is a structural twin of
`app.integration.base.Connector` (Phase 2.1.1): `describe()` +
`validate_configuration()` + `build_client()` + `fetch()` + `normalize()`.
Registered by a fixed, decorator-populated dict
(`app/discovery/adapters/registry.py`), mirroring the scheduler's own
`handler_key` security property — a `DiscoverySource.adapter_key` can never
make the platform import or execute arbitrary code; an unrecognized key
raises `DISCOVERY_ADAPTER_UNKNOWN`.

**The sole network primitive is `GovernedHttpClient`** (`app.integration.sdk`)
— the exact SSRF-hardened path Milestone 1's tools and Milestone 2's
connectors already use. `build_client()` binds it, at construction, to
exactly the hosts a source's configuration declares; a discovery adapter
cannot reach anything wider at call time, the same containment-by-construction
guarantee the connector SDK gives.

## Observations are append-only evidence

`discovery_observations` records *what a source reported, when, with what
confidence* — never the truth about the agent. It is genuinely append-only:
migration `0055` revokes `UPDATE`/`DELETE` from `PUBLIC` (mirroring migration
`0047`'s `runtime_governance_decisions` precedent exactly), and no module
under `app/discovery/` ever calls `db.delete` on one or updates a row after
insert. A bad, hostile, or stale observation is evidence to be weighed by
reconciliation — it cannot, by construction, directly corrupt the canonical
inventory.

Secrets never reach an observation: `normalized_payload` is passed through
`app.observability.scrubbing.scrub` (the same isolated, zero-platform-import
scrubber Phase 4.1 built) before the row is ever constructed. A source's
credential is applied only as an `Authorization` header during `fetch()`,
never persisted anywhere but the source's own encrypted-at-rest
`encrypted_secret` column (`app.runtime.providers.credential_crypto`, the
exact `ToolCredential` storage pattern — see
[docs/runtime/gateways.md](../runtime/gateways.md)).

Malicious or oversized external metadata is bounded before it can reach a
canonical column: `external_identifier` is truncated to
`Agent.external_reference`'s own length (255) once, at observation-persist
time (`DiscoveryRunService._persist_observations`) — the single choke point
every external identifier passes through, so reconciliation and staleness's
re-observation check always agree on the same value. `name`/`origin_provider`/
`description` are bounded again at reconciliation's create step
(`app/discovery/reconciliation.py`'s `_bounded`), matching `Agent`'s own
column widths. Each observation is persisted inside its own `SAVEPOINT`
(the same technique `app.observability.events.emit` uses for telemetry) so
one malformed item cannot poison the batch.

See [reconciliation.md](reconciliation.md) for the full matching, confidence,
no-silent-merge and staleness discipline.

## Discovery ≠ control

A newly discovered agent lands at `control_state=DISCOVERED` (Phase 5.1) —
ACT knows it exists and has **no** authority over it. Nothing in this phase
gives a discovered agent a governance or enforcement affordance: reaching
`GOVERNED` still requires the full 5.1 claim → register → enroll path,
deliberately, through a human or an explicit later automation (Phase 5.7).
`test_ac07_discovered_agent_is_not_controllable` proves a client attempting
`control_state=GOVERNED` directly on a freshly discovered agent is rejected
exactly as any other unclaimed agent would be.

## Fails open

Discovery is not on any execution or governance path (the Milestone 4 §9
plane rule, extended here): a source outage, a rate limit, a truncated page,
or a malformed response degrades a run (`PARTIAL`/`FAILED`) and, at most,
raises a staleness finding for agents that source can no longer see — it
never deletes an agent, never mutates `control_state`, and never blocks or
crashes the platform. `DiscoveryRunService.run_source` catches every
source-originated failure and turns it into a run outcome, not a propagated
exception.

## Reference vs. vendor adapters

**`HTTP_AGENT_REGISTRY`** (`app/discovery/adapters/http_agent_registry.py`)
is the one reference adapter this phase ships — a generic, vendor-neutral
client for any HTTP endpoint serving a paginated JSON agent list. It exists
to prove the framework end to end against a **real, non-mocked local HTTP
server** (`tests/discovery/test_discovery_framework.py`'s `local_server`
fixture — the same real-`http.server` convention Phase 2.2.1's REST-connector
tests established), not to catalog a vendor. No real vendor's API shape is
assumed anywhere in this adapter.

**Explicitly deferred**: Azure AI Foundry, AWS Bedrock Agents, a
LangGraph/CrewAI registry, Kubernetes CRDs, a real MCP server's
`list_agents`, and any other vendor-specific adapter. Adding one is a new,
independent module under `app/discovery/adapters/`, registered the same way
— the framework does not change. `test_ac15_reference_adapter_distinguished_no_vendor_catalog`
asserts the registry holds exactly `("HTTP_AGENT_REGISTRY",)` today.

A reference MCP-style adapter, when built, would discover an MCP server's
agents *as agents* — it must not build the MCP dependency graph, which is
Phase 5.4's job.

## Sweeps run on the existing scheduler — no new scheduler

`discovery.sweep` (`app/scheduler/handlers.py`) is a registered Phase 3.8
handler like every other scheduled job: it lists an organization's enabled
`DiscoverySource` rows and calls `DiscoveryRunService.run_source` for each,
one failure never stopping the sweep (the same discipline
`canary_auto_advance`/`rollback_trigger_evaluation` already established). A
tenant creates a `JobDefinition` naming `discovery.sweep` through the
existing `POST /api/v1/runtime/scheduler/jobs`, exactly like any other job —
no discovery-specific scheduling mechanism was built.

## API surface

Mounted under `/api/v1/discovery`, mirroring the connector-management
surface's own shape:

```
GET    /adapters                              the adapter registry, exhaustive by construction
GET    /sources                               list this tenant's sources
POST   /sources                               create (validates config against the adapter's schema)
GET    /sources/{id}
PATCH  /sources/{id}                          config/secret/enabled/staleness-policy updates
POST   /sources/{id}/runs                     manual trigger, synchronous, Idempotency-Key aware
GET    /sources/{id}/runs                     run history
GET    /runs/{id}
GET    /findings                              reconciliation + staleness findings, filterable by status
POST   /findings/{id}/resolve                 RESOLVED or DISMISSED
```

Two permissions (`discovery.source.view`, `discovery.source.manage`),
mirroring `integration.connector.view`/`.manage` exactly — no permission
inflation. **No route can write `agents` directly** — every effect on the
canonical registry flows through `DiscoveryRunService`/`ReconciliationService`,
which themselves go through the Phase 5.1 server-authoritative control-state
path. No speculative discovery/graph/posture endpoints — those are 5.3+.
