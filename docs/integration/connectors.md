# Connector Abstraction, Lifecycle, Authentication, Health, SDK, Generic REST, Database & Storage Connectors (Phases 2.1.1 – 2.2.3)

`ACT-SRS-M2` §5.1–§5.4, §6.1–§6.3, `ACT-INT-FR-001` through `FR-066`,
`FR-100` through `FR-106`, `FR-120` through `FR-127`, and `FR-140` through
`FR-145`. The connector *framework* (2.1.1's spine, 2.1.2's pluggable
authentication, 2.1.3's registry/health, 2.1.4's containment-first SDK) is
Phase 2.1, complete as of 2.1.4. Phase 2.2.1 proved the framework with the
first real connector (REST). Phase 2.2.2 added the second, carrying this
milestone's sharpest SQL-specific rule: a **generic database connector**
where **the model never writes SQL.** Phase 2.2.3 adds the third — a
**generic file & object storage connector** — carrying that same rule's
direct analogue for a different kind of structure: **a model-supplied
path can never escape its declared scope.** Filesystem, and S3-compatible
object storage today; Azure Blob backend-pending. See "Generic File &
Object Storage Connector (Phase 2.2.3)" below for exactly how, and why
that is the connector's actual value proposition to a security-conscious
enterprise, not a limitation. All seven sub-phases are covered in this one
document since each extends, rather than replaces, what came before. What
remains in Milestone 2: 2.2.4 (queue connector) and 2.3.1 (identity
federation).

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
| Queue connector | 2.2.4 |
| SQL Server support for the database connector (`pyodbc`/system ODBC driver — driver-pending, abstraction ready) | not yet scheduled |
| Azure Blob support for the storage connector (`azure-storage-blob` — backend-pending, abstraction ready) | not yet scheduled |
| Natural-language-to-SQL of any kind | **permanently out of scope — the database connector's entire reason to exist is preventing exactly this** |
| Content parsing/extraction (PDF text, image analysis, chunking) through the storage connector — it moves bytes; the Knowledge Engine (Milestone 7) parses | Milestone 7 |
| GraphQL, and any vendor-specific connector (SAP/Salesforce/ServiceNow/etc.) | fast-follow, same REST/database/storage framework, triggered by named demand |
| Identity federation (platform *user* login via an enterprise IdP — the opposite direction from connector auth, see below) | 2.3.1 |
| Connector marketplace, publishing, signing, sandboxing of untrusted third-party code | Milestone 12 |
| Wiring a connector-derived tool into `tools_snapshot`/`AgentTool`/the model-driven tool loop — 2.2.1/2.2.2/2.2.3 each built a real, direct invocation bridge but none touches `ToolGatewayService` or execution | not yet scheduled |
| Any change to model or tool execution — Milestone 1 is untouched | done |
| Deployment strategies | Milestone 3 |
| A distributed job scheduler | Milestone 3 — 2.1.3's own health-check scheduler is explicitly interim, see below |

Two things worth calling out explicitly since they are easy to mistake
for scope creep: `_CONNECTOR_TYPES` in `app/integration/service.py` is a
small, private, in-process dict (`"MOCK" -> MockConnector`,
`"MOCK_AUTH" -> MockAuthenticatedConnector`, `"SDK_EXAMPLE_WEBHOOK" ->
WebhookConnector`, `"REST" -> RestConnector` as of 2.2.1, `"DATABASE" ->
DatabaseConnector` as of 2.2.2, and — as of 2.2.3 — `"STORAGE" ->
StorageConnector`) letting
`ConnectorService` turn a `connectors` row back into a live `Connector`
instance when it needs to call `validate_configuration()`. As of 2.1.4,
`ConnectorTypeService.register()` *is* a real, public, single
registration path — every `_CONNECTOR_TYPES` entry goes through it via
`ensure_seeded()`, and an author may call it directly too (see "Connector
SDK", below) — but adding a *new* first-party entry to the dict itself
still means editing this module's source, not a runtime
`POST /connector-types` call; the dict remains process-local, not a
database-driven catalog an operator edits without a deploy. As of 2.1.3,
the *lookup* half of `ACT-INT-FR-040` (resolving an identifier to its
implementation/config, listing types/instances) has a real, dedicated
surface — `app/integration/registry.py`'s `ConnectorRegistry` — see
below. The `Connector` ABC still has no `authenticate()` or `execute()`
method (2.1.2's `AuthScheme` framework applies a credential to a request
*outside* a connector's own code, never inside it) — only
`health_check()` was added, in 2.1.3, deliberately and additively (see
below). As of 2.2.1, a connector's declared endpoints **are** genuinely
invocable — through `app/integration/connectors/rest/invoker.py`, a
platform bridge sitting above the connector, never a method on the ABC
itself — see "Generic REST Connector", below, for what that bridge is
and, just as importantly, is not (it does not touch
`ToolGatewayService`/`tools_snapshot`/the model-driven tool loop). Phase
2.2.2 gives the database connector its own analogous bridge
(`app/integration/connectors/database/invoker.py`) — the same shape,
same boundary, same thing it deliberately does not touch. Phase 2.2.3
gives the storage connector a third
(`app/integration/connectors/storage/invoker.py`) — identical shape,
plus a new element none of the prior bridges needed: it records every
access attempt, allowed or denied, in the platform audit trail
(`ACT-INT-FR-145`) — see below.

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

---

## Connector SDK (Phase 2.1.4)

`ACT-INT-FR-060` through `FR-066`. With this sub-phase, the connector
*framework* (Phase 2.1) is complete: a `Connector` has an abstraction, a
lifecycle, six authentication schemes, a registry, health monitoring,
and now a documented, stable surface through which a trusted developer —
a customer's own integration engineer, not yet an adversarial
marketplace author (see "Scope", below) — can author one, safely,
without touching platform internals.

### What "the SDK" actually is

Not a new capability layered on top of 2.1.1–2.1.3 — a **formalization**
of the surface `MockConnector` was already using. `app/integration/sdk/
__init__.py` re-exports, by explicit name, exactly what an author needs:
the `Connector` base to subclass, the declaration types
(`ConnectorDescriptor`, `ToolContract`, `ConnectorLifecycleState`), a
`SUPPORTED_AUTH_SCHEMES` set to validate a declared `auth_requirements.
scheme` against, the one JSON-Schema config validator
(`validate_configuration_schema`), one governed network primitive
(`GovernedHttpClient`), and the testing harness
(`ConnectorTestHarness`/`HealthCheckOutcome`). Importing from
`app.integration.sdk` is the supported contract; importing from any
other `app.integration.*`/`app.runtime.*` module directly is not, and
those may change without notice — stated as the module's own first line
of documentation, not left implicit.

### The governing tension, and how the surface resolves it

An SDK invites code an author, not a platform maintainer, wrote. That
code must be easy to write correctly and *structurally* incapable of
being written dangerously — not "an author is told not to bypass egress,
skip authorization, opt out of audit, or mishandle credentials," but "the
SDK does not offer a method that would let them." Concretely, what is
**not** re-exported and why:

| Withheld | Why |
|---|---|
| Any database `Session`, `ConnectorService`/`ConnectorRegistry`/`ConnectorCredentialService` | A connector's own code (`describe`/`validate_configuration`/`health_check`) never receives a session, an organization id, or any handle that could reach another tenant's data — the ABC's own method signatures are structurally incapable of it |
| `AuthScheme`/`OutboundRequest`, credential resolution, a way to register a new scheme | An author *declares* a scheme identifier; they never see, handle, or apply a decrypted credential — that happens entirely in `app.integration.auth`, outside a connector's own code, exactly as 2.1.2 already established |
| `httpx`/`requests`/raw sockets, `egress_guard`/`http_executor` directly | `GovernedHttpClient` is the *only* network primitive on the surface — every call is policy-checked against the host(s) it was built with, before any DNS lookup or socket opens |
| `AuthorizationAuditService`, any audit-suppression flag | No method on the surface accepts anything resembling "skip audit" |
| Any route-registration mechanism | A connector's actions reach the platform exclusively through the existing, permission-gated `app/integration/routes.py` surface — the SDK offers no way to add a second, ungated entry point |

### `GovernedHttpClient` — the one network primitive

`app/integration/sdk/http.py`, a thin, connector-facing wrapper over
Milestone 1's own SSRF-hardened path
(`app.runtime.tools.egress_guard`/`http_executor`) — **reused directly,
not reimplemented**, per the build prompt's own instruction. Two
properties make it safe by construction rather than by convention:

1. **`allowed_hosts` is fixed at construction, never a per-call
   argument.** Neither `request()` nor `evaluate()` accepts a host
   override — a connector's own code cannot widen what it may reach at
   the moment it makes a call, only at the moment it builds the client,
   which in every intended usage is derived from the instance's own
   declared configuration (exactly the shape the worked example's
   `webhook_url` already is).
2. **`evaluate()` is a pure, offline policy check** — no socket, and no
   DNS unless a host actually clears the allowlist first (`evaluate_url`
   checks the allowlist *before* resolving). This is what makes "a call
   to an undeclared host is denied" (AC-11) verifiable with zero live
   network or mocked transport: the denial happens at the allowlist
   check alone.

### Completeness enforcement — one check, two callers, no privileged path

`app/integration/validation.py`'s `validate_declaration_complete()` is
the single place a connector type's declaration is checked before
registration: non-empty `config_schema`/`capabilities`/`tool_contracts`
(each tool contract itself well-formed), a declared `auth_requirements.
scheme` that is either `NONE` or a real, registered identifier, and a
`health_check()` that is more than a placeholder. Two callers, both
calling this exact function — `ConnectorTypeService.register()` (the
real registration path) and `ConnectorTestHarness.
assert_declaration_complete()` (so an author proves their connector will
register *before* ever touching a database) — there is no second,
weaker check for SDK-authored connectors.

**Detecting an unimplemented `health_check()`.** The ABC already
guarantees the method exists (`TypeError` at instantiation otherwise,
2.1.1's own AC-02) — what it cannot guarantee is that the method does
anything real. `validate_declaration_complete` calls `health_check({})`
once, as a smoke probe; a placeholder body that raises
`app.integration.validation.HealthCheckNotImplemented` (a dedicated
marker — deliberately **not** Python's own generic "unimplemented
method" builtin, since an existing 2.1.3 test greps this entire package
for exactly that builtin's name as a leftover-stub signal, and colliding
with it would make that check meaningless) is treated as incomplete; any
other exception is treated as ordinary `ERROR`-path behavior — the same
distinction `ConnectorHealthService` itself already draws between
`ERROR` (a probe raised) and `UNHEALTHY` (a probe cleanly returned
`False`) — not a sign the method was never written.

### Registration parity — proven by construction, not asserted

`ACT-INT-FR-062` requires no privileged path for an SDK-authored
connector. Rather than build a parallel registration mechanism and then
prove it behaves identically to the first-party one, this sub-phase
registers its own worked example (`SDK_EXAMPLE_WEBHOOK`) in the *same*
`_CONNECTOR_TYPES` dict, right alongside `MOCK`/`MOCK_AUTH`, so it flows
through the identical `ensure_seeded()` → `register()` → database-insert
path every prior connector type already used. There is nothing to keep
in sync between "the first-party path" and "the SDK path" because there
is only one path.

### The worked example — `WebhookConnector`

`app/integration/sdk/example/webhook_connector.py`: a minimal outbound
webhook connector — one declared tool (`send_notification`), `BEARER`
authentication, and a `health_check()` that pre-flights its own declared
`webhook_url` host through a `GovernedHttpClient` built from *that same
host* — built and tested using **only** names imported from
`app.integration.sdk` (plus the standard library). This is not a style
choice; it is the sub-phase's own required proof (AC-02): if expressing
a real, if minimal, connector had required reaching past
`app.integration.sdk`, the surface would have been incomplete, and the
build prompt's own instruction was to fix the surface, not route around
it. It did not — confirmed by an AST-based test
(`test_ac02_example_imports_only_from_the_sdk_surface`) that inspects
the file's own import statements, not just its behavior. Its own tests,
in a dedicated `test_connector_sdk_example.py`, are held to the same
standard for *their* imports (AC-03) — kept in a separate file
specifically so that file's own import list is a clean, isolated proof,
undiluted by the broader platform-internal imports this sub-phase's
other, governance-proving tests legitimately need.

### Testing utilities — the pattern `MockConnector` already used, packaged

`app/integration/sdk/testing.py`'s `ConnectorTestHarness` wraps one
connector instance under test and exercises `describe()`/
`validate_configuration()`/`health_check()`/a named `ToolContract`
directly, in-process — no live external system, no database, no network
call of the harness's own (a connector's own `health_check()` may choose
to make one through `GovernedHttpClient`; the harness neither requires
nor prevents that). `HealthCheckOutcome.reachable` is `None` when the
call raised, mirroring `ConnectorHealthService`'s own `ERROR`/`UNHEALTHY`
split, so a harness caller asserts either outcome without writing its
own `try`/`except`.

### Scope — trusted authors, not an adversarial marketplace (stated explicitly)

This SDK targets **first-party and trusted-enterprise authors**: a
customer's own integration engineers, writing connectors they deploy in
their own tenant, in good faith, against a contract that makes the
dangerous mistakes structurally unavailable. It is **not** a sandbox for
running actively adversarial third-party code — the containment problem
of a connector *deliberately* trying to escape or exfiltrate belongs to
Milestone 12's marketplace, which builds on these guarantees but must
additionally assume hostile intent (arbitrary code execution inside the
platform process is not, today, sandboxed at the OS/process level for
connectors any more than it is for any other in-process Python code).
The SDK module's own docstring states this boundary directly rather than
leaving it implied — "the SDK offers no dangerous affordance" is not the
same claim as "arbitrary code is safe to execute here."

### No migration

Every table this sub-phase's authoring surface touches already exists
(`connectors`, `connector_instances`, and everything 2.1.2/2.1.3 added).
The SDK is an authoring surface over that existing schema, not a new
concept requiring storage of its own — migration head remains
`0035_connector_health`.

## Testing (2.1.4)

`backend/tests/integration/test_connector_sdk.py` (surface, registration
parity & completeness, governance inheritance, testing utilities,
integrity) and `test_connector_sdk_example.py` (the worked example's own
SDK-harness-only tests), grouped exactly as the build prompt's own §8
groups its acceptance criteria: surface (AC-01..04), registration parity
& completeness (AC-05..09), governance inheritance (AC-10..15 — the
containment core), testing utilities (AC-16..18), integrity (AC-19..24 —
the suite-level ones are proven by the full-suite run, not duplicated
here). Every pre-existing test passes unmodified — no ABC method
changed, no existing service method's signature changed beyond the
purely additive `ConnectorTypeService.register()`, and `app/runtime/`
was not touched.

## Generic REST Connector (Phase 2.2.1)

`ACT-SRS-M2` §6.1, `ACT-INT-FR-100` through `FR-106`. The connector
framework's first real job, and the SDK's first real proving ground: a
`RestConnector` that turns any typical HTTP/JSON API into governed tools
by declaration — no vendor-specific code, ever, in the runtime or
anywhere else.

### What "the declaration" actually is

A REST connector *instance*'s `configuration` (validated by
`RestConnector.validate_configuration`, both structurally via a JSON
Schema and semantically via
`app/integration/connectors/rest/declaration.py::parse_declaration`) is
exactly:

```jsonc
{
  "base_url": "https://api.vendor-crm.example.com",
  "auth_scheme": "BEARER",                    // one of SUPPORTED_AUTH_SCHEMES
  "additional_allowed_hosts": ["auth.vendor-crm.example.com"],  // optional
  "allow_plaintext_http": false,               // optional, mirrors Tool.http_config's own escape hatch
  "endpoints": [
    {
      "name": "get_ticket", "method": "GET", "path": "/v1/tickets/{ticket_id}",
      "description": "Fetch a single ticket by id.",
      "parameters": {"type": "object", "properties": {"ticket_id": {"type": "string"}}, "required": ["ticket_id"]},
      "path_params": ["ticket_id"],
      "response_field": "data"
    },
    {
      "name": "list_tickets", "method": "GET", "path": "/v1/tickets",
      "description": "List tickets, optionally filtered by status.",
      "parameters": {"type": "object", "properties": {"status": {"type": "string"}}},
      "query_params": {"status": "status"},
      "pagination": {"style": "offset_limit", "page_size": 25, "items_field": "data.items"}
    }
  ]
}
```

Every endpoint becomes one distinct tool contract (`ACT-INT-FR-102`) —
name, description, and `parameters` (the tool's own argument schema)
carried straight through by
`declaration.py::tool_contracts_for(configuration)`. `path_params`/
`query_params`/`header_params`/`body_fields` say *where* each named
argument goes; `response_field` (a dotted path, or absent for "the whole
body") and an optional `output_schema` say how the response becomes the
tool's output; `pagination` declares one of three bounded strategies.

**Why `RestConnector.describe()` (the type-level, zero-argument call
every connector type answers) carries only a structural placeholder tool
contract, not the real per-instance ones.** `Connector.describe()` has no
configuration parameter — it can't know an instance's endpoints, because
no instance exists yet when a *type* registers. Rather than widen the
`Connector` ABC itself (which would ripple into `MockConnector`/
`WebhookConnector` too, for a capability only REST needs), the type-level
descriptor declares one honest, self-documenting placeholder purely to
satisfy `ACT-INT-FR-064`'s completeness check; `tool_contracts_for()` is
the real, per-instance mechanism `ACT-INT-FR-102` means. A deliberate,
reported design decision — see `connector.py`'s own docstring.

### Built through the SDK surface — proven, not asserted

`app/integration/connectors/rest/{declaration,templating,extraction,
pagination,connector}.py` import only from `app.integration.sdk` (or each
other) — the exact discipline 2.1.4's `WebhookConnector` established,
now proven against a connector that does a real job, via the same
AST-import-inspection test
(`test_rest_connector.py::test_ac15_the_connector_package_imports_only_from_the_sdk_surface_or_itself`).
`GovernedHttpClient` is the *only* outbound mechanism anywhere in the
package, including the invocation bridge (`invoker.py`) — no file imports
`httpx`/`requests`/a raw socket, verified the same way.

**A real SDK gap this connector found, and the fix.** `GovernedHttpClient
.request()` forwarded a caller's `url` straight to `execute_http_tool` as
`base_url` — but `execute_http_tool`'s own `_build_target_url` only ever
honors a query string supplied through its dedicated `query` parameter,
silently dropping one embedded in `base_url` itself. 2.1.4's
`WebhookConnector` never used a query string, so this never surfaced.
`list_tickets` (paginated, above) does. Rather than reach around the SDK
surface, `GovernedHttpClient.request()` gained one new, optional `query:
str | None` parameter (an already-encoded query string), forwarded
straight through — a small, deliberate, backward-compatible surface
addition, not a workaround. See `sdk/http.py`'s updated docstring.

### Injection-safe templating

Tool arguments are always *data*: a path argument is percent-encoded with
**no** safe characters (`urllib.parse.quote(value, safe="")`), so
`"123/../admin"` becomes the single, inert path segment
`"123%2F..%2Fadmin"` — it can never introduce an extra `/` and escape the
declared endpoint. A header or query argument containing `\r`/`\n`/NUL is
rejected outright before it ever reaches a request (header-injection
defense). A body argument is placed into the JSON body as its own
key/value — never string-interpolated — so its value can never alter the
body's own shape. See `templating.py`.

### Egress inheritance — nothing reimplemented

The declared `base_url`'s host, plus any `additional_allowed_hosts`, are
the only hosts `invoker.py` ever builds a `GovernedHttpClient` with — the
exact same SSRF-hardened allowlist/resolution/redirect-revalidation path
Milestone 1's own HTTP tool action uses, reused directly. A call to a
host the instance never declared is denied `HOST_NOT_ALLOWLISTED`; a
declared host that resolves to a private/link-local/loopback address
(the cloud-metadata vector, `169.254.169.254`, among them) is denied
`PRIVATE_ADDRESS` — before any socket is ever opened, exactly as for a
first-party tool call. `TOOL_EGRESS_DENIED` is reused for both, per the
build prompt's own instruction not to invent a REST-specific egress code.

### Bounded pagination

Three declared styles — `offset_limit`, `page_number`, `cursor` — each
walking pages until a short/empty one signals "done." All three share one
hard rule: the number of pages fetched is capped at
`min(declared max_pages, 100)` regardless of what the declaration or the
remote server claims, so a misconfigured or actively misbehaving API that
always signals "more" cannot force an unbounded fetch. See
`pagination.py`.

### The tool-invocation bridge — real, but deliberately narrow

**Finding**: as of 2.1.4, nothing converted a connector's declared
`ToolContract` into an actual invocation — `ConnectorRegistry.
resolve_instance_for_invocation` (2.1.3) resolves an instance to a plain,
fail-fast-checked snapshot, and its own docstring says "2.2.x's tool
bridge is expected to call this method first," but no such bridge existed
anywhere. A REST connector nobody can invoke proves nothing (build prompt
§3), so this sub-phase built one: `app/integration/connectors/rest/
invoker.py`'s `invoke_tool(db, organization_id, instance_id, tool_name,
arguments, ...)` — fail-fast resolves the instance, parses its
declaration, applies its declared `auth_scheme` via the existing
authentication framework, renders and dispatches the request through
`GovernedHttpClient`, drives pagination where declared, and extracts the
result. Proven completely end to end against a real local HTTP server in
`test_rest_connector_invocation.py` — including a genuine, stored,
encrypted `BEARER` credential (`ConnectorCredentialService`) actually
appearing as a real `Authorization` header on the request the server
receives, `RestConnector`'s own code never seeing it.

**Deliberately not wired into `ToolGatewayService`/`tools_snapshot`/the
model-driven tool loop** — Milestone 1's tool execution is untouched, per
this sub-phase's own working constraints. `invoke_tool` is a complete,
independently useful, independently tested capability in its own right;
a future milestone that assigns connector-derived tools to agents can
call it (or an equivalent) from wherever that wiring eventually lives,
without this bridge needing to change.

**Credentials, per-instance, generalized from 2.1.2's own precedent.**
Every connector type before 2.2.1 declared one fixed `auth_requirements.
scheme` for every instance of that type (`ConnectorCredentialService.
resolve_and_apply` reads it from the *type* row). A generic REST connector
serves many vendor APIs, each with its own scheme — so `auth_scheme` lives
in the *instance's* declaration instead (`ACT-INT-FR-101`), and
`ConnectorCredentialService` gained one small, additive public method,
`resolve_and_apply_for_scheme(instance, request, auth_scheme, ...)`, doing
exactly what `resolve_and_apply` always did but for an explicitly supplied
scheme; `resolve_and_apply` itself is now a one-line wrapper over it, and
every existing caller/test is unaffected. `RestConnector`'s own code still
never imports `app.integration.auth` at all — only `invoker.py` (the
bridge) does, proven by AST inspection alongside the SDK-surface check.

### The vendor-like declaration — the `ACT-INT-FR-106` proof

`test_rest_connector.py`'s `VENDOR_DECLARATION` is a plausible support-
ticketing CRM API — `create_ticket` (POST + body), `get_ticket` (GET +
path param), `list_tickets` (GET, offset/limit-paginated), `update_ticket`
(PATCH + path param + body) — configured entirely as the JSON shown
above, with no code, and (in `test_rest_connector_invocation.py`) driven
end to end against a real local fixture server. This is the concrete
claim `ACT-INT-FR-106` makes: a typical vendor REST integration is a
configuration document, not an engineering project.

### The expressiveness boundary — stated, not implied

This declaration model covers the common REST shapes: path/query/header/
body parameters, JSON bodies and responses, the six existing
authentication schemes, and three pagination styles. It does **not**
attempt streaming responses, multipart/form uploads, non-JSON content
types (XML, CSV), HATEOAS link traversal, or GraphQL (a fast-follow on
the same framework, not this connector's job). A vendor API needing any
of those needs either an extension to this declaration model (a
deliberate, future addition) or a dedicated connector — not a reason to
bend this one past what `ACT-INT-FR-106` actually asks for ("typical,"
not "universal").

### No migration

Every table this connector touches (`connectors`, `connector_instances`,
`connector_credentials`) already exists. A REST connector instance's
entire declaration lives in `connector_instances.configuration` — the
same JSONB column every connector instance already has. Migration head
remains `0035_connector_health`.

### API (2.2.1)

No new HTTP route. Registering the `REST` connector type reuses the
existing type-registration path (`ensure_seeded()`); configuring a REST
instance uses the existing `POST /connectors` /
`PATCH /connectors/{id}` endpoints with a REST declaration as the
`configuration` body. The invocation bridge (`invoker.invoke_tool`) is a
direct, database-backed Python entry point, not (yet) an HTTP route —
see "The tool-invocation bridge," above, for why.

New error codes: `REST_ENDPOINT_NOT_DECLARED` (a tool name with no
matching declared endpoint), `REST_TEMPLATE_INVALID` (a templating
failure — a missing required argument, or one that would alter request
structure), `REST_EXTRACTION_FAILED` (a response that doesn't match its
own declared `response_field`/`output_schema`, or isn't valid JSON at
all). `TOOL_EGRESS_DENIED` is reused for allowlist/SSRF denials, per the
build prompt's own instruction.

## Testing (2.2.1)

`backend/tests/integration/test_rest_connector.py` (declaration & tool
contracts AC-01..04, templating & extraction AC-05..09, pagination
AC-13..14 — pure, no HTTP at all — SDK-surface & integrity AC-15..25) and
`test_rest_connector_invocation.py` (the live half of AC-10..12, AC-18,
and AC-19 — every test that talks to "a server" talks to a real
`http.server` bound to `127.0.0.1` on an OS-assigned port, reached via an
injected DNS resolver, mirroring `test_http_tool_execution.py`'s own
established fixture-server convention; no test makes a real outbound call
to a non-local host). 41 new tests; every pre-existing test passes
unmodified — the one behavioral change outside the new package
(`GovernedHttpClient.request()`'s new `query` parameter) is additive and
backward compatible, and 2.1.4's own SDK test suite passes unchanged
against it.

## Generic Database Connector (Phase 2.2.2)

`ACT-SRS-M2` §6.2, `ACT-INT-FR-120` through `FR-127`. The connector
enterprises want most and fear most — and the one carrying this
milestone's single sharpest security rule.

### The model never writes SQL — this connector's actual security promise

Not sanitized SQL. Not escaped SQL. Not SQL passed through a validator.
**No model-authored SQL, ever, anywhere in this codebase.** An integration
engineer declares named, parameterized queries at *configuration* time —
reviewed, fixed, human-authored SQL text. A model's entire surface through
this connector is a query *name* (which must match a declaration exactly)
and parameter *values* (bound by the database driver, never interpolated
into SQL text). There is no method anywhere in
`app/integration/connectors/database/` that accepts a raw SQL string from
an invocation caller — not a weaker one, not an "advanced mode," not a
debug endpoint. `executor.py`'s `execute_declared_query` is the *only*
function that ever runs SQL against a real database, and its signature is
`(engine, dialect, query: DeclaredQuery, params, row_limit,
timeout_seconds)` — there is no parameter position a raw string could
occupy. This is containment by **absence**, not by a check that runs and
rejects — the same principle the SDK used for the raw HTTP client
(2.1.4) and 2.2.1 used for request templating, applied here at its most
consequential: a security-conscious enterprise can adopt this connector
specifically *because* it structurally cannot run model-authored SQL, not
merely because it is told not to.

### The declaration — one example

```jsonc
{
  "dialect": "POSTGRESQL",
  "host": "orders-db.internal.example.com",
  "port": 5432,
  "database": "orders",
  "auth_scheme": "BASIC",           // username/password, resolved via the existing credential framework
  "read_only": true,                // the default; write requires an explicit override
  "pool_size": 5, "max_overflow": 5,
  "default_row_limit": 500, "max_row_limit": 5000,
  "default_timeout_seconds": 10, "max_timeout_seconds": 60,
  "queries": [
    {
      "name": "get_order_status",
      "description": "Look up an order's current status by id.",
      "sql": "SELECT id, status, updated_at FROM orders WHERE id = :order_id",
      "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]},
      "row_limit": 1
    }
  ]
}
```

`:name` is SQLAlchemy's own dialect-agnostic named bind-parameter syntax —
declared once, translated to each dialect's native placeholder style
(`%(name)s` for psycopg2/PyMySQL, `?` for a future `pyodbc`) entirely
inside SQLAlchemy's own dialect layer (`drivers.py`). Every declared
query becomes one distinct tool contract (`ACT-INT-FR-121`), derived
per-instance by `declaration.py::tool_contracts_for()` — `DatabaseConnector
.describe()` itself (a zero-argument, type-level call) carries only a
structural completeness placeholder, for exactly the reason 2.2.1's
`RestConnector.describe()` does — see that section, above.

### Bound parameters, proven against a real database

`executor.py` passes the declared SQL text and the parameter mapping to
SQLAlchemy's `text()` construct *separately* — the SQL string and a
parameter's value never touch each other in Python code, so there is
nothing that could turn a value into structure even by accident. Proven,
not just asserted: `test_database_connector.py` binds
`"'; DROP TABLE users; --"` as a parameter value against this platform's
own real dev Postgres and asserts it comes back as an inert, literal
string — the `users` table is still there afterward — plus the classic
injection family (UNION, comment, stacked-query, boolean-blind) as
parameter values, all inert. A dedicated test also inspects the literal
SQL text SQLAlchemy hands to the DBAPI driver (via its own
`before_cursor_execute` event) and confirms it still contains the
placeholder token, never the substituted value — "bound, not
interpolated" verified by watching execution, not just checking the
outcome.

### Read-only by default, with defense in depth

An instance is read-only unless its configuration explicitly sets
`"read_only": false`. At **configuration time**, every declared query's
SQL is classified read/write by inspecting its first real (comment-
stripped) keyword — `SELECT`/`WITH`/`SHOW`/`EXPLAIN` read, anything else
write, fail-closed (an unrecognized statement is treated as a write, never
assumed safe). Inspecting this SQL is legitimate specifically because it
is *declared and trusted* — authored by a human at configuration time,
never derived from model output; this is the same distinction the build
prompt itself draws, and the reason this classification does not
contradict "the model never writes SQL." A read-only instance declaring a
mutating query is rejected outright with `DB_WRITE_NOT_PERMITTED` before
it is ever stored. **Defense in depth, stated plainly**: this platform-
level enforcement is a second layer, not a substitute for the DBA also
granting the connection's own database role read-only privileges — an
enterprise should do both.

### Limits, enforced two ways

**Row limit** — every declared query fetches via `fetchmany(row_limit +
1)`, never a bare `fetchall()`, so memory use is bounded regardless of the
true result size. A result exceeding the limit is **rejected outright**,
never silently truncated — a truncated result handed to a model could
read as a complete, misleading answer, the same reasoning behind
Milestone 1's `TOOL_RESPONSE_TOO_LARGE`.

**Timeout** — enforced twice, not once: a server-side statement-timeout
GUC (`SET LOCAL statement_timeout` for PostgreSQL, `SET SESSION
MAX_EXECUTION_TIME` for MySQL) bounds the query at the database itself,
and a client-side wall-clock bound (a single-worker thread +
`Future.result(timeout=...)`) is the backstop that guarantees
`DB_QUERY_TIMEOUT` is raised even if a dialect's own setting somehow
doesn't fire. Python cannot forcibly cancel a blocked DBAPI call, so a
client-side timeout doesn't kill the worker thread outright — it stops
waiting on it; the thread itself exits once the (already-set) server-side
timeout aborts the query moments later, a bounded, self-resolving
condition, not a permanent leak. Verified live: a `pg_sleep(3)` query
declared with a 1-second timeout is terminated in just over one second,
not three.

### Drivers — PostgreSQL and MySQL fully supported, SQL Server driver-pending

Built on SQLAlchemy Core (already this codebase's own database toolkit,
not a new dependency introduced for this connector). `drivers.py` maps
each supported dialect to its own SQLAlchemy drivername
(`postgresql+psycopg2`, `mysql+pymysql`) and builds connection URLs via
`sqlalchemy.engine.URL.create()` — a structured object, never a bare
string, so a password never has to be concatenated into (and risk being
logged from) a connection string anywhere in this codebase.

**SQL Server is a recognized, driver-pending value, not a silent gap.**
`"SQLSERVER"` is accepted by the JSON Schema so a misconfigured instance
gets a specific "driver-pending" message instead of a bare "invalid enum
value" — but no `pyodbc`/ODBC driver dependency was added this phase.
`mssql+pyodbc` requires the Microsoft ODBC Driver for SQL Server installed
at the *system* level (not a pip package), genuinely heavy and
platform-awkward to add sight-unseen in this environment — the build
prompt's own explicit allowance. Adding it later is a new
`_DIALECT_DRIVERNAME` entry plus the system driver; nothing else in the
abstraction changes.

**One new dependency**: `PyMySQL` (pure-Python MySQL DBAPI driver, no
system client library needed, unlike `pyodbc`) — added to
`requirements.txt` specifically for the MySQL dialect. PostgreSQL support
needed no new dependency (`psycopg2-binary` already backs the platform's
own database).

### Connection pooling and credential protection

Each connector instance gets its own SQLAlchemy `Engine` (and therefore
its own connection pool, sized by the instance's own `pool_size`/
`max_overflow`), cached per-instance in-process so repeated invocations
reuse the pool rather than rebuilding it on every call — an `Engine` is
meant to be a long-lived, per-target factory, not recreated per
invocation. A configuration change does not currently evict a cached
engine — a documented, known limitation, acceptable since reconfiguration
is rare relative to invocation volume.

A database credential (username/password) resolves through the identical
encrypted-storage machinery every other connector credential already
uses (`ConnectorCredentialService`, `connector_credentials`, Fernet
encryption) — but not through `resolve_and_apply_for_scheme()` itself,
which returns an HTTP-header-shaped `OutboundRequest` that has no natural
meaning for a database connection. `ConnectorCredentialService` gained
one new, small, additive public method, `resolve_credential_bundle()`,
returning the decrypted bundle itself rather than an applied HTTP
request — the same resolve-then-refresh mechanics (including the OAuth2
access-token step, for parity), just handed to a DBAPI driver's own
`connect()` call instead of a header. Proven live: a stored, encrypted
`BASIC` (username/password) credential is what the bridge actually
connects to this platform's own dev Postgres with — confirmed by asking
the database itself who is connected (`SELECT current_user`), not by
inspecting internals. The credential is never in the connector's own
code (`DatabaseConnector` imports no auth machinery, no SQLAlchemy, no
database driver, and does not even receive a credential in its
`health_check()` — see below), never in a returned row, and never in any
raised error message (`executor.py`'s `_safe_message` reduces every
driver-level failure to a generic, safe summary — the exception's class
name only, never its own message text, which can embed a DSN, host, or
credential fragment depending on the failure).

### `health_check()` — TCP reachability only, no credential, no query

A database connector's `health_check(configuration)` never receives a
credential in the first place (the ABC's own contract — a credential
lives in the separate, encrypted `connector_credentials` store, never in
`configuration`), so unlike a REST connector's offline `GovernedHttpClient
.evaluate()`, there is no equivalent "check without connecting" path for
a database protocol. Instead, `health_check` opens a raw TCP connection
to the declared `(host, port)` with a short timeout and closes it —
proving "the database server is reachable at the network level" without
attempting authentication or running any query at all.

### The tool-invocation bridge

`app/integration/connectors/database/invoker.py` mirrors 2.2.1's own
`invoker.py` exactly: fail-fast resolves the instance (the unchanged
2.1.3 registry), resolves its credential bundle, gets or creates its
per-instance connection pool, validates the caller's parameters against
the named query's own declared JSON Schema (`DB_PARAMETER_INVALID` on
failure), and executes through `executor.py`. **Deliberately not wired
into `ToolGatewayService`/`tools_snapshot`/the model-driven tool loop** —
the same boundary 2.2.1 drew, for the same reason (Milestone 1 stays
untouched).

### The one justified SDK-surface deviation

`declaration.py` stays exactly as SDK-surface-restricted as 2.2.1's own
`declaration.py` — it imports only from `app.integration.sdk` and the
standard library, raising only `ConnectorConfigInvalidError` for every
structural/semantic problem. `connector.py` has **one** additional,
specific, documented import beyond the SDK surface:
`DbWriteNotPermittedError` from `app.integration.errors`, needed because
`ACT-INT-FR-125` requires its own distinct, stable error code at
*configuration* time (`DB_WRITE_NOT_PERMITTED`) — something 2.2.1 never
needed, since nothing about a REST declaration is rejected at
configuration time with its own dedicated code. Widening the SDK's own
`ConnectorConfigInvalidError` to carry a distinguishable reason for every
connector type would have been a larger, riskier change for a need only
this one connector has; importing one additional, narrow exception type
is the smaller, more honest alternative — exactly the kind of "justified,
reported surface addition" this sub-phase's own acceptance criteria (AC-20)
anticipate.

### Expressiveness boundary

This connector runs exactly what is declared: named, parameterized,
single-statement SQL queries with a JSON-Schema parameter contract, a row
limit, and a timeout. It does not offer query building, ORM-style
composition, schema introspection, multi-statement transactions spanning
more than one declared query, or streaming/cursor-based pagination of
enormous result sets (the row-limit-reject policy exists precisely so
"the result was too big" is a loud, explicit failure, not something this
connector tries to paper over with partial pages). None of that is
missing by oversight — each is either out of this sub-phase's scope
(§3) or contradicts the containment model this connector exists to
enforce.

### No migration

Every table this connector touches (`connectors`, `connector_instances`,
`connector_credentials`) already exists. A database connector instance's
entire declaration lives in `connector_instances.configuration`, the same
JSONB column every connector instance already has; its credential uses
the existing `connector_credentials` table unchanged. Migration head
remains `0035_connector_health`.

### API (2.2.2)

No new HTTP route. Registering the `DATABASE` connector type reuses the
existing type-registration path; configuring an instance uses the
existing `POST`/`PATCH /connectors` endpoints with a database declaration
as the `configuration` body. The invocation bridge
(`invoker.invoke_tool`) is a direct, database-backed Python entry point,
mirroring 2.2.1's own API scope exactly.

New error codes: `DB_QUERY_NOT_DECLARED`, `DB_PARAMETER_INVALID`,
`DB_WRITE_NOT_PERMITTED`, `DB_RESULT_LIMIT_EXCEEDED`, `DB_QUERY_TIMEOUT`,
and one addition beyond the build prompt's own list —
`DB_CONNECTION_FAILED` — needed so a connection-level failure has a
distinct, assertable code that never echoes a connection string. There is
deliberately **no** "raw SQL rejected" error code: no code path accepts
raw SQL in the first place, so no error is ever needed to reject it.

## Testing (2.2.2)

`backend/tests/integration/test_database_connector.py` (the security core
AC-01..06, declared queries & parameters AC-07..10, read-only & limits
AC-11..14 — most running directly against this platform's own real dev
Postgres, not mocks — drivers/pooling/credentials AC-15..19, SDK-surface &
integrity AC-20..29) and `test_database_connector_invocation.py` (the
live-credential half of AC-18/AC-21 and the end-to-end bridge proof,
AC-23 — a real, database-backed `ConnectorInstance` with a real, stored,
encrypted `BASIC` credential, connecting to this platform's own dev
Postgres exactly as `db_session`/`SessionLocal` already do elsewhere in
this codebase — never a second database, never a mock). 42 new tests;
every pre-existing test passes unmodified.

**MySQL/SQL Server coverage boundary, stated explicitly**: the injection-
safety, bound-parameter, row-limit, and timeout tests all run against
real PostgreSQL — the only dialect this test environment has a live
server for. MySQL coverage in this phase is the driver-abstraction and
declaration-parsing level only (dialect dispatch, drivername mapping,
identical `:name` declaration syntax) — proven structurally, not against
a live MySQL server, since none is available in this environment. SQL
Server has no driver at all this phase (see above) and therefore no
coverage beyond the "recognized but driver-pending" rejection test. A
future phase (or whenever a live MySQL instance becomes available in
CI) should add the same live-injection proof MySQL currently lacks —
noted here rather than left silently implied as equivalent to
PostgreSQL's.

## Generic File & Object Storage Connector (Phase 2.2.3)

`ACT-SRS-M2` §6.3, `ACT-INT-FR-140` through `FR-145`. The database
connector's direct analogue applied to a structurally different kind of
danger: not a query language a model could inject into, but a
filesystem/object-store namespace a model could walk out of.

### A model-supplied path can never escape its declared scope — this connector's actual security promise

Not sanitized. Not escaped. Not validated-then-allowed-anyway. **A path
argument is canonicalized, then proven to resolve inside its declared
boundary, before any read or write is attempted — anything that cannot be
proven in-scope is denied outright, never "best-effort cleaned up and let
through."** The enforcement lives in exactly one module,
`app/integration/connectors/storage/scope.py`, and its one public
function, `resolve_and_contain(boundary, supplied_path)`, has no code
path that returns a value the caller hasn't already proven safe — it
either returns a validated, in-scope target or raises
`ScopeViolationError`. There is no method anywhere in this connector
package that performs a read or write against an unvalidated path; every
backend call in `backends.py` takes the *validated* target
`resolve_and_contain` produced, never the model's raw string. This is the
same containment-by-construction principle 2.2.2 used for SQL, applied
here to a namespace-escape instead of a syntax-injection: a
security-conscious enterprise can point this connector at a bucket of
customer documents specifically *because* no prompt, however crafted, can
make an agent read outside the folder it was scoped to — not because it
is told not to.

### Canonicalize, then contain — the enforcement pipeline

Every supplied path/key goes through the same four-stage pipeline before
any backend-specific logic runs:

1. **Reject control characters** in the raw input (including a literal
   NUL — `file.txt\0.png`).
2. **Percent-decode iteratively**, bounded rounds, so a supplied value is
   fully revealed before any traversal check runs against it — checking
   the raw string and decoding *afterward* would let an encoded `..`
   slip past a check that only ever saw the encoded form. This is what
   catches both single- (`%2e%2e%2f`) and double-encoded (`..%252f`)
   traversal in one pass: decode once, `%2e%2e%2f` → `../`, caught;
   decode twice, `..%252f` → `..%2f` → `../`, caught.
3. **Reject control characters revealed by decoding** (an encoded NUL,
   `file.txt%00.png`, is exactly as denied as a literal one).
4. **Unicode-normalize (NFKC)** so a homoglyph/fullwidth variant of `.`
   or `/` (U+FF0E, U+FF0F) collapses to its canonical ASCII form before
   the traversal check runs, rather than slipping through a naive
   `".." in path` check that never recognized the character in the first
   place.

Only *then* does backend-specific canonicalization run — and **the
canonicalized result, never the raw or partially-processed string, is
what gets contained-checked and returned as the operation's real
target.** This closes the TOCTOU/rebinding-shaped gap explicitly (the
storage analogue of validating a DNS name and then connecting to a
different, later-resolved IP): a caller cannot validate one string and
operate on a different, later-resolved one, because the function that
validates is the same function that hands back the only value a backend
is ever given.

### Two backends, one contract, different enforcement underneath

Filesystem paths and object-store keys are canonicalized differently
because they mean different things:

- **Filesystem** — real hierarchical paths, real directories, real
  symlinks. Canonicalization is `os.path.realpath`, which resolves both
  `..` segments *and* symlinks in one pass. Containment is then a
  straightforward prefix check against the declared base directory's own
  realpath. Because `realpath` resolves symlinks, **a path that is
  legitimately inside the declared scope but is itself a symlink
  pointing outside it is caught for free** — the same resolution step
  that defeats `../../etc/passwd` also defeats a symlink escape, proven
  live with a real temporary symlink (or, where creating one needs a
  privilege this environment doesn't grant by default, a Windows
  directory junction — also a reparse point `realpath` resolves
  identically).
- **Object storage** (S3-compatible, and Azure Blob once implemented) —
  keys are *flat strings* that only *look* hierarchical; there is no
  real directory to resolve against, so there is nothing for `realpath`
  to do. Canonicalization is lexical (`posixpath.normpath` on the
  prefix+supplied-key combination), and containment is a
  segment-respecting prefix check — `"reports"` does not wrongly contain
  `"reports-2/x"`, and a key that normalizes to `"../secrets/x"` or
  further still (`"../../../etc/passwd"`) is denied whether it only
  escapes the declared *prefix* or the *bucket* entirely.

One call signature, `resolve_and_contain(boundary, supplied_path)`,
dispatches to whichever canonicalization the declared backend needs —
mirroring exactly the "one abstraction, per-backend enforcement
underneath" shape 2.2.2's `drivers.py` established for SQL dialects,
applied here to scope enforcement instead of placeholder translation.

### Built and tested in complete isolation from any backend

`scope.py` has **zero dependencies on this platform** — not the SDK, not
`app.integration.errors`, not a database session, nothing beyond the
Python standard library (`os`, `posixpath`, `re`, `unicodedata`,
`urllib.parse`). It is importable and fully testable with no live
storage of any kind, the same isolation Milestone 1's egress guard was
built and tested with. `test_storage_scope.py` proves every traversal
vector named by this phase's own acceptance criteria — relative
traversal, absolute paths (POSIX, Windows drive-letter, UNC), percent-
and double-percent-encoding, backslash variants, null-byte truncation
(literal and encoded), Unicode homoglyph normalization, object-store
prefix/bucket escape (including the sibling-prefix boundary case,
`"reports"` vs. `"reports-2"`), and the filesystem symlink escape — with
a real temporary symlink/junction, never a mock — with **no live storage
anywhere in the file**.

### Declared scopes — one example

```jsonc
{
  "backend": "FILESYSTEM",
  "read_only": true,                     // the default; write requires an explicit override
  "default_max_object_size_bytes": 10000000, "max_max_object_size_bytes": 100000000,
  "scopes": [
    {
      "name": "read_customer_reports",
      "description": "Read a report file by its relative path.",
      "operation": "READ",
      "base_directory": "/srv/reports/acme-corp"
    }
  ]
}
```

```jsonc
{
  "backend": "S3",
  "endpoint_url": null,                  // real AWS S3; set to a MinIO URL for an S3-compatible target
  "region": "us-east-1",
  "auth_scheme": "BASIC",                // access_key_id/secret_access_key -- see below
  "scopes": [
    {
      "name": "read_q1_documents",
      "description": "Read a document from the Q1 reports prefix.",
      "operation": "READ",
      "bucket": "acme-data",
      "prefix": "reports/2026-q1"
    }
  ]
}
```

Each declared scope becomes one distinct tool contract (`ACT-INT-FR-141`)
whose only parameter is `path` — the bounded remainder of the key/path a
model supplies, exactly the value `resolve_and_contain` validates before
anything runs. `declaration.py::tool_contracts_for()` derives these
per-instance, mirroring 2.2.1/2.2.2's identical pattern —
`StorageConnector.describe()` itself carries only a structural
completeness placeholder, for the same reason those connectors' own
`describe()` methods do.

### Size limits, checked before any full transfer

A read checks the object's size via metadata *first* —
`os.path.getsize` for the filesystem backend, a `head_object` HEAD call
(never a GET) for S3 — and rejects with `STORAGE_OBJECT_TOO_LARGE`
before ever opening the file or fetching the object's bytes if it is
already too large. Both reads additionally bound the actual transfer
itself (`read(max_bytes + 1)`) as a second, defense-in-depth check
against a size that changes between the metadata check and the transfer
— the same "reject, never truncate" discipline 2.2.2 established for an
oversized query result. A write checks the in-memory payload's length
before ever calling the backend. Every size limit is two-tiered exactly
like the database connector's row limit: a scope's own
`max_object_size_bytes` (optional), capped by the instance's
`max_max_object_size_bytes`, falling back to
`default_max_object_size_bytes` when unset.

### Read-only by default, with defense in depth

An instance is read-only unless its configuration explicitly sets
`"read_only": false`. At **configuration time**, a read-only instance
declaring one or more `"WRITE"` scopes is rejected outright with
`STORAGE_WRITE_NOT_PERMITTED` before it is ever stored — mirroring
`DB_WRITE_NOT_PERMITTED` exactly. **Defense in depth, stated plainly**:
this platform-level enforcement is a second layer, not a substitute for
the storage credential itself being read-scoped (an S3 access key with
only `GetObject`, a read-only SAS token for Azure Blob) — an enterprise
should configure both.

### Backends — filesystem and S3-compatible fully supported, Azure Blob backend-pending

The filesystem backend needs no new dependency (`os`/`pathlib`, already
the standard library). The S3-compatible backend uses `boto3` — a new
dependency added specifically for this connector — via one small
dispatch layer (`backends.py`) that builds a client from the
declaration's `endpoint_url`/`region` (so the identical backend serves
real AWS S3 *or* any S3-compatible target, e.g. MinIO, by declaration,
never a code change) and the resolved credential.

**Azure Blob is a recognized, backend-pending value, not a silent gap.**
`"AZURE_BLOB"` is accepted by the JSON Schema so a misconfigured instance
gets a specific "backend-pending" message instead of a bare "invalid
enum value" — but no `azure-storage-blob` dependency was added this
phase. That SDK is a genuinely heavy dependency this environment cannot
exercise live, exactly the build prompt's own explicit allowance to mark
a backend pending with the abstraction ready rather than half-implement
it — the same treatment 2.2.2 gave SQL Server. Adding it later is a new
dispatch branch in `backends.py` plus the dependency; nothing else in
the abstraction changes.

### Credential protection

A storage credential resolves through the identical encrypted-storage
machinery every other connector credential already uses
(`ConnectorCredentialService`, `connector_credentials`, Fernet
encryption) via the same `resolve_credential_bundle()` method 2.2.2
added — an S3 access key id / secret access key is not naturally
HTTP-header-shaped any more than a database username/password is. The
`BASIC` auth scheme's generic `username`/`password` fields carry the
access key id / secret access key respectively — a deliberate,
documented reuse (no S3-specific field forcing a new `AuthScheme`),
exactly the generalization 2.2.2 established for a non-HTTP-shaped
credential. The credential is never in the connector's own code
(`StorageConnector` imports no auth machinery, no `boto3`, and does not
even receive a credential in its `health_check()` — see below), never in
a returned object's bytes, and never in any raised error message
(`backends.py`'s `_safe_message` reduces every backend-level failure to
a generic, safe summary — the exception's class name only) or audit
record (see below).

### `health_check()` — reachability only, no credential, no object access

For the filesystem backend, `health_check` checks that every declared
scope's own base directory actually exists as a real directory — no
credential involved, since a local filesystem has none. For the
S3-compatible backend, mirroring the database connector's own TCP-only
reachability check exactly, `health_check` opens a raw TCP connection to
the configured (or default AWS) endpoint host and closes it — proving
network-level reachability without authenticating or listing anything.

### The tool-invocation bridge, and its own new element: per-access audit

`app/integration/connectors/storage/invoker.py` mirrors 2.2.2's
`invoker.py` exactly: fail-fast resolves the instance (the unchanged
2.1.3 registry), resolves its credential bundle, validates the caller's
supplied `path` against the named scope's own declared boundary via
`scope.resolve_and_contain` **before any backend call**, and dispatches
through `backends.py`. **Deliberately not wired into
`ToolGatewayService`/`tools_snapshot`/the model-driven tool loop** — the
same boundary 2.2.1/2.2.2 drew, for the same reason.

**New this phase (`ACT-INT-FR-145`)**: every access attempt — allowed or
denied, read or write — is recorded in the platform audit trail
(`INTEGRATION_CONNECTOR_OBJECT_ACCESSED`, via the same
`AuthorizationAuditService` every other domain in this codebase already
writes through), carrying the backend, scope name, operation, the
*validated* path (never the raw supplied string — a denied traversal
attempt's audit record correctly carries no path at all, since none was
ever validated), size, and outcome (`SUCCESS`/`DENIED`/`NOT_FOUND`/
`TOO_LARGE`/`ERROR`) — via a `finally` block, so a denial is audited
exactly as reliably as a success. This is 2.2.x's first invocation-level
audit event; neither 2.2.1's nor 2.2.2's own build prompt required
auditing individual calls, so neither bridge does — this one's own build
prompt (`FR-145`) explicitly does, so this bridge is the first to.
Credentials are never part of the recorded `meta` — proven live against
a real, stored, encrypted credential.

### Two narrow, justified deviations from the SDK-surface-only discipline

Unlike 2.2.1's and 2.2.2's own `declaration.py` modules (which needed
none beyond the SDK's generic `ConnectorConfigInvalidError`), this
phase's own acceptance criteria explicitly require a distinguishable
`STORAGE_SCOPE_INVALID` code for a badly-shaped scope declaration —
`declaration.py::parse_declaration` raises it directly for its own
semantic checks (a scope missing the field its backend requires, a
duplicate scope name, a backend-pending value, a size limit that doesn't
fit its own instance-level caps). `connector.py` carries the second,
narrower deviation: `StorageWriteNotPermittedError`, for the one
config-time check that needs its own distinct code — exactly the shape
2.2.2's `connector.py` established for `DbWriteNotPermittedError`.
`scope.py` and `backends.py` both stay entirely free of
`app.integration.errors` — `scope.py` has zero platform dependencies at
all (see above), and `backends.py` raises only its own local exceptions,
translated to platform errors exclusively by `invoker.py`, mirroring
2.2.2's `executor.py` discipline exactly.

### Expressiveness boundary

This connector moves bytes within a declared scope: read an object,
write an object (if configured), bounded by a declared size limit. It
does not parse PDF text, analyze images, chunk documents for retrieval,
or offer directory listing, recursive copy, or streaming of arbitrarily
large objects through the model — a read returns size-bounded object
bytes; what happens to them is the Knowledge Engine's concern
(Milestone 7), not this connector's. None of that is missing by
oversight — each is either out of this sub-phase's scope (§3) or
contradicts the bounded-transfer model this connector exists to enforce.

### No migration

Every table this connector touches (`connectors`, `connector_instances`,
`connector_credentials`, `authorization_audit`) already exists. A
storage connector instance's entire declaration lives in
`connector_instances.configuration`, the same JSONB column every
connector instance already has. Migration head remains
`0035_connector_health`.

### API (2.2.3)

No new HTTP route. Registering the `STORAGE` connector type reuses the
existing type-registration path; configuring an instance uses the
existing `POST`/`PATCH /connectors` endpoints with a storage declaration
as the `configuration` body. The invocation bridge
(`invoker.invoke_tool`) is a direct, database-backed Python entry point,
mirroring 2.2.1/2.2.2's own API scope exactly.

New error codes: `STORAGE_PATH_DENIED`, `STORAGE_OBJECT_TOO_LARGE`,
`STORAGE_WRITE_NOT_PERMITTED`, `STORAGE_OBJECT_NOT_FOUND`,
`STORAGE_SCOPE_INVALID`, and one addition beyond the build prompt's own
list — `STORAGE_BACKEND_FAILED` — needed so a backend-level failure that
isn't "not found," "too large," or a scope denial has a distinct,
assertable, safe-message-only code (mirrors `DB_CONNECTION_FAILED`).
There is deliberately **no** "sanitization failed" code: a supplied path
is canonicalized then proven in-scope or denied outright — there is no
partial-sanitize outcome to name.

## Testing (2.2.3)

`test_storage_scope.py` (the isolated security core — every traversal
vector named by this phase's own acceptance criteria, with **no live
storage anywhere in the file**, including a real temporary symlink/
junction for the filesystem escape case), `test_storage_connector.py`
(scope/operations/limits, backend dispatch — filesystem against real
`tmp_path` I/O, S3 against a mocked `boto3.client` — SDK-surface &
integrity), and `test_storage_connector_invocation.py` (the live-database
half: end-to-end bridge invocation, per-access audit trail verification,
and credential-protection proof, against this platform's own real dev
database exactly as `db_session`/`SessionLocal` already do elsewhere in
this codebase — never a mock). 82 new tests; every pre-existing test
passes unmodified.

**S3/MinIO coverage boundary, stated explicitly**: no S3-compatible
server (MinIO or otherwise) is reachable in this environment, so the S3
backend's dispatch correctness (`head_object`/`get_object`/`put_object`
called with exactly the scope-validated bucket and key, and S3
not-found/error translation) is proven against a mocked `boto3.client`,
never a live object store. The *containment logic itself* — which key a
supplied value resolves to, and whether that resolution stays in
bounds — has full, unmocked coverage in `test_storage_scope.py`, since
that logic is backend-agnostic pure Python with no dependency on `boto3`
at all; only the "does this connector correctly call the S3 SDK with the
already-validated value" question is covered by a mock rather than a
live server. Azure Blob has no coverage beyond the "recognized but
backend-pending" rejection test, since it has no live implementation
this phase (see above). A future phase (or whenever a local MinIO
instance becomes available in this environment) should add the same
live-object-store proof PostgreSQL already has for the database
connector — noted here rather than left silently implied as
equivalent.
