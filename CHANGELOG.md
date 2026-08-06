# Changelog

All notable changes to the AI Agent Control Tower are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/); the project is pre-1.0 and
versions track the roadmap phases rather than semver guarantees.

## [Unreleased] — Phase 2.2.2 · Generic Database Connector

**Milestone 2's second real connector — and the one carrying its single sharpest security rule: the model never writes SQL.** Not sanitized, not escaped, not validated-then-run — absent. There is no code path anywhere in this codebase that takes model-derived text and places it into SQL structure.

- **Added** `app/integration/connectors/database/` — `DatabaseConnector`, built through the SDK surface (one specific, documented, justified deviation — see below), turning declared, parameterized queries against PostgreSQL/MySQL into governed tools. SQL Server is a recognized but driver-pending dialect (`mssql+pyodbc` needs a system ODBC driver, not added this phase).
- **Added** `executor.py`, the security-critical component: its **only** public entry point, `execute_declared_query(engine, dialect, query: DeclaredQuery, params, row_limit, timeout_seconds)`, has no parameter position a raw SQL string could occupy — containment by absence, not a rejecting check. Parameters bound via SQLAlchemy's `text()` + a separate parameter mapping, never interpolated — proven against this platform's own real dev Postgres: `"'; DROP TABLE users; --"` and the classic UNION/comment/stacked-query/boolean-blind injection family all come back as inert literal values.
- **Added** row-limit (`fetchmany(row_limit + 1)`, rejected outright — never silently truncated — if exceeded) and timeout enforcement (a server-side `statement_timeout`/`MAX_EXECUTION_TIME` GUC plus a client-side thread + `Future.result(timeout=...)` backstop; a 3-second `pg_sleep` declared with a 1-second timeout terminates in ~1 second).
- **Added** read-only-by-default posture (`ACT-INT-FR-125`): every declared query's *trusted, human-authored* SQL (never model output) is classified read/write at configuration time by its first real keyword, fail-closed; a read-only instance declaring a mutating query is rejected outright with a new `DB_WRITE_NOT_PERMITTED`.
- **Added** `app/integration/connectors/database/invoker.py` — the tool-invocation bridge, mirroring 2.2.1's own exactly: fail-fast resolves the instance, resolves its credential bundle, gets/creates its per-instance connection pool, validates parameters against the named query's own declared schema, executes — proven end to end against this platform's own real dev Postgres, including a genuine stored/encrypted `BASIC` credential actually authenticating the connection (confirmed via `SELECT current_user`). **Not wired into `ToolGatewayService`/`tools_snapshot`/the model-driven tool loop** — Milestone 1 stays untouched.
- **Added** `ConnectorCredentialService.resolve_credential_bundle()` — an additive method returning the decrypted credential bundle itself rather than an HTTP-header-shaped `OutboundRequest`, since a database username/password has no natural HTTP-header meaning; shares its resolve/decrypt/OAuth2-refresh mechanics with 2.2.1's `resolve_and_apply_for_scheme()` via a new private helper.
- **The one justified SDK-surface deviation**: `connector.py` imports one specific, documented exception type (`DbWriteNotPermittedError`) beyond the pure-SDK-surface discipline 2.2.1 established, needed because `ACT-INT-FR-125` requires its own distinct, stable error code at configuration time — something 2.2.1 never needed. `declaration.py` itself stays exactly as SDK-surface-restricted as 2.2.1's own equivalent module.
- **Added** connection pooling per instance (an SQLAlchemy `Engine`, cached in-process per connector instance id, configurable `pool_size`/`max_overflow`) and credential protection (connection URLs built via `sqlalchemy.engine.URL.create()`, never a bare string; every driver-level failure reduced to a generic, safe message — never the connection string, host, or credential).
- **Added** six new error codes: `DB_QUERY_NOT_DECLARED`, `DB_PARAMETER_INVALID`, `DB_WRITE_NOT_PERMITTED`, `DB_RESULT_LIMIT_EXCEEDED`, `DB_QUERY_TIMEOUT`, and `DB_CONNECTION_FAILED` (the last one beyond the build prompt's own list — a small, justified addition so a connection failure has a distinct, assertable code that never echoes the connection string). Deliberately **no** "raw SQL rejected" code — no code path accepts raw SQL, so none is ever needed to reject it.
- **New dependency**: `PyMySQL` (pure-Python MySQL DBAPI driver, no system client library needed) for the MySQL dialect. PostgreSQL needed no new dependency (`psycopg2-binary` already backs the platform's own database).
- **Explicitly out of scope, per the build prompt**: storage/queue connectors (2.2.3/2.2.4), vendor-specific connectors, identity federation (2.3.1), **natural-language-to-SQL of any kind — permanently out of scope, the anti-goal this connector exists to prevent**, any change to model/tool execution.
- **No migration** — every table touched already exists (`connectors`/`connector_instances`/`connector_credentials`). **No new HTTP route** — instance configuration reuses the existing `POST`/`PATCH /connectors` endpoints; the invocation bridge is a direct, database-backed Python entry point.
- **MySQL/SQL Server coverage boundary stated explicitly**: injection-safety, bound-parameter, row-limit, and timeout tests all run against real PostgreSQL — the only dialect this test environment has a live server for. MySQL coverage this phase is driver-dispatch/declaration-parsing only, not proven against a live server; SQL Server has no driver and only the driver-pending rejection is tested.
- 42 new backend tests (`tests/integration/test_database_connector.py`, 35 — security core/declared-queries/read-only/limits/drivers/SDK-surface/integrity, most against real Postgres; `test_database_connector_invocation.py`, 7 — end to end against a real, database-backed `ConnectorInstance` with a real, stored, encrypted credential). Backend **1,163** green (1,121 + 42), 0 failed, 1 deselected; frontend untouched by this backend-only phase, still **297** green. See [docs/integration/connectors.md](docs/integration/connectors.md)'s "Generic Database Connector" section.

## [Unreleased] — Phase 2.2.1 · Generic REST Connector

**Milestone 2's first real connector, and the SDK's first real proving ground.** Any typical HTTP/JSON API becomes governed tools by declaration alone — no code, no vendor-specific logic anywhere in the runtime.

- **Added** `app/integration/connectors/rest/` — `RestConnector` (`connector.py`) built entirely through the 2.1.4 SDK surface. A connector instance's `configuration` declares a base URL, a per-instance authentication scheme, and one or more endpoints (method, path template, argument-to-request mapping, response extraction, optional pagination) — `declaration.py`'s `parse_declaration()`/`tool_contracts_for()` validate it structurally and semantically and derive one distinct `ToolContract` per endpoint (`ACT-INT-FR-102`).
- **Added** injection-safe request templating (`templating.py`): a path argument is percent-encoded with no safe characters (`"123/../admin"` renders as the single, inert segment `"123%2F..%2Fadmin"`, never escaping the declared endpoint); a header/query argument containing a control character is rejected outright; a body argument is placed into the JSON body as its own key/value, never string-interpolated.
- **Added** response extraction (`extraction.py`) — a dotted `response_field` path navigates the JSON response to the tool's output; an optional `output_schema` is validated with the same `jsonschema` library used elsewhere in this codebase.
- **Added** bounded pagination (`pagination.py`) — `offset_limit`/`page_number`/`cursor`, hard-capped at `min(declared max_pages, 100)` regardless of what the declaration or the remote server claims; a misbehaving server that never signals "done" cannot force an unbounded fetch.
- **Added** `app/integration/connectors/rest/invoker.py` — the first tool-invocation bridge built anywhere in this codebase: `invoke_tool()` fail-fast resolves a connector instance (the unchanged 2.1.3 registry), applies its declared authentication scheme via the existing 2.1.2 framework, renders and dispatches the request through `GovernedHttpClient`, drives pagination, and extracts the result — proven end to end against a real local HTTP server, including a genuine stored, encrypted `BEARER` credential reaching the server as a real header. **Not wired into `ToolGatewayService`/`tools_snapshot`/the model-driven tool loop** — Milestone 1 stays untouched, per this sub-phase's own scope.
- **Added** `ConnectorCredentialService.resolve_and_apply_for_scheme()` — an additive generalization of `resolve_and_apply()` (now a one-line wrapper over it) supporting a connector *instance's* own declared scheme rather than one scheme fixed per connector *type*, since a generic REST connector serves many vendor APIs from one registered type.
- **Fixed** `GovernedHttpClient.request()` silently dropping a query string embedded in its `url` argument (`execute_http_tool`'s `_build_target_url` only ever honored its own dedicated `query` parameter) — invisible to 2.1.4's query-free `WebhookConnector`, fatal to a paginated REST endpoint. Added a new, optional, backward-compatible `query` parameter; every existing caller (including 2.1.4's own tests) is unaffected.
- **Added** `REST_ENDPOINT_NOT_DECLARED`/`REST_TEMPLATE_INVALID`/`REST_EXTRACTION_FAILED` error codes. `TOOL_EGRESS_DENIED` is reused for allowlist/SSRF denials, per this sub-phase's own instruction not to invent a REST-specific egress code.
- **Added** a realistic four-endpoint vendor-like declaration (a support-ticketing CRM API: create/get/list-paginated/update) as the concrete `ACT-INT-FR-106` proof — a typical vendor REST integration is a configuration document, not an engineering project.
- **Explicitly out of scope, per the build prompt**: database/storage/queue connectors (2.2.2/2.2.3/2.2.4), GraphQL and vendor-specific connectors (fast-follow on this same framework), the connector marketplace/sandboxing (Milestone 12), identity federation (2.3.1), any change to model/tool execution.
- **No migration** — every table touched already exists; the declaration lives in the existing `connector_instances.configuration` JSONB column. **No new HTTP route** — instance configuration reuses the existing `POST`/`PATCH /connectors` endpoints; the invocation bridge is a direct, database-backed Python entry point.
- 41 new backend tests (`tests/integration/test_rest_connector.py`, 30 — declaration/templating/extraction/pagination/SDK-surface/integrity, no HTTP at all; `test_rest_connector_invocation.py`, 11 — end to end against a real local fixture server). Backend **1,121** green (1,080 + 41), 0 failed, 1 deselected; frontend untouched by this backend-only phase, still **297** green. See [docs/integration/connectors.md](docs/integration/connectors.md)'s "Generic REST Connector" section.

## [Unreleased] — Phase 2.1.4 · Connector SDK

**Completes the connector framework (Milestone 2, Phase 2.1).** A `Connector` now has an abstraction, a lifecycle, six authentication schemes, a registry, health monitoring, and a documented, containment-first SDK a trusted developer can author one through.

- **Added** `app/integration/sdk/` — the connector-authoring surface, explicit `__all__` re-exports only: `Connector`, the declaration types (`ConnectorDescriptor`/`ToolContract`/`ConnectorLifecycleState`), `SUPPORTED_AUTH_SCHEMES`, `validate_configuration_schema`/`ConnectorConfigInvalidError`, `GovernedHttpClient`, and the testing harness (`ConnectorTestHarness`/`HealthCheckOutcome`). Importing from `app.integration.sdk` is the supported contract; every other `app.integration.*`/`app.runtime.*` import is not, and may change without notice.
- **Added** `app/integration/sdk/http.py`'s `GovernedHttpClient` — the *only* network primitive the surface exposes, reusing Milestone 1's `egress_guard`/`http_executor` directly (not reimplemented). `allowed_hosts` is fixed at construction, never a per-call argument — a connector's own code cannot widen what it may reach at call time.
- **Added** the containment core (`ACT-INT-FR-066`): the SDK surface exposes no database session, no credential-resolution machinery (`AuthScheme`/`OutboundRequest`/`ConnectorCredentialService` all withheld), no raw HTTP client, no audit-suppression hook, and no route-registration mechanism — mechanically proven by a dedicated governance-inheritance test suite (AC-10..AC-15), not merely documented. An SDK connector cannot make an undeclared outbound call, receive a decrypted credential, suppress audit, or reach another tenant's data, because the SDK does not offer a method to do any of those.
- **Added** `app/integration/validation.py`'s `validate_declaration_complete()` — the single completeness check both the real registration path (`ConnectorTypeService.register()`, a new public method) and the SDK harness's pre-registration self-check call. A connector missing its config schema, capabilities, tool contracts, a declared/registered auth scheme, or a real `health_check()` implementation fails registration with `CONNECTOR_DECLARATION_INCOMPLETE`, naming exactly what's missing.
- **Added** `app/integration/sdk/example/webhook_connector.py`'s `WebhookConnector` (`SDK_EXAMPLE_WEBHOOK`) — a worked example built and tested using **only** the SDK surface, verified by an AST-based import-inspection test, not just by behavior. Registered through the identical `_CONNECTOR_TYPES`/`ensure_seeded` path as `MOCK`/`MOCK_AUTH` — registration parity proven by construction, not asserted.
- **Added** `ConnectorTypeService.register()` — the single, now genuinely public registration path; `ensure_seeded()` calls it once per `_CONNECTOR_TYPES` entry with no per-identifier branch.
- **Added** `CONNECTOR_DECLARATION_INCOMPLETE` error code (422).
- **Explicitly out of scope, per the build prompt**: the generic REST/database/storage/queue connectors (2.2.x — this SDK's own real proving ground), a distributable PyPI package (the surface isn't battle-tested yet), a connector marketplace/publishing/signing (Milestone 12), untrusted-third-party-code sandboxing (this SDK targets trusted, first-party authors — the module's own docstring states this boundary directly), identity federation (2.3.1).
- **No migration** — the SDK is an authoring surface over the existing schema. **No new HTTP route** — a code-authoring capability, not an API.
- 31 new backend tests (`tests/integration/test_connector_sdk.py`, 26; `test_connector_sdk_example.py`, 5 — kept in its own file so its import list is an isolated proof that the example's own tests use only the SDK harness). Backend **1,080** green (1,049 + 31), 0 failed, 1 deselected; frontend untouched by this backend-only phase, still **297** green. See [docs/integration/connectors.md](docs/integration/connectors.md)'s "Connector SDK" section.

## [Unreleased] — Phase 2.1.3 · Connector Registry & Health

- **Added** `app/integration/registry.py` — `ConnectorRegistry`, the
  single lookup surface for type resolution/listing (platform-wide) and
  tenant-scoped instance resolution/listing, wrapping 2.1.1's own
  services rather than duplicating them. Its `resolve_instance_for_invocation`
  is the **fail-fast wiring point** (`ACT-INT-FR-044`): raises
  `CONNECTOR_UNAVAILABLE` immediately for a `failed`/`disabled` instance,
  before any real call is ever attempted — Phase 2.2.x's tool bridge
  inherits this guarantee for free.
- **Added** `Connector.health_check(configuration) -> bool` — a new,
  additive abstract method on the ABC (deliberate and expected this
  sub-phase, unlike the still-absent `authenticate()`/`execute()`).
  Answers reachability only; receives only the instance's own
  `configuration`, **never a credential** — auth validity is checked
  entirely separately, by reusing `ConnectorCredentialService.validate()`
  (2.1.2), not duplicated. `MockConnector`/`MockAuthenticatedConnector`
  both implement it, configurable via `simulate_unreachable`/
  `simulate_error` in the instance's own stored configuration.
- **Added** `app/integration/health.py` — `ConnectorHealthService.check()`
  combines both probes into `HEALTHY`/`UNHEALTHY`/`ERROR`: `ERROR`
  (a probe raised) is distinct from a completed `UNHEALTHY` result —
  `POST .../health/check` returns 502 (`CONNECTOR_HEALTH_CHECK_FAILED`)
  for the former, 200 with the result body for the latter.
- **Added** automated `active -> failed`/`failed -> active` transitions:
  a failing check on an `active` instance calls the pre-existing,
  unchanged `ConnectorService.mark_failed`; a passing check on a
  `failed` instance calls a new `ConnectorService.recover` method and a
  new `recover` event added to `lifecycle.py`'s transition graph — both
  through the same, unbypassed 2.1.1 state machine.
- **Added** alerting via the *existing* audit-event mechanism, not a new
  channel: `ConnectorService._transition` now tags
  `INTEGRATION_CONNECTOR_STATE_CHANGED`'s `meta.severity` as `CRITICAL`
  when `to_state == "failed"` — the same severity-tagged, dashboard-
  reviewed (not pushed) pattern Phase 5.6a.1's `RUNTIME_TOOL_EGRESS_DENIED`
  already established. `app/services/notification_service.py` was
  examined and rejected (no subscription/recipient-list concept to hook
  a connector event into).
- **Added** `app/integration/scheduler.py` — an interim, in-process
  `asyncio` background task, off by default everywhere including every
  test run (`CONNECTOR_HEALTH_SCHEDULER_ENABLED=false`), explicitly
  documented as replaceable by Milestone 3's real scheduler rather than
  extended toward a distributed system (REPO_STATE §10.2). `run_sweep_once()`
  is a plain synchronous function tests call directly instead of waiting
  on the loop's sleep.
- **Added** `connector_health_checks` (migration `0035_connector_health`)
  — append-only history, capped at 200 rows per instance (a simple
  rollup, not a time-based policy); `connector_instances` gained a
  two-column health cache (`last_health_check_at`, `current_health`).
- **Added** 3 new routes under `/api/v1/integration` (`GET .../health`,
  `POST .../health/check`, `GET .../health/history`), reusing 2.1.1/
  2.1.2's permissions; 2 new error codes (`CONNECTOR_UNAVAILABLE`,
  `CONNECTOR_HEALTH_CHECK_FAILED`); 1 new audit event
  (`INTEGRATION_CONNECTOR_HEALTH_CHECKED`).
- **Changed** `ConnectorCredentialService.validate()`'s `actor` parameter
  to optional (`User | None`), additively, so the scheduler's
  system-triggered checks can call it with no human actor — every
  existing caller still passes a real one.
- **Fixed** (test-authoring, not production code): one pre-existing 2.1.1
  test (`test_ac03_mock_connector_satisfies_the_interface_without_an_abc_change`)
  asserted the ABC's method set was exactly `{describe,
  validate_configuration}` — updated to include the deliberately grown
  `health_check`, not a weakening (the test's actual intent still holds
  and is still checked).
- **Explicitly out of scope, per the build prompt**: the connector SDK
  (2.1.4), any real connector, the connector-to-tool bridge's actual
  invocation logic (2.1.3 built the fail-fast resolution boundary it
  will call, not the bridge itself), identity federation (2.3.1), and
  any distributed job scheduler (Milestone 3).
- 24 new backend tests (`tests/integration/test_connector_health.py`).
  Backend **1,049** green (1,025 + 24), 0 failed, 1 deselected; frontend
  untouched by this backend-only phase, still **297** green. See
  [docs/integration/connectors.md](docs/integration/connectors.md)'s
  "Registry & Health" section.

## [Unreleased] — Phase 2.1.2 · Connector Authentication Framework

- **Added** `app/integration/auth/` — a pluggable authentication scheme
  framework: `base.py` (the `AuthScheme` abstract interface and the
  connector-neutral `OutboundRequest` fixture), `registry.py` (explicit
  `register()`/`resolve()`, mirroring the provider/connector registry
  pattern), and six registered implementations under `schemes/` — static
  API key, bearer token, HTTP basic, OAuth2 client-credentials, OAuth2
  authorization-code, and mTLS.
- **Added** `ConnectorCredentialService` (`auth/service.py`) storing one
  encrypted JSON-bundle-per-`(connector_instance_id, auth_scheme)` row —
  **reusing `app/runtime/providers/credential_crypto.py`'s
  `encrypt_secret`/`decrypt_secret`/`mask_hint` directly**, verified by
  object identity in tests, not just behavior. No extraction or
  generalization was needed: those three functions already had zero
  provider-specific logic in their own bodies, the same precedent Phase
  5.6a.1's `ToolCredentialService` already set for tool credentials. The
  platform-held-Fernet-key Known Deviation is inherited from
  5.7a.5/5.6a.1, not newly introduced.
- **Added** `app/integration/auth/token_manager.py` — OAuth2 token
  acquisition, encrypted caching, and transparent refresh across all
  three grant types (client-credentials, authorization-code, refresh-
  token). **Concurrency-safe by design**: `get_valid_access_token` locks
  the *parent* `connector_instances` row (not the token row, which may
  not exist yet on a first acquisition) via `SELECT ... FOR UPDATE` —
  proven with real threads against real Postgres connections
  (`test_ac13_concurrent_refresh_does_not_double_refresh`, a fixture
  transport with an artificial delay widening the race window, asserting
  the token endpoint was hit exactly once).
- **Added** the OAuth2 authorization-code flow's built half: stored
  client configuration, `build_authorization_url()` (URL construction
  only, no HTTP route since the build prompt's own endpoint table didn't
  list one), the `GET`/`POST .../oauth/callback` code→token exchange,
  and refresh-and-apply given a stored refresh token. **Stubbed, stated
  plainly**: the interactive consent-redirect UI itself — an explicit
  front-end concern, out of scope for this backend-only sub-phase.
- **Added** `connector_credentials`/`connector_oauth_tokens` tables
  (migration `0034_connector_auth`) — neither stores a structured
  plaintext credential field, only ciphertext + a masked hint.
- **Added** `MockAuthenticatedConnector` (`app/integration/mock_authenticated.py`)
  alongside (not replacing) 2.1.1's `MockConnector`, declaring a real
  `API_KEY` auth requirement so the framework is exercised end to end
  against a mock — no real connector invokes anything yet (2.1.3/2.2.x).
- **Added** 7 new routes under `/api/v1/integration` (`GET
  /auth-schemes`, `GET`/`PUT`/`DELETE .../credentials`, `POST
  .../credentials/validate`, `GET`/`POST .../oauth/callback`), reusing
  2.1.1's two permissions rather than adding a finer
  `integration.credential.manage` (stated as not warranted — a
  credential is a property of a connector instance, not a separately
  access-controlled resource).
- **Added** 4 new error codes (`CONNECTOR_CREDENTIAL_NOT_FOUND`/
  `CONNECTOR_AUTH_SCHEME_UNSUPPORTED`/`CONNECTOR_CREDENTIAL_INVALID`/
  `CONNECTOR_OAUTH_REFRESH_FAILED`) and 3 new audit events
  (`INTEGRATION_CONNECTOR_CREDENTIAL_UPDATED`/`_DELETED`/`_VALIDATED`).
- **Explicitly out of scope, per the build prompt**: connector registry &
  health (2.1.3), the connector SDK (2.1.4), any real connector, and
  identity federation (2.3.1 — the opposite direction: a platform *user*
  authenticating via an enterprise IdP, not the platform authenticating
  itself to an external system).
- 31 new backend tests (`tests/integration/test_connector_auth.py`),
  including the real-thread OAuth2 concurrency proof and a full redaction
  sweep (no credential value in logs, audit `meta`, or API responses).
  Backend **1,025** green (994 + 31), 0 failed, 1 deselected; frontend
  untouched by this backend-only phase, still **297** green. See
  [docs/integration/connectors.md](docs/integration/connectors.md)'s
  "Authentication" section.

## [Unreleased] — Phase 2.1.1 · Connector Abstraction & Lifecycle

- **Added** `app/integration/` — a new sibling domain to `app/runtime/`
  (Milestone 2's first sub-phase): `base.py` (the `Connector` abstract
  interface — `describe()`/`validate_configuration()` abstract, deliberately
  no `authenticate()`/`execute()`/`health_check()`, all left to the
  sub-phases that actually need them), `types.py` (connector-neutral
  `ConnectorDescriptor`/`ToolContract`/`ConnectorLifecycleState` — frozen,
  slotted dataclasses, `MappingProxyType`-wrapped dict fields, mirroring
  `app/runtime/providers/types.py`'s own precedent), `lifecycle.py` (the
  single transition authority for the five-state machine
  `registered → configured → active → disabled → failed`), `mock.py`
  (`MockConnector`, the trivial reference implementation), `service.py`
  (`ConnectorTypeService`/`ConnectorService`), `errors.py`, `routes.py`,
  `schemas.py`.
- **Added** `Connector`, `ConnectorInstance`, `ConnectorLifecycleEvent` ORM
  models (`app/models/integration.py`) and migration `0033_connector_core`
  — three new tables, no existing table touched: `connectors` (registered
  types, unique on `connector_type`+`version`), `connector_instances`
  (tenant-scoped, unique on `organization_id`+`name`, **no credential
  column** — that's Phase 2.1.2), `connector_lifecycle_events`
  (append-only, no update/delete path anywhere).
- **Added** the **runtime-never-knows principle**, enforced by construction
  rather than convention: a test greps every file under `app/runtime/` for
  the substring `"connector"` and fails the build if it finds one
  (`ACT-INT-FR-006`) — currently zero.
- **Added** config validation that reuses Milestone 1's `jsonschema`
  library via a new thin wrapper (`validate_configuration_schema`), not a
  new validator.
- **Added** 8 routes under `/api/v1/integration` (connector types, tenant
  instances CRUD, `activate`/`disable`, lifecycle events) and 2 new
  permissions (`integration.connector.view`/`.manage`).
- **Added** 4 new error codes (`CONNECTOR_TYPE_NOT_FOUND`/
  `CONNECTOR_NOT_FOUND`/`CONNECTOR_CONFIG_INVALID`/
  `CONNECTOR_INVALID_TRANSITION`) and 1 new audit event
  (`INTEGRATION_CONNECTOR_STATE_CHANGED`, dual-written to both the
  lifecycle-events table and the platform-wide `AuthorizationAuditService`).
- **Explicitly out of scope, per the build prompt**: authentication
  framework (2.1.2), connector registry & health monitoring (2.1.3), the
  connector SDK (2.1.4), any real connector, and the connector-to-tool
  bridge that would actually make a declared tool contract invokable.
- 24 new backend tests (`tests/integration/test_connector_core.py`, a new
  top-level test directory with its own minimal fixtures). Backend
  **994** green (970 + 24), 0 failed, 1 deselected; frontend untouched by
  this backend-only phase, still **297** green. See
  [docs/integration/connectors.md](docs/integration/connectors.md).

## [Unreleased] — Phase 5.6a.3 · Model-Driven Tool Invocation Loop

**Completes Milestone 1** — an agent registered, versioned, signed and
deployed now genuinely executes end to end: calls a real model, the model
requests a real tool, the tool runs safely, the result feeds back, the
loop resolves to a final answer, every token/call/decision audited.

- **Added** `ToolLoopOrchestrator` (`app/runtime/services.py`), driving
  model → tool → model over `ModelGatewayService.invoke()` and
  `ToolGatewayService.invoke()`, both entirely unchanged — every existing
  authorization check, egress guard, and schema-validation/resilience path
  applies automatically, with zero new code.
- **Added** two additive, both-optional parameters to
  `ModelGatewayService.invoke()` (`conversation`, `tools`) — a version's
  frozen `tools_snapshot` is offered only to a provider whose `describe()`
  declares `supports_tools` (`MOCK` never does, so every 5.6a.1/5.6a.2
  test — all `MOCK`-based — is completely unaffected).
- **Added** four independent termination caps — max iterations, token
  budget, wall-clock, repeated-identical-call (reusing Phase 5.2.4's
  canonical serialization for "identical call" comparison) — each ending
  in a distinct, audited `agent_executions.termination_reason`.
- **Added** real parallel execution of tool calls the model requests
  together, gated by the same `idempotent` flag 5.6a.2 introduced, reused
  for a second purpose: safe-to-retry ⟺ safe-to-run-alongside-siblings. A
  single non-idempotent tool anywhere in a batch drops the whole batch to
  sequential, model-given order.
- **Fixed** a genuine deadlock, found by reproducing it directly against
  `pg_stat_activity`, not guessed at: the first parallel-execution design
  opened a fresh `Session` per worker thread, whose `INSERT INTO
  tool_calls` blocked on the still-`FOR UPDATE`-locked `agent_executions`
  row from `claim_next`, while the main thread blocked on those same
  worker threads via `future.result()`. Fixed by committing the claiming
  session immediately before any parallel dispatch.
- **Added** `TOOL_NOT_BOUND_TO_VERSION` — a tool named outside the
  version's frozen `tools_snapshot` is a scope violation, not a
  recoverable mistake the model gets to iterate past; this is also where
  "no agent-to-agent chaining" is structurally enforced, since a tool is
  the only thing this loop can ever name.
- **Added** `execution_messages` table (migration `0032_tool_loop`) — the
  full conversation transcript, exposed at `GET /executions/{id}/messages`;
  `agent_executions` gained `loop_iterations`/`termination_reason`,
  `tool_calls` gained `loop_iteration`.
- 17 new backend tests including an end-to-end proof (real fixtured model
  → real HTTP tool through the egress guard → final answer, fully
  audited). Backend **970** green (953 + 17), 0 failed, 1 deselected;
  frontend untouched, still **297** green. See
  [docs/runtime/gateways.md](docs/runtime/gateways.md)'s "Milestone 1 —
  complete" section.

## [Unreleased] — Phase 5.6a.2 · Tool Schema Validation & Resilience

- **Added** argument validation against `Tool.input_schema` before any
  side effect runs — before `FUNCTION`'s echo, and before the `HTTP`
  branch even builds an egress policy. A violation returns
  `TOOL_SCHEMA_INVALID` with a structured, JSON-encoded
  `ToolCall.validation_error`; no request is issued. A response is
  validated against an optional `output_schema` only when one is
  declared. Both frozen into the version snapshot at publish time,
  alongside `http_config.timeout_seconds` (closing a gap 5.6a.1 left
  open — that phase read the live, mutable `Tool.timeout_seconds` column
  at execution time).
- **Reused — not duplicated** — Phase 5.7a.4's `ProviderErrorClass`
  taxonomy and retry/circuit-breaker machinery for a tool's HTTP-level
  failures; the one piece that wasn't already provider-neutral (what
  happens when the circuit is open) was extracted into a shared core so
  both the model and tool paths use one implementation.
- **Added** idempotency as an explicit, opt-in `http_config.idempotent`
  declaration — never inferred from HTTP method; undeclared or `false`
  means a transient failure is never retried. A retried call gets one new
  `ToolCall` row per attempt.
- **Added** a new per-execution concurrency ceiling
  (`app/runtime/tools/concurrency.py`) — real-thread-tested, not yet
  contended until 5.6a.3's parallel tool execution.
- **Changed** (behavior change from 5.6a.1): a `FAILED` tool call (schema
  violation, exhausted retry, timeout, oversized response, open circuit,
  concurrency-ceiling rejection) no longer aborts the whole execution —
  only a governance/egress `DENIED` call still does.
- **Added** five new error codes (`TOOL_SCHEMA_INVALID`/
  `TOOL_RESPONSE_TOO_LARGE`/`TOOL_TIMEOUT`/`TOOL_EXECUTION_FAILED`/
  `TOOL_CONCURRENCY_LIMIT_EXCEEDED`) and `RUNTIME_TOOL_FAILED`; migration
  `0031_tool_resilience` (three new nullable `tool_calls` columns, no new
  table).
- 19 new backend tests. Backend **953** green (934 + 19), 0 failed, 1
  deselected; frontend untouched, still **297** green.

## [Unreleased] — Phase 5.6a.1 · HTTP Tool Execution & Egress Control

The first tool-side sub-phase of Milestone 1 — closes the other half of
the same untested assumption every phase before it rested on: every
agent so far could only call the built-in `FUNCTION`/`echo` action.

- **Added** `app/runtime/tools/` — a new package: `egress_guard.py` (pure
  logic, no network/database — `EgressPolicy`/`EgressDecision`/
  `evaluate_url`/`resolve_and_validate`, plus a permissive IP-literal
  parser catching decimal/octal/hex loopback encodings some platforms'
  libc resolvers accept but Python's `ipaddress` module rejects) and
  `http_executor.py` (`execute_http_tool`, `_PinnedTransport` — connects
  to the address the guard validated, never a freshly re-resolved
  hostname, defending against DNS rebinding; verified empirically against
  the installed `httpx`/`httpcore` before writing tests).
- **Added** a real `HTTP` action to `ToolGatewayService` (`FUNCTION`/
  `echo` unchanged), reading its egress policy from the *frozen* version
  snapshot, never live, mutable `Tool` state — `SnapshotBuilderService`
  gained a new `runtime.tool_configs` snapshot key (`tools_snapshot`
  itself deliberately untouched — three existing subsystems consume its
  bare-id-list shape).
- **Added** `tool_credentials` table and `ToolCredentialService`, reusing
  Phase 5.7a.5's `credential_crypto.py` directly.
- **Added** `TOOL_EGRESS_DENIED` error code and `RUNTIME_TOOL_INVOKED`/
  `RUNTIME_TOOL_EGRESS_DENIED` audit events — the latter `CRITICAL`
  severity (an egress denial is a signal someone may be probing the SSRF
  boundary).
- Migration `0030_http_tool_egress`: `tools.http_config` (JSONB), eight
  new columns on `tool_calls` (egress/HTTP recording), new
  `tool_credentials` table.
- 51 new backend tests: 32 in `test_egress_guard.py` (every SSRF vector
  individually, no network/database), 19 in `test_http_tool_execution.py`
  (executor mechanics against real local `127.0.0.1` fixture servers).
  Backend **934** green (883 + 51), 0 failed, 1 deselected; frontend
  untouched, still **297** green. See
  [docs/runtime/gateways.md](docs/runtime/gateways.md)'s "Egress
  control" section.

## [Unreleased] — Phase 5.7a.5 · Per-Organization Provider Credentials

**Completes the model half of Milestone 1** — only tool execution
(5.6a.1-3) remained before the platform genuinely executed end to end.

- **Added** `provider_credentials` table (migration
  `0029_provider_credentials`): one row per `(organization_id, provider)`,
  `encrypted_secret` a Fernet ciphertext
  (`app/runtime/providers/credential_crypto.py`, new file — key from
  `settings.MODEL_CREDENTIAL_ENCRYPTION_KEY` or auto-generated/persisted
  to `.keys/`, mirroring Phase 5.2.4's `LocalKeyProvider` pattern).
- **Added** `ProviderCredentialService` (`store`/`get_metadata`/
  `resolve_secret`/`delete`/`list_for_org`/`test`) with an explicit
  resolution order (`ACT-MDL-FR-082`): per-organization stored credential
  → `MODEL_PROVIDER_API_KEYS` fallback → none — a real provider rejecting
  an unauthenticated call with nothing configured anywhere is translated
  from the generic `AUTHENTICATION_FAILED` to the more specific,
  non-retryable `PROVIDER_CREDENTIAL_REQUIRED`.
- **Added** synchronous credential resolution on the worker's own thread
  in `ExecutionWorkerService._execute`, *before* the model call is handed
  to its `ThreadPoolExecutor` — a live `Session` cannot safely cross that
  thread boundary, so only the resulting plain `ResolvedCredential` value
  does.
- **Added** 4 new routes under `/api/v1/runtime/providers/{provider}/credentials`
  (`GET`/`PUT`/`DELETE`/`POST .../test`) and 2 new permissions
  (`runtime.provider.view`/`.manage`).
- **Kept** `MODEL_PROVIDER_API_KEYS` as the fallback default (not
  removed) — no previously-passing test broke.
- 25 new backend tests. Backend **883** green (858 + 25), 0 failed, 1
  deselected; frontend untouched, still **297** green.

## [Unreleased] — Phase 5.7a.4 · Error Taxonomy & Resilience

- **Added** an eight-class provider-neutral failure taxonomy
  (`ProviderErrorClass`): `RATE_LIMITED`/`PROVIDER_UNAVAILABLE`/`TIMEOUT`
  retryable; `CONTEXT_LENGTH_EXCEEDED`/`CONTENT_FILTERED`/
  `AUTHENTICATION_FAILED`/`INVALID_REQUEST`/`UNKNOWN` never retried.
  Classification lives in the adapter (`openai_compatible.py`);
  retry/backoff/circuit-breaking live in the service layer
  (`ModelGatewayService`), so a future second adapter inherits both with
  zero new retry code.
- **Added** exponential-with-jitter backoff, a provider's own
  `Retry-After` header honored in preference to computed backoff, a
  per-provider in-process three-state circuit breaker, and a streaming
  pre-/post-first-token retry boundary (a pre-first-token interruption
  retries; a post-first-token one persists the partial and is never
  retried).
- **Added** credential/base-URL scrubbing before any message reaches a
  log or caller.
- **Changed** the pre-existing execution-level retry
  (`ExecutionWorkerService._fail_or_retry`, Phase 5.0) is untouched
  except its `non_retryable` set gained the five non-retryable classes.
- **No schema migration** — `error_code` (already `VARCHAR(50)` on both
  `agent_executions` and `execution_attempts`) now stores the taxonomy
  class string in place of the old generic code.
- 36 new backend tests plus nine new committed error fixtures. Backend
  **858** green (822 + 36), 0 failed, 1 deselected; frontend untouched,
  still **297** green.

## [Unreleased] — Phase 5.7a.3 · Streaming & Token Accounting

- **Added** real SSE streaming, replacing 5.7a.2's `stream()` placeholder
  — incremental content deltas, tool-call reassembly across
  fragmented/interleaved chunks; an interrupted stream persists a partial
  via `FinishReason.ERROR` rather than raising (deliberately unlike
  `complete()`).
- **Added** an opt-in streaming path to `ModelGatewayService.invoke()`
  (`model_configuration.stream=true`) — the `(output_payload, usage)`
  contract stays unchanged for every non-streaming caller.
- **Added** real token/cost accounting: `usage` gained
  `token_accounting_complete`/`was_streamed`/`stream_interrupted`/
  `time_to_first_token_ms`/`generation_duration_ms`/`finish_reason`; a
  provider omitting usage now reports `{}` — never zero-filled (the
  never-estimate rule, `ACT-MDL-FR-046`).
- **Added** `model_pricing` table with effective dating (a price change
  inserts and closes a row, never mutates one in place) backing
  `PricingService`, replacing the flat placeholder rate; local/unpriced
  providers (`MOCK`) honestly cost `0`.
- Migration `0028_streaming_and_pricing`: new `model_pricing` table
  (seeded), 12 new columns on `agent_executions`, 4 on
  `execution_attempts`; 1,538 pre-existing non-zero-cost rows marked
  `cost_is_estimated=true`, never recomputed.
- 22 new backend tests. Backend **822** green (800 + 22), 0 failed, 1
  deselected; frontend untouched, still **297** green.

## [Unreleased] — Phase 5.7a.2 · First Real Provider Adapter

- **Added** `OpenAICompatibleProvider`
  (`app/runtime/providers/openai_compatible.py`) — the first real,
  network-calling provider, speaking the OpenAI chat-completions wire
  protocol against any `base_url` (Ollama/vLLM/LM Studio/OpenAI),
  registered as `"OPENAI_COMPATIBLE"` (names the protocol, not a vendor —
  `"OPENAI"` deliberately left free for a future vendor-specific
  adapter). Message/tool-call/finish-reason translation,
  sampling-parameter filtering, tolerant parsing of responses missing
  optional fields.
- **Fixed** `registry.resolve()` to actually forward `model`/`api_key` to
  the provider instance — a genuine 5.7a.1 gap where neither previously
  reached further than usage-reporting strings.
- **Added** `ProviderRequestFailedError`/`MODEL_PROVIDER_REQUEST_FAILED`
  — one coarse exception, not a taxonomy (classifying failure modes for
  retry is 5.7a.4's job).
- **Added** fixture-replay test infrastructure (`httpx.MockTransport`,
  six committed wire-format fixtures, a manual recorder script, a
  `live_provider` pytest marker excluded by default via
  `backend/pytest.ini`).
- 30 new backend tests (`test_openai_compatible_provider.py` plus
  additions to `test_provider_abstraction.py`); `registered_identifiers()`
  now returns `["MOCK", "OPENAI_COMPATIBLE"]`. Backend **800** green (766
  + 34 including conformance-suite additions), 0 failed, 1 deselected
  (the new `live_provider`-marked genuinely-live Ollama check); frontend
  untouched, still **297** green.

## [Unreleased] — Phase 5.7a.1 · Model Provider Abstraction & Registry

- **Added** `app/runtime/providers/` — a new package: `base.py` (the
  `ModelProvider` abstract interface: `complete()`/`stream()`/`describe()`
  abstract, `supports()` concrete and derived from `describe()`),
  `types.py` (the provider-neutral internal representation —
  `ModelMessage`, `ModelRequest`, `ModelResponse`, `ModelToolDefinition`,
  `ModelToolCall`, `ModelCapabilities`, `FinishReason` — all immutable,
  frozen/slotted dataclasses with `MappingProxyType`-wrapped dict fields),
  `registry.py` (explicit `register()`/`resolve()`, not directory-scanning
  discovery), `mock.py` (`MockProvider`, the first implementation),
  `errors.py` (`ProviderUnavailableError`, `CapabilityUnsupportedError`).
- **Migrated** `MOCK` onto the new interface with unchanged externally
  observable behavior: exact input echo, `provider == "MOCK"`, a positive
  token count. The exact wording of the completion text and exact token
  counts changed internally (dict-key-count vs. message-count), but
  nothing in the test suite ever asserted on either — zero pre-existing
  tests needed modification.
- **Refactored** `ModelGatewayService.invoke()` to resolve providers via
  the registry instead of an inline `MOCK`-only branch. Public signature
  and `(output_payload, usage)` return shape unchanged; provider selection
  still reads only from the version's frozen `model_configuration`, never
  from mutable agent/deployment state. `AuthorizationGateway` is
  untouched — it already ran at an earlier pipeline stage
  (`request_execution`, before an execution is even queued), well before
  provider resolution.
- **Added** capability declaration and enforcement
  (`ACT-MDL-FR-009`): a request asking a provider for something its own
  `describe()` says it doesn't support (e.g. tool definitions sent to
  `MockProvider`, which declares `supports_tools=False`) raises
  `MODEL_CAPABILITY_UNSUPPORTED` (422) rather than being silently ignored
  or mishandled.
- **Added** a reusable, parameterized conformance test suite
  (`PROVIDERS_UNDER_TEST` in `tests/runtime/test_provider_abstraction.py`)
  — every future adapter (starting with Phase 5.7a.2's real provider) is
  validated against it by adding one line, not copying tests.
- **Added** `MODEL_CAPABILITY_UNSUPPORTED` error code;
  `MODEL_PROVIDER_UNAVAILABLE` preserved exactly. Added
  `MODEL_DEFAULT_PROVIDER`/`MODEL_PROVIDER_BASE_URLS` settings
  (`ACT-MDL-FR-010` — per-provider base URL configuration, proven
  end-to-end even though `MOCK` has nothing to call).
- **No schema migration** — this sub-phase is purely an application-layer
  abstraction over the existing `model_configuration` JSONB column.
- **Explicitly out of scope, per the build prompt**: any real provider
  implementation (5.7a.2), streaming (5.7a.3), token accounting/cost
  (5.7a.3/5.7a.5), a real error taxonomy and retry (5.7a.4), credential
  storage (5.7a.5).
- 23 new backend tests (`tests/runtime/test_provider_abstraction.py`) —
  unit/conformance (no database) plus 4 integration tests proving the
  execution pipeline actually routes through the new abstraction
  end-to-end. Backend **766** green (743 + 23), 0 failed; frontend
  untouched by this backend-only phase, still **297** green.

## [Unreleased] — Phase 5.2.4 · Cryptographic Signing, Provenance & Portable Attestation

- **Added** `app/runtime/versioning/canonical.py` — the single canonical
  serialization implementation (sorted keys by Unicode code point, NFC
  string normalization, UTF-8, no whitespace, non-ASCII literal, floats
  rejected outright) now shared by every checksum producer/verifier.
  Refactored `_checksum()` (`services.py`) and `checksum_of()`
  (`snapshot.py`) to delegate to it; the original routines are kept,
  renamed `_legacy_checksum`/`_legacy_checksum_of` and marked deprecated,
  to verify rows created before this phase.
- **Added** `checksum_algorithm` on `agent_versions`/
  `agent_version_snapshots` (migration `0027_version_signing`) —
  `'legacy-sha256'` for existing rows (untouched by the migration itself),
  `'canonical-sha256'` for new ones; verification branches on it. Both
  `checksum` columns widened to fit the new `sha256:<hex>` prefixed format.
  `backend/scripts/recompute_checksums.py` (with `--dry-run`) is the
  explicit, audited way to upgrade legacy rows.
- **Fixed** `build_snapshot()` embedding raw `datetime` objects for
  `release_window_start`/`release_window_end`/`support_end_date`, silently
  tolerated by the old checksum routine's `default=str`; now `.isoformat()`
  strings, a precondition canonical.py's stricter typing surfaced.
- **Added** `SigningProvider` abstraction (`app/runtime/versioning/signing/`)
  — `LocalKeyProvider` (Ed25519, gitignored `.keys/`, auto-generates a dev
  keypair on first use) is the only implementation; swapping to Azure Key
  Vault at deployment is a configuration change, not a rewrite. Private key
  material never crosses the interface.
- **Added** `AttestationService` (`app/runtime/versioning/attestation.py`):
  builds an in-toto Statement v1 predicate + DSSE envelope
  (`application/vnd.in-toto+json`) per published version, signs the DSSE
  Pre-Authentication Encoding (not the raw payload) via the configured
  provider. Self-contained by design — every predicate claim is
  interpretable from the document alone, no database lookup required.
- **Added** signing to `publish()`, fail-closed — the opposite policy from
  Phase 5.2.6's advisory compatibility analysis: a signing failure raises
  out of `publish()` entirely, and the version never reaches `PUBLISHED`.
- **Added** key rotation/revocation (`SigningKeyService`,
  `app/runtime/versioning/keys.py`) — revocation marks affected signatures
  `KEY_REVOKED` without altering the version record or signature bytes;
  rotation keeps prior key versions retrievable so old signatures stay
  verifiable.
- **Wired** the previously-always-null `agent_versions.signature_id` to the
  primary (`PUBLISHER`) signature's id, rather than dropping the column.
- **Added** migration `0027_version_signing`: new tables `signing_keys`,
  `signing_key_versions`, `agent_version_signatures`,
  `agent_version_provenance`; `agent_versions` gains `signed_at`/
  `manifest_digest`.
- **Added** 8 routes (`.../signatures`, `.../provenance`,
  `.../attestation`, `.../verify`, `.../countersign`, `/signing-keys`,
  `/signing-keys/{id}/rotate`, `/signing-keys/{id}/revoke`) and 2 new
  permissions (`runtime.signing.view`/`.manage`); the countersign endpoint
  reuses the existing `runtime.agent.approve` rather than inventing a
  `runtime.version.approve` synonym.
- **Deliberately deferred** (see `docs/runtime/versioning.md`'s Known
  Deviations): a public/unauthenticated verification endpoint
  (`ACT-VER-FR-070`) — every route here is authenticated and
  organization-scoped; Azure Key Vault as a second `SigningProvider`
  (`ACT-VER-NFR-002`'s closure condition) — the local provider necessarily
  loads private key bytes into process memory to sign, by construction.
- Two pre-existing tests updated in place (asserted the legacy bare-64-hex
  checksum length; now assert the new `sha256:<hex>` format) — the only
  tests touched, per this phase's own one-exception rule.
- 47 new backend tests (`tests/runtime/test_canonical.py`,
  `test_version_signing.py`, `test_attestation.py`). Backend **743** green
  (696 + 47); frontend untouched by this backend-only phase, still **297**
  green.

## [Unreleased] — Phase 5.2.6 · Compatibility & Breaking-Change Detection

- **Added** `CompatibilityAnalysisService` (`app/runtime/versioning/compatibility.py`):
  classifies a candidate version against a resolved baseline into
  `COMPATIBLE`/`BACKWARD_COMPATIBLE`/`BREAKING`/`UNKNOWN` — input/output
  contract (JSON Schema diff on `AgentDefinition.input_schema`/
  `output_schema`), tool/capability bindings, model provider/config
  changes, a numeric resource-limit heuristic, policy tightening
  (`approved_models`, `prohibited_environments`,
  `requires_approval_environments`), and prompt/metadata changes.
- **Added** migration `0026_version_compatibility`: `agent_versions` gains
  `compatibility_baseline_id`/`compatibility_analyzed_at`; new table
  `agent_version_compatibility_findings` (one row per detected change,
  replaced wholesale on re-analysis, never accumulated).
- **Added** automatic compatibility analysis right after `publish()`'s own
  commit succeeds — failure-tolerant: an analyzer exception is logged and
  swallowed, never blocking publication. Also available on demand via
  `POST .../versions/{id}/compatibility/analyze` (recomputes and persists;
  backfills versions published before this phase existed).
- **Added** three routes: `GET`/`POST .../versions/{id}/compatibility`,
  `GET .../versions/{id}/compatibility/findings` — all reuse
  `runtime.version.view` (no new permission).
- **Replaced** `VersionReadinessService`'s `compatibility_analysis` check
  — no longer always `skipped: true`; now a real evaluation that warns
  (doesn't fail) on a correctly major-bumped breaking change and fails
  only on genuine semver/compatibility inconsistency, still never gating
  any lifecycle action.
- **Deliberate SRS deviation**: semver/compatibility-level inconsistency
  is reported (`semver_consistent: false`, a failed readiness check), not
  enforced as a `publish()` blocker — preserves Part 1's advisory-only
  boundary for comparison/readiness; see
  [docs/runtime/versioning.md](docs/runtime/versioning.md).
- 35 new backend tests (`tests/runtime/test_version_compatibility.py`,
  16 pure/database-free classification tests + 19 integration/API tests).
  Backend **696** green (661 + 35); frontend untouched by this
  backend-only phase, still **297** green.

## [Unreleased] — Phase 5.2 Part 1 · Enterprise Versioning & Release Management Foundation

- **Added** migration `0025_agent_versioning`: additive release-management
  columns on `agent_versions` (release channel, compatibility/signature
  placeholders, lineage pointers, retirement) and six new tables —
  `agent_release_channels` (seeded catalog), `agent_version_snapshots`
  (the frozen, complete release document), `agent_release_metadata`,
  `agent_release_artifacts`, `agent_release_notes`, and
  `agent_version_status_history`.
- **Added** enforced semantic versioning (§15-16): auto-derived or
  validated strictly-increasing `MAJOR.MINOR.PATCH`, replacing Phase 5.0's
  unvalidated string field.
- **Added** the snapshot builder (§10-14): one frozen, checksummed document
  per version — registry identity, definition, runtime config, and every
  release-management attachment — built exactly once, at publish.
- **Added** version lineage (§17-18): parent-version linking, supersession
  tracking, and a settable rollback-target pointer (foundation only —
  executing a rollback remains `DeploymentService`'s existing job).
- **Added** release channels (§9, §26), categorized release notes and
  artifact references (§27-28), and the version status-history ledger
  (§19, §25) — all gated by the same immutability rule once a version is
  PUBLISHED.
- **Added** the `RETIRED` terminal lifecycle state and `retire` action
  (DEPRECATED → RETIRED), reachable only from DEPRECATED, matching the SRS
  lifecycle diagram.
- **Added** version comparison (§3): a read-only structural diff between
  any two versions of the same agent — scalar fields, key-level JSONB
  config diffs, and artifact/note set differences.
- **Added** promotion readiness (§3, §30): a read-only diagnostic endpoint
  evaluating the SRS's full "Version Readiness" checklist (snapshot
  creation, validation, metadata, ownership, registry status, blocking
  governance findings, artifacts, approval) — advisory only, never a gate
  on the lifecycle actions themselves.
- **Deliberately not enforced**: the SRS's "cannot publish two active
  releases" — this platform's existing rollback/canary deployment
  strategies require multiple simultaneously-PUBLISHED versions; see
  [docs/runtime/versioning.md](docs/runtime/versioning.md) for the full
  rationale. Compatibility *analysis* and real cryptographic signing are
  out of scope (explicitly deferred by the SRS to a later part).
- 25 new backend tests (`tests/authorization/test_agent_versioning.py`);
  7 new frontend tests. Backend **661** green, frontend **297** green;
  clean typecheck and build.

## [Unreleased] — Phase 5.1 · Enterprise Agent Registry

### Part 5.1 — Enterprise Agent Registry, Definitions & Lifecycle

- **Added** migration `0024_agent_registry`: additive registry columns on
  `agents` (org-hierarchy scoping, mandatory-identity pointer, ownership
  roles, tags/metadata, `row_version` optimistic concurrency) and
  `agent_definitions` (requirement declarations); new tables
  `agent_ownership_history`, `agent_lifecycle_events`,
  `agent_validation_runs`, `agent_duplicate_matches`, `agent_import_jobs`/
  `agent_import_items`, `agent_export_jobs`, `agent_migration_records`; a
  one-identity-per-agent unique constraint on `agent_identities`.
- **Added** the full 13-state registry lifecycle (§18-§21), replacing
  Phase 5.0's collapsed 8-state one — `register`, `submit-for-approval`,
  `reject`, `resume`, `restore` are new actions; every transition gets its
  own dedicated audit event and a structured `agent_lifecycle_events` row.
- **Added** accountable ownership with transfer + immutable history, and
  mandatory machine-identity association/creation/rotation with the
  eligibility enforcement (active, unexpired, DB-uniqueness) Phase 5.0
  never checked.
- **Added** the validation-report engine (§25-§31): metadata/organization/
  ownership/identity/definition/risk rules, JSON Schema DoS guards
  (size/depth limits), entrypoint format validation per type, sample-payload
  testing.
- **Added** duplicate detection (§32, §33, §64): exact + `difflib`
  similarity matching, reviewer decisions, confirmed duplicates block
  registration.
- **Added** JSON/YAML/CSV bulk import (§39-§42, always lands as DRAFT) and
  export (§43-§44, secrets always excluded via an allowlist, CSV
  formula-injection neutralized) with job/item tracking, run synchronously
  inline (no background worker in this environment, same as the execution
  queue).
- **Added** legacy-agent classification (§70-§73) for rows created under
  Phase 5.0's simpler registry.
- **Added** ~25 new `runtime.agent.*` permissions and the frontend
  10-step registration wizard, 12-tab agent detail page, duplicate-review
  page, and import/export pages. See
  [docs/runtime/registry/](docs/runtime/registry/) for the full set.

### Part 5.1 hardening — acceptance-criteria gap closure

- **Fixed** `AgentDefinitionRead` (`app/runtime/schemas.py`) — missing
  `framework_version`, `runtime_language`, `capability_declarations`,
  `tool_declarations`, and the six `*_requirements` fields, causing a hard
  `TypeError` every time the frontend's Definition tab rendered.
- **Added** the legacy-migration frontend page (`MigrationPage.tsx`,
  `/runtime/migration`) — the classification service and API existed with
  no UI to trigger or review it.
- **Added** registration-wizard draft autosave (§22.6): persists to
  `localStorage` on every change, restores with a dismissible banner on
  return, clears on successful submit; fixed the wizard's form `<Label>`s
  to be properly associated with their inputs (`htmlFor`/`id`) along the
  way.
- **Added** performance tests (`test_agent_registry_perf.py`, §31):
  bulk-registration/search throughput and duplicate detection against a
  50+ agent pool, following the existing timing-reported convention.
- **Added** frontend test coverage for all 5 registry pages (23 tests) —
  previously untested.
- **Removed** dead Phase 5.0 schemas superseded by the registry
  (`AgentRegisterRequest`, `AgentUpdateRequest`, `AgentRuntimeRead`,
  `AgentDefinitionCreate`).
- Backend **636** green (incl. 2 new perf tests); frontend **290** green;
  clean typecheck and build.

## [Unreleased] — Phase 5.0 · Agent Runtime & Lifecycle Management

### Part 5.0 — Agent Runtime & Lifecycle Management

- **Added** the `/api/v1/runtime` control plane (§66) — `app/runtime/`:
  agent registry and lifecycle, immutable versioning, deployments, the
  Runtime Gateway, executions, capabilities, tools, runtime approvals,
  health/workers and the kill switch. Gated by 32 new `runtime.*`
  permissions and new builtin roles `ROLE_RUNTIME_ADMIN`/
  `ROLE_RUNTIME_OPERATOR`.
- **Added** migration `0023_agent_runtime`: additive `lifecycle_status`,
  `slug`, `project_id`, `owner_type`/`owner_id`, `criticality`,
  `data_classification`, `default_environment`, `archived_at` on the
  existing `agents` table (no parallel registry — see
  [docs/runtime/architecture.md](docs/runtime/architecture.md)); new
  `agent_definitions`, `agent_versions`, `agent_deployments`,
  `agent_executions`, `execution_attempts`, `execution_locks`,
  `capabilities`, `agent_capabilities`, `tools`, `agent_tools`,
  `tool_calls`, `runtime_events`, `deployment_health`,
  `idempotency_records`, `runtime_approvals`.
- **Added** immutable, checksummed agent versions (§11, §12): DRAFT →
  READY_FOR_REVIEW → APPROVED → PUBLISHED → DEPRECATED/REVOKED; publish
  recomputes and compares the `sha256` checksum, blocking on tamper.
- **Added** the Runtime Gateway (§24-§28, §33): the only execution entry
  point — agent/deployment/version state → idempotency → the existing
  Phase 4.3.6 `AuthorizationGateway` (RBAC/ABAC) → runtime policy → human
  approval → the Postgres-backed queue. Denials and policy blocks are
  saved as inspectable execution rows rather than raised as errors.
- **Added** the worker runtime (§31-§37): `SELECT ... FOR UPDATE SKIP
  LOCKED` claim + `execution_locks` lease, per-attempt retry with a
  non-retryable error allowlist, dead-lettering after `maximum_retries`.
  Driven inline/eagerly by the Runtime Gateway in this environment (no
  Redis/Celery dependency added).
- **Added** the Model Gateway (§40-§42) and Tool Gateway (§43, §44):
  provider-/tool-neutral contracts; only the `MOCK` model provider and the
  `FUNCTION`/`echo` tool action actually execute — every other provider or
  tool type is fully authorized but fails closed
  (`MODEL_PROVIDER_UNAVAILABLE`/`TOOL_ACTION_NOT_ALLOWED`).
- **Added** runtime approvals (§39, new `runtime_approvals` table — the
  existing `Approval` model is 1:1 with `agent_action_id` and doesn't fit
  a deployment/execution-scoped approval) and the kill switch (§60,
  execution/agent/organization scope, always audited and reason-required).
- **Added** the runtime dashboard and Operations Center (§70, §75):
  live KPIs, 7-day execution trend, status distribution, worker health
  derived from heartbeat age.
- **Added** frontend `modules/runtime`: 11 pages + `RuntimeNav`
  (permission-filtered, mirrors `GovernanceNav`); `/runtime/*` routes;
  linked from `AdminNav`.
- **Added** 17 new backend integration tests
  (`tests/authorization/test_runtime.py`): lifecycle, checksum tampering,
  deployment gating, idempotency, concurrency limits, tool authorization
  with retry, mission-critical approval, kill switch, and role-scoping.
  Backend **561** green; frontend tsc + build clean; verified end-to-end
  in a real browser (register → activate an agent → publish a version →
  deploy → run an execution to `SUCCEEDED`).
- Docs: [docs/runtime/](docs/runtime/) — overview, architecture,
  agent-lifecycle, versioning, deployments, executions, workers-and-queue,
  capabilities-and-tools, gateways, runtime-policy-and-approvals,
  health-and-observability, operations-and-kill-switch, security.

### Part 5.0 hardening — acceptance-criteria gap closure

- **Fixed** runtime limits: `maximum_executions_per_minute` and
  `maximum_cost` (rolling daily budget) are now enforced alongside
  `maximum_concurrent_executions`; `maximum_tokens` is checked pre-flight.
  Every count excludes the execution under evaluation — without that, a
  request always counted against its own limit before being decided.
- **Added** execution timeout enforcement (§36):
  `maximum_execution_seconds` bounds the model call via
  `ThreadPoolExecutor` + `future.result(timeout=)` (cross-platform, unlike
  `signal.alarm`); exhausted retries after a timeout report `TIMED_OUT`.
- **Added** `ExecutionWorkerService.reap_expired_locks` (§32): recovers
  executions left `RUNNING` by a worker that never renewed its
  `execution_locks` lease, called opportunistically before every claim;
  `POST /runtime/workers/reap` for operator-triggered recovery.
- **Added** tool constraint enforcement (§23): `read_only`,
  `maximum_calls_per_execution` and `allowed_domains` are real checks in
  the Tool Gateway now, not just stored JSONB.
- **Added** kill-switch PROJECT and PLATFORM scopes (§60); PLATFORM
  additionally requires the actor's role to be `SUPER_ADMIN` — the
  ordinary per-organization permission grant is not sufficient on its own
  for a cross-tenant action.
- **Added** input/output JSON Schema contract validation (§7.2, new
  `jsonschema` dependency): execution input is validated against the
  agent definition's `input_schema` before an execution row is created;
  output against `output_schema` before an attempt can report `SUCCEEDED`.
- **Added** a central execution state-machine transition guard (§27):
  every `AgentExecution.status` change goes through
  `_set_execution_status`/`_EXECUTION_TRANSITIONS`, which rejects any
  transition outside the documented machine instead of trusting every call
  site.
- **Added** 16 new backend tests (577 total green), including regression
  coverage for two real bugs the new tests caught: a per-minute
  rate-limit off-by-one, and a test-isolation leak in the worker-reaper
  tests that could starve a later test's execution behind an orphaned
  `QUEUED` row (the claim query is intentionally global/non-tenant-scoped
  — see [docs/runtime/workers-and-queue.md](docs/runtime/workers-and-queue.md)).

## [Unreleased] — Phase 4.3 · Enterprise Authorization Platform

### Part 4.3.8 — Identity Governance & Administration (IGA)

- **Added** the `/api/v1/governance` control plane (§19) — 40 endpoints in
  `app/governance/`: certification campaigns (a thin proxy over the 4.3.7
  `AccessReviewService`, extended with `campaign_type` and MODIFIED/DELEGATED
  decisions), SoD rules/findings, toxic-permission rules/findings, governance
  findings, privileged accounts/reviews, orphaned-account detection, risk
  scores, remediation actions, compliance reports/frameworks, and the
  governance dashboard/analytics. Gated by 11 new `governance.*` permissions
  and a new builtin `ROLE_COMPLIANCE_ADMIN`.
- **Added** migration `0022_governance_iga`: `sod_rules`,
  `governance_findings`, `remediation_actions`, `governance_risk_scores`,
  `compliance_reports`, `privileged_account_reviews`, plus an additive
  `campaign_type` column on `access_review_campaigns`.
- **Added** Separation of Duties / toxic-permission detection (§9, §10): one
  rule engine (`rule_type=SOD|TOXIC_PERMISSION`) — an identity trips a rule
  when its effective, role-hierarchy-resolved permissions intersect both of
  the rule's permission sets. Detection runs on an org-wide scan endpoint
  *and* as a best-effort check after every `POST /role-assignments`
  (continuous detection, §10), never blocking the assignment it observes.
- **Added** privileged access governance (§11): lists identities holding a
  tracked admin-tier role with a live risk score and last session activity;
  review/approve/revoke — revoke removes the grant through the RBAC service.
- **Added** orphaned identity detection (§12): disabled-but-still-granted
  users, 90-day-inactive users with live assignments, stale API keys, unused
  roles — deduplicated against already-open findings.
- **Added** governance risk scoring (§13): 0–100 score from five weighted
  factors (privileged roles, open toxic/SoD findings, inactivity, failed
  certifications, outstanding approvals) → LOW/MEDIUM/HIGH/CRITICAL band.
- **Added** automated remediation (§14): typed actions against a finding.
  REMOVE_ROLE/DISABLE_ACCOUNT/DISABLE_API_KEY/EXPIRE_DELEGATION execute
  against live state; NOTIFY_MANAGER/CREATE_APPROVAL_REQUEST/REQUIRE_MFA/
  CREATE_SECURITY_TICKET are recorded as audit-tracked hooks (documented gap:
  no manager hierarchy, ticketing integration, or per-user MFA-required flag
  exists yet to wire into).
- **Added** compliance reporting (§15, §16): SOC 2/ISO 27001/HIPAA/GDPR/NIST/
  CIS/Internal control → platform-evidence mapping; immutable evidence
  snapshots; JSON/CSV export (PDF/Excel via client-side conversion).
- **Added** the governance dashboard + analytics (§21, §26): 10 widgets, 5
  charts, computed live from current governance/certification tables.
- **Added** frontend `modules/governance`: 12 pages (dashboard, campaigns,
  certification review, SoD rules/findings, toxic permissions, privileged
  access, orphaned accounts, findings, remediation, compliance, analytics) +
  `GovernanceNav`; `/governance/*` routes; linked from `AdminNav` and a new
  Settings → Security governance card.
- Docs: `docs/governance/{governance-dashboard,access-certification,
  sod-analysis,toxic-permissions,privileged-access,orphaned-identities,
  risk-scoring,remediation,compliance-reporting}.md`.
- Backend **544** tests green (14 new); frontend **267** tests green; `tsc -b`
  and `vite build` clean; verified end-to-end against a live Postgres
  database in a real headless-Chromium session (register → login → create
  and activate an SoD rule → create, launch and review a certification
  campaign — zero console errors, all mutations reflected live).

### Part 4.3.7 — Enterprise authorization administration portal

- **Added** the `/api/v1/admin` control plane (§18) — 20 endpoints in
  `app/authorization/admin/`, each a thin, permission-gated delegation to the
  existing phase services (no duplicated authorization logic, all enforcement
  through the 4.3.6 gateway): dashboard, roles CRUD, the permission catalog,
  the organization tree, the resource registry, ABAC policy CRUD, the policy
  simulator, the authorization decision explorer, access reviews and security
  analytics.
- **Added** the administration dashboard (§6): twelve tenant-scoped widgets
  (users, roles, permissions, policies, sessions, requests/denied 24h, pending
  approvals, MFA challenges, high-risk decisions, cache hit ratio, evaluation
  latency) and five charts (authorization trend, top permissions, policy
  matches, decision breakdown, approval queue).
- **Added** **access review campaigns** (§14; migration `0021`):
  `access_review_campaigns` + `access_review_items` with the DRAFT → SCHEDULED
  → ACTIVE → COMPLETED → ARCHIVED lifecycle. Activation snapshots every
  in-scope role assignment; reviewers certify or revoke each item — a revoke
  removes the underlying assignment through the RBAC service (caches
  invalidate, `ROLE_REMOVED` fires); completion requires every item decided;
  reports export as JSON with an `AUDIT_EXPORTED` event.
- **Added** the **authorization decision explorer** (§13): filterable,
  tenant-isolated decision history (identity, permission, resource, outcome,
  time range) with per-row detail; every query emits `DECISION_VIEWED`.
- **Added** the **security analytics dashboard** (§17): denied trends,
  high-risk decisions, MFA/approval rates, latency (avg/p95), cache
  performance, ABAC denies/challenges, top denied permissions and resource
  sharing trends.
- **Added** 10 portal permissions (`admin.*`, §21 — separable from the raw
  `role.manage`/`authorization.abac.*` sets) and 8 audit events (§22:
  `ACCESS_REVIEW_*`, `SIMULATION_EXECUTED`, `DECISION_VIEWED`,
  `AUDIT_EXPORTED`).
- **Frontend**: `modules/admin` — AdminDashboardPage, DecisionExplorerPage,
  AccessReviewsPage (create/activate/decide/complete/export), 
  SecurityAnalyticsPage and the permission-aware `AdminNav` unifying the
  4.3.1–4.3.5 pages (roles, organization explorer, resources, ABAC builder,
  simulator, audit) into one §5 navigation; routes under `/admin`; portal
  entry card in Settings → Security.
- **Docs**: `docs/admin/{dashboard,roles,organization-explorer,
  resource-management,abac-builder,policy-simulator,decision-explorer,
  access-reviews,audit-center,security-analytics}.md`; ERD + README + ROADMAP
  updated.

### Part 4.3.6 — Enterprise authorization middleware & enforcement architecture

- **Added** `app/authorization/middleware/`: the **AuthorizationGateway** (§22) —
  the single coordination point through which every enforcement surface authorizes;
  an immutable **AuthorizationContext** (frozen dataclass + read-only mappings,
  `identity.*` spoofing stripped at build time) assembled only by the
  `AuthorizationContextBuilder`; a pinned ten-stage **pipeline** (AUTHENTICATION →
  IDENTITY_CONTEXT → SESSION_VALIDATION → ORGANIZATION_CONTEXT → RBAC →
  RESOURCE_AUTHORIZATION → ABAC → OBLIGATIONS → AUDIT → CACHE) whose trace service
  rejects out-of-order recording; an **ObligationExecutor** (approval / MFA /
  justification flags, recursive field masking, parameter clamping, security
  notification); a **DecisionCacheService** keyed by identity × permission ×
  resource × org × RBAC-version × ABAC-generation (+ TTL and per-identity epoch —
  role, policy, org and session-revocation changes all invalidate; challenges and
  dynamic contexts never cached); `PipelineMetricsService` (§34) and the six §24
  audit events (`AUTHORIZATION_STARTED/COMPLETED/FAILED`, `DECISION_GENERATED`
  with the full pipeline trace, `OBLIGATIONS_APPLIED`, `EXECUTION_COMPLETED`).
- **Changed** every enforcement point onto the gateway (§27–§31):
  `require_permission` (all routes) now runs the full pipeline — ABAC challenges
  surface as typed errors (`APPROVAL_REQUIRED` 403, `MFA_REQUIRED` 401,
  `JUSTIFICATION_REQUIRED` 403, satisfiable in-band via `X-Justification`),
  constraint decisions ride on `request.state.authorization`, and plain denials
  keep the legacy 403 contract; `POST /api/v1/authorization/check` became a thin
  gateway call; the **agent runtime** (`process_agent_action`) applies the ABAC
  layer for agent principals (deny → BLOCK, approval → PENDING_APPROVAL into the
  human-review queue) and reports EXECUTION_COMPLETED; background workers,
  schedulers and workflow nodes authorize via `authorize_background(...)` (no
  session; account state still enforced).
- **Added** `evaluate_for_agent` to the ABAC engine (subject = AI_AGENT built
  server-side; `ai_context` may only contribute `ai.*` / `environment.*` keys) and
  a monotonic `generation` to the policy cache powering decision-cache rotation.
- **Fixed** a get-or-create race in the permission-version bootstrap (concurrent
  first requests for one org) with `ON CONFLICT DO NOTHING`.
- **Security (§36)**: middleware mandatory (bypass test proves routes fail without
  it); default deny preserved; ABAC evaluation errors **fail closed**; immutable
  context; challenge errors leak no policy internals; cached decisions are
  per-identity (poisoning impossible by key construction) and tamper-proof
  (copies out); session revocation invalidates instantly.
- **Added** `GET /api/v1/authorization/middleware/metrics` (§34) and error codes
  `ABAC_DENIED`, `APPROVAL_REQUIRED`, `JUSTIFICATION_REQUIRED` (§25).
- **Frontend (§32, §33)**: `AuthorizationProvider` (wraps the 4.3.2
  PermissionProvider; routes gateway decisions and typed API errors to the
  matching UI), `ApprovalRequiredDialog`, `MFAChallenge`, `ObligationDialog`
  (justification capture, mask/limit display), `AuthorizationErrorBoundary`,
  `PermissionGuard`, `useAuthorize` (live gateway check) and
  `decisionToUi` / `maskFields` / `actionLimits` utilities.
- **Docs**: `docs/authorization/{middleware,pipeline,obligations,context,gateway}.md`;
  README + ROADMAP updated.

### Part 4.3.5 — Attribute-Based Access Control engine (ABAC)

- **Added** the ABAC schema (migration `0020`): `abac_policies` (versioned,
  lifecycle-managed context policies — a NULL `organization_id` marks a platform policy
  no tenant can override), `abac_policy_versions` (immutable published snapshots, no FK
  so history survives deletion), `attribute_definitions` (the attribute registry),
  `abac_evaluations` (one row per decision with the redacted explanation) and
  `abac_policy_exceptions` (time-boxed, approved, auto-expiring exemptions).
- **Added** `app/authorization/abac/`: attribute registry + five providers
  (subject/resource/action/environment/AI) behind an `AttributeContextBuilder` — only
  registered attributes may appear in policies; an `OperatorRegistry` mapping all 16
  comparison operators to safe functions (no dynamic code execution, regex length +
  nested-quantifier guards against ReDoS); a recursive `ConditionEvaluator` for nested
  ALL/ANY/NOT trees (depth-capped, with a per-condition trace);
  `PolicyValidationService` (schema, attribute existence, data types, operators,
  effects, obligations); policy lifecycle DRAFT → VALIDATED → ACTIVE →
  DISABLED/DEPRECATED/ARCHIVED with publish-time snapshots, clone and rollback;
  a `PolicyResolver` (scope + target matching over the org hierarchy, per-org cache
  invalidated on any policy/attribute change); five combining algorithms
  (`DENY_OVERRIDES` default — deny → approval → MFA → justification → mask/limit →
  allow); an `ObligationService` (CREATE_APPROVAL, REQUIRE_MFA, REQUIRE_JUSTIFICATION,
  MASK_FIELDS, LIMIT_ACTION, LOG_ONLY) and a `DecisionExplanationService` that redacts
  RESTRICTED attribute values from user-facing output.
- **Changed** `POST /api/v1/authorization/check` to run ABAC **after** the baseline:
  RBAC/resource deny is final (ABAC can never grant); on baseline allow ABAC may deny,
  challenge (`REQUIRE_APPROVAL` / `REQUIRE_MFA` / `REQUIRE_JUSTIFICATION`) or constrain
  (`MASK_FIELDS` / `LIMIT_ACTION`); no applicable policy → the baseline decision stands.
  Responses now carry `decision` + `obligations`.
- **Added** 26 `/api/v1/authorization` endpoints (§30): policy CRUD, validate / publish /
  disable / archive / clone, versions + rollback, simulate (stack-wide and single-policy,
  read-only — the simulator never executes the action and is the only place subject
  attributes may be overridden), evaluate, the evaluation log, ABAC metrics, the
  attribute catalog and policy exceptions (expiry mandatory).
- **Security (§40)**: default deny preserved; only registered operators/attributes;
  caller context can never spoof `identity.*` attributes; platform policies are not
  overridable; published history is immutable; cross-tenant policies and evaluations are
  invisible; sensitive values masked in explanations and logs; 13 error codes; 17 audit
  events; 10 permissions (`authorization.abac.*`, `authorization.attribute.manage`,
  `authorization.exception.manage`) with authoring and publishing separable for
  segregation of duties.
- **Added** the admin portal (Settings → Security → Context policies): ABAC policies
  (list/detail/create/edit with the **visual policy builder** — nested condition groups,
  attribute/operator/typed-value selectors, human-readable preview, raw JSON for
  advanced admins), version history, the **Policy Simulator**, the attribute catalog,
  the evaluation viewer and policy exceptions.
- **Docs**: `docs/authorization/abac/{overview,policy-language,attributes,operators,
  combining-algorithms,policy-lifecycle,policy-simulation,security}.md`; ERD + README +
  ROADMAP updated.

### Part 4.3.4 — Enterprise resource-based authorization (RBAC + Resource ACL)

- **Added** the protected-resource registry and per-resource authorization metadata
  (migration `0019`): `resources` (owner + owner_type, visibility PRIVATE→PUBLIC_INTERNAL,
  status, JSONB resource policy), `resource_acl`, `resource_shares`, `ownership_history`,
  `resource_delegations` — all org-anchored, satellites cascading with the registry.
- **Added** `app/authorization/resources/`: `ResourceAuthorizationService` (the §5/§18
  evaluation chain — org scope → roles → explicit deny → policy → ownership → ACL →
  delegation → sharing → visibility → default deny, with a step trace), plus registry,
  ACL, sharing, ownership (audited transfers + preserved history), delegation and policy
  services and a `MembershipResolver` for USER/ROLE/TEAM/DEPARTMENT/ORGANIZATION
  principals.
- **Changed** the Permission Engine check (`POST /api/v1/authorization/check`) to route
  **registered** resources through the resource-level chain — identical roles, different
  per-resource answers; unregistered resources keep the 4.3.2/4.3.3 path.
- **Added** 20 `/api/v1/resources` endpoints (§19): registry CRUD + types,
  owner / transfer-ownership / ownership-history, ACL CRUD, share/update/revoke,
  delegate/revoke/list, policy, and `POST /resources/{id}/authorize` with identity
  simulation (`resource.manage`) powering the **Authorization Inspector**.
- **Security (§22)**: default deny; explicit deny overrides every allow; owners cannot
  bypass global denies or resource policies; platform admins cannot be ACL-denied on
  SYSTEM resources; cross-org lookups 404 and cross-org sharing is rejected; expired
  ACL entries/shares/delegations are ignored. 14 audit events
  (`RESOURCE_SHARED/UNSHARED`, `RESOURCE_OWNER_CHANGED`, `RESOURCE_ACL_CREATED/UPDATED/
  DELETED`, `RESOURCE_DELEGATED/DELEGATION_REVOKED`, `RESOURCE_POLICY_UPDATED`,
  `RESOURCE_ACCESS_GRANTED/DENIED`, …); 9 error codes; permissions
  `resource.view` / `resource.manage`.
- **Added** the admin portal (Settings → Security → Resources): Resource permissions,
  Resource ACL (search/filter + effect toggle), Sharing, Ownership transfer (+history),
  Delegation management, Authorization Inspector.
- **Docs**: `docs/authorization/{resource-authorization,resource-acl,resource-sharing,
  delegation}.md`, `resource-ownership.md` + ERD + README updated.
- **Tests**: backend **442** green (21 new: ownership/transfer, ACL deny precedence +
  expiry, sharing levels + cross-tenant, delegation lifecycle + expiry, visibility,
  policy, inspector, audit, §25 perf); frontend **242** green (7 new). tsc + build clean.

### Part 4.3.3 — Enterprise organization hierarchy

- **Added** the full hierarchy — Platform → Organization → Business Unit → Department →
  Team → Project → Resources — extending existing tables (migration `0018`): new
  `business_units`, `projects`, `resource_ownership`, `delegations`; `organizations`
  +slug/owner, `departments` +business_unit/status, `teams` +status.
- **Added** services: entity CRUD (org/BU/dept/team/project) with parent validation and
  child-deletion guards, `HierarchyResolverService`, `ResourceOwnershipService`,
  `OrganizationHierarchyService` (tree), `DelegationService` (with boundary enforcement).
- **Changed** the Permission Engine to resolve a resource's ownership path into the
  check's `ResourceContext` — scoped grants now apply via **downward inheritance** — and
  to enforce **cross-organization isolation** (foreign-org resources denied unless the
  caller holds `*` or an active delegation).
- **Added** 20+ `/api/v1` endpoints (organizations, business-units, departments, teams,
  projects, hierarchy/tree, resource-ownership, delegations) gated
  `organization.view`/`.manage`; 10 org audit events; error codes `CROSS_ORG_FORBIDDEN`,
  `ENTITY_HAS_CHILDREN`, `DELEGATION_EXCEEDS_AUTHORITY`, `BUSINESS_UNIT_NOT_FOUND`, ….
- **Added** the admin portal (Settings → Security → Organization): a searchable Hierarchy
  Explorer tree plus Business units, Departments, Teams, Projects and Delegation pages.
- **Docs**: `docs/authorization/{organization-hierarchy,hierarchy-resolution,
  resource-ownership,delegated-administration}.md`.
- **Tests**: backend **421** (8 new: CRUD/tree, department inheritance, cross-org
  isolation, delegation boundary, resolver); frontend **235** (3 new). tsc + build clean.

### Part 4.3.2 — Enterprise Permission Engine

- **Added** a centralized `PermissionEngine` (`app/authorization/engine.py`) with pure
  resolvers: Role (assigned + inherited), Permission (grant list), Wildcard (`resource.*`
  + global `*`), Scope (global→resource), Conflict (**explicit deny wins**, default deny).
- **Added** a Postgres permission cache: `permission_cache` (resolved grants per identity)
  + `permission_versions` (per-org invalidation token, bumped on any role/permission/
  assignment change) + `role_permissions.effect` (ALLOW/DENY) + `authorization_decisions`
  (decision audit with timing). Migration `0017`.
- **Changed** `require_permission` to gate through the engine platform-wide — inheritance,
  wildcards, scope and deny now apply on every endpoint (all existing checks preserved).
- **Added** `POST /api/v1/authorization/check` (evaluate the caller's access;
  `evaluation_time_ms`, `cache_hit`), role create/update `denied_permissions`, and error
  codes `ROLE_NOT_ASSIGNED`, `RESOURCE_FORBIDDEN`, `EXPLICIT_DENY`, `AUTHORIZATION_FAILED`,
  `PERMISSION_CACHE_MISS` (§28).
- **Added** the frontend permission layer: `PermissionProvider`, `usePermissions`/`useCan`,
  `ProtectedComponent` / `RequirePermission` (wildcard-aware; server is source of truth).
- **Docs**: `docs/authorization/{permission-engine,permission-resolution,wildcards,scopes,
  caching}.md`.
- **Tests**: backend **408** (25 new: wildcards, scope, conflict/deny, cache invalidation,
  `/check`, decision audit); frontend **232** (8 new). tsc + build clean.

### Part 4.3.1 — Enterprise RBAC foundation

- **Added** a new `app/authorization/` package extending the existing flat RBAC:
  role category/status/priority/assignability, a domain-grouped `resource.action`
  permission catalog, scoped role assignments (global → resource, time-boxed), an acyclic
  role hierarchy (senior inherits descendants), and an `authorization_audit` trail.
- **Added** three tables (`permission_groups`, `role_hierarchy`, `authorization_audit`)
  and columns on `roles`/`rbac_permissions`/`role_permissions`/`user_roles` — migration
  `0016`, additive. 18 built-in roles seeded globally alongside the legacy four.
- **Added** 15+ `/api/v1` endpoints (roles, permissions, permission-groups,
  role-assignments, role-hierarchy, authorization/audit) gated on
  `role.view`/`role.manage`/`role.assign`, and error codes `ROLE_ALREADY_EXISTS`,
  `CIRCULAR_ROLE_HIERARCHY`, `SYSTEM_ROLE_PROTECTED`, `ROLE_HAS_ASSIGNMENTS`,
  `INVALID_PERMISSION_NAME`, `INVALID_SCOPE`, … (§24).
- **Added** the admin portal (Settings → Security → Authorization): Roles, Permissions,
  Permission groups, Assignments, Hierarchy, Audit.
- **Docs**: `docs/authorization/{rbac,roles,permissions,role-hierarchy}.md`.
- **Tests**: backend **383** (31 new: cycle detection, scope validation, CRUD, inheritance,
  audit); frontend **221** (4 new). tsc + build clean.

## [0.4.0] — Phase 4.2.2 · Enterprise Human Authentication

The identity platform now spans authentication → sessions → registration → password
policy → recovery → account protection, closed out by an integration & release pass.

### Part 4.2.2.3.5 — Backend APIs, integration & release (close-out)

- **Added** cross-cutting HTTP middleware (`app/core/middleware.py`):
  - `RequestContextMiddleware` — a stable `X-Request-ID` on every request/response
    (inbound if supplied, else a generated UUID4), threaded into the error envelope (§15).
  - `SecurityHeadersMiddleware` — `X-Content-Type-Options: nosniff`, `X-Frame-Options:
    DENY`, `Referrer-Policy`, deny-by-default `Content-Security-Policy`,
    `Permissions-Policy`, and opt-in HSTS on every response, errors included (§16, §23).
- **Added** the standard §5 **response envelope**: `ResponseEnvelopeMiddleware` wraps
  every 2xx JSON response under `/api` as `{success, data, meta:{request_id, timestamp}}`
  (leaving `/health`, `/openapi.json` and file exports untouched); errors gain a matching
  `meta`. The SPA unwraps it centrally (`services/envelope.ts`, used by the axios
  interceptor and the bare refresh client), so no service code changed. Toggle:
  `RESPONSE_ENVELOPE_ENABLED`.
- **Added** a full-stack deployment: `frontend/Dockerfile` (Vite build → nginx serving the
  SPA and reverse-proxying `/api`), `frontend/nginx.conf`, a `web` service in
  `docker-compose.yml` (web + api + db, same-origin, no CORS), and `docs/deployment.md`
  with the §24 release checklist (provided vs operator-supplied).
- **Added** `SECURITY_*`, `REQUEST_ID_HEADER`, `RESPONSE_ENVELOPE_ENABLED` settings;
  `docs/api/http-conventions.md`, `docs/testing/strategy.md`, this changelog.
- **Verified** the §4 API contract end-to-end. Remaining honest deviation:
  admin/invitation/password routes live under `/identity` & `/security` (stable paths);
  no unreachable `logout-all`/`device-delete` stubs added.
- **Tests**: backend **352 passing** (+11 hardening/envelope tests); measured **92%** line
  coverage on `app.identity` + `app.core`. Frontend tsc + production build clean; web
  Docker image builds.

### Part 4.2.2.3.4 — Account protection & risk-based authentication

- **Added** risk scoring (0–100), progressive lockout (15m→30m→1h→24h→review),
  brute-force/credential-stuffing detection, blocked IPs, protection-rule engine, adaptive
  rate limiting and a CAPTCHA seam. Tables `account_locks`, `identity_risk_events`,
  `blocked_ips`, `identity_protection_rules` (migration `0015`). Security console UI.
- **Known limitations**: MFA `CHALLENGE` decisions fail-safe **deny** until MFA enrolment
  lands; CAPTCHA is a disabled, provider-agnostic seam.

### Part 4.2.2.3.3 — Password reset, account recovery & email change

- **Added** forgot/reset password (30-min single-use tokens, non-enumerating responses,
  revokes all sessions), verified email change, recovery-events dashboard (migration `0014`).

### Part 4.2.2.3.2 — Enterprise password policy & credential management

- **Added** single-source password policy, password history (no reuse of last 10), 90-day
  expiration with warnings, admin temporary-password reset, mandatory first-login change
  (migration `0013`).

### Part 4.2.2.3.1 — Registration, invitations & email verification

- **Added** invited + self-serve registration, invitation lifecycle, email verification,
  Postgres-backed rate limiting (migrations `0011`–`0012`).

### Part 4.2.2.2 — Login, logout & session lifecycle

- **Added** stateful session validation on every request (immediate revocation), device
  trust/block, refresh-token families with reuse detection, admin session management
  (migrations `0009`–`0010`).

### Part 4.2.2.1 — Enterprise human authentication

- **Added** `/api/v1/auth/*` on argon2id, rotating refresh tokens, account lockout, login
  history, silent refresh (migration `0008`).

## [0.3.0] — Phase 3 · Enterprise Dashboard UI

- React 19 + TypeScript SPA: agents, policies, approvals, audit, analytics dashboards.

## [0.2.0] — Phase 2 · Production-oriented platform

- Agent API-key auth, database-driven policy engine, advanced RBAC, email notifications,
  forensic audit, dashboard APIs, risk engine v2, Docker.

## [0.1.0] — Phase 1 · Backend MVP

- FastAPI + PostgreSQL control plane: agents, permissions, risk scoring, approvals,
  immutable audit logs, JWT auth.
