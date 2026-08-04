# Connector Abstraction, Lifecycle, Authentication & Health (Phases 2.1.1 – 2.1.3)

`ACT-SRS-M2` §5.1–§5.3, `ACT-INT-FR-001` through `FR-047`. The first
three sub-phases of Milestone 2 (Enterprise Integration Framework) —
2.1.1 is the spine every later connector is built on; 2.1.2 is the
pluggable authentication framework that lets a connector instance hold
real, encrypted credentials for six schemes, including transparent
OAuth2; 2.1.3 makes a connector *discoverable and monitored* — a
registry that resolves it, health checks that verify it, and an
automated path into (and back out of) the `failed` state 2.1.1 defined
but never drove. All three are covered in this one document since each
extends, rather than replaces, what came before.

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
                                        |
                                     recover
                                        v
                                      active
```

`app/integration/lifecycle.py` is the single authority on which
transitions are valid — `ConnectorService` never inlines the graph
itself. Five named events: `configure`, `activate`, `disable`,
`mark_failed`, and (Phase 2.1.3) `recover`. Every actual transition (not
every write) appends a `connector_lifecycle_events` row and an
`AuthorizationAuditEvent.INTEGRATION_CONNECTOR_STATE_CHANGED` audit
entry — the two supplement each other rather than one replacing the
other: the table is the connector-specific queryable history
(`GET /connectors/{id}/events`); the audit service call keeps this
domain consistent with the platform-wide "every state change is
audited" convention every other RUNTIME_*/ROLE_*/etc. event already
follows.

`failed` was reachable from every other state (`mark_failed`) from
2.1.1 onward — the machine was already complete per that sub-phase's own
acceptance criteria — but nothing *drove* it automatically until Phase
2.1.3's `ConnectorHealthService`, which now calls the same, unchanged
`mark_failed` on a failing check (`active -> failed`) and the new
`recover` on a subsequent passing one (`failed -> active`). Neither is
exposed as a dedicated HTTP route in either sub-phase's own §7 — both
exist as real, directly-tested `ConnectorService` methods, driven
automatically by health checks and, before 2.1.3, only by direct/test
calls.

**Why `recover` is a new event, not folded into `activate`**: a
health-driven recovery and an operator activating a freshly-configured
connector are different operations with different preconditions (the
former only ever follows a passing health check; the latter never
touches health at all) — conflating them would make the audit trail
ambiguous about which actually happened.

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
| Connector SDK | 2.1.4 |
| Any real connector (REST, database, storage, queue) | 2.2.x |
| Identity federation (platform *user* login via an enterprise IdP — the opposite direction from connector auth, see below) | 2.3.1 |
| Converting a declared tool contract into an actual invokable `Tool` row bound into `tools_snapshot` (the "tool bridge") — 2.1.3 built the fail-fast *resolution* boundary it will call, not the bridge itself | 2.2.x |
| Any change to model or tool execution — Milestone 1 is untouched | done |
| Deployment strategies | Milestone 3 |
| A distributed job scheduler | Milestone 3 — 2.1.3's own health-check scheduler is explicitly interim, see below |

Two things worth calling out explicitly since they are easy to mistake
for scope creep: `_CONNECTOR_TYPES` in `app/integration/service.py` is a
small, private, in-process dict (`"MOCK" -> MockConnector`,
`"MOCK_AUTH" -> MockAuthenticatedConnector`) letting `ConnectorService`
turn a `connectors` row back into a live `Connector` instance when it
needs to call `validate_configuration()` — it is still not the
*dynamic-registration* half of what `ACT-INT-FR-040` describes (adding a
real connector type in 2.2.x still means adding a line to this dict, not
calling a public `register()`), though as of 2.1.3 the *lookup* half
(resolving an identifier to its implementation/config, listing
types/instances) has a real, dedicated surface —
`app/integration/registry.py`'s `ConnectorRegistry` — see below. And the
`Connector` ABC still has no `authenticate()` or `execute()` method
(2.1.2's `AuthScheme` framework applies a credential to a request
*outside* a connector's own code, never inside it; actually invoking a
connector is still the tool bridge's job, still out of scope until
2.2.x) — only `health_check()` was added, in 2.1.3, deliberately and
additively (see below).

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

## API (2.1.1)

Eight endpoints under `/api/v1/integration`, gated by two new
permissions (`integration.connector.view`, `integration.connector.manage`)
— see `app/integration/routes.py`. Every route scopes by
`actor.organization_id`, never a caller-supplied id, so cross-org access
returns a generic `CONNECTOR_NOT_FOUND` (404) rather than a 403 that
would confirm another org's instance exists — the same discipline every
other org-scoped resource in this codebase already follows.

## Testing (2.1.1)

`backend/tests/integration/test_connector_core.py`, 24 tests, grouped
exactly as the build prompt's own §8 groups its acceptance criteria:
abstraction (AC-01..06), type vs instance (AC-07..09), config validation
(AC-10..12), lifecycle (AC-13..19), API & integrity (AC-20..27 — the
suite-level ones are proven by the full-suite run, not duplicated here).
Every pre-existing test (994 total after this phase, was 970) passes
unmodified — `app/runtime/` was not touched.

---

## Authentication (Phase 2.1.2)

`ACT-INT-FR-020` through `FR-028`. A connector instance's declared
`auth_requirements.scheme` (2.1.1) now actually *resolves* to real,
encrypted, per-organization credentials — six pluggable schemes, applied
to a connector-neutral `OutboundRequest` fixture. Nothing yet invokes a
real connector end to end (that needs 2.1.3's registry and a real
connector, 2.2.x); this sub-phase proves the framework against
`MockAuthenticatedConnector` and fixtured HTTP transports instead.

### The direction this authenticates

Easy to conflate with 2.3.1 — deliberately not the same thing:

- **2.1.2 (this sub-phase)**: the **platform authenticates itself to an
  external system** on a connector's behalf (an API key, an OAuth2
  client-credentials grant, an mTLS client cert presented to a
  third-party API).
- **2.3.1 (identity federation, later)**: a **platform user** logs in
  via the enterprise's own IdP (OIDC/SAML). Opposite direction — a user
  authenticating *to* the platform, not the platform authenticating *to*
  something else.

### The six schemes

| Scheme identifier | What a connector author declares (`credential` body fields) | How it's applied |
|---|---|---|
| `API_KEY` | `api_key` (required), `header_name` (optional, defaults to `X-API-Key`) | Sets the named request header |
| `BEARER` | `token` | `Authorization: Bearer <token>` |
| `BASIC` | `username`, `password` | `Authorization: Basic <base64(username:password)>` |
| `OAUTH2_CLIENT_CREDENTIALS` | `client_id`, `client_secret`, `token_url` | Resolves a live access token via `token_manager` first, then `Authorization: Bearer <access_token>` |
| `OAUTH2_AUTHORIZATION_CODE` | `client_id`, `client_secret`, `authorize_url`, `token_url`, `redirect_uri` | Same as above, but the initial token pair comes from a code exchange (see below), not a direct grant |
| `MTLS` | `client_cert_pem`, `client_key_pem` | Sets `OutboundRequest.tls_client_cert` — configures the TLS handshake itself, never a header |

Adding a 7th scheme is a new `AuthScheme` subclass registered in
`app/integration/auth/registry.py` and nothing else — mechanically
proven by `test_ac02_adding_a_scheme_requires_only_a_registered_subclass`
(registers a throwaway scheme and exercises it through the existing,
unmodified resolution path) and by a runtime-never-knows-style grep
confirming zero connector/auth-scheme vocabulary anywhere under
`app/runtime/`.

### Storage — one encrypted bundle per `(instance, scheme)`

`connector_credentials` (migration `0034_connector_auth`) stores one row
per `(connector_instance_id, auth_scheme)`. The scheme's declared fields
are JSON-serialized into a single string and *that whole string* is what
gets encrypted — the table has no per-field plaintext column (`api_key`,
`client_secret`, etc. never appear as column names), only
`encrypted_secret` (ciphertext) and `secret_hint` (masked tail).

### Reusing `credential_crypto.py` — directly, no extraction needed

The build prompt's hard mandate was: extend the 5.7a.5 pattern, don't
build a second encrypted-secret store. `app/integration/auth/service.py`
imports `encrypt_secret`/`decrypt_secret`/`mask_hint` from
`app/runtime/providers/credential_crypto.py` and calls them directly —
**no extraction or generalization was needed**, because those three
functions already operate on plain strings with zero provider-specific
logic in any branch of their own code (only their module's docstring and
settings names mention "provider"). Phase 5.6a.1's `ToolCredentialService`
already set this exact precedent for tool credentials; connector
credentials are the second reuse of the same three functions, not a
third encryption implementation. `test_ac06`/`test_ac22` assert this by
identity (`svc_module.encrypt_secret is credential_crypto.encrypt_secret`),
not just by behavior.

**Inherited Known Deviation, not a new one**: connector credentials share
the exact same platform-held Fernet key
(`settings.MODEL_CREDENTIAL_ENCRYPTION_KEY`/`_PATH`) that provider
credentials (5.7a.5) and tool credentials (5.6a.1) already use. The key
necessarily enters process memory to encrypt/decrypt — accepted
pre-production, closes when Milestone 13 lands external KMS/vault
integration, exactly the closure condition 5.7a.5 recorded (itself
mirroring Phase 5.2.4's signing-key deviation). No new deviation entry
was added anywhere — this one already covers it.

### OAuth2 — acquisition, caching, transparent refresh

`app/integration/auth/token_manager.py` owns all three OAuth2 grant
types (client-credentials, authorization-code, refresh-token) behind one
shared HTTP call helper. Tokens are cached in `connector_oauth_tokens`
(one row per instance, encrypted access + refresh token independently)
and a resolution always returns a token with at least
`REFRESH_MARGIN_SECONDS` (60s) of remaining validity — never an expired
one.

**Concurrency-safe refresh**: `get_valid_access_token` takes a
`SELECT ... FOR UPDATE` lock on the *parent* `connector_instances` row,
not the token row itself. Locking the token row directly can't
serialize the very first acquisition (no row exists yet to lock, so two
concurrent first-callers would race an `INSERT`); the parent instance
row always exists, so locking it serializes both the "create" and
"refresh" cases uniformly and is semantically apt ("only one thread may
mutate this connector's credentials at a time"). The lock is held only
for check-then-refresh-then-commit; committing releases it immediately,
so a second, blocked caller re-checks expiry against the now-current row
and reuses the fresh token instead of refreshing again. Proven with real
threads and real Postgres connections in
`test_ac13_concurrent_refresh_does_not_double_refresh` (a fixture
transport with an artificial 0.3s delay widens the race window; the test
asserts the token endpoint was hit exactly once).

### Authorization-code: built vs. stubbed (stated plainly)

- **Built**: stored client configuration; `build_authorization_url()`
  (URL construction only); the `GET`/`POST .../oauth/callback` code→token
  exchange; and — the part the build prompt explicitly required —
  refresh-and-apply: given a stored refresh token, a valid access token
  is kept available and applied transparently on every resolution
  (`test_ac14`).
- **Stubbed**: the interactive consent-redirect UI itself. This backend
  builds the authorization URL a browser would be sent to, but nothing
  here renders a page or performs that redirect — an explicit front-end
  concern, out of scope per the build prompt's own allowance. No HTTP
  route exposes `build_authorization_url()` either, since the build
  prompt's own §7 endpoint table lists only the callback — a frontend
  needing the URL would call the (currently service-only) builder once a
  route is warranted, deferred rather than speculatively added.

### Rotation, mTLS, and validation

- **Rotation** (`ACT-INT-FR-026`): `PUT .../credentials` re-encrypts in
  place. An invocation that already resolved a credential holds a plain,
  in-memory snapshot with no live reference back to the row — rotation
  can't retroactively affect it. The next invocation resolves the new
  value. No mid-invocation re-resolution is attempted, exactly mirroring
  5.7a.5's rotation semantics.
- **mTLS** (`ACT-INT-FR-027`): cert + key are encrypted at rest exactly
  like any other credential; `MTLSScheme.apply()` sets
  `OutboundRequest.tls_client_cert` (never a header) and the private key
  is never assigned to anything beyond that one call's local variables —
  the same signing-key-grade discipline Phase 5.2.4 established for
  private key material.
- **Validation** (`ACT-INT-FR-028`): `POST .../credentials/validate`
  records `last_validated_at`/`validation_status`, never the credential
  itself. For the two OAuth2 schemes this is a real token
  acquisition/refresh attempt; for every other scheme, since no real
  connector exists yet to call, validation is a declared structural
  check (required fields present, bundle decrypts cleanly) — exactly as
  the build prompt's own §7 anticipated.

### API (2.1.2)

Seven new endpoints under `/api/v1/integration` — `GET /auth-schemes`,
`GET`/`PUT`/`DELETE .../credentials`, `POST .../credentials/validate`,
`GET`/`POST .../oauth/callback` — reusing 2.1.1's two permissions
(`integration.connector.view`/`.manage`) rather than adding a finer
`integration.credential.manage`: a credential is a property of a
connector instance, not a separately access-controlled resource, and
nothing in the SRS asked for a finer split.

## Testing (2.1.2)

`backend/tests/integration/test_connector_auth.py`, 31 tests, grouped
exactly as the build prompt's own §8 groups its acceptance criteria:
scheme framework (AC-01..05), encryption & reuse (AC-06..09), OAuth2
(AC-10..15), rotation/mTLS/validation (AC-16..18), redaction & integrity
(AC-19..30 — the suite-level ones are proven by the full-suite run, not
duplicated here). Every pre-existing test (1,025 total after this phase,
was 994) passes unmodified — `app/runtime/` was not touched, and every
2.1.1 test still passes with zero changes to `lifecycle.py`'s transition
graph or `ConnectorService`'s existing methods (only additive: one new
`_CONNECTOR_TYPES` entry).

---

## Registry & Health (Phase 2.1.3)

`ACT-INT-FR-040` through `FR-047`. A connector is now *discoverable and
monitored* — the missing piece between "configured and authenticated"
(2.1.1/2.1.2) and "invocable" (2.2.x).

### The registry — one lookup surface

`app/integration/registry.py`'s `ConnectorRegistry` wraps 2.1.1's
`ConnectorTypeService`/`ConnectorService` under a single surface rather
than duplicating their logic — type resolution (`resolve_type`/
`list_types`, platform-wide) and instance resolution (`list_instances`,
tenant-scoped). Its one genuinely new method,
`resolve_instance_for_invocation`, is the **fail-fast wiring point**
(`ACT-INT-FR-044`): it raises `ConnectorUnavailableError` immediately for
a `failed` or `disabled` instance, before anything downstream ever
attempts a real call. Phase 2.2.x's tool bridge is expected to call this
method first and inherit the fail-fast guarantee for free — with no
fail-fast logic of its own to write.

**Deliberately narrow, stated explicitly**: this only enforces the
`failed`/`disabled` guarantee `ACT-INT-FR-044` names. It does not also
require `active` — whether a merely `registered`/`configured` instance
may be invoked is 2.2.x's own invocation-semantics decision, not this
registry's job.

### Health checks — two independent probes, structurally separated

A check answers two questions, kept deliberately separate:

1. **Reachability** — `Connector.health_check(configuration)`, the one
   new abstract method the ABC gained this sub-phase (additive, expected
   — see below). Receives only the instance's own `configuration`,
   **never a credential**.
2. **Authentication validity** — reuses `ConnectorCredentialService.
   validate()` (2.1.2) entirely, rather than duplicating credential
   logic here or ever handing a connector's own code a decrypted secret.

This split is a deliberate security property: nothing in
`ConnectorHealthService`, and nothing in any connector's own
`health_check()`, ever sees a decrypted credential — only
`ConnectorCredentialService` itself does, exactly as before 2.1.3
existed. `MockConnector`/`MockAuthenticatedConnector`'s own
`health_check()` implementations are configurable via the instance's own
`configuration` (`simulate_unreachable`/`simulate_error`), so tests drive
every path through the ordinary API rather than a Python-level test
hook.

**`HEALTHY` vs `UNHEALTHY` vs `ERROR`**: `HEALTHY` only when both probes
pass (or auth is declared `NONE`); `UNHEALTHY` when a probe cleanly
reports false; `ERROR` when a probe *raises* — a distinct outcome,
since an error means the check itself couldn't reach a conclusion, not
that it concluded "down." `POST .../health/check` reflects this at the
HTTP layer too: a completed check (healthy or not) returns 200; a check
that couldn't complete raises `CONNECTOR_HEALTH_CHECK_FAILED` (502).

### The `Connector` ABC gained `health_check()` — additive, expected

Unlike the authentication-related methods 2.1.1 deliberately withheld
from the ABC (which belonged to 2.1.2, and still don't exist —
`authenticate()`/`execute()` remain absent), adding `health_check()` now
is this sub-phase's own explicit job, not scope creep. Every concrete
connector must implement it or cannot be instantiated — a genuine,
necessary contract change. This *did* require updating one already-shipped
2.1.1 test (`test_ac03_mock_connector_satisfies_the_interface_without_an_abc_change`,
which asserted the ABC's method set was exactly `{describe,
validate_configuration}`) — not a weakening: the assertion's actual
intent (MockConnector needs nothing beyond what the ABC declares) still
holds and is still checked; only the enumerated set was updated to match
the ABC's own, deliberate growth.

### Automated `failed`/`recover` transitions

`ConnectorHealthService` drives the state machine, never bypasses it: a
failing check on an `active` instance calls the same, unchanged
`ConnectorService.mark_failed` (already existed since 2.1.1); a passing
check on a `failed` instance calls the new `ConnectorService.recover`
(`failed -> active`, one new lifecycle event added this sub-phase — see
"The lifecycle state machine" above). Both go through
`ConnectorService._transition`, so the append-only lifecycle-event
history and the `INTEGRATION_CONNECTOR_STATE_CHANGED` audit trail cover
health-driven transitions identically to operator-driven ones.

### Alerting — no new channel built

`ACT-INT-FR-046` asks for an alert on `active -> failed`. This codebase's
only existing outbound-notification mechanism
(`app/services/notification_service.py`) is a direct SMTP sender with no
subscription/recipient-list concept to hook a per-connector, per-org
health event into — building one would be its own sub-phase's worth of
work, not a one-line addition. Instead, this sub-phase follows the exact
precedent Phase 5.6a.1 already set for `RUNTIME_TOOL_EGRESS_DENIED`: a
severity-tagged audit event, reviewed via a dashboard/query, not pushed.
Every health check emits `INTEGRATION_CONNECTOR_HEALTH_CHECKED`
(informational, every result); the *existing*
`INTEGRATION_CONNECTOR_STATE_CHANGED` event — unchanged from 2.1.1,
`ConnectorService._transition` now tags its `meta.severity` as
`CRITICAL` when `to_state == "failed"` (`INFO` otherwise) — **is** this
codebase's alerting signal for a failed connector. Not a dedicated new
event.

### Bounded history — a simple cap, not a time-based policy

`connector_health_checks` is append-only; after recording a check,
`ConnectorHealthService` deletes rows beyond the 200 most recent *per
instance*, always explicitly keeping the just-inserted row (guarding
against a same-transaction `checked_at` ordering tie rolling off the
very check that triggered the cleanup). A flat per-instance cap, not a
time window — revisit if per-instance check volume ever grows enough for
that distinction to matter; at the interim scheduler's own default
5-minute interval, 200 rows is the better part of a day's history,
comfortably more when checks are mostly on-demand.

### The interim scheduler — in-process, off by default, explicitly replaceable

REPO_STATE §10.2 is explicit: this codebase has no distributed job
scheduler, deliberately — Milestone 3 owns building one.
`app/integration/scheduler.py` is the simplest mechanism consistent with
that: one `asyncio` background task (started from `app/main.py`'s
`lifespan`), gated entirely by `settings.
CONNECTOR_HEALTH_SCHEDULER_ENABLED` (**default `false`, including every
test run** — AC-19's determinism requirement is satisfied structurally,
not by a test-only override). When enabled, it wakes on a plain interval
(`CONNECTOR_HEALTH_CHECK_INTERVAL_SECONDS`, default 300s) and calls
`run_sweep_once()` — a synchronous function that iterates every
currently-`active` instance across every organization and runs an
on-demand-equivalent check against each. No persistence of "which check
is due," no distributed lock, no retry queue. **Intended replacement
path**: delete this module and its one call site in `main.py`'s
lifespan; register the same iteration as a real Milestone-3 job. Nothing
here is designed to be extended in place into that system — tests call
`run_sweep_once()` directly rather than waiting on the loop's sleep, the
same "on-demand is the deterministic path" discipline the rest of this
sub-phase already follows.

### API (2.1.3)

Three new endpoints under `/api/v1/integration`, reusing 2.1.1/2.1.2's
two permissions: `GET .../health` (cached current status, no check run),
`POST .../health/check` (on-demand, records + transitions), `GET
.../health/history` (paginated, newest first).

## Testing (2.1.3)

`backend/tests/integration/test_connector_health.py`, 24 tests, grouped
exactly as the build prompt's own §8 groups its acceptance criteria:
registry (AC-01..04), health check (AC-05..10), transition & fail-fast
(AC-11..15), history & alerting (AC-16..18), scheduler & integrity
(AC-19..27 — the suite-level ones are proven by the full-suite run, not
duplicated here). Every pre-existing test (1,049 total after this phase,
was 1,025) passes unmodified except the one, documented, necessary
update to a 2.1.1 test described above — `app/runtime/` was not touched,
and 2.1.2's credential/auth handling is unchanged (`ConnectorCredentialService.
validate()`'s `actor` parameter became optional, additively, so the
scheduler's system-triggered checks can call it with no human actor —
every existing caller still passes a real one).
