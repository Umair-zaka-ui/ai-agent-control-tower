# Connector Abstraction, Lifecycle & Authentication (Phases 2.1.1 – 2.1.2)

`ACT-SRS-M2` §5.1–§5.2, `ACT-INT-FR-001` through `FR-028`. These are the
first two sub-phases of Milestone 2 (Enterprise Integration Framework) —
2.1.1 is the spine every later connector is built on; 2.1.2 is the
pluggable authentication framework that lets a connector instance hold
real, encrypted credentials for six schemes, including transparent
OAuth2. Both are covered in this one document since 2.1.2 extends,
rather than replaces, everything below the "Authentication" heading.

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
| Connector registry (dynamic type registration/resolution), health monitoring | 2.1.3 |
| Connector SDK | 2.1.4 |
| Any real connector (REST, database, storage, queue) | 2.2.x |
| Identity federation (platform *user* login via an enterprise IdP — the opposite direction from connector auth, see below) | 2.3.1 |
| Converting a declared tool contract into an actual invokable `Tool` row bound into `tools_snapshot` (the "tool bridge") | lands once 2.1.3 exists |
| Any change to model or tool execution — Milestone 1 is untouched | done |
| Deployment strategies | Milestone 3 |

Two things worth calling out explicitly since they are easy to mistake
for scope creep: `_CONNECTOR_TYPES` in `app/integration/service.py` is a
small, private, in-process dict (`"MOCK" -> MockConnector`, and, as of
2.1.2, `"MOCK_AUTH" -> MockAuthenticatedConnector`) letting
`ConnectorService` turn a `connectors` row back into a live `Connector`
instance when it needs to call `validate_configuration()` — it is
explicitly **not** the connector registry `ACT-INT-FR-040`/`FR-041`
describes (no dynamic registration, no public resolution API, no health
awareness) and is expected to be superseded entirely once 2.1.3 lands.
And the `Connector` ABC deliberately has no `authenticate()`, `execute()`
or `health_check()` method — adding one now would be building ahead of
the sub-phase that actually needs it, exactly the temptation the build
prompt warned against. (2.1.2 added an `AuthScheme` framework, but a
connector's own `authenticate()` — actually *invoking* a scheme against
a real outbound call — is still absent, since no real connector invokes
anything yet.)

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
