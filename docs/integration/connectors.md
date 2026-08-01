# Connector Abstraction & Lifecycle (Phase 2.1.1)

`ACT-SRS-M2` §5.1, `ACT-INT-FR-001` through `FR-010`. This is the first
sub-phase of Milestone 2 (Enterprise Integration Framework) — the spine
every later connector, generic or vendor-specific, is built on.

## What this sub-phase is, in one sentence

A `Connector` abstraction with a tenant-scoped instance lifecycle and a
trivial reference implementation (`MockConnector`) — structurally the
exact twin of Phase 5.7a.1's `ModelProvider`/registry/`MockProvider`
triad, deliberately built the same way: interface first, proven by a
trivial implementation, before any real one leans on it.

## The runtime-never-knows principle

The governing constraint of this entire milestone (`ACT-INT-FR-006`,
SRS §3.3): **no connector- or vendor-specific logic may ever appear in
the runtime, the model gateway, or `ToolGatewayService`'s core.** A
connector produces a Tool; the runtime invokes a Tool and cannot tell an
SAP-backed one from an echo one. This sub-phase enforces it by
construction, not by convention — `test_connector_core.py`'s
`test_ac05_no_connector_specific_vocabulary_leaks_into_the_runtime`
mechanically greps every file under `app/runtime/` for the substring
`"connector"` and fails the build if it finds one. Today that count is
zero, and nothing in this sub-phase gives the runtime any reason to ever
import from `app.integration`.

## Type vs instance — the distinction that matters

- A **connector type** (`connectors` table, `app/integration/base.py`'s
  `Connector` ABC) is the *implementation*: "the generic REST connector,"
  "the reference MOCK connector." Registered once, platform-wide,
  declaring its capabilities, configuration schema, authentication
  *requirements* (declared only — never performed, see below) and the
  tool contract(s) it exposes. Versioned (`ACT-INT-FR-008`): a new
  version is a new row, never an in-place edit, so an existing instance's
  binding to a contract never shifts under it.

- A **connector instance** (`connector_instances` table) is a *tenant's
  configured use* of one type: "Acme Corp's connection to their orders
  API." Org-scoped, carries its own `configuration` (validated against
  its type's `config_schema`) and its own `lifecycle_state`. Many
  instances of one type coexist across many organizations with
  completely independent configuration.

Conflating these two was the single most likely design error this
sub-phase's build prompt called out in advance — the split above is what
avoids it.

## The lifecycle state machine

```
registered --configure--> configured --activate--> active
                               ^                       |
                               |                    disable
                               |                       v
                               +-------------------  disabled
                                                        |
        (any state) --mark_failed--> failed <-----------+
```

`app/integration/lifecycle.py` is the single authority on which
transitions are valid — `ConnectorService` never inlines the graph
itself. Four named events: `configure`, `activate`, `disable`,
`mark_failed`. Every actual transition (not every write) appends a
`connector_lifecycle_events` row and an `AuthorizationAuditEvent
.INTEGRATION_CONNECTOR_STATE_CHANGED` audit entry — the two supplement
each other rather than one replacing the other: the table is the
connector-specific queryable history (`GET /connectors/{id}/events`);
the audit service call keeps this domain consistent with the platform-
wide "every state change is audited" convention every other RUNTIME_*/
ROLE_*/etc. event already follows.

`failed` is reachable from every other state (`mark_failed`) — the
machine is complete per this sub-phase's own acceptance criteria — but
nothing *drives* it automatically yet; that is Phase 2.1.3's health
monitoring. No HTTP route exposes `mark_failed` in this sub-phase (see
§7 of the build prompt, which lists no such endpoint); it exists as a
real, directly-tested `ConnectorService` method so `failed` is genuinely
reachable today, not a documented-but-unreachable value.

### A decision the build prompt's own API list left open

The build prompt specifies eight endpoints but not exactly which
lifecycle states `PATCH /connectors/{id}` (configuration update) is
allowed from. This sub-phase settled it as: **`registered`, `configured`,
or `disabled` — never `active`.** An operator must `disable` an active
connector before changing its configuration. This mirrors this
codebase's existing taste for "you cannot silently rewrite something
live" (a published `AgentVersion`'s configuration is frozen the same
way) and gives one unambiguous moment where a live connector's
configuration is known to be settled. `disabled -> configured` reuses
the same `configure` event as `registered -> configured` — re-enabling a
disabled instance is exactly the same operation (supply/re-validate
configuration, land in `configured`) as configuring a fresh one.

## Configuration validation reuses Milestone 1's validator

`app/integration/base.py`'s `validate_configuration_schema()` is a thin
wrapper around the exact `jsonschema` library Milestone 1 already
validates tool and agent contracts with (`app/runtime/services.py`'s
`_validate_schema`) — not a new validator, per this sub-phase's own
working constraint. It is not imported directly from
`app.runtime.services`, since that function is a sibling domain's
private implementation detail, not a published shared utility; reusing
the one library both call is the actual point of "don't build a second
validator," not literal code-sharing across an internal boundary.

`Connector.validate_configuration()` is abstract — every concrete
connector must implement it. `MockConnector`'s implementation is exactly
one line (call the shared helper with its own `describe().config_schema`)
— proof that a connector with no validation needs beyond its declared
JSON Schema pays no extra cost, while the hook stays available, abstract,
for a future connector that needs cross-field checks JSON Schema can't
express.

## What is deliberately not here

| Deferred | Sub-phase |
|---|---|
| Authentication framework (API key, OAuth2, mTLS, ...) — a connector only *declares* `auth_requirements`, never performs authentication | 2.1.2 |
| Connector registry (dynamic type registration/resolution), health monitoring | 2.1.3 |
| Connector SDK | 2.1.4 |
| Any real connector (REST, database, storage, queue) | 2.2.x |
| Identity federation | 2.3.1 |
| Converting a declared tool contract into an actual invokable `Tool` row bound into `tools_snapshot` (the "tool bridge") | lands once 2.1.2/2.1.3 exist |
| Any change to model or tool execution — Milestone 1 is untouched | done |
| Deployment strategies | Milestone 3 |

Two things worth calling out explicitly since they are easy to mistake
for scope creep: `_CONNECTOR_TYPES` in `app/integration/service.py` is a
small, private, in-process dict (today: only `"MOCK" -> MockConnector`)
letting `ConnectorService` turn a `connectors` row back into a live
`Connector` instance when it needs to call `validate_configuration()` —
it is explicitly **not** the connector registry `ACT-INT-FR-040`/`FR-041`
describes (no dynamic registration, no public resolution API, no health
awareness) and is expected to be superseded entirely once 2.1.3 lands.
And the `Connector` ABC deliberately has no `authenticate()`, `execute()`
or `health_check()` method — adding one now would be building ahead of
the sub-phase that actually needs it, exactly the temptation the build
prompt warned against.

## Data model

- **`connectors`** — registered types. Unique on `(connector_type,
  version)`. Platform-wide, not tenant-scoped (the same "global catalog"
  shape release channels and signing keys already use elsewhere in this
  codebase).
- **`connector_instances`** — tenant configurations. Unique on
  `(organization_id, name)`. No credential column — Phase 2.1.2's
  concern, referenced once it exists, never stored here.
- **`connector_lifecycle_events`** — append-only audit trail. No table in
  this schema uses a database-level `REVOKE`; "append-only" is enforced
  the same way every other audit-shaped table in this codebase enforces
  it — `ConnectorService` exposes no update/delete method for this table,
  and no route accepts `PATCH`/`DELETE` on the events collection
  (mechanically checked by `test_ac18_lifecycle_events_are_append_only_by_construction`).

Migration `0033_connector_core`, additive only, reversible (`alembic
downgrade -1` / `upgrade head` both verified clean).

## API

Eight endpoints under `/api/v1/integration`, gated by two new
permissions (`integration.connector.view`, `integration.connector.manage`)
— see `app/integration/routes.py`. Every route scopes by
`actor.organization_id`, never a caller-supplied id, so cross-org access
returns a generic `CONNECTOR_NOT_FOUND` (404) rather than a 403 that
would confirm another org's instance exists — the same discipline every
other org-scoped resource in this codebase already follows.

## Testing

`backend/tests/integration/test_connector_core.py`, 24 tests, grouped
exactly as the build prompt's own §8 groups its acceptance criteria:
abstraction (AC-01..06), type vs instance (AC-07..09), config validation
(AC-10..12), lifecycle (AC-13..19), API & integrity (AC-20..27 — the
suite-level ones are proven by the full-suite run, not duplicated here).
Every pre-existing test (994 total after this phase, was 970) passes
unmodified — `app/runtime/` was not touched.
