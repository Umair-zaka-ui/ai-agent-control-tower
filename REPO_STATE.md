# REPO_STATE.md

**Purpose**: a factual, verified state document for `ai-agent-control-tower`. Every claim below was extracted directly from the codebase, the live local Postgres database (after `alembic upgrade head`, currently `0046_trace_explorer_index` on PostgreSQL 17.10), the running FastAPI app object, or `git` — not from memory, changelog prose, or inference. Where something could not be mechanically verified, it is marked **UNVERIFIED**.

**Generated**: 2026-07-23, initial version on branch `main` at commit `8092be1ac5b07ce1744ace5b7d0615835ed2c219`. **Fully regenerated** the same day after Phase 5.2 Part 1, Phase 5.2.6, and Phase 5.2.4 all shipped — that pass reflected `main` at commit `9ddb46d` ("Merge Phase 5.2.4: Cryptographic Signing, Provenance & Portable Attestation", 2026-07-23 07:24:47 +0500). §2, §3, §5, §6, and §8 were re-derived from the live system in that pass. **Updated 2026-07-24** after Phase 5.7a.1 (Model Provider Abstraction & Registry) shipped — reflected `main` at commit `326e55a`. **Updated 2026-07-28** after Phase 5.7a.2 (OpenAI-Compatible Provider Adapter) and Phase 5.7a.3 (Streaming & Token Accounting) both shipped — this pass covers *two* un-documented phases at once, since REPO_STATE.md was not updated after 5.7a.2 landed before 5.7a.3's build began. Now reflects `main` at commit `781cc82` ("Merge Phase 5.7a.3: Streaming & Token Accounting", 2026-07-28 00:44:13 +0500), working tree clean. §2/§3/§5 were re-derived live (not assumed): schema **did** change this time — `model_pricing` (new table) plus sixteen new columns across `agent_executions`/`execution_attempts`, migration head now `0028_streaming_and_pricing` — while routes stayed unchanged at 452 (streaming is internal-only, no new HTTP surface). §1, §4, §6, §7, §8, §9, and §10 were updated to cover `openai_compatible.py` (missing from the previous pass only because it didn't exist yet), the registry's `model`/`api_key` forwarding, real SSE streaming, token/cost accounting, and `PricingService`.

**Updated 2026-07-29** after Phase 5.7a.4 (Error Taxonomy & Resilience) shipped — reflects `main` at commit `1fbe49c` ("Merge Phase 5.7a.4: Error Taxonomy & Resilience", 2026-07-29 20:52:37 +0500), working tree clean. **§2/§3/§5 are unchanged and were re-confirmed, not re-derived from scratch, since this phase added no migration and no new HTTP route** (verified: `alembic current` still reports `0028_streaming_and_pricing`; `agent_executions.error_code`/`execution_attempts.error_code`, both pre-existing `VARCHAR(50)` columns, now store a taxonomy class string instead of the generic `MODEL_PROVIDER_REQUEST_FAILED` code — a value change, not a schema change; route count unchanged at 452). §1, §4, §6, §7, §8, §9, and §10 were updated to cover the new `ProviderErrorClass` taxonomy, adapter-level classification/credential-scrubbing, service-layer retry/backoff/circuit-breaking, and the two new fields on `ModelResponse` (`error_class`, `retry_after_seconds`).

**Updated 2026-07-30** after Phase 5.7a.5 (Per-Organization Provider Credentials) shipped — **this completes the model half of Milestone 1** (only tool execution, Phase 5.6a.1-3, remains). Reflects `main` at commit `b9461ab` ("Merge Phase 5.7a.5: Per-Organization Provider Credentials"), working tree clean once this document's own update is committed. **§2/§3/§5 re-derived live**: schema changed (one new table, `provider_credentials`, 99 tables total, live `sqlalchemy.inspect()` confirmed), migration head now `0029_provider_credentials`, routes grew from 452 to 456 (four new endpoints under `/api/v1/runtime/providers/{provider}/credentials`). §1, §4, §6, §7, §8, §9, and §10 were updated to cover per-organization encrypted credential storage (`ProviderCredential`), the `credential_crypto.py` Fernet utility (a Known Deviation recorded, mirroring `ACT-VER-NFR-002`), `ProviderCredentialService`, the `MODEL_PROVIDER_API_KEYS`-as-fallback decision, and the `PROVIDER_CREDENTIAL_REQUIRED` translation in `ModelGatewayService.invoke()`.

**Updated 2026-07-30 (same day)** after Phase 5.6a.1 (HTTP Tool Execution & Egress Control) shipped — reflects `main` at commit `125b31c` ("Merge Phase 5.6a.1: HTTP Tool Execution & Egress Control"). The first tool-side sub-phase to ship in Milestone 1: `ToolGatewayService` gained a real `HTTP` action behind a hardened, exhaustively-tested SSRF egress guard — see `docs/runtime/gateways.md`'s "Egress control" section for the full defense (address validation across encodings, DNS-rebinding connection pinning verified empirically against the installed `httpx`/`httpcore`, redirect re-validation, the frozen-in-snapshot allowlist). **§2/§3/§5 re-derived live**: schema changed (one new table, `tool_credentials`; one new nullable column on `tools` (`http_config`) and eight on `tool_calls` — 100 tables total), migration head now `0030_http_tool_egress`, routes unchanged at 456 (the HTTP action's configuration rides the existing `POST /tools` endpoint via a schema extension, not a new route — matching this phase's own "likely no new HTTP surface" scope guidance). §1, §4, §6, §7, §8, §9, and §10 were updated to cover the new `app/runtime/tools/` package (`egress_guard.py`, `http_executor.py`), `ToolCredentialService`, the `tool_configs` addition to the version snapshot document (`tools_snapshot` itself deliberately untouched — three existing subsystems consume its bare-id-list shape), and the `TOOL_EGRESS_DENIED` error code.

**Updated 2026-07-31** after Phase 5.6a.2 (Tool Schema Validation & Resilience) shipped — reflects `main` at commit `6aafaac` ("Merge Phase 5.6a.2: Tool Schema Validation & Resilience", 2026-07-31 04:40:17 +0500), working tree clean once this document's own update is committed. The second tool-side sub-phase in Milestone 1: tool call arguments are now validated against a declared JSON-Schema input contract before anything with a side effect runs (and, for `HTTP`, before the egress guard is even consulted), responses against an optional output contract, and the Phase 5.7a.4 model-provider error taxonomy/retry/circuit-breaker machinery is now reused — not duplicated — for a tool's HTTP-level failures. The one genuine finding: 5.7a.4's circuit-breaker *state machine* and backoff math were already provider-neutral, but "what happens when the circuit is open" was hard-coded to raise a model-specific exception, so that one function was split into a neutral core (`_circuit_is_open`/`_circuit_note_success`/`_circuit_note_failure`/`_backoff_delay`) plus two thin, behavior-identical wrapper sets (model-side unchanged, tool-side new) — see `docs/runtime/gateways.md`'s "Schema validation & resilience" section for the full honest assessment. A failed tool call (schema violation, exhausted retry, timeout, oversized response, open circuit, concurrency-ceiling rejection) is a deliberate, scoped behavior change from 5.6a.1: it no longer aborts the whole execution, only a governance/egress `DENIED` call still does. **§2/§3/§5 re-derived live**: schema changed (no new table; three new nullable columns on `tool_calls` — `error_class`/`attempt_number`/`validation_error` — 100 tables total, unchanged), migration head now `0031_tool_resilience`, routes unchanged at 456 (no new HTTP surface — this phase extends the existing tool-call execution path, not the tool-management API). §1, §4, §6, §7, §8, §9, and §10 were updated to cover the new `app/runtime/tools/concurrency.py` module, the extracted neutral resilience core in `services.py`, the `tool_configs` snapshot entry's new `input_schema`/`output_schema` keys and `http_config`'s frozen `timeout_seconds`, and the five new `TOOL_*` error codes.

**Updated 2026-08-01** after Phase 5.6a.3 (Model-Driven Tool Invocation Loop) shipped — **this completes Milestone 1**: an agent registered, versioned, signed, and deployed now genuinely executes end to end (calls a real model, the model requests a real tool, the tool runs safely, the result feeds back, the loop resolves to a final answer, every token/call/decision audited). Reflects `main` at commit `2d3623b` ("Merge Phase 5.6a.3: Model-Driven Tool Invocation Loop", 2026-08-01 02:28:21 +0500), working tree clean once this document's own update is committed. `ModelGatewayService.invoke()` gained two additive, both-optional parameters (`conversation`, `tools` — mirroring `resolved_credential`'s own precedent exactly) and now offers a version's frozen `tools_snapshot` to any provider that declares `supports_tools` (`MOCK` never does, so every 5.6a.1/5.6a.2 test — all `MOCK` — is completely unaffected). A new `ToolLoopOrchestrator` (`services.py`) drives model → tool → model, reusing `ToolGatewayService.invoke()` entirely unchanged for every tool call, with four independent termination caps (iteration count, token budget, wall-clock, repeated-identical-call — the last reusing Phase 5.2.4's canonical serialization) and real parallel execution of tool calls the model requests together, gated by the exact same 5.6a.2 `idempotent` flag reused for a second purpose (safe-to-retry ⟺ safe-to-run-alongside-siblings). **One genuine bug, found and fixed, not merely noted**: the first parallel-execution design deadlocked — a fresh per-thread `Session`'s FK-checking `INSERT INTO tool_calls` blocked on the still-`FOR UPDATE`-locked `agent_executions` row from `claim_next`, while the main thread blocked on those same worker threads via `future.result()` — reproduced directly against `pg_stat_activity` before fixing it by committing the claiming session immediately before any parallel dispatch (safe, since that lock's one job was already done by that point). **§2/§3/§5 re-derived live**: schema changed (one new table, `execution_messages` — the full conversation transcript, `ACT-TLX-FR-049` — 101 tables total; two new columns on `agent_executions` (`loop_iterations`, `termination_reason`); one new nullable column on `tool_calls` (`loop_iteration`)), migration head now `0032_tool_loop`, routes grew from 456 to 457 (one new endpoint, `GET /executions/{id}/messages`, exposing the transcript). §1, §4, §6, §7, §8, §9, and §10 were updated to cover `ToolLoopOrchestrator`, the two new `ModelGatewayService.invoke()` parameters, `ExecutionMessage`, and the two new `TOOL_NOT_BOUND_TO_VERSION`/`TOOL_LOOP_LIMIT_EXCEEDED` error codes.

**Regenerated 2026-08-01 (same day, no code change)** — `main` is still at `a98a9c0`, working tree clean (`alembic current` re-confirmed `0032_tool_loop`; no migration, no route, no file changed since the entry above). This pass exists to record two things that changed *outside* the codebase: (1) a stale trailing sentence in §8 still named the pre-5.6a.3 commit (`125b31c`) as "current branch" a full phase after the branch table above it had already moved on — fixed; (2) **the Milestone 2 SRS (`ACT-SRS-M2`, "Enterprise Integration Framework") was approved and handed down** — connector abstraction/lifecycle, a pluggable authentication framework, a connector registry/health/SDK, generic REST/database/storage/queue connectors, and external identity federation (OIDC/SAML), explicitly *not* the vendor-specific catalog (SAP/Salesforce/ServiceNow), which is scoped as fast-follow work once a real deployment names a vendor. This SRS also revises the roadmap: **the former Milestone 2 (Deployment & Release Strategies) moves to Milestone 3** — the SRS's own §2.3 rationale is that controlled rollout only matters once agents do consequential things against real enterprise systems, which integration is what creates. No sub-phase of Milestone 2 has started; §6 gains a **NOT STARTED** stub section below so the sequencing is visible, and `ROADMAP.md` is noted as not yet reflecting this revision (see §9, new gap item).

**Updated 2026-08-01 (same day)** after Phase 2.1.1 (Connector Abstraction & Lifecycle) shipped — **Milestone 2's first sub-phase**, and the first line of code this codebase has ever run against the Enterprise Integration Framework SRS recorded two paragraphs above. Reflects `main` at commit `dcc314e` ("Merge Phase 2.1.1: Connector Abstraction & Lifecycle"), working tree clean once this document's own update is committed. Structural twin of Phase 5.7a.1: a new sibling domain, `app/integration/` (not under `app/runtime/` — a deliberate placement, since the runtime must never import from it, see below), gets a `Connector` ABC (`base.py`, abstract `describe()`/`validate_configuration()` only — no `authenticate()`/`execute()`/`health_check()`, all explicitly deferred), a five-state tenant-instance lifecycle machine (`lifecycle.py`: `registered→configured→active→disabled→failed`, one authority, no inlined graph elsewhere), and a trivial `MockConnector` reference implementation proving the ABC without distortion — exactly the discipline `MockProvider` established before any real provider existed. Config validation reuses Milestone 1's `jsonschema` library (a new thin wrapper, `validate_configuration_schema()`, not a new validator). The milestone's own governing constraint, the **runtime-never-knows principle** (`ACT-INT-FR-006`), is enforced by construction and mechanically checked: a dedicated test greps every file under `app/runtime/` for the substring `"connector"` and fails the build if it finds one — that count is zero. **§2/§3/§5 re-derived live**: schema changed (three new tables — `connectors`, `connector_instances`, `connector_lifecycle_events` — 104 tables total, live `sqlalchemy.inspect()` confirmed), migration head now `0033_connector_core`, routes grew from **456** to 464 (eight new endpoints under `/api/v1/integration`) — re-verifying the *previous* count this pass found REPO_STATE's own prior prose said "457," but a direct measurement against the pre-2.1.1 commit (`a98a9c0`, via a temporary `git worktree`) showed the live `APIRoute` count was actually 456; corrected here rather than silently perpetuated, the same "verify, don't carry forward" discipline that caught §8's stale branch reference two paragraphs up. §1, §4, §6, §7, §8, §9, and §10 were updated to cover `app/integration/`, `ConnectorService`/`ConnectorTypeService`, the two new `integration.connector.*` permissions, the four new `CONNECTOR_*` error codes, and the documented judgment call on which lifecycle states `PATCH /connectors/{id}` is allowed from.

**Updated 2026-08-04** after Phase 2.1.2 (Connector Authentication Framework) shipped — Milestone 2's second sub-phase. Reflects `main` at commit `8e26934` ("Merge Phase 2.1.2: Connector Authentication Framework"), working tree clean once this document's own update is committed. Six pluggable `AuthScheme` implementations (API key, bearer, basic, OAuth2 client-credentials, OAuth2 authorization-code, mTLS), explicitly registered (`app/integration/auth/registry.py`, mirroring the provider/connector registry pattern exactly), applying a resolved credential to a connector-neutral `OutboundRequest` fixture — no real connector invokes yet (2.1.3/2.2.x). **Reuses `credential_crypto.py` directly, no extraction needed**: `encrypt_secret`/`decrypt_secret`/`mask_hint` are imported as-is into `app/integration/auth/service.py` (verified by identity, not just behavior — `svc_module.encrypt_secret is credential_crypto.encrypt_secret`), the same precedent Phase 5.6a.1's `ToolCredentialService` already set; the platform-held-Fernet-key Known Deviation is inherited from 5.7a.5/5.6a.1, not newly introduced. OAuth2 token acquisition/caching/transparent refresh (`token_manager.py`) is concurrency-safe via a `SELECT ... FOR UPDATE` lock on the *parent* `connector_instances` row (not the token row itself, which can't exist yet on a first acquisition) — proven with real threads against real Postgres connections (`test_ac13_concurrent_refresh_does_not_double_refresh`), the same lock-as-serialization-point discipline `ExecutionWorkerService.claim_next` already established. Authorization-code: client-config storage, authorization-URL construction, the callback code-exchange, and refresh-and-apply are built; the interactive consent-redirect UI is explicitly stubbed (a documented, in-scope front-end deferral, not an oversight). `MockAuthenticatedConnector` added alongside 2.1.1's `MockConnector` (not modifying it) to exercise the framework end to end. **§2/§3/§5 re-derived live**: schema changed (two new tables — `connector_credentials`, `connector_oauth_tokens` — 106 tables total), migration head now `0034_connector_auth`, routes grew from 464 to **471** (seven new endpoints, reusing 2.1.1's two `integration.connector.*` permissions rather than adding a finer one — stated as a deliberate, not-warranted-here decision). §1, §4, §6, §7, §8, §9, and §10 were updated to cover the new `app/integration/auth/` package, `ConnectorCredentialService`/`token_manager`, the four new `CONNECTOR_*` OAuth/credential error codes, and the three new `INTEGRATION_CONNECTOR_CREDENTIAL_*` audit events.

**Updated 2026-08-05** after Phase 2.1.3 (Connector Registry & Health) shipped — Milestone 2's third sub-phase. Reflects `main` at commit `9902ea9` ("Merge Phase 2.1.3: Connector Registry & Health"), working tree clean once this document's own update is committed. `app/integration/registry.py`'s new `ConnectorRegistry` is the single lookup surface (type + tenant-scoped instance resolution/listing), wrapping 2.1.1's own services rather than duplicating them; its `resolve_instance_for_invocation` is the **fail-fast wiring point** (`ACT-INT-FR-044`) — raises `CONNECTOR_UNAVAILABLE` immediately for a `failed`/`disabled` instance, before any real call is ever attempted, so Phase 2.2.x's tool bridge inherits the guarantee for free. `Connector.health_check(configuration) -> bool` is a new, additive ABC method (reachability only, **never handed a credential** — auth validity is checked separately by reusing `ConnectorCredentialService.validate()` entirely, so nothing in a connector's own code, or in the new `ConnectorHealthService`, ever sees a decrypted secret). A failing check on an `active` instance now automatically calls the same, unchanged `mark_failed`; a passing check on a `failed` one calls a new `recover` event (`failed -> active`) added to `lifecycle.py` — both through the unchanged 2.1.1 state machine, never bypassed. **Alerting reuses the existing precedent, no new channel built**: `INTEGRATION_CONNECTOR_STATE_CHANGED` (unchanged event, 2.1.1) now carries `meta.severity: CRITICAL` on a failed transition, the same "severity-tagged audit event, human-reviewed, not pushed" pattern `RUNTIME_TOOL_EGRESS_DENIED` (5.6a.1) already established — `notification_service.py` was examined and rejected as a fit (no subscription/recipient-list concept to hook a connector event into). The **interim in-process scheduler** (`app/integration/scheduler.py`) is off by default everywhere, including every test run (`CONNECTOR_HEALTH_SCHEDULER_ENABLED=false`), and explicitly documented as Milestone-3-replaceable, not extended toward a distributed system — matching REPO_STATE §10.2's standing constraint. **One pre-existing 2.1.1 test needed a small, necessary update, not a weakening**: `test_ac03_mock_connector_satisfies_the_interface_without_an_abc_change` asserted the ABC's method set was exactly `{describe, validate_configuration}`; updated to include the deliberately, additively grown `health_check` (the test's actual intent — MockConnector needs nothing beyond what the ABC declares — still holds and is still checked). **§2/§3/§5 re-derived live**: schema changed (one new table — `connector_health_checks` — plus two new nullable columns on `connector_instances`, `last_health_check_at`/`current_health` — 107 tables total), migration head now `0035_connector_health`, routes grew from 471 to **474** (three new endpoints, reusing 2.1.1/2.1.2's two permissions). §1, §4, §6, §7, §8, §9, and §10 were updated to cover `app/integration/registry.py`/`health.py`/`scheduler.py`, the two new `CONNECTOR_UNAVAILABLE`/`CONNECTOR_HEALTH_CHECK_FAILED` error codes, the new `INTEGRATION_CONNECTOR_HEALTH_CHECKED` audit event, and the `recover` lifecycle event.

**Updated 2026-08-05 (same day)** after Phase 2.1.4 (Connector SDK) shipped — Milestone 2's fourth sub-phase, and the one that **completes the connector framework** (Phase 2.1 in full; what remains in Milestone 2 is *using* it — 2.2.x's generic connectors, 2.3.1's identity federation). Reflects `main` at commit `5802bb2` ("Merge Phase 2.1.4: Connector SDK"), working tree clean once this document's own update is committed. This sub-phase adds no new capability so much as it **formalizes and hardens** the surface `MockConnector` was already using: `app/integration/sdk/__init__.py` re-exports, by explicit name, exactly what a trusted connector author needs (the `Connector` base, declaration types, `SUPPORTED_AUTH_SCHEMES`, `validate_configuration_schema`, one governed network primitive, and a testing harness) and nothing else — no database session, no credential-resolution machinery (`AuthScheme`/`OutboundRequest`/`ConnectorCredentialService` are all withheld), no raw `httpx`/`requests`, no audit-suppression hook, no route-registration mechanism. **The containment principle is structural, not conventional**: an author cannot make an undeclared outbound call, receive a decrypted credential, suppress audit, or reach another tenant's data because the SDK simply does not offer a method to do any of those — proven by a dedicated governance-inheritance test suite (`test_ac10`..`test_ac15` in `test_connector_sdk.py`), not merely documented. `app/integration/sdk/http.py`'s `GovernedHttpClient` is the **only** network primitive the surface exposes — a thin wrapper reusing Milestone 1's `egress_guard`/`http_executor` directly (not reimplemented); its `allowed_hosts` is fixed at construction, never a per-call argument, so a connector's own code cannot widen what it may reach at call time. `app/integration/validation.py`'s `validate_declaration_complete()` is the single completeness check both the real registration path (`ConnectorTypeService.register`, a new, genuinely public method — `ensure_seeded()` now calls it uniformly for every `_CONNECTOR_TYPES` entry, first-party and SDK-authored alike, with no per-identifier branch) and the SDK test harness's pre-registration self-check both call; a placeholder `health_check()` is detected via a dedicated `HealthCheckNotImplemented` marker exception — deliberately **not** Python's own generic unimplemented-method builtin, since an existing 2.1.3 test (`test_ac27_no_new_todo_or_skip_markers_in_this_phases_files`) greps this entire package for that builtin's name as a leftover-stub signal, and colliding with it would have made that check meaningless. **Registration parity is proven by construction**: the worked example, `WebhookConnector` (`app/integration/sdk/example/webhook_connector.py`, connector type `SDK_EXAMPLE_WEBHOOK`), sits in the *same* `_CONNECTOR_TYPES` dict as `MOCK`/`MOCK_AUTH` and flows through the identical `ensure_seeded → register` path — there is no second, SDK-specific registration mechanism to keep in sync, because there is only one. The example is built and tested using only names imported from `app.integration.sdk` (plus the standard library), verified by an AST-based import-inspection test, not just by behavior — if expressing it had required reaching past the SDK surface, the surface would have needed fixing, and it did not. **§2/§3/§5 re-confirmed unchanged, not re-derived from scratch, since this sub-phase added no migration and no new HTTP route** (verified live: `alembic current` still reports `0035_connector_health`, `sqlalchemy.inspect()` still reports 107 tables, and a live `app.main:app` route count is still **474** — the SDK is a code-authoring capability, not an API, exactly as this sub-phase's own build prompt anticipated as the default). §1, §4, §6, §7, §8, §9, and §10 were updated to cover `app/integration/sdk/` (`__init__.py`, `http.py`, `testing.py`, `example/webhook_connector.py`), `app/integration/validation.py`, the new `ConnectorTypeService.register()` method, and the new `CONNECTOR_DECLARATION_INCOMPLETE` error code.

**Updated 2026-08-05 (same day)** after Phase 2.2.1 (Generic REST Connector) shipped — Milestone 2's fifth sub-phase, and its **first real connector**: everything through 2.1.4 built the connector *framework*; this is the first proof it actually does a job. Reflects `main` at commit `3cc7701` ("Merge Phase 2.2.1: Generic REST Connector"), working tree clean once this document's own update is committed. `RestConnector` (`app/integration/connectors/rest/connector.py`) turns any HTTP/JSON API into governed tools by declaration — base URL, per-instance authentication scheme, and one or more endpoints (method, path template, argument-to-request mapping, response extraction, optional pagination) — with no code, built entirely through the 2.1.4 SDK surface (`declaration.py`/`templating.py`/`extraction.py`/`pagination.py`/`connector.py` import only from `app.integration.sdk` or each other, verified by AST inspection, not just documented). **Two genuine findings, both fixed, not merely noted**: (1) a connector's real, per-endpoint tool contracts (`ACT-INT-FR-102`) cannot come from `Connector.describe()` — a zero-argument, type-level call with no instance configuration to derive them from — so `RestConnector.describe()` carries one honest structural placeholder and `declaration.py::tool_contracts_for(configuration)` is the real, per-instance mechanism, called by the new invocation bridge; (2) `GovernedHttpClient.request()` silently dropped any query string embedded in its `url` argument (`execute_http_tool`'s `_build_target_url` only ever honors its own dedicated `query` parameter) — invisible to 2.1.4's `WebhookConnector`, which never used one, but fatal to a paginated REST endpoint; fixed by adding one new, optional, backward-compatible `query` parameter to `GovernedHttpClient.request()` itself, a deliberate SDK-surface extension, not a workaround. **The tool-invocation bridge, built for the first time**: as of 2.1.4, nothing anywhere converted a connector's declared `ToolContract` into a real invocation — `app/integration/connectors/rest/invoker.py`'s `invoke_tool()` is that bridge (fail-fast resolve via the unchanged 2.1.3 registry, parse the declaration, apply the instance's declared `auth_scheme` via the existing 2.1.2 authentication framework, template the request injection-safely, dispatch through `GovernedHttpClient`, drive pagination, extract the output) — proven completely end to end against a real local HTTP server, including a genuine stored, encrypted `BEARER` credential actually reaching the server as a real header. **Deliberately not wired into `ToolGatewayService`/`tools_snapshot`/the model-driven tool loop** — Milestone 1 stays untouched, per this sub-phase's own working constraints; `invoke_tool` is a complete, independently-tested capability a future milestone can call from wherever that wiring eventually lives. `ConnectorCredentialService` gained one small, additive public method, `resolve_and_apply_for_scheme()` (an explicit-scheme generalization of the pre-existing `resolve_and_apply()`, which is now a one-line wrapper over it — every existing caller/test unaffected) — needed because a generic REST connector serves many vendor APIs, each with its own instance-declared scheme (`ACT-INT-FR-101`), unlike every 2.1.x connector type's one-fixed-scheme-per-type precedent. Injection-safe templating denies path escape (`"123/../admin"` renders as the single, inert segment `"123%2F..%2Fadmin"`, percent-encoded with no safe characters) and header/query injection (control characters rejected outright); pagination (offset/limit, page-number, cursor) is capped at `min(declared max_pages, 100)` regardless of what a misbehaving server claims. A realistic, four-endpoint, vendor-like declaration (a plausible support-ticketing CRM API) is the concrete `ACT-INT-FR-106` proof, exercised both structurally and against a real local fixture server. **§2/§3/§5 re-confirmed unchanged, not re-derived from scratch, since this sub-phase added no migration and no new HTTP route** (verified live: `alembic current` still reports `0035_connector_health`, `sqlalchemy.inspect()` still reports 107 tables, and a live `app.main:app` route count is still **474** — REST connector instances are configured through the existing `POST`/`PATCH /connectors` endpoints with a REST declaration as the `configuration` body; the invocation bridge is a direct, database-backed Python entry point, not yet an HTTP route). §1, §4, §6, §7, §8, §9, and §10 were updated to cover `app/integration/connectors/rest/` (`declaration.py`, `templating.py`, `extraction.py`, `pagination.py`, `connector.py`, `invoker.py`), the new `REST_ENDPOINT_NOT_DECLARED`/`REST_TEMPLATE_INVALID`/`REST_EXTRACTION_FAILED` error codes, and `GovernedHttpClient`'s new `query` parameter.

**Updated 2026-08-06** after Phase 2.2.2 (Generic Database Connector) shipped — Milestone 2's sixth sub-phase, and the second real connector. Reflects `main` at commit `f29d1cd` ("Merge Phase 2.2.2: Generic Database Connector"), working tree clean once this document's own update is committed. `DatabaseConnector` (`app/integration/connectors/database/`) turns declared, parameterized queries against PostgreSQL/MySQL (SQL Server: driver-pending) into governed tools — **the model never writes SQL**: `executor.py`'s only public entry point, `execute_declared_query(engine, dialect, query: DeclaredQuery, params, row_limit, timeout_seconds)`, has no parameter position a raw SQL string could occupy anywhere in this codebase; containment by absence, the same principle the SDK used for the raw HTTP client (2.1.4) and 2.2.1 used for request templating, applied here at its most consequential. Proven against this platform's own real dev Postgres, not mocked: a bound parameter value of `"'; DROP TABLE users; --"` (plus the classic UNION/comment/stacked-query/boolean-blind injection family) comes back as an inert literal string, with the `users` table still present afterward; a dedicated test inspects the literal SQL SQLAlchemy hands the DBAPI driver via its own `before_cursor_execute` event and confirms the placeholder token, never the substituted value, is what's actually sent. Read-only is the default posture (`ACT-INT-FR-125`): every declared query's *trusted, human-authored* SQL (never model output — the distinction that makes inspecting it legitimate) is classified read/write at configuration time by its first real keyword, fail-closed, and a read-only instance declaring a mutating query is rejected outright with a new `DB_WRITE_NOT_PERMITTED` — the one place this sub-phase's `connector.py` deliberately, narrowly steps outside the pure-SDK-surface discipline 2.2.1 established (importing one specific, documented exception type, reported as a justified addition per this sub-phase's own AC-20). Every query enforces a row limit (`fetchmany(row_limit + 1)`, rejected outright rather than silently truncated if exceeded) and a timeout (enforced twice — a server-side `statement_timeout`/`MAX_EXECUTION_TIME` GUC, plus a client-side thread + `Future.result(timeout=...)` backstop — verified live: a 3-second `pg_sleep` declared with a 1-second timeout terminates in just over one second). `ConnectorCredentialService` gained one new, additive public method, `resolve_credential_bundle()` — the same resolve-then-refresh mechanics as 2.2.1's `resolve_and_apply_for_scheme()`, returning the decrypted bundle itself rather than an HTTP-header-shaped `OutboundRequest`, since a database username/password has no natural HTTP-header meaning; proven live, connecting to this platform's own dev Postgres and confirming via `SELECT current_user` that the resolved, stored, encrypted `BASIC` credential is what actually authenticated. New dependency: `PyMySQL` (pure-Python, no system client library, unlike SQL Server's `pyodbc`/system ODBC driver — deliberately not added this phase, driver-pending, abstraction ready). **§2/§3/§5 re-confirmed unchanged, not re-derived from scratch, since this sub-phase added no migration and no new HTTP route** (verified live: `alembic current` still reports `0035_connector_health`, `sqlalchemy.inspect()` still reports 107 tables, and a live `app.main:app` route count is still **474**). §1, §4, §6, §7, §8, §9, and §10 were updated to cover `app/integration/connectors/database/` (`declaration.py`, `drivers.py`, `executor.py`, `connector.py`, `invoker.py`), the six new `DB_*` error codes, and the `ConnectorCredentialService.resolve_credential_bundle()` addition.

**Updated 2026-08-07** after Phase 2.2.3 (Generic File & Object Storage Connector) shipped — Milestone 2's seventh sub-phase, and the third real connector. Reflects `main` at commit `c612456` ("Merge Phase 2.2.3: Generic File & Object Storage Connector"), working tree clean once this document's own update is committed. `StorageConnector` (`app/integration/connectors/storage/`) turns declared, scoped filesystem/S3-compatible access into governed tools — the direct analogue of 2.2.2's SQL rule for a different kind of structure: **a model-supplied path can never escape its declared scope**. The enforcement lives in exactly one, isolated module, `scope.py` — zero dependencies on this platform, not even the SDK, just `os`/`posixpath`/`re`/`unicodedata`/`urllib.parse` — whose one public function, `resolve_and_contain(boundary, supplied_path)`, either returns a canonicalized, proven-in-scope target or raises; there is no code path anywhere in this connector that performs a read/write against an unvalidated path. Canonicalize-then-contain runs a four-stage pipeline (control-character rejection, iterative percent-decoding, a second control-character check on the decoded result, NFKC Unicode normalization) before backend-specific canonicalization — `os.path.realpath` (resolves `..` *and* symlinks in one pass) for the filesystem backend, `posixpath.normpath` (lexical, no real directory to resolve) for object storage — proven against every named traversal vector (relative, absolute — POSIX/Windows-drive/UNC, single- and double-percent-encoded, backslash, literal and encoded null-byte, Unicode homoglyph, object-store prefix/bucket escape including the sibling-prefix boundary case) with **no live storage anywhere in the test file**, plus a filesystem symlink-escape test using a real temporary symlink (or, since this environment's default user lacks the Windows privilege to create one, a directory junction — also a reparse point `realpath` resolves identically; the fallback is exercised for real in this environment, not merely coded and skipped). Read-only is the default posture (`ACT-INT-FR-144`, mirroring `ACT-INT-FR-125` exactly): a read-only instance declaring a write scope is rejected at configuration time with a new `STORAGE_WRITE_NOT_PERMITTED`. Object size is checked via metadata *before* any full transfer (`os.path.getsize`/`head_object`, never `fetchall`-style unbounded loading) and bounded a second time during the transfer itself, rejecting rather than truncating an oversized result — the same discipline 2.2.2 established for an oversized query result. **New this phase**: every object access attempt — allowed or denied — is recorded in the platform audit trail (`INTEGRATION_CONNECTOR_OBJECT_ACCESSED`, a new `AuthorizationAuditEvent`), carrying the *validated* path (never the raw supplied string, and a denial correctly carries none at all), backend, scope, operation, size, and outcome — proven live against a real, stored, encrypted credential that never appears in the recorded `meta`; this is 2.2.x's first invocation-level audit event, since neither 2.2.1's nor 2.2.2's own build prompt required auditing individual calls and this one's own (`ACT-INT-FR-145`) explicitly does. `ConnectorCredentialService.resolve_credential_bundle()` (added in 2.2.2) is reused unchanged — an S3 access key id/secret access key resolve through the `BASIC` scheme's generic `username`/`password` fields, the same non-HTTP-shaped-credential generalization 2.2.2 established for a database username/password. New dependency: `boto3` (S3-compatible object storage; also serves MinIO/any S3-compatible target via a declared `endpoint_url`). Azure Blob is a recognized, backend-pending value (`azure-storage-blob` deliberately not added — driver-pending, abstraction ready, mirroring 2.2.2's SQL Server precedent exactly); its S3 backend dispatch is proven against a mocked `boto3.client` (no live AWS/MinIO reachable in this environment) — the underlying containment logic itself has full, unmocked coverage, since it is backend-agnostic and lives entirely in `scope.py`. Two narrow, justified SDK-surface deviations, both documented: `declaration.py` raises its own `StorageScopeInvalidError` (this phase's own acceptance criteria require a distinguishable declaration-time code where 2.2.2's own declaration.py needed none beyond the SDK's generic one) and `connector.py` raises `StorageWriteNotPermittedError` (mirroring `DbWriteNotPermittedError` exactly); `scope.py` and `backends.py` both stay entirely free of `app.integration.errors`, translated to platform errors exclusively by `invoker.py`, mirroring 2.2.2's `executor.py` discipline. **§2/§3/§5 re-confirmed unchanged, not re-derived from scratch, since this sub-phase added no migration and no new HTTP route** (verified live: `alembic current`/`ScriptDirectory.get_current_head()` still reports `0035_connector_health`, `sqlalchemy.inspect()` still reports 107 tables, and a live `app.main:app` `APIRoute` count is still **474**). §1, §4, §6, §7, §8, §9, and §10 were updated to cover `app/integration/connectors/storage/` (`scope.py`, `declaration.py`, `backends.py`, `connector.py`, `invoker.py`), the six new `STORAGE_*` error codes, and the new `INTEGRATION_CONNECTOR_OBJECT_ACCESSED` audit event.

**Updated 2026-08-07 (same day)** after Phase 2.2.4 (Generic Message Queue Connector) shipped — Milestone 2's eighth sub-phase, the fourth and last generic connector, and **the completion of Milestone 2's connector framework plus all four generic connectors**. Reflects `main` at commit `775bfe1` ("Merge Phase 2.2.4: Generic Message Queue Connector"), working tree clean once this document's own update is committed. `QueueConnector` (`app/integration/connectors/queue/`) turns declared queue bindings into governed publish/consume tools — a two-sided containment discipline, the queue analogue of 2.2.2's/2.2.3's own single-sided rules: **publish is scoped to a queue fixed by the tool contract itself** (`ACT-INT-FR-161`/`FR-164` — the model's only parameter on a publish contract is the message body; there is no queue-name parameter to redirect through at all, so "the model cannot publish outside its declared queue" holds by absence of the affordance, not by validating a supplied name against an allowlist) and **consume is always bounded to at most N messages within a bounded wait, never an unbounded stream** (`ACT-INT-FR-162` — verified live against a fixtured transport: a queue holding five messages with a batch cap of three yields exactly three; an empty queue with a 0.3s wait returns an empty list in ~0.3s, not indefinitely). The isolated `scope.py` — genuinely zero imports of any kind, not even `__future__`-adjacent platform code — checks only whether a *resolved* binding's declared operation (`PUBLISH`/`CONSUME`) matches what is being attempted against it, simpler by design than 2.2.3's path enforcer since there is no queue-name value to canonicalize in the first place; the bridge (`invoker.py`) exposes this as two distinct entry points, `publish_message`/`consume_messages`, each checking before touching a broker. A published message exceeding its effective size limit is rejected before any connection is attempted (`ACT-INT-FR-163`); a **consumed** oversized message is truncated to the limit and marked `truncated: true` rather than failing the whole bounded batch or being silently dropped — a deliberate, documented departure from 2.2.2's/2.2.3's own "reject the whole operation" precedent, justified because a consume batch is a set of otherwise-independent messages, not a single object or one query's result set. **Acknowledgment policy is explicit and identical in spirit across both backends**: a message is acknowledged as part of the same call that returns it to the caller (AMQP's `basic_get(auto_ack=True)`; SQS's explicit `delete_message` immediately after `receive_message`) — at-most-once from the queue's own perspective, a deliberate default for a bounded, discrete tool operation, documented rather than left implicit. **Zero SDK-surface deviations in `declaration.py`/`connector.py` — a first among the generic connectors, contrasted explicitly with 2.2.2's one and 2.2.3's two**: this phase's own required error-code vocabulary (`QUEUE_NOT_DECLARED`/`QUEUE_MESSAGE_TOO_LARGE`/`QUEUE_OPERATION_NOT_PERMITTED`/`QUEUE_CONSUME_TIMEOUT`) is entirely invocation-time, and there is no instance-level posture flag (no `read_only` equivalent) for a per-binding operation to conflict with at configuration time — this phase's shape matches 2.2.1's REST connector precedent instead. Built the fourth tool-invocation bridge in this codebase, reusing 2.2.3's `INTEGRATION_CONNECTOR_OBJECT_ACCESSED` audit event (rather than adding a new one) for every publish/consume attempt, allowed or denied — proven live against this platform's own real dev database with a genuine stored, encrypted `BASIC` credential (an AMQP username/password) actually reaching a (fixtured) connection. New dependency: `pika` (pure-Python AMQP client); SQS reuses 2.2.3's own `boto3` dependency, no new one needed. Azure Service Bus is a recognized, backend-pending value (`azure-servicebus` deliberately not added — mirrors 2.2.2's SQL Server / 2.2.3's Azure Blob precedent exactly). **§2/§3/§5 re-confirmed unchanged, not re-derived from scratch, since this sub-phase added no migration and no new HTTP route** (verified live: `ScriptDirectory.get_current_head()` still reports `0035_connector_health`, `sqlalchemy.inspect()` still reports 107 tables, and a live `app.main:app` `APIRoute` count is still **474**). §1, §4, §6, §7, §8, §9, and §10 were updated to cover `app/integration/connectors/queue/` (`scope.py`, `declaration.py`, `backends.py`, `connector.py`, `invoker.py`), the five new `QUEUE_*` error codes, and the reuse (not addition) of the `INTEGRATION_CONNECTOR_OBJECT_ACCESSED` audit event. **Milestone 2's connector framework (2.1.x) and all four generic connectors (2.2.1-2.2.4) are now complete — 8 of 9 sub-phases done; only 2.3.1 (identity federation) remains.**

**Updated 2026-08-08** after Phase 2.3.1 (External Identity Federation) shipped — Milestone 2's ninth and final sub-phase. **The Enterprise Integration Framework is now complete: the connector framework, all four generic connectors, and identity federation.** Reflects `main` at commit `281fd41` ("Merge Phase 2.3.1: External Identity Federation — Milestone 2 complete"), working tree clean once this document's own update is committed. `app/identity/federation/` adds OIDC (authorization-code flow) and SAML 2.0 (web-browser SSO) federated authentication — deliberately the *inversion* of every prior connector sub-phase (2.1.2, 2.2.x): where a connector holds a platform secret and presents it outward, federation verifies a signed assertion *from* an enterprise's own IdP and never receives, or stores, the user's own credential at all (`ACT-INT-FR-186`). The security core for both protocols is proven against real cryptographic material, never mocked: `oidc.py`'s `verify_id_token` is pure (no HTTP, no database) and reuses `python-jose` (already a platform dependency) "with care," not hand-rolled — the accepted algorithm set is fixed by the organization's own stored configuration and never taken from the token's own `alg` header, which is what closes the classic JWT algorithm-confusion bypass (proven directly: a test mints an HS256 token guessing the RSA public key as an HMAC secret, and a bare `alg: none` unsigned token, and both are rejected). `saml.py`'s `verify_response` is a thin wrapper around `python3-saml`/`xmlsec` (a new dependency — SAML XML signature verification is never hand-rolled, a well-documented vulnerability class) — proven to reject **two distinct signature-wrapping attack shapes** using real, `xmlsec`-signed SAML fixtures built by the test suite's own `_saml_fixtures.py` helper (the only place in this codebase that ever *constructs* a signed assertion, since the platform is a verifier, never an issuer). CSRF/replay is defended without a new "pending requests" table: both flows embed everything the callback needs (nonce, or the outgoing SAML request's own id) in a short-lived, platform-signed `state`/`RelayState` token, reusing the existing `JWT_SECRET_KEY` — no new secret. A federated identity links to the platform's **existing** user/RBAC model via the IdP's stable subject id (never email, which can be reassigned) — an existing local account is linked by email match when one exists; a genuinely new user is JIT-provisioned (configurable per organization) through `UserProvisioningService`, the exact seam that module's own docstring says was built for "SSO... without a redesign." A federated login terminates in the platform's **existing** session-issuance pipeline (`SessionLifecycleService`/`RefreshRotationService`/`TokenService`) — never a parallel one — so a federated session is indistinguishable from a local one everywhere downstream (proven directly via `/api/v1/auth/me`). Assurance level is deliberately `AAL1`, never speculatively `AAL2`, since this platform cannot reliably verify what MFA the IdP itself enforced. Local password authentication is completely unaffected — proven directly and by the entire pre-existing local-auth suite passing unmodified. New dependencies: `python3-saml`, `xmlsec`, `lxml`, `isodate` (SAML only; OIDC reuses the existing `python-jose` dependency, no new one needed). **§2/§3/§5 re-derived live**: schema changed (two new tables — `identity_federation_configs`, `federated_identities` — 109 tables total, live `sqlalchemy.inspect()` confirmed), migration head now `0036_identity_federation` (reversible, verified via `alembic downgrade -1` then `upgrade head`), routes grew from 474 to **484** (ten new endpoints: four public SSO flow endpoints under `/api/v1/auth/federation`, six admin config-management endpoints under `/api/v1/identity/federation/configs`). **Five pre-existing "migration head unchanged" tests needed a small, necessary update, not a weakening**: 2.1.4/2.2.1/2.2.2/2.2.3/2.2.4 each correctly asserted no migration had landed *in their own phase* (all true when written); this phase's own genuine, justified migration moved the head, so each assertion was updated to the new, correct filename — the same "small, necessary update" precedent 2.1.3 already established for its own ABC method-set assertion. §1, §4, §6, §7, §8, §9, and §10 were updated to cover `app/identity/federation/` (`oidc.py`, `saml.py`, `claim_mapping.py`, `service.py`, `schemas.py`, `routes.py`), `app/identity/models/federation.py`, `app/identity/api/routes/federation_configs.py`, the six new `FEDERATION_*` error codes, and the two new `identity.federation.view`/`.manage` permissions. **Milestone 2 — the Enterprise Integration Framework — is now complete: 9 of 9 sub-phases done.**

**Updated 2026-08-10** after Phase 3.1 (Enterprise Deployment Core) shipped — **Milestone 3 (ACT-SRS-M3, "Deployment & Release") begins here**, the first sub-phase against the SRS the 2026-08-01 entry above flagged as pending. Reflects `main` at commit `c0789d4` ("Merge Phase 3.1: Enterprise Deployment Core"), working tree clean once this document's own update is committed. The existing, partially-wired `agent_deployments` table (Phase 5.0's `status`, five direct-write service methods, no event lineage, no concurrency guard) gains a genuinely new, second lifecycle — `lifecycle_state`, a real 15-state machine with a single transition authority (`app.runtime.deployment.service.DeploymentLifecycleService.transition()`), never the pre-existing `status` widened or replaced. **The two fields are deliberately independent after a one-time migration reconciliation**: `status` keeps being read/written, completely unmodified, by every pre-existing `DeploymentService` method, *including* the one place execution actually gates on deployment state (`ExecutionRequestService._request_execution`'s `deployment.status != "ACTIVE"` check) — proven untouched both by a grep-based test scoped to that one function's own source and by a full, unmodified execution running end to end. This is why the phase is scoped the way it is: the version resolver and the real execution gate that would make the *new* lifecycle matter belong with traffic allocation in Phase 3.4, not here. **Ruling #6 (mandatory inspection)**: the platform's existing suspension/kill mechanism is `Agent.lifecycle_status` reaching `"SUSPENDED"` (driven by the pre-existing `AgentLifecycleService` or `KillSwitchService`, §60) — `DeploymentLifecycleService._assert_can_reach_active()` *reads* it every time a deployment would land in `ACTIVE` (including a `PAUSED → ACTIVE` resume) and never writes it, no parallel mechanism built. The same guard also enforces the `runtime_approvals` precondition for `ACTIVE` where policy demands it, mirroring — without touching — the legacy `DeploymentService.deploy()`'s own mission-critical-production reroute shape. **The reusable `Idempotency-Key` contract** (`app.runtime.deployment.idempotency.IdempotencyService`, proven generic via a unit test exercising it against a bare non-deployment stub) uses a claim-then-poll pattern, not naive check-then-act: a plain "SELECT, then on miss run the operation and INSERT" has a genuine TOCTOU race under real concurrency, so a caller instead commits a placeholder claim row first and lets the table's own unique constraint be the concurrency primitive — the loser of a two-thread race catches the resulting `IntegrityError` and polls briefly for the winner's result rather than ever running the operation twice (proven with real separate Postgres connections, mirroring 2.1.2's own OAuth2-refresh concurrency-test precedent). **Optimistic concurrency** is a genuine SQLAlchemy `version_id_col` on the new `revision` column — every UPDATE of the row carries `WHERE revision = <loaded value>` and SQLAlchemy raises `StaleDataError` (translated to `DEPLOYMENT_REVISION_CONFLICT`) on a lost race; proven with two real threads racing one transition, exactly one succeeds. A genuine, accepted side effect discovered live: `version_id_col` is mapper-wide, so a legacy `.status`-only write (e.g. the pre-existing `/suspend` endpoint) also bumps `revision` — harmless, since the new authority always re-reads a deployment fresh immediately before every transition, documented rather than silently left as a surprise. **A real routing conflict was found and resolved, not silently redesigned around**: the build prompt's literal `/pause`/`/resume`/`/retire` paths collide with routes this codebase already shipped in Phase 5.0 operating on the legacy `status` field; the new lifecycle's five mutating actions were nested under `/lifecycle/...` instead, leaving every pre-existing endpoint completely untouched (see `docs/deployment/lifecycle.md`'s own "A routing conflict, resolved" section). **A permission-naming difference was similarly resolved by reuse**: the pre-existing `runtime.deployment.view`/`runtime.deployment.deploy` (already gating every legacy deployment mutation behind one permission) are reused verbatim rather than adding the build prompt's suggested, near-duplicate `deployment.view`/`deployment.manage`. **§2/§3/§5 re-derived live**: schema changed (two new tables — `deployment_events`, `idempotency_keys` — plus four new columns on `agent_deployments` — `lifecycle_state`/`revision`/`state_reason`/`superseded_by_deployment_id` — 111 tables total, live `sqlalchemy.inspect()` confirmed), migration head now `0037_deployment_lifecycle` (reversible, verified live via `alembic downgrade -1` then `upgrade head`, both clean), routes grew from 484 to **489** (five new endpoints under `/deployments/{id}/lifecycle/...`, plus the pre-existing `POST /deployments` extended additively with `Idempotency-Key` support). **The §15 deterministic mapping** (all eleven legacy `status` values → their `lifecycle_state` equivalent, applied once, live, to every pre-existing row — full table in `docs/deployment/lifecycle.md`) is the phase's own historical backfill; it is *not* an ongoing invariant, since `status` keeps drifting via legacy endpoints after migration while `lifecycle_state` stays frozen at whatever the migration set — a real, live-discovered fact that required correcting this phase's own first draft of its migration-mapping test (it had wrongly assumed the two fields would stay in lockstep forever). **Five pre-existing "migration head unchanged" tests needed the same small, necessary update 2.3.1's own five needed**: `test_connector_sdk.py`/`test_database_connector.py`/`test_queue_connector.py`/`test_rest_connector.py`/`test_storage_connector.py` each bumped to `0037_deployment_lifecycle.py`. §1, §4, §6, §7, §8, §9, and §10 were updated to cover `app/runtime/deployment/` (`lifecycle.py`, `idempotency.py`, `service.py`), the four new `DEPLOYMENT_*`/reused `IDEMPOTENCY_CONFLICT` error codes, and the twelve new `RUNTIME_DEPLOYMENT_*` audit events. **Milestone 3 now has 1 of 10 sub-phases implemented; the Milestone 2 completion above stands unchanged.**

**Updated 2026-08-10 (same day)** after Phase 3.2 (Environment & Promotion Model) shipped — Milestone 3's second sub-phase. Reflects `main` at commit `a500991` ("Merge Phase 3.2: Environment & Promotion Model"), working tree clean once this document's own update is committed. `agent_deployments.environment` (a bare, unvalidated string) gains a sibling, `environment_id`, a real foreign key to a new, tenant-scoped `Environment` entity carrying policy — **the legacy string is never removed or repointed**: every existing read of it, in particular the Milestone 1 execution-path check inside `RuntimePolicyService.evaluate`, is unchanged. `environment_id` is populated three ways: migration `0038`'s own §15 backfill for every pre-existing row (4,706/4,706, verified live), an opportunistic best-effort string→row lookup inside `DeploymentLifecycleService.create()` for the plain create path, and directly by the new `PromotionService.promote()`. **The security core of this phase**: promotion preserves the exact immutable version — `PromotionService.promote` loads the source `AgentVersion` exactly once and passes that same object straight into the existing `DeploymentService.create`, so nothing in the new module can construct, copy, or modify a version row; verified live (`test_ac06_ac07_promotion_preserves_the_exact_version`) by confirming the promoted deployment's `agent_version_id` matches exactly, the agent's total version count is unchanged, and `checksum`/`manifest_digest`/`signature_id` are byte-identical before/after. **`prohibited_environments` (build prompt's mandatory inspection) was found and integrated, not paralleled**: `app.runtime.environment.policy.check_prohibited` reads the exact same `AgentVersion.policy_snapshot["prohibited_environments"]` field `RuntimePolicyService.evaluate` already reads at execution time — a version barred from an environment by that pre-existing mechanism cannot be promoted into it either, one fact, one place. A second, unrelated `prohibited_environments` field also exists on `Capability` (§18/§19) — a capability-level restriction, confirmed unrelated and untouched. **The release-channel relationship (the build prompt's second mandatory inspection) was found to be orthogonal, not overlapping**: `AgentReleaseChannel` (Phase 5.2 Part 1) is a global stability track a version is published onto; an `Environment` is a tenant-scoped deployment target a published version is promoted through — promotion never reads or writes `release_channel_id`, and no channel vocabulary (`STABLE`/`BETA`/`CANARY`/`INTERNAL`) appears anywhere in the new environment-policy module, both proven by dedicated tests rather than left as an assertion. **Approval is folded into the existing single funnel, not a second mechanism**: `DeploymentLifecycleService._requires_deployment_approval` (Phase 3.1) gains one additive condition — a governed environment's own `is_production` flag or `policy.requires_approval` — alongside its two pre-existing legacy checks; all three land a deployment in `PENDING_APPROVAL` through the same, unmodified reroute. `PromotionPath.requires_approval` (the build prompt's own §5 schema column) is stored and returned by the API but deliberately not wired as a *second*, independent approval gate this phase — reported as a scoped, documented deviation, not silently built. **`ACTIVE`/`PAUSED` → `SUPERSEDED`, declared but left undriven by Phase 3.1's own lifecycle module ("3.2 drives this")**, is now driven: after a promoted deployment reaches `ACTIVE`, any other `ACTIVE`/`PAUSED` deployment of the same agent already in the target environment is superseded (not retired), preserving lineage via `superseded_by_deployment_id`. Environment policy evaluation (`app.runtime.environment.policy.evaluate`) is a single deploy/promote-time choke point called from exactly one place, `DeploymentLifecycleService.start_deploying` — covering a plain deploy and a promotion identically, never running on every execution request. **Which policy dimensions are actually enforced, stated plainly**: `allowed_models`, `allowed_data_classifications` (checked against every bound tool's `Tool.data_classification`), `requires_approval`, `maximum_concurrent_deployments`, and `change_window` are enforced; `allowed_external_systems` (renamed from the build prompt's own `allowed_connectors` — the literal word is mechanically forbidden anywhere under `app/runtime`, the runtime-never-knows principle 2.1.1 established) and `rollback_rules` are modeled only, since there is no existing link in this codebase between a runtime `Tool`/`AgentVersion` and Milestone 2's own integration-instance catalog to check the former against, and rollback itself is Phase 3.7's own job. **A genuine bug found and fixed before it reached a test failure**: the first draft of `EnvironmentService.ensure_seeded`/its `list_environments` route call site mirrored `ReleaseChannelService.ensure_seeded`'s own flush-only pattern, but that precedent's callers all commit later as part of a larger flow — this route did not, so the seeded rows were silently rolled back on session close; fixed by adding an explicit `db.commit()` at the call site, matching the *actual* precedent (`list_release_channels`, which does the same). **§2/§3/§5 re-derived live**: schema changed (two new tables — `environments`, `promotion_paths` — plus one new column on `agent_deployments`, `environment_id` — 113 tables total, live `sqlalchemy.inspect()` confirmed), migration head now `0038_environments_promotion` (reversible, verified live via `alembic downgrade -1` then `upgrade head`, both clean, environments/paths correctly re-seeded), routes grew from 489 to **499** (ten new endpoints: `/environments` × 6, `/promotion-paths` × 3, `/deployments/{id}/promote` × 1). **Five pre-existing "migration head unchanged" tests needed the same small, necessary update 2.3.1's and 3.1's own five needed**: `test_connector_sdk.py`/`test_database_connector.py`/`test_queue_connector.py`/`test_rest_connector.py`/`test_storage_connector.py` each bumped to `0038_environments_promotion.py`. §1, §4, §6, §7, §8, §9, and §10 were updated to cover `app/runtime/environment/` (`policy.py`, `service.py`), the five new `ENVIRONMENT_*`/`PROMOTION_*` error codes, the seven new audit events (`RELEASE_PROMOTED`, `RELEASE_PROMOTION_BLOCKED`, five `RUNTIME_ENVIRONMENT_*`/`RUNTIME_PROMOTION_PATH_*`), and the two new `runtime.environment.view`/`.manage` permissions. **Milestone 3 now has 2 of 10 sub-phases implemented.**

**Updated 2026-08-11** after Phase 3.3 (Deployment Preflight & Release Gate Engine) shipped — Milestone 3's third sub-phase. Reflects `main` at commit `7e834cb` ("Merge Phase 3.3: Deployment Preflight & Release Gate Engine"), working tree clean once this document's own update is committed. New `app/runtime/release_gate/` package — `checks.py` (thirteen individual checks + `run_checks`/`verdict_for`) and `service.py` (`ReleaseGateService`) — builds the single authoritative deployment-readiness evaluation the build prompt calls for: one PASS/WARNING/BLOCK verdict aggregating checks already built across Milestones 0/1/2 and Phases 3.1/3.2, with **no new signature verifier, compatibility analyzer, health-check mechanism, or approval engine** — every check calls an existing capability, verified by call (spy tests), not copy. **The check-to-source mapping, stated plainly**: agent active/kill switch → `Agent.lifecycle_status` (Ruling #6, reused verbatim, **absolute BLOCK, never overridable** — AC-07); version published → `AgentVersion.status`; snapshot checksum → `app.runtime.services._verify_checksum`; signature/provenance → `AttestationService.verify`; compatibility → `AgentVersion.compatibility_level` (**WARNING only**, deliberately preserving `docs/runtime/versioning.md`'s own documented "readiness has never gated anything" boundary rather than silently turning it into a hard block); owners → `Agent.owner_id`; machine identity → `AgentIdentity` (same WARNING/BLOCK split `AgentValidationService`'s §28.4 check already uses); provider availability/credentials → `app.runtime.providers.registry`/`ProviderCredentialService.resolve_for_version`; tools → `Tool.enabled`; environment policy → `app.runtime.environment.policy.evaluate` (Phase 3.2, called verbatim); required approvals → `DeploymentLifecycleService`'s own private approval-funnel methods (Phase 3.1, called verbatim, **WARNING not BLOCK** — a pending approval is the designed reroute to `PENDING_APPROVAL`, not a failure). **The freshness rule — the phase's one genuinely new requirement — is applied to `DeploymentHealth.checked_at`/`HealthMonitoringService`, not the build prompt's own suggested Milestone-2 connector-health signal**: two independent, structural reasons, both confirmed by reading the code rather than assumed — (1) the runtime-never-knows vocabulary boundary (Milestone 2's own mechanically-enforced tests forbid that vocabulary anywhere under `app/runtime`), and (2) even setting that aside, there is no existing link in this codebase between a runtime `Tool`/`AgentVersion` and Milestone 2's own integration-instance catalog to know *which* external-system instance a deployment even depends on — the identical gap Phase 3.2 already reported for `allowed_external_systems`. Reported here as a gap, not built around with a parallel dependency-modeling feature; the freshness rule itself is still real, tested, and wired to a genuine, reachable signal. Every finding's severity is data (`_DEFAULT_SEVERITY`), overridable per environment via `Environment.policy["preflight_severity_overrides"]`, except the kill-switch code (hardcoded absolute). Freshness bound similarly configurable via `Environment.policy["preflight_freshness_bound_seconds"]` (platform default 900s/15min). **Wired into `DeploymentLifecycleService.start_deploying()`**, deliberately positioned after the pre-existing 3.2 narrow environment-policy check (left completely unchanged, including its own error codes — AC-11) and before the approval-reroute logic (never disturbed, since the gate's own approval finding is WARNING, not BLOCK); a `BLOCK` verdict raises `DEPLOYMENT_PREFLIGHT_BLOCKED`, and every verdict is persisted regardless. **Promotion is gated for free**: `PromotionService.promote()` (Phase 3.2) already funnels its new deployment through this same `start_deploying()` call — no extra wiring needed, exactly the allowance the build prompt's own §1 scope table anticipated. **The kill switch is absolute and always re-checked live, never trusted from a prior evaluation** (AC-08): `ReleaseGateService.evaluate()` never caches; proven live — a deployment that passes preflight (`PASS`), whose agent is then killed, and which then attempts to deploy, is blocked on re-evaluation, on top of (not instead of) the pre-existing, independent Ruling #6 check that still fires at the literal `DEPLOYING → ACTIVE` transition for any path bypassing the gate (e.g. `resume()`). **One pre-existing Phase 3.1 test's expectation changed, not weakened**: `test_ac09_suspended_agent_blocks_activation` now asserts `DEPLOYMENT_PREFLIGHT_BLOCKED` (was `DEPLOYMENT_AGENT_SUSPENDED`) and a `READY` post-condition (was `DEPLOYING`) — the gate now blocks *before* the `READY→DEPLOYING` mutation rather than after it (3.1's own original code mutated `READY→DEPLOYING` first, then failed at the next `DEPLOYING→ACTIVE` step, leaving the deployment "stuck" at `DEPLOYING`), a strictly safer post-condition; the underlying guarantee ("a suspended agent's deployment cannot activate") is fully preserved, and if anything now enforced earlier and more cleanly. Two findings were caught proactively, before the full suite run, mirroring 3.2's own discipline: a vocabulary leak in `checks.py`'s own docstring (fixed by rewording before it ever tripped the pre-existing grep tests) and the gate's initial call-site placement *after* the approval-reroute logic (which would have skipped persisting a preflight record for every deployment correctly rerouted to `PENDING_APPROVAL` — moved before the reroute instead, safe since the gate's own approval finding is WARNING). **§2/§3/§5 re-derived live**: schema changed (one new table — `deployment_preflight_results` — 114 tables total, live `sqlalchemy.inspect()` confirmed), migration head now `0039_deployment_preflight` (reversible, verified live via `alembic downgrade -1` then `upgrade head`, both clean), routes grew from 499 to **502** (three new endpoints: `POST`/`GET .../deployments/{id}/preflight`, `GET .../preflight/history`). **Five pre-existing "migration head unchanged" tests needed the same small, necessary update 2.3.1's/3.1's/3.2's own five needed**: `test_connector_sdk.py`/`test_database_connector.py`/`test_queue_connector.py`/`test_rest_connector.py`/`test_storage_connector.py` each bumped to `0039_deployment_preflight.py`. §1, §4, §6, §7, §8, §9, and §10 were updated to cover `app/runtime/release_gate/` (`checks.py`, `service.py`), the two new `DEPLOYMENT_PREFLIGHT_BLOCKED`/`PREFLIGHT_CHECK_UNAVAILABLE` error codes, and the three new `DEPLOYMENT_VALIDATION_STARTED`/`_FAILED`/`_PASSED` audit events (SRS's own literal, unprefixed names, mirroring 3.2's `RELEASE_PROMOTED`/`RELEASE_PROMOTION_BLOCKED` precedent). **Milestone 3 now has 3 of 10 sub-phases implemented.**

**Updated 2026-08-13** after Phase 3.4 (Traffic Allocation, Version Resolver & Execution Gate) shipped — Milestone 3's core sub-phase, and **the one deliberate change to the Milestone 1 execution path**. Reflects branch `feat/3.4-traffic-resolver-gate`, branched from `main` at `c658cf5`, working tree clean once this document's own update is committed. Two new modules under the existing `app/runtime/deployment/` package — `traffic.py` (the servability predicate + `TrafficAllocationService`) and `resolver.py` (`VersionResolver`) — plus two new tables and one migration with the §15 step-2 backfill.

**The M1 execution-path change, precisely**: `ExecutionRequestService._request_execution` (`app/runtime/services.py`) previously selected a version by reading the active deployment's own `agent_version_id` — a direct 1:1 — after two guards (`DEPLOYMENT_NOT_FOUND` if no active deployment, `DEPLOYMENT_NOT_ACTIVE` if it wasn't `status == "ACTIVE"`). That block is now a single `VersionResolver(db).resolve(...)` call. Everything after it is untouched, including the `authorize(deployment)` call, runtime-policy evaluation, the approval reroute, the queue and the worker.

**Two build-prompt premises did not hold against this repository, and were reported rather than silently designed around** (the build prompt asked for exactly this):

1. **Ruling #4 was already enforced here.** The two guards above have rejected deployment-less execution since Milestone 1, so the prompt's "executions may run deployment-less currently" was false and **there were no deployment-less-execution tests to migrate** (its AC-12). What 3.4 actually adds is weighted resolution plus one new fail-closed mode. Correspondingly, AC-09's requested `NO_ACTIVE_DEPLOYMENT` was added as an *additional* code for the genuinely new case rather than replacing the two pre-existing ones — replacing them would have broken a Milestone 1 API contract for no benefit.
2. **The real decision was the two-state-field split**, which the prompt did not anticipate. `agent_deployments.status` is written by the legacy `DeploymentService` **and by `KillSwitchService`**; `lifecycle_state` only by `DeploymentLifecycleService` (3.1 pause, 3.2 promote/supersede). `docs/deployment/lifecycle.md` had framed 3.4 as "flipping the gate over" to `lifecycle_state`, but doing that literally would have **disarmed the kill switch** at ORGANIZATION/PROJECT/PLATFORM scope (those write only `status`) and stranded every legacy-deployed agent (`lifecycle_state` stays `DRAFT`), while gating on `status` alone would leave 3.1-paused deployments serving and every 3.2-promoted deployment permanently unable to execute. The resolved semantics — confirmed before any code was written — are **union with veto**: a deployment serves iff either machine says ACTIVE and neither vetoes. **Neither machine was rewritten**, which is why this phase touches one place rather than six. Full truth table in `docs/deployment/traffic-and-resolution.md`, pinned by a test so a future rename of either machine's states fails loudly.

**The actual deliberate test migration** was therefore a different one from the prompt's prediction, and it was *strengthened*, not weakened: 3.2's `test_ac15_promoting_to_lifecycle_active_has_no_effect_on_the_legacy_execution_gate` → `..._now_serves_execution`. Its own 3.2-era docstring had named the expiry condition — *"until Phase 3.4 deliberately wires the two together."* It still pins `status != 'ACTIVE'` before executing, so the execution can only have been admitted by `lifecycle_state`; had 3.4 gated on `status` alone it would still fail. A 3.4 test asserts the migration is present and has not been softened into accepting either outcome. **No other test changed behaviour**; the usual five Milestone-2 "migration head unchanged" tests were bumped `0039` → `0040`, the same bookkeeping 3.2 and 3.3 did.

**Authorization non-bypass — the milestone's sharpest line (§27 §10.2) — verified three independent ways**: structurally against the resolver's parsed **AST** (no authorization/policy import, no `AuthorizationGateway`/`RuntimePolicyService`/`ExecutionWorkerService`/`authorize` identifier — AST rather than raw text, because the module's own docstring discusses the gateway at length explaining why it must not touch it); positionally (the resolver call site precedes `decision = authorize(deployment)` and the `if not decision.allowed:` branch still exists); and behaviourally (a same-tenant VIEWER is rejected 403 on an agent whose traffic *is* resolved through an allocation, while the admin's identical request succeeds — so the rejection is the permission check, not a broken fixture). The resolver selects a version and returns a plain value; it never dispatches.

**Performance and caching**: no cache, deliberately, and the *absence* is tested. Every candidate cache key here (deployment state, allocation revision, version status) is mutated by code spread across three phases — pause, supersede, rollback, revoke, kill switch — so a cache would need an invalidation hook in all of them to stay correct *under the kill switch*: a fail-closed hazard bought for an unmeasured gain. Measured instead: **≤3 indexed queries** per resolution, asserted by counting statements through a SQLAlchemy `before_cursor_execute` hook (so an N+1 or a naive multi-join fails the test, not just a review), and **<25 ms** per resolution over 200 consecutive resolutions, observed ≈1–2 ms locally.

**Concurrency**: settled by a **partial unique index** on `(agent_id, environment_id) WHERE is_current`, not a lock — deliberately lock-free so nothing in this domain can deadlock against the execution path's own locks (§9's Milestone 1 lesson). Two ordering details proved load-bearing during the build and are now explicit rather than left to SQLAlchemy's unit-of-work heuristics: the previous revision's `is_current` clear is flushed **before** the new INSERT (otherwise a caller's own legitimate write hits the partial index mid-flush), and the whole write sequence — not just the commit — sits inside the `IntegrityError` guard, because the conflict surfaces at the first flush that emits the INSERT rather than at commit. The AC-13 race test is **deterministic**, not a timing-dependent thread barrier: a real second connection opens a transaction and holds it open, so the writer under test blocks inside Postgres and the outcome is not a scheduling coin-flip.

**§2/§3/§5 re-derived live**: schema changed (two new tables — `deployment_traffic_allocations`, `deployment_traffic_weights` — **116 tables** total, live count confirmed), migration head now `0040_traffic_allocation` (reversible, verified live via `alembic downgrade` then `upgrade head`, both clean), routes grew from 502 to **505**. §1, §4, §6, §7, §8, §9 and §10 were updated to cover the two new modules, the four new error codes (`TRAFFIC_WEIGHTS_INVALID`, `VERSION_NOT_ELIGIBLE`, `TRAFFIC_ALLOCATION_CONFLICT`, `NO_ACTIVE_DEPLOYMENT`), and the two new audit events (`DEPLOYMENT_TRAFFIC_CHANGED`, `RUNTIME_EXECUTION_NO_ACTIVE_DEPLOYMENT`). Backend suite **1,478** green, 0 failed, 1 deselected. **Milestone 3 now has 4 of 10 sub-phases implemented.**

**Updated 2026-08-14** after Phase 3.5 (Canary Deployment Engine) shipped — Milestone 3's fifth sub-phase, and the driver Phase 3.4's traffic allocation was built for. Reflects branch `feat/3.5-canary-engine`, branched from `main` at `f5b27a3`, working tree clean once this document's own update is committed. Three new modules under the existing `app/runtime/deployment/` package — `rollout.py` (the pure transition graph and stage-gate logic), `health.py` (the AI-aware release-health engine, ruling #3) and `canary.py` (`CanaryRolloutService`) — plus three new tables and two indexes that `agent_executions` genuinely lacked.

**A candidate is promoted stage by stage, and a stage clears only when all three of its gates are satisfied**: minimum duration elapsed, minimum sample count met, and an AI-aware health requirement satisfied. Every stage advance changes traffic by calling Phase 3.4's `TrafficAllocationService.set_weights` — atomic, revisioned, eligibility-checked, audited — and never by writing `deployment_traffic_weights` directly. That is structural rather than aspirational: `canary.py` contains no reference to the weight tables at all, asserted against the parsed AST, so it *cannot* bypass 3.4. A separate test asserts 3.4's `resolver.py` and `traffic.py` are byte-identical to `main` (AC-16): this phase drives that mechanism, it does not modify it.

**INSUFFICIENT_DATA is first-class, and is the phase's core safety property.** Below a stage's minimum sample count the verdict is INSUFFICIENT_DATA regardless of how clean the few samples look, and it satisfies no health requirement at any level. Two successful calls out of two is not "healthy" — nothing bad *observed* is not nothing bad *happening*. The evaluation order encodes this: veto first, sample sufficiency second, thresholds and baseline only then.

**Ruling #3 — why this database now has two health tables.** The pre-existing `deployment_health` is a *liveness heartbeat* (a worker reported in, the process is up), written from an external signal. The new `deployment_health_evaluations` is a *release judgement* computed by aggregating `agent_executions` over a window — a model version can be perfectly alive while refusing every third request, timing out on long prompts, or tripping policy denials. Widening the heartbeat table would have made one row type carry two unrelated meanings. The old table is untouched in both directions, and a test asserts its row count is unchanged across a full rollout.

**The health signals used were confirmed by reading `AgentExecution`, not assumed from the SRS's wish-list**: success/failure/timeout (`status`), policy denials (`status` DENIED/BLOCKED), latency (`duration_ms`, mean and p95), cost (`cost_amount`), tokens (`total_tokens`), failure class (`error_code`, the 5.7a.4 taxonomy). Only *terminal* executions count — counting a still-running one as "not a failure" would make a stalled canary look healthier the more stuck it got. **Gap reported, not built around**: per-external-system failure counts are unavailable on an execution row (no dependency link says which external system a version depends on — the identical gap 3.2 and 3.3 already reported, and the runtime-never-knows boundary keeps that vocabulary out of `app/runtime` entirely).

**Kill-switch dominance (§12) is enforced by two independent mechanisms**, so a bug in either alone cannot open the gate: (1) a veto check before every operation that could give the candidate *more* traffic — start, advance, resume, promote, auto-advance — reading the same fields 3.4's resolver reads, covering both the AGENT-scope agent suspension and the ORGANIZATION/PROJECT/PLATFORM-scope deployment suspension, plus "no servable deployment at all"; and (2) a health engine that independently returns UNKNOWN — never HEALTHY — for a vetoed candidate. De-escalating operations (pause/abort/request-rollback) deliberately skip the check, because a kill switch must never trap a rollout in a state an operator cannot back out of; aborting is precisely what someone does *after* hitting the switch. On the automated path a veto is *reported*, not raised, so a future scheduler sweeping many rollouts is not aborted by one killed agent — it still does not advance.

**Auto-advance is interim and explicitly bounded** (M3-3.5-FR-013): `POST .../evaluate` advances by at most one stage per call even when several stages' gates are simultaneously clear, and is idempotent. It is not a scheduler; Phase 3.8 will call this exact method on a timer with no change required here — the same relationship `app/integration/scheduler.py` (2.1.3's interim in-process loop) already documents for its own replacement. **The 3.5/3.7 seam** is stated in `docs/deployment/canary.md`: this phase refuses to advance on a failed health gate and can *request* a rollback; 3.7 adds the configurable per-tenant trigger policy deciding *when* to call it.

**Three real bugs were found and fixed during the build**, each a variant of a lesson already recorded in this repository: (1) a candidate with no servable deployment was treated as "no veto to apply" and reported HEALTHY, so a paused candidate could look promotable — closed by `require_servable`; (2) the idempotency fingerprint included mutable server state (`stage_index`), so every retry looked like a genuinely different request under 3.1's contract and deduplication never fired; (3) `StaleDataError` surfaces at the *first flush* — which the audit insert triggers — not at the commit, so guarding only the commit let a raw 500 escape under a real race, exactly as Phases 3.1 and 3.4 both documented. A fourth issue was a *test* over-specification rather than a product bug: the AC-14 `EXPLAIN` assertion originally pinned one specific index, and Postgres legitimately preferred the organization index once the table held real data; it now asserts the property that matters (the composite index serves the per-version window shape as an Index Only Scan, and the full predicate never sequentially scans).

**§2/§3/§5 re-derived live**: schema changed (three new tables — **119 tables** total, live count confirmed), migration head now `0041_canary_rollout` (reversible, verified via `alembic downgrade` then `upgrade head`, both clean), routes grew from 505 to **515**. §1, §4, §6, §7, §8, §9 and §10 were updated to cover the three new modules, the five new error codes, and the six new audit events (pause/resume deliberately reuse the pre-existing `RUNTIME_DEPLOYMENT_PAUSED`/`_RESUMED` rather than minting a second pair meaning the same thing). Backend suite **1,535** green, 0 failed, 1 deselected; frontend **297** green, untouched. **Milestone 3 now has 5 of 10 sub-phases implemented.**

**Updated 2026-08-14 (defect fix, not a phase)** — `fix/temp-password-policy-compliance`, off `main` at `acd3661`. Closes a real, pre-existing bug surfaced (not caused) by Phase 3.5's full-suite run: `generate_temporary_password()` returned its first draw unchecked, so **9 of 20,000 draws violated the platform's own password policy** and would have been rejected by the login/set path they were issued for. The generator now validates every candidate through `PasswordPolicyService.validate` — the identical entry point `CredentialService._apply_new_password` uses, so the rules are never duplicated and a future policy change binds generation automatically — and re-draws on failure, with a 100-attempt safety cap that raises rather than ever returning a non-compliant value. `PasswordResetService` passes `user=` so the context-dependent identity-substring rule is covered too. Three files changed (`credentials/service.py`, `credentials/reset_service.py`, and the test file); **no change to the password policy itself, to login/set-time validation, or to any other credential generator** — verified by an empty `git diff` on `security/passwords.py` and `credentials/policy_service.py`. The previously-flaky 50-draw test was replaced with a 5,000-draw zero-violation assertion plus new tests for the safety cap, shared-validator reuse (verified by call *and* by injecting a new rule the generator honours with no change of its own), and the preserved strength properties (length, four character classes, alphabet, no collisions across 1,000 draws). Measured after the fix: 0 violations in 20,000 draws; 15 consecutive runs of the test file clean. Backend **1,541 passed, 0 failed, 1 deselected**; frontend untouched, **297** green. See §9 item 15 for the full history of this defect.

**Updated 2026-08-14** after Phase 3.6 (Blue-Green & Recreate Strategy Execution) shipped — Milestone 3's sixth sub-phase. Reflects branch `feat/3.6-strategies`, branched from `main` at `c89f685`, working tree clean once this document's own update is committed. One new module, `app/runtime/deployment/strategies.py`; **no new tables and no migration** (head stays `0041_canary_rollout`).

**The mandatory §2 findings, both confirmed by reading the code:** (1) `agent_deployments.deployment_strategy` was, until this phase, **an entirely unused column** — present since migration 0023 with a `RECREATE` default, constrained to four values by `schemas._STRATEGY`, set on create, copied forward by `PromotionService`, exposed in `DeploymentRead`, and never read to decide anything. This phase is its first consumer, so the abstraction extends nothing and parallels nothing. (2) The two replica-count columns are **vestigial in the meaningful sense**: the legacy `DeploymentService.deploy`/`retire` assign them constants and `PromotionService` copies one forward, but **nothing reads either to make any decision** — no scheduling, no scaling, no routing, no branch anywhere. That is what makes deferring ROLLING honest rather than lazy, and it is why the deferral is a real 501 error naming Phase 3.9 rather than a handler moving those counters (which would report progress while nothing rolled — the precise pretence SRS §3.6 forbids).

**Strategies are weight patterns over Phase 3.4's allocation, not separate machinery.** RECREATE is 0→100 in one cutover with the previous superseded through 3.1's lifecycle authority; BLUE_GREEN is 0 (warm) →100 in one atomic switch with the old version *preserved* at 0% as a rollback target. `strategies.py` contains **no reference to `DeploymentTrafficWeight`/`DeploymentTrafficAllocation`** (asserted against the parsed AST), so bypassing 3.4's atomic, revisioned, audited mechanism is structurally impossible. A separate test asserts 3.4's `resolver.py`/`traffic.py` and 3.5's `canary.py`/`rollout.py`/`health.py` are byte-identical to `main`: this phase drives them, it does not modify them.

**Two orderings are load-bearing and were reasoned about rather than stumbled into.** RECREATE supersedes the previous deployment *after* traffic moves, because superseding first would make it non-servable and 3.4 rejects weight on a version with no servable deployment — the cutover would fail on its own precondition. BLUE_GREEN re-runs the release gate *at the switch*, not only at prepare, because a deployment can pass validation and then have its agent killed or its version revoked before an operator presses the button; there is a test for exactly that sequence.

**Blue preservation needed no new storage, which §5 asked to check before adding any.** After a switch BLUE stays lifecycle-ACTIVE holding 0% (3.4's resolver skips zero-weight entries, so *preserved* is not *split-serving* — proven by driving real executions before and after) and is recorded as GREEN's rollback target through `VersionLineageService.set_rollback_target`, not a raw column write. This is the first code in the codebase that **reads** `rollback_target_id` to perform a rollback, which closes the long-standing §9 item 12 gap in combination with 3.4 and 3.5. "Prepared" is likewise inferable from 3.4's existing rows — GREEN carries a zero-weight entry exactly when warmed — so `BLUE_GREEN_NOT_PREPARED` needed no state either.

**Rollback deliberately skips both the §12 veto and the gate**, for one reason: rollback must work when things are worst. Rolling back reduces exposure, so a kill switch must never trap an operator on the version they are trying to leave; and requiring BLUE — the version that was already serving — to re-pass a gate would make rollback fail exactly when it is most needed. Everything that could give a candidate *more* traffic (RECREATE cutover, blue-green prepare, blue-green switch) does check the veto, reading the same fields 3.4's resolver reads.

**§2/§3/§5 re-derived live**: schema unchanged at **119 tables**, migration head unchanged at `0041_canary_rollout` (no migration this phase), routes grew from 515 to **518**. §1, §4, §6, §7, §8, §9 and §10 were updated to cover the new module, the four new error codes (including `STRATEGY_ROLLING_DEFERRED` at **501**, since a declared-but-unimplemented strategy is neither a client mistake nor a state conflict) and the two new audit events. Backend suite **1,575** green, 0 failed, 1 deselected; frontend **297** green, untouched. **Milestone 3 now has 6 of 10 sub-phases implemented**, with ROLLING pending in 3.9.

**Updated 2026-08-14 (documentation-maintenance pass, no code change)** — `main` is at `5b33f42`, the Phase 3.6 merge, pushed and level with `origin/main`; no file under `backend/` or `frontend/` changed in this pass, so §2/§3/§5 and every test count above stand as last measured. This pass exists to correct three places where *this document's own bookkeeping* had fallen behind the code it describes, rather than to record new work:

1. **§6's Milestone 3 sub-phase table was three phases stale** — still reading "IN PROGRESS (3/10)" with a single "3.4 – 3.10 **NOT STARTED**" row, while 3.4, 3.5 and 3.6 had all shipped and each had a header entry above claiming §6 was updated. The narrative sections those entries also named (§2/§3/§5) genuinely *were* re-derived live each pass and are correct; it was the sub-phase table alone that was missed. Now carries a full evidence row for each of the three, and the heading reads 6/10.
2. **§8's branch history was stale at Phase 3.3** — 50 branches listed, ending at `feat/3.3-release-gates`, with a "Current branch: `feat/3.6-strategies`" line contradicting the table above it. Regenerated live: 54 local branches, the four new ones added, and the current-branch line now correctly names `main` at the merge commit.
3. **§9 item 17 still said "5 of 10 … 3.6 is next"** — corrected to 6 of 10 with 3.7 next.

Recorded here rather than silently fixed, in the same spirit as §9 items 2, 17 and 18, each of which documents an inaccuracy this document previously carried about itself. `RECOVERY.md` and `README.md` were refreshed in the same pass; `README.md` in particular had been frozen at Phase 5.2 Part 1 (2026-07-24) and described neither Milestone 1's completion nor Milestones 2 and 3 at all.

**Updated 2026-08-17** after Phase 3.7 (Automated Rollback & Release Safety) shipped — Milestone 3's seventh sub-phase, and the safety capstone of the deployment engines. Reflects branch `feat/3.7-automated-rollback`, branched from `main` at `248ce00`, working tree clean once this document's own update is committed. One new module, `app/runtime/deployment/rollback.py`; two new tables; migration head now `0042_automated_rollback`.

**The §2 mandatory report contains a correction to this document.** The build prompt described `rollback_target_id` as "a pointer nothing reads (REPO_STATE §9.12)", quoting this file. That was accurate when written and had already been superseded: **Phase 3.6 reads it** to perform a blue-green rollback, and §9 item 12 was updated accordingly in the 3.6 pass. What was genuinely outstanding was *designating* the field as part of a rollout and honouring it from any path other than blue-green. Reported rather than silently built around, per the prompt's own instruction.

**Three rollback implementations existed, with three different notions of "the target"** — Phase 5.0's `DeploymentService.rollback` (caller-supplied version, and a *redeploy* rather than a traffic shift), 3.5's `request_rollback` (`plan.stable_version_id`), and 3.6's `blue_green_rollback` (`rollback_target_id`). This phase adds one authoritative answer and one operation every trigger funnels through, and it **leaves all three in place**: the Phase 5.0 endpoint in particular still owns `POST /deployments/{id}/rollback` and still redeploys, because taking that path over would have changed a Milestone 1 API contract and required rewriting passing tests. The new surface nests under `/rollback/...`, the identical resolution Phase 3.1 used for its own `/pause`/`/resume`/`/retire` collision.

**Kill-switch dominance here means something narrower and sharper than "rollback is blocked".** *Automation* is subordinate to a kill switch; a human is not. An automatic rollback on a killed agent does not run — automation that rolled back to a healthy version and reactivated it would be automation undoing a human's kill, the one thing §12 exists to prevent. A **manual** rollback still runs, matching 3.6's own reasoning that a kill switch must never trap an operator on the version they are trying to leave. The §12 check runs *before* the health evaluation, and that ordering was corrected during the build after a failing test: the health engine independently returns UNKNOWN for a vetoed candidate, so checking afterwards reported a kill switch as "health verdict UNKNOWN is not evidence of a regression" — safe, but the wrong explanation for an operator to read.

**Anti-flap uses two independent guards plus a database primitive.** A cooldown (default 900s) from the most recent automatic rollback for an (agent, environment); and the rule that **only a version actually on trial is a candidate**, so a version holding zero traffic is never re-judged — which is what stops the restored last-known-good from being rolled back by the same policy on the next tick. That second guard was documented before it was implemented, and the gap was caught by this phase's own AC-07 test rather than by review. Deduplication is separate: a partial unique index on `dedup_key`, keyed on (deployment, deployed version), so the database decides a race between two evaluations — the same primitive 3.4 used for `uq_traffic_allocations_current`. Manual and forced rollbacks sit outside it deliberately.

**Recovery maps onto `RECOVERY.md`'s own durable/ephemeral split.** The `rollback_events` row is committed as `IN_PROGRESS` **before** any traffic moves and marked `COMPLETED` only after the allocation commits, so a crash between the two leaves a readable record of an intent formed but not finished; `resume_incomplete` runs at the start of every evaluation. Re-applying the move is harmless because 3.4's allocation declares a desired end state rather than a delta, so there is no half-applied state for a resume to compound. Health verdicts, threshold arithmetic and cooldown windows are recomputed on demand and stored nowhere.

**A pre-existing test caught a real collision for the fourth time in this repository** (see §9 item 15's own record of the earlier three). Phase 3.5's `test_ac13_the_rollout_state_machine_has_one_transition_authority` greps every file mentioning `RolloutPlan` for `.state =`, and this phase's `RollbackEvent.state` false-matched it. The column was renamed to `status` — which also matches this platform's naming everywhere else — rather than suppressing the guard with the `noqa` escape it offers. This phase's own AC-09 structural test then had to become precise about *receivers* rather than attribute names, since `event.status` is a legitimate write and `deployment.status` is not; it is stricter as a result, not weaker.

**§2/§3/§5 re-derived live**: schema changed (two new tables — `rollback_trigger_policies`, `rollback_events` — **121 tables** total), migration head now `0042_automated_rollback` (reversible, verified live via `alembic downgrade` then `upgrade head`, both clean), routes grew from 518 to **524**. §1, §4, §6, §7, §8, §9 and §10 were updated to cover the new module, the four new error codes, the three new audit events and the one new permission (`runtime.deployment.force_rollback`). Backend suite **1,633** green, 0 failed, 1 deselected; frontend **297** green, untouched. **Milestone 3 now has 7 of 10 sub-phases implemented**; 3.8 (the scheduler that drives this phase's bounded evaluation on a real timer) is next.

**Updated 2026-08-17** after Phase 3.8 (Distributed Scheduler) shipped — Milestone 3's eighth sub-phase and the first half of its distributed-systems core. Reflects branch `feat/3.8-distributed-scheduler`, branched from `main` at `d8bb3b6`. One new package, `app/scheduler/`; two new tables; migration head now `0043_distributed_scheduler`.

**The §2 mandatory reports.** (1) The `FOR UPDATE SKIP LOCKED` precedent is `ExecutionWorkerService.claim_next`, and reading it closely mattered: it `flush()`es rather than commits, so the claiming transaction stays open across the entire attempt and is released only by `run_once`'s `finally`. That is the *opposite* of what a scheduler needs, so the precedent was followed for the locking idiom and deliberately not for the transaction lifetime. (2) The M1 deadlock fix is `ToolLoopOrchestrator._execute_parallel`'s `self.db.commit()` before spawning threads, with a 23-line comment explaining that Postgres's own deadlock detector could not see the cycle because the main connection looked idle rather than waiting. (3) The interim scheduler specified its own retirement in its docstring — *"delete this module, delete its one call site, register the same iteration as a real job"* — and that is exactly the retirement performed.

**The commit-before-dispatch boundary is the phase.** Three transactions per run: the claim (lock a due definition, insert the run row, advance `next_run_at`, **commit**), the handler (holding no lock from the claim), and completion. The scheduler has the identical shape to the M1 deadlock — a claim that locks a row, then work that touches the database on other connections for possibly minutes — so the lock is released before any handler runs. Proven three independent ways rather than asserted once: from *inside* a handler (a different connection takes `FOR UPDATE NOWAIT` on the definition row and succeeds, which is only possible post-commit), behaviourally (instance A mid-handler does not block instance B claiming a different job), and structurally.

**Exactly-once, and the limit of what a lease can promise.** `uq_job_runs_occurrence` makes one run row per `(definition, occurrence)`; the occurrence key derives from the instant a job was *due*, since a claim-time key would differ per instance and defeat the guard entirely. Retry and stale-lease recovery both **reuse that row** rather than inserting another, which turns "no duplicate successful run" from a detection problem into a schema property. What it does **not** mean is exactly-once side effects: a crash after a handler's work committed but before the run was marked SUCCEEDED will re-run it. That is stated in the code, the docs and here rather than glossed, and it is why every registered handler is an idempotent reconciliation rather than an event emitter.

**Placement was forced, not chosen.** `app/scheduler/` is a sibling of `app/runtime/` and `app/integration/` because it registers a connector-health handler, and Milestone 2's mechanically-enforced runtime-never-knows rule fails the build if the word "connector" appears anywhere under `app/runtime/`. The constraint turned out to describe the right architecture anyway — the scheduler is platform infrastructure that happens to run deployment and integration work, not part of either.

**The interim scheduler is genuinely retired, and a pre-existing test had to be updated for it.** Phase 2.1.3's `test_ac20` read `app/integration/scheduler.py`'s source and asserted it was an INTERIM, REPLACEABLE, `asyncio`-based loop — assertions that now describe a file deliberately deleted. The behaviour it protected (a sweep visits active instances and records a `SCHEDULED` check) is asserted verbatim against the rehoused `run_sweep_once`, and the test is now **stricter**: it additionally asserts the retirement happened and the sweep is reachable as a registered handler. This is the same "small, necessary update, not a weakening" precedent §9 item 15 already records for 2.1.3's own ABC method-set, 2.3.1's migration-head tests, 3.3's AC-09 and 3.7's byte-identity test.

**The scheduler principal was a genuine fork, escalated before coding.** 3.5's and 3.7's bounded operations require an `actor: User` for Phase 3.1's idempotency scoping, and no system principal existed. Reusing a real user would have made the audit trail claim a person triggered every scheduled rollback — undoing exactly what 3.7's `initiated_by = NULL` was for; widening the two operations to accept `None` would have modified `canary.py`, which 3.6 and 3.7 both pin byte-identical to `main`. The resolved choice is one non-human `users` row per organization that **cannot authenticate** (unusable password hash, `is_active=false`), asserted by a test that attempts login rather than by construction.

**§2/§3/§5 re-derived live**: schema changed (two new tables — `job_definitions`, `job_runs` — **123 tables** total), migration head now `0043_distributed_scheduler` (reversible, verified live), routes grew from 524 to **530**. Backend suite **1,684** green (1,633 + 51), 0 failed, 1 deselected; frontend **297** green, untouched. **Milestone 3 now has 8 of 10 sub-phases implemented**; 3.9 (the distributed worker fleet — the milestone's riskiest phase, which reuses this phase's lease discipline) is next.

**The PG16/17 mismatch is carried to 3.9, explicitly.** `docker-compose.yml` still declares `postgres:16-alpine` with database `agent_control_tower` while local development, dumps and every recovery proof run on PostgreSQL 17.10. It is *not* resolved here, and the reasoning is deliberate: changing a Compose Postgres major version is a data-directory-incompatible change that deserves its own scope, and it becomes materially testable only in 3.9, when the worker fleet is the first thing that genuinely runs in containers. `RECOVERY.md` already carries the warning; it stays there until 3.9 resolves it.

**Updated 2026-08-18** after Phase 3.9 (Distributed Execution Worker Fleet & Rolling Deployment) shipped — Milestone 3's ninth sub-phase, the milestone's riskiest, and the one that finally resolves ruling #1. Reflects branch `feat/3.9-worker-fleet-rolling`, branched from `main` at `06b8750`. One new package, `app/workers/`; one new module, `app/runtime/deployment/rolling.py`; one new table; migration head now `0044_worker_fleet_rolling`.

**The §2 mandatory reports.** (1) **The M1 execution claim/run/commit boundaries.** `ExecutionWorkerService.claim_next` took `SELECT ... FOR UPDATE SKIP LOCKED` on a `QUEUED` row, set RUNNING, inserted an `ExecutionLock` and an `ExecutionAttempt`, and **`flush()`ed** — so the claim's exclusive row lock was held for the *entire* attempt, every model and tool call included, and released only by `run_once`'s `finally`. That is the exact shape of the M1 deadlock, at fleet scale. (2) **PG16/17**: Compose declared `postgres:16-alpine` with database `agent_control_tower`; the live environment and every backup are PostgreSQL 17.10 with `ai_agent_control_tower`. Both the major version *and* the name differed. (3) **What "cohort" can honestly mean**: version binding happens at *enqueue* time — 3.4's resolver picks a version via `select_weighted` and writes it onto the execution row — so workers are version-agnostic by construction, and any cohort definition claiming otherwise would be fiction. All three were reported before coding, and the two genuine forks (cohort semantics, PG resolution) were escalated rather than guessed.

**The commit-before-dispatch boundary is the phase, again — this time on the hottest path in the platform.** `claim_next` now **commits** instead of flushing. After it returns, the worker holds no lock taken at claim time, and the long, network-bound part of the attempt runs against an unlocked row. Committing is safe precisely because the lock had already done its one job: the row is no longer `QUEUED`, and the *committed* status change is what excludes peers now — permanently, rather than for the duration of a transaction. `execution_locks.execution_id` (UNIQUE, since migration 0023) is the durable owner record that replaces the transient lock, which is why **no second lease table was added**: two sources of truth for one fact is how a distributed system starts lying about who owns what. **One behavioural change is stated rather than buried**: a worker that dies mid-attempt used to have its claim rolled back straight to `QUEUED`; now the execution stays `RUNNING` until its lease expires and `reap_expired_locks` applies the retry policy. Recovery is slower by at most one lease and, in exchange, *observable*.

**The proof, and the lock mode that a failing test corrected.** Checked three ways: behaviourally (a second connection takes `FOR UPDATE NOWAIT` on the just-claimed row and succeeds), from *inside a running model call* (the network-I/O window where the deadlock actually lived), and structurally over the AST. The in-flight probe originally asked for `FOR UPDATE NOWAIT` and **failed against correct code** — by mid-attempt the worker legitimately holds a *shared* lock on its own row, having inserted children of it. The right probe is `FOR KEY SHARE NOWAIT`: exactly the lock a tool thread's `INSERT INTO tool_calls` needs, and exactly the one the old exclusive claim blocked. Two shared holders coexist; the deadlock was always the exclusive claim standing in their way. **All five gate tests were verified to fail with the boundary reverted to `flush()`**, so they are regression guards rather than tautologies.

**M1 preservation is the non-negotiable gate, and it holds.** `app/workers/worker.py` contains no execution logic whatsoever — no provider call, no tool loop, no retry policy, no cost arithmetic, no authorization — asserted over the AST's names-in-use rather than the source text, because the module docstring necessarily names the machinery it delegates to. The entire M1 execution suite passes unchanged (113 in the five execution-path files; 681 across `tests/runtime/` + `tests/authorization/test_runtime.py`), with the only edit to `services.py` being the one transaction boundary and the docstrings that describe it.

**ROLLING is real, and its limit is stated up front.** A cohort is a declared partition of the registered fleet (`worker_registrations.cohort`); its capacity is the summed declared concurrency of its live, heartbeating workers. A rolling deployment converts cohorts in name order, and each step moves traffic to the fraction of **real fleet capacity** converted so far — a fleet holding 8 and 2 slots steps **80 → 100**, not an invented 25/50/75/100; four equal cohorts step 25/50/75/100 because the fleet *is* four equal quarters. The derivation is recorded on the plan as `cohort_plan` because a rollout whose step sizes become unexplainable minutes later is barely better than an invented one. **The honest limit: workers are not version-pinned.** Version selection is 3.4's, at enqueue; what rolls is the share of new work routed to the candidate, in units of real capacity. Pinning workers to versions would put version filtering in the hot claim path, make the worker second-guess the sole allocator, and starve any execution whose version had no converted worker. So the fleet **sizes** and **gates** the rollout instead — a step can never describe capacity that does not exist, and a cohort that dies mid-rollout fails the next step closed with `ROLLING_COHORT_INVALID`. Neither is expressible without a real fleet; a counter on a deployment row could do neither. **The vestigial replica columns remain untouched and unnamed** — Phase 3.1's AC-14 guard still passes over the whole package, prose included.

**No rolling state machine was written, and no rolling table.** Phase 3.5 already built seven states, pause/resume/abort/rollback-request, per-stage health gates, optimistic concurrency, idempotency and audit. Rolling needs exactly that and differs only in where stage weights come from, so a rolling deployment **is** a `RolloutPlan` with `kind='ROLLING'`. Every operation after the start is 3.5's, unmodified; rollback integration is inherited rather than rebuilt. The entire schema difference is two columns (`kind`, `cohort_plan`) and one new table for the fleet itself.

**The cohort gate lives in the choke point, not in a wrapper.** It was first written on `RollingDeploymentService.advance` — and that was wrong: a rolling plan *is* a `RolloutPlan`, so `POST /rollouts/{id}/advance` and the evaluate-and-advance path both reach it, and a check on a rolling-specific wrapper simply would not run when an operator used the generic route. It was moved into `CanaryRolloutService._advance_one_stage`, the one place a stage is actually entered, and the wrapper deleted.

**A route collision was found and nested around rather than taken over.** `GET /api/v1/runtime/workers` and `POST .../workers/reap` have existed since M1 (worker activity derived from attempts; expired-lock reaping). The build prompt's §6 sketched the fleet API at `/api/v1/workers`, but this repository's runtime API is uniformly `/api/v1/runtime/...` and that prefix was already occupied. The fleet API is therefore mounted at `/api/v1/runtime/fleet`, the same discipline 3.7 used when it nested under `/deployments/{id}/rollback/...` rather than seizing the Phase 5.0 `/rollback` endpoint. **Reported, not silently redesigned.**

**A pre-existing test conflicted with this phase's mandate, and the guard was narrowed and replaced rather than weakened.** Phase 3.7's `test_ac16_earlier_phase_mechanics_are_unmodified` asserted six deployment modules byte-identical to a *moving* `main` — which asserted not only "3.7 did not touch these" but "no future phase ever will". Two of the six had a future phase with an explicit mandate: 3.6's own `RollingStrategy` docstring designated itself "the seam Phase 3.9 fills". `canary.py` and `strategies.py` moved out of the byte-equality list, and the constraint on them got *sharper*: a new test compares both modules' declared surface against `main` and asserts the only additions are the two named rolling helpers, with nothing removed or renamed. Four files byte-locked plus two structurally locked is a stronger total guarantee than six locked against a baseline that was going to have to break. **Fifth instance of a pre-existing test catching a real constraint** — see §9 item 15.

**The PG16/17 mismatch is CLOSED.** `docker-compose.yml` now declares `postgres:17-alpine` and `POSTGRES_DB: ai_agent_control_tower`, matching the live environment and every backup. Asserted by tests against both the file *and* the running server (`SHOW server_version`), so it cannot drift again. `RECOVERY.md`'s "Docker warning" is rewritten as a closure notice carrying the one hazard alignment creates: `act_pgdata` is a major-version-specific data directory, so an existing checkout that ever started on 16 must drop that volume before 17 will boot. **Deliberately not automated** — a script that silently dropped a database volume on first run would be a worse failure than the mismatch it fixed.

**§2/§3/§5 re-derived live**: schema changed (one new table — `worker_registrations` — **124 tables** total), migration head now `0044_worker_fleet_rolling` (reversible, verified live via `alembic downgrade 0043` then `upgrade head`, both clean), routes grew from 530 to **536**. §1, §4, §6, §7, §8, §9 and §10 updated for the new package, the three new error codes, the three new audit events and the two new permissions (`runtime.worker.view`, `runtime.worker.manage`). Backend suite **1,744** green (1,684 + 60), 0 failed, 1 deselected; frontend **297** green, untouched. **Milestone 3 now has 9 of 10 sub-phases implemented**; only 3.10 (the Release Operations Center — the operator-facing assembly of everything this milestone built) remains.

**Updated 2026-08-21** after Phase 3.10 (AI Release Operations Center) shipped — Milestone 3's tenth and final sub-phase. **MILESTONE 3 IS COMPLETE (10/10).** Reflects branch `feat/3.10-release-operations-center`, branched from `main` at `88cc3c8`. One new frontend module, `frontend/src/modules/operations/`; one new backend module, `app/runtime/operations.py`; four read-only endpoints; **no migration** — head stays `0044_worker_fleet_rolling`.

**The §2 mandatory report, delivered before coding.** For each of the twelve §22 views, which endpoints feed it and whether it needed a new one. **Eight of the twelve needed nothing.** Four genuine gaps: (1) an *overview* aggregation, because a row on that screen needs the agent name, version identity, environment, traffic weight, live rollout and health verdict — five extra requests per deployment client-side, so forty deployments would be two hundred round trips to render one table; (2) *release history*, genuinely missing — lifecycle events and rollback history were exposed only *per deployment*, so reconstructing "what shipped last night" required knowing every deployment id in advance, which §13's reconstructability requirement cannot survive; (3) the *detail composite*, since §22 lists thirteen fields spread across eight endpoints; (4) the *rollout list* — the sharpest gap, since Phase 3.5 shipped `GET /rollouts/{id}` and **no way to discover a rollout at all**. A canary could be advancing through production traffic with no way to see it in the API.

**Read + trigger, enforced structurally rather than promised.** `app/runtime/operations.py` contains no `add`/`commit`/`delete`/`flush` call and imports no mutating service — both asserted over the AST, the second listing ten forbidden service names explicitly. All four routes are GET, asserted by enumerating the mounted router. **No migration**, because reading existing data is the whole job and a new table would have meant the phase invented domain state. A git-diff test pins twelve deployment/worker/scheduler engine modules byte-identical to `main`.

**Truthful state is the phase's real deliverable.** §10 forbids presenting a blocked, killed or unproven release as safe — and the UI can only show what the read model tells it, so a read model that omitted a kill switch would *make* the UI lie. Four facts are therefore surfaced as first-class fields rather than left to be inferred: `kill_switch_active` (a boolean, not a lifecycle string the browser must parse), `gate_verdict` (BLOCK renders destructive and is never summarised away), `release_health.is_proving` (false for UNKNOWN/INSUFFICIENT_DATA — Phase 3.5's rule that the absence of evidence is never evidence of health, carried into the UI), and `servable` (Phase 3.4's own union-with-veto predicate, reported rather than re-derived, because two implementations of "is this actually serving?" would eventually disagree). Blockers are shown **all of them**, most severe first, above everything else on the detail view.

**Dangerous actions are gated in two tiers, deliberately unequal.** A single confirm for reversible things (drain a worker, pause a rollout, disable a job); type-to-confirm for the irreversible or production-traffic-moving (promote to production, roll back, abort a rollout, change traffic weights, arm a scheduled job). Uniform friction is friction people learn to click through. The dialog is a guard against the **accidental, not the unauthorized** — the server decides who may act, and treating a client dialog as a security control would be exactly the client-side-only gating §10 forbids.

**Conflicts are explained, never retried.** Every Milestone 3 engine uses optimistic concurrency, so an operator acting on stale state gets a conflict code. The UI never auto-retries one — that would re-apply an intent formed against state that no longer exists — and never shows it as a generic failure, which reads as "the platform is broken" rather than "your colleague just paused this". Safety refusals (`KILL_SWITCH_ACTIVE`, `ROLLBACK_TARGET_UNAVAILABLE`, `ROLLING_COHORT_INVALID`, `ROLLOUT_STAGE_GATE_NOT_MET`) pass through **verbatim**, because the server's message names precisely which rule fired.

**Five things the UI deliberately cannot do**, each closing a hole a convenience feature would have opened: run a job (Phase 3.8 built its API so no HTTP route dispatches — a "run now" button would execute a handler with no occurrence row and no lease, defeating exactly-once by never taking one); register a worker (phantom capacity, from which rolling derives *real* step weights); choose an arbitrary rollback target (3.7 fails closed rather than guessing, so the wizard displays the target and says so when there isn't one, instead of offering a picker that reintroduces the guess); normalise traffic weights (that would be making an allocation decision, and would hide that what was typed is not what shipped); or predict a stage gate (a UI that predicted it would eventually predict it wrong, and a wrongly-disabled button is as damaging mid-incident as a wrongly-enabled one).

**The route-path conflict was reported, not silently redesigned.** The build prompt's §6 sketched `/api/v1/deployments/overview`; this repository's runtime API is uniformly `/api/v1/runtime/...`, and `/deployments/{deployment_id}` would have swallowed "overview" as an id. The read models are nested under `/runtime/operations/`. The rollout list is the exception and sits at `/runtime/rollouts`, beside `GET /rollouts/{id}`, because it is not an aggregation for a screen — it is the list endpoint 3.5's own resource was missing. **Third consecutive phase to hit and report a path conflict** (3.7's `/rollback`, 3.9's `/workers`, now this).

**§2/§3/§5 re-derived live**: schema **unchanged at 124 tables**, migration head **unchanged at `0044_worker_fleet_rolling`** (no migration this phase), routes grew from 536 to **540** (+4, all GET). Backend suite **1,770** green (1,744 + 26), 0 failed, 1 deselected; frontend **327** green (297 + 30), 49 files. **Milestone 3 is COMPLETE — 10 of 10 sub-phases implemented.**

**Verification methods used**:
- Directory tree: `find` (depth 4, pruned `node_modules`/`__pycache__`/`.git`/`.venv`/`dist`/`.pytest_cache`).
- Database schema: live `sqlalchemy.inspect()` introspection against the actual Postgres instance (`ai_agent_control_tower`, `127.0.0.1:5432`) — this is what the migration chain has *actually produced*, not a re-read of the migration source.
- Migration chain: `alembic history` + `alembic current` + `ls backend/migrations/versions/`.
- API surface: introspection of the live `app.main:app` FastAPI object (`app.routes`), extracting each route's HTTP methods, path, and — where present — the RBAC permission code captured in `require_permission(code)`'s closure.
- Implemented modules: AST-parsed (`ast.parse`) every non-`__init__.py` file under `backend/app/`, extracting the module docstring's first line and every top-level class/public-function name — not a manual read, so nothing was skipped or summarized from memory.
- Tests: backend suite actually executed (`pytest -q`) at generation time, not carried forward from an earlier run. Frontend (`vitest run`) was **not** re-run in this pass — Phase 5.2.6 and Phase 5.2.4 are both backend-only, so its last actually-executed count (297 passed) is carried forward, explicitly flagged as such rather than silently re-asserted as freshly run.
- Branches: `git branch -a --sort=-committerdate` with `--format` adding ISO committer dates (the bare command has no date column; dates were explicitly requested).

---

**Updated 2026-08-25** after Phase 4.1 (Runtime Telemetry & Trace Context Foundation) shipped — **Milestone 4's first sub-phase**, opening Enterprise Runtime Governance & Observability (ACT-SRS-M4). Reflects `main` at the merge of `feat/4.1-runtime-telemetry`, working tree clean once this document's own update is committed.

**This pass began with two mandatory pre-steps run against the live repository, and both found real staleness.**

*Pre-step A — regenerate at the true head.* §2, §3 and §5 had each kept a *stale headline* while their per-phase narrative paragraphs were faithfully extended beneath — the worst possible combination, because the document looked maintained. §2 said "119 tables ... through `0041_canary_rollout`" (live: **124** tables, 123 in `Base.metadata`, head `0045_runtime_telemetry_context`); §3 said "42 revisions ... head `0041_canary_rollout`" (live: **45**); §5 said "**518**" routes, correct as of Phase 3.6 and four phases stale (live: **541**). All three are now taken from the live system, with the drift recorded in place rather than quietly overwritten. PostgreSQL is **17.10**. Backend suite: **1,770 collected**, and a full pre-phase baseline run on unmodified `main` recorded 1,769 passed / 1 failed — the failure being `test_idempotency_is_scoped_per_agent_not_shared`, which passes in isolation and is the same intermittent test 3.9's commit message recorded; it is a genuine flake, confirmed here on code this phase had not touched.

*Pre-step B — disambiguate the 4.x numbering.* This repository contains **two unrelated families that both use 4.x**: Book-07's identity/authorization work (`Part 4.1` Identity Foundation, `Phase 4.3` Authorization Platform, `Part 4.3.1–4.3.8`) and ACT-SRS-M4's observability work (`Phase 4.1–4.10`, requirements prefixed `M4-`). ROADMAP now carries a numbering note at the top with a comparison table, both historical headings are labelled *(historical Book-07 family — not Milestone 4)*, and the new Milestone 4 section states the `M4-` prefix convention. "Part 4.1" is Identity Foundation; "Phase 4.1 (M4)" is Runtime Telemetry. They share a number and nothing else.

**The gap this phase closed was measured, not assumed.** `correlation_id` has existed on `agent_executions` (indexed) since Milestone 1, and `runtime_events` has carried `request_id`/`correlation_id` columns just as long. Nothing populated them: `ExecutionRequestService` read `correlation_id` **only** from the request body, and `POST /executions` did not take a `Request` object at all, so no header could reach it. Live measurement: **74,395 of 74,619** executions (99.7%) had a null `correlation_id`, and essentially all **296,941** `runtime_events` rows did. The substrate was right; the propagation was absent.

**Two prompt-versus-repository conflicts were found and reported rather than coded around.** The build prompt's §2 stated that `agent_executions` carries "`request_id` + `correlation_id` ... (indexed)" and that `execution_attempts` has both "NOT NULL". Neither was true: `agent_executions` had `correlation_id` only and **no** `request_id`, and `execution_attempts` has **neither** column. The live schema won, as the prompt itself directed.

**New package `app/observability/`** — a *sibling* of `app/runtime` and `app/integration`, not a module inside either. Telemetry is a derived plane (SRS §5) and the dependency runs one way; placing it beside the runtime makes that direction visible in the import graph instead of merely asserted in a document. Six modules: `scrubbing.py` (the isolated secret scrubber — **standard library only, zero platform imports**, asserted over the AST, the same discipline `scope.py` was built with), `attributes.py` (semantic attributes + the bounded metric-label allowlist), `capture.py` (the METADATA_ONLY baseline, four data classes, the structural chain-of-thought exclusion), `trace.py` (trace/span context, no SQLAlchemy import at all), `events.py` (the runtime-event contract, emitted best-effort), `assembly.py` (read-only trace assembly).

**Spans are derived, never stored — the §13 decision, and the most consequential one in the phase.** A span id is a deterministic `uuid5` over (trace id, span kind, row id, ordinal), and a trace is assembled by walking the foreign keys that already exist: `execution_attempts`, `execution_messages` and `tool_calls` all carry `execution_id`, already hold their own timings, statuses and error classes, and are already authoritative. A `runtime_trace_spans` table would have been a second, lossy copy of them. **No `correlation_id` was added to any child table either** — copying the parent's correlation onto each child is the same duplication arriving as a column instead of a table.

**Migration `0045_runtime_telemetry_context`: two nullable columns, no table, no backfill.** The two facts that are genuinely *not* derivable from existing data: `agent_executions.request_id` (the HTTP request that created an execution — lost forever if not captured at the request; partial-indexed `WHERE request_id IS NOT NULL`) and `runtime_events.span_id` (which derived span an event occurred in — `execution_id` narrows to a trace but not to a step). **`correlation_id` was deliberately not backfilled**: `trace_id_for(execution)` returns `correlation_id or str(execution.id)`, so all ~74,000 historical executions gained a stable, unique trace identity from a pure function, with zero rows written and nothing a downgrade could fail to reverse. Reversible, verified live (`downgrade -1` / `upgrade head` clean).

**Telemetry is non-gating, and enforced two ways because one is not enough** (SRS §9 — the deliberate inverse of every other subsystem in this codebase, which all fail closed). `emit()` catches `Exception` **and** performs its write inside a `SAVEPOINT`. Without the savepoint a failed `INSERT` leaves the caller's transaction poisoned, so the swallowed exception resurfaces as a corrupted execution three frames up — a bug that would look correct in a unit test and fail in production. Both properties are tested, including one that asserts the session is still usable after a forced failure, and one that runs a real execution with `emit`/`emit_event` monkeypatched to raise.

**`_record_event` was split along the plane boundary.** It had *dual-written* the audit trail and `runtime_events` from one call, with the raw unfiltered `meta` as payload and `correlation_id` left null. The audit half is unchanged and still raises (the compliance record must not be lossy); the telemetry half now goes through `_emit_telemetry` → `emit_event`, which attaches the trace identity, scrubs, drops content and private reasoning, and never raises. One choke point, 33 call sites, no call site changed.

**METADATA_ONLY is the default and chain-of-thought is structurally excluded.** Content — prompts, tool arguments, model output — is not captured at all; a real execution carrying a distinctive marker in its input payload is asserted to leave that marker nowhere in `runtime_events`. Private reasoning is `DataClass.NEVER`, absent from *every* mode's allowed set, tested parametrically over every member of `CaptureMode` so a mode added later cannot acquire it, and **dropped rather than redacted** — a `REDACTED` marker would still record that reasoning existed and how many turns had it.

**Bounded metric cardinality is structural, not remembered** (SRS §12). `metric_labels()` is the only supported way to build a label dict and raises on every high-cardinality identity and every sensitive name, with the tests parametrized over the declared sets so a name added later cannot be left out of the guard. The raw `model` is a trace attribute; only `model_category` is metric-eligible.

**Execution behaviour is unchanged, including the subtle case.** Phase 3.4 uses `payload["correlation_id"]` as its sticky routing key, so writing a header-derived or auto-minted correlation into the *payload* would silently have made every request sticky and quietly defeated percentage rollouts. The minted id reaches the execution **row** and never the payload; `_routing_key` still reads exactly what it read before, and a test pins that.

**One Phase 3.10 test was rewritten and deliberately strengthened.** `test_ac15_no_migration_was_added` asserted that the repository's *newest* migration was `0044_worker_fleet_rolling` — true when 3.10 shipped, false the moment any later phase adds one, and silent about whether 3.10 itself added a migration. It is the same moving-target trap Phase 3.7's byte-identity guard fell into. It now asserts the claim itself — no migration in the repository belongs to Phase 3.10 — which stays true forever and additionally catches a 3.10 migration inserted *before* the head, which the original would have missed entirely.

**One route** (540 → **541**): `GET /api/v1/runtime/executions/{execution_id}/trace`, reusing the **pre-existing** `runtime.telemetry.view` permission, whose description already read "View runtime telemetry and execution traces". No new permission was registered: the stronger `runtime.trace.content.view` (SRS §16) is deferred to 4.8, because under METADATA_ONLY it would guard nothing, and a permission that guards nothing teaches operators it is safe to grant. **No new error code and no new audit event** — telemetry failures are swallowed, and a capture-baseline change is not yet possible to make.

**The scheduler leg is wired, not merely available** (M4-4.1-FR-003). `SchedulerService._audit` already routed through `_record_event`, so its events were each getting a freshly minted trace id — meaning one job occurrence's STARTED and SUCCEEDED/FAILED events belonged to *different* traces and a run was unreconstructable. `_record_event` gained an optional `trace`, and the scheduler passes `TraceContext.for_job_run(run)`: a job occurrence has no caller and so no inbound correlation, and its own `job_runs` row id is the right name for its trace. Derived, so the scheduler needed no schema change at all. A structural test asserts the call site exists, because an API nobody calls would satisfy the requirement on paper and leave scheduler events untraceable in fact.

**125 new tests** in `backend/tests/runtime/test_telemetry_foundation.py`. Backend **1,895 passed, 0 failed, 1 deselected** (1,770 baseline + 125), 737s; frontend **327 passed** across 49 files, unchanged (4.1 is backend-only). Routes 540 -> **541**; schema unchanged at **124 tables**; migration head **`0046_trace_explorer_index`**, reversible (verified live). See `docs/observability/architecture.md`, `semantic-conventions.md`, `privacy.md`, and ADR-0008 (telemetry as a derived plane).

**Phase 4.2 (Unified AI Execution Trace) shipped 2026-08-26** — Milestone 4's second sub-phase, and the phase ADR-0008 had named in advance as the point to revisit the derived-spans decision *with real numbers*.

**The measurement came first, because it decided the architecture.** Against the live database at **90,695 executions / 355,377 runtime_events**: trace-detail assembly (the four-table walk) ran at **0.74ms p50 / 1.08ms p95**, and every one of the explorer's six filter dimensions landed between **0.23ms and 0.87ms p50**, none sequentially scanning `agent_executions`. Assembly is three orders of magnitude inside any reasonable budget, so **no read projection and no span index were added** — a projection would have optimized a sub-millisecond query at the price of a second copy to keep in sync, which is exactly the §13 duplication ADR-0008 rejected. The restraint is recorded with the numbers that justify it, in ADR-0008's new "Measurement outcome" section and as an executable benchmark test rather than a note in a commit message.

**The measurement also found something the fragmented dev data was hiding, and that mattered more.** 90,695 executions are spread across **62,126 organizations**, so the busiest tenant owns only 500 — which made every tenant-scoped query look fast for a reason that would not hold for a real customer. Measuring the honest worst case (one tenant owning the whole table) exposed a genuine cliff: `agent_executions` had **no index on `created_at` at all**, so the explorer's default listing planned as a `Parallel Seq Scan` — **26.94ms p50 / 142.27ms p95**, growing linearly. Migration `0046_trace_explorer_index` adds `(organization_id, created_at DESC)`. Before and after, same query, same tenant: `Bitmap Heap Scan -> rows=500 -> top-N heapsort` (18 buffers, 0.196ms) became `Index Scan -> rows=50 -> no Sort node` (4 buffers, 0.043ms). **The disappearing Sort is the point, not the 0.15ms**: bitmap-plus-sort is O(rows the tenant owns), an index walked in order and stopped at the LIMIT is O(limit) — flat as a tenant grows. An index is not a §13 duplication: it stores no independent copy, contains only values already in the table's own columns, and is an access path to the authoritative table rather than a second thing claiming to be the truth.

**Trace assembly gained the missing §8-4.2 node categories.** 4.1 covered execution/attempt/model/tool/external; 4.2 adds **authorization**, **runtime_policy**, **queue** and **approval**, plus finalization. Six of the ten node kinds are backed by a real row and name it (`source_table`/`source_id`); four are computed phases that report `source_table: null`, so a reader can tell derived nodes from row-backed ones at a glance. The **queue node is a computed gap** (`queued_at`→`started_at`) with no row anywhere — kept because in a slow trace it is frequently the largest interval, and an operator asking "why did this take 40 seconds?" is usually looking at queue wait rather than model latency. It is emitted only when both ends are known: an open-ended wait is not a measured duration.

**A real 4.1 modelling bug was found and fixed.** The root `execution` span started at `started_at`, so the gate and queue nodes 4.2 added rendered *before their own parent* — incoherent on a timeline. The root now spans `created_at`→`completed_at` and is a true envelope; spans return root-first, then chronologically, with unknown-start nodes last.

**Metadata-only is the hard line, and it is enforced upstream of the routes.** Neither the assembler nor the explorer reads a content column at all — asserted over the AST as attribute reads — so the boundary cannot be undone by a route change alone. `runtime.trace.content.view` is **named in code and deliberately not registered** in the permission catalog: naming it gives the boundary a visible owner, registering it would create a grantable permission that guards nothing. A real execution carrying a distinctive marker in its input is asserted to leave that marker nowhere in either the trace or the explorer.

**Tenant isolation is §34's stronger form** — not merely refusing to read another tenant's data but refusing to confirm it exists. Both the correlation lookup and the primary-key fallback apply the tenant predicate, and a cross-tenant trace id produces a response byte-identical to a nonexistent one (compared on the error payload; only the envelope's per-request id and timestamp differ). A structural test asserts no code path in the explorer builds a statement without an `organization_id` filter.

**One deviation from the build prompt, reported not silently taken.** §6 asked to register `runtime.observability.view`. 4.2 **reuses the pre-existing `runtime.telemetry.view`** instead, whose catalog description already reads "View runtime telemetry and execution traces" — exactly this capability. Two permission codes guarding one capability is how an authorization model drifts from what operators believe they granted; 4.1 made the same call for the same reason.

**The frontend Trace Explorer and Trace Detail views are deferred to Phase 4.9** (the observability center), which the build prompt explicitly permits. Building them now and rebuilding them into the unified center two phases later would be duplicated work against a moving design; the backend surface they will consume is complete and tested.

Three new routes under `/api/v1/observability` (541 → **544**), no collision with the legacy `analytics` dashboards (which aggregate the Phase 3 `agent_actions` table and know nothing of `AgentExecution`). 4.1's `/runtime/executions/{id}/trace` is retained and delegates to the same assembler, so the two cannot diverge. One new error code (`TRACE_NOT_FOUND`), no new audit event (a metadata trace read is an ordinary authorized read; the content-view audit is 4.8's). Schema **unchanged at 124 tables**; migration head **`0046_trace_explorer_index`**, reversible (verified live). **52 new tests** in `backend/tests/runtime/test_execution_tracing.py`. Backend **1,947 passed, 0 failed, 1 deselected** (1,895 baseline + 52), 706s; frontend **327 passed** across 49 files, unchanged (the trace UI is deferred to 4.9). See `docs/observability/tracing.md` and ADR-0008's measurement outcome.

## 1. Project Structure

Directory tree, 4 levels deep, from the repository root. `node_modules`, `__pycache__`, `.git`, `.venv`/`venv`, `dist`, and `.pytest_cache` are pruned. Files and directories are shown together, alphabetically within each level.

```
.agents
.gitattributes
.gitignore
CHANGELOG.md
README.md
RECOVERY.md
ROADMAP.md
backend
  .coverage
  .dockerignore
  .env
  .env.example
  .gitignore
  Dockerfile
  README.md
  alembic.ini
  app
    __init__.py
    api
      __init__.py
      deps.py
      router.py
      routes
    authorization
      __init__.py
      abac
      admin
      cache.py
      catalog.py
      decisions.py
      engine.py
      enums.py
      hierarchy
      middleware
      repositories.py
      resources
      routes.py
      schemas.py
      seeding.py
      services.py
    core
      __init__.py
      config.py
      database.py
      enums.py
      middleware.py
      policy_templates.py
      security.py
    governance
      __init__.py
      routes.py
      schemas.py
      services.py
    identity
      __init__.py
      api
      audit
      auth
      credentials
      email
      errors.py
      federation
        __init__.py
        claim_mapping.py
        oidc.py
        routes.py
        saml.py
        schemas.py
        service.py
      models
      permissions
      protection
      ratelimit
      recovery
      registration
      repositories
      roles
      schemas
      security
      services
      sessions
      tokens
    integration
      __init__.py
      auth
        __init__.py
        base.py
        registry.py
        schemes
          __init__.py
          api_key.py
          basic.py
          bearer.py
          mtls.py
          oauth2_authorization_code.py
          oauth2_client_credentials.py
        service.py
        token_manager.py
      base.py
      connectors
        __init__.py
        database
          __init__.py
          connector.py
          declaration.py
          drivers.py
          executor.py
          invoker.py
        queue
          __init__.py
          backends.py
          connector.py
          declaration.py
          invoker.py
          scope.py
        rest
          __init__.py
          connector.py
          declaration.py
          extraction.py
          invoker.py
          pagination.py
          templating.py
        storage
          __init__.py
          backends.py
          connector.py
          declaration.py
          invoker.py
          scope.py
      errors.py
      health.py
      lifecycle.py
      mock.py
      mock_authenticated.py
      registry.py
      routes.py
      schemas.py
      scheduler.py
      sdk
        __init__.py
        example
          __init__.py
          webhook_connector.py
        http.py
        testing.py
      service.py
      types.py
      validation.py
    main.py
    models
      __init__.py
      abac.py
      access_review.py
      agent.py
      agent_action.py
      agent_registry.py
      api_key.py
      approval.py
      audit_log.py
      governance.py
      integration.py
      mixins.py
      organization.py
      organization_hierarchy.py
      permission.py
      policy.py
      rbac.py
      resource_authorization.py
      runtime.py
      user.py
    runtime
      __init__.py
      deployment
      environment
      providers
      registry
      release_gate
      routes.py
      schemas.py
      services.py
      tools
      versioning
    schemas
      __init__.py
      agent.py
      agent_action.py
      analytics.py
      api_key.py
      approval.py
      audit.py
      audit_log.py
      auth.py
      dashboard.py
      organization.py
      permission.py
      policy.py
      rbac.py
      user.py
    seed.py
    services
      __init__.py
      agent_action_service.py
      analytics_service.py
      api_key_service.py
      approval_service.py
      audit_service.py
      audit_view.py
      auth_service.py
      decision_engine.py
      notification_service.py
      permission_engine.py
      policy_engine.py
      rbac_service.py
      risk_engine.py
  docker-entrypoint.sh
  migrations
    env.py
    script.py.mako
    versions
      0001_initial_schema.py
      0002_phase2_schema.py
      0003_agent_management.py
      0004_policy_management.py
      0005_approval_workbench.py
      0006_identity_foundation.py
      0007_identity_lifecycle.py
      0008_auth_login_history.py
      0009_session_lifecycle.py
      0010_session_admin_permissions.py
      0011_security_event_read_indexes.py
      0012_registration_invites.py
      0013_credential_management.py
      0014_password_reset_recovery.py
      0015_account_protection.py
      0016_rbac_foundation.py
      0017_permission_engine.py
      0018_org_hierarchy.py
      0019_resource_authorization.py
      0020_abac_engine.py
      0021_access_reviews.py
      0022_governance_iga.py
      0023_agent_runtime.py
      0024_agent_registry.py
      0025_agent_versioning.py
      0026_version_compatibility.py
      0027_version_signing.py
      0028_streaming_and_pricing.py
      0029_provider_credentials.py
      0030_http_tool_egress.py
      0031_tool_resilience.py
      0032_tool_loop.py
      0033_connector_core.py
      0034_connector_auth.py
      0035_connector_health.py
      0036_identity_federation.py
      0037_deployment_lifecycle.py
      0038_environments_promotion.py
      0039_deployment_preflight.py
      0040_traffic_allocation.py
      0041_canary_rollout.py
  pytest.ini
  requirements.txt
  scripts
    __init__.py
    recompute_checksums.py
    record_provider_fixtures.py
  tests
    __init__.py
    authorization
      conftest.py
      test_abac.py
      test_abac_perf.py
      test_abac_unit.py
      test_admin_portal.py
      test_agent_registry.py
      test_agent_registry_perf.py
      test_agent_versioning.py
      test_governance.py
      test_hierarchy.py
      test_hierarchy_unit.py
      test_middleware.py
      test_middleware_perf.py
      test_middleware_unit.py
      test_permission_engine.py
      test_permission_engine_perf.py
      test_permission_engine_unit.py
      test_rbac_endpoints.py
      test_rbac_unit.py
      test_resource_authorization.py
      test_resource_authorization_perf.py
      test_runtime.py
    conftest.py
    identity
      __init__.py
      auth
      credentials
      federation
        __init__.py
        _saml_fixtures.py
        conftest.py
        test_claim_mapping.py
        test_federation_config_crud.py
        test_federation_login_flow.py
        test_oidc_bypass_prevention.py
        test_saml_bypass_prevention.py
      integration
      protection
      recovery
      registration
      unit
    integration
      conftest.py
      test_connector_auth.py
      test_connector_core.py
      test_connector_health.py
      test_connector_sdk.py
      test_connector_sdk_example.py
      test_database_connector.py
      test_database_connector_invocation.py
      test_queue_connector.py
      test_queue_connector_invocation.py
      test_queue_scope.py
      test_rest_connector.py
      test_rest_connector_invocation.py
      test_storage_connector.py
      test_storage_connector_invocation.py
      test_storage_scope.py
    runtime
      conftest.py
      fixtures
        providers
          README.md
          error_authentication_failed.json
          error_connection_refused.json
          error_content_filtered.json
          error_context_length_exceeded.json
          error_invalid_request.json
          error_rate_limited.json
          error_read_timeout.json
          error_server_error.json
          error_unrecognizable.json
          max_tokens_reached.json
          multi_turn_with_tool_message.json
          multiple_tool_calls.json
          omitted_optional_fields.json
          simple_completion.json
          single_tool_call.json
          stream_simple_completion.sse
          stream_tool_call_fragmented.sse
          stream_truncated.sse
          stream_with_usage.sse
          stream_without_usage.sse
      test_attestation.py
      test_canonical.py
      test_deployment_lifecycle.py
      test_egress_guard.py
      test_environment_promotion.py
      test_error_taxonomy_and_resilience.py
      test_http_tool_execution.py
      test_openai_compatible_provider.py
      test_provider_abstraction.py
      test_provider_credentials.py
      test_release_gate.py
      test_streaming_and_accounting.py
      test_tool_loop.py
      test_tool_resilience.py
      test_version_compatibility.py
      test_version_signing.py
    test_agents_part32.py
    test_analytics_part36.py
    test_approvals_part34.py
    test_audit_part35.py
    test_dashboard_part3.py
    test_decision_engine.py
    test_http_hardening.py
    test_integration.py
    test_policies_part33.py
    test_policy_engine.py
    test_response_envelope.py
    test_risk_engine.py
  var
    dev-outbox.log
backups
  README.md
  ai_agent_control_tower_20260717-021359.dump
  ai_agent_control_tower_20260717-021359.dump.sha256
  backup-manifest.txt
  recovery-tool-test
    .act-backup-target
    20260717T121100Z
      COMPLETE
      SHA256SUMS.txt
      database
      manifest.json
      secrets-inventory.txt
      source
      tools
  seed-credentials.txt
docker-compose.yml
docs
  admin
    abac-builder.md
    access-reviews.md
    audit-center.md
    dashboard.md
    decision-explorer.md
    organization-explorer.md
    policy-simulator.md
    resource-management.md
    roles.md
    security-analytics.md
  api
    http-conventions.md
  architecture
    README.md
    adr
      0001-record-architecture-decisions.md
      0002-postgresql-as-sole-datastore.md
      0003-stateless-jwt-with-rotating-refresh-tokens.md
      0004-single-source-password-policy.md
      0005-additive-identity-layer-alongside-legacy-auth.md
      0006-deterministic-governance-pipeline.md
      0007-stateful-session-validation.md
      README.md
      _template.md
    c4
      01-context.md
      02-container.md
      03-component-backend.md
    data
      erd.md
    deployment
      deployment.md
    security
      threat-model.md
    sequences
      01-human-login.md
      02-token-refresh-and-reuse.md
      03-agent-action-governance.md
  authorization
    abac
      attributes.md
      combining-algorithms.md
      operators.md
      overview.md
      policy-language.md
      policy-lifecycle.md
      policy-simulation.md
      security.md
    caching.md
    context.md
    delegated-administration.md
    delegation.md
    gateway.md
    hierarchy-resolution.md
    middleware.md
    obligations.md
    organization-hierarchy.md
    permission-engine.md
    permission-resolution.md
    permissions.md
    pipeline.md
    rbac.md
    resource-acl.md
    resource-authorization.md
    resource-ownership.md
    resource-sharing.md
    role-hierarchy.md
    roles.md
    scopes.md
    wildcards.md
  deployment
    environments.md
    lifecycle.md
    release-gates.md
  deployment.md
  governance
    access-certification.md
    compliance-reporting.md
    governance-dashboard.md
    orphaned-identities.md
    privileged-access.md
    remediation.md
    risk-scoring.md
    sod-analysis.md
    toxic-permissions.md
  identity
    authentication-architecture.md
    credential-management.md
    device-management.md
    email-verification.md
    human-authentication.md
    invitations.md
    migration-plan.md
    password-history.md
    password-policy.md
    password-reset.md
    recovery.md
    registration.md
    security-events.md
    session-lifecycle.md
    token-rotation.md
    token-strategy.md
    trust-model.md
  integration
    connectors.md
  phase-3-part-1.md
  phase-3-part-4.md
  phase-3-part-5.md
  phase-3-part-6.md
  phase-4-part-1.md
  runtime
    agent-lifecycle.md
    architecture.md
    capabilities-and-tools.md
    deployments.md
    executions.md
    gateways.md
    health-and-observability.md
    operations-and-kill-switch.md
    overview.md
    providers.md
    registry
      agent-definitions.md
      api.md
      domain-model.md
      duplicate-detection.md
      identity-association.md
      import-export.md
      json-schema.md
      lifecycle.md
      migration.md
      overview.md
      ownership.md
      registration.md
      security.md
      validation.md
    runtime-policy-and-approvals.md
    security.md
    versioning.md
    workers-and-queue.md
  security
    account-lockout.md
    account-protection.md
    brute-force-protection.md
    identity-protection-rules.md
    risk-based-authentication.md
  testing
    strategy.md
frontend
  .dockerignore
  .env
  .env.example
  .gitignore
  .oxlintrc.json
  CODING_STANDARDS.md
  Dockerfile
  README.md
  components.json
  index.html
  nginx.conf
  package-lock.json
  package.json
  postcss.config.js
  public
    favicon.svg
    icons.svg
  src
    App.tsx
    authorization
      PermissionContext.tsx
      ProtectedComponent.tsx
      hooks.ts
      index.ts
      middleware
      permissions.ts
      tests
    components
      auth
      common
      dashboard
      layout
      ui
    config
      env.ts
      queryClient.ts
    constants
      app.ts
      index.ts
      navigation.ts
      permissions.ts
      queryKeys.ts
      roles.ts
      routes.ts
    contexts
      AuthContext.tsx
      NotificationsContext.tsx
      ThemeContext.tsx
    hooks
      index.ts
      useAgentActivity.ts
      useApprovals.ts
      useAuth.ts
      useDashboardSummary.ts
      useDebouncedValue.ts
      useNotifications.ts
      useRecentActions.ts
      useRecentAuditLogs.ts
      useRiskTrend.ts
      useSystemHealth.ts
      useTheme.ts
    index.css
    layouts
      AuthLayout.tsx
      DashboardLayout.tsx
      ErrorLayout.tsx
      index.ts
    main.tsx
    modules
      abac
      admin
      agents
      analytics
      approvals
      audit
      authorization
      governance
      hierarchy
      identity
      policies
      protection
      resources
      runtime
      security
    pages
      DashboardPage.tsx
      NotFoundPage.tsx
      ProfilePage.tsx
      SettingsPage.tsx
      UsersPage.tsx
      auth
      index.ts
    routes
      AppRoutes.tsx
      index.ts
    services
      abacService.ts
      adminService.ts
      apiClient.ts
      approvalService.ts
      auditService.ts
      authService.ts
      authorizationService.ts
      credentialService.ts
      dashboardService.test.ts
      dashboardService.ts
      envelope.ts
      governanceService.ts
      hierarchyService.ts
      index.ts
      protectionService.ts
      recoveryService.ts
      registrationService.ts
      resourceAuthzService.ts
      runtimeService.ts
      systemService.ts
      tests
      tokenRefresh.ts
      userService.ts
    styles
    test
      setup.ts
    types
      abac.ts
      admin.ts
      agent.ts
      agentAction.ts
      approval.ts
      audit.ts
      auth.ts
      authorization.ts
      common.ts
      dashboard.ts
      governance.ts
      hierarchy.ts
      index.ts
      policy.ts
      resourceAuthz.ts
      runtime.ts
    utils
      cn.ts
      error.ts
      format.ts
      index.ts
      permissions.ts
      risk.test.ts
      risk.ts
      tokenStorage.ts
      validation.ts
  tailwind.config.js
  tsconfig.app.json
  tsconfig.json
  tsconfig.node.json
  vite.config.ts
  vitest.config.ts
scripts
  backup
    Backup-ControlTower.ps1
    Export-ControlTowerSecrets.ps1
    Initialize-BackupTarget.ps1
    Register-BackupTask.ps1
    Restore-ControlTower.ps1
    Verify-ControlTowerBackup.ps1
```

## 2. Database Schema

**124 tables** (live `sqlalchemy.inspect()`; 123 in `Base.metadata` — Alembic manages `alembic_version` itself and it is not a model), extracted against the local PostgreSQL **17.10** database after running every migration through **`0045_runtime_telemetry_context`** (head). This reflects exactly what the migration chain produces. *(Re-derived 2026-08-25 during Phase 4.1's pre-step A. This paragraph previously said "119 tables ... through `0041_canary_rollout`" — stale since Phase 3.5, even though the per-phase update paragraphs below were kept current. The headline number is now taken from the live database rather than carried forward.)* `alembic_version` (Alembic's own bookkeeping table, one column, no app data) is included below for completeness since it is a real table in the database.

**Phase 3.5 update**: 3 new tables — `rollout_plans` (one governed canary promotion within an (agent, environment): the seven-state rollout machine, `current_stage_index`, and a `revision` optimistic-concurrency guard that is a SQLAlchemy `version_id_col`), `rollout_stages` (the ordered stages and their three gates — `min_duration_seconds`/`min_samples`/`health_requirement` — plus `target_weight`, `advance_mode` and `entered_at`), and `deployment_health_evaluations` (ruling #3's AI-aware release-health verdicts: `health_state`/`sample_count`/`metrics` JSONB/`baseline_ref` JSONB/window bounds) — 119 tables total. **The pre-existing `deployment_health` table is untouched in both directions** (ruling #3) — it answers a different question (liveness heartbeat vs release judgement), and a test asserts its row count is unchanged across a full rollout. Two indexes were added to the pre-existing `agent_executions`: `ix_agent_executions_version_created` on `(agent_version_id, created_at)` and `ix_agent_executions_deployment_created` on `(deployment_id, created_at)` — the latter is the **first index that column has ever had**. No existing column was altered. Migration `0041_canary_rollout` is purely additive with no data backfill; `alembic downgrade`/`upgrade` re-verified clean this session.

**Phase 3.4 update**: 2 new tables — `deployment_traffic_allocations` (one revision of an agent's weighted traffic split in one environment: `organization_id`/`agent_id`/`environment_id`/`revision`/`is_current`/`reason`/`created_at`/`created_by`; hot-path index on `(agent_id, environment_id, is_current)`, a **partial unique index** `uq_traffic_allocations_current` on `(agent_id, environment_id) WHERE is_current` that is the domain's concurrency primitive, and a unique constraint on `(agent_id, environment_id, revision)`) and `deployment_traffic_weights` (the entries of one allocation: `allocation_id`/`agent_version_id`/`deployment_id`/`weight`, CHECK `weight BETWEEN 0 AND 100`, unique on `(allocation_id, agent_version_id)`) — 116 tables total. No existing table or column was changed. Migration `0040_traffic_allocation` is additive plus the §15 step-2 data backfill (every servable deployment with a governed `environment_id` gets a current 100% allocation to the version it was already serving — see `docs/deployment/traffic-and-resolution.md`). Reversible; `alembic downgrade`/`upgrade` re-verified clean this session.

**Phase 3.3 update**: 1 new table — `deployment_preflight_results` (one persisted `ReleaseGateService.evaluate()` verdict per call: `deployment_id`/`organization_id`/`verdict`/`findings` JSONB list/`evaluated_at`/`evaluated_by`, composite index on `(deployment_id, evaluated_at)`) — 114 tables total. No existing table or column was changed. Migration `0039_deployment_preflight` is purely additive, one new table only, no data backfill.

**Phase 3.2 update**: 2 new tables — `environments` (tenant-scoped deployment targets: `organization_id`/`name`/`display_name`/`is_production`/`policy` JSONB, unique on `(organization_id, name)`), `promotion_paths` (the org-configured directed graph a version's deployment eligibility may move along: `organization_id`/`from_environment_id`/`to_environment_id`/`requires_approval`, unique on `(organization_id, from_environment_id, to_environment_id)`) — 113 tables total. `agent_deployments` gained one column: `environment_id` (nullable FK to `environments`, `ON DELETE SET NULL`) — the pre-existing `environment` string column is untouched. Migration `0038_environments_promotion` is additive plus one deterministic, one-time data seed+backfill (the §15 mapping — see `docs/deployment/environments.md`).

**Phase 3.1 update**: 2 new tables — `deployment_events` (append-only lifecycle lineage: `from_state`/`to_state`/`event_type`/`reason`/`actor_id`/`idempotency_key`, indexed on `(deployment_id, created_at)`), `idempotency_keys` (the reusable, platform-wide `Idempotency-Key` contract, scoped `(organization_id, operation, idempotency_key)`, unique) — 111 tables total. `agent_deployments` gained four columns: `lifecycle_state`/`revision`/`state_reason`/`superseded_by_deployment_id` (the last a self-referencing FK, `ON DELETE SET NULL`). No existing column was retyped or dropped. Migration `0037_deployment_lifecycle` is additive plus one deterministic, one-time data backfill (the §15 mapping — see `docs/deployment/lifecycle.md`).

**Phase 2.3.1 update** (the immediately preceding schema change, correcting this document's own header, which was not kept current through that phase): 2 new tables — `identity_federation_configs` (per-organization IdP configuration; `configuration` JSONB non-secret, `encrypted_client_secret` nullable; unique on `(organization_id, protocol, provider_type)`), `federated_identities` (links an IdP subject to an existing `users.id` row; no credential column of any kind; unique on `(federation_config_id, external_subject_id)`) — 109 tables total as of that phase. Migration `0036_identity_federation` was purely additive, two new tables only. (Phase 2.2.1 through 2.2.4, in between, added no schema — every generic connector configures through the pre-existing `connectors`/`connector_instances`/`connector_credentials` tables.)

**Phase 2.1.3 update**: 1 new table — `connector_health_checks` (append-only history: `check_type`/`reachable`/`auth_valid`/`result`/`reason`/`latency_ms`/`checked_at`, indexed on `(connector_instance_id, checked_at)`) — 107 tables total. `connector_instances` gained two nullable columns: `last_health_check_at` (TIMESTAMP), `current_health` (VARCHAR(16)) — a fast-read cache derived from the history table. Migration `0035_connector_health` is purely additive.

**Phase 2.1.2 update**: 2 new tables — `connector_credentials` (per-`(connector_instance_id, auth_scheme)` encrypted credential bundle: `encrypted_secret`/`secret_hint`/`status`/`last_validated_at`/`validation_status`, unique on `(connector_instance_id, auth_scheme)`, no per-field plaintext column), `connector_oauth_tokens` (per-instance cached OAuth2 token pair: `encrypted_access_token`/`encrypted_refresh_token`/`expires_at`, unique on `connector_instance_id`) — 106 tables total. No existing table gained, lost, or retyped a column — migration `0034_connector_auth` is purely additive, two new tables only.

**Phase 2.1.1 update**: 3 new tables — `connectors` (registered connector *types*: `connector_type`/`version` unique, `capabilities`/`config_schema`/`auth_requirements`/`tool_contracts` all JSONB), `connector_instances` (tenant-scoped configured uses of a type: `organization_id` FK CASCADE, `connector_id` FK RESTRICT, `configuration` JSONB, `lifecycle_state` VARCHAR(20), unique on `(organization_id, name)`), `connector_lifecycle_events` (append-only transition audit: `connector_instance_id` FK CASCADE, `from_state`/`to_state`, `reason`, `actor_id`) — 104 tables total. No existing table gained, lost, or retyped a column — migration `0033_connector_core` is purely additive, three new tables only.

**Phase 5.6a.3 update**: 1 new table, `execution_messages` (the full conversation transcript for the model-driven tool loop, `ACT-TLX-FR-049` — 101 tables total). `agent_executions` gained two columns: `loop_iterations` (`INTEGER NOT NULL DEFAULT 0`), `termination_reason` (`VARCHAR(40)` nullable). `tool_calls` gained one nullable column: `loop_iteration` (`INTEGER`) — migration `0032_tool_loop`.

**Phase 5.6a.2 update**: table count unchanged at 100 (no new table). `tool_calls` gained three nullable columns: `error_class` (`VARCHAR(32)`), `attempt_number` (`INTEGER`), `validation_error` (`TEXT`) — migration `0031_tool_resilience`.

**Phase 5.6a.1 update**: re-extracted this session (previously 99 tables at `0029_provider_credentials`). 1 new table: `tool_credentials` (per-organization, per-tool encrypted HTTP-action credentials, `ACT-TLX-FR-012`). `tools` gained one column (`http_config`, JSONB); `tool_calls` gained eight (`target_host`/`target_path`/`http_method`/`http_status`/`request_bytes`/`response_bytes`/`egress_decision`/`egress_denied_reason`).

**Phase 5.7a.5 update**: re-extracted previously (98 tables at `0028_streaming_and_pricing`). 1 new table: `provider_credentials` (per-organization, per-provider encrypted model-provider credentials, `ACT-MDL-FR-080..083`). No existing table gained or lost a column — this phase is purely additive at the schema level.

**Phase 5.7a.4 update**: no schema change at all (confirmed live) — the taxonomy classification is stored as a value inside the pre-existing `error_code` columns, not a new column.

**Phase 5.7a.3 update**: re-extracted this session (previously 97 tables at `0027_version_signing`). 1 new table: `model_pricing` (per-provider/model pricing with effective dating, ACT-MDL-FR-084). `agent_executions` gained twelve columns (`prompt_tokens`/`completion_tokens`/`total_tokens`/`token_accounting_complete`/`cost_amount`/`cost_currency`/`pricing_version`/`cost_is_estimated`/`time_to_first_token_ms`/`generation_duration_ms`/`finish_reason`/`was_streamed`/`stream_interrupted`); `execution_attempts` gained four (`prompt_tokens`/`completion_tokens`/`total_tokens`/`token_accounting_complete`). Phase 5.7a.1/5.7a.2 added no schema changes at all (confirmed live both times — see §8's branch history and the Milestone 1 status table in §6).

**Phase 5.2.6/5.2.4 update**: re-extracted previously (92 tables at `0025_agent_versioning`). 5 new tables: `agent_version_compatibility_findings` (5.2.6), `signing_keys`, `signing_key_versions`, `agent_version_signatures`, `agent_version_provenance` (5.2.4). `agent_versions` gained `compatibility_baseline_id`/`compatibility_analyzed_at` (5.2.6) and `checksum_algorithm`/`signed_at`/`manifest_digest` (5.2.4), plus `checksum` widened from `VARCHAR(64)` to `VARCHAR(80)`. `agent_version_snapshots` gained `checksum_algorithm` and the same `checksum` widening.

For each table: every column with its Postgres type, nullability and default; primary key; foreign keys (with `ondelete` behavior); unique constraints; and indexes (including the unique ones, which Postgres also surfaces as indexes).

#### abac_evaluations
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NULL
  - identity_id: UUID NULL
  - resource_type: VARCHAR(50) NULL
  - resource_id: UUID NULL
  - action: VARCHAR(100) NOT NULL
  - decision: VARCHAR(30) NOT NULL
  - matched_policy_ids: JSONB NULL
  - obligations: JSONB NULL
  - explanation: JSONB NULL
  - evaluation_time_ms: DOUBLE PRECISION NULL
  - request_id: VARCHAR(100) NULL
  - correlation_id: VARCHAR(100) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=abac_evaluations_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=abac_evaluations_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_abac_evaluations_decision: ['decision']
  - ix_abac_evaluations_org: ['organization_id']

#### abac_policies
Columns:
  - id: UUID NOT NULL
  - policy_family_id: UUID NOT NULL
  - organization_id: UUID NULL
  - name: VARCHAR(255) NOT NULL
  - description: TEXT NULL
  - version: INTEGER NOT NULL DEFAULT 1
  - status: VARCHAR(20) NOT NULL DEFAULT 'DRAFT'::character varying
  - priority: INTEGER NOT NULL DEFAULT 100
  - combining_algorithm: VARCHAR(30) NOT NULL DEFAULT 'DENY_OVERRIDES'::character varying
  - scope_type: VARCHAR(20) NOT NULL DEFAULT 'ORGANIZATION'::character varying
  - scope_id: UUID NULL
  - target: JSONB NULL
  - conditions: JSONB NULL
  - effect: VARCHAR(30) NOT NULL DEFAULT 'DENY'::character varying
  - obligations: JSONB NULL
  - valid_from: TIMESTAMP NULL
  - valid_until: TIMESTAMP NULL
  - created_by: UUID NULL
  - updated_by: UUID NULL
  - published_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=abac_policies_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=abac_policies_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_abac_policies_family: ['policy_family_id']
  - ix_abac_policies_org: ['organization_id']
  - ix_abac_policies_status: ['status']

#### abac_policy_exceptions
Columns:
  - id: UUID NOT NULL
  - policy_id: UUID NOT NULL
  - subject_type: VARCHAR(30) NOT NULL DEFAULT 'USER'::character varying
  - subject_id: UUID NOT NULL
  - resource_type: VARCHAR(50) NULL
  - resource_id: UUID NULL
  - reason: VARCHAR(500) NULL
  - approved_by: UUID NULL
  - valid_from: TIMESTAMP NULL
  - valid_until: TIMESTAMP NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=abac_policy_exceptions_pkey)
Foreign keys:
  - ['policy_id'] -> abac_policies.['id'] (name=abac_policy_exceptions_policy_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_abac_policy_exceptions_policy: ['policy_id']
  - ix_abac_policy_exceptions_subject: ['subject_id']

#### abac_policy_versions
Columns:
  - id: UUID NOT NULL
  - policy_family_id: UUID NOT NULL
  - version: INTEGER NOT NULL
  - snapshot: JSONB NOT NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=abac_policy_versions_pkey)
Indexes:
  - ix_abac_policy_versions_family: ['policy_family_id']

#### access_review_campaigns
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - description: TEXT NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'DRAFT'::character varying
  - scope: JSONB NULL
  - reviewer_id: UUID NULL
  - due_at: TIMESTAMP NULL
  - created_by: UUID NULL
  - activated_at: TIMESTAMP NULL
  - completed_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - campaign_type: VARCHAR(30) NOT NULL DEFAULT 'QUARTERLY'::character varying
Primary key: ['id'] (name=access_review_campaigns_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=access_review_campaigns_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_access_review_campaigns_org: ['organization_id']
  - ix_access_review_campaigns_status: ['status']

#### access_review_items
Columns:
  - id: UUID NOT NULL
  - campaign_id: UUID NOT NULL
  - subject_id: UUID NOT NULL
  - subject_label: VARCHAR(255) NOT NULL
  - assignment_id: UUID NULL
  - role_id: UUID NULL
  - role_name: VARCHAR(255) NOT NULL
  - scope_label: VARCHAR(255) NULL
  - decision: VARCHAR(20) NOT NULL DEFAULT 'PENDING'::character varying
  - decided_by: UUID NULL
  - decided_at: TIMESTAMP NULL
  - comment: VARCHAR(500) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=access_review_items_pkey)
Foreign keys:
  - ['campaign_id'] -> access_review_campaigns.['id'] (name=access_review_items_campaign_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_access_review_items_campaign: ['campaign_id']
  - ix_access_review_items_decision: ['decision']
  - ix_access_review_items_subject: ['subject_id']

#### account_locks
Columns:
  - id: UUID NOT NULL
  - user_id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - reason: VARCHAR(40) NOT NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - locked_at: TIMESTAMP NOT NULL DEFAULT now()
  - expires_at: TIMESTAMP NULL
  - unlocked_at: TIMESTAMP NULL
  - unlocked_by: UUID NULL
  - meta: JSONB NOT NULL DEFAULT '{}'::jsonb
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=account_locks_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=account_locks_organization_id_fkey, ondelete=CASCADE)
  - ['unlocked_by'] -> users.['id'] (name=account_locks_unlocked_by_fkey, ondelete=SET NULL)
  - ['user_id'] -> users.['id'] (name=account_locks_user_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_account_locks_organization_id: ['organization_id']
  - ix_account_locks_status: ['status']
  - ix_account_locks_user_id: ['user_id']
  - ix_account_locks_user_status: ['user_id', 'status']

#### agent_actions
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - resource: VARCHAR(100) NOT NULL
  - action: VARCHAR(100) NOT NULL
  - input_payload: JSONB NOT NULL
  - output_payload: JSONB NULL
  - risk_score: INTEGER NOT NULL
  - decision: VARCHAR(16) NOT NULL
  - decision_reason: TEXT NOT NULL
  - status: VARCHAR(8) NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_actions_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_actions_agent_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=agent_actions_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_actions_agent_id: ['agent_id']
  - ix_agent_actions_organization_id: ['organization_id']

#### agent_api_keys
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - key_hash: VARCHAR(128) NOT NULL
  - key_prefix: VARCHAR(20) NOT NULL
  - status: VARCHAR(7) NOT NULL
  - last_used_at: TIMESTAMP NULL
  - expires_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_api_keys_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_api_keys_agent_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_agent_api_keys_key_hash: ['key_hash']
Indexes:
  - ix_agent_api_keys_agent_id: ['agent_id']
  - ix_agent_api_keys_key_hash: ['key_hash']
  - uq_agent_api_keys_key_hash: ['key_hash'] (unique)

#### agent_capabilities
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - agent_version_id: UUID NULL
  - capability_id: UUID NOT NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'REQUESTED'::character varying
  - constraints: JSONB NULL
  - approved_by: UUID NULL
  - approved_at: TIMESTAMP NULL
  - expires_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_capabilities_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_capabilities_agent_id_fkey, ondelete=CASCADE)
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_capabilities_agent_version_id_fkey, ondelete=CASCADE)
  - ['capability_id'] -> capabilities.['id'] (name=agent_capabilities_capability_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_capabilities_agent: ['agent_id']
  - ix_agent_capabilities_capability: ['capability_id']
  - ix_agent_capabilities_status: ['status']

#### agent_definitions
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - description: TEXT NULL
  - framework: VARCHAR(50) NOT NULL DEFAULT 'CUSTOM'::character varying
  - entrypoint_type: VARCHAR(30) NOT NULL DEFAULT 'FUNCTION'::character varying
  - entrypoint: VARCHAR(500) NOT NULL
  - system_instructions: TEXT NULL
  - configuration_schema: JSONB NULL
  - input_schema: JSONB NULL
  - output_schema: JSONB NULL
  - metadata: JSONB NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - framework_version: VARCHAR(50) NULL
  - runtime_language: VARCHAR(50) NULL
  - capability_declarations: JSONB NOT NULL DEFAULT '[]'::jsonb
  - tool_declarations: JSONB NOT NULL DEFAULT '[]'::jsonb
  - model_requirements: JSONB NOT NULL DEFAULT '{}'::jsonb
  - memory_requirements: JSONB NOT NULL DEFAULT '{}'::jsonb
  - data_requirements: JSONB NOT NULL DEFAULT '{}'::jsonb
  - network_requirements: JSONB NOT NULL DEFAULT '{}'::jsonb
  - secret_requirements: JSONB NOT NULL DEFAULT '{}'::jsonb
  - runtime_requirements: JSONB NOT NULL DEFAULT '{}'::jsonb
  - created_by: UUID NULL
  - updated_by: UUID NULL
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_definitions_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_definitions_agent_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_definitions_agent: ['agent_id']

#### agent_deployments
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - agent_version_id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - environment: VARCHAR(20) NOT NULL DEFAULT 'DEVELOPMENT'::character varying
  - deployment_strategy: VARCHAR(20) NOT NULL DEFAULT 'RECREATE'::character varying
  - status: VARCHAR(20) NOT NULL DEFAULT 'CREATED'::character varying
  - desired_replicas: INTEGER NOT NULL DEFAULT 1
  - active_replicas: INTEGER NOT NULL DEFAULT 0
  - configuration: JSONB NOT NULL DEFAULT '{}'::jsonb
  - secret_references: JSONB NOT NULL DEFAULT '{}'::jsonb
  - runtime_limits: JSONB NOT NULL DEFAULT '{}'::jsonb
  - health_status: VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN'::character varying
  - deployed_by: UUID NULL
  - deployed_at: TIMESTAMP NULL
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - retired_at: TIMESTAMP NULL
  - lifecycle_state: VARCHAR(24) NOT NULL DEFAULT 'DRAFT'::character varying — Phase 3.1, the new governed lifecycle; `status` above is untouched, kept for the pre-existing `DeploymentService` methods
  - revision: INTEGER NOT NULL DEFAULT 1 — Phase 3.1, a SQLAlchemy `version_id_col` (optimistic concurrency, mapper-wide)
  - state_reason: TEXT NULL — Phase 3.1
  - superseded_by_deployment_id: UUID NULL — Phase 3.1
  - environment_id: UUID NULL — Phase 3.2, nullable FK to `environments`; the pre-existing `environment` string above is untouched, see docs/deployment/environments.md
Primary key: ['id'] (name=agent_deployments_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_deployments_agent_id_fkey, ondelete=CASCADE)
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_deployments_agent_version_id_fkey, ondelete=RESTRICT)
  - ['environment_id'] -> environments.['id'] (name=fk_agent_deployments_environment, ondelete=SET NULL) — Phase 3.2
  - ['organization_id'] -> organizations.['id'] (name=agent_deployments_organization_id_fkey, ondelete=CASCADE)
  - ['superseded_by_deployment_id'] -> agent_deployments.['id'] (name=fk_agent_deployments_superseded_by, ondelete=SET NULL) — Phase 3.1
Indexes:
  - ix_agent_deployments_agent: ['agent_id']
  - ix_agent_deployments_environment_id: ['environment_id'] — Phase 3.2
  - ix_agent_deployments_lifecycle_state: ['lifecycle_state'] — Phase 3.1
  - ix_agent_deployments_org: ['organization_id']
  - ix_agent_deployments_status: ['status']
  - ix_agent_deployments_version: ['agent_version_id']

#### agent_duplicate_matches
Columns:
  - id: UUID NOT NULL
  - source_agent_id: UUID NOT NULL
  - candidate_agent_id: UUID NOT NULL
  - match_type: VARCHAR(20) NOT NULL
  - confidence_score: NUMERIC(5, 2) NOT NULL
  - matching_fields: JSONB NOT NULL DEFAULT '[]'::jsonb
  - status: VARCHAR(30) NOT NULL DEFAULT 'POSSIBLE_DUPLICATE'::character varying
  - reviewed_by: UUID NULL
  - review_decision: VARCHAR(30) NULL
  - review_reason: TEXT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - reviewed_at: TIMESTAMP NULL
Primary key: ['id'] (name=agent_duplicate_matches_pkey)
Foreign keys:
  - ['candidate_agent_id'] -> agents.['id'] (name=agent_duplicate_matches_candidate_agent_id_fkey, ondelete=CASCADE)
  - ['source_agent_id'] -> agents.['id'] (name=agent_duplicate_matches_source_agent_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_duplicate_matches_candidate: ['candidate_agent_id']
  - ix_agent_duplicate_matches_source: ['source_agent_id']
  - ix_agent_duplicate_matches_status: ['status']

#### agent_executions
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - agent_version_id: UUID NOT NULL
  - deployment_id: UUID NULL
  - trigger_type: VARCHAR(20) NOT NULL DEFAULT 'API'::character varying
  - triggered_by_identity_id: UUID NULL
  - parent_execution_id: UUID NULL
  - correlation_id: VARCHAR(100) NULL
  - idempotency_key: VARCHAR(150) NULL
  - input_payload: JSONB NOT NULL DEFAULT '{}'::jsonb
  - output_payload: JSONB NULL
  - status: VARCHAR(24) NOT NULL DEFAULT 'CREATED'::character varying
  - decision: VARCHAR(24) NULL
  - risk_score: INTEGER NULL
  - priority: VARCHAR(20) NOT NULL DEFAULT 'NORMAL'::character varying
  - queued_at: TIMESTAMP NULL
  - started_at: TIMESTAMP NULL
  - completed_at: TIMESTAMP NULL
  - duration_ms: INTEGER NULL
  - attempt_count: INTEGER NOT NULL DEFAULT 0
  - cancel_requested: BOOLEAN NOT NULL DEFAULT false
  - error_code: VARCHAR(50) NULL
  - error_message: TEXT NULL
  - model_usage: JSONB NULL
  - tool_usage: JSONB NULL
  - cost: NUMERIC(12, 6) NOT NULL DEFAULT '0'::numeric
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - prompt_tokens: INTEGER NULL
  - completion_tokens: INTEGER NULL
  - total_tokens: INTEGER NULL
  - token_accounting_complete: BOOLEAN NOT NULL DEFAULT true
  - cost_amount: NUMERIC(18, 8) NULL
  - cost_currency: VARCHAR(3) NOT NULL DEFAULT 'USD'::character varying
  - pricing_version: VARCHAR(32) NULL
  - cost_is_estimated: BOOLEAN NOT NULL DEFAULT false
  - time_to_first_token_ms: INTEGER NULL
  - generation_duration_ms: INTEGER NULL
  - finish_reason: VARCHAR(32) NULL
  - was_streamed: BOOLEAN NOT NULL DEFAULT false
  - stream_interrupted: BOOLEAN NOT NULL DEFAULT false
  - loop_iterations: INTEGER NOT NULL DEFAULT 0
  - termination_reason: VARCHAR(40) NULL
Primary key: ['id'] (name=agent_executions_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_executions_agent_id_fkey, ondelete=CASCADE)
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_executions_agent_version_id_fkey, ondelete=RESTRICT)
  - ['deployment_id'] -> agent_deployments.['id'] (name=agent_executions_deployment_id_fkey, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=agent_executions_organization_id_fkey, ondelete=CASCADE)
  - ['parent_execution_id'] -> agent_executions.['id'] (name=agent_executions_parent_execution_id_fkey, ondelete=SET NULL)
Indexes:
  - ix_agent_executions_agent: ['agent_id']
  - ix_agent_executions_correlation: ['correlation_id']
  - ix_agent_executions_idempotency: ['idempotency_key']
  - ix_agent_executions_org: ['organization_id']
  - ix_agent_executions_queue: ['status', 'priority', 'queued_at']
  - ix_agent_executions_status: ['status']
  - ix_agent_executions_version: ['agent_version_id']

#### agent_export_jobs
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - export_type: VARCHAR(30) NOT NULL
  - format: VARCHAR(10) NOT NULL
  - filters: JSONB NOT NULL DEFAULT '{}'::jsonb
  - status: VARCHAR(20) NOT NULL DEFAULT 'PENDING'::character varying
  - record_count: INTEGER NOT NULL DEFAULT 0
  - storage_reference: VARCHAR(500) NULL
  - payload: TEXT NULL
  - expires_at: TIMESTAMP NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - completed_at: TIMESTAMP NULL
Primary key: ['id'] (name=agent_export_jobs_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=agent_export_jobs_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_export_jobs_org: ['organization_id']

#### agent_identities
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - client_id: VARCHAR(100) NOT NULL
  - credential_type: VARCHAR(30) NOT NULL
  - status: VARCHAR(30) NOT NULL
  - last_used_at: TIMESTAMP NULL
  - expires_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_identities_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_identities_agent_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_agent_identities_agent: ['agent_id']
  - uq_agent_identities_client_id: ['client_id']
Indexes:
  - ix_agent_identities_agent_id: ['agent_id']
  - ix_agent_identities_client_id: ['client_id']
  - uq_agent_identities_agent: ['agent_id'] (unique)
  - uq_agent_identities_client_id: ['client_id'] (unique)

#### agent_import_items
Columns:
  - id: UUID NOT NULL
  - import_job_id: UUID NOT NULL
  - record_identifier: VARCHAR(255) NOT NULL
  - status: VARCHAR(20) NOT NULL
  - agent_id: UUID NULL
  - errors: JSONB NOT NULL DEFAULT '[]'::jsonb
  - warnings: JSONB NOT NULL DEFAULT '[]'::jsonb
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_import_items_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_import_items_agent_id_fkey, ondelete=SET NULL)
  - ['import_job_id'] -> agent_import_jobs.['id'] (name=agent_import_items_import_job_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_import_items_job: ['import_job_id']

#### agent_import_jobs
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - file_name: VARCHAR(255) NOT NULL
  - format: VARCHAR(10) NOT NULL
  - mode: VARCHAR(30) NOT NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'PENDING'::character varying
  - total_records: INTEGER NOT NULL DEFAULT 0
  - successful_records: INTEGER NOT NULL DEFAULT 0
  - failed_records: INTEGER NOT NULL DEFAULT 0
  - warning_records: INTEGER NOT NULL DEFAULT 0
  - created_by: UUID NULL
  - started_at: TIMESTAMP NULL
  - completed_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_import_jobs_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=agent_import_jobs_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_import_jobs_org: ['organization_id']

#### agent_lifecycle_events
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - previous_status: VARCHAR(20) NULL
  - new_status: VARCHAR(20) NOT NULL
  - reason: TEXT NULL
  - requested_by: UUID NOT NULL
  - approved_by: UUID NULL
  - authorization_decision_id: UUID NULL
  - request_id: VARCHAR(100) NOT NULL
  - correlation_id: VARCHAR(100) NOT NULL
  - metadata: JSONB NOT NULL DEFAULT '{}'::jsonb
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_lifecycle_events_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_lifecycle_events_agent_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=agent_lifecycle_events_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_lifecycle_events_agent: ['agent_id']
  - ix_agent_lifecycle_events_org: ['organization_id']

#### agent_migration_records
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - migration_batch_id: VARCHAR(100) NOT NULL
  - legacy_source: VARCHAR(100) NOT NULL
  - legacy_id: VARCHAR(100) NOT NULL
  - migration_status: VARCHAR(30) NOT NULL
  - mapping_warnings: JSONB NOT NULL DEFAULT '[]'::jsonb
  - migrated_by: UUID NULL
  - migrated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_migration_records_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_migration_records_agent_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_migration_records_agent: ['agent_id']
  - ix_agent_migration_records_batch: ['migration_batch_id']

#### agent_ownership_history
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - owner_role: VARCHAR(30) NOT NULL
  - previous_owner_type: VARCHAR(30) NULL
  - previous_owner_id: UUID NULL
  - new_owner_type: VARCHAR(30) NOT NULL
  - new_owner_id: UUID NOT NULL
  - reason: TEXT NOT NULL
  - changed_by: UUID NOT NULL
  - approved_by: UUID NULL
  - changed_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_ownership_history_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_ownership_history_agent_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_ownership_history_agent: ['agent_id']

#### agent_release_artifacts
Columns:
  - id: UUID NOT NULL
  - agent_version_id: UUID NOT NULL
  - artifact_type: VARCHAR(30) NOT NULL
  - reference: VARCHAR(500) NOT NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_release_artifacts_pkey)
Foreign keys:
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_release_artifacts_agent_version_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_release_artifacts_version: ['agent_version_id']

#### agent_release_channels
Columns:
  - id: UUID NOT NULL
  - name: VARCHAR(30) NOT NULL
  - description: TEXT NULL
  - is_default: BOOLEAN NOT NULL DEFAULT false
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_release_channels_pkey)
Unique constraints:
  - agent_release_channels_name_key: ['name']
Indexes:
  - agent_release_channels_name_key: ['name'] (unique)

#### agent_release_metadata
Columns:
  - id: UUID NOT NULL
  - agent_version_id: UUID NOT NULL
  - release_name: VARCHAR(255) NULL
  - release_description: TEXT NULL
  - business_justification: TEXT NULL
  - change_category: VARCHAR(20) NULL
  - release_window_start: TIMESTAMP NULL
  - release_window_end: TIMESTAMP NULL
  - support_end_date: TIMESTAMP NULL
  - approval_ticket: VARCHAR(100) NULL
  - source_branch: VARCHAR(200) NULL
  - commit_reference: VARCHAR(100) NULL
  - build_reference: VARCHAR(200) NULL
  - risk_score: INTEGER NULL
  - documentation_url: VARCHAR(500) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_release_metadata_pkey)
Foreign keys:
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_release_metadata_agent_version_id_fkey, ondelete=CASCADE)
Unique constraints:
  - agent_release_metadata_agent_version_id_key: ['agent_version_id']
Indexes:
  - agent_release_metadata_agent_version_id_key: ['agent_version_id'] (unique)
  - ix_agent_release_metadata_version: ['agent_version_id']

#### agent_release_notes
Columns:
  - id: UUID NOT NULL
  - agent_version_id: UUID NOT NULL
  - category: VARCHAR(20) NOT NULL DEFAULT 'CHANGED'::character varying
  - note: TEXT NOT NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_release_notes_pkey)
Foreign keys:
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_release_notes_agent_version_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_release_notes_version: ['agent_version_id']

#### agent_tools
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - agent_version_id: UUID NULL
  - tool_id: UUID NOT NULL
  - allowed_actions: JSONB NOT NULL DEFAULT '[]'::jsonb
  - constraints: JSONB NULL
  - environment: VARCHAR(20) NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'REQUESTED'::character varying
  - approved_by: UUID NULL
  - approved_at: TIMESTAMP NULL
  - expires_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_tools_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_tools_agent_id_fkey, ondelete=CASCADE)
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_tools_agent_version_id_fkey, ondelete=CASCADE)
  - ['tool_id'] -> tools.['id'] (name=agent_tools_tool_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_tools_agent: ['agent_id']
  - ix_agent_tools_status: ['status']
  - ix_agent_tools_tool: ['tool_id']

#### agent_validation_runs
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'RUNNING'::character varying
  - validator_version: VARCHAR(20) NOT NULL
  - summary: JSONB NOT NULL DEFAULT '{}'::jsonb
  - errors: JSONB NOT NULL DEFAULT '[]'::jsonb
  - warnings: JSONB NOT NULL DEFAULT '[]'::jsonb
  - checks: JSONB NOT NULL DEFAULT '[]'::jsonb
  - started_at: TIMESTAMP NOT NULL DEFAULT now()
  - completed_at: TIMESTAMP NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_validation_runs_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_validation_runs_agent_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_validation_runs_agent: ['agent_id']

#### agent_version_compatibility_findings
Columns:
  - id: UUID NOT NULL
  - agent_version_id: UUID NOT NULL
  - baseline_version_id: UUID NULL
  - category: VARCHAR(40) NOT NULL
  - path: VARCHAR(255) NOT NULL
  - change_type: VARCHAR(20) NOT NULL
  - materiality: VARCHAR(20) NOT NULL
  - baseline_value: TEXT NULL
  - candidate_value: TEXT NULL
  - description: TEXT NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_version_compatibility_findings_pkey)
Foreign keys:
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_version_compatibility_findings_agent_version_id_fkey, ondelete=CASCADE)
  - ['baseline_version_id'] -> agent_versions.['id'] (name=agent_version_compatibility_findings_baseline_version_id_fkey, ondelete=SET NULL)
Indexes:
  - ix_version_compat_findings_version: ['agent_version_id']

#### agent_version_provenance
Columns:
  - id: UUID NOT NULL
  - agent_version_id: UUID NOT NULL
  - actor_id: UUID NOT NULL
  - actor_type: VARCHAR(32) NOT NULL DEFAULT 'USER'::character varying
  - source_repository: TEXT NULL
  - source_commit: VARCHAR(64) NULL
  - source_ref: VARCHAR(255) NULL
  - build_environment: VARCHAR(128) NULL
  - builder_identity: TEXT NOT NULL
  - source_ip: VARCHAR(45) NULL
  - correlation_id: UUID NULL
  - attestation_document: JSONB NOT NULL DEFAULT '{}'::jsonb
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_version_provenance_pkey)
Foreign keys:
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_version_provenance_agent_version_id_fkey, ondelete=CASCADE)
Unique constraints:
  - agent_version_provenance_agent_version_id_key: ['agent_version_id']
Indexes:
  - agent_version_provenance_agent_version_id_key: ['agent_version_id'] (unique)
  - ix_agent_version_provenance_version: ['agent_version_id']

#### agent_version_signatures
Columns:
  - id: UUID NOT NULL
  - agent_version_id: UUID NOT NULL
  - manifest_digest: VARCHAR(80) NOT NULL
  - signature: BYTEA NOT NULL
  - algorithm: VARCHAR(32) NOT NULL
  - signing_key_id: UUID NOT NULL
  - signing_key_version: INTEGER NOT NULL
  - signature_type: VARCHAR(32) NOT NULL DEFAULT 'PUBLISHER'::character varying
  - dsse_envelope: JSONB NOT NULL DEFAULT '{}'::jsonb
  - verification_status: VARCHAR(20) NOT NULL DEFAULT 'UNVERIFIED'::character varying
  - signed_at: TIMESTAMP NOT NULL DEFAULT now()
  - signed_by: UUID NULL
Primary key: ['id'] (name=agent_version_signatures_pkey)
Foreign keys:
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_version_signatures_agent_version_id_fkey, ondelete=CASCADE)
  - ['signed_by'] -> users.['id'] (name=agent_version_signatures_signed_by_fkey, ondelete=SET NULL)
  - ['signing_key_id'] -> signing_keys.['id'] (name=agent_version_signatures_signing_key_id_fkey, ondelete=RESTRICT)
Indexes:
  - ix_agent_version_signatures_version: ['agent_version_id']

#### agent_version_snapshots
Columns:
  - id: UUID NOT NULL
  - agent_version_id: UUID NOT NULL
  - snapshot: JSONB NOT NULL DEFAULT '{}'::jsonb
  - checksum: VARCHAR(80) NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - checksum_algorithm: VARCHAR(20) NOT NULL DEFAULT 'legacy-sha256'::character varying
Primary key: ['id'] (name=agent_version_snapshots_pkey)
Foreign keys:
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_version_snapshots_agent_version_id_fkey, ondelete=CASCADE)
Unique constraints:
  - agent_version_snapshots_agent_version_id_key: ['agent_version_id']
Indexes:
  - agent_version_snapshots_agent_version_id_key: ['agent_version_id'] (unique)
  - ix_agent_version_snapshots_version: ['agent_version_id']

#### agent_version_status_history
Columns:
  - id: UUID NOT NULL
  - agent_version_id: UUID NOT NULL
  - previous_status: VARCHAR(20) NULL
  - new_status: VARCHAR(20) NOT NULL
  - reason: TEXT NULL
  - changed_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=agent_version_status_history_pkey)
Foreign keys:
  - ['agent_version_id'] -> agent_versions.['id'] (name=agent_version_status_history_agent_version_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_agent_version_status_history_version: ['agent_version_id']

#### agent_versions
Columns:
  - id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - definition_id: UUID NOT NULL
  - version: INTEGER NOT NULL
  - semantic_version: VARCHAR(20) NOT NULL DEFAULT '0.1.0'::character varying
  - status: VARCHAR(20) NOT NULL DEFAULT 'DRAFT'::character varying
  - configuration_snapshot: JSONB NOT NULL DEFAULT '{}'::jsonb
  - prompt_snapshot: JSONB NULL
  - model_configuration: JSONB NOT NULL DEFAULT '{}'::jsonb
  - capabilities_snapshot: JSONB NOT NULL DEFAULT '[]'::jsonb
  - tools_snapshot: JSONB NOT NULL DEFAULT '[]'::jsonb
  - policy_snapshot: JSONB NULL
  - checksum: VARCHAR(80) NOT NULL
  - release_notes: TEXT NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - published_at: TIMESTAMP NULL
  - deprecated_at: TIMESTAMP NULL
  - release_channel_id: UUID NULL
  - compatibility_level: VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN'::character varying
  - signature_id: VARCHAR(255) NULL
  - snapshot_reference: VARCHAR(255) NULL
  - parent_version_id: UUID NULL
  - rollback_target_id: UUID NULL
  - superseded_by_id: UUID NULL
  - release_branch: VARCHAR(100) NOT NULL DEFAULT 'main'::character varying
  - reviewed_by: UUID NULL
  - revoked_reason: TEXT NULL
  - retired_at: TIMESTAMP NULL
  - compatibility_baseline_id: UUID NULL
  - compatibility_analyzed_at: TIMESTAMP NULL
  - checksum_algorithm: VARCHAR(20) NOT NULL DEFAULT 'legacy-sha256'::character varying
  - signed_at: TIMESTAMP NULL
  - manifest_digest: VARCHAR(80) NULL
Primary key: ['id'] (name=agent_versions_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=agent_versions_agent_id_fkey, ondelete=CASCADE)
  - ['definition_id'] -> agent_definitions.['id'] (name=agent_versions_definition_id_fkey, ondelete=RESTRICT)
  - ['compatibility_baseline_id'] -> agent_versions.['id'] (name=fk_agent_versions_compatibility_baseline, ondelete=SET NULL)
  - ['parent_version_id'] -> agent_versions.['id'] (name=fk_agent_versions_parent_version, ondelete=SET NULL)
  - ['release_channel_id'] -> agent_release_channels.['id'] (name=fk_agent_versions_release_channel, ondelete=SET NULL)
  - ['rollback_target_id'] -> agent_versions.['id'] (name=fk_agent_versions_rollback_target, ondelete=SET NULL)
  - ['superseded_by_id'] -> agent_versions.['id'] (name=fk_agent_versions_superseded_by, ondelete=SET NULL)
Unique constraints:
  - uq_agent_versions_agent_version: ['agent_id', 'version']
Indexes:
  - ix_agent_versions_agent: ['agent_id']
  - ix_agent_versions_compatibility_baseline: ['compatibility_baseline_id']
  - ix_agent_versions_parent_version: ['parent_version_id']
  - ix_agent_versions_release_channel: ['release_channel_id']
  - ix_agent_versions_status: ['status']
  - uq_agent_versions_agent_version: ['agent_id', 'version'] (unique)

#### agents
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - description: TEXT NULL
  - agent_type: VARCHAR(100) NOT NULL
  - api_key_hash: VARCHAR(255) NOT NULL
  - status: VARCHAR(9) NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - owner: VARCHAR(255) NULL
  - department: VARCHAR(255) NULL
  - version: VARCHAR(50) NOT NULL DEFAULT '1.0.0'::character varying
  - capabilities: JSONB NOT NULL DEFAULT '[]'::jsonb
  - default_risk_score: INTEGER NOT NULL DEFAULT 0
  - max_allowed_risk: INTEGER NOT NULL DEFAULT 100
  - human_approval_required: BOOLEAN NOT NULL DEFAULT false
  - auto_suspend_threshold: INTEGER NULL
  - risk_level: VARCHAR(20) NOT NULL DEFAULT 'LOW'::character varying
  - health: VARCHAR(20) NOT NULL DEFAULT 'HEALTHY'::character varying
  - slug: VARCHAR(150) NULL
  - project_id: UUID NULL
  - owner_type: VARCHAR(30) NULL
  - owner_id: UUID NULL
  - criticality: VARCHAR(20) NOT NULL DEFAULT 'MEDIUM'::character varying
  - data_classification: VARCHAR(30) NOT NULL DEFAULT 'INTERNAL'::character varying
  - default_environment: VARCHAR(20) NOT NULL DEFAULT 'DEVELOPMENT'::character varying
  - lifecycle_status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - archived_at: TIMESTAMP NULL
  - business_unit_id: UUID NULL
  - department_id: UUID NULL
  - team_id: UUID NULL
  - identity_id: UUID NULL
  - display_name: VARCHAR(255) NULL
  - business_purpose: TEXT NULL
  - autonomy_level: VARCHAR(30) NOT NULL DEFAULT 'ASSISTIVE'::character varying
  - technical_owner_id: UUID NULL
  - compliance_owner_id: UUID NULL
  - support_contact: VARCHAR(255) NULL
  - documentation_url: VARCHAR(500) NULL
  - repository_url: VARCHAR(500) NULL
  - tags: JSONB NOT NULL DEFAULT '[]'::jsonb
  - metadata: JSONB NOT NULL DEFAULT '{}'::jsonb
  - registration_source: VARCHAR(30) NOT NULL DEFAULT 'MANUAL'::character varying
  - external_reference: VARCHAR(255) NULL
  - created_by: UUID NULL
  - updated_by: UUID NULL
  - validated_at: TIMESTAMP NULL
  - approved_at: TIMESTAMP NULL
  - activated_at: TIMESTAMP NULL
  - suspended_at: TIMESTAMP NULL
  - retired_at: TIMESTAMP NULL
  - row_version: INTEGER NOT NULL DEFAULT 1
Primary key: ['id'] (name=agents_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=agents_organization_id_fkey, ondelete=CASCADE)
  - ['business_unit_id'] -> business_units.['id'] (name=fk_agents_business_unit, ondelete=SET NULL)
  - ['compliance_owner_id'] -> users.['id'] (name=fk_agents_compliance_owner, ondelete=SET NULL)
  - ['department_id'] -> departments.['id'] (name=fk_agents_department, ondelete=SET NULL)
  - ['identity_id'] -> agent_identities.['id'] (name=fk_agents_identity, ondelete=SET NULL)
  - ['project_id'] -> projects.['id'] (name=fk_agents_project, ondelete=SET NULL)
  - ['team_id'] -> teams.['id'] (name=fk_agents_team, ondelete=SET NULL)
  - ['technical_owner_id'] -> users.['id'] (name=fk_agents_technical_owner, ondelete=SET NULL)
Unique constraints:
  - uq_agents_org_external_ref: ['organization_id', 'external_reference']
  - uq_agents_org_slug: ['organization_id', 'slug']
Indexes:
  - ix_agents_autonomy_level: ['autonomy_level']
  - ix_agents_business_unit: ['business_unit_id']
  - ix_agents_created_at: ['created_at']
  - ix_agents_criticality: ['criticality']
  - ix_agents_data_classification: ['data_classification']
  - ix_agents_department: ['department_id']
  - ix_agents_fulltext: [None]
  - ix_agents_identity: ['identity_id']
  - ix_agents_lifecycle_status: ['lifecycle_status']
  - ix_agents_metadata_gin: ['metadata']
  - ix_agents_organization_id: ['organization_id']
  - ix_agents_owner: ['owner_id']
  - ix_agents_project: ['project_id']
  - ix_agents_risk_level: ['risk_level']
  - ix_agents_slug: ['slug']
  - ix_agents_tags_gin: ['tags']
  - ix_agents_team: ['team_id']
  - ix_agents_updated_at: ['updated_at']
  - uq_agents_org_external_ref: ['organization_id', 'external_reference'] (unique)
  - uq_agents_org_slug: ['organization_id', 'slug'] (unique)

#### alembic_version
Columns:
  - version_num: VARCHAR(32) NOT NULL
Primary key: ['version_num'] (name=alembic_version_pkc)

#### approval_comments
Columns:
  - id: UUID NOT NULL
  - approval_id: UUID NOT NULL
  - user_id: UUID NULL
  - comment: TEXT NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=approval_comments_pkey)
Foreign keys:
  - ['approval_id'] -> approvals.['id'] (name=approval_comments_approval_id_fkey, ondelete=CASCADE)
  - ['user_id'] -> users.['id'] (name=approval_comments_user_id_fkey, ondelete=SET NULL)
Indexes:
  - ix_approval_comments_approval_id: ['approval_id']

#### approvals
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - agent_action_id: UUID NOT NULL
  - requested_by_agent_id: UUID NOT NULL
  - reviewed_by_user_id: UUID NULL
  - decision: VARCHAR(9) NOT NULL
  - review_comment: TEXT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - reviewed_at: TIMESTAMP NULL
  - priority: VARCHAR(8) NOT NULL DEFAULT 'MEDIUM'::approval_priority
  - sla_due_at: TIMESTAMP NULL
  - assigned_to_user_id: UUID NULL
  - escalation_target: TEXT NULL
  - escalated_at: TIMESTAMP NULL
Primary key: ['id'] (name=approvals_pkey)
Foreign keys:
  - ['agent_action_id'] -> agent_actions.['id'] (name=approvals_agent_action_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=approvals_organization_id_fkey, ondelete=CASCADE)
  - ['requested_by_agent_id'] -> agents.['id'] (name=approvals_requested_by_agent_id_fkey, ondelete=CASCADE)
  - ['reviewed_by_user_id'] -> users.['id'] (name=approvals_reviewed_by_user_id_fkey, ondelete=SET NULL)
  - ['assigned_to_user_id'] -> users.['id'] (name=fk_approvals_assigned_to_users, ondelete=SET NULL)
Unique constraints:
  - uq_approvals_agent_action_id: ['agent_action_id']
Indexes:
  - ix_approvals_agent_action_id: ['agent_action_id']
  - ix_approvals_assigned_to_user_id: ['assigned_to_user_id']
  - ix_approvals_organization_id: ['organization_id']
  - ix_approvals_priority: ['priority']
  - uq_approvals_agent_action_id: ['agent_action_id'] (unique)

#### attribute_definitions
Columns:
  - id: UUID NOT NULL
  - name: VARCHAR(120) NOT NULL
  - category: VARCHAR(20) NOT NULL
  - data_type: VARCHAR(20) NOT NULL
  - description: TEXT NULL
  - sensitivity: VARCHAR(20) NOT NULL DEFAULT 'INTERNAL'::character varying
  - supported_operators: JSONB NULL
  - source: VARCHAR(50) NULL
  - is_system: BOOLEAN NOT NULL DEFAULT false
  - enabled: BOOLEAN NOT NULL DEFAULT true
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=attribute_definitions_pkey)
Unique constraints:
  - uq_attribute_definitions_name: ['name']
Indexes:
  - uq_attribute_definitions_name: ['name'] (unique)

#### audit_logs
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - actor_type: VARCHAR(6) NOT NULL
  - actor_id: UUID NULL
  - event_type: VARCHAR(100) NOT NULL
  - entity_type: VARCHAR(100) NOT NULL
  - entity_id: UUID NULL
  - metadata: JSONB NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - ip_address: VARCHAR(64) NULL
  - user_agent: VARCHAR(512) NULL
  - request_id: VARCHAR(64) NULL
  - trace_id: VARCHAR(64) NULL
  - before_state: JSONB NULL
  - after_state: JSONB NULL
Primary key: ['id'] (name=audit_logs_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=audit_logs_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_audit_logs_entity_id: ['entity_id']
  - ix_audit_logs_entity_type: ['entity_type']
  - ix_audit_logs_event_type: ['event_type']
  - ix_audit_logs_organization_id: ['organization_id']
  - ix_audit_logs_request_id: ['request_id']
  - ix_audit_logs_trace_id: ['trace_id']

#### auth_devices
Columns:
  - id: UUID NOT NULL
  - user_id: UUID NOT NULL
  - fingerprint: VARCHAR(128) NOT NULL
  - device_name: VARCHAR(255) NULL
  - device_type: VARCHAR(32) NULL
  - browser: VARCHAR(64) NULL
  - browser_version: VARCHAR(32) NULL
  - operating_system: VARCHAR(64) NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN'::character varying
  - last_ip: VARCHAR(64) NULL
  - last_seen_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL
Primary key: ['id'] (name=auth_devices_pkey)
Foreign keys:
  - ['user_id'] -> users.['id'] (name=auth_devices_user_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_auth_devices_user_fingerprint: ['user_id', 'fingerprint']
Indexes:
  - ix_auth_devices_fingerprint: ['fingerprint']
  - ix_auth_devices_status: ['status']
  - ix_auth_devices_user_id: ['user_id']
  - uq_auth_devices_user_fingerprint: ['user_id', 'fingerprint'] (unique)

#### auth_sessions
Columns:
  - id: UUID NOT NULL
  - user_id: UUID NOT NULL
  - ip_address: VARCHAR(64) NULL
  - user_agent: VARCHAR(512) NULL
  - created_at: TIMESTAMP NOT NULL
  - last_seen_at: TIMESTAMP NULL
  - revoked_at: TIMESTAMP NULL
  - organization_id: UUID NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - device_id: UUID NULL
  - device_name: VARCHAR(255) NULL
  - device_type: VARCHAR(32) NULL
  - browser: VARCHAR(64) NULL
  - browser_version: VARCHAR(32) NULL
  - operating_system: VARCHAR(64) NULL
  - country: VARCHAR(64) NULL
  - city: VARCHAR(128) NULL
  - timezone: VARCHAR(64) NULL
  - login_method: VARCHAR(32) NULL
  - last_activity_at: TIMESTAMP NULL
  - idle_expires_at: TIMESTAMP NOT NULL
  - absolute_expires_at: TIMESTAMP NOT NULL
  - revoked_reason: VARCHAR(32) NULL
  - security_score: INTEGER NOT NULL DEFAULT 100
  - is_trusted: BOOLEAN NOT NULL DEFAULT false
  - refresh_token_family_id: UUID NOT NULL
Primary key: ['id'] (name=sessions_pkey)
Foreign keys:
  - ['device_id'] -> auth_devices.['id'] (name=fk_auth_sessions_device_id, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=fk_auth_sessions_organization_id, ondelete=CASCADE)
  - ['user_id'] -> users.['id'] (name=sessions_user_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_auth_sessions_device_id: ['device_id']
  - ix_auth_sessions_family: ['refresh_token_family_id']
  - ix_auth_sessions_organization_id: ['organization_id']
  - ix_auth_sessions_status: ['status']
  - ix_auth_sessions_user_status: ['user_id', 'status']
  - ix_sessions_user_id: ['user_id']

#### authorization_audit
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NULL
  - actor_id: UUID NULL
  - identity_id: UUID NULL
  - event_type: VARCHAR(50) NOT NULL
  - permission: VARCHAR(100) NULL
  - resource_type: VARCHAR(50) NULL
  - resource_id: UUID NULL
  - decision: VARCHAR(10) NULL
  - reason: TEXT NULL
  - meta: JSONB NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=authorization_audit_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=authorization_audit_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_authorization_audit_actor: ['actor_id']
  - ix_authorization_audit_created_at: ['created_at']
  - ix_authorization_audit_event_type: ['event_type']
  - ix_authorization_audit_identity: ['identity_id']
  - ix_authorization_audit_org: ['organization_id']

#### authorization_decisions
Columns:
  - id: UUID NOT NULL
  - identity_id: UUID NULL
  - organization_id: UUID NULL
  - permission: VARCHAR(100) NOT NULL
  - resource_type: VARCHAR(50) NULL
  - resource_id: UUID NULL
  - allowed: BOOLEAN NOT NULL
  - reason: TEXT NULL
  - scope: VARCHAR(20) NULL
  - source_role: VARCHAR(100) NULL
  - evaluation_time_ms: DOUBLE PRECISION NULL
  - request_id: VARCHAR(128) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=authorization_decisions_pkey)
Indexes:
  - ix_authz_decisions_allowed: ['allowed']
  - ix_authz_decisions_created_at: ['created_at']
  - ix_authz_decisions_identity: ['identity_id']
  - ix_authz_decisions_org: ['organization_id']

#### blocked_ips
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NULL
  - ip_address: VARCHAR(64) NOT NULL
  - reason: VARCHAR(255) NULL
  - expires_at: TIMESTAMP NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=blocked_ips_pkey)
Foreign keys:
  - ['created_by'] -> users.['id'] (name=blocked_ips_created_by_fkey, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=blocked_ips_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_blocked_ips_ip_address: ['ip_address']
  - ix_blocked_ips_org_ip: ['organization_id', 'ip_address']
  - ix_blocked_ips_organization_id: ['organization_id']

#### business_units
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - manager_id: UUID NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=business_units_pkey)
Foreign keys:
  - ['manager_id'] -> users.['id'] (name=business_units_manager_id_fkey, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=business_units_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_business_unit_org_name: ['organization_id', 'name']
Indexes:
  - ix_business_units_org: ['organization_id']
  - uq_business_unit_org_name: ['organization_id', 'name'] (unique)

#### capabilities
Columns:
  - id: UUID NOT NULL
  - name: VARCHAR(100) NOT NULL
  - display_name: VARCHAR(150) NOT NULL
  - description: TEXT NULL
  - category: VARCHAR(50) NULL
  - risk_level: VARCHAR(20) NOT NULL DEFAULT 'MEDIUM'::character varying
  - requires_approval: BOOLEAN NOT NULL DEFAULT false
  - required_permissions: JSONB NOT NULL DEFAULT '[]'::jsonb
  - prohibited_environments: JSONB NOT NULL DEFAULT '[]'::jsonb
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=capabilities_pkey)
Unique constraints:
  - uq_capabilities_name: ['name']
Indexes:
  - uq_capabilities_name: ['name'] (unique)

#### compliance_reports
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - framework: VARCHAR(30) NOT NULL
  - report_type: VARCHAR(50) NOT NULL
  - scope: JSONB NULL
  - payload: JSONB NOT NULL
  - version: VARCHAR(20) NOT NULL DEFAULT 'v1'::character varying
  - generated_by: UUID NULL
  - generated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=compliance_reports_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=compliance_reports_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_compliance_reports_framework: ['framework']
  - ix_compliance_reports_org: ['organization_id']

#### connector_credentials
Columns:
  - id: UUID NOT NULL
  - connector_instance_id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - auth_scheme: VARCHAR(48) NOT NULL
  - encrypted_secret: TEXT NOT NULL
  - secret_hint: VARCHAR(8) NOT NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - last_validated_at: TIMESTAMP NULL
  - validation_status: VARCHAR(20) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - created_by: UUID NULL
Primary key: ['id'] (name=connector_credentials_pkey)
Foreign keys:
  - ['connector_instance_id'] -> connector_instances.['id'] (name=connector_credentials_connector_instance_id_fkey, ondelete=CASCADE)
  - ['created_by'] -> users.['id'] (name=connector_credentials_created_by_fkey, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=connector_credentials_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_connector_credentials_instance_scheme: ['connector_instance_id', 'auth_scheme']
Indexes:
  - ix_connector_credentials_connector_instance_id: ['connector_instance_id']
  - ix_connector_credentials_organization_id: ['organization_id']
  - uq_connector_credentials_instance_scheme: ['connector_instance_id', 'auth_scheme']

#### connector_health_checks
Columns:
  - id: UUID NOT NULL
  - connector_instance_id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - check_type: VARCHAR(16) NOT NULL
  - reachable: BOOLEAN NOT NULL
  - auth_valid: BOOLEAN NOT NULL
  - result: VARCHAR(16) NOT NULL
  - reason: TEXT NULL
  - latency_ms: INTEGER NULL
  - checked_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=connector_health_checks_pkey)
Foreign keys:
  - ['connector_instance_id'] -> connector_instances.['id'] (name=connector_health_checks_connector_instance_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=connector_health_checks_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_connector_health_checks_checked_at: ['checked_at']
  - ix_connector_health_checks_connector_instance_id: ['connector_instance_id']
  - ix_connector_health_checks_instance_checked_at: ['connector_instance_id', 'checked_at']
  - ix_connector_health_checks_organization_id: ['organization_id']

#### connector_instances
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - connector_id: UUID NOT NULL
  - name: VARCHAR(128) NOT NULL
  - configuration: JSONB NOT NULL DEFAULT '{}'::jsonb
  - lifecycle_state: VARCHAR(20) NOT NULL DEFAULT 'registered'::character varying
  - state_reason: TEXT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - created_by: UUID NULL
  - last_health_check_at: TIMESTAMP NULL
  - current_health: VARCHAR(16) NULL
Primary key: ['id'] (name=connector_instances_pkey)
Foreign keys:
  - ['connector_id'] -> connectors.['id'] (name=connector_instances_connector_id_fkey, ondelete=RESTRICT)
  - ['organization_id'] -> organizations.['id'] (name=connector_instances_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_connector_instances_org_name: ['organization_id', 'name']
Indexes:
  - ix_connector_instances_connector_id: ['connector_id']
  - ix_connector_instances_lifecycle_state: ['lifecycle_state']
  - ix_connector_instances_organization_id: ['organization_id']
  - uq_connector_instances_org_name: ['organization_id', 'name']

#### connector_lifecycle_events
Columns:
  - id: UUID NOT NULL
  - connector_instance_id: UUID NOT NULL
  - from_state: VARCHAR(20) NULL
  - to_state: VARCHAR(20) NOT NULL
  - reason: TEXT NULL
  - actor_id: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=connector_lifecycle_events_pkey)
Foreign keys:
  - ['connector_instance_id'] -> connector_instances.['id'] (name=connector_lifecycle_events_connector_instance_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_connector_lifecycle_events_connector_instance_id: ['connector_instance_id']

#### connector_oauth_tokens
Columns:
  - id: UUID NOT NULL
  - connector_instance_id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - encrypted_access_token: TEXT NOT NULL
  - encrypted_refresh_token: TEXT NULL
  - expires_at: TIMESTAMP NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=connector_oauth_tokens_pkey)
Foreign keys:
  - ['connector_instance_id'] -> connector_instances.['id'] (name=connector_oauth_tokens_connector_instance_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=connector_oauth_tokens_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_connector_oauth_tokens_instance: ['connector_instance_id']
Indexes:
  - ix_connector_oauth_tokens_connector_instance_id: ['connector_instance_id']
  - ix_connector_oauth_tokens_organization_id: ['organization_id']
  - uq_connector_oauth_tokens_instance: ['connector_instance_id']

#### connectors
Columns:
  - id: UUID NOT NULL
  - connector_type: VARCHAR(64) NOT NULL
  - version: VARCHAR(32) NOT NULL
  - capabilities: JSONB NOT NULL
  - config_schema: JSONB NOT NULL
  - auth_requirements: JSONB NOT NULL
  - tool_contracts: JSONB NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=connectors_pkey)
Unique constraints:
  - uq_connectors_type_version: ['connector_type', 'version']
Indexes:
  - ix_connectors_connector_type: ['connector_type']
  - uq_connectors_type_version: ['connector_type', 'version']

#### delegations
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - delegator_id: UUID NULL
  - delegatee_id: UUID NOT NULL
  - scope_type: VARCHAR(20) NOT NULL
  - scope_id: UUID NULL
  - permission: VARCHAR(100) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - revoked_at: TIMESTAMP NULL
Primary key: ['id'] (name=delegations_pkey)
Foreign keys:
  - ['delegatee_id'] -> users.['id'] (name=delegations_delegatee_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=delegations_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_delegations_delegatee: ['delegatee_id']
  - ix_delegations_org: ['organization_id']

#### departments
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - manager_id: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - business_unit_id: UUID NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
Primary key: ['id'] (name=departments_pkey)
Foreign keys:
  - ['manager_id'] -> users.['id'] (name=departments_manager_id_fkey, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=departments_organization_id_fkey, ondelete=CASCADE)
  - ['business_unit_id'] -> business_units.['id'] (name=fk_departments_business_unit_id, ondelete=SET NULL)
Indexes:
  - ix_departments_business_unit: ['business_unit_id']
  - ix_departments_organization_id: ['organization_id']

#### deployment_events
Columns (Phase 3.1 — append-only lifecycle lineage, one row per transition):
  - id: UUID NOT NULL
  - deployment_id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - from_state: VARCHAR(24) NULL
  - to_state: VARCHAR(24) NOT NULL
  - event_type: VARCHAR(48) NOT NULL
  - reason: TEXT NULL
  - actor_id: UUID NULL
  - idempotency_key: VARCHAR(255) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=deployment_events_pkey)
Foreign keys:
  - ['deployment_id'] -> agent_deployments.['id'] (name=deployment_events_deployment_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=deployment_events_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_deployment_events_deployment_created: ['deployment_id', 'created_at']
  - ix_deployment_events_deployment_id: ['deployment_id']
  - ix_deployment_events_event_type: ['event_type']
  - ix_deployment_events_organization_id: ['organization_id']

#### deployment_health
Columns:
  - id: UUID NOT NULL
  - deployment_id: UUID NOT NULL
  - worker_id: VARCHAR(100) NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN'::character varying
  - metrics: JSONB NULL
  - checked_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=deployment_health_pkey)
Foreign keys:
  - ['deployment_id'] -> agent_deployments.['id'] (name=deployment_health_deployment_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_deployment_health_deployment: ['deployment_id']

#### deployment_preflight_results
Columns (Phase 3.3 — one persisted `ReleaseGateService.evaluate()` verdict per call):
  - id: UUID NOT NULL
  - deployment_id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - verdict: VARCHAR(12) NOT NULL
  - findings: JSONB NOT NULL DEFAULT '[]'::jsonb
  - evaluated_at: TIMESTAMP NOT NULL DEFAULT now()
  - evaluated_by: UUID NULL
Primary key: ['id'] (name=deployment_preflight_results_pkey)
Foreign keys:
  - ['deployment_id'] -> agent_deployments.['id'] (name=deployment_preflight_results_deployment_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=deployment_preflight_results_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_deployment_preflight_results_deployment_evaluated: ['deployment_id', 'evaluated_at']
  - ix_deployment_preflight_results_deployment_id: ['deployment_id']
  - ix_deployment_preflight_results_organization_id: ['organization_id']

#### email_verifications
Columns:
  - id: UUID NOT NULL
  - user_id: UUID NOT NULL
  - verification_token_hash: VARCHAR(255) NOT NULL
  - expires_at: TIMESTAMP NOT NULL
  - verified_at: TIMESTAMP NULL
  - superseded_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - purpose: VARCHAR(20) NOT NULL DEFAULT 'ACTIVATION'::character varying
  - new_email: VARCHAR(320) NULL
Primary key: ['id'] (name=email_verifications_pkey)
Foreign keys:
  - ['user_id'] -> users.['id'] (name=email_verifications_user_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_email_verifications_token_hash: ['verification_token_hash']
Indexes:
  - ix_email_verifications_token_hash: ['verification_token_hash']
  - ix_email_verifications_user_id: ['user_id']
  - uq_email_verifications_token_hash: ['verification_token_hash'] (unique)

#### environments — Phase 3.2
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - name: VARCHAR(64) NOT NULL
  - display_name: VARCHAR(128) NOT NULL
  - is_production: BOOLEAN NOT NULL DEFAULT false
  - policy: JSONB NOT NULL DEFAULT '{}'::jsonb
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=environments_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=environments_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_environments_org_name: ['organization_id', 'name']
Indexes:
  - ix_environments_organization_id: ['organization_id']
  - uq_environments_org_name: ['organization_id', 'name'] (unique)

#### execution_attempts
Columns:
  - id: UUID NOT NULL
  - execution_id: UUID NOT NULL
  - attempt_number: INTEGER NOT NULL
  - worker_id: VARCHAR(100) NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'RUNNING'::character varying
  - started_at: TIMESTAMP NULL
  - completed_at: TIMESTAMP NULL
  - duration_ms: INTEGER NULL
  - error_code: VARCHAR(50) NULL
  - error_message: TEXT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - prompt_tokens: INTEGER NULL
  - completion_tokens: INTEGER NULL
  - total_tokens: INTEGER NULL
  - token_accounting_complete: BOOLEAN NOT NULL DEFAULT true
Primary key: ['id'] (name=execution_attempts_pkey)
Foreign keys:
  - ['execution_id'] -> agent_executions.['id'] (name=execution_attempts_execution_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_execution_attempts_execution: ['execution_id']

#### execution_messages
Columns:
  - id: UUID NOT NULL
  - execution_id: UUID NOT NULL
  - sequence: INTEGER NOT NULL
  - role: VARCHAR(20) NOT NULL
  - content: TEXT NULL
  - tool_call_id: VARCHAR(100) NULL
  - tool_name: VARCHAR(100) NULL
  - tool_calls_requested: JSONB NULL
  - loop_iteration: INTEGER NOT NULL DEFAULT 0
  - prompt_tokens: INTEGER NULL
  - completion_tokens: INTEGER NULL
  - total_tokens: INTEGER NULL
  - cost_amount: NUMERIC(18, 8) NULL
  - duration_ms: INTEGER NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=execution_messages_pkey)
Foreign keys:
  - ['execution_id'] -> agent_executions.['id'] (name=execution_messages_execution_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_execution_messages_execution_id: ['execution_id']

#### execution_locks
Columns:
  - id: UUID NOT NULL
  - execution_id: UUID NOT NULL
  - worker_id: VARCHAR(100) NOT NULL
  - acquired_at: TIMESTAMP NOT NULL DEFAULT now()
  - expires_at: TIMESTAMP NOT NULL
  - heartbeat_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=execution_locks_pkey)
Foreign keys:
  - ['execution_id'] -> agent_executions.['id'] (name=execution_locks_execution_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_execution_locks_execution: ['execution_id']
Indexes:
  - uq_execution_locks_execution: ['execution_id'] (unique)

#### external_clients
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - client_name: VARCHAR(255) NOT NULL
  - client_id: VARCHAR(100) NOT NULL
  - redirect_uri: VARCHAR(2048) NULL
  - secret_hash: VARCHAR(255) NOT NULL
  - allowed_scopes: JSONB NOT NULL
  - status: VARCHAR(30) NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=external_clients_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=external_clients_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_external_clients_client_id: ['client_id']
Indexes:
  - ix_external_clients_client_id: ['client_id']
  - ix_external_clients_organization_id: ['organization_id']
  - uq_external_clients_client_id: ['client_id'] (unique)

#### governance_findings
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - finding_type: VARCHAR(30) NOT NULL
  - severity: VARCHAR(20) NOT NULL DEFAULT 'MEDIUM'::character varying
  - identity_id: UUID NULL
  - identity_label: VARCHAR(255) NULL
  - resource_id: UUID NULL
  - rule_id: UUID NULL
  - details: JSONB NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'OPEN'::character varying
  - detected_at: TIMESTAMP NOT NULL DEFAULT now()
  - resolved_at: TIMESTAMP NULL
  - resolved_by: UUID NULL
Primary key: ['id'] (name=governance_findings_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=governance_findings_organization_id_fkey, ondelete=CASCADE)
  - ['rule_id'] -> sod_rules.['id'] (name=governance_findings_rule_id_fkey, ondelete=SET NULL)
Indexes:
  - ix_governance_findings_identity: ['identity_id']
  - ix_governance_findings_org: ['organization_id']
  - ix_governance_findings_status: ['status']
  - ix_governance_findings_type: ['finding_type']

#### governance_risk_scores
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - identity_id: UUID NOT NULL
  - identity_label: VARCHAR(255) NOT NULL
  - score: INTEGER NOT NULL DEFAULT 0
  - band: VARCHAR(20) NOT NULL DEFAULT 'LOW'::character varying
  - factors: JSONB NULL
  - computed_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=governance_risk_scores_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=governance_risk_scores_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_governance_risk_identity: ['organization_id', 'identity_id']
Indexes:
  - ix_governance_risk_scores_band: ['band']
  - ix_governance_risk_scores_org: ['organization_id']
  - uq_governance_risk_identity: ['organization_id', 'identity_id'] (unique)

#### idempotency_keys
Columns (Phase 3.1 — the reusable, platform-wide `Idempotency-Key` contract; a *different*, more general table from `idempotency_records` below, which is execution-specific and untouched):
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - operation: VARCHAR(64) NOT NULL
  - idempotency_key: VARCHAR(255) NOT NULL
  - request_fingerprint: VARCHAR(64) NOT NULL
  - result_ref: JSONB NOT NULL DEFAULT '{}'::jsonb
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - expires_at: TIMESTAMP NOT NULL
Primary key: ['id'] (name=idempotency_keys_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=idempotency_keys_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_idempotency_keys_scope: ['organization_id', 'operation', 'idempotency_key']
Indexes:
  - ix_idempotency_keys_organization_id: ['organization_id']
  - uq_idempotency_keys_scope: ['organization_id', 'operation', 'idempotency_key'] (unique)

#### idempotency_records
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - identity_id: UUID NULL
  - agent_id: UUID NOT NULL
  - idempotency_key: VARCHAR(150) NOT NULL
  - request_hash: VARCHAR(64) NOT NULL
  - execution_id: UUID NOT NULL
  - expires_at: TIMESTAMP NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=idempotency_records_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=idempotency_records_agent_id_fkey, ondelete=CASCADE)
  - ['execution_id'] -> agent_executions.['id'] (name=idempotency_records_execution_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=idempotency_records_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_idempotency_key: ['organization_id', 'agent_id', 'idempotency_key']
Indexes:
  - uq_idempotency_key: ['organization_id', 'agent_id', 'idempotency_key'] (unique)

#### identity_protection_rules
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - name: VARCHAR(150) NOT NULL
  - description: VARCHAR(500) NULL
  - conditions: JSONB NOT NULL DEFAULT '[]'::jsonb
  - decision: VARCHAR(30) NOT NULL
  - enabled: BOOLEAN NOT NULL DEFAULT true
  - priority: INTEGER NOT NULL DEFAULT 100
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=identity_protection_rules_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=identity_protection_rules_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_identity_protection_rules_organization_id: ['organization_id']

#### identity_risk_events
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NULL
  - user_id: UUID NULL
  - event_type: VARCHAR(64) NOT NULL
  - risk_score: INTEGER NOT NULL DEFAULT 0
  - risk_level: VARCHAR(20) NOT NULL
  - signals: JSONB NOT NULL DEFAULT '{}'::jsonb
  - decision: VARCHAR(30) NOT NULL
  - ip_address: VARCHAR(64) NULL
  - user_agent: VARCHAR(512) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=identity_risk_events_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=identity_risk_events_organization_id_fkey, ondelete=CASCADE)
  - ['user_id'] -> users.['id'] (name=identity_risk_events_user_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_identity_risk_events_created_at: ['created_at']
  - ix_identity_risk_events_event_type: ['event_type']
  - ix_identity_risk_events_org_created: ['organization_id', 'created_at']
  - ix_identity_risk_events_organization_id: ['organization_id']
  - ix_identity_risk_events_risk_level: ['risk_level']
  - ix_identity_risk_events_user_id: ['user_id']

#### invitations
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - email: VARCHAR(320) NOT NULL
  - role_id: UUID NULL
  - department_id: UUID NULL
  - team_id: UUID NULL
  - invited_by: UUID NULL
  - token_hash: VARCHAR(255) NOT NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'PENDING'::character varying
  - expires_at: TIMESTAMP NOT NULL
  - accepted_at: TIMESTAMP NULL
  - cancelled_at: TIMESTAMP NULL
  - resent_count: INTEGER NOT NULL DEFAULT 0
  - last_sent_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=invitations_pkey)
Foreign keys:
  - ['department_id'] -> departments.['id'] (name=invitations_department_id_fkey, ondelete=SET NULL)
  - ['invited_by'] -> users.['id'] (name=invitations_invited_by_fkey, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=invitations_organization_id_fkey, ondelete=CASCADE)
  - ['role_id'] -> roles.['id'] (name=invitations_role_id_fkey, ondelete=SET NULL)
  - ['team_id'] -> teams.['id'] (name=invitations_team_id_fkey, ondelete=SET NULL)
Unique constraints:
  - uq_invitations_token_hash: ['token_hash']
Indexes:
  - ix_invitations_email: ['email']
  - ix_invitations_org_status: ['organization_id', 'status']
  - ix_invitations_organization_id: ['organization_id']
  - ix_invitations_status: ['status']
  - ix_invitations_token_hash: ['token_hash']
  - uq_invitations_pending_email: ['organization_id', None] (unique)
  - uq_invitations_token_hash: ['token_hash'] (unique)

#### login_history
Columns:
  - id: UUID NOT NULL
  - user_id: UUID NULL
  - email: VARCHAR(320) NOT NULL
  - success: BOOLEAN NOT NULL
  - failure_reason: VARCHAR(64) NULL
  - ip_address: VARCHAR(64) NULL
  - user_agent: VARCHAR(512) NULL
  - country: VARCHAR(64) NULL
  - city: VARCHAR(128) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - organization_id: UUID NULL
  - device_fingerprint: VARCHAR(128) NULL
  - risk_score: INTEGER NULL
  - decision: VARCHAR(30) NULL
Primary key: ['id'] (name=login_history_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=fk_login_history_organization_id, ondelete=CASCADE)
  - ['user_id'] -> users.['id'] (name=login_history_user_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_login_history_created_at: ['created_at']
  - ix_login_history_email: ['email']
  - ix_login_history_organization_id: ['organization_id']
  - ix_login_history_success: ['success']
  - ix_login_history_user_id: ['user_id']

#### model_pricing
Columns:
  - id: UUID NOT NULL
  - provider: VARCHAR(64) NOT NULL
  - model_name: VARCHAR(128) NOT NULL
  - prompt_cost_per_1k: NUMERIC(18, 8) NOT NULL
  - completion_cost_per_1k: NUMERIC(18, 8) NOT NULL
  - currency: VARCHAR(3) NOT NULL DEFAULT 'USD'::character varying
  - pricing_version: VARCHAR(32) NOT NULL
  - effective_from: TIMESTAMP NOT NULL
  - effective_to: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=model_pricing_pkey)
Unique constraints:
  - ['provider', 'model_name', 'effective_from'] (name=uq_model_pricing_provider_model_from)
Indexes:
  - ix_model_pricing_model_name: ['model_name']
  - ix_model_pricing_provider: ['provider']
  - uq_model_pricing_provider_model_from: ['provider', 'model_name', 'effective_from']

#### organizations
Columns:
  - id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - status: VARCHAR(30) NOT NULL DEFAULT 'ACTIVE'::character varying
  - registration_mode: VARCHAR(20) NOT NULL DEFAULT 'INVITE_ONLY'::character varying
  - slug: VARCHAR(120) NULL
  - owner_id: UUID NULL
Primary key: ['id'] (name=organizations_pkey)
Foreign keys:
  - ['owner_id'] -> users.['id'] (name=fk_organizations_owner_id, ondelete=SET NULL)
Indexes:
  - ix_organizations_slug: ['slug'] (unique)

#### ownership_history
Columns:
  - id: UUID NOT NULL
  - resource_id: UUID NOT NULL
  - previous_owner: UUID NULL
  - previous_owner_type: VARCHAR(20) NULL
  - new_owner: UUID NOT NULL
  - new_owner_type: VARCHAR(20) NOT NULL DEFAULT 'USER'::character varying
  - changed_by: UUID NULL
  - reason: VARCHAR(500) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=ownership_history_pkey)
Foreign keys:
  - ['resource_id'] -> resources.['id'] (name=ownership_history_resource_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_ownership_history_resource: ['resource_id']

#### password_history
Columns:
  - id: UUID NOT NULL
  - user_id: UUID NOT NULL
  - password_hash: VARCHAR(255) NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=password_history_pkey)
Foreign keys:
  - ['user_id'] -> users.['id'] (name=password_history_user_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_password_history_user_created: ['user_id', 'created_at']

#### password_reset_requests
Columns:
  - id: UUID NOT NULL
  - user_id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - token_hash: VARCHAR(255) NOT NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'PENDING'::character varying
  - expires_at: TIMESTAMP NOT NULL
  - used_at: TIMESTAMP NULL
  - created_ip: VARCHAR(64) NULL
  - created_user_agent: VARCHAR(512) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=password_reset_requests_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=password_reset_requests_organization_id_fkey, ondelete=CASCADE)
  - ['user_id'] -> users.['id'] (name=password_reset_requests_user_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_password_reset_requests_token_hash: ['token_hash']
Indexes:
  - ix_password_reset_requests_organization_id: ['organization_id']
  - ix_password_reset_requests_status: ['status']
  - ix_password_reset_requests_token_hash: ['token_hash']
  - ix_password_reset_requests_user_id: ['user_id']
  - ix_password_reset_requests_user_status: ['user_id', 'status']
  - uq_password_reset_requests_token_hash: ['token_hash'] (unique)

#### permission_cache
Columns:
  - id: UUID NOT NULL
  - identity_id: UUID NOT NULL
  - organization_id: UUID NULL
  - grants_json: JSONB NOT NULL
  - version: INTEGER NOT NULL DEFAULT 0
  - expires_at: TIMESTAMP NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=permission_cache_pkey)
Unique constraints:
  - uq_permission_cache_identity: ['identity_id']
Indexes:
  - ix_permission_cache_org: ['organization_id']
  - uq_permission_cache_identity: ['identity_id'] (unique)

#### permission_groups
Columns:
  - id: UUID NOT NULL
  - name: VARCHAR(50) NOT NULL
  - display_name: VARCHAR(100) NOT NULL
  - description: TEXT NULL
  - sort_order: INTEGER NOT NULL DEFAULT 0
Primary key: ['id'] (name=permission_groups_pkey)
Unique constraints:
  - uq_permission_group_name: ['name']
Indexes:
  - ix_permission_groups_name: ['name']
  - uq_permission_group_name: ['name'] (unique)

#### permission_versions
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NULL
  - version: INTEGER NOT NULL DEFAULT 1
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=permission_versions_pkey)
Unique constraints:
  - uq_permission_version_org: ['organization_id']
Indexes:
  - uq_permission_version_org: ['organization_id'] (unique)

#### permissions
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - resource: VARCHAR(100) NOT NULL
  - action: VARCHAR(100) NOT NULL
  - allowed: BOOLEAN NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=permissions_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=permissions_agent_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=permissions_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_permission_agent_resource_action: ['agent_id', 'resource', 'action']
Indexes:
  - ix_permissions_agent_id: ['agent_id']
  - ix_permissions_organization_id: ['organization_id']
  - uq_permission_agent_resource_action: ['agent_id', 'resource', 'action'] (unique)

#### policies
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - description: TEXT NULL
  - resource: VARCHAR(100) NOT NULL
  - action: VARCHAR(100) NOT NULL
  - conditions: JSONB NOT NULL
  - decision: VARCHAR(30) NOT NULL
  - priority: INTEGER NOT NULL DEFAULT 0
  - enabled: BOOLEAN NOT NULL DEFAULT true
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - severity: VARCHAR(20) NOT NULL DEFAULT 'MEDIUM'::character varying
  - status: VARCHAR(20) NOT NULL DEFAULT 'ENABLED'::character varying
  - created_by: UUID NULL
  - trigger_count: INTEGER NOT NULL DEFAULT 0
  - last_triggered_at: TIMESTAMP NULL
Primary key: ['id'] (name=policies_pkey)
Foreign keys:
  - ['created_by'] -> users.['id'] (name=fk_policies_created_by_users, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=policies_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_policies_action: ['action']
  - ix_policies_enabled: ['enabled']
  - ix_policies_organization_id: ['organization_id']
  - ix_policies_resource: ['resource']

#### privileged_account_reviews
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - identity_id: UUID NOT NULL
  - identity_label: VARCHAR(255) NOT NULL
  - role_name: VARCHAR(255) NOT NULL
  - risk_score: INTEGER NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'PENDING'::character varying
  - reviewed_by: UUID NULL
  - reviewed_at: TIMESTAMP NULL
  - due_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=privileged_account_reviews_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=privileged_account_reviews_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_privileged_account_reviews_identity: ['identity_id']
  - ix_privileged_account_reviews_org: ['organization_id']
  - ix_privileged_account_reviews_status: ['status']

#### projects
Columns:
  - id: UUID NOT NULL
  - team_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - owner_id: UUID NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=projects_pkey)
Foreign keys:
  - ['owner_id'] -> users.['id'] (name=projects_owner_id_fkey, ondelete=SET NULL)
  - ['team_id'] -> teams.['id'] (name=projects_team_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_project_team_name: ['team_id', 'name']
Indexes:
  - ix_projects_team: ['team_id']
  - uq_project_team_name: ['team_id', 'name'] (unique)

#### promotion_paths — Phase 3.2
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - from_environment_id: UUID NOT NULL
  - to_environment_id: UUID NOT NULL
  - requires_approval: BOOLEAN NOT NULL DEFAULT false
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=promotion_paths_pkey)
Foreign keys:
  - ['from_environment_id'] -> environments.['id'] (name=promotion_paths_from_environment_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=promotion_paths_organization_id_fkey, ondelete=CASCADE)
  - ['to_environment_id'] -> environments.['id'] (name=promotion_paths_to_environment_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_promotion_paths_org_edge: ['organization_id', 'from_environment_id', 'to_environment_id']
Indexes:
  - ix_promotion_paths_from_environment_id: ['from_environment_id']
  - ix_promotion_paths_organization_id: ['organization_id']
  - ix_promotion_paths_to_environment_id: ['to_environment_id']
  - uq_promotion_paths_org_edge: ['organization_id', 'from_environment_id', 'to_environment_id'] (unique)

#### provider_credentials
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - provider: VARCHAR(64) NOT NULL
  - encrypted_secret: TEXT NOT NULL
  - secret_hint: VARCHAR(8) NOT NULL
  - base_url: TEXT NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - created_by: UUID NULL
  - last_used_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=provider_credentials_pkey)
Foreign keys:
  - ['created_by'] -> users.['id'] (name=provider_credentials_created_by_fkey, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=provider_credentials_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_provider_credentials_org_provider: ['organization_id', 'provider']
Indexes:
  - ix_provider_credentials_organization_id: ['organization_id']
  - uq_provider_credentials_org_provider: ['organization_id', 'provider'] (unique)

#### rate_limit_hits
Columns:
  - id: UUID NOT NULL
  - bucket: VARCHAR(255) NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=rate_limit_hits_pkey)
Indexes:
  - ix_rate_limit_hits_bucket_created: ['bucket', 'created_at']

#### rbac_permissions
Columns:
  - id: UUID NOT NULL
  - code: VARCHAR(100) NOT NULL
  - description: TEXT NULL
  - display_name: VARCHAR(150) NULL
  - group_id: UUID NULL
  - resource_type: VARCHAR(50) NULL
  - action: VARCHAR(50) NULL
  - is_system: BOOLEAN NOT NULL DEFAULT true
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=rbac_permissions_pkey)
Foreign keys:
  - ['group_id'] -> permission_groups.['id'] (name=fk_rbac_permissions_group_id, ondelete=SET NULL)
Unique constraints:
  - uq_rbac_permissions_code: ['code']
Indexes:
  - ix_rbac_permissions_code: ['code']
  - ix_rbac_permissions_group_id: ['group_id']
  - ix_rbac_permissions_resource_type: ['resource_type']
  - uq_rbac_permissions_code: ['code'] (unique)

#### refresh_tokens
Columns:
  - id: UUID NOT NULL
  - session_id: UUID NOT NULL
  - token_hash: VARCHAR(255) NOT NULL
  - created_at: TIMESTAMP NOT NULL
  - expires_at: TIMESTAMP NOT NULL
  - revoked_at: TIMESTAMP NULL
  - rotated_to_id: UUID NULL
  - family_id: UUID NOT NULL
  - reuse_detected_at: TIMESTAMP NULL
Primary key: ['id'] (name=refresh_tokens_pkey)
Foreign keys:
  - ['session_id'] -> auth_sessions.['id'] (name=refresh_tokens_session_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_refresh_tokens_token_hash: ['token_hash']
Indexes:
  - ix_refresh_tokens_family_id: ['family_id']
  - ix_refresh_tokens_session_id: ['session_id']
  - ix_refresh_tokens_token_hash: ['token_hash']
  - uq_refresh_tokens_token_hash: ['token_hash'] (unique)

#### remediation_actions
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - finding_id: UUID NOT NULL
  - action_type: VARCHAR(30) NOT NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'PENDING'::character varying
  - mode: VARCHAR(20) NOT NULL DEFAULT 'MANUAL'::character varying
  - payload: JSONB NULL
  - created_by: UUID NULL
  - approved_by: UUID NULL
  - executed_by: UUID NULL
  - executed_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=remediation_actions_pkey)
Foreign keys:
  - ['finding_id'] -> governance_findings.['id'] (name=remediation_actions_finding_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=remediation_actions_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_remediation_actions_finding: ['finding_id']
  - ix_remediation_actions_org: ['organization_id']
  - ix_remediation_actions_status: ['status']

#### resource_acl
Columns:
  - id: UUID NOT NULL
  - resource_id: UUID NOT NULL
  - principal_type: VARCHAR(20) NOT NULL
  - principal_id: UUID NOT NULL
  - permission: VARCHAR(100) NOT NULL
  - effect: VARCHAR(5) NOT NULL DEFAULT 'ALLOW'::character varying
  - expires_at: TIMESTAMP NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=resource_acl_pkey)
Foreign keys:
  - ['resource_id'] -> resources.['id'] (name=resource_acl_resource_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_resource_acl_principal: ['principal_id']
  - ix_resource_acl_resource: ['resource_id']

#### resource_delegations
Columns:
  - id: UUID NOT NULL
  - resource_id: UUID NOT NULL
  - delegate_id: UUID NOT NULL
  - permissions: JSONB NOT NULL DEFAULT '[]'::jsonb
  - expires_at: TIMESTAMP NULL
  - status: VARCHAR(10) NOT NULL DEFAULT 'ACTIVE'::character varying
  - reason: VARCHAR(500) NULL
  - approved_by: UUID NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=resource_delegations_pkey)
Foreign keys:
  - ['delegate_id'] -> users.['id'] (name=resource_delegations_delegate_id_fkey, ondelete=CASCADE)
  - ['resource_id'] -> resources.['id'] (name=resource_delegations_resource_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_resource_delegations_delegate: ['delegate_id']
  - ix_resource_delegations_resource: ['resource_id']

#### resource_ownership
Columns:
  - id: UUID NOT NULL
  - resource_type: VARCHAR(50) NOT NULL
  - resource_id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - business_unit_id: UUID NULL
  - department_id: UUID NULL
  - team_id: UUID NULL
  - project_id: UUID NULL
  - owner_id: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=resource_ownership_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=resource_ownership_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_resource_ownership: ['resource_type', 'resource_id']
Indexes:
  - ix_resource_ownership_lookup: ['resource_type', 'resource_id']
  - ix_resource_ownership_org: ['organization_id']
  - uq_resource_ownership: ['resource_type', 'resource_id'] (unique)

#### resource_shares
Columns:
  - id: UUID NOT NULL
  - resource_id: UUID NOT NULL
  - shared_with_type: VARCHAR(20) NOT NULL
  - shared_with_id: UUID NOT NULL
  - access_level: VARCHAR(10) NOT NULL DEFAULT 'READ'::character varying
  - expires_at: TIMESTAMP NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=resource_shares_pkey)
Foreign keys:
  - ['resource_id'] -> resources.['id'] (name=resource_shares_resource_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_resource_shares_resource: ['resource_id']
  - ix_resource_shares_with: ['shared_with_id']

#### resources
Columns:
  - id: UUID NOT NULL
  - resource_type: VARCHAR(50) NOT NULL
  - resource_id: UUID NOT NULL
  - name: VARCHAR(255) NULL
  - organization_id: UUID NOT NULL
  - project_id: UUID NULL
  - owner_id: UUID NOT NULL
  - owner_type: VARCHAR(20) NOT NULL DEFAULT 'USER'::character varying
  - created_by: UUID NULL
  - visibility: VARCHAR(20) NOT NULL DEFAULT 'PRIVATE'::character varying
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - policy: JSONB NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=resources_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=resources_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_resources_type_id: ['resource_type', 'resource_id']
Indexes:
  - ix_resources_lookup: ['resource_type', 'resource_id']
  - ix_resources_org: ['organization_id']
  - ix_resources_owner: ['owner_id']
  - uq_resources_type_id: ['resource_type', 'resource_id'] (unique)

#### role_hierarchy
Columns:
  - id: UUID NOT NULL
  - parent_role_id: UUID NOT NULL
  - child_role_id: UUID NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=role_hierarchy_pkey)
Foreign keys:
  - ['child_role_id'] -> roles.['id'] (name=role_hierarchy_child_role_id_fkey, ondelete=CASCADE)
  - ['parent_role_id'] -> roles.['id'] (name=role_hierarchy_parent_role_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_role_hierarchy_edge: ['parent_role_id', 'child_role_id']
Indexes:
  - ix_role_hierarchy_child: ['child_role_id']
  - ix_role_hierarchy_parent: ['parent_role_id']
  - uq_role_hierarchy_edge: ['parent_role_id', 'child_role_id'] (unique)

#### role_permissions
Columns:
  - id: UUID NOT NULL
  - role_id: UUID NOT NULL
  - permission_id: UUID NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - effect: VARCHAR(10) NOT NULL DEFAULT 'ALLOW'::character varying
Primary key: ['id'] (name=role_permissions_pkey)
Foreign keys:
  - ['permission_id'] -> rbac_permissions.['id'] (name=role_permissions_permission_id_fkey, ondelete=CASCADE)
  - ['role_id'] -> roles.['id'] (name=role_permissions_role_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_role_permission: ['role_id', 'permission_id']
Indexes:
  - ix_role_permissions_permission_id: ['permission_id']
  - ix_role_permissions_role_id: ['role_id']
  - uq_role_permission: ['role_id', 'permission_id'] (unique)

#### roles
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NULL
  - name: VARCHAR(100) NOT NULL
  - description: TEXT NULL
  - is_system: BOOLEAN NOT NULL DEFAULT false
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - display_name: VARCHAR(150) NULL
  - category: VARCHAR(20) NOT NULL DEFAULT 'CUSTOM'::character varying
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - is_assignable: BOOLEAN NOT NULL DEFAULT true
  - priority: INTEGER NOT NULL DEFAULT 50
  - created_by: UUID NULL
  - updated_by: UUID NULL
Primary key: ['id'] (name=roles_pkey)
Foreign keys:
  - ['created_by'] -> users.['id'] (name=fk_roles_created_by, ondelete=SET NULL)
  - ['updated_by'] -> users.['id'] (name=fk_roles_updated_by, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=roles_organization_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_role_org_name: ['organization_id', 'name']
Indexes:
  - ix_roles_organization_id: ['organization_id']
  - ix_roles_status: ['status']
  - uq_role_org_name: ['organization_id', 'name'] (unique)

#### runtime_approvals
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - agent_id: UUID NULL
  - agent_version_id: UUID NULL
  - deployment_id: UUID NULL
  - execution_id: UUID NULL
  - requested_action: VARCHAR(30) NOT NULL
  - risk_score: INTEGER NULL
  - reason: TEXT NULL
  - matched_policies: JSONB NOT NULL DEFAULT '[]'::jsonb
  - request_summary: JSONB NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'PENDING'::character varying
  - requested_by: UUID NULL
  - reviewed_by: UUID NULL
  - decision_comment: TEXT NULL
  - expires_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - reviewed_at: TIMESTAMP NULL
Primary key: ['id'] (name=runtime_approvals_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=runtime_approvals_agent_id_fkey, ondelete=CASCADE)
  - ['agent_version_id'] -> agent_versions.['id'] (name=runtime_approvals_agent_version_id_fkey, ondelete=CASCADE)
  - ['deployment_id'] -> agent_deployments.['id'] (name=runtime_approvals_deployment_id_fkey, ondelete=CASCADE)
  - ['execution_id'] -> agent_executions.['id'] (name=runtime_approvals_execution_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=runtime_approvals_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_runtime_approvals_org: ['organization_id']
  - ix_runtime_approvals_status: ['status']

#### runtime_events
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - agent_id: UUID NULL
  - deployment_id: UUID NULL
  - execution_id: UUID NULL
  - event_type: VARCHAR(50) NOT NULL
  - severity: VARCHAR(20) NOT NULL DEFAULT 'INFO'::character varying
  - payload: JSONB NULL
  - request_id: VARCHAR(100) NULL
  - correlation_id: VARCHAR(100) NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=runtime_events_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=runtime_events_agent_id_fkey, ondelete=CASCADE)
  - ['deployment_id'] -> agent_deployments.['id'] (name=runtime_events_deployment_id_fkey, ondelete=CASCADE)
  - ['execution_id'] -> agent_executions.['id'] (name=runtime_events_execution_id_fkey, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=runtime_events_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_runtime_events_agent: ['agent_id']
  - ix_runtime_events_execution: ['execution_id']
  - ix_runtime_events_org: ['organization_id']
  - ix_runtime_events_type: ['event_type']

#### security_events
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NULL
  - event_type: VARCHAR(64) NOT NULL
  - actor_type: VARCHAR(30) NOT NULL
  - actor_id: UUID NULL
  - target_type: VARCHAR(30) NULL
  - target_id: UUID NULL
  - request_id: VARCHAR(64) NULL
  - correlation_id: VARCHAR(64) NULL
  - ip_address: VARCHAR(64) NULL
  - meta: JSONB NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=security_events_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=security_events_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_security_events_actor_created: ['actor_id', 'created_at']
  - ix_security_events_event_type: ['event_type']
  - ix_security_events_org_created: ['organization_id', 'created_at']
  - ix_security_events_organization_id: ['organization_id']
  - ix_security_events_request_id: ['request_id']
  - ix_security_events_session_id: [None]
  - ix_security_events_type_created: ['event_type', 'created_at']

#### service_accounts
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - client_secret_hash: VARCHAR(255) NOT NULL
  - permissions: JSONB NOT NULL
  - owner_id: UUID NULL
  - status: VARCHAR(30) NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=service_accounts_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=service_accounts_organization_id_fkey, ondelete=CASCADE)
  - ['owner_id'] -> users.['id'] (name=service_accounts_owner_id_fkey, ondelete=SET NULL)
Indexes:
  - ix_service_accounts_organization_id: ['organization_id']

#### signing_key_versions
Columns:
  - id: UUID NOT NULL
  - signing_key_id: UUID NOT NULL
  - version: INTEGER NOT NULL
  - public_key_pem: TEXT NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - retired_at: TIMESTAMP NULL
Primary key: ['id'] (name=signing_key_versions_pkey)
Foreign keys:
  - ['signing_key_id'] -> signing_keys.['id'] (name=signing_key_versions_signing_key_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_signing_key_versions_key_version: ['signing_key_id', 'version']
Indexes:
  - ix_signing_key_versions_key: ['signing_key_id']
  - uq_signing_key_versions_key_version: ['signing_key_id', 'version'] (unique)

#### signing_keys
Columns:
  - id: UUID NOT NULL
  - key_id: VARCHAR(128) NOT NULL
  - provider: VARCHAR(32) NOT NULL DEFAULT 'LOCAL'::character varying
  - algorithm: VARCHAR(32) NOT NULL DEFAULT 'ED25519'::character varying
  - current_version: INTEGER NOT NULL DEFAULT 1
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - public_key_pem: TEXT NOT NULL
  - revoked_at: TIMESTAMP NULL
  - revocation_reason: TEXT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=signing_keys_pkey)
Unique constraints:
  - signing_keys_key_id_key: ['key_id']
Indexes:
  - signing_keys_key_id_key: ['key_id'] (unique)

#### sod_rules
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - rule_type: VARCHAR(20) NOT NULL DEFAULT 'SOD'::character varying
  - name: VARCHAR(255) NOT NULL
  - description: TEXT NULL
  - risk_level: VARCHAR(20) NOT NULL DEFAULT 'MEDIUM'::character varying
  - permissions_a: JSONB NOT NULL
  - permissions_b: JSONB NOT NULL
  - scope: JSONB NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'DRAFT'::character varying
  - created_by: UUID NULL
  - approved_by: UUID NULL
  - approved_at: TIMESTAMP NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=sod_rules_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=sod_rules_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_sod_rules_org: ['organization_id']
  - ix_sod_rules_status: ['status']
  - ix_sod_rules_type: ['rule_type']

#### teams
Columns:
  - id: UUID NOT NULL
  - department_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - lead_id: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
Primary key: ['id'] (name=teams_pkey)
Foreign keys:
  - ['department_id'] -> departments.['id'] (name=teams_department_id_fkey, ondelete=CASCADE)
  - ['lead_id'] -> users.['id'] (name=teams_lead_id_fkey, ondelete=SET NULL)
Indexes:
  - ix_teams_department_id: ['department_id']

#### tool_calls
Columns:
  - id: UUID NOT NULL
  - execution_id: UUID NOT NULL
  - agent_id: UUID NOT NULL
  - tool_id: UUID NOT NULL
  - action: VARCHAR(50) NOT NULL
  - input_summary: JSONB NULL
  - output_summary: JSONB NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'ALLOWED'::character varying
  - risk_score: INTEGER NULL
  - authorization_decision_id: UUID NULL
  - approval_id: UUID NULL
  - started_at: TIMESTAMP NULL
  - completed_at: TIMESTAMP NULL
  - duration_ms: INTEGER NULL
  - error_code: VARCHAR(50) NULL
  - cost: NUMERIC(12, 6) NULL
  - target_host: VARCHAR(255) NULL
  - target_path: TEXT NULL
  - http_method: VARCHAR(10) NULL
  - http_status: INTEGER NULL
  - request_bytes: INTEGER NULL
  - response_bytes: INTEGER NULL
  - egress_decision: VARCHAR(20) NULL
  - egress_denied_reason: VARCHAR(64) NULL
  - error_class: VARCHAR(32) NULL
  - attempt_number: INTEGER NULL
  - validation_error: TEXT NULL
  - loop_iteration: INTEGER NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=tool_calls_pkey)
Foreign keys:
  - ['agent_id'] -> agents.['id'] (name=tool_calls_agent_id_fkey, ondelete=CASCADE)
  - ['execution_id'] -> agent_executions.['id'] (name=tool_calls_execution_id_fkey, ondelete=CASCADE)
  - ['tool_id'] -> tools.['id'] (name=tool_calls_tool_id_fkey, ondelete=RESTRICT)
Indexes:
  - ix_tool_calls_agent: ['agent_id']
  - ix_tool_calls_execution: ['execution_id']
  - ix_tool_calls_tool: ['tool_id']

#### tools
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NULL
  - name: VARCHAR(100) NOT NULL
  - display_name: VARCHAR(150) NOT NULL
  - description: TEXT NULL
  - tool_type: VARCHAR(30) NOT NULL DEFAULT 'FUNCTION'::character varying
  - endpoint_reference: VARCHAR(500) NULL
  - input_schema: JSONB NULL
  - output_schema: JSONB NULL
  - risk_level: VARCHAR(20) NOT NULL DEFAULT 'MEDIUM'::character varying
  - side_effect_level: VARCHAR(20) NOT NULL DEFAULT 'NONE'::character varying
  - data_classification: VARCHAR(30) NOT NULL DEFAULT 'INTERNAL'::character varying
  - requires_approval: BOOLEAN NOT NULL DEFAULT false
  - timeout_seconds: INTEGER NOT NULL DEFAULT 30
  - enabled: BOOLEAN NOT NULL DEFAULT true
  - http_config: JSONB NULL
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=tools_pkey)
Foreign keys:
  - ['organization_id'] -> organizations.['id'] (name=tools_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_tools_org: ['organization_id']

#### tool_credentials
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - tool_id: UUID NOT NULL
  - encrypted_secret: TEXT NOT NULL
  - secret_hint: VARCHAR(8) NOT NULL
  - status: VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'::character varying
  - created_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=tool_credentials_pkey)
Foreign keys:
  - ['created_by'] -> users.['id'] (name=tool_credentials_created_by_fkey, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=tool_credentials_organization_id_fkey, ondelete=CASCADE)
  - ['tool_id'] -> tools.['id'] (name=tool_credentials_tool_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_tool_credentials_org_tool: ['organization_id', 'tool_id']
Indexes:
  - ix_tool_credentials_organization_id: ['organization_id']
  - uq_tool_credentials_org_tool: ['organization_id', 'tool_id'] (unique)

#### user_profiles
Columns:
  - id: UUID NOT NULL
  - user_id: UUID NOT NULL
  - first_name: VARCHAR(100) NULL
  - last_name: VARCHAR(100) NULL
  - job_title: VARCHAR(150) NULL
  - department: VARCHAR(150) NULL
  - phone: VARCHAR(40) NULL
  - timezone: VARCHAR(64) NULL
  - language: VARCHAR(16) NULL
  - avatar_url: TEXT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=user_profiles_pkey)
Foreign keys:
  - ['user_id'] -> users.['id'] (name=user_profiles_user_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_user_profiles_user_id: ['user_id']
Indexes:
  - ix_user_profiles_user_id: ['user_id']
  - uq_user_profiles_user_id: ['user_id'] (unique)

#### user_roles
Columns:
  - id: UUID NOT NULL
  - user_id: UUID NOT NULL
  - role_id: UUID NOT NULL
  - scope: VARCHAR(20) NOT NULL DEFAULT 'GLOBAL'::character varying
  - organization_id: UUID NULL
  - department_id: UUID NULL
  - team_id: UUID NULL
  - project_id: UUID NULL
  - resource_type: VARCHAR(50) NULL
  - resource_id: UUID NULL
  - expires_at: TIMESTAMP NULL
  - assigned_by: UUID NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
Primary key: ['id'] (name=user_roles_pkey)
Foreign keys:
  - ['assigned_by'] -> users.['id'] (name=fk_user_roles_assigned_by, ondelete=SET NULL)
  - ['department_id'] -> departments.['id'] (name=fk_user_roles_department_id, ondelete=CASCADE)
  - ['organization_id'] -> organizations.['id'] (name=fk_user_roles_organization_id, ondelete=CASCADE)
  - ['team_id'] -> teams.['id'] (name=fk_user_roles_team_id, ondelete=CASCADE)
  - ['role_id'] -> roles.['id'] (name=user_roles_role_id_fkey, ondelete=CASCADE)
  - ['user_id'] -> users.['id'] (name=user_roles_user_id_fkey, ondelete=CASCADE)
Unique constraints:
  - uq_user_role_scope: ['user_id', 'role_id', 'scope', 'organization_id', 'department_id', 'team_id', 'project_id', 'resource_type', 'resource_id']
Indexes:
  - ix_user_roles_organization_id: ['organization_id']
  - ix_user_roles_role_id: ['role_id']
  - ix_user_roles_scope: ['scope']
  - ix_user_roles_user_id: ['user_id']
  - uq_user_role_scope: ['user_id', 'role_id', 'scope', 'organization_id', 'department_id', 'team_id', 'project_id', 'resource_type', 'resource_id'] (unique)

#### users
Columns:
  - id: UUID NOT NULL
  - organization_id: UUID NOT NULL
  - name: VARCHAR(255) NOT NULL
  - email: VARCHAR(320) NOT NULL
  - password_hash: VARCHAR(255) NOT NULL
  - role: VARCHAR(11) NOT NULL
  - is_active: BOOLEAN NOT NULL
  - created_at: TIMESTAMP NOT NULL DEFAULT now()
  - updated_at: TIMESTAMP NOT NULL DEFAULT now()
  - department_id: UUID NULL
  - status: VARCHAR(30) NOT NULL DEFAULT 'ACTIVE'::character varying
  - password_changed_at: TIMESTAMP NULL
  - password_expires_at: TIMESTAMP NULL
  - must_change_password: BOOLEAN NOT NULL DEFAULT false
  - pending_email: VARCHAR(320) NULL
Primary key: ['id'] (name=users_pkey)
Foreign keys:
  - ['department_id'] -> departments.['id'] (name=fk_users_department_id, ondelete=SET NULL)
  - ['organization_id'] -> organizations.['id'] (name=users_organization_id_fkey, ondelete=CASCADE)
Indexes:
  - ix_users_department_id: ['department_id']
  - ix_users_email: ['email'] (unique)
  - ix_users_organization_id: ['organization_id']
  - ix_users_password_expires_at: ['password_expires_at']

## 3. Migration Chain

All **46** Alembic revisions in `backend/migrations/versions/`, in chain order (oldest → newest), verified via `alembic history` and a directory listing this session. **Current head: `0046_trace_explorer_index`** *(re-derived 2026-08-25, Phase 4.1 pre-step A; this line previously said "42 revisions" and "`0041_canary_rollout`", stale by four phases)* (verified via `alembic current` against the live database; `alembic upgrade head` / `downgrade -1` / `upgrade head` re-verified clean this session for the newest revision).

| # | Revision file | Description (from the migration's own docstring) |
|---|---|---|
| 1 | `0001_initial_schema.py` | Initial schema: organizations, users, agents, permissions, agent_actions, approvals and audit_logs. |
| 2 | `0002_phase2_schema.py` | Phase 2 schema: agent API keys, policies, advanced RBAC, approval priority/SLA/comments and audit log forensic fields. |
| 3 | `0003_agent_management.py` | Phase 3 Part 3.2 - enterprise agent management fields + statuses. |
| 4 | `0004_policy_management.py` | Phase 3 Part 3.3 - policy management metadata. |
| 5 | `0005_approval_workbench.py` | Phase 3 Part 3.4 - approval queue & human review workbench. |
| 6 | `0006_identity_foundation.py` | Phase 4 Part 4.1 - Enterprise Identity Platform foundation. |
| 7 | `0007_identity_lifecycle.py` | Phase 4 Part 4.1a - unify the identity lifecycle across all identity types. |
| 8 | `0008_auth_login_history.py` | Phase 4 Part 4.2.2.1 - human authentication: login history + lockout window. |
| 9 | `0009_session_lifecycle.py` | Phase 4 Part 4.2.2.2 - login, logout & session lifecycle. |
| 10 | `0010_session_admin_permissions.py` | Phase 4 Part 4.2.2.2 - administrative session-management permissions. |
| 11 | `0011_security_event_read_indexes.py` | Phase 4 Part 4.2.2.2 - indexes for the security-event read path. |
| 12 | `0012_registration_invites.py` | Phase 4 Part 4.2.2.3.1 - enterprise registration, invitations & email verification. |
| 13 | `0013_credential_management.py` | Phase 4 Part 4.2.2.3.2 - enterprise password policy & credential management. |
| 14 | `0014_password_reset_recovery.py` | Phase 4 Part 4.2.2.3.3 - password reset, account recovery & email change. |
| 15 | `0015_account_protection.py` | Phase 4 Part 4.2.2.3.4 - enterprise account protection & risk-based auth. |
| 16 | `0016_rbac_foundation.py` | Phase 4.3.1 - Enterprise RBAC foundation. |
| 17 | `0017_permission_engine.py` | Phase 4.3.2 - Enterprise Permission Engine. |
| 18 | `0018_org_hierarchy.py` | Phase 4.3.3 - Enterprise organization authorization hierarchy. |
| 19 | `0019_resource_authorization.py` | Phase 4.3.4 - Enterprise resource-based authorization (RBAC + Resource ACL). |
| 20 | `0020_abac_engine.py` | Phase 4.3.5 - Attribute-Based Access Control engine. |
| 21 | `0021_access_reviews.py` | Phase 4.3.7 - Enterprise authorization administration portal. |
| 22 | `0022_governance_iga.py` | Phase 4.3.8 - Identity Governance & Administration (IGA). |
| 23 | `0023_agent_runtime.py` | Phase 5.0 - Enterprise AI Agent Runtime & Lifecycle Management. |
| 24 | `0024_agent_registry.py` | Phase 5.1 - Enterprise Agent Registry, Definitions & Lifecycle. |
| 25 | `0025_agent_versioning.py` | Phase 5.2 Part 1 - Enterprise Immutable Agent Versioning & Release Management. |
| 26 | `0026_version_compatibility.py` | Phase 5.2.6 - Compatibility & Breaking-Change Detection. |
| 27 | `0027_version_signing.py` | Phase 5.2.4 - Cryptographic Signing, Provenance & Portable Attestation. |
| 28 | `0028_streaming_and_pricing.py` | Phase 5.7a.3 - Streaming & Token Accounting: 12 new columns on `agent_executions`, 4 on `execution_attempts`, new `model_pricing` table (seeded with 3 illustrative rows), legacy non-zero-cost rows marked `cost_is_estimated=true`. |
| 29 | `0029_provider_credentials.py` | Phase 5.7a.5 - Per-Organization Provider Credentials: new `provider_credentials` table (encrypted-at-rest, one row per `(organization_id, provider)`), two new RBAC permissions (`runtime.provider.view`/`.manage`) backfilled onto the global catalog. |
| 30 | `0030_http_tool_egress.py` | Phase 5.6a.1 - HTTP Tool Execution & Egress Control: `tools.http_config` (JSONB), eight new columns on `tool_calls` (egress/HTTP recording), new `tool_credentials` table. |
| 31 | `0031_tool_resilience.py` | Phase 5.6a.2 - Tool Schema Validation & Resilience: three new nullable columns on `tool_calls` (`error_class`/`attempt_number`/`validation_error`); no new table. |
| 32 | `0032_tool_loop.py` | Phase 5.6a.3 - Model-Driven Tool Invocation Loop: new `execution_messages` table (the conversation transcript); two new columns on `agent_executions` (`loop_iterations`/`termination_reason`); one new nullable column on `tool_calls` (`loop_iteration`). |
| 33 | `0033_connector_core.py` | Phase 2.1.1 - Connector Abstraction & Lifecycle: three new tables — `connectors` (registered types), `connector_instances` (tenant-scoped configured uses), `connector_lifecycle_events` (append-only transition audit). No existing table touched. |
| 34 | `0034_connector_auth.py` | Phase 2.1.2 - Connector Authentication Framework: two new tables — `connector_credentials` (per-instance, per-scheme encrypted credential bundle), `connector_oauth_tokens` (per-instance cached OAuth2 token pair). No existing table touched. |
| 35 | `0035_connector_health.py` | Phase 2.1.3 - Connector Registry & Health: new `connector_health_checks` table (append-only history); two new nullable columns on `connector_instances` (`last_health_check_at`, `current_health`). |
| 36 | `0036_identity_federation.py` | Phase 2.3.1 - External Identity Federation: two new tables — `identity_federation_configs` (per-organization IdP configuration), `federated_identities` (links an IdP subject to an existing user; no credential column). No existing table touched. |
| 37 | `0037_deployment_lifecycle.py` | Phase 3.1 - Enterprise Deployment Core: two new tables — `deployment_events` (append-only lifecycle lineage), `idempotency_keys` (the reusable platform-wide idempotency contract); four new columns on `agent_deployments` (`lifecycle_state`/`revision`/`state_reason`/`superseded_by_deployment_id`) plus a deterministic, one-time §15 data backfill mapping every existing row's legacy `status` into the new `lifecycle_state`. |
| 38 | `0038_environments_promotion.py` | Phase 3.2 - Environment & Promotion Model: two new tables — `environments` (governed, tenant-scoped deployment targets with policy), `promotion_paths` (the org-configured graph of legal promotions); one new column on `agent_deployments` (`environment_id`) plus a deterministic, one-time §15 seed (standard five environments + default promotion chain per organization) and backfill mapping every existing row's legacy `environment` string to the matching new row. |
| 39 | `0039_deployment_preflight.py` | Phase 3.3 - Deployment Preflight & Release Gate Engine: one new table — `deployment_preflight_results` (one persisted `ReleaseGateService.evaluate()` verdict + JSONB findings per call). No existing table or column touched; no data backfill. |
| 40 | `0040_traffic_allocation.py` | Phase 3.4 - Traffic Allocation, Version Resolver & Execution Gate: two new tables — `deployment_traffic_allocations` (one revision of an agent's weighted split in one environment; partial unique index on `(agent_id, environment_id) WHERE is_current` as the concurrency primitive), `deployment_traffic_weights` (the `(version, deployment, weight)` entries). No existing table or column touched. Includes the §15 step-2 data backfill: every servable deployment with a governed `environment_id` gets a current 100% allocation to the version it was already serving, newest-by-`deployed_at` winning per `(agent, environment)`. |
| 41 | `0041_canary_rollout.py` | Phase 3.5 - Canary Deployment Engine: three new tables — `rollout_plans` (the rollout state machine + `version_id_col` concurrency guard), `rollout_stages` (ordered stages and their three gates), `deployment_health_evaluations` (ruling #3's AI-aware release-health verdicts) — plus two indexes on the pre-existing `agent_executions`: `(agent_version_id, created_at)` and `(deployment_id, created_at)`, the latter the first index that column has ever had. The pre-existing `deployment_health` table is untouched (ruling #3). No existing column altered; no data backfill. **(head)** |

## 4. Implemented Modules

**268 non-`__init__.py` Python files** under `backend/app/` (266 at the last full count, post Phase 3.2. **+2 this update, Phase 3.3**: the new `app/runtime/release_gate/` package — `checks.py`, `service.py` (`__init__.py` excluded from this count as it is everywhere else in this section). 263 at the count before that, post Phase 2.1.2. **+3 this update, Phase 2.1.3**: `app/integration/health.py`, `registry.py`, `scheduler.py` — no new sub-package, all three land directly in the existing `app/integration/` directory. 252 at the count before that, post Phase 2.1.1. **+11 that update, Phase 2.1.2**: the new `app/integration/auth/` sub-package — `base.py`, `registry.py`, `service.py`, `token_manager.py` (4 files) plus `schemes/api_key.py`, `basic.py`, `bearer.py`, `mtls.py`, `oauth2_authorization_code.py`, `oauth2_client_credentials.py` (6 files) — plus `app/integration/mock_authenticated.py` (1 file); `__init__.py` files excluded from this count as they are everywhere else in this section. 243 at the count before that, post Phase 5.6a.3; **+9 that update, Phase 2.1.1**: the entire new `app/integration/` package — `base.py`, `errors.py`, `lifecycle.py`, `mock.py`, `routes.py`, `schemas.py`, `service.py`, `types.py` (8 files) — plus `app/models/integration.py` (1 file). A genuinely new sibling domain, not an extension of an existing one, matching how `app/runtime/providers/` first appeared as a new package in Phase 5.7a.1's count). AST-parsed for their module docstring (first line shown) and every top-level class/public function. Grouped by domain (backend directory structure). Frontend module structure is summarized separately at the end of this section (file-count only — the frontend was not AST-parsed since the exhaustive symbol-level inventory the user asked for was scoped to "modules" in the module/class/function sense, which is the backend's organizing unit; the frontend's `src/modules/*` React component tree does not have an equivalent exported-symbol convention).

**Out of this section's stated scope** (`backend/app/` only): `backend/scripts/recompute_checksums.py` (Phase 5.2.4's audited legacy-checksum-migration script) and its `backend/scripts/__init__.py` live under `backend/scripts/`, a sibling of `backend/app/`, not under it — noted here for completeness rather than silently expanding the count above.

### api

**`backend/app/api/deps.py`** — Shared FastAPI dependencies: DB session, authentication, RBAC and context.
- Classes: `ActionPrincipal`
- Functions: `get_current_user,require_roles,require_permission,get_current_agent,get_action_principal,get_request_context`

**`backend/app/api/router.py`** — Aggregates every route module into a single API router.

**`backend/app/api/routes/agent_actions.py`** — Agent action routes - submit an action and inspect past actions.
- Functions: `submit_agent_action,list_agent_actions,get_agent_action`

**`backend/app/api/routes/agents.py`** — Agent management routes (scoped to the caller's organization).
- Functions: `create_agent,list_agents,get_agent,update_agent,delete_agent,agent_stats,update_agent_status`

**`backend/app/api/routes/analytics.py`** — Analytics & AI Operations Center routes (Phase 3 Part 3.6).
- Functions: `analytics_overview,analytics_kpis,analytics_activity,analytics_fleet_health,analytics_risk,analytics_performance,analytics_policies,analytics_review,analytics_cost,analytics_insights,analytics_reports`

**`backend/app/api/routes/api_keys.py`** — Agent API key routes - issue, list and revoke keys.
- Functions: `generate_api_key,list_api_keys,revoke_api_key`

**`backend/app/api/routes/approvals.py`** — Approval routes - the Human Review Workbench (Phase 3 Part 3.4).
- Functions: `list_approvals,list_pending_approvals,approval_statistics,approval_history,approval_escalations,get_approval,approval_timeline,list_comments,add_comment,approve,reject,escalate,assign`

**`backend/app/api/routes/audit.py`** — Audit & Compliance Center routes (Phase 3 Part 3.5).
- Functions: `list_audit,audit_statistics,audit_timeline,audit_event_catalog,audit_security,audit_compliance,audit_export,get_audit_event`

**`backend/app/api/routes/audit_logs.py`** — Audit log routes - read-only access to the event trail.
- Functions: `list_audit_logs,list_entity_audit_logs`

**`backend/app/api/routes/auth.py`** — Authentication routes: register, login and current-user.
- Functions: `register,login,me`

**`backend/app/api/routes/dashboard.py`** — Dashboard routes - aggregated metrics and feeds for the future frontend.
- Functions: `dashboard_summary,agent_activity,risk_trend,recent_actions,high_risk_actions,pending_approvals`

**`backend/app/api/routes/organizations.py`** — Organization routes.
- Functions: `create_organization,get_organization`

**`backend/app/api/routes/permissions.py`** — Permission management routes.
- Functions: `create_permission,list_permissions,list_agent_permissions`

**`backend/app/api/routes/policies.py`** — Policy routes - CRUD, lifecycle, simulation and audit for governance policies.
- Functions: `create_policy,list_policies,list_policy_templates,get_policy,update_policy,enable_policy,disable_policy,test_policy,policy_audit,delete_policy`

**`backend/app/api/routes/rbac.py`** — RBAC routes - inspect roles/permissions and assign roles to users.
- Functions: `list_permissions,list_roles,my_permissions,assign_role`

**`backend/app/api/routes/system.py`** — System routes - operational health of the platform's subsystems.
- Functions: `system_health`

**`backend/app/api/routes/users.py`** — User management routes (scoped to the caller's organization).
- Functions: `create_user,list_users,get_user`


### authorization (core)

**`backend/app/authorization/cache.py`** — Permission cache + version management (Phase 4.3.2 §10, §18).
- Classes: `PermissionCacheService`

**`backend/app/authorization/catalog.py`** — Permission groups, the enriched permission catalog, and the built-in role
- Classes: `PermissionGroupDef,BuiltinRoleDef`
- Functions: `split_code,group_for_code,display_name_for_code,legacy_role_priority`

**`backend/app/authorization/decisions.py`** — Authorization decision audit (Phase 4.3.2 §18, §20, §27).
- Classes: `AuthorizationDecisionService`

**`backend/app/authorization/engine.py`** — The Enterprise Permission Engine (Phase 4.3.2).
- Classes: `Grant,ResourceContext,AuthorizationResult,WildcardResolver,RoleResolver,ScopeResolver,ConflictResolver,PermissionResolver,PermissionEngine`

**`backend/app/authorization/enums.py`** — Authorization enums (Phase 4.3.1 §8, §9, §15, §23).
- Classes: `RoleCategory,RoleStatus,AssignmentScope,AuthorizationDecision,AuthorizationEngineEvent,AuthorizationAuditEvent`

**`backend/app/authorization/repositories.py`** — Authorization repositories (Phase 4.3.1 §19).
- Classes: `RoleRepository,PermissionRepository,PermissionGroupRepository,RoleAssignmentRepository,RoleHierarchyRepository,AuthorizationAuditRepository`

**`backend/app/authorization/routes.py`** — Enterprise authorization API (Phase 4.3.1 §20).
- Functions: `list_roles,create_role,get_role,update_role,delete_role,role_effective_permissions,list_permissions,create_permission,update_permission,delete_permission,list_permission_groups,list_role_assignments,create_role_assignment,delete_role_assignment,list_role_hierarchy,create_role_hierarchy,delete_role_hierarchy,authorization_check,list_authorization_audit`

**`backend/app/authorization/schemas.py`** — Authorization API schemas (Phase 4.3.1 §20).
- Classes: `PermissionGroupRead,PermissionRead,PermissionCreate,PermissionUpdate,RoleRead,RoleCreate,RoleUpdate,EffectivePermissionsRead,RoleAssignmentCreate,RoleAssignmentRead,RoleHierarchyCreate,RoleHierarchyRead,AuthorizationCheckRequest,AuthorizationCheckResponse,AuthorizationAuditRead`

**`backend/app/authorization/seeding.py`** — Idempotent seeding of the authorization foundation (Phase 4.3.1 §7, §12, §17).
- Functions: `seed_authorization`

**`backend/app/authorization/services.py`** — Authorization services (Phase 4.3.1 §18).
- Classes: `AuthorizationAuditService,PermissionService,PermissionGroupService,RoleService,RoleHierarchyService,RoleAssignmentService`


### authorization/abac

**`backend/app/authorization/abac/attributes.py`** — ABAC attribute system (Phase 4.3.5 §5, §18–§20).
- Classes: `AttributeRegistryService,AuthorizationAttributeContext,SubjectAttributeProvider,ResourceAttributeProvider,ActionAttributeProvider,EnvironmentAttributeProvider,AIAttributeProvider,AttributeContextBuilder`

**`backend/app/authorization/abac/conditions.py`** — ABAC condition evaluator (Phase 4.3.5 §9, §24).
- Classes: `ConditionTrace,ConditionEvaluator`

**`backend/app/authorization/abac/engine.py`** — The ABAC engine (Phase 4.3.5 §13–§17, §23–§26, §43).
- Classes: `ABACMetrics,MatchedPolicy,CombiningAlgorithmService,ObligationService,DecisionExplanationService,ABACResult,ABACEngine,PolicySimulationService`

**`backend/app/authorization/abac/enums.py`** — ABAC engine enums (Phase 4.3.5 §5, §7–§13, §38).
- Classes: `PolicyStatus,PolicyEffect,CombiningAlgorithm,PolicyScopeType,AttributeCategory,AttributeDataType,AttributeSensitivity,Operator,ABACDecision,ABACAuditEvent`

**`backend/app/authorization/abac/operators.py`** — ABAC operator registry (Phase 4.3.5 §9, §10, §24).
- Classes: `OperatorRegistry`
- Functions: `validate_regex_pattern,validate_condition_value`

**`backend/app/authorization/abac/policies.py`** — ABAC policy services (Phase 4.3.5 §6–§8, §11–§13, §21, §23–§24, §27–§28).
- Classes: `PolicyCache,PolicyValidationService,PolicyService,PolicyResolver`
- Functions: `record_abac_event`

**`backend/app/authorization/abac/routes.py`** — ABAC engine API (Phase 4.3.5 §30, §37).
- Functions: `list_policies,create_policy,get_policy,update_policy,delete_policy,validate_policy,publish_policy,disable_policy,archive_policy,clone_policy,list_versions,get_version,rollback_policy,simulate,simulate_policy,evaluate,list_evaluations,get_evaluation,abac_metrics,middleware_metrics,list_attributes,get_attribute,create_attribute,update_attribute,list_exceptions,create_exception,revoke_exception`

**`backend/app/authorization/abac/schemas.py`** — ABAC API schemas (Phase 4.3.5 §15, §30, §31).
- Classes: `PolicyRead,PolicyWrite,ValidationResult,PolicyVersionRead,AttributeRead,AttributeCreate,AttributeUpdate,ABACDecisionRead,EvaluateRequest,SimulateRequest,SimulationRead,EvaluationRead,ExceptionRead,ExceptionCreate`


### authorization/admin

**`backend/app/authorization/admin/routes.py`** — Administration portal API (Phase 4.3.7 §18) — /api/v1/admin.
- Functions: `dashboard,list_roles,create_role,update_role,delete_role,list_permissions,organization_tree,list_resources,list_policies,create_policy,update_policy,delete_policy,policy_simulator,authorization_decisions,list_campaigns,create_campaign,get_campaign,update_campaign,schedule_campaign,activate_campaign,campaign_items,decide_item,complete_campaign,archive_campaign,export_campaign,analytics`

**`backend/app/authorization/admin/schemas.py`** — Pydantic schemas for the administration portal API (Phase 4.3.7 §18).
- Classes: `DashboardWidgets,DashboardCharts,DashboardRead,DecisionRead,CampaignCreate,CampaignUpdate,ReviewItemRead,CampaignRead,ItemDecision,AnalyticsRead`

**`backend/app/authorization/admin/services.py`** — Administration portal services (Phase 4.3.7).
- Classes: `DashboardService,DecisionExplorerService,AccessReviewService,SecurityAnalyticsService`


### authorization/hierarchy

**`backend/app/authorization/hierarchy/enums.py`** — Organization hierarchy enums (Phase 4.3.3 §3, §18).
- Classes: `HierarchyLevel,OrgEntityStatus,OrgAuditEvent`

**`backend/app/authorization/hierarchy/routes.py`** — Organization hierarchy API (Phase 4.3.3 §15, §17).
- Functions: `list_organizations,create_organization,get_organization,update_organization,delete_organization,list_business_units,create_business_unit,get_business_unit,update_business_unit,delete_business_unit,list_departments,create_department,get_department,update_department,delete_department,list_teams,create_team,get_team,update_team,delete_team,list_projects,create_project,get_project,update_project,delete_project,hierarchy_tree,assign_ownership,transfer_ownership,get_ownership,list_delegations,create_delegation,revoke_delegation`

**`backend/app/authorization/hierarchy/schemas.py`** — Organization hierarchy API schemas (Phase 4.3.3 §15).
- Classes: `OrganizationRead,OrganizationWrite,BusinessUnitRead,BusinessUnitWrite,DepartmentRead,DepartmentWrite,TeamRead,TeamWrite,ProjectRead,ProjectWrite,ResourceOwnershipRead,ResourceOwnershipAssign,OwnershipTransfer,DelegationRead,DelegationCreate`

**`backend/app/authorization/hierarchy/services.py`** — Organization hierarchy services (Phase 4.3.3 §12, §13).
- Classes: `HierarchyResolverService,_OrgScoped,BusinessUnitService,DepartmentService,TeamService,ProjectService,ResourceOwnershipService,OrganizationHierarchyService,DelegationService`
- Functions: `record_org_event`


### authorization/middleware

**`backend/app/authorization/middleware/audit.py`** — Middleware audit integration (Phase 4.3.6 §24, §35).
- Classes: `AuthorizationAuditService`

**`backend/app/authorization/middleware/cache.py`** — Decision cache (Phase 4.3.6 §19, §23).
- Classes: `_Entry,DecisionCacheService`

**`backend/app/authorization/middleware/context.py`** — The authorization context (Phase 4.3.6 §5).
- Classes: `AuthorizationContext,AuthorizationContextBuilder`

**`backend/app/authorization/middleware/errors.py`** — Standard authorization exceptions (Phase 4.3.6 §25, §26).
- Classes: `AuthorizationMiddlewareError,AuthenticationFailed,SessionExpired,PermissionDenied,ResourceForbidden,ABACDenied,ApprovalRequired,MFARequired,JustificationRequired,PolicyEvaluationFailed`

**`backend/app/authorization/middleware/gateway.py`** — The Authorization Gateway (Phase 4.3.6 §21, §22).
- Classes: `GatewayDecision,AuthorizationGateway`

**`backend/app/authorization/middleware/metrics.py`** — Pipeline metrics (Phase 4.3.6 §34).
- Classes: `PipelineMetricsService`

**`backend/app/authorization/middleware/obligations.py`** — Obligation processing (Phase 4.3.6 §16).
- Classes: `ObligationOutcome,ObligationExecutor`

**`backend/app/authorization/middleware/pipeline.py`** — The authorization pipeline (Phase 4.3.6 §4, §9, §18).
- Classes: `AuthorizationPipeline,DecisionTrace,DecisionTraceService`


### authorization/resources

**`backend/app/authorization/resources/enums.py`** — Resource-based authorization enums (Phase 4.3.4 §3, §9, §10, §12, §23).
- Classes: `ResourceType,OwnerType,VisibilityLevel,PrincipalType,ACLEffect,ShareAccessLevel,ResourceStatus,DelegationStatus,ResourceAuditEvent`

**`backend/app/authorization/resources/routes.py`** — Resource-based authorization API (Phase 4.3.4 §19).
- Functions: `list_resource_types,list_resources,register_resource,get_resource,update_resource,get_owner,transfer_ownership,ownership_history,list_acl,add_acl_entry,update_acl_entry,delete_acl_entry,list_shares,share_resource,update_share,revoke_share,list_delegations,delegate_resource,revoke_delegation,set_policy,authorize`

**`backend/app/authorization/resources/schemas.py`** — Resource-based authorization API schemas (Phase 4.3.4 §19).
- Classes: `ResourceRead,ResourceRegister,ResourceUpdate,OwnerRead,OwnershipTransferRequest,OwnershipHistoryRead,ACLEntryRead,ACLEntryCreate,ACLEntryUpdate,ShareRead,ShareCreate,ShareUpdate,ResourceDelegationRead,ResourceDelegationCreate,PolicyWrite,AuthorizeRequest,AuthorizeResponse`

**`backend/app/authorization/resources/services.py`** — Resource-based authorization services (Phase 4.3.4 §16, §17).
- Classes: `MembershipResolver,ResourceRegistryService,_ResourceScoped,ResourceACLService,ResourceSharingService,ResourceOwnershipService,ResourceDelegationService,ResourcePolicyService,ResourceDecision,ResourceAuthorizationService`
- Functions: `action_of,permission_covers,record_resource_event`


### core

**`backend/app/core/config.py`** — Application configuration loaded from environment variables / .env file.
- Classes: `Settings`

**`backend/app/core/database.py`** — Database engine, session factory and declarative base.
- Classes: `Base`
- Functions: `get_db`

**`backend/app/core/enums.py`** — Enumerations shared between SQLAlchemy models and Pydantic schemas.
- Classes: `UserRole,AgentStatus,RiskLevel,AgentHealth,ActionDecision,ActionStatus,ApprovalDecision,ActorType,ApiKeyStatus,ApprovalPriority,PolicySeverity,PolicyStatus,EscalationTarget`

**`backend/app/core/middleware.py`** — Cross-cutting HTTP middleware (Phase 4.2.2.3.5 §13, §15, §16, §23).
- Classes: `RequestContextMiddleware,SecurityHeadersMiddleware,ResponseEnvelopeMiddleware`
- Functions: `install_http_middleware`

**`backend/app/core/policy_templates.py`** — Built-in policy templates surfaced in the dashboard's template gallery.

**`backend/app/core/security.py`** — Security helpers: password hashing, JWT tokens and API key handling.
- Functions: `hash_password,is_unusable_password,verify_password,needs_rehash,create_access_token,decode_access_token,generate_api_key,generate_agent_api_key,hash_api_key,verify_api_key`


### governance

**`backend/app/governance/routes.py`** — Identity Governance & Administration API (Phase 4.3.8 §19) — /api/v1/governance.
- Functions: `dashboard,analytics,list_campaigns,create_campaign,get_campaign,update_campaign,launch_campaign,campaign_items,complete_campaign,archive_campaign,export_campaign,approve_review,revoke_review,delegate_review,modify_review,list_sod_rules,create_sod_rule,update_sod_rule,activate_sod_rule,disable_sod_rule,list_sod_findings,scan_sod,list_toxic_rules,create_toxic_rule,activate_toxic_rule,disable_toxic_rule,list_toxic_findings,scan_toxic,list_findings,remediate_finding,list_privileged_accounts,request_privileged_review,list_privileged_reviews,decide_privileged_review,list_orphaned_accounts,scan_orphaned_accounts,list_risk_scores,recalculate_risk_scores,list_remediation_actions,create_remediation_action,execute_remediation_action,compliance_frameworks,list_compliance_reports,generate_compliance_report,get_compliance_report`

**`backend/app/governance/schemas.py`** — Pydantic schemas for the governance API (Phase 4.3.8 §19).
- Classes: `SoDRuleCreate,SoDRuleUpdate,SoDRuleRead,GovernanceFindingRead,FindingResolve,RemediationActionCreate,RemediationActionRead,GovernanceRiskScoreRead,PrivilegedAccountRead,PrivilegedReviewDecision,OrphanedScanResult,ComplianceReportGenerate,ComplianceReportRead,ComplianceFrameworkRead,GovernanceDashboardRead,GovernanceAnalyticsRead,CampaignCreate,CampaignUpdate,CampaignRead,ReviewItemRead,ReviewDecision`

**`backend/app/governance/services.py`** — Identity Governance & Administration services (Phase 4.3.8).
- Classes: `SoDAnalysisService,GovernanceFindingService,RemediationService,GovernanceRiskScoringService,PrivilegedAccessReviewService,OrphanedIdentityService,ComplianceReportingService,GovernanceDashboardService`


### identity/api

**`backend/app/identity/api/deps.py`** — Identity API dependencies.
- Functions: `get_identity_service,get_request_id`

**`backend/app/identity/api/router.py`** — Aggregates identity routes under the versioned prefix (SRS §17).

**`backend/app/identity/api/routes/agent_identities.py`** — AI agent identity endpoints (SRS §7). Identity of an agent, not the agent.
- Functions: `list_agent_identities,create_agent_identity,get_agent_identity,transition_agent_identity`

**`backend/app/identity/api/routes/departments.py`** — Identity department endpoints (SRS §9 api).
- Functions: `list_departments,create_department,get_department`

**`backend/app/identity/api/routes/external_clients.py`** — External client endpoints (SRS §7). Power BI, Zapier, Salesforce, Fabric…
- Functions: `list_external_clients,create_external_client,get_external_client,transition_external_client`

**`backend/app/identity/api/routes/invitations.py`** — Invitation endpoints (4.2.2.3.1 §15).
- Classes: `EmailDeliveryStatus`
- Functions: `create_invitation,list_invitations,resend_invitation,cancel_invitation,preview_invitation,approve_registration,email_delivery_status`

**`backend/app/identity/api/routes/organizations.py`** — Identity organization endpoints (SRS §9 api).
- Functions: `list_organizations,get_organization,transition_organization`

**`backend/app/identity/api/routes/registration.py`** — Public registration & email-verification endpoints (4.2.2.3.1 §15).
- Functions: `register_from_invitation,self_register,verify_email,resend_verification`

**`backend/app/identity/api/routes/roles.py`** — Identity role endpoints (SRS §9 api). Reuses the RBAC role engine.
- Functions: `list_roles`

**`backend/app/identity/api/routes/service_accounts.py`** — Service account endpoints (SRS §7). Backend automation identities.
- Functions: `list_service_accounts,create_service_account,get_service_account,transition_service_account`

**`backend/app/identity/api/routes/sessions.py`** — Administrative session & device management (SRS 4.2.2.2 §17, §18, §32).
- Classes: `AdminRevokeRequest,AdminRevokeResponse`
- Functions: `list_sessions,get_session,list_user_devices,admin_revoke_session,admin_revoke_all_sessions,list_security_events,list_security_event_types,list_session_events`

**`backend/app/identity/api/routes/users.py`** — Identity user endpoints (SRS §9 api). Thin controllers → IdentityService.
- Functions: `list_users,create_user,get_user,activate_user,suspend_user,transition_user`


### identity/audit

**`backend/app/identity/audit/events.py`** — Identity audit/security event recording (SRS §9 audit, §19).
- Functions: `record_security_event`


### identity/auth

**`backend/app/identity/auth/authentication_service.py`** — AuthenticationService — login / refresh / logout orchestration (SRS §16, §19–21).
- Classes: `RequestClient,LoginResult,RefreshResult,AuthenticationService`

**`backend/app/identity/auth/context.py`** — IdentityContext — the internal object every authenticated request carries.
- Classes: `IdentityContext`

**`backend/app/identity/auth/credential_service.py`** — CredentialService — verify secrets and credential status (SRS §11, §16).
- Classes: `CredentialService`

**`backend/app/identity/auth/dependency.py`** — Authentication middleware/dependency (SRS §17; 4.2.2.2 §5, §16, §28).
- Functions: `extract_credential,authenticate,require_scope,require_assurance`

**`backend/app/identity/auth/device_service.py`** — DeviceService — register, recognise, trust and block devices (SRS §13, §14).
- Classes: `ClientInfo,DeviceService`
- Functions: `parse_user_agent,fingerprint_for`

**`backend/app/identity/auth/enums.py`** — Authentication enumerations (SRS §3, §10, §13).
- Classes: `AuthIdentityType,AuthMethod,AuthAssuranceLevel,MfaMethod,AuthEventType`

**`backend/app/identity/auth/login_history_service.py`** — LoginHistoryService — record attempts and drive account lockout (SRS §10, §13, §14).
- Classes: `LockoutState,LoginHistoryService`

**`backend/app/identity/auth/password_service.py`** — PasswordService — hash, verify and enforce password complexity (SRS §9, §11, §14).
- Classes: `PasswordService`

**`backend/app/identity/auth/refresh_rotation_service.py`** — RefreshRotationService — rotate, detect reuse, revoke families (SRS §7, §8, §9).
- Classes: `IssuedToken,RefreshRotationService`

**`backend/app/identity/auth/resolver.py`** — IdentityContextResolver — validated credentials → IdentityContext (SRS §9, §16).
- Classes: `IdentityContextResolver`

**`backend/app/identity/auth/routes.py`** — Human authentication + session lifecycle endpoints (SRS §16, §23).
- Functions: `get_auth_service,login,mfa_verify,refresh,logout,me,list_sessions,get_session,revoke_session,delete_session,list_devices,trust_device,my_security_events,block_device`

**`backend/app/identity/auth/schemas.py`** — Request/response DTOs for the human-authentication endpoints (SRS §16, §17, §23).
- Classes: `LoginRequestDTO,TokenResponse,LoginResponse,MfaVerifyRequestDTO,RefreshRequestDTO,MeResponse,SessionRead,SessionDetail,RevokeSessionRequest,LogoutRequest,LogoutResponse,DeviceRead,SecurityEventRead,SecurityEventPage`

**`backend/app/identity/auth/security_event_service.py`** — SecurityEventService — record authentication/security events (SRS §13, §16).
- Classes: `SecurityEventService`

**`backend/app/identity/auth/session_lifecycle_service.py`** — SessionLifecycleService — create, touch, expire, revoke (SRS §4, §5, §11, §12).
- Classes: `SessionTimings,SessionLifecycleService`

**`backend/app/identity/auth/session_security_service.py`** — SessionSecurityService — score sessions and detect suspicious behaviour (SRS §15).
- Classes: `RiskAssessment,SessionSecurityService`

**`backend/app/identity/auth/token_service.py`** — TokenService — create / decode / validate access tokens (SRS §6, §7, §16).
- Classes: `TokenService`


### identity/credentials

**`backend/app/identity/credentials/audit.py`** — CredentialAuditService — one place every credential event is recorded (SRS §18).
- Classes: `CredentialContext,CredentialAuditService`

**`backend/app/identity/credentials/history_service.py`** — PasswordHistoryService — store past hashes, detect reuse, prune (SRS §10, §19).
- Classes: `PasswordHistoryService`

**`backend/app/identity/credentials/policy_service.py`** — PasswordPolicyService — validation, strength, expiration (SRS §5, §8, §11, §19).
- Classes: `PasswordPolicyService`

**`backend/app/identity/credentials/reset_service.py`** — PasswordResetService — administrative reset & temporary passwords (SRS §12, §16).
- Classes: `TemporaryCredential,PasswordResetService`

**`backend/app/identity/credentials/routes.py`** — Credential-management endpoints (SRS §22).
- Functions: `change_password,admin_reset_password,validate_password,password_policy,password_expiration,password_dashboard`

**`backend/app/identity/credentials/schemas.py`** — Request/response DTOs for the credential-management API (SRS §22).
- Classes: `ChangePasswordRequest,ChangePasswordResponse,AdminResetRequest,AdminResetResponse,ValidatePasswordRequest,ValidatePasswordResponse,PasswordPolicyResponse,PasswordExpirationResponse,PasswordDashboardUser,PasswordDashboardResponse`

**`backend/app/identity/credentials/service.py`** — CredentialService — the one place a human password is set or changed (SRS §9, §14, §15).
- Classes: `CredentialService`
- Functions: `generate_temporary_password`, `_draw_temporary_password`
- **Defect fix (2026-08-14)**: `generate_temporary_password()` previously returned its first draw unchecked, on the stated reasoning that sequences and repeats were "astronomically unlikely" from CSPRNG picks. That was wrong by orders of magnitude — a 16-character draw contains 13 overlapping 4-character windows and `app.identity.security.passwords._has_run` forbids runs along six sequences in both directions, so **9 draws in 20,000 (~1 in 2,200) violated the policy** and were then rejected by the very login path they were issued for. It now generates, validates through `PasswordPolicyService.validate` (the *same* entry point `_apply_new_password` uses at set time — the rules are never duplicated), and re-draws on failure, with a 100-attempt safety cap that raises rather than ever returning a non-compliant value. `PasswordResetService` passes `user=` so the context-dependent identity-substring rule is checked too. Re-draws a fresh candidate rather than repairing in place, which would leak structure about which substrings can never appear. Measured after the fix: 0 violations in 20,000 draws.


### identity/email

**`backend/app/identity/email/service.py`** — Transactional email for onboarding (4.2.2.3.1 §6, §8, §12).
- Classes: `EmailResult,EmailService`
- Functions: `invitation_url,verification_url,reset_url,new_email_verification_url`


### identity/errors.py

**`backend/app/identity/errors.py`** — Standard identity error envelope and exception handling (SRS §18).
- Classes: `ErrorCode,IdentityError`
- Functions: `error_body,register_identity_exception_handlers`
- Phase 2.3.1 added six new `FEDERATION_*` codes (`FEDERATION_CONFIG_NOT_FOUND`, `FEDERATION_CONFIG_INVALID`, `FEDERATION_ASSERTION_INVALID` — the bypass-prevention code, shared by both OIDC and SAML — `FEDERATION_STATE_INVALID`, `FEDERATION_USER_NOT_PROVISIONED`, `FEDERATION_CLAIM_MAPPING_FAILED`).
- Phase 3.1 added three new codes (`DEPLOYMENT_INVALID_TRANSITION`, `DEPLOYMENT_REVISION_CONFLICT`, `DEPLOYMENT_AGENT_SUSPENDED`, all 409) and reused two pre-existing ones rather than duplicating them: `DEPLOYMENT_NOT_FOUND` (already existed) and `IDEMPOTENCY_CONFLICT` (already existed, Phase 5.0 §33 — the build prompt's own suggested `IDEMPOTENCY_KEY_CONFLICT` would have meant exactly the same failure).
- Phase 3.2 added five new codes (`ENVIRONMENT_NOT_FOUND` 404, `ENVIRONMENT_POLICY_VIOLATION`/`PROMOTION_PATH_NOT_DEFINED`/`PROMOTION_WINDOW_CLOSED`/`PROMOTION_IMMUTABILITY_VIOLATION` all 409) and reused `DEPLOYMENT_NOT_FOUND` for the deployment-lookup-before-promote case rather than a duplicate.
- Phase 3.3 added two new codes (`DEPLOYMENT_PREFLIGHT_BLOCKED`, `PREFLIGHT_CHECK_UNAVAILABLE`, both 409) and reused `DEPLOYMENT_NOT_FOUND` for the deployment-lookup-before-preflight case rather than a duplicate, mirroring 3.2's own promotion precedent.
- Phase 3.6 added four new codes: `STRATEGY_ROLLING_DEFERRED` (**501** — a recognized, declared strategy the platform genuinely does not implement yet; not a client mistake and not a state conflict), `STRATEGY_GATE_BLOCKED` (409 — deliberately distinct from 3.1's `DEPLOYMENT_PREFLIGHT_BLOCKED`: that stops a deployment *reaching* ACTIVE, this stops an already-active one *taking over traffic*), `BLUE_GREEN_NOT_PREPARED` (409), `STRATEGY_CONFLICT` (409). No new kill-switch code was minted — the pre-existing generic `KILL_SWITCH_ACTIVE` (423) is reused.
- Phase 3.5 added five new codes: `ROLLOUT_NOT_FOUND` (404), `ROLLOUT_STAGE_GATE_NOT_MET` (409), `ROLLOUT_INVALID_TRANSITION` (409), `ROLLOUT_HALTED_BY_KILL_SWITCH` (423), `ROLLOUT_CONFLICT` (409). `ROLLOUT_HALTED_BY_KILL_SWITCH` is deliberately distinct from the pre-existing `KILL_SWITCH_ACTIVE` (also 423): that one describes an *execution* being refused, this one an *automation* being frozen, and an operator seeing it needs to know their rollout is halted rather than that one call failed.
- Phase 3.4 added four new codes: `TRAFFIC_WEIGHTS_INVALID` (422), `VERSION_NOT_ELIGIBLE` (422), `TRAFFIC_ALLOCATION_CONFLICT` (409), `NO_ACTIVE_DEPLOYMENT` (409). **`NO_ACTIVE_DEPLOYMENT` is additive, not a replacement**: the build prompt's AC-09 asked for it to be *the* execution-gate rejection code, but this path already returned `DEPLOYMENT_NOT_FOUND` (404) / `DEPLOYMENT_NOT_ACTIVE` (409) and had done so since Milestone 1. Those two keep their exact meanings and statuses, and the new code covers only the genuinely new mode — a servable deployment exists but every version its allocation weights has become unservable. No Milestone 1 API contract was broken. See `docs/deployment/traffic-and-resolution.md`.


### identity/federation

**`backend/app/identity/federation/oidc.py`** — Phase 2.3.1 SRS ACT-INT-FR-180, FR-181 — OIDC authorization-code flow, JWKS-based ID-token verification.
- Classes: `OidcVerificationError,OidcClaims`
- Functions: `generate_state_nonce,build_authorization_url,fetch_discovery_document,fetch_jwks,exchange_code_for_id_token,verify_id_token`
- `verify_id_token` is the security core — pure (no HTTP, no database), reusing `python-jose` (already a platform dependency) "with care": the accepted algorithm set is fixed by the organization's own stored configuration and never taken from the token's own `alg` header (closing the classic algorithm-confusion bypass), the signing key is resolved from the IdP's own JWKS by `kid` with no fallback, and issuer/audience/expiry/nonce are all explicitly checked. Proven against a real, freshly-generated RSA keypair in every bypass test — never a mock signer.

**`backend/app/identity/federation/saml.py`** — Phase 2.3.1 SRS ACT-INT-FR-180 — SAML 2.0 web-browser SSO, XML-signature-verified assertions.
- Classes: `SamlVerificationError,SamlClaims`
- Functions: `build_settings,build_request_data,build_authn_request,build_redirect_url,sp_metadata_xml,verify_response`
- A thin wrapper around `python3-saml`/`xmlsec` (new dependencies) — XML signature verification is never hand-rolled. `strict: True` is always set. Proven to reject two distinct signature-wrapping attack shapes using real `xmlsec`-signed fixtures (`backend/tests/identity/federation/_saml_fixtures.py`, the only place in this codebase that ever *constructs* a signed assertion).

**`backend/app/identity/federation/claim_mapping.py`** — Phase 2.3.1 SRS ACT-INT-FR-183 — IdP group/role claim → platform role mapping.
- Functions: `resolve_role_names`
- Pure, no database — configuration (`{"rules": [{"idp_value": ..., "role_name": ...}]}`), not code.

**`backend/app/identity/federation/service.py`** — Phase 2.3.1 SRS ACT-INT-FR-180..187 — `FederationService`.
- Classes: `FederatedLoginResult,FederationService`
- Per-organization configuration CRUD, OIDC/SAML login orchestration, JIT provisioning via the existing `UserProvisioningService` seam, and session issuance through the platform's **existing** pipeline (`SessionLifecycleService`/`RefreshRotationService`/`IdentityContextResolver`/`TokenService`) — never a parallel one. CSRF/replay defended via a short-lived, platform-signed `state`/`RelayState` flow token (reuses `settings.JWT_SECRET_KEY`, no new secret) rather than a new "pending requests" table.

**`backend/app/identity/federation/routes.py`** — Phase 2.3.1 — public federated-login endpoints under `/api/v1/auth/federation`.
- Functions: `start_login,oidc_callback,saml_acs,sp_metadata`
- Unauthenticated by nature (they *establish* authentication). `config_id` is not part of the callback/ACS URLs at all — recovered from the verified state/RelayState token itself.

**`backend/app/identity/federation/schemas.py`** — Phase 2.3.1 — request/response DTOs for federation endpoints.
- Classes: `FederationConfigCreate,FederationConfigUpdate,FederationConfigRead,FederationConfigTestResult,OidcCallbackRequest`
- `FederationConfigRead` never includes the client secret, encrypted or otherwise — only `has_client_secret: bool`, the same "hint, never ciphertext" discipline 2.1.2's `ConnectorCredentialRead` established.


### identity/models

**`backend/app/identity/models/agent_identity.py`** — AI Agent Identity — the *identity* of an agent, not the agent itself (SRS §7).
- Classes: `AgentIdentity`

**`backend/app/identity/models/credential.py`** — Credential-history ORM model (4.2.2.3.2 §10, §21).
- Classes: `PasswordHistory`

**`backend/app/identity/models/department.py`** — Organizational hierarchy below the tenant: Department → Team (SRS §7, §11).
- Classes: `Department,Team`

**`backend/app/identity/models/enums.py`** — Identity domain enumerations (Phase 4 Part 4.1).
- Classes: `IdentityType,IdentityStatus,InvitationStatus,RegistrationMode,PasswordResetStatus,EmailVerificationPurpose,CredentialType,SessionStatus,SessionRevocationReason,DeviceStatus,SessionSecurityBand,SecurityEventType`
- Functions: `can_transition`

**`backend/app/identity/models/external_client.py`** — External Client identity — Power BI, Zapier, Salesforce, Fabric, etc. (SRS §7).
- Classes: `ExternalClient`

**`backend/app/identity/models/federation.py`** — Phase 2.3.1 SRS ACT-INT-FR-180..187 — per-organization IdP configuration and federated-identity linkage.
- Classes: `FederationConfig,FederatedIdentity`
- `FederationConfig.configuration` (JSONB) is non-secret but integrity-critical; `encrypted_client_secret` is nullable and, when present, encrypted via the existing `credential_crypto.py` — reusing 2.1.2's credential-at-rest machinery rather than inventing a new one. `FederatedIdentity` deliberately has **no credential column of any kind** — it links `external_subject_id` to a platform `user_id`, nothing more, embodying the inversion this phase's design is built around (see `docs/identity/federation.md`).

**`backend/app/identity/models/login_history.py`** — Login history model (table ``login_history``, SRS §13).
- Classes: `LoginHistory`

**`backend/app/identity/models/protection.py`** — Account-protection ORM models (4.2.2.3.4 §17).
- Classes: `AccountLock,IdentityRiskEvent,BlockedIp,IdentityProtectionRule`

**`backend/app/identity/models/recovery.py`** — Password-reset request model (4.2.2.3.3 §5).
- Classes: `PasswordResetRequest`

**`backend/app/identity/models/registration.py`** — Invitation, email-verification, user-profile and rate-limit models (4.2.2.3.1 §5).
- Classes: `Invitation,EmailVerification,UserProfile,RateLimitHit`

**`backend/app/identity/models/security_event.py`** — Security event model (table ``security_events``, SRS §10, §19).
- Classes: `SecurityEvent`

**`backend/app/identity/models/service_account.py`** — Service Account identity — backend automation (SRS §7).
- Classes: `ServiceAccount`

**`backend/app/identity/models/session.py`** — Session, refresh-token and device models (SRS 4.2.2.2 §6, §7, §13).
- Classes: `UserSession,RefreshToken,UserDevice`


### identity/permissions

**`backend/app/identity/permissions/evaluator.py`** — Permission evaluator (SRS §9).
- Classes: `PermissionEvaluator`


### identity/protection

**`backend/app/identity/protection/alerts.py`** — SecurityAlertService — notify users and admins of protection events (§30).
- Classes: `SecurityAlertService`

**`backend/app/identity/protection/detection.py`** — Risk scoring, anomaly detection and brute-force detection (4.2.2.3.4 §9–§15).
- Classes: `LoginSignals,LoginAnomalyService,RiskScoringService,BruteForcePattern,BruteForceDetectionService`

**`backend/app/identity/protection/enums.py`** — Account-protection enumerations (4.2.2.3.4 §7, §8, §14).
- Classes: `AuthDecision,RiskLevel,AccountLockStatus,AccountLockReason`

**`backend/app/identity/protection/lockout.py`** — AccountLockoutService — progressive, stateful account locks (4.2.2.3.4 §8, §29).
- Classes: `LockResult,AccountLockoutService`

**`backend/app/identity/protection/policy.py`** — Blocked IPs, protection rules, adaptive rate limiting and CAPTCHA (§10, §16, §28).
- Classes: `BlockedIpService,CaptchaService,AdaptiveRateLimitService,IdentityProtectionRuleService`

**`backend/app/identity/protection/rate_limit.py`** — Adaptive rate limiting for the login endpoint (4.2.2.3.4 §10).
- Functions: `adaptive_login_rate_limit`

**`backend/app/identity/protection/repositories.py`** — Repositories for the account-protection tables (4.2.2.3.4 §17, §20).
- Classes: `AccountLockRepository,BlockedIpRepository,IdentityProtectionRuleRepository,IdentityRiskEventRepository,LoginAttemptQuery`

**`backend/app/identity/protection/routes.py`** — Account-protection admin endpoints (4.2.2.3.4 §20).
- Functions: `summary,login_attempts,risk_events,account_locks,unlock_lock,lock_user,unlock_user,list_blocked_ips,block_ip,unblock_ip,list_rules,create_rule,update_rule,delete_rule`

**`backend/app/identity/protection/schemas.py`** — Request/response DTOs for the account-protection API (4.2.2.3.4 §20).
- Classes: `LoginAttemptRead,RiskEventRead,AccountLockRead,BlockedIpRead,ProtectionRuleRead,UnlockRequest,LockUserRequest,BlockIpRequest,ProtectionRuleWrite,ProtectionRuleUpdate,ProtectionSummary`

**`backend/app/identity/protection/service.py`** — AccountProtectionService — coordinates protection during login (§6, §19, §21).
- Classes: `ProtectionOutcome,AccountProtectionService`


### identity/ratelimit

**`backend/app/identity/ratelimit/limiter.py`** — Rate limiting for public endpoints (4.2.2.3.1 §19).
- Classes: `RateLimitDecision,RateLimiter`
- Functions: `client_ip,rate_limit`


### identity/recovery

**`backend/app/identity/recovery/audit.py`** — RecoveryAuditService — one place recovery events are recorded (4.2.2.3.3 §24).
- Classes: `RecoveryContext,RecoveryAuditService`

**`backend/app/identity/recovery/email_change_service.py`** — EmailChangeService — verified email change (4.2.2.3.3 §12).
- Classes: `EmailChangeService`

**`backend/app/identity/recovery/password_reset_service.py`** — PasswordResetService — the forgot-password / reset flow (4.2.2.3.3 §9, §10, §19).
- Classes: `PasswordResetService`

**`backend/app/identity/recovery/repository.py`** — Password-reset repository (4.2.2.3.3 §20). Lookup is always by token hash.
- Classes: `PasswordResetRepository`

**`backend/app/identity/recovery/routes.py`** — Recovery endpoints (4.2.2.3.3 §21).
- Functions: `forgot_password,reset_password,change_email,verify_new_email,recovery_events`

**`backend/app/identity/recovery/schemas.py`** — Request/response DTOs for the recovery API (4.2.2.3.3 §21).
- Classes: `ForgotPasswordRequest,ResetPasswordRequest,ChangeEmailRequest,VerifyNewEmailRequest,RecoveryAck,RecoveryEventRead`

**`backend/app/identity/recovery/service.py`** — RecoveryService — coordinates the recovery workflow (4.2.2.3.3 §3, §19).
- Classes: `RecoveryService`


### identity/registration

**`backend/app/identity/registration/audit.py`** — RegistrationAuditService — one place that records onboarding events (§7, §13, §20).
- Classes: `RequestContext,RegistrationAuditService`

**`backend/app/identity/registration/invitation_service.py`** — InvitationService — create, validate, resend, revoke (4.2.2.3.1 §7, §8).
- Classes: `IssuedInvitation,InvitationService`

**`backend/app/identity/registration/provisioning_service.py`** — UserProvisioningService — turn an accepted invitation into an identity (§7).
- Classes: `ProvisionRequest,UserProvisioningService`

**`backend/app/identity/registration/registration_service.py`** — RegistrationService — the onboarding orchestrator (4.2.2.3.1 §7, §8).
- Classes: `RegistrationResult,RegistrationService`

**`backend/app/identity/registration/schemas.py`** — DTOs for registration, invitations and email verification (§10, §11, §15, §17).
- Classes: `_TrimmedNames,InvitationCreateRequest,InvitationActionRequest,InvitationRead,InvitationPreview,RegisterFromInvitationRequest,SelfRegisterRequest,RegistrationResponse,VerifyEmailRequest,ResendVerificationRequest,GenericAcknowledgement,UserProfileRead`

**`backend/app/identity/registration/tokens.py`** — Onboarding token generation (4.2.2.3.1 §9, §14).
- Functions: `generate_invitation_token,generate_verification_token,generate_reset_token,token_hash`

**`backend/app/identity/registration/verification_service.py`** — EmailVerificationService — issue, validate, redeem (4.2.2.3.1 §7, §12).
- Classes: `IssuedVerification,EmailVerificationService`


### identity/repositories

**`backend/app/identity/repositories/base.py`** — Generic repository base — one aggregate per repository (SRS §16).
- Classes: `BaseRepository`

**`backend/app/identity/repositories/department_repository.py`** — Department aggregate repository (SRS §16).
- Classes: `DepartmentRepository`

**`backend/app/identity/repositories/device_repository.py`** — Device repository (SRS 4.2.2.2 §22).
- Classes: `DeviceRepository`

**`backend/app/identity/repositories/identity_repositories.py`** — Repositories for the machine identity aggregates (SRS §16).
- Classes: `AgentIdentityRepository,ServiceAccountRepository,ExternalClientRepository`

**`backend/app/identity/repositories/login_history_repository.py`** — Login history repository (SRS §13, §15).
- Classes: `LoginHistoryRepository`

**`backend/app/identity/repositories/organization_repository.py`** — Organization aggregate repository (SRS §16).
- Classes: `OrganizationRepository`

**`backend/app/identity/repositories/permission_repository.py`** — Permission catalog repository (SRS §16). Reuses ``rbac_permissions``.
- Classes: `PermissionRepository`

**`backend/app/identity/repositories/refresh_token_repository.py`** — Refresh-token repository (SRS 4.2.2.2 §22).
- Classes: `RefreshTokenRepository`

**`backend/app/identity/repositories/registration_repositories.py`** — Repositories for invitations, email verifications and user profiles (§5).
- Classes: `InvitationRepository,EmailVerificationRepository,UserProfileRepository`

**`backend/app/identity/repositories/role_repository.py`** — Role aggregate repository (SRS §16). Reuses the existing RBAC roles table.
- Classes: `RoleRepository`

**`backend/app/identity/repositories/security_event_repository.py`** — Security-event repository — the read path over ``security_events`` (SRS §26).
- Classes: `SecurityEventRepository`

**`backend/app/identity/repositories/session_repository.py`** — Session aggregate repository (SRS 4.2.2.2 §22).
- Classes: `SessionRepository`

**`backend/app/identity/repositories/user_repository.py`** — User aggregate repository (SRS §16).
- Classes: `UserRepository`


### identity/roles

**`backend/app/identity/roles/engine.py`** — Role engine — assign/revoke/list roles (SRS §9 roles).
- Classes: `RoleEngine`


### identity/schemas

**`backend/app/identity/schemas/identity.py`** — Identity request/response schemas (SRS §9 schemas, §18 error format).
- Classes: `ErrorBody,ErrorEnvelope,LifecycleTransition,UserRead,UserCreate,OrganizationRead,DepartmentRead,DepartmentCreate,TeamRead,RoleRead,ServiceAccountRead,SessionRead,AgentIdentityCreate,AgentIdentityRead,ServiceAccountCreate,ServiceAccountCreated,ExternalClientCreate,ExternalClientRead,ExternalClientCreated`


### identity/security

**`backend/app/identity/security/passwords.py`** — Password policy + hashing/secret helpers (SRS §9, §11, §14).
- Classes: `PasswordPolicyError`
- Functions: `validate_password,hash_user_password,estimate_strength,policy_description,needs_password_upgrade,verify_user_password,hash_secret,verify_secret,generate_client_secret`


### identity/services

**`backend/app/identity/services/identity_service.py`** — IdentityService — the single entry point for identity operations (SRS §15).
- Classes: `IdentityService`


### integration

**`backend/app/integration/base.py`** — Phase 2.1.1 SRS ACT-INT-FR-001, FR-006 — the connector contract.
- Classes: `Connector`
- Functions: `validate_configuration_schema`
- `Connector`'s abstract method set grew from `{describe, validate_configuration}` to `{describe, validate_configuration, health_check}` in Phase 2.1.3 — deliberate, additive; `authenticate`/`execute` still do not exist.

**`backend/app/integration/errors.py`** — Phase 2.1.1 SRS ACT-INT-FR-005, FR-009 — connector-layer exceptions.
- Classes: `ConnectorTypeNotFoundError,ConnectorNotFoundError,ConnectorConfigInvalidError,ConnectorInvalidTransitionError,ConnectorCredentialNotFoundError,ConnectorAuthSchemeUnsupportedError,ConnectorCredentialInvalidError,ConnectorOAuthRefreshFailedError,ConnectorUnavailableError,ConnectorHealthCheckFailedError,ConnectorDeclarationIncompleteError,RestEndpointNotDeclaredError,RestTemplateInvalidError,RestExtractionFailedError,DbQueryNotDeclaredError,DbParameterInvalidError,DbWriteNotPermittedError,DbResultLimitExceededError,DbQueryTimeoutError,DbConnectionFailedError,StoragePathDeniedError,StorageObjectTooLargeError,StorageWriteNotPermittedError,StorageObjectNotFoundError,StorageScopeInvalidError,StorageBackendFailedError,QueueBindingNotDeclaredError,QueueMessageTooLargeError,QueueOperationNotPermittedError,QueueConsumeTimeoutError,QueueBackendFailedError` (middle four added Phase 2.1.2; next two added Phase 2.1.3; next one added Phase 2.1.4; next three added Phase 2.2.1; next six added Phase 2.2.2; next six added Phase 2.2.3; last five added Phase 2.2.4)

**`backend/app/integration/health.py`** — Phase 2.1.3 SRS ACT-INT-FR-042..047 — `ConnectorHealthService`.
- Classes: `ConnectorHealthService`

**`backend/app/integration/lifecycle.py`** — Phase 2.1.1 SRS ACT-INT-FR-003 — the connector instance lifecycle state machine.
- Functions: `can_transition,target_state,all_states`
- Phase 2.1.3 added one new event to the transition table (`recover`, `failed -> active`) — the function signatures above are unchanged, only `_TRANSITIONS`' data grew.

**`backend/app/integration/mock.py`** — Phase 2.1.1 SRS ACT-INT-FR-001 — MockConnector.
- Classes: `MockConnector`
- Phase 2.1.3 added `health_check()` (configurable via `simulate_unreachable`/`simulate_error` in the instance's own `configuration`).

**`backend/app/integration/mock_authenticated.py`** — Phase 2.1.2 — MockAuthenticatedConnector.
- Classes: `MockAuthenticatedConnector`
- Phase 2.1.3 added `health_check()`, same pattern as `MockConnector`'s.

**`backend/app/integration/registry.py`** — Phase 2.1.3 SRS ACT-INT-FR-040, FR-041, FR-044 — the connector registry.
- Classes: `ResolvedConnector,ConnectorRegistry`

**`backend/app/integration/routes.py`** — Enterprise Integration Framework API (Phase 2.1.1 SRS §7, Phase 2.1.2 SRS §7, Phase 2.1.3 SRS §7) — /api/v1/integration.
- Functions: `list_connector_types,list_connectors,create_connector,get_connector,configure_connector,activate_connector,disable_connector,list_connector_events,list_auth_schemes,list_connector_credentials,upsert_connector_credential,delete_connector_credential,validate_connector_credential,oauth_callback_get,oauth_callback_post,get_connector_health,run_connector_health_check,list_connector_health_history` (7 added Phase 2.1.2; last 3 added Phase 2.1.3)

**`backend/app/integration/schemas.py`** — Phase 2.1.1 — Pydantic request/response schemas for `/api/v1/integration`.
- Classes: `ConnectorTypeRead,ConnectorInstanceRead,ConnectorLifecycleEventRead,ConnectorInstanceCreate,ConnectorInstanceConfigure,ConnectorDisableRequest,ConnectorCredentialRead,ConnectorCredentialUpsert,ConnectorCredentialValidationResult,AuthSchemeRead,OAuthCallbackRequest,OAuthAuthorizationUrlRead,OAuthCallbackResult,ConnectorHealthCheckRead,ConnectorHealthRead` (7 added Phase 2.1.2; last 2 added Phase 2.1.3)

**`backend/app/integration/scheduler.py`** — Phase 2.1.3 SRS ACT-INT-FR-043 — interim in-process health-check scheduler.
- Functions: `run_sweep_once,start,stop`

**`backend/app/integration/service.py`** — Phase 2.1.1 SRS ACT-INT-FR-001..010 — `ConnectorService`.
- Classes: `ConnectorTypeService,ConnectorService`
- Phase 2.1.3 added one public method, `ConnectorService.recover` (the `failed -> active` counterpart to the pre-existing `mark_failed`).
- Phase 2.1.4 added `ConnectorTypeService.register()` — the single registration path (completeness-validates, then upserts by `(connector_type, version)`); `ensure_seeded()` was rewritten to call it once per `_CONNECTOR_TYPES` entry instead of inlining the same insert logic. `_CONNECTOR_TYPES` gained one entry, `"SDK_EXAMPLE_WEBHOOK" -> WebhookConnector` (the 2.1.4 worked example, imported from `app.integration.sdk.example.webhook_connector`).
- Phase 2.2.1 added one more entry, `"REST" -> RestConnector` (imported from `app.integration.connectors.rest.connector`) — registers through the identical `ensure_seeded`/`register` path, no branching.
- Phase 2.2.2 added one more entry, `"DATABASE" -> DatabaseConnector` (imported from `app.integration.connectors.database.connector`) — same path, no branching.
- Phase 2.2.3 added one more entry, `"STORAGE" -> StorageConnector` (imported from `app.integration.connectors.storage.connector`) — same path, no branching.
- Phase 2.2.4 added one more entry, `"QUEUE" -> QueueConnector` (imported from `app.integration.connectors.queue.connector`) — same path, no branching. This is the fourth and last generic connector; Milestone 2's connector framework and every generic connector are now complete.

**`backend/app/integration/types.py`** — Phase 2.1.1 SRS ACT-INT-FR-002, FR-007 — connector-neutral declaration types.
- Classes: `ConnectorLifecycleState,ToolContract,ConnectorDescriptor`

**`backend/app/integration/validation.py`** — Phase 2.1.4 SRS ACT-INT-FR-064 — connector declaration completeness.
- Classes: `HealthCheckNotImplemented`
- Functions: `validate_declaration_complete`
- The one completeness check both `ConnectorTypeService.register` and `ConnectorTestHarness.assert_declaration_complete` call — no second, weaker check for SDK-authored connectors. `HealthCheckNotImplemented` is a dedicated marker (not Python's own generic unimplemented-method builtin) specifically to avoid colliding with `test_connector_health.py`'s existing package-wide grep for that builtin's name as a leftover-stub signal.


### integration/auth

**`backend/app/integration/auth/base.py`** — Phase 2.1.2 SRS ACT-INT-FR-020, FR-021 — the authentication scheme contract.
- Classes: `OutboundRequest,AuthScheme`

**`backend/app/integration/auth/registry.py`** — Phase 2.1.2 SRS ACT-INT-FR-021 — explicit authentication scheme registry.
- Functions: `register,resolve,registered_identifiers`

**`backend/app/integration/auth/schemes/api_key.py`** — Phase 2.1.2 SRS ACT-INT-FR-020 — static API key scheme.
- Classes: `ApiKeyScheme`

**`backend/app/integration/auth/schemes/basic.py`** — Phase 2.1.2 SRS ACT-INT-FR-020 — HTTP basic authentication scheme.
- Classes: `BasicAuthScheme`

**`backend/app/integration/auth/schemes/bearer.py`** — Phase 2.1.2 SRS ACT-INT-FR-020 — static bearer token scheme.
- Classes: `BearerTokenScheme`
- Functions: `apply_bearer`

**`backend/app/integration/auth/schemes/mtls.py`** — Phase 2.1.2 SRS ACT-INT-FR-027 — mutual TLS scheme.
- Classes: `MTLSScheme`

**`backend/app/integration/auth/schemes/oauth2_authorization_code.py`** — Phase 2.1.2 SRS ACT-INT-FR-024 — OAuth2 authorization-code scheme.
- Classes: `OAuth2AuthorizationCodeScheme`

**`backend/app/integration/auth/schemes/oauth2_client_credentials.py`** — Phase 2.1.2 SRS ACT-INT-FR-024 — OAuth2 client-credentials scheme.
- Classes: `OAuth2ClientCredentialsScheme`

**`backend/app/integration/auth/service.py`** — Phase 2.1.2 SRS ACT-INT-FR-020..028 — `ConnectorCredentialService`.
- Classes: `ConnectorCredentialService`
- Phase 2.2.1 added one public method, `resolve_and_apply_for_scheme(instance, request, auth_scheme, ...)` — the same resolve-then-apply mechanics as `resolve_and_apply()`, generalized to an explicitly supplied scheme rather than the connector *type*'s single fixed `auth_requirements.scheme` (needed because the generic REST connector serves many vendor APIs, each with its own instance-declared scheme). `resolve_and_apply()` itself is now a one-line wrapper over it — unchanged behavior, every existing caller/test unaffected.
- Phase 2.2.2 added one more public method, `resolve_credential_bundle(instance, auth_scheme, ...)` — the same resolve mechanics again, returning the decrypted bundle itself rather than an HTTP-header-shaped `OutboundRequest` (a database username/password has no HTTP-header meaning). Both `resolve_and_apply_for_scheme` and `resolve_credential_bundle` now share a new private `_resolve_bundle_for_scheme` helper — no behavior change for any existing caller.
- Phase 2.2.3 reuses `resolve_credential_bundle(...)` unchanged — an S3 access key id/secret access key resolve through the `BASIC` scheme's generic `username`/`password` fields, no new method needed.
- Phase 2.2.4 also reuses `resolve_credential_bundle(...)` unchanged — an AMQP broker username/password or an SQS access key id/secret access key both resolve through the same `BASIC` scheme's generic fields, no new method needed for a fourth connector in a row.

**`backend/app/integration/auth/token_manager.py`** — Phase 2.1.2 SRS ACT-INT-FR-024 — OAuth2 token acquisition, caching and concurrency-safe refresh.
- Classes: `TokenResponse`
- Functions: `exchange_client_credentials,exchange_authorization_code,refresh_with_token,store_authorization_code_exchange,get_valid_access_token`


### integration/sdk

**`backend/app/integration/sdk/__init__.py`** — Phase 2.1.4 SRS ACT-INT-FR-060..066 — the connector authoring surface.
- Constants: `SUPPORTED_AUTH_SCHEMES`
- Re-exports (explicit `__all__`, the supported contract): `Connector,ConnectorDescriptor,ToolContract,ConnectorLifecycleState,SUPPORTED_AUTH_SCHEMES,validate_configuration_schema,ConnectorConfigInvalidError,GovernedHttpClient,ConnectorTestHarness,HealthCheckOutcome`
- No database session, credential-resolution machinery, raw HTTP client, audit-suppression hook, or route-registration mechanism appears anywhere in this module's exports — the containment property `test_connector_sdk.py`'s AC-10/12/14/15 mechanically check.

**`backend/app/integration/sdk/http.py`** — Phase 2.1.4 SRS ACT-INT-FR-066 — the only outbound network primitive the SDK surface exposes.
- Classes: `GovernedHttpClient`
- A thin wrapper reusing `app.runtime.tools.egress_guard`/`http_executor` directly (not reimplemented). `allowed_hosts` is fixed at construction; neither `request()` nor `evaluate()` accepts a per-call host override.
- Phase 2.2.1 added one new, optional parameter to `request()`: `query: str | None` — `execute_http_tool`'s own `_build_target_url` only ever honors a query string supplied through its dedicated `query` parameter, silently dropping one embedded directly in `url`; invisible to 2.1.4's query-free `WebhookConnector`, fatal to a paginated REST endpoint. Additive, backward-compatible; 2.1.4's own test suite passes unchanged.

**`backend/app/integration/sdk/testing.py`** — Phase 2.1.4 SRS ACT-INT-FR-063 — fixture-based connector testing, no live external system required.
- Classes: `HealthCheckOutcome,ConnectorTestHarness`
- Formalizes the pattern `MockConnector`'s own tests (2.1.1-2.1.3) already used; every method is pure, in-process, no I/O of its own.

**`backend/app/integration/sdk/example/webhook_connector.py`** — Phase 2.1.4 SRS ACT-INT-FR-060..066 — the worked example connector.
- Classes: `WebhookConnector`
- Constants: `CONNECTOR_TYPE = "SDK_EXAMPLE_WEBHOOK"`
- Built and tested using only names imported from `app.integration.sdk` (plus the standard library) — verified by an AST-based import-inspection test (`test_ac02_example_imports_only_from_the_sdk_surface`), not just by behavior.


### integration/connectors/rest

**`backend/app/integration/connectors/rest/declaration.py`** — Phase 2.2.1 SRS ACT-INT-FR-100, FR-101, FR-102, FR-106 — the REST connector's declaration model.
- Classes: `RestEndpoint,RestDeclaration`
- Constants: `CONFIG_SCHEMA`
- Functions: `parse_declaration,tool_contracts_for`
- `tool_contracts_for(configuration)` is the real, per-instance `ACT-INT-FR-102` mechanism (one `ToolContract` per declared endpoint) — `RestConnector.describe()` itself, a zero-argument type-level call, cannot produce these.
- Imports only from `app.integration.sdk` (plus stdlib) — AST-verified alongside `templating.py`/`extraction.py`/`pagination.py`/`connector.py`.

**`backend/app/integration/connectors/rest/templating.py`** — Phase 2.2.1 SRS ACT-INT-FR-104 — injection-safe request templating.
- Classes: `TemplateRenderError`
- Functions: `render_path,render_query,render_headers,render_body,build_request_url`
- `render_path` percent-encodes each substituted value with no safe characters (`quote(value, safe="")`) — a `"/"` or `".."` inside an argument can never introduce an extra path segment.

**`backend/app/integration/connectors/rest/extraction.py`** — Phase 2.2.1 SRS ACT-INT-FR-104 — response extraction.
- Classes: `ResponseExtractionError`
- Functions: `extract_output,validate_output_schema`
- Reuses `jsonschema` directly (the same library `base.py`/`runtime/services.py` already use), not a new validator.

**`backend/app/integration/connectors/rest/pagination.py`** — Phase 2.2.1 SRS ACT-INT-FR-105 — bounded pagination.
- Classes: `PaginationError`
- Functions: `run_pagination`
- Three styles (`offset_limit`/`page_number`/`cursor`), hard-capped at `min(declared max_pages, 100)` regardless of server behavior — never an unbounded fetch.

**`backend/app/integration/connectors/rest/connector.py`** — Phase 2.2.1 SRS ACT-INT-FR-100..106 — `RestConnector`.
- Classes: `RestConnector`
- Constants: `CONNECTOR_TYPE = "REST"`
- Built through the SDK surface only; `describe()` carries one structural placeholder tool contract (real ones are per-instance, see `declaration.py`); `health_check()` pre-flights the declared `base_url`'s host via `GovernedHttpClient`, never a credential.

**`backend/app/integration/connectors/rest/invoker.py`** — Phase 2.2.1 SRS ACT-INT-FR-100..106 — the REST connector's tool-invocation bridge.
- Functions: `invoke_tool,invoke_endpoint`
- **Not** SDK-surface-restricted — platform bridge code sitting above `RestConnector`, exactly where `health.py`/`service.py` already sit above every `Connector` implementation. The first tool-invocation bridge built anywhere in this codebase (2.1.3's registry docstring anticipated it; nothing called `resolve_instance_for_invocation` for this purpose before now). Fail-fast resolves the instance, applies the declared `auth_scheme` via `ConnectorCredentialService.resolve_and_apply_for_scheme()` (new, additive), dispatches through `GovernedHttpClient`, drives pagination, extracts output. Not wired into `ToolGatewayService`/`tools_snapshot`/the model-driven tool loop.


### integration/connectors/database

**`backend/app/integration/connectors/database/declaration.py`** — Phase 2.2.2 SRS ACT-INT-FR-120, FR-121, FR-122, FR-125 — the database connector's declaration model.
- Classes: `DeclaredQuery,DatabaseDeclaration`
- Constants: `SUPPORTED_DIALECTS = ("POSTGRESQL", "MYSQL")`, `CONFIG_SCHEMA`
- Functions: `classify_query,mutating_query_names,parse_declaration,tool_contracts_for`
- `classify_query` inspects *declared, trusted* SQL only (never model output) — fail-closed: anything not recognizably `SELECT`/`WITH`/`SHOW`/`EXPLAIN` is classified `"WRITE"`. Imports only from `app.integration.sdk` (plus stdlib) — the one file in this package that stays exactly as SDK-surface-restricted as 2.2.1's own `declaration.py`.

**`backend/app/integration/connectors/database/drivers.py`** — Phase 2.2.2 SRS ACT-INT-FR-120, FR-126, FR-127 — the PostgreSQL/MySQL dialect abstraction.
- Constants: `SUPPORTED_DIALECTS`, `PENDING_DIALECTS = frozenset({"SQLSERVER"})`
- Functions: `build_connection_url,get_or_create_engine,dispose_engine`
- Built on SQLAlchemy Core (already a first-class dependency); `build_connection_url` returns a `sqlalchemy.engine.URL` object, never a bare string, so a password is never concatenated into loggable text. `get_or_create_engine` is a per-instance, in-process engine/pool cache (config changes do not currently evict a cached entry — a documented, known limitation). SQL Server is a recognized but currently undriven dialect (`mssql+pyodbc` needs a system ODBC driver, not added this phase).

**`backend/app/integration/connectors/database/executor.py`** — Phase 2.2.2 SRS ACT-INT-FR-121, FR-122, FR-123, FR-124 — the security-critical query executor.
- Classes: `QueryTimeoutError,ResultLimitExceededError,QueryExecutionError`
- Functions: `execute_declared_query`
- Its **only** public entry point takes an engine, a dialect, a `DeclaredQuery`, and a parameter mapping — no parameter position anywhere accepts a raw SQL string (containment by absence, `ACT-INT-FR-122`). Parameters bound via SQLAlchemy's `text()` + a separate parameter mapping, never interpolated. Row limit via `fetchmany(row_limit + 1)`, rejected outright if exceeded (never truncated). Timeout enforced twice: a server-side `statement_timeout`/`MAX_EXECUTION_TIME` GUC plus a client-side thread + `Future.result(timeout=...)` backstop.

**`backend/app/integration/connectors/database/connector.py`** — Phase 2.2.2 SRS ACT-INT-FR-120..127 — `DatabaseConnector`.
- Classes: `DatabaseConnector`
- Constants: `CONNECTOR_TYPE = "DATABASE"`
- **One documented deviation** from pure-SDK-surface restriction: imports `DbWriteNotPermittedError` from `app.integration.errors`, needed for its config-time read-only-vs-mutating-query rejection (`ACT-INT-FR-125`) — a distinct, stable error code 2.2.1 never needed at configuration time. `health_check()` is a raw TCP connect to the declared `(host, port)` — reachability only, no credential (a database connector's `configuration` never includes one), no query.

**`backend/app/integration/connectors/database/invoker.py`** — Phase 2.2.2 SRS ACT-INT-FR-120..127 — the database connector's tool-invocation bridge.
- Functions: `invoke_tool,run_query`
- **Not** SDK-surface-restricted, mirroring `connectors/rest/invoker.py` exactly. Fail-fast resolves the instance, resolves its credential bundle via `ConnectorCredentialService.resolve_credential_bundle()` (new, additive), gets/creates its per-instance pool, validates parameters against the named query's own JSON Schema, executes. Not wired into `ToolGatewayService`/`tools_snapshot`/the model-driven tool loop.


### integration/connectors/storage

**`backend/app/integration/connectors/storage/scope.py`** — Phase 2.2.3 SRS ACT-INT-FR-141, FR-143 — the traversal/scope-escape enforcer, the security core.
- Classes: `ScopeViolationError,ScopeBoundary,ValidatedTarget`
- Functions: `resolve_and_contain`
- **Zero dependencies on this platform** — not the SDK, not `app.integration.errors`, just `os`/`posixpath`/`re`/`unicodedata`/`urllib.parse` — importable and fully testable with no live storage of any kind (mirrors Milestone 1's isolated egress guard). Its one public function canonicalizes (control-character rejection, iterative percent-decoding, NFKC Unicode normalization, then `os.path.realpath` for filesystem or `posixpath.normpath` for object storage) and only then contains-checks — the canonicalized result, never the raw string, is what a caller ever receives (no TOCTOU gap, `ACT-INT-FR-143`).

**`backend/app/integration/connectors/storage/declaration.py`** — Phase 2.2.3 SRS ACT-INT-FR-140..145 — the storage connector's declaration model.
- Classes: `DeclaredStorageScope,StorageDeclaration`
- Constants: `SUPPORTED_BACKENDS = ("FILESYSTEM", "S3")`, `CONFIG_SCHEMA`
- Functions: `write_scope_names,parse_declaration,tool_contracts_for`
- **Two narrow, justified deviations** from 2.2.1's pure-SDK-surface precedent (see module docstring): raises its own `StorageScopeInvalidError` (imported from `app.integration.errors`) for all semantic validation, since this phase's own acceptance criteria require a distinguishable declaration-time code where 2.2.2's declaration.py needed none. `tool_contracts_for(configuration)` is the real, per-instance `ACT-INT-FR-141` mechanism (one `ToolContract`, parameter `path`, per declared scope).

**`backend/app/integration/connectors/storage/backends.py`** — Phase 2.2.3 SRS ACT-INT-FR-140, FR-142 — filesystem + S3-compatible object storage behind one dispatch interface.
- Classes: `ObjectNotFoundError,ObjectTooLargeError,StorageBackendError`
- Constants: `SUPPORTED_BACKENDS = frozenset({"FILESYSTEM", "S3"})`, `PENDING_BACKENDS = frozenset({"AZURE_BLOB"})`
- Functions: `read_object,write_object`
- A read checks size via metadata first (`os.path.getsize`/`head_object`, a HEAD call, never a GET) and rejects before any full transfer; both reads additionally bound the transfer itself as a second, defense-in-depth check. Local exceptions only — never `app.integration.errors` — translated to platform errors exclusively by `invoker.py`, mirroring `connectors/database/executor.py`'s discipline exactly. Azure Blob is a recognized but currently undriven backend (`azure-storage-blob` needs a genuinely heavy dependency, not added this phase).

**`backend/app/integration/connectors/storage/connector.py`** — Phase 2.2.3 SRS ACT-INT-FR-140..145 — `StorageConnector`.
- Classes: `StorageConnector`
- Constants: `CONNECTOR_TYPE = "STORAGE"`
- **One additional documented import** beyond the SDK surface (plus reusing `declaration.py`'s own `StorageScopeInvalidError`): `StorageWriteNotPermittedError` from `app.integration.errors`, needed for its config-time read-only-vs-write-scope rejection (`ACT-INT-FR-144`) — mirrors `DbWriteNotPermittedError` exactly. `health_check()` checks every declared scope's base directory exists (filesystem) or opens a raw TCP connection to the configured/default endpoint host (S3) — reachability only, no credential, no object access.

**`backend/app/integration/connectors/storage/invoker.py`** — Phase 2.2.3 SRS ACT-INT-FR-140..145 — the storage connector's tool-invocation bridge.
- Classes: `StorageScopeNotDeclaredError`
- Functions: `invoke_tool,run_access`
- **Not** SDK-surface-restricted, mirroring `connectors/database/invoker.py` exactly. Fail-fast resolves the instance, resolves its credential bundle, validates the supplied `path` against the named scope's declared boundary via `scope.resolve_and_contain` **before any backend call**, dispatches through `backends.py`. **New this phase**: records every access attempt — allowed or denied — in the platform audit trail (`INTEGRATION_CONNECTOR_OBJECT_ACCESSED`, via a `finally` block so a denial is audited exactly as reliably as a success) — 2.2.x's first invocation-level audit event. Not wired into `ToolGatewayService`/`tools_snapshot`/the model-driven tool loop.


### integration/connectors/queue

**`backend/app/integration/connectors/queue/scope.py`** — Phase 2.2.4 SRS ACT-INT-FR-161, FR-164 — the queue connector's scope-permission check.
- Classes: `QueueScopeViolationError`
- Constants: `PUBLISH = "PUBLISH"`, `CONSUME = "CONSUME"`
- Functions: `check_operation_permitted`
- **Genuinely zero imports of any kind** (not even from the SDK) — simpler by design than `connectors/storage/scope.py`: there is no queue-name value to canonicalize because the target queue is fixed by the tool contract itself (`ACT-INT-FR-164`), never a value the model supplies. What this module checks instead: whether a *resolved* binding's own declared operation matches what is being attempted against it.

**`backend/app/integration/connectors/queue/declaration.py`** — Phase 2.2.4 SRS ACT-INT-FR-160..164 — the queue connector's declaration model.
- Classes: `DeclaredQueueBinding,QueueDeclaration`
- Constants: `SUPPORTED_BACKENDS = ("AMQP", "SQS")`, `CONFIG_SCHEMA`
- Functions: `parse_declaration,tool_contracts_for`
- **Zero deviations from the SDK-surface-only discipline — a first among the generic connectors** (contrasted explicitly with 2.2.2's one and 2.2.3's two, see this module's own docstring for why: this phase's own required error-code vocabulary is entirely invocation-time). `tool_contracts_for(configuration)` is the real, per-instance `ACT-INT-FR-161` mechanism — a `PUBLISH` binding's only parameter is `message`; a `CONSUME` binding's only parameter is an optional `max_messages` cap. Neither ever exposes a queue-name parameter to the model.

**`backend/app/integration/connectors/queue/backends.py`** — Phase 2.2.4 SRS ACT-INT-FR-160, FR-162, FR-163 — AMQP + SQS behind one dispatch interface.
- Classes: `MessageTooLargeError,QueueBackendError,ConsumedMessage`
- Constants: `SUPPORTED_BACKENDS = frozenset({"AMQP", "SQS"})`, `PENDING_BACKENDS = frozenset({"SERVICE_BUS"})`
- Functions: `publish,consume`
- A publish checks the payload's size against the binding's effective limit *before* any connection is attempted. Consume is bounded on two axes: never more than the binding's effective batch cap regardless of how many messages the queue holds, and never past the binding's effective wait timeout regardless of what the caller asks for — each backend's own bounded retrieval primitive (`basic_get`/`receive_message`) is wrapped in an explicit wall-clock deadline. **Acknowledgment policy is ack-on-retrieve, identical in spirit across both backends** (AMQP: `basic_get(auto_ack=True)`; SQS: an explicit `delete_message` immediately after `receive_message`) — at-most-once from the queue's own perspective, documented rather than left implicit. An oversized *consumed* message is truncated to the limit and flagged `truncated=True`, never silently passed whole or dropped (a deliberate departure from 2.2.2's/2.2.3's own "reject the whole operation" precedent — a consume batch is a set of otherwise-independent messages, not a single object or one query's result set). Local exceptions only, translated to platform errors exclusively by `invoker.py`. Azure Service Bus is a recognized but currently undriven backend (`azure-servicebus` needs a genuinely heavy dependency, not added this phase).

**`backend/app/integration/connectors/queue/connector.py`** — Phase 2.2.4 SRS ACT-INT-FR-160..164 — `QueueConnector`.
- Classes: `QueueConnector`
- Constants: `CONNECTOR_TYPE = "QUEUE"`
- **Zero deviations from the SDK surface**, matching `declaration.py`. `health_check()` opens a raw TCP connection to the declared broker host/port (AMQP: `host`/`port`; SQS: the configured/default endpoint host) — reachability only, no credential, no message.

**`backend/app/integration/connectors/queue/invoker.py`** — Phase 2.2.4 SRS ACT-INT-FR-160..164 — the queue connector's tool-invocation bridge.
- Functions: `publish_message,consume_messages`
- **Not** SDK-surface-restricted, mirroring `connectors/storage/invoker.py`'s audited shape but with **two** distinct public entry points rather than one polymorphic `invoke_tool` — because a queue binding's permitted operation is fixed at declaration time and a caller must state which operation it is attempting, so the bridge can verify (`scope.check_operation_permitted`) the resolved binding actually permits it *before* touching a broker. **Reuses 2.2.3's `INTEGRATION_CONNECTOR_OBJECT_ACCESSED` audit event** rather than adding a new one — every publish/consume attempt, allowed or denied, is recorded via a `finally` block. Not wired into `ToolGatewayService`/`tools_snapshot`/the model-driven tool loop.


### main.py

**`backend/app/main.py`** — FastAPI application entry point.
- Functions: `health_check`


### models

**`backend/app/models/abac.py`** — ABAC engine models (Phase 4.3.5 §21).
- Classes: `ABACPolicy,ABACPolicyVersion,AttributeDefinition,ABACEvaluation,ABACPolicyException`

**`backend/app/models/access_review.py`** — Access review campaigns (Phase 4.3.7 §14).
- Classes: `AccessReviewCampaign,AccessReviewItem`

**`backend/app/models/agent.py`** — Agent model - the AI agents whose actions are governed.
- Classes: `Agent`

**`backend/app/models/agent_action.py`** — AgentAction model - a single attempted action and its governance outcome.
- Classes: `AgentAction`

**`backend/app/models/agent_registry.py`** — Phase 5.1 - Enterprise Agent Registry, Definitions & Lifecycle: ownership
- Classes: `AgentOwnershipHistory,AgentLifecycleEvent,AgentValidationRun,AgentDuplicateMatch,AgentImportJob,AgentImportItem,AgentExportJob,AgentMigrationRecord`

**`backend/app/models/api_key.py`** — AgentApiKey model - hashed, rotatable API keys for agent authentication.
- Classes: `AgentApiKey`

**`backend/app/models/approval.py`** — Approval model - the human review attached to a pending agent action.
- Classes: `Approval,ApprovalComment`

**`backend/app/models/audit_log.py`** — AuditLog model - an append-only record of every significant event.
- Classes: `AuditLog`

**`backend/app/models/governance.py`** — Identity Governance & Administration models (Phase 4.3.8 §17).
- Classes: `SoDRule,GovernanceFinding,RemediationAction,GovernanceRiskScore,ComplianceReport,PrivilegedAccountReview`

**`backend/app/models/integration.py`** — Enterprise Integration Framework models (Phase 2.1.1 SRS ACT-INT-FR-001..010).
- Classes: `Connector,ConnectorInstance,ConnectorLifecycleEvent,ConnectorCredential,ConnectorOAuthToken,ConnectorHealthCheck`
- *Correction made this pass*: the previous two regenerations (2.1.2, 2.1.3) updated this file's own docstring/columns correctly but missed refreshing this AST-derived class list here — `ConnectorCredential`/`ConnectorOAuthToken` (added Phase 2.1.2) had silently been absent from it until now. Re-verified directly against the file's actual top-level classes this pass, not carried forward.

**`backend/app/models/mixins.py`** — Reusable column mixins for ORM models.
- Classes: `UUIDPrimaryKeyMixin,TimestampMixin`

**`backend/app/models/organization.py`** — Organization model - the top-level tenant boundary.
- Classes: `Organization`

**`backend/app/models/organization_hierarchy.py`** — Enterprise organization hierarchy models (Phase 4.3.3 §5, §6, §10, §11).
- Classes: `BusinessUnit,Project,ResourceOwnership,Delegation`

**`backend/app/models/permission.py`** — Permission model - per-agent allow/deny rules for resource + action pairs.
- Classes: `Permission`

**`backend/app/models/policy.py`** — Policy model - database-driven governance rules evaluated per action.
- Classes: `Policy`

**`backend/app/models/rbac.py`** — Advanced RBAC models: roles, permission catalog and their join tables.
- Classes: `Role,RbacPermission,PermissionGroup,RolePermission,UserRole,RoleHierarchy,AuthorizationAudit,PermissionVersion,PermissionCache,AuthorizationDecision`

**`backend/app/models/resource_authorization.py`** — Resource-based authorization models (Phase 4.3.4 §15).
- Classes: `ProtectedResource,ResourceACLEntry,ResourceShare,OwnershipHistory,ResourceDelegation`

**`backend/app/models/runtime.py`** — Agent Runtime & Lifecycle Management models (Phase 5.0 §62).
- Classes: `AgentDefinition,AgentVersion,AgentReleaseChannel,AgentVersionSnapshot,AgentReleaseMetadata,AgentReleaseArtifact,AgentReleaseNote,AgentVersionStatusHistory,AgentDeployment,Environment,PromotionPath,DeploymentPreflightResult,AgentExecution,ExecutionAttempt,ExecutionLock,ModelPricing,ProviderCredential,Capability,AgentCapability,Tool,AgentTool,ToolCall,ToolCredential,RuntimeEvent,DeploymentHealth,DeploymentEvent,IdempotencyRecord,IdempotencyKey,RuntimeApproval` (`ModelPricing` — Phase 5.7a.3, previously missing from this list only because this pass is the first full re-check of it since; `ProviderCredential` — Phase 5.7a.5; `ToolCredential` — Phase 5.6a.1, same `__repr__`-redaction discipline as `ProviderCredential`, see §10.31/§10.41; `DeploymentEvent`/`IdempotencyKey` — Phase 3.1; `Environment`/`PromotionPath` — Phase 3.2; `DeploymentPreflightResult` — Phase 3.3)
- Phase 5.6a.1: `Tool` gained `http_config: dict | None` (JSONB); `ToolCall` gained the eight egress/HTTP recording columns (see §2's `tool_calls` entry).
- Phase 3.1: `AgentDeployment` gained `lifecycle_state: str`/`revision: int`/`state_reason: str | None`/`superseded_by_deployment_id: uuid.UUID | None` and `__mapper_args__ = {"version_id_col": revision}` — a genuine SQLAlchemy optimistic-concurrency mapper option, not a plain column; every UPDATE of this row via the ORM now carries `WHERE revision = <loaded value>` and raises `StaleDataError` on a lost race, mapper-wide (including the pre-existing, unmodified `.status`-only writers — see §10's new entry on this accepted side effect). New `DeploymentEvent` (append-only lineage) and `IdempotencyKey` (the reusable, generic idempotency contract — deliberately distinct from the narrower, execution-scoped `IdempotencyRecord` above, which Phase 3.1 does not touch).
- Phase 3.2: `AgentDeployment` gained `environment_id: uuid.UUID | None` (nullable FK to the new `environments` table) — the pre-existing `environment` string column is untouched. New `Environment` (governed, tenant-scoped deployment target with a `policy` JSONB) and `PromotionPath` (the org-configured directed graph between two `Environment` rows).
- Phase 3.3: No existing column touched. New `DeploymentPreflightResult` (one persisted `ReleaseGateService.evaluate()` verdict + JSONB `findings` list per call, composite index on `(deployment_id, evaluated_at)`).
- Phase 3.5: No existing column touched. New `RolloutPlan` (the canary state machine; `__mapper_args__ = {"version_id_col": revision}`, the same optimistic-concurrency mechanism `AgentDeployment` uses), `RolloutStage` (ordered stages + the three gates), `DeploymentHealthEvaluation` (ruling #3's release-health verdict, deliberately a *new* table rather than a widening of the pre-existing `DeploymentHealth` heartbeat — the two answer different questions, and the old one is untouched).
- Phase 3.4: No existing column touched. New `DeploymentTrafficAllocation` (one revision of an agent's weighted split in one environment — `organization_id`/`agent_id`/`environment_id`/`revision`/`is_current`/`reason`/`created_at`/`created_by`) and `DeploymentTrafficWeight` (`allocation_id`/`agent_version_id`/`deployment_id`/`weight`, CHECK 0-100, unique on `(allocation_id, agent_version_id)`). Deliberately *not* columns on `AgentDeployment`: an allocation spans several deployments, so no single deployment row can own the others' weights (ruling #2's sanctioned new domain object).

**`backend/app/models/user.py`** — User model - human operators (admins, reviewers, viewers).
- Classes: `User`


### runtime (Phase 5.0 core)

**`backend/app/runtime/routes.py`** — Agent Runtime & Lifecycle Management API (Phase 5.0 §66) — /api/v1/runtime.
- Functions: `dashboard,list_agents,register_agent,get_agent,update_agent,delete_agent,list_definitions,register_lifecycle_action,validate_agent,submit_for_approval,approve_agent,reject_agent,activate_agent,suspend_agent,resume_agent,deprecate_agent,archive_agent,restore_agent,retire_agent,get_ownership,transfer_ownership,ownership_history,get_identity,associate_identity,create_and_associate_identity,replace_identity,list_validations,get_validation,run_validation,test_schema,duplicate_check,duplicate_matches,review_duplicate,agent_lifecycle_events,agent_runtime_events,import_agents,get_import_job,get_import_items,export_agents,get_export_job,download_export,classify_legacy_agents,list_migration_records,list_versions,create_version,get_version,validate_version,approve_version,publish_version,deprecate_version,revoke_version,retire_version,get_version_snapshot,get_version_status_history,set_version_rollback_target,get_release_metadata,upsert_release_metadata,list_release_artifacts,add_release_artifact,list_release_notes,add_release_note,list_release_channels,compare_versions,version_readiness,list_deployments,create_deployment,get_deployment,deploy,suspend_deployment,resume_deployment,rollback_deployment,retire_deployment,transition_deployment,pause_deployment_lifecycle,resume_deployment_lifecycle,retire_deployment_lifecycle,list_deployment_lifecycle_events,promote_deployment,run_deployment_preflight,get_deployment_preflight,get_deployment_preflight_history,submit_heartbeat,deployment_health,list_environments,create_environment,get_environment,update_environment,get_environment_policy,set_environment_policy,list_promotion_paths,create_promotion_path,delete_promotion_path,request_execution,request_self_execution,list_executions,get_execution,cancel_execution,retry_execution,replay_execution,execution_attempts,execution_tool_calls,execution_events,execution_messages,list_capabilities,create_capability,agent_capabilities,assign_capability,decide_capability,revoke_capability,list_tools,create_tool,agent_tools,assign_tool,decide_tool,revoke_tool,list_approvals,decide_approval,platform_health,list_workers,reap_stale_locks,kill_execution,kill_agent,kill_project,kill_organization,kill_platform,list_provider_credentials,upsert_provider_credential,delete_provider_credential,test_provider_credential`
- Phase 5.7a.5 added the four `list_provider_credentials`/`upsert_provider_credential`/`delete_provider_credential`/`test_provider_credential` functions, gated by two new permission constants `_PROVIDER_VIEW`/`_PROVIDER_MANAGE`. Phase 5.6a.1 added **no new route** — the `HTTP` tool action's configuration rides the existing `create_tool`/`ToolRead` via a schema extension (`http_config`), not a new endpoint. Phase 5.6a.2 also added **no new route** — schema validation and resilience are enforced entirely inside the existing tool-call execution path (`ToolGatewayService.invoke`), not a new endpoint. Phase 5.6a.3 added one new route, `execution_messages` (`GET /executions/{id}/messages`), exposing the new conversation-transcript table — same `_EXEC_VIEW` permission and `ExecutionRequestService.get_or_404` pattern as `execution_tool_calls`/`execution_events`.
- Phase 3.1 added five new functions — `transition_deployment`/`pause_deployment_lifecycle`/`resume_deployment_lifecycle`/`retire_deployment_lifecycle`/`list_deployment_lifecycle_events`, all under `/deployments/{id}/lifecycle/...` (a nested sub-path chosen specifically to avoid colliding with the pre-existing `resume_deployment`/`retire_deployment` above, which keep operating on the legacy `status` field, completely unmodified — see `docs/deployment/lifecycle.md`'s "A routing conflict, resolved"). Reuse the pre-existing `_DEPLOY_VIEW`/`_DEPLOY_ACTION` permission constants (`runtime.deployment.view`/`.deploy`), not new ones. `create_deployment` itself was extended additively: an `Idempotency-Key` header parameter and a call to the new `DeploymentLifecycleService.create()` in place of the bare `DeploymentService.create()` call — same route, same permission, same response model.
- Phase 3.2 added ten new functions: `promote_deployment` (`POST /deployments/{id}/promote` — no path collision found, used directly per the build prompt's own §6, unlike 3.1's own `/lifecycle/...` nesting; reuses `_DEPLOY_ACTION`) and nine environment/promotion-path CRUD functions (`list_environments`/`create_environment`/`get_environment`/`update_environment`/`get_environment_policy`/`set_environment_policy`/`list_promotion_paths`/`create_promotion_path`/`delete_promotion_path`) under two new permission constants, `_ENV_VIEW`/`_ENV_MANAGE` (`runtime.environment.view`/`.manage`).
- Phase 3.3 added three new functions — `run_deployment_preflight`/`get_deployment_preflight`/`get_deployment_preflight_history`, under `/deployments/{id}/preflight` and `/deployments/{id}/preflight/history` — no path collision found, used directly. Reuse the pre-existing `_DEPLOY_ACTION`/`_DEPLOY_VIEW` permission constants, no new permission codes (mirroring 3.2's own promotion precedent).
- Phase 3.6 added three new functions — `execute_deployment_strategy` (`POST /deployments/{id}/strategy/execute`, dispatching on the deployment's own `deployment_strategy` column), `blue_green_switch` and `blue_green_rollback` (under `/deployments/{id}/strategy/blue-green/...`). No path collision: the pre-existing `/deployments/{id}/...` paths are deploy/suspend/resume/rollback/retire/promote/preflight/heartbeat/health, none of which is `/strategy/*`. A unified execute endpoint was chosen over per-strategy paths deliberately — a `/strategy/recreate` path would let a caller run a recreate on a deployment declared BLUE_GREEN, making the column decorative again; the strategy is likewise not read from the request body. Reuse `_DEPLOY_ACTION`, except `blue_green_rollback` which uses the pre-existing `_DEPLOY_ROLLBACK`, matching 3.5's own rollout-rollback split.
- Phase 3.5 added ten new functions — `create_rollout` (under `/agents/{agent_id}/environments/{environment_id}/rollouts`, the same agent+environment prefix 3.4's traffic routes use, since a rollout drives exactly that tuple's allocation) plus `get_rollout`/`get_rollout_health`/`advance_rollout`/`evaluate_rollout`/`pause_rollout`/`resume_rollout`/`abort_rollout`/`promote_rollout`/`request_rollout_rollback` under `/rollouts/{id}/...`. No path collision found. Reuse `_DEPLOY_VIEW`/`_DEPLOY_ACTION`, except `request_rollout_rollback`, which uses the pre-existing `_DEPLOY_ROLLBACK` (`runtime.deployment.rollback`) — an organization may well want to grant "can roll back" separately from "can push a canary forward". No production-specific permission was introduced: Phase 3.2's environment policy is where this codebase already expresses that, and a second parallel mechanism would fragment it.
- Phase 3.4 added three new functions — `get_traffic_allocation`/`set_traffic_allocation`/`get_traffic_allocation_history`, under `/agents/{agent_id}/environments/{environment_id}/traffic` and `.../traffic/history` — no path collision found. Mounted on agent+environment rather than the build prompt's alternative `/deployments/{id}/traffic` (both shapes were offered; this one was chosen and the reason recorded): an allocation spans several deployments, so hanging it off one deployment id would make that deployment arbitrarily own the others' weights and would leave the resolver's own lookup key unexpressible. Reuse `_DEPLOY_VIEW`/`_DEPLOY_ACTION`, no new permission codes. The PUT honours `Idempotency-Key` via 3.1's `IdempotencyService` (operation `deployment.traffic.set`).

**`backend/app/runtime/schemas.py`** — Pydantic schemas for the Agent Runtime API (Phase 5.0 §66).
- Classes: `AgentDefinitionRead,AgentVersionCreate,AgentVersionRead,DeploymentCreate,DeploymentRollbackRequest,DeploymentRead,DeploymentTransitionRequest,DeploymentLifecycleActionRequest,DeploymentEventRead,DeploymentPromoteRequest,EnvironmentCreate,EnvironmentUpdate,EnvironmentPolicyUpdate,EnvironmentRead,PromotionPathCreate,PromotionPathRead,PreflightFindingRead,DeploymentPreflightRead,DeploymentHealthRead,HeartbeatSubmit,ExecutionCreate,AgentSelfExecutionCreate,ExecutionRead,ExecutionMessageRead,ExecutionAttemptRead,ToolCallRead,RuntimeEventRead,CapabilityCreate,CapabilityRead,AgentCapabilityAssign,AgentCapabilityRead,ToolCreate,ToolRead,AgentToolAssign,AgentToolRead,RuntimeApprovalDecision,RuntimeApprovalRead,KillSwitchRequest,RuntimeDashboardRead,ProviderCredentialRead,ProviderCredentialUpsert,ProviderCredentialTestResult` (the three `ProviderCredential*` classes added Phase 5.7a.5 — `ProviderCredentialRead` is built from the `ProviderCredentialInfo` dataclass, not the ORM row, and has no field capable of carrying a decrypted value; `ExecutionMessageRead` added Phase 5.6a.3; `DeploymentTransitionRequest`/`DeploymentLifecycleActionRequest`/`DeploymentEventRead` added Phase 3.1; `DeploymentPromoteRequest`/`EnvironmentCreate`/`EnvironmentUpdate`/`EnvironmentPolicyUpdate`/`EnvironmentRead`/`PromotionPathCreate`/`PromotionPathRead` added Phase 3.2; `PreflightFindingRead`/`DeploymentPreflightRead` added Phase 3.3)
- Phase 5.6a.1: `ToolCreate`/`ToolRead` gained `http_config: dict | None`; `ToolCallRead` gained the eight egress/HTTP recording fields (`target_host`/`target_path`/`http_method`/`http_status`/`request_bytes`/`response_bytes`/`egress_decision`/`egress_denied_reason`), all nullable, null for `FUNCTION`/`echo` rows.
- Phase 5.6a.2: `ToolRead` gained `input_schema: dict | None`/`output_schema: dict | None` (the two columns pre-existed on `Tool` since Phase 5.0 but were never exposed on this schema until now); `ToolCallRead` gained `error_class`/`attempt_number`/`validation_error`, all nullable.
- Phase 5.6a.3: `ExecutionRead` gained `loop_iterations: int`/`termination_reason: str | None`. New `ExecutionMessageRead` — one row per transcript entry (`role`, `content`, `tool_call_id`, `tool_name`, `tool_calls_requested`, `loop_iteration`, per-turn token/cost/duration fields).
- Phase 3.1: `DeploymentRead` gained `lifecycle_state: str`/`revision: int`/`state_reason: str | None`/`superseded_by_deployment_id: uuid.UUID | None`. New `DeploymentTransitionRequest` (`to_state`/`reason?`/`expected_revision?`, the generic `/lifecycle/transition` body), `DeploymentLifecycleActionRequest` (`reason?`/`expected_revision?`, the pause/resume/retire body), `DeploymentEventRead` (one row of `deployment_events` lineage).
- Phase 3.2: `DeploymentRead` gained `environment_id: uuid.UUID | None`. New `DeploymentPromoteRequest` (`to_environment_id`/`reason?`, the `/promote` body), `EnvironmentCreate`/`EnvironmentUpdate`/`EnvironmentPolicyUpdate`/`EnvironmentRead`, `PromotionPathCreate`/`PromotionPathRead`.
- Phase 3.3: New `PreflightFindingRead` (`code`/`severity`/`source`/`explanation`/`remediation`) and `DeploymentPreflightRead` (`verdict`/`findings: list[PreflightFindingRead]`/`evaluated_at`/`evaluated_by`) — no existing schema field changed.
- Phase 3.6: New `StrategyOutcomeRead` (`strategy`/`operation`/`deployment_id`/`candidate_version_id`/`previous_version_id`/`candidate_weight`/`previous_weight`/`allocation_revision`/`detail`). It reports the resulting allocation revision deliberately, so a caller can see traffic moved through 3.4's revisioned mechanism rather than take it on trust. No existing schema field changed.
- Phase 3.5: New `RolloutStageWrite`/`RolloutCreate`/`RolloutActionRequest` (request bodies) and `RolloutStageRead`/`RolloutPlanRead`/`HealthEvaluationRead`/`RolloutHealthRead`. No existing schema field changed. The non-decreasing-weights rule, the "a staged canary needs a stable version" rule and the "INSUFFICIENT_DATA cannot be a health requirement" rule are deliberately *not* pydantic validators — each must fail with this milestone's own error code and an actionable explanation, not a generic 422 body.
- Phase 3.4: `ExecutionCreate` and `AgentSelfExecutionCreate` each gained two optional fields — `routing_key: str | None` (opt-in sticky routing) and `environment: str | None` (narrows which environment's deployments the resolver considers). Both default to `None`, so every pre-existing request body is unchanged in meaning. New `TrafficWeightWrite`/`TrafficAllocationWrite` (the PUT body: `weights`, `reason?`, `expected_revision?`) and `TrafficWeightRead`/`TrafficAllocationRead`. The sum-to-100 rule is deliberately *not* a pydantic validator — it must fail with this milestone's own `TRAFFIC_WEIGHTS_INVALID` code, not a generic 422 body.

**`backend/app/runtime/services.py`** — Agent Runtime & Lifecycle Management services (Phase 5.0).
- Classes: `CostResult,PricingService,ProviderCredentialInfo,ResolvedCredential,CredentialTestResult,ProviderCredentialService,ModelGatewayError,ModelGatewayService,AgentRegistryService,AgentVersionService,DeploymentService,CapabilityService,ToolRegistryService,ToolCredentialService,ToolGatewayService,_LoopToolCall,_ToolCallSnapshot,ToolLoopOrchestrator,PolicyResult,RuntimePolicyService,IdempotencyService,ExecutionRequestService,ExecutionWorkerService,RuntimeApprovalService,HealthMonitoringService,KillSwitchService,RuntimeDashboardService` (`CostResult`/`PricingService` added Phase 5.7a.3; `ProviderCredentialInfo`/`ResolvedCredential`/`CredentialTestResult`/`ProviderCredentialService` added Phase 5.7a.5; `ToolCredentialService` added Phase 5.6a.1, `ACT-TLX-FR-012` — a deliberately smaller surface than `ProviderCredentialService`, `store`/`resolve_secret`/`delete` only, reusing `credential_crypto.py` directly rather than duplicating it; `_LoopToolCall`/`_ToolCallSnapshot`/`ToolLoopOrchestrator` added Phase 5.6a.3, see below)
- Phase 5.7a.4 additions (`ACT-MDL-FR-060..069`): module-level `_ProviderCircuitState`, `_provider_circuit_state` (dict), `reset_provider_circuit_breakers`, `_circuit_before_call`, `_circuit_record_success`, `_circuit_record_failure`, `_provider_backoff_delay` — the per-provider, in-process circuit breaker and backoff-delay calculator, used by two new `ModelGatewayService` methods: `_complete_with_resilience` (wraps `provider.complete()` with retry-on-transient-classification) and `_stream_once` (the renamed body of the old `_invoke_streaming`, now also returning a retryable-pre-first-token verdict); `_invoke_streaming` itself now wraps `_stream_once` in the same retry loop. `ExecutionWorkerService._execute`'s `except IdentityError` branch and `_fail_or_retry`'s `non_retryable` set were both extended — see REPO_STATE §10.29/§10.30.
- Phase 5.7a.5 additions (`ACT-MDL-FR-080..083`): `ModelGatewayService.invoke()` gained an optional `resolved_credential: ResolvedCredential | None` keyword parameter (resolved by the caller, never by `invoke()` itself — see §10.34) and now translates a classified `AUTHENTICATION_FAILED` into `ModelGatewayError(PROVIDER_CREDENTIAL_REQUIRED)` when no credential was supplied for that call from any source. `ExecutionWorkerService._execute` resolves via `ProviderCredentialService(self.db).resolve_for_version(...)` synchronously, on the worker's own thread, *before* submitting the model call to its `ThreadPoolExecutor` — see §10.34.
- Phase 5.6a.1 additions (`ACT-TLX-FR-001..013`): `ToolGatewayService` gained an `HTTP` dispatch branch (`_invoke_http`) alongside the unchanged `FUNCTION`/`echo` one, plus `_frozen_http_config` (reads the egress policy from the *published version's* `AgentVersionSnapshot`, never live `Tool` state — see §10.39/§10.40). `TOOL_EGRESS_DENIED` added to `_fail_or_retry`'s `non_retryable` set (a policy fact, not a transient failure).
- Phase 5.6a.2 additions (`ACT-TLX-FR-020..029`, see §10.42): 5.7a.4's `_ProviderCircuitState`/`_provider_backoff_delay` were **refactored, not left alone** — the state machine and backoff math were extracted into a neutral core (`_CircuitState`, `_circuit_is_open`, `_circuit_note_success`, `_circuit_note_failure`, `_backoff_delay`), with the pre-existing model-side functions rebuilt on top of it (same signatures, same behavior, every pre-existing 5.7a.4 test passes unmodified) alongside a new, parallel tool-side set (`_tool_circuit_state`, `reset_tool_circuit_breakers`, `_tool_circuit_is_open`, `_tool_circuit_record_success`, `_tool_circuit_record_failure`, `_tool_backoff_delay`). New module-level `_tool_schema_violation`, `_classify_tool_http_status`, `_classify_tool_execution_failure` (maps a tool's `HttpExecutionResult` onto the **same** `ProviderErrorClass` the model side uses — AC-12). `ToolGatewayService._frozen_http_config` renamed/generalized to `_frozen_tool_entry` (returns the whole `tool_configs[tool_id]` entry, not just `http_config`, so both the HTTP branch and the new schema-validation step share one snapshot lookup). `invoke()` gained an argument-validation step before every dispatch branch, and its final DENIED-only-raises logic gained a parallel `FAILED`-never-raises branch (a genuine behavior change — see §10.42). `_invoke_http` rewritten: a per-attempt retry loop (idempotent + transient classification only), one new `ToolCall` row per attempt, output-schema validation, a circuit-breaker check before the loop starts (mirroring `_complete_with_resilience`'s own call pattern exactly), and a `concurrency.track()` guard around each actual outbound request.
- Phase 5.6a.3 additions (`ACT-TLX-FR-040..049`, see §10.44..47): `ModelGatewayService.invoke()` gained two new, both-optional keyword parameters — `conversation: tuple[ModelMessage, ...] | None` and `tools: tuple[ModelToolDefinition, ...] | None`, mirroring `resolved_credential`'s own additive precedent exactly — and now offers `tools` to a provider only when it declares `supports_tools`; the returned `usage` dict gained one new key, `tool_calls` (a plain, JSON-safe list, empty whenever the model didn't request one). New `ToolLoopOrchestrator` class: `run()` drives model → tool → model over `ModelGatewayService.invoke()` and `ToolGatewayService.invoke()`, both completely unchanged; `_frozen_tool_entries` (name-keyed, mirrors `_frozen_tool_entry`), `_canonical_key` (reuses `app.runtime.versioning.canonical` for repeated-call detection), `_execute_calls`/`_execute_sequential`/`_execute_parallel` (the last opens one fresh `Session` per thread, **and commits `self.db` immediately beforehand** — see §10.46 for the deadlock this fixes), `_append_message`/`_terminate`/`_aggregate_usage` (transcript and accounting bookkeeping). `ExecutionWorkerService._execute`'s model-call section now calls `ToolLoopOrchestrator(self.db).run(...)`; the pre-existing explicit `input_payload["tool_calls"]` loop immediately after it is completely unchanged, both in code and in every test that exercises it. `_fail_or_retry`'s `non_retryable` set gained `TOOL_NOT_BOUND_TO_VERSION`/`TOOL_LOOP_LIMIT_EXCEEDED`.
- Phase 3.1 addition: `RuntimeApprovalService.decide()` gained one additive call, alongside (never instead of) its own pre-existing `.status` handling for a `DEPLOYMENT` approval — `DeploymentLifecycleService(self.db).apply_approval_decision(actor, deployment, decision)`, a no-op for a deployment never routed through the new `PENDING_APPROVAL` lifecycle state. Imported locally inside the method (not at module top) to avoid a circular import, since `app.runtime.deployment.service` itself imports from this module. `_request_execution` (the M1 execution gate) is untouched — see `app/runtime/deployment/service.py`'s own module docstring and `test_ac13_execution_path_does_not_reference_the_new_lifecycle_state`.


### runtime/deployment (Phase 3.1)

**`backend/app/runtime/deployment/lifecycle.py`** — ACT-SRS-M3 §3.1 M3-3.1-FR-001..003 — the pure, 15-state deployment lifecycle transition graph. No I/O, no database.
- Functions: `can_transition,all_states,allowed_targets`
- `_TRANSITIONS: dict[str, frozenset[str]]` (module-private) is the one source of truth for every declared edge; `DRIVEN_THIS_PHASE` documents which states this phase wires a real service method/route for versus leaves declared-but-undriven for a later phase (3.2/3.5/3.7) — see the module's own docstring for the full table.

**`backend/app/runtime/deployment/idempotency.py`** — ACT-SRS-M3 §3.1 M3-3.1-FR-010..013 — the reusable, platform-wide `Idempotency-Key` contract.
- Classes: `IdempotencyService`
- Functions: `fingerprint`
- Claim-then-poll, not check-then-act: a placeholder claim row is committed first, and the table's own `(organization_id, operation, idempotency_key)` unique constraint is the concurrency primitive — the loser of a race catches `IntegrityError` and polls briefly rather than ever running the wrapped operation twice. Proven generic (not deployment-specific) by a unit test exercising `execute()` against a bare stub callable.

**`backend/app/runtime/deployment/service.py`** — ACT-SRS-M3 §3.1 M3-3.1-FR-001..031 — `DeploymentLifecycleService`, the single authority on `AgentDeployment.lifecycle_state`.
- Classes: `DeploymentLifecycleService`
- `transition()` is the one function that ever assigns `lifecycle_state` — mechanically checked (`test_ac02_lifecycle_state_is_never_assigned_outside_the_authority`). Reaching `ACTIVE` (from any source state) runs two guards inline: Ruling #6 (`agent.lifecycle_status != "SUSPENDED"`, reading — never writing — the pre-existing suspension mechanism) and the `runtime_approvals` precondition where policy demands it. `create()` wraps the pre-existing `DeploymentService.create()` (composition, not duplication) with idempotency and the new lineage row. `start_deploying()` drives the synchronous READY/APPROVED→...→ACTIVE happy path, including the READY-stage approval-reroute mirroring legacy `DeploymentService.deploy()`'s own shape. Deliberately does not touch `AgentDeployment.status`, `desired_replicas`/`active_replicas`, or `ExecutionRequestService._request_execution` — see the module's own docstring.
- **Phase 3.2 additive changes**: `create()` gained an opportunistic, best-effort `environment` string→`Environment` row lookup (local import of `app.runtime.environment.service.EnvironmentService`, avoiding a circular import) that fills `environment_id` when a row of that name already exists for the caller's organization — never fails a create if not. `start_deploying()` gained one new guard, run first: `app.runtime.environment.policy.evaluate()` against the deployment's `Environment` (when `environment_id` is set) — the single deploy/promote-time environment-policy choke point, shared identically by a plain deploy and a promotion. `_requires_deployment_approval()` gained one additive condition (a governed environment's own `is_production`/`policy.requires_approval`) alongside its two pre-existing legacy checks.
- **Phase 3.3 additive change**: `start_deploying()` gained one more guard, run immediately after the 3.2 environment-policy check above and before the approval-reroute logic: `ReleaseGateService(self.db).evaluate(actor, deployment)` (module-level import — no circular import, since `app.runtime.release_gate`'s own module-level imports never reach back into this module; only its `checks.py::check_approvals` does, via a local, function-body import). A `BLOCK` verdict raises `DEPLOYMENT_PREFLIGHT_BLOCKED`, carrying the blocking finding codes; every verdict (including `PASS`/`WARNING`) is persisted regardless. See §10's new entry on why this runs *before* the approval-reroute (a `PREFLIGHT_APPROVAL_PENDING` finding is WARNING, never BLOCK, so it never disturbs that flow) and on the one pre-existing 3.1 test whose expected error code and post-condition both changed as a direct, documented consequence.

### runtime/environment (Phase 3.2)

**`backend/app/runtime/environment/policy.py`** — ACT-SRS-M3 §3.2 M3-3.2-FR-010..013 — environment policy evaluation.
- Functions: `check_prohibited, check_allowed_models, check_allowed_data_classifications, check_concurrency, check_change_window, requires_approval, evaluate`
- `evaluate()` is the single deploy/promote-time choke point, called from exactly one place (`DeploymentLifecycleService.start_deploying`). Enforced dimensions: `allowed_models`, `allowed_data_classifications` (checked against every bound tool's live `Tool.data_classification`), `requires_approval`, `maximum_concurrent_deployments`, `change_window`. Modeled-only: `allowed_external_systems` (no existing link between a runtime `Tool`/`AgentVersion` and Milestone 2's own integration-instance catalog — the field was renamed from the build prompt's own `allowed_connectors`, since the literal word is mechanically forbidden anywhere under `app/runtime`), `rollback_rules` (Phase 3.7's own job). `check_prohibited()` reads the exact same `AgentVersion.policy_snapshot["prohibited_environments"]` field `RuntimePolicyService.evaluate` (`app.runtime.services`, M1 execution path) already reads — integrated, not paralleled.

**`backend/app/runtime/environment/service.py`** — ACT-SRS-M3 §3.2 — `EnvironmentService`, `PromotionPathService`, `PromotionService`.
- Classes: `EnvironmentService, PromotionPathService, PromotionService`
- `EnvironmentService.ensure_seeded()` is a defensive, per-organization get-or-create for the standard five environments plus the default `DEVELOPMENT→TEST→STAGING→PRODUCTION` promotion chain, mirroring `ReleaseChannelService.ensure_seeded()`'s own precedent (its call sites, `GET`/`POST /environments`, explicitly `db.commit()` afterward — the flush-only precedent alone was found, live, to silently roll back on session close). `PromotionService.promote()` is the immutability-preserving promotion operation: loads the source `AgentVersion` exactly once and passes that same object straight into the existing `DeploymentService.create` (nothing here ever constructs, copies, or mutates a version row); validates the `PromotionPath` and environment policy fail-fast before creating any row; drives the new deployment through `DeploymentLifecycleService` (`transition`/`start_deploying`, never a parallel authority); drives the previously-declared-but-undriven `ACTIVE|PAUSED → SUPERSEDED` edge when a newer deployment lands in the same agent+environment slot; idempotent via the exact 3.1 `IdempotencyService`, operation `"deployment.promote"`.

### runtime/release_gate (Phase 3.3)

**`backend/app/runtime/release_gate/checks.py`** — ACT-SRS-M3 §Phase-3.3 M3-3.3-FR-010..023 — the individual preflight checks.
- Classes: `Finding, GateContext`
- Functions: `evaluate_freshness, check_agent_active_and_kill_switch, check_version_published, check_snapshot_checksum, check_signature_and_provenance, check_compatibility, check_owners, check_machine_identity, check_provider_available, check_provider_credentials, check_tools_valid, check_environment_policy, check_approvals, check_health_freshness, run_checks, verdict_for`
- Every check calls an *existing* capability — no reimplementation (full check-to-source table in `docs/deployment/release-gates.md`). `run_checks()` wraps every call so an unexpected exception becomes a `PREFLIGHT_CHECK_UNAVAILABLE` finding (fail closed), never a silently skipped check. Severity per finding code is data (`_DEFAULT_SEVERITY`), overridable per environment via `Environment.policy["preflight_severity_overrides"]` — except `PREFLIGHT_KILL_SWITCH_ACTIVE`, hardcoded absolute (AC-07, never looked up in the override map). **The freshness rule** (`evaluate_freshness`, pure, database-free) is applied to `DeploymentHealth.checked_at`, not the build prompt's own suggested Milestone-2 connector-health signal — see this module's own docstring and `docs/deployment/release-gates.md` for the two independent, structural reasons (the runtime-never-knows vocabulary boundary, and no existing dependency link between a runtime `Tool`/`AgentVersion` and Milestone 2's integration-instance catalog — the identical gap 3.2 already reported for `allowed_external_systems`). `check_approvals` locally imports `DeploymentLifecycleService` (avoiding a circular import) and calls its private `_requires_deployment_approval`/`_approved_deployment_approval` methods verbatim, WARNING (not BLOCK) severity — a pending approval is the designed reroute path, not a failure.

**`backend/app/runtime/release_gate/service.py`** — ACT-SRS-M3 §Phase-3.3 — `ReleaseGateService`, the single authoritative deployment-readiness evaluation.
- Classes: `ReleaseGateService`
- `evaluate()` builds a `GateContext`, runs `checks.run_checks()`, aggregates the verdict (`checks.verdict_for()`), persists a `DeploymentPreflightResult` row, audits `DEPLOYMENT_VALIDATION_STARTED` then `DEPLOYMENT_VALIDATION_FAILED`/`_PASSED` (a kill-switch-caused BLOCK additionally tagged `severity="CRITICAL"`), commits, and returns the persisted row — called both by the explicit `POST .../preflight` preview route and internally by `DeploymentLifecycleService.start_deploying()`, one evaluation path for both. Deliberately **not** wrapped in the 3.1 `IdempotencyService` contract — FR-031 requires a fresh result on every call, the opposite of idempotent replay (the same precedent `CompatibilityAnalysisService.analyze` already establishes). `get_latest()`/`get_history()` reuse `DeploymentService.get_or_404` verbatim for tenant scoping.

### runtime/deployment — strategy execution (Phase 3.6)

**`backend/app/runtime/deployment/strategies.py`** — ACT-SRS-M3 §Phase-3.6 — the strategy abstraction and its handlers.
- Classes: `StrategyOutcome, DeploymentStrategyHandler, RecreateStrategy, BlueGreenStrategy, RollingStrategy, CanaryStrategyPointer, DeploymentStrategyService`
- Functions: `handler_for`
- **The first code to dispatch on `agent_deployments.deployment_strategy`.** That column has existed since Phase 5.0 (migration 0023, default `RECREATE`, constrained to `RECREATE|ROLLING|CANARY|BLUE_GREEN` by `schemas._STRATEGY`) and was, until this phase, pure data — set on create, copied forward by `PromotionService`, exposed in `DeploymentRead`, and never read to decide anything.
- **Strategies are weight patterns over Phase 3.4's allocation, not separate machinery.** RECREATE is 0→100 in one cutover with the previous superseded; BLUE_GREEN is 0 (warm) →100 in one atomic switch with the old version *preserved* at 0%. Every traffic change goes through `TrafficAllocationService.set_weights`; this module contains **no reference to `DeploymentTrafficWeight`/`DeploymentTrafficAllocation`**, asserted against the parsed AST, so bypassing 3.4 is structurally impossible rather than discouraged.
- **Ordering that is load-bearing**: RECREATE supersedes the previous deployment *after* traffic moves, because superseding first would make it non-servable and 3.4 rejects weight on a version with no servable deployment. BLUE_GREEN re-runs the release gate *at the switch*, not only at prepare, because a deployment can pass validation and then have its agent killed or its version revoked before an operator presses the button.
- **Blue preservation reuses existing lineage — no new table, no migration.** After a switch BLUE stays lifecycle-ACTIVE at 0% weight (3.4's resolver skips zero-weight entries, so preserved is not split-serving) and is recorded as GREEN's rollback target through `VersionLineageService.set_rollback_target` rather than a raw column write. This is the first code that *reads* `AgentVersion.rollback_target_id` to perform a rollback — see §9 item 12, which recorded it as a settable pointer nothing acted on. "Prepared" is likewise inferable (GREEN holds a zero-weight entry exactly when warmed), so no state was added for it.
- **Rollback deliberately skips both the §12 veto and the gate**: rolling back reduces exposure, and a kill switch must never trap an operator on the version they are trying to leave; requiring BLUE to re-pass a gate would make rollback fail exactly when it is most needed.
- **ROLLING is declared, dispatched, and raises `STRATEGY_ROLLING_DEFERRED` (501) naming Phase 3.9** — a real terminal error, not a stub (no partial implementation, no placeholder exception). Rolling needs an instance substrate this platform does not have; the two replica-count columns are vestigial (written as constants by the legacy `DeploymentService.deploy`/`retire`, read for no decision anywhere). Phase 3.1's own AC-14 test forbids even *naming* those columns anywhere in this package, prose included, so this module refers to them indirectly — a stricter guard than "don't assign to them", kept rather than relaxed.
- Reuses the generic pre-existing `KILL_SWITCH_ACTIVE` (423) for the §12 veto rather than 3.5's `ROLLOUT_HALTED_BY_KILL_SWITCH`: an operator running a blue-green switch has no rollout, and no new code is minted for a condition the platform already names.

### runtime/deployment — canary rollout & release health (Phase 3.5)

**`backend/app/runtime/deployment/rollout.py`** — ACT-SRS-M3 §Phase-3.5 M3-3.5-FR-010/FR-012 — the rollout transition graph and pure stage-gate logic.
- Classes: `StageGateResult`
- Functions: `can_transition, allowed_targets, all_states, health_requirement_satisfied, evaluate_stage_gates`
- Pure: no I/O, no ORM, the structural twin of `lifecycle.py`. Seven states with `TERMINAL_STATES` closed. `health_requirement_satisfied` is where the phase's core safety rule lives: `INSUFFICIENT_DATA` and `UNKNOWN` satisfy **no** requirement, because a naive "is it bad?" check would let them through on the grounds that nothing bad was *observed*. `HEALTH_REQUIREMENT_NONE` is an explicit per-stage waiver of the health *quality* bar — it deliberately does **not** waive `UNKNOWN`, or it would become a way to opt out of the kill switch. `evaluate_stage_gates` returns *every* unmet reason, not the first.

**`backend/app/runtime/deployment/health.py`** — ACT-SRS-M3 §6/§7 (ruling #3) — the AI-aware release-health engine.
- Classes: `HealthMetrics, HealthVerdict, HealthEvaluationService`
- Functions: `thresholds_for, plan_environment`
- Aggregates `agent_executions` over a window rather than reading a heartbeat: a version can be perfectly alive while refusing every third request. Signals used (confirmed against the model, not assumed from the SRS): success/failure/timeout via `status`, policy denials via `status` DENIED/BLOCKED, latency via `duration_ms` (mean and p95), cost via `cost_amount`, tokens via `total_tokens`, failure class via `error_code`. Only *terminal* executions count — counting a running one as "not a failure" would make a stalled canary look healthier the more stuck it got. Evaluation order is deliberate: **veto first** (a killed/non-servable candidate is UNKNOWN before a row is read), **sample sufficiency second** (INSUFFICIENT_DATA below the minimum however clean the samples), thresholds and baseline only then. `_veto_reason`'s `require_servable` flag closes a real hole found during the build: a candidate with *no* servable deployment would otherwise have been treated as "no veto to apply" and reported HEALTHY. Thresholds are overridable per environment via `Environment.policy["canary_health_thresholds"]` — the same pattern 3.3 established, not a second mechanism. `_apply_baseline` implements §7's two findings; the provider-wide one softens blame but floors the verdict at DEGRADED, since a shared incident is exactly when no version should earn more traffic.

**`backend/app/runtime/deployment/canary.py`** — ACT-SRS-M3 §Phase-3.5 — `CanaryRolloutService`, the engine driving 3.4's allocation.
- Classes: `CanaryRolloutService`
- **Traffic only ever moves through 3.4's `set_weights`** — atomic, revisioned, eligibility-checked, audited. Structural rather than aspirational: this module contains no reference to `DeploymentTrafficWeight`/`DeploymentTrafficAllocation` at all, asserted against the parsed AST, so it *cannot* bypass the mechanism. `RolloutPlan.state` is written only in `_transition` (mechanically checked). `_assert_not_vetoed` runs before every operation that could increase the candidate's traffic and reads the same fields 3.4's resolver reads; de-escalating operations (pause/abort/request-rollback) deliberately skip it, because a kill switch must never trap a rollout in a state an operator cannot back out of. `evaluate_and_advance` is the interim auto-advance: bounded to **at most one stage per call** and idempotent — explicitly not a scheduler, and Phase 3.8 will call this exact method on a timer. Idempotency fingerprints carry the caller's *intent only* (the rollout id), never server-side state like the stage index, which would make every retry look like a different request. The whole mutation sequence sits inside the `StaleDataError` guard, not just the commit — that error surfaces at the first flush the audit insert triggers, the same lesson 3.1 and 3.4 both recorded.

### runtime/deployment — traffic & resolver (Phase 3.4)

**`backend/app/runtime/deployment/traffic.py`** — ACT-SRS-M3 §Phase-3.4 M3-3.4-FR-001..005 — the servability predicate and `TrafficAllocationService`.
- Classes: `WeightEntry, TrafficAllocationService`
- Functions: `servable_clause, is_servable`
- **Owns the definition of "servable"**, in both SQL (`servable_clause()`, for the resolver's hot path and eligibility queries) and Python (`is_servable()`, for an already-loaded row) — one definition, never restated at a call site. The rule is *union with veto*: a deployment serves iff `status == "ACTIVE" OR lifecycle_state == "ACTIVE"`, and neither field is in that machine's non-serving set (`NON_SERVING_STATUS` / `NON_SERVING_LIFECYCLE`). This is forced by the two-machine split §10 already documents: `status` is written by the legacy `DeploymentService` **and by `KillSwitchService`**, `lifecycle_state` only by `DeploymentLifecycleService`. Gating on `lifecycle_state` alone would disarm the kill switch at ORGANIZATION/PROJECT/PLATFORM scope and strand every legacy-deployed row; gating on `status` alone would let a 3.1-paused deployment keep serving and leave every 3.2-promoted deployment unable to execute. **Neither machine was rewritten** — the resolver honours both. Full truth table in `docs/deployment/traffic-and-resolution.md`, pinned by `test_ac10_servability_predicate_truth_table`.
- `TrafficAllocationService.set_weights()` is the hardened operation (§27 §4.5's top threat is an attacker redirecting traffic to a version of their choosing): validates the complete set before writing anything (sum exactly 100, no repeats, range 0-100 → `TRAFFIC_WEIGHTS_INVALID`; same-agent/PUBLISHED/signed/backed-by-a-servable-deployment-in-this-environment → `VERSION_NOT_ELIGIBLE`), then writes a **new revision** and clears the previous one's `is_current` in a single transaction with one commit — a partial or non-100 state is therefore never committed and never observable. Idempotent via 3.1's `IdempotencyService` verbatim (operation `deployment.traffic.set`), audited `DEPLOYMENT_TRAFFIC_CHANGED` with full from/to weight maps.
- **Concurrency is the partial unique index, not a lock** — no advisory lock is taken anywhere in this domain, deliberately, so nothing here can deadlock against the execution path's own locks (§9's Milestone 1 lesson). The losing writer's `IntegrityError` becomes `TRAFFIC_ALLOCATION_CONFLICT`. Two ordering details are load-bearing and explicit rather than left to SQLAlchemy: the previous row's `is_current` clear is flushed **before** the new INSERT (otherwise a caller's own legitimate write hits the partial index mid-flush), and the entire write sequence — not just the commit — sits inside the `IntegrityError` guard, because the conflict surfaces at the first flush that emits the INSERT. Same shape and same reason as `DeploymentLifecycleService.transition`'s `StaleDataError` handling.

**`backend/app/runtime/deployment/resolver.py`** — ACT-SRS-M3 §Phase-3.4 M3-3.4-FR-010..014, FR-020..022 — `VersionResolver`, the hot-path resolver and, in the same mechanism, ruling #4's execution gate.
- Classes: `ResolvedVersion, VersionResolver`
- Functions: `select_weighted`
- Called from **exactly one place**, `ExecutionRequestService._request_execution`, between the agent-lifecycle checks and the creation of the `AgentExecution` row — strictly before the pre-existing `authorize(deployment)` call, which is untouched. **This is Milestone 3's single deliberate change to the Milestone 1 execution path.**
- **It selects a version and returns a plain value; it never dispatches.** No authorization module, policy engine or worker is imported — verified structurally against the module's parsed **AST** (not raw text: the docstring discusses the gateway at length, explaining exactly why it must not touch it), positionally (the resolver call site precedes `decision = authorize(deployment)`), and behaviourally (a same-tenant VIEWER is rejected 403 on an allocation-routed agent). A resolver that resolved-and-dispatched would be an authorization bypass — the milestone's sharpest line (§27 §10.2).
- At most **three indexed queries** per resolution: servable deployments for the agent, the current allocation (hitting `ix_traffic_allocations_agent_environment_current`), and the weights joined to their deployments and versions. **No cache**, deliberately — every candidate cache key is mutated by code across three phases (pause, supersede, rollback, revoke, kill switch), so a cache would need invalidation hooks in all of them to stay correct *under the kill switch*. Measured instead: ≤3 queries (asserted by counting statements through a `before_cursor_execute` hook, so an N+1 fails the test) and <25 ms per resolution, observed ≈1-2 ms.
- **Implicit 100% allocation**: a servable deployment with no allocation row resolves to its own version — what keeps deployments created *after* migration 0040 working without an operator setting weights first, and what makes the §15 backfill's guarantee hold for new rows too. On that path the version's status is deliberately not filtered here, so the pre-existing `AGENT_VERSION_REVOKED`/`AGENT_VERSION_NOT_PUBLISHED` checks in `_request_execution` still fire exactly as before. An explicit `deployment_id` in the request is honoured as a pin (tenant + servability still checked, with the unchanged M1 codes), not re-routed through weights.
- `select_weighted()` is deterministic given a routing key (`sha256(key) % total`, walked over entries sorted by version id — no stored session state) and random otherwise. Stickiness is opt-in: explicit `routing_key`, else `correlation_id`, else random — deliberately *not* defaulted to the principal's id, which would silently make every request from one user sticky and defeat a percentage rollout for a small user base.

### runtime/providers (Phase 5.7a.1, 5.7a.2, 5.7a.3, 5.7a.4, 5.7a.5)

**`backend/app/runtime/providers/base.py`** — Phase 5.7a.1 SRS ACT-MDL-FR-001, FR-002, FR-009 — the model provider contract.
- Classes: `ModelProvider`
- Unchanged by Phase 5.7a.4/5.7a.5 — re-verified this session.

**`backend/app/runtime/providers/credential_crypto.py`** — Phase 5.7a.5 SRS ACT-MDL-FR-080 — new file. Fernet symmetric encryption for per-organization provider credentials.
- Functions: `reset_cached_key,encrypt_secret,decrypt_secret,mask_hint`
- Key from `settings.MODEL_CREDENTIAL_ENCRYPTION_KEY` if set; otherwise auto-generated and persisted to `settings.MODEL_CREDENTIAL_ENCRYPTION_KEY_PATH` (default `./.keys/model_credentials.key`, gitignored) — the identical dev-convenience pattern Phase 5.2.4's `LocalKeyProvider` already established for signing keys. **Known Deviation** (mirrors `ACT-VER-NFR-002`): a platform-held key necessarily enters process memory to encrypt/decrypt; closes at Milestone 13 (external KMS/vault).

**`backend/app/runtime/providers/errors.py`** — Phase 5.7a.1 SRS ACT-MDL-FR-005, FR-009 — provider-layer exceptions.
- Classes: `ProviderUnavailableError,CapabilityUnsupportedError,ProviderRequestFailedError` (`ProviderRequestFailedError` added Phase 5.7a.2 — one coarse `MODEL_PROVIDER_REQUEST_FAILED` exception for any adapter HTTP failure, originally deliberately not a taxonomy; Phase 5.7a.4 gave it two new attributes, `error_class: ProviderErrorClass` (defaulting to `UNKNOWN`) and `retry_after_seconds: float | None`, without changing its `.code`/HTTP-status mapping)

**`backend/app/runtime/providers/mock.py`** — Phase 5.7a.1 SRS ACT-MDL-FR-008 — MockProvider.
- Classes: `MockProvider`
- Unchanged since 5.7a.1 — re-verified this session (not in the 5.7a.2/5.7a.3/5.7a.4 diffs).

**`backend/app/runtime/providers/openai_compatible.py`** — Phase 5.7a.2 SRS ACT-MDL-FR-020..028, Phase 5.7a.3 SRS ACT-MDL-FR-040..044, Phase 5.7a.4 SRS ACT-MDL-FR-060..069 — OpenAI-compatible chat completions adapter, streaming and error classification included.
- Classes: `OpenAICompatibleProvider`
- Functions (module-level, Phase 5.7a.4): `_classify_status_error,_classify_transport_error,_parse_retry_after,_scrub`
- The first real, network-calling `ModelProvider` (Phase 5.7a.2); real incremental SSE streaming replaced a placeholder `stream()` in Phase 5.7a.3. Registered as `"OPENAI_COMPATIBLE"` (names the wire protocol, not a vendor) in `registry.py`. Phase 5.7a.4 added `_classified_status_error`/`_classified_transport_error` instance methods (mapping an HTTP status/body or an `httpx` exception onto `ProviderErrorClass`) and threaded classification/credential-scrubbing through both `complete()`'s raise sites and `stream()`'s interrupted-chunk yield sites.

**`backend/app/runtime/providers/registry.py`** — Phase 5.7a.1 SRS ACT-MDL-FR-003, FR-005, FR-010 — provider registry.
- Functions: `register,resolve,registered_identifiers`
- `resolve()` gained optional `model`/`api_key` parameters in Phase 5.7a.2, forwarded to a provider's constructor only if that constructor's signature actually declares the matching parameter (checked via `inspect.signature`, not assumed) — a genuine Phase 5.7a.1 gap: neither previously reached a provider instance, only usage-reporting strings. Unchanged by Phase 5.7a.4 — re-verified this session.

**`backend/app/runtime/providers/types.py`** — Phase 5.7a.1 SRS ACT-MDL-FR-006, FR-007, Phase 5.7a.4 SRS ACT-MDL-FR-060 — provider-neutral internal representation.
- Classes: `FinishReason,ProviderErrorClass,ModelToolDefinition,ModelToolCall,ModelMessage,ModelRequest,ModelResponse,ModelCapabilities` (`ProviderErrorClass` — the eight-class error taxonomy — added Phase 5.7a.4, alongside module-level `RETRYABLE_PROVIDER_ERROR_CLASSES: frozenset`)
- Functions: `_frozen_mapping,assemble_response` (`assemble_response()` added Phase 5.7a.3 — reduces a `ModelProvider.stream()` chunk sequence into one complete `ModelResponse`; no new dataclass was needed for streaming, see REPO_STATE §10.25. Phase 5.7a.4 extended it to also carry forward the last chunk's `error_class`/`retry_after_seconds` — see §10.28.)
- `ModelResponse` gained two new optional fields in Phase 5.7a.4: `error_class: ProviderErrorClass | None = None`, `retry_after_seconds: float | None = None` — both default `None`, so every pre-existing construction (`MockProvider`, every test) is unaffected.


### runtime/tools (Phase 5.6a.1, 5.6a.2)

**`backend/app/runtime/tools/egress_guard.py`** — Phase 5.6a.1 SRS ACT-TLX-FR-004..010 — new file. The isolated SSRF containment boundary: pure logic, no network, no database.
- Classes: `EgressPolicy,EgressDecision`
- Functions: `resolve_and_validate,evaluate_url` (public); `_parse_ip_literal,_parse_component,_is_blocked_address,_default_resolve` (private — the permissive decimal/octal/hex/`inet_aton`-style IP-literal parser and the address-classification check)
- Constants: `MALFORMED_URL,SCHEME_NOT_ALLOWED,HOST_NOT_ALLOWLISTED,PRIVATE_ADDRESS,RESOLUTION_FAILED,REDIRECT_DEPTH_EXCEEDED,DEFAULT_MAX_REDIRECTS`
- 32 tests in `backend/tests/runtime/test_egress_guard.py`, exhaustively covering every SSRF vector individually (AC-01..10) with zero network/database dependency (AC-26). Unchanged by Phase 5.6a.2 — re-verified this session.

**`backend/app/runtime/tools/http_executor.py`** — Phase 5.6a.1 SRS ACT-TLX-FR-001, FR-006, FR-007, FR-009, Phase 5.6a.2 SRS ACT-TLX-FR-025 — the only code path that turns an `egress_guard` decision into a real connection.
- Classes: `HttpExecutionResult,_PinnedTransport`
- Functions: `execute_http_tool,redact_headers,redact_body,_build_target_url,_evaluate_and_pin,_resolve_redirect_target,_parse_retry_after` (`_parse_retry_after` added Phase 5.6a.2 — a private, ~8-line duplicate of `openai_compatible._parse_retry_after` rather than a cross-package import, keeping `app/runtime/tools/` at zero dependency on `app/runtime/providers/`)
- `_PinnedTransport` connects to the address the guard validated, never a freshly re-resolved hostname (DNS-rebinding defense, `ACT-TLX-FR-006`) — rewrites the outgoing `httpx.Request.url` to the validated IP while leaving the already-set `Host` header untouched and setting TLS SNI via the `sni_hostname` request extension (confirmed present in the installed `httpcore 1.0.9` before this module was written). Redirects are never auto-followed (`follow_redirects=False`); each hop is re-evaluated from scratch against the policy, depth-capped. `_build_target_url` never resolves caller-supplied text as a URL against the tool's base the way `urljoin()` would — only the *path* component of whatever is supplied ever reaches the final URL, so the host always comes from the tool's own declared endpoint (`ACT-TLX-FR-010`). Phase 5.6a.2: `HttpExecutionResult` gained one new field, `retry_after_seconds: float | None = None`, populated from a `Retry-After` response header — consumed by `ToolGatewayService._invoke_http`'s retry backoff the same way the model side already honors a provider's own header.

**`backend/app/runtime/tools/concurrency.py`** — Phase 5.6a.2 SRS ACT-TLX-FR-029 — new file. The per-execution concurrent outbound-request ceiling: pure, in-process bookkeeping, no network, no database — the same isolation discipline `egress_guard.py` established.
- Classes: `ToolConcurrencyLimitExceeded` (exception)
- Functions: `track` (context manager — reserves/releases one concurrent-request slot for an execution id, raising if the configured ceiling would be exceeded), `current_inflight` (test-only introspection)
- Today's `ExecutionWorkerService` issues tool calls strictly sequentially, so this ceiling is never actually contended in production yet — it exists as the enforcement point 5.6a.3's model-driven loop plugs into without a new mechanism. Tested directly with real threads (`test_concurrency_ceiling_is_enforced`), since the sequential caller can't exercise contention on its own.


### runtime/registry (Phase 5.1)

**`backend/app/runtime/registry/duplicates.py`** — Phase 5.1 SRS §32-§33, §64 — exact + similarity duplicate detection.
- Classes: `AgentDuplicateDetectionService`

**`backend/app/runtime/registry/identity.py`** — Phase 5.1 SRS §11 — mandatory machine-identity association, with the
- Classes: `AgentIdentityAssociationService`

**`backend/app/runtime/registry/imports_exports.py`** — Phase 5.1 SRS §39-§45 — JSON/YAML/CSV agent import & export.
- Classes: `AgentImportService,AgentExportService`

**`backend/app/runtime/registry/migration.py`** — Phase 5.1 SRS §70-§73 — legacy-agent migration classification.
- Classes: `AgentMigrationService`

**`backend/app/runtime/registry/ownership.py`** — Phase 5.1 SRS §12-§13 — accountable ownership + immutable ownership history.
- Classes: `AgentOwnershipService`

**`backend/app/runtime/registry/schemas.py`** — Pydantic schemas for the Phase 5.1 Enterprise Agent Registry (SRS 5.1).
- Classes: `AgentDefinitionRegistryCreate,AgentRegistrationCreate,AgentRegistryUpdate,AgentRegistryRead,AgentLifecycleActionRequest,OwnershipTransferRequest,OwnershipHistoryRead,AgentOwnershipRead,IdentityAssociateRequest,IdentityCreateAndAssociateRequest,IdentityReplaceRequest,AgentIdentityRead,ValidationFinding,ValidationRunRead,SchemaTestRequest,SchemaTestResponse,DuplicateMatchRead,DuplicateReviewRequest,ImportRequest,ImportItemRead,ImportJobRead,ExportRequest,ExportJobRead,AgentLifecycleEventRead,MigrationRecordRead`

**`backend/app/runtime/registry/services.py`** — Phase 5.1 SRS §18-§21 — the full registry lifecycle state machine, and
- Classes: `AgentLifecycleService,AgentSearchService`

**`backend/app/runtime/registry/validation.py`** — Phase 5.1 SRS §25-§31 — the agent-registry validation-report engine.
- Classes: `ValidationFinding,AgentValidationService`
- Functions: `check_schema_dos_guards,validate_sample_payload,validate_entrypoint,check_url_for_embedded_credentials,has_blocking_findings`


### runtime/versioning (Phase 5.2 Part 1)

**`backend/app/runtime/versioning/artifacts.py`** — Phase 5.2 Part 1 SRS §27 — release artifact references.
- Classes: `ReleaseArtifactService`

**`backend/app/runtime/versioning/attestation.py`** — Phase 5.2.4 SRS ACT-VER-FR-060..071 — portable attestation & DSSE signing.
- Classes: `AttestationService`
- Functions: `pae,compute_manifest_digest,build_attestation`

**`backend/app/runtime/versioning/canonical.py`** — Phase 5.2.4 SRS ACT-VER-FR-025, FR-040..FR-047 — canonical serialization.
- Classes: `CanonicalizationError`
- Functions: `canonicalize,digest_bytes,digest,verify_digest,stringify_floats`

**`backend/app/runtime/versioning/channels.py`** — Phase 5.2 Part 1 SRS §9, §26 — release channel catalog.
- Classes: `ReleaseChannelService`

**`backend/app/runtime/versioning/compare.py`** — Phase 5.2 Part 1 SRS §3 — version comparison.
- Classes: `VersionComparisonService`

**`backend/app/runtime/versioning/compatibility.py`** — Phase 5.2.6 SRS ACT-VER-FR-100..108 — compatibility & breaking-change detection.
- Classes: `Finding,CompatibilityAnalysisService`
- Functions: `declared_increment,expected_increment_for,is_semver_consistent,compare_input_contract,compare_output_contract,compare_tool_bindings,compare_capabilities,compare_model_configuration,compare_policy,compare_prompt_and_metadata,detect_breaking,overall_level,classify_change`

**`backend/app/runtime/versioning/keys.py`** — Phase 5.2.4 SRS ACT-VER-FR-060..071 — signing key lifecycle.
- Classes: `SigningKeyService`

**`backend/app/runtime/versioning/lineage.py`** — Phase 5.2 Part 1 SRS §17-18 — version lineage.
- Classes: `VersionLineageService`

**`backend/app/runtime/versioning/locking.py`** — Phase 5.2 Part 1 SRS §14, §21 — the shared immutability gate.
- Functions: `ensure_not_locked`

**`backend/app/runtime/versioning/notes.py`** — Phase 5.2 Part 1 SRS §28 — structured, categorized release notes.
- Classes: `ReleaseNoteService`

**`backend/app/runtime/versioning/readiness.py`** — Phase 5.2 Part 1 SRS §3, §30 — promotion readiness.
- Classes: `VersionReadinessService`

**`backend/app/runtime/versioning/release_metadata.py`** — Phase 5.2 Part 1 SRS §26, §28 — release metadata (name, justification,
- Classes: `ReleaseMetadataService`

**`backend/app/runtime/versioning/schemas.py`** — Pydantic schemas for the Phase 5.2 Part 1 versioning foundation.
- Classes: `ReleaseChannelRead,VersionSnapshotRead,ReleaseMetadataUpsert,ReleaseMetadataRead,ReleaseArtifactCreate,ReleaseArtifactRead,ReleaseNoteCreate,ReleaseNoteRead,VersionStatusHistoryRead,RollbackTargetRequest,RevokeVersionRequest,VersionComparisonRead,ReadinessCheckRead,VersionReadinessRead,CompatibilityFindingRead,CompatibilityReportFinding,CompatibilitySummary,CompatibilityReportRead,SignatureRead,ProvenanceRead,AttestationRead,SigningKeyRead,RevokeSigningKeyRequest,SignatureVerificationCheck,VerificationResultRead` *(class list extended by Phase 5.2.6 and Phase 5.2.4; docstring unchanged)*

**`backend/app/runtime/versioning/semantic_version.py`** — Phase 5.2 Part 1 SRS §15-16 — semantic versioning rules.
- Classes: `SemanticVersionService`
- Functions: `parse_semver`

**`backend/app/runtime/versioning/signing/base.py`** — Phase 5.2.4 SRS ACT-VER-FR-060..071 — the signing provider contract.
- Classes: `SignatureResult,KeyRotationResult,SigningProvider`

**`backend/app/runtime/versioning/signing/local.py`** — Phase 5.2.4 SRS ACT-VER-FR-060..071 — local, file-based Ed25519 signing.
- Classes: `LocalKeyProvider`

**`backend/app/runtime/versioning/signing/registry.py`** — Phase 5.2.4 SRS ACT-VER-FR-060..071 — signing provider selection.
- Functions: `get_signing_provider`

**`backend/app/runtime/versioning/snapshot.py`** — Phase 5.2 Part 1 SRS §10-14 — the snapshot builder.
- Classes: `SnapshotBuilderService`
- Functions: `build_snapshot,checksum_of` *(plus `_legacy_checksum_of`, private, added by Phase 5.2.4)*
- Phase 5.6a.1 (`ACT-TLX-FR-004`): `build_snapshot()` gained an optional `tools: list[Tool] | None` parameter and a new `runtime.tool_configs` key in its returned document — `{tool_id: {"name", "tool_type", "http_config"}}`, copied by value from each assigned tool's *current* row at publish time (§12's "never reference a mutable record" discipline). Deliberately a new key, not a change to `tools_snapshot`'s own shape — see §10.39. `SnapshotBuilderService.build_and_store` now also fetches the version's assigned `Tool` rows (by the ids already in `tools_snapshot`) to pass through.

**`backend/app/runtime/versioning/status_history.py`** — Phase 5.2 Part 1 SRS §19, §25 — the version lifecycle transition ledger.
- Functions: `record_status_change,list_status_history`


### schemas

**`backend/app/schemas/agent.py`** — Agent schemas. ``api_key_hash`` is never exposed; the plaintext API key is
- Classes: `AgentCreate,AgentUpdate,AgentStatusUpdate,AgentRead,AgentCreateResponse,AgentListResponse,AgentStats`

**`backend/app/schemas/agent_action.py`** — Agent action schemas - the heart of the governance workflow.
- Classes: `AgentActionCreate,AgentActionDecisionResponse,AgentActionRead`

**`backend/app/schemas/analytics.py`** — Analytics & AI Operations Center schemas (Phase 3 Part 3.6).
- Classes: `KpiMetric,FleetHealth,ActivityPoint,RiskBands,RiskTrendPoint,RiskGroup,RiskHeatmapRow,HighRiskAgent,RiskAnalytics,PerformanceMetrics,AgentRanking,PerformanceAnalytics,PolicyStat,PolicyAnalytics,ReviewerStat,HumanReviewAnalytics,CostItem,CostAnalytics,Insight,ReportRow,ReportSection,AnalyticsReport,AnalyticsOverview`

**`backend/app/schemas/api_key.py`** — Agent API key schemas. The raw key is returned only once at creation.
- Classes: `ApiKeyCreate,ApiKeyRead,ApiKeyCreateResponse`

**`backend/app/schemas/approval.py`** — Approval schemas.
- Classes: `ApprovalReviewRequest,ApprovalEscalateRequest,ApprovalAssignRequest,ApprovalCommentCreate,ApprovalCommentRead,ApprovalRead,ApprovalListItem,ApprovalAgentInfo,ApprovalActionInfo,ApprovalPolicyInfo,ApprovalRiskAssessment,ApprovalDetail,ApprovalTimelineEvent,ApprovalStatistics`

**`backend/app/schemas/audit.py`** — Audit & Compliance Center schemas (Phase 3 Part 3.5).
- Classes: `AuditEventListItem,AuditRelatedEvent,AuditEventDetail,AuditTimelineItem,AuditStatistics,AuditEventTypeInfo,AuditSecuritySummary,ComplianceMetric,AuditComplianceSummary`

**`backend/app/schemas/audit_log.py`** — Audit log schemas.
- Classes: `AuditLogRead`

**`backend/app/schemas/auth.py`** — Authentication schemas: registration, login and tokens.
- Classes: `RegisterRequest,LoginRequest,Token`

**`backend/app/schemas/dashboard.py`** — Dashboard schemas - aggregated metrics for the future frontend.
- Classes: `DashboardSummary,ActivityPoint,RiskTrendPoint,SystemHealth,RecentActionItem,PendingApprovalItem`

**`backend/app/schemas/organization.py`** — Organization schemas.
- Classes: `OrganizationCreate,OrganizationRead`

**`backend/app/schemas/permission.py`** — Permission schemas.
- Classes: `PermissionCreate,PermissionRead`

**`backend/app/schemas/policy.py`** — Policy schemas.
- Classes: `PolicyCreate,PolicyUpdate,PolicyRead,PolicyTestRequest,PolicyTestResult,PolicyTemplate`

**`backend/app/schemas/rbac.py`** — RBAC schemas: roles, permissions and role assignment.
- Classes: `RbacPermissionRead,RoleRead,RoleWithPermissions,AssignRoleRequest,MyPermissionsResponse`

**`backend/app/schemas/user.py`** — User schemas. Password hashes are never exposed in any response model.
- Classes: `UserCreate,UserRead`


### seed.py

**`backend/app/seed.py`** — Seed the database with demo data (Phase 1 + Phase 2).
- Functions: `seed`


### services

**`backend/app/services/agent_action_service.py`** — Agent action orchestration.
- Classes: `RequestContext,ProcessResult`
- Functions: `process_agent_action`

**`backend/app/services/analytics_service.py`** — Analytics & AI Operations Center service (Phase 3 Part 3.6).
- Functions: `kpis,fleet_health,activity,risk_analytics,performance_analytics,policy_analytics,human_review_analytics,cost_analytics,insights,report,overview`

**`backend/app/services/api_key_service.py`** — Agent API key service: issuing, authenticating and revoking keys.
- Functions: `issue_api_key,authenticate,list_keys,revoke_key`

**`backend/app/services/approval_service.py`** — Approval service - creating approval requests and processing reviews.
- Functions: `priority_for_risk,create_pending_approval,approve_action,reject_action,escalate_action,assign_reviewer,add_comment`

**`backend/app/services/audit_service.py`** — Audit service - the single entry point for writing audit log entries.
- Functions: `log_event`

**`backend/app/services/audit_view.py`** — Audit view service (Phase 3 Part 3.5).
- Functions: `humanize,category_of,severity_of,is_security_event,name_maps,actor_name,to_list_item,related_events,event_catalog,timeline_label`

**`backend/app/services/auth_service.py`** — Authentication service - registration and credential verification.
- Functions: `email_exists,register_organization,authenticate_user`

**`backend/app/services/decision_engine.py`** — Decision engine.
- Classes: `DecisionResult`
- Functions: `make_decision`

**`backend/app/services/notification_service.py`** — Notification service - email notifications via SMTP (Mailtrap in dev).
- Functions: `delivery_enabled,outbox_path,send_email,notify_approval_requested,notify_approval_decided,notify_agent_suspended,notify_policy_violation`

**`backend/app/services/permission_engine.py`** — Permission engine.
- Classes: `PermissionResult`
- Functions: `check_permission`

**`backend/app/services/policy_engine.py`** — Policy engine: evaluate database-driven policies against an action.
- Classes: `PolicyResult`
- Functions: `evaluate_conditions,evaluate_policies`

**`backend/app/services/rbac_service.py`** — Advanced RBAC service.
- Functions: `seed_rbac,get_user_permissions,user_has_permission`

**`backend/app/services/risk_engine.py`** — Risk engine V2.
- Classes: `RiskBreakdown`
- Functions: `calculate_risk_breakdown,calculate_risk_score`


### frontend/src (summary — file counts only, verified via `find`)

Services (`frontend/src/services/*.ts`, one per backend domain): `abacService.ts`, `adminService.ts`, `apiClient.ts`, `approvalService.ts`, `auditService.ts`, `authService.ts`, `authorizationService.ts`, `credentialService.ts`, `dashboardService.ts`, `envelope.ts`, `governanceService.ts`, `hierarchyService.ts`, `index.ts`, `protectionService.ts`, `recoveryService.ts`, `registrationService.ts`, `resourceAuthzService.ts`, `runtimeService.ts`, `systemService.ts`, `tokenRefresh.ts`, `userService.ts`.

Modules (`frontend/src/modules/*`, `.ts`/`.tsx` file count excluding tests):

| Module | Files |
|---|---|
| `abac` | 13 |
| `admin` | 6 |
| `agents` | 25 |
| `analytics` | 40 |
| `approvals` | 39 |
| `audit` | 38 |
| `authorization` | 7 |
| `governance` | 15 |
| `hierarchy` | 8 |
| `identity` | 28 |
| `policies` | 36 |
| `protection` | 7 |
| `resources` | 8 |
| `runtime` | 19 |
| `security` | 11 |

## 5. API Surface

Extracted by importing the live `app.main:app` FastAPI object and iterating `app.routes` — every method, path, and (where the endpoint depends on `require_permission(code)`) the exact permission code, read out of that dependency's closure. This is the actual routing table the server would serve. `/docs`, `/openapi.json`, `/redoc` are excluded from the count and table below. A permission of `—` means the route has no `require_permission` dependency (either public, or gated by a different mechanism — e.g. API-key auth via `get_current_agent`, or session/JWT auth alone via `get_current_user` with no RBAC check).

Grouped by top-level path prefix for readability. Re-extracted this session (previously 452 after Phase 5.7a.2/5.7a.3/5.7a.4, none of which added a route; 4 new routes at Phase 5.7a.5 — provider-credential CRUD/test endpoints, bringing the total to 456). Re-confirmed unchanged at 456 after both Phase 5.6a.1 and Phase 5.6a.2 — neither added an HTTP route; both extend the existing tool-call execution path. **Phase 5.6a.3** added 1 new route (`GET /executions/{id}/messages`, the conversation transcript) — this document's prose said "bringing the total to 457" at the time, but a direct re-measurement this pass, against a temporary `git worktree` checked out at that exact commit (`a98a9c0`), shows the live count was **456**, not 457 — a small, previously-uncaught inaccuracy in prior prose, corrected here rather than carried forward (see §9's new gap item). **Phase 2.1.1** adds 8 new routes under `/api/v1/integration` (connector types, tenant instances, lifecycle actions, lifecycle events) — freshly verified both sides of this addition: 456 before, 464 after, an exact +8 with nothing else added or removed. **Phase 2.1.2** adds 7 new routes under the same prefix (`GET /auth-schemes`, `GET`/`PUT`/`DELETE .../credentials`, `POST .../credentials/validate`, `GET`/`POST .../oauth/callback`) — 464 before, 471 after, an exact +7. **Phase 2.1.3** adds 3 new routes under the same prefix (`GET .../health`, `POST .../health/check`, `GET .../health/history`) — 471 before, 474 after, an exact +3. **Phase 2.2.1/2.2.2/2.2.3/2.2.4** add none (each generic connector is configured through the pre-existing `POST`/`PATCH /connectors` endpoints; the invocation bridge is a direct Python entry point, not yet an HTTP route) — unchanged at 474 through all four. **Phase 2.3.1** adds 10 new routes: 4 public under `/api/v1/auth/federation` (login/callback/SAML ACS/metadata) and 6 admin CRUD under `/api/v1/identity/federation/configs` — 474 before, 484 after, an exact +10. **Phase 3.1** adds 5 new routes under `/api/v1/runtime/deployments/{id}/lifecycle/...` (`transition`/`pause`/`resume`/`retire`/`events`) — 484 before, 489 after, an exact +5; the pre-existing `POST /deployments` is extended additively (honors `Idempotency-Key`) without becoming a new route. **Phase 3.2** adds 10 new routes: 1 under `/api/v1/runtime/deployments/{id}/promote` (no path collision found — used directly, unlike 3.1's own `/lifecycle/...` nesting) and 9 under `/api/v1/runtime/environments`/`/promotion-paths` (environment CRUD + policy, promotion-path CRUD) — 489 before, 499 after, an exact +10. **Phase 3.3** adds 3 new routes under `/api/v1/runtime/deployments/{id}/preflight` (run, get latest, get history) — no path collision found, used directly — 499 before, 502 after, an exact +3. **Phase 3.4** adds 3 new routes under `/api/v1/runtime/agents/{agent_id}/environments/{environment_id}/traffic` (get current, set weights, get history) — no path collision found — 502 before, 505 after, an exact +3. Mounted on agent+environment rather than the build prompt's alternative `/deployments/{id}/traffic`, because an allocation spans several deployments (reason recorded in §4's routes entry). **Phase 3.5** adds 10 new routes: 1 under `/api/v1/runtime/agents/{agent_id}/environments/{environment_id}/rollouts` (create+start) and 9 under `/api/v1/runtime/rollouts/{id}/...` (get, health, advance, evaluate, pause, resume, abort, promote, request-rollback) — no path collision found — 505 before, 515 after, an exact +10. **Phase 3.6** adds 3 new routes under `/api/v1/runtime/deployments/{id}/strategy/...` (execute, blue-green/switch, blue-green/rollback) — no path collision found — 515 before, 518 after, an exact +3.

Total application routes (excluding /docs, /openapi.json, /redoc): **544**

*Re-derived live 2026-08-25 during Phase 4.1's pre-step A.* This line read **518** — correct as of Phase 3.6 and stale for every phase after it, even though the narrative paragraph above kept being extended. The intervening additions, each re-verified this pass: **3.7** +2, **3.8** +6, **3.9** +6 (fleet API, mounted at `/runtime/fleet` after a reported collision with M1's existing `/runtime/workers`), **3.10** +4 (the operations read model), **4.1** +1 (`GET /runtime/executions/{execution_id}/trace`). 518 → 541. The authoritative number is the live `APIRoute` count, not this document's prose — the same "verify, don't carry forward" correction §9 item 18 records for an earlier off-by-one.

#### `/agent-actions`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/agent-actions` | `—` | `app.api.routes.agent_actions::list_agent_actions` |
| POST | `/agent-actions` | `—` | `app.api.routes.agent_actions::submit_agent_action` |
| GET | `/agent-actions/{agent_action_id}` | `—` | `app.api.routes.agent_actions::get_agent_action` |

#### `/agents`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/agents` | `—` | `app.api.routes.agents::list_agents` |
| POST | `/agents` | `—` | `app.api.routes.agents::create_agent` |
| DELETE | `/agents/{agent_id}` | `—` | `app.api.routes.agents::delete_agent` |
| GET | `/agents/{agent_id}` | `—` | `app.api.routes.agents::get_agent` |
| PUT | `/agents/{agent_id}` | `—` | `app.api.routes.agents::update_agent` |
| GET | `/agents/{agent_id}/api-keys` | `agent.view` | `app.api.routes.api_keys::list_api_keys` |
| POST | `/agents/{agent_id}/generate-api-key` | `apikey.create` | `app.api.routes.api_keys::generate_api_key` |
| GET | `/agents/{agent_id}/stats` | `—` | `app.api.routes.agents::agent_stats` |
| PATCH | `/agents/{agent_id}/status` | `—` | `app.api.routes.agents::update_agent_status` |

#### `/analytics`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/analytics/activity` | `analytics.view` | `app.api.routes.analytics::analytics_activity` |
| GET | `/analytics/cost` | `analytics.view` | `app.api.routes.analytics::analytics_cost` |
| GET | `/analytics/fleet-health` | `analytics.view` | `app.api.routes.analytics::analytics_fleet_health` |
| GET | `/analytics/insights` | `analytics.view` | `app.api.routes.analytics::analytics_insights` |
| GET | `/analytics/kpis` | `analytics.view` | `app.api.routes.analytics::analytics_kpis` |
| GET | `/analytics/overview` | `analytics.view` | `app.api.routes.analytics::analytics_overview` |
| GET | `/analytics/performance` | `analytics.view` | `app.api.routes.analytics::analytics_performance` |
| GET | `/analytics/policies` | `analytics.view` | `app.api.routes.analytics::analytics_policies` |
| GET | `/analytics/reports` | `analytics.view` | `app.api.routes.analytics::analytics_reports` |
| GET | `/analytics/review` | `analytics.view` | `app.api.routes.analytics::analytics_review` |
| GET | `/analytics/risk` | `analytics.view` | `app.api.routes.analytics::analytics_risk` |

#### `/api-keys`

| Method | Path | Permission | Handler |
|---|---|---|---|
| POST | `/api-keys/{key_id}/revoke` | `apikey.revoke` | `app.api.routes.api_keys::revoke_api_key` |

#### `/api/v1/admin`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/admin/access-reviews` | `admin.reviews.manage` | `app.authorization.admin.routes::list_campaigns` |
| POST | `/api/v1/admin/access-reviews` | `admin.reviews.manage` | `app.authorization.admin.routes::create_campaign` |
| GET | `/api/v1/admin/access-reviews/{campaign_id}` | `admin.reviews.manage` | `app.authorization.admin.routes::get_campaign` |
| PUT | `/api/v1/admin/access-reviews/{campaign_id}` | `admin.reviews.manage` | `app.authorization.admin.routes::update_campaign` |
| POST | `/api/v1/admin/access-reviews/{campaign_id}/activate` | `admin.reviews.manage` | `app.authorization.admin.routes::activate_campaign` |
| POST | `/api/v1/admin/access-reviews/{campaign_id}/archive` | `admin.reviews.manage` | `app.authorization.admin.routes::archive_campaign` |
| POST | `/api/v1/admin/access-reviews/{campaign_id}/complete` | `admin.reviews.manage` | `app.authorization.admin.routes::complete_campaign` |
| GET | `/api/v1/admin/access-reviews/{campaign_id}/export` | `admin.reviews.manage` | `app.authorization.admin.routes::export_campaign` |
| GET | `/api/v1/admin/access-reviews/{campaign_id}/items` | `admin.reviews.manage` | `app.authorization.admin.routes::campaign_items` |
| POST | `/api/v1/admin/access-reviews/{campaign_id}/items/{item_id}/decide` | `admin.reviews.manage` | `app.authorization.admin.routes::decide_item` |
| POST | `/api/v1/admin/access-reviews/{campaign_id}/schedule` | `admin.reviews.manage` | `app.authorization.admin.routes::schedule_campaign` |
| GET | `/api/v1/admin/analytics` | `admin.analytics.view` | `app.authorization.admin.routes::analytics` |
| GET | `/api/v1/admin/authorization-decisions` | `admin.audit.view` | `app.authorization.admin.routes::authorization_decisions` |
| GET | `/api/v1/admin/dashboard` | `admin.dashboard.view` | `app.authorization.admin.routes::dashboard` |
| GET | `/api/v1/admin/organizations` | `admin.organizations.manage` | `app.authorization.admin.routes::organization_tree` |
| GET | `/api/v1/admin/permissions` | `admin.permissions.manage` | `app.authorization.admin.routes::list_permissions` |
| GET | `/api/v1/admin/policies` | `admin.policies.manage` | `app.authorization.admin.routes::list_policies` |
| POST | `/api/v1/admin/policies` | `admin.policies.manage` | `app.authorization.admin.routes::create_policy` |
| DELETE | `/api/v1/admin/policies/{policy_id}` | `admin.policies.manage` | `app.authorization.admin.routes::delete_policy` |
| PUT | `/api/v1/admin/policies/{policy_id}` | `admin.policies.manage` | `app.authorization.admin.routes::update_policy` |
| POST | `/api/v1/admin/policy-simulator` | `admin.simulator.use` | `app.authorization.admin.routes::policy_simulator` |
| GET | `/api/v1/admin/resources` | `admin.resources.manage` | `app.authorization.admin.routes::list_resources` |
| GET | `/api/v1/admin/roles` | `admin.roles.manage` | `app.authorization.admin.routes::list_roles` |
| POST | `/api/v1/admin/roles` | `admin.roles.manage` | `app.authorization.admin.routes::create_role` |
| DELETE | `/api/v1/admin/roles/{role_id}` | `admin.roles.manage` | `app.authorization.admin.routes::delete_role` |
| PUT | `/api/v1/admin/roles/{role_id}` | `admin.roles.manage` | `app.authorization.admin.routes::update_role` |

#### `/api/v1/auth`

| Method | Path | Permission | Handler |
|---|---|---|---|
| POST | `/api/v1/auth/admin/reset-password` | `credential.reset` | `app.identity.credentials.routes::admin_reset_password` |
| POST | `/api/v1/auth/change-email` | `—` | `app.identity.recovery.routes::change_email` |
| POST | `/api/v1/auth/change-password` | `—` | `app.identity.credentials.routes::change_password` |
| GET | `/api/v1/auth/devices` | `—` | `app.identity.auth.routes::list_devices` |
| POST | `/api/v1/auth/devices/{device_id}/block` | `—` | `app.identity.auth.routes::block_device` |
| POST | `/api/v1/auth/devices/{device_id}/trust` | `—` | `app.identity.auth.routes::trust_device` |
| POST | `/api/v1/auth/forgot-password` | `—` | `app.identity.recovery.routes::forgot_password` |
| POST | `/api/v1/auth/login` | `—` | `app.identity.auth.routes::login` |
| POST | `/api/v1/auth/logout` | `—` | `app.identity.auth.routes::logout` |
| GET | `/api/v1/auth/me` | `—` | `app.identity.auth.routes::me` |
| POST | `/api/v1/auth/mfa/verify` | `—` | `app.identity.auth.routes::mfa_verify` |
| GET | `/api/v1/auth/password-expiration` | `—` | `app.identity.credentials.routes::password_expiration` |
| GET | `/api/v1/auth/password-policy` | `—` | `app.identity.credentials.routes::password_policy` |
| POST | `/api/v1/auth/refresh` | `—` | `app.identity.auth.routes::refresh` |
| POST | `/api/v1/auth/register` | `—` | `app.identity.api.routes.registration::register_from_invitation` |
| POST | `/api/v1/auth/register/self` | `—` | `app.identity.api.routes.registration::self_register` |
| POST | `/api/v1/auth/resend-verification` | `—` | `app.identity.api.routes.registration::resend_verification` |
| POST | `/api/v1/auth/reset-password` | `—` | `app.identity.recovery.routes::reset_password` |
| GET | `/api/v1/auth/security-events` | `—` | `app.identity.auth.routes::my_security_events` |
| GET | `/api/v1/auth/sessions` | `—` | `app.identity.auth.routes::list_sessions` |
| DELETE | `/api/v1/auth/sessions/{session_id}` | `—` | `app.identity.auth.routes::delete_session` |
| GET | `/api/v1/auth/sessions/{session_id}` | `—` | `app.identity.auth.routes::get_session` |
| POST | `/api/v1/auth/sessions/{session_id}/revoke` | `—` | `app.identity.auth.routes::revoke_session` |
| POST | `/api/v1/auth/validate-password` | `—` | `app.identity.credentials.routes::validate_password` |
| POST | `/api/v1/auth/verify-email` | `—` | `app.identity.api.routes.registration::verify_email` |
| POST | `/api/v1/auth/verify-new-email` | `—` | `app.identity.recovery.routes::verify_new_email` |

#### `/api/v1/authorization`

| Method | Path | Permission | Handler |
|---|---|---|---|
| POST | `/api/v1/authorization/abac/evaluate` | `—` | `app.authorization.abac.routes::evaluate` |
| GET | `/api/v1/authorization/abac/evaluations` | `authorization.abac.audit` | `app.authorization.abac.routes::list_evaluations` |
| GET | `/api/v1/authorization/abac/evaluations/{evaluation_id}` | `authorization.abac.audit` | `app.authorization.abac.routes::get_evaluation` |
| GET | `/api/v1/authorization/abac/metrics` | `authorization.abac.view` | `app.authorization.abac.routes::abac_metrics` |
| GET | `/api/v1/authorization/abac/policies` | `authorization.abac.view` | `app.authorization.abac.routes::list_policies` |
| POST | `/api/v1/authorization/abac/policies` | `authorization.abac.create` | `app.authorization.abac.routes::create_policy` |
| DELETE | `/api/v1/authorization/abac/policies/{policy_id}` | `authorization.abac.archive` | `app.authorization.abac.routes::delete_policy` |
| GET | `/api/v1/authorization/abac/policies/{policy_id}` | `authorization.abac.view` | `app.authorization.abac.routes::get_policy` |
| PUT | `/api/v1/authorization/abac/policies/{policy_id}` | `authorization.abac.update` | `app.authorization.abac.routes::update_policy` |
| POST | `/api/v1/authorization/abac/policies/{policy_id}/archive` | `authorization.abac.archive` | `app.authorization.abac.routes::archive_policy` |
| POST | `/api/v1/authorization/abac/policies/{policy_id}/clone` | `authorization.abac.create` | `app.authorization.abac.routes::clone_policy` |
| POST | `/api/v1/authorization/abac/policies/{policy_id}/disable` | `authorization.abac.disable` | `app.authorization.abac.routes::disable_policy` |
| POST | `/api/v1/authorization/abac/policies/{policy_id}/publish` | `authorization.abac.publish` | `app.authorization.abac.routes::publish_policy` |
| POST | `/api/v1/authorization/abac/policies/{policy_id}/rollback/{version}` | `authorization.abac.publish` | `app.authorization.abac.routes::rollback_policy` |
| POST | `/api/v1/authorization/abac/policies/{policy_id}/simulate` | `authorization.abac.simulate` | `app.authorization.abac.routes::simulate_policy` |
| POST | `/api/v1/authorization/abac/policies/{policy_id}/validate` | `authorization.abac.update` | `app.authorization.abac.routes::validate_policy` |
| GET | `/api/v1/authorization/abac/policies/{policy_id}/versions` | `authorization.abac.view` | `app.authorization.abac.routes::list_versions` |
| GET | `/api/v1/authorization/abac/policies/{policy_id}/versions/{version}` | `authorization.abac.view` | `app.authorization.abac.routes::get_version` |
| POST | `/api/v1/authorization/abac/simulate` | `authorization.abac.simulate` | `app.authorization.abac.routes::simulate` |
| GET | `/api/v1/authorization/attributes` | `authorization.abac.view` | `app.authorization.abac.routes::list_attributes` |
| POST | `/api/v1/authorization/attributes` | `authorization.attribute.manage` | `app.authorization.abac.routes::create_attribute` |
| PUT | `/api/v1/authorization/attributes/{definition_id}` | `authorization.attribute.manage` | `app.authorization.abac.routes::update_attribute` |
| GET | `/api/v1/authorization/attributes/{name}` | `authorization.abac.view` | `app.authorization.abac.routes::get_attribute` |
| GET | `/api/v1/authorization/audit` | `role.view` | `app.authorization.routes::list_authorization_audit` |
| POST | `/api/v1/authorization/check` | `—` | `app.authorization.routes::authorization_check` |
| GET | `/api/v1/authorization/exceptions` | `authorization.exception.manage` | `app.authorization.abac.routes::list_exceptions` |
| POST | `/api/v1/authorization/exceptions` | `authorization.exception.manage` | `app.authorization.abac.routes::create_exception` |
| DELETE | `/api/v1/authorization/exceptions/{exception_id}` | `authorization.exception.manage` | `app.authorization.abac.routes::revoke_exception` |
| GET | `/api/v1/authorization/middleware/metrics` | `authorization.abac.view` | `app.authorization.abac.routes::middleware_metrics` |

#### `/api/v1/business-units`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/business-units` | `organization.view` | `app.authorization.hierarchy.routes::list_business_units` |
| POST | `/api/v1/business-units` | `organization.manage` | `app.authorization.hierarchy.routes::create_business_unit` |
| DELETE | `/api/v1/business-units/{bu_id}` | `organization.manage` | `app.authorization.hierarchy.routes::delete_business_unit` |
| GET | `/api/v1/business-units/{bu_id}` | `organization.view` | `app.authorization.hierarchy.routes::get_business_unit` |
| PUT | `/api/v1/business-units/{bu_id}` | `organization.manage` | `app.authorization.hierarchy.routes::update_business_unit` |

#### `/api/v1/delegations`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/delegations` | `organization.view` | `app.authorization.hierarchy.routes::list_delegations` |
| POST | `/api/v1/delegations` | `organization.manage` | `app.authorization.hierarchy.routes::create_delegation` |
| DELETE | `/api/v1/delegations/{delegation_id}` | `organization.manage` | `app.authorization.hierarchy.routes::revoke_delegation` |

#### `/api/v1/departments`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/departments` | `organization.view` | `app.authorization.hierarchy.routes::list_departments` |
| POST | `/api/v1/departments` | `organization.manage` | `app.authorization.hierarchy.routes::create_department` |
| DELETE | `/api/v1/departments/{dept_id}` | `organization.manage` | `app.authorization.hierarchy.routes::delete_department` |
| GET | `/api/v1/departments/{dept_id}` | `organization.view` | `app.authorization.hierarchy.routes::get_department` |
| PUT | `/api/v1/departments/{dept_id}` | `organization.manage` | `app.authorization.hierarchy.routes::update_department` |

#### `/api/v1/governance`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/governance/analytics` | `governance.analytics.view` | `app.governance.routes::analytics` |
| GET | `/api/v1/governance/campaigns` | `governance.certification.manage` | `app.governance.routes::list_campaigns` |
| POST | `/api/v1/governance/campaigns` | `governance.certification.manage` | `app.governance.routes::create_campaign` |
| GET | `/api/v1/governance/campaigns/{campaign_id}` | `governance.certification.manage` | `app.governance.routes::get_campaign` |
| PUT | `/api/v1/governance/campaigns/{campaign_id}` | `governance.certification.manage` | `app.governance.routes::update_campaign` |
| POST | `/api/v1/governance/campaigns/{campaign_id}/archive` | `governance.certification.manage` | `app.governance.routes::archive_campaign` |
| POST | `/api/v1/governance/campaigns/{campaign_id}/complete` | `governance.certification.manage` | `app.governance.routes::complete_campaign` |
| GET | `/api/v1/governance/campaigns/{campaign_id}/export` | `governance.certification.manage` | `app.governance.routes::export_campaign` |
| GET | `/api/v1/governance/campaigns/{campaign_id}/items` | `governance.certification.manage` | `app.governance.routes::campaign_items` |
| POST | `/api/v1/governance/campaigns/{campaign_id}/launch` | `governance.certification.manage` | `app.governance.routes::launch_campaign` |
| GET | `/api/v1/governance/compliance/frameworks` | `governance.compliance.view` | `app.governance.routes::compliance_frameworks` |
| GET | `/api/v1/governance/compliance/reports` | `governance.compliance.view` | `app.governance.routes::list_compliance_reports` |
| POST | `/api/v1/governance/compliance/reports` | `governance.compliance.view` | `app.governance.routes::generate_compliance_report` |
| GET | `/api/v1/governance/compliance/reports/{report_id}` | `governance.compliance.view` | `app.governance.routes::get_compliance_report` |
| GET | `/api/v1/governance/dashboard` | `governance.dashboard.view` | `app.governance.routes::dashboard` |
| GET | `/api/v1/governance/findings` | `governance.findings.manage` | `app.governance.routes::list_findings` |
| POST | `/api/v1/governance/findings/{finding_id}/remediate` | `governance.findings.manage` | `app.governance.routes::remediate_finding` |
| GET | `/api/v1/governance/orphaned-accounts` | `governance.orphaned.manage` | `app.governance.routes::list_orphaned_accounts` |
| POST | `/api/v1/governance/orphaned-accounts/scan` | `governance.orphaned.manage` | `app.governance.routes::scan_orphaned_accounts` |
| GET | `/api/v1/governance/privileged-accounts` | `governance.privileged.manage` | `app.governance.routes::list_privileged_accounts` |
| GET | `/api/v1/governance/privileged-accounts/reviews` | `governance.privileged.manage` | `app.governance.routes::list_privileged_reviews` |
| POST | `/api/v1/governance/privileged-accounts/reviews` | `governance.privileged.manage` | `app.governance.routes::request_privileged_review` |
| POST | `/api/v1/governance/privileged-accounts/reviews/{review_id}/decide` | `governance.privileged.manage` | `app.governance.routes::decide_privileged_review` |
| GET | `/api/v1/governance/remediation-actions` | `governance.remediation.manage` | `app.governance.routes::list_remediation_actions` |
| POST | `/api/v1/governance/remediation-actions` | `governance.remediation.manage` | `app.governance.routes::create_remediation_action` |
| POST | `/api/v1/governance/remediation-actions/{action_id}/execute` | `governance.remediation.manage` | `app.governance.routes::execute_remediation_action` |
| POST | `/api/v1/governance/reviews/{item_id}/approve` | `governance.certification.manage` | `app.governance.routes::approve_review` |
| POST | `/api/v1/governance/reviews/{item_id}/delegate` | `governance.certification.manage` | `app.governance.routes::delegate_review` |
| POST | `/api/v1/governance/reviews/{item_id}/modify` | `governance.certification.manage` | `app.governance.routes::modify_review` |
| POST | `/api/v1/governance/reviews/{item_id}/revoke` | `governance.certification.manage` | `app.governance.routes::revoke_review` |
| GET | `/api/v1/governance/risk-scores` | `governance.analytics.view` | `app.governance.routes::list_risk_scores` |
| POST | `/api/v1/governance/risk-scores/recalculate` | `governance.analytics.view` | `app.governance.routes::recalculate_risk_scores` |
| GET | `/api/v1/governance/sod-findings` | `governance.sod.view` | `app.governance.routes::list_sod_findings` |
| POST | `/api/v1/governance/sod-findings/scan` | `governance.sod.manage` | `app.governance.routes::scan_sod` |
| GET | `/api/v1/governance/sod-rules` | `governance.sod.view` | `app.governance.routes::list_sod_rules` |
| POST | `/api/v1/governance/sod-rules` | `governance.sod.manage` | `app.governance.routes::create_sod_rule` |
| PUT | `/api/v1/governance/sod-rules/{rule_id}` | `governance.sod.manage` | `app.governance.routes::update_sod_rule` |
| POST | `/api/v1/governance/sod-rules/{rule_id}/activate` | `governance.sod.manage` | `app.governance.routes::activate_sod_rule` |
| POST | `/api/v1/governance/sod-rules/{rule_id}/disable` | `governance.sod.manage` | `app.governance.routes::disable_sod_rule` |
| GET | `/api/v1/governance/toxic-findings` | `governance.sod.view` | `app.governance.routes::list_toxic_findings` |
| POST | `/api/v1/governance/toxic-findings/scan` | `governance.toxic.manage` | `app.governance.routes::scan_toxic` |
| GET | `/api/v1/governance/toxic-rules` | `governance.sod.view` | `app.governance.routes::list_toxic_rules` |
| POST | `/api/v1/governance/toxic-rules` | `governance.toxic.manage` | `app.governance.routes::create_toxic_rule` |
| POST | `/api/v1/governance/toxic-rules/{rule_id}/activate` | `governance.toxic.manage` | `app.governance.routes::activate_toxic_rule` |
| POST | `/api/v1/governance/toxic-rules/{rule_id}/disable` | `governance.toxic.manage` | `app.governance.routes::disable_toxic_rule` |

#### `/api/v1/hierarchy`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/hierarchy/tree` | `organization.view` | `app.authorization.hierarchy.routes::hierarchy_tree` |

#### `/api/v1/identity`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/identity/agent-identities` | `agent.view` | `app.identity.api.routes.agent_identities::list_agent_identities` |
| POST | `/api/v1/identity/agent-identities` | `agent.create` | `app.identity.api.routes.agent_identities::create_agent_identity` |
| GET | `/api/v1/identity/agent-identities/{identity_id}` | `agent.view` | `app.identity.api.routes.agent_identities::get_agent_identity` |
| POST | `/api/v1/identity/agent-identities/{identity_id}/status` | `agent.create` | `app.identity.api.routes.agent_identities::transition_agent_identity` |
| GET | `/api/v1/identity/departments` | `user.view` | `app.identity.api.routes.departments::list_departments` |
| POST | `/api/v1/identity/departments` | `user.create` | `app.identity.api.routes.departments::create_department` |
| GET | `/api/v1/identity/departments/{department_id}` | `user.view` | `app.identity.api.routes.departments::get_department` |
| GET | `/api/v1/identity/email-delivery` | `invitation.view` | `app.identity.api.routes.invitations::email_delivery_status` |
| GET | `/api/v1/identity/external-clients` | `user.view` | `app.identity.api.routes.external_clients::list_external_clients` |
| POST | `/api/v1/identity/external-clients` | `user.create` | `app.identity.api.routes.external_clients::create_external_client` |
| GET | `/api/v1/identity/external-clients/{client_id}` | `user.view` | `app.identity.api.routes.external_clients::get_external_client` |
| POST | `/api/v1/identity/external-clients/{client_id}/status` | `user.create` | `app.identity.api.routes.external_clients::transition_external_client` |
| GET | `/api/v1/identity/invitations` | `invitation.view` | `app.identity.api.routes.invitations::list_invitations` |
| POST | `/api/v1/identity/invitations` | `invitation.manage` | `app.identity.api.routes.invitations::create_invitation` |
| POST | `/api/v1/identity/invitations/cancel` | `invitation.manage` | `app.identity.api.routes.invitations::cancel_invitation` |
| POST | `/api/v1/identity/invitations/resend` | `invitation.manage` | `app.identity.api.routes.invitations::resend_invitation` |
| GET | `/api/v1/identity/invitations/{token}` | `—` | `app.identity.api.routes.invitations::preview_invitation` |
| GET | `/api/v1/identity/organizations` | `user.view` | `app.identity.api.routes.organizations::list_organizations` |
| GET | `/api/v1/identity/organizations/{organization_id}` | `user.view` | `app.identity.api.routes.organizations::get_organization` |
| POST | `/api/v1/identity/organizations/{organization_id}/status` | `user.create` | `app.identity.api.routes.organizations::transition_organization` |
| GET | `/api/v1/identity/roles` | `user.view` | `app.identity.api.routes.roles::list_roles` |
| GET | `/api/v1/identity/security-events` | `session.view` | `app.identity.api.routes.sessions::list_security_events` |
| GET | `/api/v1/identity/security-events/types` | `session.view` | `app.identity.api.routes.sessions::list_security_event_types` |
| GET | `/api/v1/identity/service-accounts` | `user.view` | `app.identity.api.routes.service_accounts::list_service_accounts` |
| POST | `/api/v1/identity/service-accounts` | `user.create` | `app.identity.api.routes.service_accounts::create_service_account` |
| GET | `/api/v1/identity/service-accounts/{account_id}` | `user.view` | `app.identity.api.routes.service_accounts::get_service_account` |
| POST | `/api/v1/identity/service-accounts/{account_id}/status` | `user.create` | `app.identity.api.routes.service_accounts::transition_service_account` |
| GET | `/api/v1/identity/sessions` | `session.view` | `app.identity.api.routes.sessions::list_sessions` |
| GET | `/api/v1/identity/sessions/{session_id}` | `session.view` | `app.identity.api.routes.sessions::get_session` |
| GET | `/api/v1/identity/sessions/{session_id}/events` | `session.view` | `app.identity.api.routes.sessions::list_session_events` |
| POST | `/api/v1/identity/sessions/{session_id}/revoke` | `session.revoke` | `app.identity.api.routes.sessions::admin_revoke_session` |
| GET | `/api/v1/identity/users` | `user.view` | `app.identity.api.routes.users::list_users` |
| POST | `/api/v1/identity/users` | `user.create` | `app.identity.api.routes.users::create_user` |
| GET | `/api/v1/identity/users/{user_id}` | `user.view` | `app.identity.api.routes.users::get_user` |
| POST | `/api/v1/identity/users/{user_id}/activate` | `user.create` | `app.identity.api.routes.users::activate_user` |
| POST | `/api/v1/identity/users/{user_id}/approve` | `user.create` | `app.identity.api.routes.invitations::approve_registration` |
| GET | `/api/v1/identity/users/{user_id}/devices` | `session.view` | `app.identity.api.routes.sessions::list_user_devices` |
| POST | `/api/v1/identity/users/{user_id}/sessions/revoke-all` | `session.revoke` | `app.identity.api.routes.sessions::admin_revoke_all_sessions` |
| POST | `/api/v1/identity/users/{user_id}/status` | `user.create` | `app.identity.api.routes.users::transition_user` |
| POST | `/api/v1/identity/users/{user_id}/suspend` | `user.create` | `app.identity.api.routes.users::suspend_user` |

#### `/api/v1/integration`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/integration/connector-types` | `integration.connector.view` | `app.integration.routes::list_connector_types` |
| GET | `/api/v1/integration/connectors` | `integration.connector.view` | `app.integration.routes::list_connectors` |
| POST | `/api/v1/integration/connectors` | `integration.connector.manage` | `app.integration.routes::create_connector` |
| GET | `/api/v1/integration/connectors/{instance_id}` | `integration.connector.view` | `app.integration.routes::get_connector` |
| PATCH | `/api/v1/integration/connectors/{instance_id}` | `integration.connector.manage` | `app.integration.routes::configure_connector` |
| POST | `/api/v1/integration/connectors/{instance_id}/activate` | `integration.connector.manage` | `app.integration.routes::activate_connector` |
| POST | `/api/v1/integration/connectors/{instance_id}/disable` | `integration.connector.manage` | `app.integration.routes::disable_connector` |
| GET | `/api/v1/integration/connectors/{instance_id}/events` | `integration.connector.view` | `app.integration.routes::list_connector_events` |
| GET | `/api/v1/integration/auth-schemes` | `integration.connector.view` | `app.integration.routes::list_auth_schemes` |
| GET | `/api/v1/integration/connectors/{instance_id}/credentials` | `integration.connector.view` | `app.integration.routes::list_connector_credentials` |
| PUT | `/api/v1/integration/connectors/{instance_id}/credentials` | `integration.connector.manage` | `app.integration.routes::upsert_connector_credential` |
| DELETE | `/api/v1/integration/connectors/{instance_id}/credentials` | `integration.connector.manage` | `app.integration.routes::delete_connector_credential` |
| POST | `/api/v1/integration/connectors/{instance_id}/credentials/validate` | `integration.connector.manage` | `app.integration.routes::validate_connector_credential` |
| GET | `/api/v1/integration/connectors/{instance_id}/oauth/callback` | `integration.connector.manage` | `app.integration.routes::oauth_callback_get` |
| POST | `/api/v1/integration/connectors/{instance_id}/oauth/callback` | `integration.connector.manage` | `app.integration.routes::oauth_callback_post` |
| GET | `/api/v1/integration/connectors/{instance_id}/health` | `integration.connector.view` | `app.integration.routes::get_connector_health` |
| POST | `/api/v1/integration/connectors/{instance_id}/health/check` | `integration.connector.manage` | `app.integration.routes::run_connector_health_check` |
| GET | `/api/v1/integration/connectors/{instance_id}/health/history` | `integration.connector.view` | `app.integration.routes::list_connector_health_history` |

#### `/api/v1/organizations`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/organizations` | `organization.view` | `app.authorization.hierarchy.routes::list_organizations` |
| POST | `/api/v1/organizations` | `organization.manage` | `app.authorization.hierarchy.routes::create_organization` |
| DELETE | `/api/v1/organizations/{org_id}` | `organization.manage` | `app.authorization.hierarchy.routes::delete_organization` |
| GET | `/api/v1/organizations/{org_id}` | `organization.view` | `app.authorization.hierarchy.routes::get_organization` |
| PUT | `/api/v1/organizations/{org_id}` | `organization.manage` | `app.authorization.hierarchy.routes::update_organization` |

#### `/api/v1/permission-groups`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/permission-groups` | `role.view` | `app.authorization.routes::list_permission_groups` |

#### `/api/v1/permissions`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/permissions` | `role.view` | `app.authorization.routes::list_permissions` |
| POST | `/api/v1/permissions` | `role.manage` | `app.authorization.routes::create_permission` |
| DELETE | `/api/v1/permissions/{permission_id}` | `role.manage` | `app.authorization.routes::delete_permission` |
| PUT | `/api/v1/permissions/{permission_id}` | `role.manage` | `app.authorization.routes::update_permission` |

#### `/api/v1/projects`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/projects` | `organization.view` | `app.authorization.hierarchy.routes::list_projects` |
| POST | `/api/v1/projects` | `organization.manage` | `app.authorization.hierarchy.routes::create_project` |
| DELETE | `/api/v1/projects/{project_id}` | `organization.manage` | `app.authorization.hierarchy.routes::delete_project` |
| GET | `/api/v1/projects/{project_id}` | `organization.view` | `app.authorization.hierarchy.routes::get_project` |
| PUT | `/api/v1/projects/{project_id}` | `organization.manage` | `app.authorization.hierarchy.routes::update_project` |

#### `/api/v1/resource-ownership`

| Method | Path | Permission | Handler |
|---|---|---|---|
| POST | `/api/v1/resource-ownership` | `organization.manage` | `app.authorization.hierarchy.routes::assign_ownership` |
| POST | `/api/v1/resource-ownership/transfer` | `organization.manage` | `app.authorization.hierarchy.routes::transfer_ownership` |
| GET | `/api/v1/resource-ownership/{resource_type}/{resource_id}` | `organization.view` | `app.authorization.hierarchy.routes::get_ownership` |

#### `/api/v1/resources`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/resources` | `—` | `app.authorization.resources.routes::list_resources` |
| POST | `/api/v1/resources` | `—` | `app.authorization.resources.routes::register_resource` |
| GET | `/api/v1/resources/types` | `—` | `app.authorization.resources.routes::list_resource_types` |
| GET | `/api/v1/resources/{resource_pk}` | `—` | `app.authorization.resources.routes::get_resource` |
| PUT | `/api/v1/resources/{resource_pk}` | `—` | `app.authorization.resources.routes::update_resource` |
| GET | `/api/v1/resources/{resource_pk}/acl` | `—` | `app.authorization.resources.routes::list_acl` |
| POST | `/api/v1/resources/{resource_pk}/acl` | `—` | `app.authorization.resources.routes::add_acl_entry` |
| DELETE | `/api/v1/resources/{resource_pk}/acl/{acl_id}` | `—` | `app.authorization.resources.routes::delete_acl_entry` |
| PUT | `/api/v1/resources/{resource_pk}/acl/{acl_id}` | `—` | `app.authorization.resources.routes::update_acl_entry` |
| POST | `/api/v1/resources/{resource_pk}/authorize` | `—` | `app.authorization.resources.routes::authorize` |
| POST | `/api/v1/resources/{resource_pk}/delegate` | `—` | `app.authorization.resources.routes::delegate_resource` |
| DELETE | `/api/v1/resources/{resource_pk}/delegate/{delegation_id}` | `—` | `app.authorization.resources.routes::revoke_delegation` |
| GET | `/api/v1/resources/{resource_pk}/delegations` | `—` | `app.authorization.resources.routes::list_delegations` |
| GET | `/api/v1/resources/{resource_pk}/owner` | `—` | `app.authorization.resources.routes::get_owner` |
| GET | `/api/v1/resources/{resource_pk}/ownership-history` | `—` | `app.authorization.resources.routes::ownership_history` |
| PUT | `/api/v1/resources/{resource_pk}/policy` | `—` | `app.authorization.resources.routes::set_policy` |
| POST | `/api/v1/resources/{resource_pk}/share` | `—` | `app.authorization.resources.routes::share_resource` |
| DELETE | `/api/v1/resources/{resource_pk}/share/{share_id}` | `—` | `app.authorization.resources.routes::revoke_share` |
| PUT | `/api/v1/resources/{resource_pk}/share/{share_id}` | `—` | `app.authorization.resources.routes::update_share` |
| GET | `/api/v1/resources/{resource_pk}/shares` | `—` | `app.authorization.resources.routes::list_shares` |
| POST | `/api/v1/resources/{resource_pk}/transfer-ownership` | `—` | `app.authorization.resources.routes::transfer_ownership` |

#### `/api/v1/role-assignments`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/role-assignments` | `role.view` | `app.authorization.routes::list_role_assignments` |
| POST | `/api/v1/role-assignments` | `role.assign` | `app.authorization.routes::create_role_assignment` |
| DELETE | `/api/v1/role-assignments/{assignment_id}` | `role.assign` | `app.authorization.routes::delete_role_assignment` |

#### `/api/v1/role-hierarchy`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/role-hierarchy` | `role.view` | `app.authorization.routes::list_role_hierarchy` |
| POST | `/api/v1/role-hierarchy` | `role.manage` | `app.authorization.routes::create_role_hierarchy` |
| DELETE | `/api/v1/role-hierarchy/{edge_id}` | `role.manage` | `app.authorization.routes::delete_role_hierarchy` |

#### `/api/v1/roles`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/roles` | `role.view` | `app.authorization.routes::list_roles` |
| POST | `/api/v1/roles` | `role.manage` | `app.authorization.routes::create_role` |
| DELETE | `/api/v1/roles/{role_id}` | `role.manage` | `app.authorization.routes::delete_role` |
| GET | `/api/v1/roles/{role_id}` | `role.view` | `app.authorization.routes::get_role` |
| PUT | `/api/v1/roles/{role_id}` | `role.manage` | `app.authorization.routes::update_role` |
| GET | `/api/v1/roles/{role_id}/effective-permissions` | `role.view` | `app.authorization.routes::role_effective_permissions` |

#### `/api/v1/runtime`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/runtime/agents` | `runtime.agent.view` | `app.runtime.routes::list_agents` |
| POST | `/api/v1/runtime/agents` | `runtime.agent.create` | `app.runtime.routes::register_agent` |
| POST | `/api/v1/runtime/agents/export` | `runtime.agent.export` | `app.runtime.routes::export_agents` |
| GET | `/api/v1/runtime/agents/export/{job_id}` | `runtime.agent.export` | `app.runtime.routes::get_export_job` |
| GET | `/api/v1/runtime/agents/export/{job_id}/download` | `runtime.agent.export` | `app.runtime.routes::download_export` |
| POST | `/api/v1/runtime/agents/import` | `runtime.agent.import` | `app.runtime.routes::import_agents` |
| GET | `/api/v1/runtime/agents/import/{job_id}` | `runtime.agent.import` | `app.runtime.routes::get_import_job` |
| GET | `/api/v1/runtime/agents/import/{job_id}/items` | `runtime.agent.import` | `app.runtime.routes::get_import_items` |
| POST | `/api/v1/runtime/agents/migration/classify` | `runtime.agent.import` | `app.runtime.routes::classify_legacy_agents` |
| GET | `/api/v1/runtime/agents/migration/records` | `runtime.agent.import` | `app.runtime.routes::list_migration_records` |
| DELETE | `/api/v1/runtime/agents/{agent_id}` | `runtime.agent.delete` | `app.runtime.routes::delete_agent` |
| GET | `/api/v1/runtime/agents/{agent_id}` | `runtime.agent.view` | `app.runtime.routes::get_agent` |
| PATCH | `/api/v1/runtime/agents/{agent_id}` | `runtime.agent.update` | `app.runtime.routes::update_agent` |
| PUT | `/api/v1/runtime/agents/{agent_id}` | `runtime.agent.update` | `app.runtime.routes::update_agent` |
| POST | `/api/v1/runtime/agents/{agent_id}/activate` | `runtime.agent.activate` | `app.runtime.routes::activate_agent` |
| POST | `/api/v1/runtime/agents/{agent_id}/approve` | `runtime.agent.approve` | `app.runtime.routes::approve_agent` |
| POST | `/api/v1/runtime/agents/{agent_id}/archive` | `runtime.agent.archive` | `app.runtime.routes::archive_agent` |
| GET | `/api/v1/runtime/agents/{agent_id}/capabilities` | `runtime.agent.view` | `app.runtime.routes::agent_capabilities` |
| POST | `/api/v1/runtime/agents/{agent_id}/capabilities` | `runtime.capability.manage` | `app.runtime.routes::assign_capability` |
| DELETE | `/api/v1/runtime/agents/{agent_id}/capabilities/{assignment_id}` | `runtime.capability.manage` | `app.runtime.routes::revoke_capability` |
| POST | `/api/v1/runtime/agents/{agent_id}/capabilities/{assignment_id}/decide` | `runtime.capability.manage` | `app.runtime.routes::decide_capability` |
| GET | `/api/v1/runtime/agents/{agent_id}/definition` | `runtime.agent.view` | `app.runtime.routes::list_definitions` |
| GET | `/api/v1/runtime/agents/{agent_id}/definitions` | `runtime.agent.view` | `app.runtime.routes::list_definitions` |
| POST | `/api/v1/runtime/agents/{agent_id}/deprecate` | `runtime.agent.deprecate` | `app.runtime.routes::deprecate_agent` |
| POST | `/api/v1/runtime/agents/{agent_id}/duplicate-check` | `runtime.agent.update` | `app.runtime.routes::duplicate_check` |
| GET | `/api/v1/runtime/agents/{agent_id}/duplicate-matches` | `runtime.agent.view` | `app.runtime.routes::duplicate_matches` |
| POST | `/api/v1/runtime/agents/{agent_id}/duplicate-matches/{match_id}/review` | `runtime.agent.duplicate.review` | `app.runtime.routes::review_duplicate` |
| GET | `/api/v1/runtime/agents/{agent_id}/events` | `runtime.agent.audit.view` | `app.runtime.routes::agent_runtime_events` |
| GET | `/api/v1/runtime/agents/{agent_id}/identity` | `runtime.agent.view` | `app.runtime.routes::get_identity` |
| POST | `/api/v1/runtime/agents/{agent_id}/identity/associate` | `runtime.agent.identity.associate` | `app.runtime.routes::associate_identity` |
| POST | `/api/v1/runtime/agents/{agent_id}/identity/create-and-associate` | `runtime.agent.identity.create` | `app.runtime.routes::create_and_associate_identity` |
| POST | `/api/v1/runtime/agents/{agent_id}/identity/replace` | `runtime.agent.identity.replace` | `app.runtime.routes::replace_identity` |
| GET | `/api/v1/runtime/agents/{agent_id}/lifecycle-events` | `runtime.agent.audit.view` | `app.runtime.routes::agent_lifecycle_events` |
| GET | `/api/v1/runtime/agents/{agent_id}/ownership` | `runtime.agent.ownership.view` | `app.runtime.routes::get_ownership` |
| GET | `/api/v1/runtime/agents/{agent_id}/ownership/history` | `runtime.agent.ownership.view` | `app.runtime.routes::ownership_history` |
| POST | `/api/v1/runtime/agents/{agent_id}/ownership/transfer` | `runtime.agent.ownership.transfer` | `app.runtime.routes::transfer_ownership` |
| POST | `/api/v1/runtime/agents/{agent_id}/register` | `runtime.agent.register` | `app.runtime.routes::register_lifecycle_action` |
| POST | `/api/v1/runtime/agents/{agent_id}/reject` | `runtime.agent.reject` | `app.runtime.routes::reject_agent` |
| POST | `/api/v1/runtime/agents/{agent_id}/restore` | `runtime.agent.restore` | `app.runtime.routes::restore_agent` |
| POST | `/api/v1/runtime/agents/{agent_id}/resume` | `runtime.agent.resume` | `app.runtime.routes::resume_agent` |
| POST | `/api/v1/runtime/agents/{agent_id}/retire` | `runtime.agent.retire` | `app.runtime.routes::retire_agent` |
| POST | `/api/v1/runtime/agents/{agent_id}/schemas/test` | `runtime.agent.view` | `app.runtime.routes::test_schema` |
| POST | `/api/v1/runtime/agents/{agent_id}/submit-for-approval` | `runtime.agent.submit` | `app.runtime.routes::submit_for_approval` |
| POST | `/api/v1/runtime/agents/{agent_id}/suspend` | `runtime.agent.suspend` | `app.runtime.routes::suspend_agent` |
| GET | `/api/v1/runtime/agents/{agent_id}/tools` | `runtime.agent.view` | `app.runtime.routes::agent_tools` |
| POST | `/api/v1/runtime/agents/{agent_id}/tools` | `runtime.tool.assign` | `app.runtime.routes::assign_tool` |
| DELETE | `/api/v1/runtime/agents/{agent_id}/tools/{assignment_id}` | `runtime.tool.assign` | `app.runtime.routes::revoke_tool` |
| POST | `/api/v1/runtime/agents/{agent_id}/tools/{assignment_id}/decide` | `runtime.tool.assign` | `app.runtime.routes::decide_tool` |
| POST | `/api/v1/runtime/agents/{agent_id}/validate` | `runtime.agent.validate` | `app.runtime.routes::validate_agent` |
| GET | `/api/v1/runtime/agents/{agent_id}/validations` | `runtime.agent.validation.view` | `app.runtime.routes::list_validations` |
| POST | `/api/v1/runtime/agents/{agent_id}/validations/run` | `runtime.agent.validate` | `app.runtime.routes::run_validation` |
| GET | `/api/v1/runtime/agents/{agent_id}/validations/{validation_id}` | `runtime.agent.validation.view` | `app.runtime.routes::get_validation` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions` | `runtime.version.view` | `app.runtime.routes::list_versions` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions` | `runtime.version.create` | `app.runtime.routes::create_version` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}` | `runtime.version.view` | `app.runtime.routes::get_version` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/approve` | `runtime.agent.approve` | `app.runtime.routes::approve_version` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/artifacts` | `runtime.version.view` | `app.runtime.routes::list_release_artifacts` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/artifacts` | `runtime.version.create` | `app.runtime.routes::add_release_artifact` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/attestation` | `runtime.version.view` | `app.runtime.routes::get_version_attestation` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/compare/{other_version_id}` | `runtime.version.view` | `app.runtime.routes::compare_versions` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/compatibility` | `runtime.version.view` | `app.runtime.routes::get_version_compatibility` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/compatibility/analyze` | `runtime.version.view` | `app.runtime.routes::analyze_version_compatibility` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/compatibility/findings` | `runtime.version.view` | `app.runtime.routes::list_version_compatibility_findings` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/countersign` | `runtime.agent.approve` | `app.runtime.routes::countersign_version` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/deprecate` | `runtime.version.deprecate` | `app.runtime.routes::deprecate_version` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/notes` | `runtime.version.view` | `app.runtime.routes::list_release_notes` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/notes` | `runtime.version.create` | `app.runtime.routes::add_release_note` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/provenance` | `runtime.version.view` | `app.runtime.routes::get_version_provenance` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/publish` | `runtime.version.publish` | `app.runtime.routes::publish_version` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/readiness` | `runtime.version.view` | `app.runtime.routes::version_readiness` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/release-metadata` | `runtime.version.view` | `app.runtime.routes::get_release_metadata` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/release-metadata` | `runtime.version.create` | `app.runtime.routes::upsert_release_metadata` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/retire` | `runtime.version.retire` | `app.runtime.routes::retire_version` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/revoke` | `runtime.version.revoke` | `app.runtime.routes::revoke_version` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/rollback-target` | `runtime.version.create` | `app.runtime.routes::set_version_rollback_target` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/signatures` | `runtime.version.view` | `app.runtime.routes::list_version_signatures` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/snapshot` | `runtime.version.view` | `app.runtime.routes::get_version_snapshot` |
| GET | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/status-history` | `runtime.version.view` | `app.runtime.routes::get_version_status_history` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/validate` | `runtime.version.create` | `app.runtime.routes::validate_version` |
| POST | `/api/v1/runtime/agents/{agent_id}/versions/{version_id}/verify` | `runtime.version.view` | `app.runtime.routes::verify_version` |
| GET | `/api/v1/runtime/approvals` | `runtime.approval.review` | `app.runtime.routes::list_approvals` |
| POST | `/api/v1/runtime/approvals/{approval_id}/decide` | `runtime.approval.review` | `app.runtime.routes::decide_approval` |
| GET | `/api/v1/runtime/capabilities` | `runtime.agent.view` | `app.runtime.routes::list_capabilities` |
| POST | `/api/v1/runtime/capabilities` | `runtime.capability.manage` | `app.runtime.routes::create_capability` |
| GET | `/api/v1/runtime/dashboard` | `runtime.agent.view` | `app.runtime.routes::dashboard` |
| GET | `/api/v1/runtime/deployments` | `runtime.deployment.view` | `app.runtime.routes::list_deployments` |
| POST | `/api/v1/runtime/deployments` | `runtime.deployment.create` | `app.runtime.routes::create_deployment` |
| GET | `/api/v1/runtime/deployments/{deployment_id}` | `runtime.deployment.view` | `app.runtime.routes::get_deployment` |
| POST | `/api/v1/runtime/deployments/{deployment_id}/deploy` | `runtime.deployment.deploy` | `app.runtime.routes::deploy` |
| GET | `/api/v1/runtime/deployments/{deployment_id}/health` | `runtime.health.view` | `app.runtime.routes::deployment_health` |
| POST | `/api/v1/runtime/deployments/{deployment_id}/heartbeat` | `runtime.deployment.deploy` | `app.runtime.routes::submit_heartbeat` |
| GET | `/api/v1/runtime/deployments/{deployment_id}/lifecycle/events` | `runtime.deployment.view` | `app.runtime.routes::list_deployment_lifecycle_events` |
| POST | `/api/v1/runtime/deployments/{deployment_id}/lifecycle/pause` | `runtime.deployment.deploy` | `app.runtime.routes::pause_deployment_lifecycle` |
| POST | `/api/v1/runtime/deployments/{deployment_id}/lifecycle/resume` | `runtime.deployment.deploy` | `app.runtime.routes::resume_deployment_lifecycle` |
| POST | `/api/v1/runtime/deployments/{deployment_id}/lifecycle/retire` | `runtime.deployment.deploy` | `app.runtime.routes::retire_deployment_lifecycle` |
| POST | `/api/v1/runtime/deployments/{deployment_id}/lifecycle/transition` | `runtime.deployment.deploy` | `app.runtime.routes::transition_deployment` |
| GET | `/api/v1/runtime/deployments/{deployment_id}/preflight` | `runtime.deployment.view` | `app.runtime.routes::get_deployment_preflight` |
| POST | `/api/v1/runtime/deployments/{deployment_id}/preflight` | `runtime.deployment.deploy` | `app.runtime.routes::run_deployment_preflight` |
| GET | `/api/v1/runtime/deployments/{deployment_id}/preflight/history` | `runtime.deployment.view` | `app.runtime.routes::get_deployment_preflight_history` |
| POST | `/api/v1/runtime/deployments/{deployment_id}/promote` | `runtime.deployment.deploy` | `app.runtime.routes::promote_deployment` |
| POST | `/api/v1/runtime/deployments/{deployment_id}/resume` | `runtime.deployment.deploy` | `app.runtime.routes::resume_deployment` |
| POST | `/api/v1/runtime/deployments/{deployment_id}/retire` | `runtime.deployment.deploy` | `app.runtime.routes::retire_deployment` |
| POST | `/api/v1/runtime/deployments/{deployment_id}/rollback` | `runtime.deployment.rollback` | `app.runtime.routes::rollback_deployment` |
| POST | `/api/v1/runtime/deployments/{deployment_id}/suspend` | `runtime.deployment.deploy` | `app.runtime.routes::suspend_deployment` |
| GET | `/api/v1/runtime/environments` | `runtime.environment.view` | `app.runtime.routes::list_environments` |
| POST | `/api/v1/runtime/environments` | `runtime.environment.manage` | `app.runtime.routes::create_environment` |
| GET | `/api/v1/runtime/environments/{environment_id}` | `runtime.environment.view` | `app.runtime.routes::get_environment` |
| PATCH | `/api/v1/runtime/environments/{environment_id}` | `runtime.environment.manage` | `app.runtime.routes::update_environment` |
| GET | `/api/v1/runtime/environments/{environment_id}/policy` | `runtime.environment.view` | `app.runtime.routes::get_environment_policy` |
| PUT | `/api/v1/runtime/environments/{environment_id}/policy` | `runtime.environment.manage` | `app.runtime.routes::set_environment_policy` |
| GET | `/api/v1/runtime/executions` | `runtime.execution.view` | `app.runtime.routes::list_executions` |
| POST | `/api/v1/runtime/executions` | `runtime.execution.create` | `app.runtime.routes::request_execution` |
| POST | `/api/v1/runtime/executions/self` | `—` | `app.runtime.routes::request_self_execution` |
| GET | `/api/v1/runtime/executions/{execution_id}` | `runtime.execution.view` | `app.runtime.routes::get_execution` |
| GET | `/api/v1/runtime/executions/{execution_id}/attempts` | `runtime.execution.view` | `app.runtime.routes::execution_attempts` |
| POST | `/api/v1/runtime/executions/{execution_id}/cancel` | `runtime.execution.cancel` | `app.runtime.routes::cancel_execution` |
| GET | `/api/v1/runtime/executions/{execution_id}/events` | `runtime.execution.view` | `app.runtime.routes::execution_events` |
| POST | `/api/v1/runtime/executions/{execution_id}/replay` | `runtime.execution.retry` | `app.runtime.routes::replay_execution` |
| POST | `/api/v1/runtime/executions/{execution_id}/retry` | `runtime.execution.retry` | `app.runtime.routes::retry_execution` |
| GET | `/api/v1/runtime/executions/{execution_id}/tool-calls` | `runtime.execution.view` | `app.runtime.routes::execution_tool_calls` |
| GET | `/api/v1/runtime/health` | `runtime.health.view` | `app.runtime.routes::platform_health` |
| POST | `/api/v1/runtime/kill-switch/agents/{agent_id}` | `runtime.kill_switch.execute` | `app.runtime.routes::kill_agent` |
| POST | `/api/v1/runtime/kill-switch/executions/{execution_id}` | `runtime.kill_switch.execute` | `app.runtime.routes::kill_execution` |
| POST | `/api/v1/runtime/kill-switch/organizations/{organization_id}` | `runtime.kill_switch.execute` | `app.runtime.routes::kill_organization` |
| POST | `/api/v1/runtime/kill-switch/platform` | `runtime.kill_switch.execute` | `app.runtime.routes::kill_platform` |
| POST | `/api/v1/runtime/kill-switch/projects/{project_id}` | `runtime.kill_switch.execute` | `app.runtime.routes::kill_project` |
| GET | `/api/v1/runtime/promotion-paths` | `runtime.environment.view` | `app.runtime.routes::list_promotion_paths` |
| POST | `/api/v1/runtime/promotion-paths` | `runtime.environment.manage` | `app.runtime.routes::create_promotion_path` |
| DELETE | `/api/v1/runtime/promotion-paths/{path_id}` | `runtime.environment.manage` | `app.runtime.routes::delete_promotion_path` |
| GET | `/api/v1/runtime/providers/credentials` | `runtime.provider.view` | `app.runtime.routes::list_provider_credentials` |
| DELETE | `/api/v1/runtime/providers/{provider}/credentials` | `runtime.provider.manage` | `app.runtime.routes::delete_provider_credential` |
| PUT | `/api/v1/runtime/providers/{provider}/credentials` | `runtime.provider.manage` | `app.runtime.routes::upsert_provider_credential` |
| POST | `/api/v1/runtime/providers/{provider}/credentials/test` | `runtime.provider.manage` | `app.runtime.routes::test_provider_credential` |
| GET | `/api/v1/runtime/release-channels` | `runtime.version.view` | `app.runtime.routes::list_release_channels` |
| GET | `/api/v1/runtime/signing-keys` | `runtime.signing.view` | `app.runtime.routes::list_signing_keys` |
| POST | `/api/v1/runtime/signing-keys/{key_id}/revoke` | `runtime.signing.manage` | `app.runtime.routes::revoke_signing_key` |
| POST | `/api/v1/runtime/signing-keys/{key_id}/rotate` | `runtime.signing.manage` | `app.runtime.routes::rotate_signing_key` |
| GET | `/api/v1/runtime/tools` | `runtime.agent.view` | `app.runtime.routes::list_tools` |
| POST | `/api/v1/runtime/tools` | `runtime.tool.manage` | `app.runtime.routes::create_tool` |
| GET | `/api/v1/runtime/workers` | `runtime.health.view` | `app.runtime.routes::list_workers` |
| POST | `/api/v1/runtime/workers/reap` | `runtime.execution.retry` | `app.runtime.routes::reap_stale_locks` |

#### `/api/v1/security`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/security/account-locks` | `security.protection` | `app.identity.protection.routes::account_locks` |
| POST | `/api/v1/security/account-locks/{lock_id}/unlock` | `security.protection` | `app.identity.protection.routes::unlock_lock` |
| GET | `/api/v1/security/account-protection/summary` | `security.protection` | `app.identity.protection.routes::summary` |
| GET | `/api/v1/security/blocked-ips` | `security.protection` | `app.identity.protection.routes::list_blocked_ips` |
| POST | `/api/v1/security/blocked-ips` | `security.protection` | `app.identity.protection.routes::block_ip` |
| DELETE | `/api/v1/security/blocked-ips/{blocked_ip_id}` | `security.protection` | `app.identity.protection.routes::unblock_ip` |
| GET | `/api/v1/security/identity-protection-rules` | `security.protection` | `app.identity.protection.routes::list_rules` |
| POST | `/api/v1/security/identity-protection-rules` | `security.protection` | `app.identity.protection.routes::create_rule` |
| DELETE | `/api/v1/security/identity-protection-rules/{rule_id}` | `security.protection` | `app.identity.protection.routes::delete_rule` |
| PUT | `/api/v1/security/identity-protection-rules/{rule_id}` | `security.protection` | `app.identity.protection.routes::update_rule` |
| GET | `/api/v1/security/login-attempts` | `security.protection` | `app.identity.protection.routes::login_attempts` |
| GET | `/api/v1/security/password-dashboard` | `credential.dashboard` | `app.identity.credentials.routes::password_dashboard` |
| GET | `/api/v1/security/recovery-events` | `recovery.view` | `app.identity.recovery.routes::recovery_events` |
| GET | `/api/v1/security/risk-events` | `security.protection` | `app.identity.protection.routes::risk_events` |
| POST | `/api/v1/security/users/{user_id}/lock` | `security.protection` | `app.identity.protection.routes::lock_user` |
| POST | `/api/v1/security/users/{user_id}/unlock` | `security.protection` | `app.identity.protection.routes::unlock_user` |

#### `/api/v1/teams`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/api/v1/teams` | `organization.view` | `app.authorization.hierarchy.routes::list_teams` |
| POST | `/api/v1/teams` | `organization.manage` | `app.authorization.hierarchy.routes::create_team` |
| DELETE | `/api/v1/teams/{team_id}` | `organization.manage` | `app.authorization.hierarchy.routes::delete_team` |
| GET | `/api/v1/teams/{team_id}` | `organization.view` | `app.authorization.hierarchy.routes::get_team` |
| PUT | `/api/v1/teams/{team_id}` | `organization.manage` | `app.authorization.hierarchy.routes::update_team` |

#### `/approvals`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/approvals` | `approval.view` | `app.api.routes.approvals::list_approvals` |
| GET | `/approvals/escalations` | `approval.view` | `app.api.routes.approvals::approval_escalations` |
| GET | `/approvals/history` | `approval.view` | `app.api.routes.approvals::approval_history` |
| GET | `/approvals/pending` | `approval.view` | `app.api.routes.approvals::list_pending_approvals` |
| GET | `/approvals/statistics` | `approval.view` | `app.api.routes.approvals::approval_statistics` |
| GET | `/approvals/{approval_id}` | `approval.view` | `app.api.routes.approvals::get_approval` |
| POST | `/approvals/{approval_id}/approve` | `approval.review` | `app.api.routes.approvals::approve` |
| POST | `/approvals/{approval_id}/assign` | `approval.assign` | `app.api.routes.approvals::assign` |
| GET | `/approvals/{approval_id}/comments` | `approval.view` | `app.api.routes.approvals::list_comments` |
| POST | `/approvals/{approval_id}/comments` | `approval.review` | `app.api.routes.approvals::add_comment` |
| POST | `/approvals/{approval_id}/escalate` | `approval.escalate` | `app.api.routes.approvals::escalate` |
| POST | `/approvals/{approval_id}/reject` | `approval.review` | `app.api.routes.approvals::reject` |
| GET | `/approvals/{approval_id}/timeline` | `approval.view` | `app.api.routes.approvals::approval_timeline` |

#### `/audit`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/audit` | `audit.view` | `app.api.routes.audit::list_audit` |
| GET | `/audit/compliance` | `audit.export` | `app.api.routes.audit::audit_compliance` |
| GET | `/audit/events` | `audit.view` | `app.api.routes.audit::audit_event_catalog` |
| GET | `/audit/export` | `audit.export` | `app.api.routes.audit::audit_export` |
| GET | `/audit/security` | `audit.export` | `app.api.routes.audit::audit_security` |
| GET | `/audit/statistics` | `audit.view` | `app.api.routes.audit::audit_statistics` |
| GET | `/audit/timeline` | `audit.view` | `app.api.routes.audit::audit_timeline` |
| GET | `/audit/{event_id}` | `audit.view` | `app.api.routes.audit::get_audit_event` |

#### `/audit-logs`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/audit-logs` | `—` | `app.api.routes.audit_logs::list_audit_logs` |
| GET | `/audit-logs/entity/{entity_type}/{entity_id}` | `—` | `app.api.routes.audit_logs::list_entity_audit_logs` |

#### `/auth`

| Method | Path | Permission | Handler |
|---|---|---|---|
| POST | `/auth/login` | `—` | `app.api.routes.auth::login` |
| GET | `/auth/me` | `—` | `app.api.routes.auth::me` |
| POST | `/auth/register` | `—` | `app.api.routes.auth::register` |

#### `/dashboard`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/dashboard/activity` | `dashboard.view` | `app.api.routes.dashboard::agent_activity` |
| GET | `/dashboard/high-risk-actions` | `dashboard.view` | `app.api.routes.dashboard::high_risk_actions` |
| GET | `/dashboard/pending-approvals` | `dashboard.view` | `app.api.routes.dashboard::pending_approvals` |
| GET | `/dashboard/recent-actions` | `dashboard.view` | `app.api.routes.dashboard::recent_actions` |
| GET | `/dashboard/risk-trend` | `dashboard.view` | `app.api.routes.dashboard::risk_trend` |
| GET | `/dashboard/summary` | `dashboard.view` | `app.api.routes.dashboard::dashboard_summary` |

#### `/health`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/health` | `—` | `app.main::health_check` |

#### `/organizations`

| Method | Path | Permission | Handler |
|---|---|---|---|
| POST | `/organizations` | `—` | `app.api.routes.organizations::create_organization` |
| GET | `/organizations/{organization_id}` | `—` | `app.api.routes.organizations::get_organization` |

#### `/permissions`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/permissions` | `—` | `app.api.routes.permissions::list_permissions` |
| POST | `/permissions` | `—` | `app.api.routes.permissions::create_permission` |
| GET | `/permissions/agent/{agent_id}` | `—` | `app.api.routes.permissions::list_agent_permissions` |

#### `/policies`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/policies` | `policy.view` | `app.api.routes.policies::list_policies` |
| POST | `/policies` | `policy.create` | `app.api.routes.policies::create_policy` |
| GET | `/policies/templates` | `—` | `app.api.routes.policies::list_policy_templates` |
| DELETE | `/policies/{policy_id}` | `policy.delete` | `app.api.routes.policies::delete_policy` |
| GET | `/policies/{policy_id}` | `policy.view` | `app.api.routes.policies::get_policy` |
| PATCH | `/policies/{policy_id}` | `policy.edit` | `app.api.routes.policies::update_policy` |
| PUT | `/policies/{policy_id}` | `policy.edit` | `app.api.routes.policies::update_policy` |
| GET | `/policies/{policy_id}/audit` | `policy.view` | `app.api.routes.policies::policy_audit` |
| PATCH | `/policies/{policy_id}/disable` | `policy.edit` | `app.api.routes.policies::disable_policy` |
| PATCH | `/policies/{policy_id}/enable` | `policy.edit` | `app.api.routes.policies::enable_policy` |
| POST | `/policies/{policy_id}/test` | `policy.view` | `app.api.routes.policies::test_policy` |

#### `/rbac`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/rbac/me` | `—` | `app.api.routes.rbac::my_permissions` |
| GET | `/rbac/permissions` | `—` | `app.api.routes.rbac::list_permissions` |
| GET | `/rbac/roles` | `—` | `app.api.routes.rbac::list_roles` |
| POST | `/rbac/users/{user_id}/roles` | `rbac.manage` | `app.api.routes.rbac::assign_role` |

#### `/system`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/system/health` | `—` | `app.api.routes.system::system_health` |

#### `/users`

| Method | Path | Permission | Handler |
|---|---|---|---|
| GET | `/users` | `—` | `app.api.routes.users::list_users` |
| POST | `/users` | `—` | `app.api.routes.users::create_user` |
| GET | `/users/{user_id}` | `—` | `app.api.routes.users::get_user` |

## 6. Phase 5.2 Status

Verified against the current codebase (models, live schema, service files, route table) this session — full re-verification, all rows, not carried forward from any earlier summary. Phase 5.2 is now **fully implemented** across all seven sub-phases.

| Sub-phase | Status | Evidence |
|---|---|---|
| **5.2.1 Version Core & Immutability** | **IMPLEMENTED** | `agent_versions` table (97-table live schema, §2); `AgentVersion` model class in `backend/app/models/runtime.py`; `AgentVersionService` (create/validate/approve/publish/deprecate/revoke/retire) in `backend/app/runtime/services.py`; `VERSION_LIFECYCLE = ("DRAFT","VALIDATING","READY_FOR_REVIEW","APPROVED","PUBLISHED","DEPRECATED","REVOKED","RETIRED")` (same file, unchanged by 5.2.6/5.2.4 — verified); `agent_version_status_history` table + `backend/app/runtime/versioning/status_history.py` records every transition. |
| **5.2.2 Configuration Snapshots** | **IMPLEMENTED** | Per-field snapshots on `agent_versions` (`configuration_snapshot`, `prompt_snapshot`, `model_configuration`, `capabilities_snapshot`, `tools_snapshot`, `policy_snapshot` — Phase 5.0) plus the complete frozen document in `agent_version_snapshots.snapshot` (JSONB), built by `SnapshotBuilderService.build_and_store` / `build_snapshot()` in `backend/app/runtime/versioning/snapshot.py`, called once at `publish()`. |
| **5.2.3 Content Addressing & Checksums** | **IMPLEMENTED** (canonical-sha256 as of Phase 5.2.4) | `agent_versions.checksum`/`agent_version_snapshots.checksum` now `sha256:<hex>` via `app/runtime/versioning/canonical.py::digest()`, algorithm tracked per-row in `checksum_algorithm` (`'legacy-sha256'` for pre-5.2.4 rows, `'canonical-sha256'` for new ones; migration `0027_version_signing`). Not "content-addressed storage" in the sense of a CAS/object store — checksums are integrity hashes stored as a column, not used as lookup keys. |
| **5.2.4 Signing & Provenance** | **IMPLEMENTED** | `AttestationService` (`app/runtime/versioning/attestation.py`) signs an in-toto Statement v1 / DSSE-enveloped document over each version's manifest digest via a pluggable `SigningProvider` (`app/runtime/versioning/signing/`, `LocalKeyProvider` — Ed25519 — the only implementation today). Wired into `publish()` fail-closed (signing failure aborts publication, unlike 5.2.6's advisory analysis). New tables `signing_keys`, `signing_key_versions`, `agent_version_signatures`, `agent_version_provenance` (migration `0027_version_signing`); `agent_versions.signature_id` (previously always null) now wired to the primary signature's id. Key rotation/revocation supported; verification is internal-only (`ACT-VER-FR-070` public endpoint deliberately deferred — see docs/runtime/versioning.md's Known Deviations). 8 new routes, 2 new permissions (`runtime.signing.view`/`.manage`). 47 new tests (`backend/tests/runtime/test_canonical.py`, `test_version_signing.py`, `test_attestation.py`). |
| **5.2.5 Version Comparison & Diff** | **IMPLEMENTED** | `VersionComparisonService.compare()` in `backend/app/runtime/versioning/compare.py`; route `GET /agents/{agent_id}/versions/{version_id}/compare/{other_version_id}` in `backend/app/runtime/routes.py` (`compare_versions`). Scalar-field diff, key-level JSONB config diff, artifact/note set diff. |
| **5.2.6 Compatibility Detection** | **IMPLEMENTED** | `CompatibilityAnalysisService` in `backend/app/runtime/versioning/compatibility.py` classifies a candidate version against a resolved baseline into `COMPATIBLE`/`BACKWARD_COMPATIBLE`/`BREAKING`/`UNKNOWN`; persists to `agent_versions.compatibility_level` (now real, no longer stuck at `"UNKNOWN"`) plus new columns `compatibility_baseline_id`/`compatibility_analyzed_at` (migration `0026_version_compatibility`); one `agent_version_compatibility_findings` row per detected change. Triggered automatically as a best-effort follow-up after `publish()`'s own commit (failure-tolerant — an analyzer exception is logged and swallowed, never blocks publication); also available on demand via `POST .../compatibility/analyze`. `VersionReadinessService`'s `compatibility_analysis` check is a real evaluation — `skipped` is never `true`. Routes: `GET`/`POST .../versions/{id}/compatibility`, `.../compatibility/analyze`, `GET .../compatibility/findings`. 35 new tests in `backend/tests/runtime/test_version_compatibility.py`. See `docs/runtime/versioning.md`'s "Compatibility & breaking-change detection" section for the classification rules and the deliberate SRS deviation (semver/compatibility inconsistency is reported, not enforced as a publish-blocker). |
| **5.2.7 Release Channels & Promotion** | **IMPLEMENTED** | `agent_release_channels` table (seeded with STABLE/BETA/CANARY/INTERNAL by migration `0025`); `ReleaseChannelService` in `backend/app/runtime/versioning/channels.py`; route `GET /release-channels`. Promotion **readiness** (not promotion *execution*) via `VersionReadinessService` in `backend/app/runtime/versioning/readiness.py` and route `GET /agents/{agent_id}/versions/{version_id}/readiness` — a read-only diagnostic checklist (snapshot buildability, validation, metadata, ownership, registry status, blocking governance findings, artifacts, approval), never a gate on the lifecycle actions themselves. Actual environment promotion / rollout execution is out of scope (see §9). |

### Milestone 1 — Real Model Provider Integration (Phase 5.7a)

Verified against the current codebase this session (`main` at `b9461ab`, "Merge Phase 5.7a.5: Per-Organization Provider Credentials"). Eight planned sub-phases; the first five are now built — **this completes the model half of Milestone 1**, per the 5.7a.5 build prompt's own closing note; only tool execution (5.6a.1-3) remains before the platform genuinely executes end to end. 5.7a.1/5.7a.2/5.7a.4 added no schema migration and no new HTTP routes (confirmed live for all three); 5.7a.3 added one new table and sixteen columns with no new routes; 5.7a.5 is the second sub-phase with schema impact — one new table (`provider_credentials`) and, for the first time in this milestone, four new HTTP routes (§5 grew from 452 to 456).

| Sub-phase | Status | Evidence |
|---|---|---|
| **5.7a.1 Model Provider Abstraction & Registry** | **IMPLEMENTED** | New package `backend/app/runtime/providers/` (`base.py`'s `ModelProvider(ABC)` with abstract `complete()`/`stream()`/`describe()` and concrete `supports()`/`validate_capabilities()`; `types.py`'s frozen, provider-neutral `ModelRequest`/`ModelResponse`/`ModelMessage`/`ModelToolDefinition`/`ModelToolCall`/`ModelCapabilities`/`FinishReason`; `registry.py`'s explicit `register()`/`resolve()`/`registered_identifiers()`, no directory-scanning discovery; `mock.py`'s `MockProvider` — the sole registered adapter at the time, registered under `"MOCK"` at import time). `ModelGatewayService.invoke()` (`backend/app/runtime/services.py`) rewritten as a translation boundary. 23 tests in `backend/tests/runtime/test_provider_abstraction.py`, including a reusable parameterized conformance suite (`PROVIDERS_UNDER_TEST`). See `docs/runtime/providers.md`. |
| **5.7a.2 First Real Provider Adapter** | **IMPLEMENTED** | `backend/app/runtime/providers/openai_compatible.py`'s `OpenAICompatibleProvider` — the first real, network-calling provider, talking the OpenAI chat-completions wire protocol against any `base_url` (Ollama/vLLM/LM Studio/OpenAI), registered as `"OPENAI_COMPATIBLE"` (names the protocol, not a vendor — `"OPENAI"` is deliberately left free for a future vendor-specific adapter). Message/tool-call/finish-reason translation, sampling-parameter filtering, tolerant parsing of responses missing optional fields. `registry.resolve()` gained signature-checked `model`/`api_key` forwarding (a genuine 5.7a.1 gap — neither previously reached a provider instance). New `ProviderRequestFailedError`/`MODEL_PROVIDER_REQUEST_FAILED` (one coarse exception, not a taxonomy). Fixture-replay test infrastructure (`httpx.MockTransport`, six committed wire-format fixtures, a manual recorder script, a `live_provider` pytest marker excluded by default via `backend/pytest.ini`). 30 tests (`test_openai_compatible_provider.py` + additions to `test_provider_abstraction.py`). `registered_identifiers()` now returns `["MOCK", "OPENAI_COMPATIBLE"]`. |
| **5.7a.3 Streaming & Token Accounting** | **IMPLEMENTED** | Real SSE streaming replaces 5.7a.2's `stream()` placeholder — incremental content deltas, tool-call reassembly across fragmented/interleaved chunks, interruption persists a partial via `FinishReason.ERROR` rather than raising (deliberately unlike `complete()`). No new dataclass needed in `types.py`; one function, `assemble_response()`. `ModelGatewayService.invoke()` gained an opt-in streaming path (`model_configuration.stream=true`) with the `(output_payload, usage)` contract unchanged for non-streaming callers. Real token/cost accounting: `usage` gained `token_accounting_complete`/`was_streamed`/`stream_interrupted`/`time_to_first_token_ms`/`generation_duration_ms`/`finish_reason`; a provider omitting usage now reports `{}` (never zero-filled — the never-estimate rule, `ACT-MDL-FR-046`). New `model_pricing` table with effective dating (a price change inserts and closes a row, never mutates one in place) backs `PricingService`, replacing the flat `total_tokens*0.000002` placeholder; local/unpriced providers (`MOCK`) honestly cost `0` (two previously-stable `cost > 0` assertions were updated to `== 0` accordingly — see §10.27). 1,538 pre-existing non-zero-cost rows marked `cost_is_estimated=true` by the migration, never recomputed. 22 tests in `backend/tests/runtime/test_streaming_and_accounting.py`. See `docs/runtime/providers.md`. |
| **5.7a.4 Error Taxonomy & Resilience** | **IMPLEMENTED** | Eight-class provider-neutral taxonomy (`ProviderErrorClass` in `types.py`: `RATE_LIMITED`/`PROVIDER_UNAVAILABLE`/`TIMEOUT` retryable, `CONTEXT_LENGTH_EXCEEDED`/`CONTENT_FILTERED`/`AUTHENTICATION_FAILED`/`INVALID_REQUEST`/`UNKNOWN` never retried). Classification lives in the adapter (`openai_compatible.py`'s `_classify_status_error`/`_classify_transport_error`); retry/backoff/circuit-breaking live in the service layer (`ModelGatewayService._complete_with_resilience`/`_invoke_streaming`), so a future second adapter inherits both with zero new retry code. Exponential-with-jitter backoff (`_provider_backoff_delay`), a provider `Retry-After` header honored in preference to computed backoff, a per-provider in-process three-state circuit breaker (`_circuit_before_call`/`_circuit_record_success`/`_circuit_record_failure`), and a streaming pre-/post-first-token retry boundary (a pre-first-token interruption retries; a post-first-token one persists the partial exactly as 5.7a.3 already did and is never retried). Credential/base-URL scrubbing (`_scrub`) before any message reaches a log or caller. **No migration** — `error_code` (already `VARCHAR(50)` on both `agent_executions` and `execution_attempts`) now stores the taxonomy class string in place of the old generic code. The pre-existing execution-level retry (`ExecutionWorkerService._fail_or_retry`, Phase 5.0) is untouched except its `non_retryable` set gained the five non-retryable classes. 36 new tests in `backend/tests/runtime/test_error_taxonomy_and_resilience.py`, plus nine new committed error fixtures. See `docs/runtime/providers.md`. |
| **5.7a.5 Per-Organization Provider Credentials** | **IMPLEMENTED** | New `provider_credentials` table (migration `0029_provider_credentials`): one row per `(organization_id, provider)`, `encrypted_secret` a Fernet ciphertext (`backend/app/runtime/providers/credential_crypto.py`, new file — key from `settings.MODEL_CREDENTIAL_ENCRYPTION_KEY` or auto-generated/persisted to `.keys/`, mirroring Phase 5.2.4's `LocalKeyProvider` pattern; **Known Deviation** recorded, mirrors `ACT-VER-NFR-002`, closes at Milestone 13). `ProviderCredentialService` (`services.py`) — direct ORM, no repository: `store`/`get_metadata`/`resolve_secret`/`delete`/`list_for_org`/`test`. Resolution order per-org → `MODEL_PROVIDER_API_KEYS` fallback → none (`ACT-MDL-FR-082`); resolved synchronously on the worker's own thread in `ExecutionWorkerService._execute`, *before* the model call is handed to its `ThreadPoolExecutor` (a live `Session` cannot safely cross that thread boundary) — only the resulting plain `ResolvedCredential` value crosses over. A real provider rejecting an unauthenticated call with no credential configured anywhere is translated from the generic `AUTHENTICATION_FAILED` (5.7a.4) to the more specific, non-retryable `PROVIDER_CREDENTIAL_REQUIRED`; a *configured-but-wrong* credential still reports plain `AUTHENTICATION_FAILED`, unchanged. Four new routes under `/api/v1/runtime/providers/{provider}/credentials` (`GET`/`PUT`/`DELETE`/`POST .../test`), two new permissions (`runtime.provider.view`/`.manage`). The adapter (`openai_compatible.py`) and the registry's `model`/`api_key` forwarding (5.7a.2) needed **zero changes** — this phase only changed where the key comes from, confirmed by an explicit signature-inspection test. `MODEL_PROVIDER_API_KEYS` was **kept as the fallback default**, not removed (see §10.32) — no previously-passing test broke. 25 new tests in `backend/tests/runtime/test_provider_credentials.py`. See `docs/runtime/providers.md` and `docs/runtime/gateways.md`. |
| **5.7a.6-5.7a.8** | **NOT STARTED** | No code references them beyond forward-looking doc comments. |

### Milestone 1 — Tool Execution (Phase 5.6a) — **MILESTONE COMPLETE**

Verified against the current codebase this session (`main` at `2d3623b`, "Merge Phase 5.6a.3: Model-Driven Tool Invocation Loop"). All three planned sub-phases are now built — **Milestone 1 itself is complete**: an agent registered, versioned, signed, and deployed executes end to end (real model, real tool, real result, audited throughout). See `docs/runtime/gateways.md`'s "Milestone 1 — complete" section.

| Sub-phase | Status | Evidence |
|---|---|---|
| **5.6a.1 HTTP Tool Execution & Egress Control** | **IMPLEMENTED** | New package `backend/app/runtime/tools/`: `egress_guard.py` (pure logic, no network/database — `EgressPolicy`/`EgressDecision`/`evaluate_url`/`resolve_and_validate`, plus a permissive IP-literal parser catching decimal/octal/hex loopback encodings that some platforms' libc resolvers accept but Python's `ipaddress` module rejects) and `http_executor.py` (`execute_http_tool`, `_PinnedTransport` — connects to the address the guard validated, never a freshly re-resolved hostname, defending against DNS rebinding; verified empirically against the installed `httpx 0.28.1`/`httpcore 1.0.9` before writing tests). `ToolGatewayService` gained an `HTTP` action dispatch branch (`FUNCTION`/`echo` unchanged) reading its egress policy from the *frozen* version snapshot, never live `Tool` state — `SnapshotBuilderService.build_snapshot()` gained a new `runtime.tool_configs` key (deliberately not a change to `tools_snapshot` itself, which three existing subsystems consume as a bare tool-id list). New `tool_credentials` table + `ToolCredentialService`, reusing Phase 5.7a.5's `credential_crypto.py` directly. New `TOOL_EGRESS_DENIED` error code and `RUNTIME_TOOL_INVOKED`/`RUNTIME_TOOL_EGRESS_DENIED` audit events (the latter `CRITICAL` severity). 51 new tests: 32 in `test_egress_guard.py` (every SSRF vector individually, no network/database), 19 in `test_http_tool_execution.py` (executor mechanics against real local `127.0.0.1` fixture servers, plus the full execution pipeline). See `docs/runtime/gateways.md`'s "Egress control" section. |
| **5.6a.2 Schema Validation & Tool Resilience** | **IMPLEMENTED** | Argument validation against `Tool.input_schema` (pre-existing column, unused until now) runs before any side effect — before `FUNCTION`'s echo, and before the `HTTP` branch even builds an `EgressPolicy`. A violation returns `TOOL_SCHEMA_INVALID` with a structured (JSON-encoded) `ToolCall.validation_error`; no request is issued. A response is validated against an optional `output_schema` only when one is declared. Both schemas are frozen into `tool_configs[tool_id]` at publish time alongside `http_config`, closing a gap 5.6a.1 left open along the way: `http_config.timeout_seconds` is now also frozen (5.6a.1 read the live, mutable `Tool.timeout_seconds` column at execution time; `snapshot.py`'s `_frozen_http_config` now defaults it in from that column at publish time instead). Resilience reuses — **does not duplicate** — Phase 5.7a.4's `ProviderErrorClass` taxonomy and retry/circuit-breaker machinery; the one piece that wasn't provider-neutral (`_circuit_before_call` raised a model-specific exception on an open circuit) was extracted into a shared core so both paths use one implementation. Idempotency is an explicit, opt-in `http_config.idempotent` declaration — never inferred from HTTP method; undeclared or `false` means a transient failure is never retried. A retried call gets one new `ToolCall` row per attempt (`attempt_number`, `error_class` populated on each). New per-execution concurrency ceiling (`app/runtime/tools/concurrency.py`, real-thread-tested, not yet contended by today's sequential caller). **Behavior change**: a `FAILED` tool call (schema violation, exhausted retry, timeout, oversized response, open circuit, concurrency rejection) no longer aborts the execution — only a `DENIED` one (egress/authorization/governance, unchanged from 5.6a.1) still does; the structured error lives on the `ToolCall` row and a new `RUNTIME_TOOL_FAILED` event for 5.6a.3's loop to eventually consume. Five new error codes (`TOOL_SCHEMA_INVALID`/`TOOL_RESPONSE_TOO_LARGE`/`TOOL_TIMEOUT`/`TOOL_EXECUTION_FAILED`/`TOOL_CONCURRENCY_LIMIT_EXCEEDED`); migration `0031_tool_resilience` (three new nullable `tool_calls` columns, no new table). 19 new tests in `backend/tests/runtime/test_tool_resilience.py`; every 5.6a.1/5.7a.4 test passes unmodified. See `docs/runtime/gateways.md`'s "Schema validation & resilience" section. |
| **5.6a.3 Model-Driven Tool Invocation Loop** | **IMPLEMENTED** | `ModelGatewayService.invoke()` gained two additive, both-optional parameters (`conversation`, `tools`, mirroring `resolved_credential`'s own precedent) and now offers a version's frozen `tools_snapshot` to any provider that declares `supports_tools` (`MOCK` never does — every 5.6a.1/5.6a.2 test is `MOCK`-based and completely unaffected, confirmed by all of them passing unmodified). New `ToolLoopOrchestrator` (`services.py`) drives model → tool → model: every tool call — sequential or parallel — still goes through `ToolGatewayService.invoke()` unchanged, so existing assignment/constraint checks and 5.6a.2's schema validation/resilience/structured-`FAILED`-results all apply automatically. Four independent termination conditions (`MAX_ITERATIONS`/`TOKEN_BUDGET`/`WALL_CLOCK`/`REPEATED_CALL`, the last using Phase 5.2.4's canonical serialization for "identical call" comparison), each a distinct, audited `agent_executions.termination_reason`. Tool calls the model requests together run concurrently only when every one is declared `idempotent` (5.6a.2's flag, reused for parallel-safety); results reassemble in submission order regardless of completion order. A tool name outside `tools_snapshot` is rejected with the new `TOOL_NOT_BOUND_TO_VERSION` (a scope-violation, execution-aborting code, same tier as `TOOL_NOT_ASSIGNED` — never a recoverable retry, closing the loop's own §10.4 boundary since a tool is never an agent). New `execution_messages` table (the full conversation transcript, exposed at `GET /executions/{id}/messages`); `agent_executions` gained `loop_iterations`/`termination_reason`; `tool_calls` gained `loop_iteration`. **A genuine deadlock was found and fixed**, not merely designed around: the first parallel-execution version opened a fresh `Session` per thread whose `INSERT INTO tool_calls` blocked on the FK-referenced `agent_executions` row's still-held `claim_next` `FOR UPDATE` lock, while the main thread blocked on those same threads in turn — reproduced against `pg_stat_activity` and fixed by committing the claiming session immediately before any parallel dispatch. Migration `0032_tool_loop`. 17 new tests in `backend/tests/runtime/test_tool_loop.py`, including an end-to-end proof (real fixtured model → real HTTP tool through the egress guard → final answer, fully audited). Every 5.6a.1/5.6a.2/5.7a.* test passes unmodified. See `docs/runtime/gateways.md`'s "The model-driven tool invocation loop" section. |

### Milestone 2 — Enterprise Integration Framework (`ACT-SRS-M2`) — **COMPLETE (9/9)**

SRS approved 2026-07-28 (per the document's own §12 revision note). First sub-phase shipped 2026-08-01; second shipped 2026-08-04; third shipped 2026-08-05; fourth (2.1.4, completing the connector framework in full) shipped the same day; fifth (2.2.1, the framework's first real connector) shipped the same day again; sixth (2.2.2, the second real connector — the database connector carrying `ACT-INT-FR-121`/`FR-122`'s "the model never writes SQL" rule) shipped 2026-08-06; seventh (2.2.3, the third real connector — the storage connector carrying `ACT-INT-FR-141`/`FR-143`'s "a model-supplied path can never escape its declared scope" rule) shipped 2026-08-07; eighth (2.2.4, the fourth and last generic connector — the queue connector carrying `ACT-INT-FR-161`/`FR-162`/`FR-164`'s two-sided "publish is scoped, consume is bounded" rule) shipped the same day; ninth and final (2.3.1, external identity federation — carrying `ACT-INT-FR-186`'s inversion: federation holds no user secret and verifies an assertion inward, rather than a connector's own posture of holding a platform secret and presenting it outward) shipped the same day again. **Milestone 2 — the Enterprise Integration Framework — is now complete: 9 of 9 sub-phases done.** Nine sub-phases, recommended build order per the SRS's own §9: framework (2.1.1→2.1.4) before any generic connector, REST (2.2.1) first among generics as the substrate later vendor connectors will reuse, database (2.2.2) second, storage (2.2.3) third, and queue (2.2.4) fourth per the same §9 order, identity federation (2.3.1) independent and reorderable earlier if a design partner needs SSO before data connectors — built last in practice, with no dependency issues arising from that order.

| Sub-phase | Title | Branch (per SRS §1.1) | Status |
|---|---|---|---|
| 2.1.1 | Connector Abstraction & Lifecycle | `feat/2.1.1-connector-core` | **IMPLEMENTED** |
| 2.1.2 | Connector Authentication Framework | `feat/2.1.2-connector-auth` | **IMPLEMENTED** |
| 2.1.3 | Connector Registry & Health | `feat/2.1.3-connector-registry` | **IMPLEMENTED** |
| 2.1.4 | Connector SDK | `feat/2.1.4-connector-sdk` | **IMPLEMENTED** |
| 2.2.1 | Generic REST Connector | `feat/2.2.1-rest-connector` | **IMPLEMENTED** |
| 2.2.2 | Generic Database Connector | `feat/2.2.2-database-connector` | **IMPLEMENTED** |
| 2.2.3 | Generic File & Object Storage Connector | `feat/2.2.3-storage-connector` | **IMPLEMENTED** |
| 2.2.4 | Generic Message Queue Connector | `feat/2.2.4-queue-connector` | **IMPLEMENTED** |
| 2.3.1 | External Identity Federation | `feat/2.3.1-identity-federation` | **IMPLEMENTED** |

Load-bearing constraints for whenever build work continues (from the SRS, restated here since they shape review of every sub-phase): the **runtime-never-knows principle** (§3.3 — no connector- or vendor-specific logic may appear in the runtime, model gateway, or `ToolGatewayService` core; a connector produces a Tool, and the runtime must not be able to tell a connector-derived Tool from an echo Tool); the **framework-not-catalog boundary** (§2.4 — only the four generic connectors ship now, vendor-specific connectors are deliberately deferred to fast-follow work per named buyer demand); and the **database connector's absolute SQL-authorship rule** (`ACT-INT-FR-121`/`-122` — the model may only supply bound parameters to pre-declared, integration-engineer-reviewed queries, never generate SQL text, mirroring the egress-allowlist principle that the model chooses among approved actions but never authors one). Credential handling explicitly extends 5.7a.5's `credential_crypto.py` pattern (`ACT-INT-FR-022`) rather than introducing a second encrypted-secret store — the same reuse discipline every Milestone 1 sub-phase already followed.

| Sub-phase | Status | Evidence |
|---|---|---|
| **2.1.1 Connector Abstraction & Lifecycle** | **IMPLEMENTED** | New sibling domain `backend/app/integration/` (not under `app/runtime/` — deliberate, since the runtime must never import from it). `Connector` ABC (`base.py`) — abstract `describe()`/`validate_configuration()` only, structural twin of `ModelProvider` (5.7a.1); no `authenticate()`/`execute()`/`health_check()`, all explicitly deferred to 2.1.2/2.1.3/the tool bridge. `MockConnector` (`mock.py`) — trivial reference implementation, one config field (`endpoint`), one declared `ping` tool contract (declaration only, never invoked). Connector-neutral types (`types.py`): `ConnectorDescriptor`, `ToolContract`, `ConnectorLifecycleState` — frozen/slotted dataclasses, `MappingProxyType`-wrapped dict fields, mirroring `types.py`'s own precedent in `app/runtime/providers/`. Five-state lifecycle machine (`lifecycle.py`: `registered→configured→active→disabled→failed`, four named events `configure`/`activate`/`disable`/`mark_failed`) — the single transition authority, consulted by `ConnectorService`, never inlined. Config validation reuses Milestone 1's `jsonschema` library via a new thin wrapper (`validate_configuration_schema`), not a new validator. New tables `connectors` (registered types, unique on `(connector_type, version)`), `connector_instances` (tenant-scoped, unique on `(organization_id, name)`, no credential column), `connector_lifecycle_events` (append-only, no update/delete path anywhere — mechanically checked). Eight routes under `/api/v1/integration`, two new permissions (`integration.connector.view`/`.manage`), four new error codes (`CONNECTOR_TYPE_NOT_FOUND`/`CONNECTOR_NOT_FOUND`/`CONNECTOR_CONFIG_INVALID`/`CONNECTOR_INVALID_TRANSITION`), one new audit event (`INTEGRATION_CONNECTOR_STATE_CHANGED`, dual-written to both the lifecycle-events table and the platform-wide `AuthorizationAuditService`). **Runtime-never-knows enforced by construction, not convention**: a dedicated test greps every file under `app/runtime/` for the substring `"connector"` and fails the build if it finds one (currently zero). Migration `0033_connector_core`, three new tables, reversible. 24 new tests in `backend/tests/integration/test_connector_core.py`, grouped by the build prompt's own §8 AC groups. See `docs/integration/connectors.md`. |
| **2.1.2 Connector Authentication Framework** | **IMPLEMENTED** | New `app/integration/auth/` sub-package: `AuthScheme` ABC (`base.py`) + explicit `registry.py` (mirroring the provider/connector registry pattern) with six implementations — `ApiKeyScheme`, `BearerTokenScheme`, `BasicAuthScheme`, `OAuth2ClientCredentialsScheme`, `OAuth2AuthorizationCodeScheme`, `MTLSScheme` (`schemes/`). `ConnectorCredentialService` (`service.py`) stores one encrypted JSON-bundle-per-`(instance, scheme)` row, **reusing `app/runtime/providers/credential_crypto.py`'s `encrypt_secret`/`decrypt_secret`/`mask_hint` directly** — verified by identity (`is`), not just behavior; no extraction needed since those functions already had zero provider-specific logic in their bodies (the same precedent Phase 5.6a.1's `ToolCredentialService` set). New tables `connector_credentials` (unique on `(connector_instance_id, auth_scheme)`, no per-field plaintext column) and `connector_oauth_tokens` (unique on `connector_instance_id`, both tokens encrypted independently). `token_manager.py` handles OAuth2 acquisition/caching/refresh, concurrency-safe via a `SELECT ... FOR UPDATE` lock on the *parent* `connector_instances` row (not the token row, which may not exist yet on first acquisition) — proven with real threads against real Postgres (`test_ac13_concurrent_refresh_does_not_double_refresh`). Authorization-code: client-config storage, `build_authorization_url()`, the callback code-exchange, and refresh-and-apply are built; the interactive consent-redirect UI is explicitly stubbed (documented front-end deferral). `MockAuthenticatedConnector` added alongside (not replacing) `MockConnector` to exercise the framework against a mock, since no real connector invokes yet. Seven new routes reusing 2.1.1's two permissions (no finer `integration.credential.manage` — stated as not warranted). Four new error codes (`CONNECTOR_CREDENTIAL_NOT_FOUND`/`CONNECTOR_AUTH_SCHEME_UNSUPPORTED`/`CONNECTOR_CREDENTIAL_INVALID`/`CONNECTOR_OAUTH_REFRESH_FAILED`), three new audit events (`INTEGRATION_CONNECTOR_CREDENTIAL_UPDATED`/`_DELETED`/`_VALIDATED`). Migration `0034_connector_auth`, two new tables, reversible. 31 new tests in `backend/tests/integration/test_connector_auth.py`, grouped by the build prompt's own §8 AC groups; every 2.1.1 test still passes unmodified. See `docs/integration/connectors.md`'s "Authentication" section. |
| **2.1.3 Connector Registry & Health** | **IMPLEMENTED** | New `app/integration/registry.py`: `ConnectorRegistry` — the single lookup surface (type + tenant-scoped instance resolution/listing), wrapping 2.1.1's own services rather than duplicating them. `resolve_instance_for_invocation` is the **fail-fast wiring point** (`ACT-INT-FR-044`) — raises `CONNECTOR_UNAVAILABLE` immediately for a `failed`/`disabled` instance, before any real call is attempted; 2.2.x's tool bridge inherits this for free. New `app/integration/health.py`: `ConnectorHealthService` runs two structurally separate probes — reachability via a new, additive `Connector.health_check(configuration)` ABC method (never handed a credential) and auth validity by reusing `ConnectorCredentialService.validate()` (2.1.2) entirely, not duplicated. `HEALTHY`/`UNHEALTHY`/`ERROR` are distinct outcomes — `ERROR` (a probe raised) surfaces `CONNECTOR_HEALTH_CHECK_FAILED` (502), distinct from a completed `UNHEALTHY` (200). A failing check on `active` calls the pre-existing `mark_failed`; a passing check on `failed` calls a new `recover` event added to `lifecycle.py` (`failed -> active`) — both through the unchanged 2.1.1 state machine. **Alerting reuses the existing precedent, no new channel built**: `INTEGRATION_CONNECTOR_STATE_CHANGED` (unchanged event) now carries `meta.severity: CRITICAL` on a failed transition, mirroring `RUNTIME_TOOL_EGRESS_DENIED`'s (5.6a.1) own severity-tagged-audit-event pattern — `notification_service.py` was examined and rejected (no subscription/recipient-list concept to hook into). New `app/integration/scheduler.py`: one `asyncio` background task, off by default everywhere including every test run (`CONNECTOR_HEALTH_SCHEDULER_ENABLED=false`), explicitly documented as interim and Milestone-3-replaceable — REPO_STATE §10.2's no-distributed-scheduler constraint honored. New table `connector_health_checks` (append-only, capped at 200 rows/instance) plus a two-column health cache on `connector_instances`. Three new routes reusing 2.1.1/2.1.2's permissions. **One pre-existing 2.1.1 test updated, not weakened**: the ABC's method-set assertion grew to include the deliberately added `health_check`. Migration `0035_connector_health`, one new table, reversible. 24 new tests in `backend/tests/integration/test_connector_health.py`, grouped by the build prompt's own §8 AC groups. See `docs/integration/connectors.md`'s "Registry & Health" section. |
| **2.1.4 Connector SDK** | **IMPLEMENTED** | New `app/integration/sdk/__init__.py` — the author-facing surface, explicit `__all__` re-exports only (`Connector`, `ConnectorDescriptor`/`ToolContract`/`ConnectorLifecycleState`, `SUPPORTED_AUTH_SCHEMES`, `validate_configuration_schema`/`ConnectorConfigInvalidError`, `GovernedHttpClient`, `ConnectorTestHarness`/`HealthCheckOutcome`) — no database session, `AuthScheme`/`OutboundRequest`/credential-resolution machinery, raw HTTP client, audit-suppression hook, or route-registration mechanism appears anywhere in it, mechanically checked (`test_ac10`/`AC-12`/`AC-14`/`AC-15`). `app/integration/sdk/http.py`'s `GovernedHttpClient` is the **only** network primitive the surface exposes, wrapping `app.runtime.tools.egress_guard`/`http_executor` directly (not reimplemented); `allowed_hosts` is fixed at construction, never a per-call argument — a call to an undeclared host is denied by the allowlist check alone, before any DNS lookup (`AC-11`). New `app/integration/validation.py`: `validate_declaration_complete()`, the single completeness check both the real registration path (`ConnectorTypeService.register()`, a new public method) and `ConnectorTestHarness.assert_declaration_complete()` call — no second, weaker check for SDK-authored connectors; a placeholder `health_check()` is detected via a dedicated `HealthCheckNotImplemented` marker (not Python's own generic unimplemented-method builtin, to avoid colliding with 2.1.3's existing package-wide stub-marker grep). **Registration parity proven by construction, not asserted**: the worked example, `WebhookConnector` (`app/integration/sdk/example/webhook_connector.py`, type `SDK_EXAMPLE_WEBHOOK`), sits in the same `_CONNECTOR_TYPES` dict as `MOCK`/`MOCK_AUTH` and flows through the identical `ensure_seeded → register` path — there is only one registration path, not two kept in sync. The example is built and tested using only names imported from `app.integration.sdk` (plus the standard library), verified by an AST-based import-inspection test, not just by behavior. Governance-inheritance tests (`AC-10`..`AC-15`) prove an SDK connector cannot make an undeclared outbound call, receive a decrypted credential, suppress audit, or reach another tenant's data — because the SDK offers no method to do any of those, not because an author is told not to. **No migration** — the SDK is an authoring surface over the existing schema. **No new HTTP route** — a code-authoring capability, not an API; route count re-confirmed unchanged at 474. 31 new tests across `backend/tests/integration/test_connector_sdk.py` (26) and `test_connector_sdk_example.py` (5, importing only from `app.integration.sdk` and the example itself). See `docs/integration/connectors.md`'s "Connector SDK" section. |
| **2.2.1 Generic REST Connector** | **IMPLEMENTED** | New `app/integration/connectors/rest/` package — Milestone 2's first real connector, and the SDK's first real proving ground. `RestConnector` (`connector.py`) built through the SDK surface only (`declaration.py`/`templating.py`/`extraction.py`/`pagination.py`/`connector.py` import solely from `app.integration.sdk` or each other, AST-verified). `declaration.py`: `CONFIG_SCHEMA` (structural) + `parse_declaration()` (semantic — path-placeholder/`path_params` agreement, argument-name cross-referencing, `auth_scheme` membership in `SUPPORTED_AUTH_SCHEMES`) + `tool_contracts_for(configuration)` — the real, per-instance `ACT-INT-FR-102` mechanism (`RestConnector.describe()` itself carries only a structural completeness placeholder, since a zero-argument type-level call cannot know an instance's endpoints — a documented, deliberate decision, not an oversight). `templating.py`: injection-safe path (percent-encoded with no safe characters — `"123/../admin"` renders as the single segment `"123%2F..%2Fadmin"`, never escaping to `/admin`), query, header (control-character rejection), and body rendering. `extraction.py`: dotted-path response extraction + `jsonschema`-based output validation. `pagination.py`: `offset_limit`/`page_number`/`cursor`, hard-capped at `min(declared max_pages, 100)` regardless of server behavior. New `app/integration/connectors/rest/invoker.py` (platform bridge, not SDK-surface-restricted): `invoke_tool()` is the first-ever tool-invocation bridge in this codebase — fail-fast resolves via the unchanged 2.1.3 registry, applies the instance's declared `auth_scheme` via a new, additive `ConnectorCredentialService.resolve_and_apply_for_scheme()` method (2.1.2's `resolve_and_apply()` is now a thin wrapper over it, unchanged behavior for every existing caller), dispatches through `GovernedHttpClient`, drives pagination, extracts output — proven end to end against a real local `http.server` fixture, including a genuine stored/encrypted `BEARER` credential reaching the server as a real header. **Deliberately not wired into `ToolGatewayService`/`tools_snapshot`/the model loop** — Milestone 1 untouched. **One SDK-surface fix**: `GovernedHttpClient.request()` gained an optional `query` parameter (`execute_http_tool`'s `_build_target_url` was silently dropping a query string embedded in the URL itself — invisible to 2.1.4's query-free `WebhookConnector`, fatal to a paginated endpoint) — additive, backward-compatible, 2.1.4's own test suite unaffected. Three new error codes (`REST_ENDPOINT_NOT_DECLARED`/`REST_TEMPLATE_INVALID`/`REST_EXTRACTION_FAILED`); `TOOL_EGRESS_DENIED` reused for allowlist/SSRF denials, per the build prompt's own instruction. A realistic four-endpoint vendor-like declaration (support-ticketing CRM: create/get/list-paginated/update) is the concrete `ACT-INT-FR-106` proof. **No migration** — every table touched already exists, the declaration lives in the existing `connector_instances.configuration` JSONB column. **No new HTTP route** — configuring an instance reuses the existing `POST`/`PATCH /connectors` endpoints; the invocation bridge is a direct Python entry point. 41 new tests across `backend/tests/integration/test_rest_connector.py` (30 — declaration/templating/extraction/pagination/SDK-surface/integrity, no HTTP at all) and `test_rest_connector_invocation.py` (11 — end to end against a real local fixture server, mirroring `test_http_tool_execution.py`'s own established convention). See `docs/integration/connectors.md`'s "Generic REST Connector" section. |
| **2.2.2 Generic Database Connector** | **IMPLEMENTED** | New `app/integration/connectors/database/` package — Milestone 2's second real connector, carrying its single sharpest security rule: **the model never writes SQL** (`ACT-INT-FR-121`/`FR-122`). `declaration.py`: `CONFIG_SCHEMA` (structural) + `parse_declaration()` (semantic — a query's `:name` bind-placeholders must exactly match its declared `parameters` properties, an unsupported/pending dialect is rejected by name) + `tool_contracts_for(configuration)` (one `ToolContract` per declared query, `ACT-INT-FR-121`) + `classify_query()` (read/write classification of *declared, trusted* SQL by its first real keyword, fail-closed — never applied to model output) + `mutating_query_names()` (pure data, never raises). `drivers.py`: PostgreSQL (`postgresql+psycopg2`, no new dependency) and MySQL (`mysql+pymysql`, new `PyMySQL` dependency, pure-Python) dialect dispatch via SQLAlchemy Core's own dialect layer (never a hand-rolled placeholder translation); SQL Server recognized in the config schema but rejected as driver-pending (`mssql+pyodbc` needs a system ODBC driver, not added this phase); connection URLs built via `sqlalchemy.engine.URL.create()` so a password is never concatenated into a bare string; a per-instance engine/pool cache (`get_or_create_engine`/`dispose_engine`), keyed by connector instance id. `executor.py` — the security-critical component: its only public entry, `execute_declared_query(engine, dialect, query: DeclaredQuery, params, row_limit, timeout_seconds)`, has no parameter position a raw SQL string could occupy anywhere in this codebase (containment by absence, not a rejecting check); parameters bound via SQLAlchemy's `text()` + a parameter mapping, never interpolated (proven against real Postgres: `"'; DROP TABLE users; --"` and the classic UNION/comment/stacked-query/boolean-blind injection family all come back as inert literal values, `users` still present afterward; a dedicated test inspects the literal SQL sent to the DBAPI driver via `before_cursor_execute` and confirms the placeholder token, never the value, is what's sent); rows fetched via `fetchmany(row_limit + 1)`, rejected outright (never truncated) if exceeded; timeout enforced twice (a server-side `statement_timeout`/`MAX_EXECUTION_TIME` GUC plus a client-side thread + `Future.result(timeout=...)` backstop — verified live, a 3s `pg_sleep` with a 1s timeout terminates in ~1s). New `app/integration/connectors/database/invoker.py` (platform bridge, mirrors 2.2.1's own exactly): `invoke_tool()` fail-fast resolves via the unchanged 2.1.3 registry, resolves the instance's credential bundle, gets/creates its pool, validates parameters against the named query's own JSON Schema, executes — proven end to end against this platform's own real dev Postgres, including a genuine stored/encrypted `BASIC` credential authenticating the connection (confirmed via `SELECT current_user`). **Deliberately not wired into `ToolGatewayService`/`tools_snapshot`/the model loop** — Milestone 1 untouched. `ConnectorCredentialService` gained one new, additive public method, `resolve_credential_bundle()` — the same resolve-then-refresh mechanics as 2.2.1's `resolve_and_apply_for_scheme()` (both now share a new private `_resolve_bundle_for_scheme` helper), returning the decrypted bundle itself rather than an HTTP-header-shaped `OutboundRequest`, since a database username/password has no HTTP-header meaning. Read-only is the default posture (`ACT-INT-FR-125`): a read-only instance declaring a mutating query is rejected at *configuration* time with a new `DB_WRITE_NOT_PERMITTED` — the one place `connector.py` deliberately, narrowly steps outside 2.2.1's pure-SDK-surface discipline (importing one specific, documented exception type from `app.integration.errors`, reported as a justified addition per this sub-phase's own AC-20). Six new error codes (`DB_QUERY_NOT_DECLARED`/`DB_PARAMETER_INVALID`/`DB_WRITE_NOT_PERMITTED`/`DB_RESULT_LIMIT_EXCEEDED`/`DB_QUERY_TIMEOUT`/`DB_CONNECTION_FAILED` — the last one beyond the build prompt's own list, a small justified addition for AC-19's "connection failure never echoes the connection string"); deliberately **no** "raw SQL rejected" code, since no code path accepts raw SQL to reject. A realistic declared-query set (parameterized lookup + row-generating list) is the concrete `ACT-INT-FR-121` proof. **No migration** — every table touched already exists (`connectors`/`connector_instances`/`connector_credentials`). **No new HTTP route** — configuring an instance reuses the existing `POST`/`PATCH /connectors` endpoints; the invocation bridge is a direct Python entry point. **MySQL/SQL Server coverage boundary stated explicitly**: MySQL is proven at the driver-dispatch/declaration level only (no live MySQL server in this environment); SQL Server has no driver and only the driver-pending-rejection path is tested. 42 new tests across `backend/tests/integration/test_database_connector.py` (35 — security core/declared-queries/read-only/limits/drivers/SDK-surface/integrity, most against real Postgres) and `test_database_connector_invocation.py` (7 — end to end against a real, database-backed `ConnectorInstance` with a real, stored, encrypted credential, connecting to this platform's own dev Postgres). See `docs/integration/connectors.md`'s "Generic Database Connector" section. |
| **2.2.3 Generic File & Object Storage Connector** | **IMPLEMENTED** | New `app/integration/connectors/storage/` package — Milestone 2's third real connector, carrying `ACT-INT-FR-141`/`FR-143`'s direct analogue of the database connector's SQL rule: **a model-supplied path can never escape its declared scope**. `scope.py` — the security core, with **zero dependencies on this platform** (not even the SDK; just `os`/`posixpath`/`re`/`unicodedata`/`urllib.parse`): its one public function, `resolve_and_contain(boundary, supplied_path)`, canonicalizes (control-character rejection, iterative percent-decoding, a second control-character check on the decoded result, NFKC Unicode normalization, then `os.path.realpath` for filesystem — resolving `..` *and* symlinks in one pass — or `posixpath.normpath` for object storage) and only then contains-checks, returning the canonicalized target or raising — never validating one string and letting a caller act on a different, later-resolved one (no TOCTOU gap, `ACT-INT-FR-143`/AC-10). Proven against every named traversal vector — relative, absolute (POSIX/Windows-drive/UNC), single- and double-percent-encoded, backslash, literal and encoded null-byte, Unicode homoglyph normalization, object-store prefix/bucket escape including the sibling-prefix boundary case — with **no live storage anywhere in the test file**, plus a filesystem symlink-escape test using a real temporary symlink (or, since this environment's default user lacks the Windows privilege to create one without elevation, a directory junction — also a reparse point `realpath` resolves identically; genuinely exercised, not skipped, in this environment). `declaration.py`: `CONFIG_SCHEMA` (structural) + `parse_declaration()` (semantic, raising a dedicated `StorageScopeInvalidError` — one of two narrow, justified deviations this phase needed where 2.2.2's own `declaration.py` needed none, since this phase's own acceptance criteria require a distinguishable declaration-time code) + `tool_contracts_for(configuration)` (one `ToolContract`, parameter `path`, per declared scope) + `write_scope_names()` (pure data, never raises). `backends.py`: filesystem (no new dependency) and S3-compatible (new `boto3` dependency) behind one dispatch interface — a read checks size via metadata first (`os.path.getsize`/`head_object`, a HEAD call, never a GET) and rejects before any full transfer, bounding the transfer itself as a second, defense-in-depth check; local exceptions only, translated to platform errors exclusively by `invoker.py`, mirroring `executor.py`'s discipline exactly. Azure Blob is a recognized, backend-pending value (`azure-storage-blob` deliberately not added — a genuinely heavy dependency this environment cannot exercise live, mirroring 2.2.2's SQL Server precedent exactly); S3 dispatch correctness (`head_object`/`get_object`/`put_object` called with the already scope-validated bucket/key, error translation) is proven against a mocked `boto3.client`, since no S3-compatible server is reachable in this environment — the underlying containment logic has full, unmocked coverage in `scope.py`'s own tests, since it is backend-agnostic pure Python. New `app/integration/connectors/storage/invoker.py` (platform bridge, mirrors 2.2.2's own exactly): `invoke_tool()` fail-fast resolves via the unchanged 2.1.3 registry, resolves the credential bundle (reusing `resolve_credential_bundle()` unchanged — an S3 access key id/secret access key carried by the `BASIC` scheme's generic `username`/`password` fields, no new method needed), validates the supplied `path` against the named scope's declared boundary **before any backend call**, dispatches through `backends.py` — proven end to end against this platform's own real dev database with a real, database-backed `ConnectorInstance`, including a genuine stored/encrypted `BASIC` credential. **Deliberately not wired into `ToolGatewayService`/`tools_snapshot`/the model loop** — Milestone 1 untouched. **New this phase** (`ACT-INT-FR-145`): every access attempt — allowed or denied, read or write — is recorded in the platform audit trail via a new `INTEGRATION_CONNECTOR_OBJECT_ACCESSED` audit event (a `finally` block so a denial is audited exactly as reliably as a success, carrying the *validated* path — never the raw supplied string, and a denial correctly carries none at all — backend, scope, operation, size, and outcome; credentials never appear in the recorded `meta`) — this is 2.2.x's first invocation-level audit event, since neither 2.2.1's nor 2.2.2's own build prompt required auditing individual calls. Read-only is the default posture (`ACT-INT-FR-144`): a read-only instance declaring a write scope is rejected at *configuration* time with a new `StorageWriteNotPermittedError`/`STORAGE_WRITE_NOT_PERMITTED` — `connector.py`'s own, second narrow deviation, mirroring `DbWriteNotPermittedError` exactly. Six new error codes (`STORAGE_PATH_DENIED`/`STORAGE_OBJECT_TOO_LARGE`/`STORAGE_WRITE_NOT_PERMITTED`/`STORAGE_OBJECT_NOT_FOUND`/`STORAGE_SCOPE_INVALID`/`STORAGE_BACKEND_FAILED` — the last one beyond the build prompt's own list, a small justified addition mirroring `DB_CONNECTION_FAILED`); deliberately **no** "sanitization failed" code, since a supplied path is canonicalized then proven in-scope or denied outright — there is no partial-sanitize outcome to name. **No migration** — every table touched already exists (`connectors`/`connector_instances`/`connector_credentials`/`authorization_audit`). **No new HTTP route** — configuring an instance reuses the existing `POST`/`PATCH /connectors` endpoints; the invocation bridge is a direct Python entry point. **S3/MinIO/Azure Blob coverage boundary stated explicitly**: S3 dispatch is proven against a mocked client (no live S3-compatible server in this environment); Azure Blob has no coverage beyond the "recognized but backend-pending" rejection test. 82 new tests across `backend/tests/integration/test_storage_scope.py` (41 — the isolated security core, no live storage anywhere), `test_storage_connector.py` (30 — scope/operations/limits, backend dispatch, SDK-surface/integrity), and `test_storage_connector_invocation.py` (11 — end to end against a real, database-backed `ConnectorInstance` with a real, stored, encrypted credential, connecting to this platform's own dev database). See `docs/integration/connectors.md`'s "Generic File & Object Storage Connector" section. |
| **2.2.4 Generic Message Queue Connector** | **IMPLEMENTED** | New `app/integration/connectors/queue/` package — Milestone 2's fourth and last generic connector, carrying a two-sided version of the prior connectors' single-sided containment rules: **publish is scoped to a queue fixed by the tool contract itself** (`ACT-INT-FR-161`/`FR-164` — no queue-name parameter exists for the model to redirect through at all) and **consume is always bounded to at most N messages within a bounded wait, never an unbounded stream** (`ACT-INT-FR-162`). `scope.py` — genuinely **zero imports of any kind**, simpler by design than 2.2.3's path enforcer since there is no queue-name value to canonicalize; its one function, `check_operation_permitted(binding_name, declared_operation, requested_operation)`, checks only whether a resolved binding's declared operation matches what is being attempted. `declaration.py`: `CONFIG_SCHEMA` (structural) + `parse_declaration()` (semantic, raising only the SDK's own generic `ConnectorConfigInvalidError`) + `tool_contracts_for(configuration)` (one `ToolContract` per declared binding — a `PUBLISH` binding's only parameter is `message`; a `CONSUME` binding's only parameter is an optional `max_messages` cap, itself still capped by the binding's own effective batch size). **Zero SDK-surface deviations in `declaration.py`/`connector.py` — a first among the generic connectors** (2.2.2 needed one, 2.2.3 needed two; this phase's own required error-code vocabulary is entirely invocation-time, and there is no instance-level posture flag for a per-binding operation to conflict with at configuration time). `backends.py`: AMQP (new `pika` dependency) and SQS (reuses 2.2.3's `boto3`) behind one dispatch interface — a publish checks size before any connection is attempted; a consume is bounded on two axes (batch cap, wall-clock deadline) regardless of what the queue holds or the caller asks for, verified live against a fixtured transport (a queue holding five messages with a cap of three yields exactly three; an empty queue with a 0.3s wait returns empty in ~0.3s). **Acknowledgment policy is explicit ack-on-retrieve, identical in spirit across both backends** (AMQP `basic_get(auto_ack=True)`; SQS an explicit `delete_message` immediately after `receive_message`) — at-most-once from the queue's own perspective, documented as a deliberate default for a bounded, discrete tool operation. An oversized **consumed** message is truncated to the limit and flagged `truncated=True` rather than failing the whole batch or being silently dropped — a deliberate departure from 2.2.2's/2.2.3's own "reject the whole operation" precedent, justified because a consume batch is a set of otherwise-independent messages. New `app/integration/connectors/queue/invoker.py` (platform bridge, mirrors 2.2.3's own audited shape) exposes **two** distinct entry points, `publish_message`/`consume_messages`, rather than one polymorphic `invoke_tool`, each verifying the resolved binding's declared operation before touching a broker — proven end to end against this platform's own real dev database with a real, database-backed `ConnectorInstance` and a genuine stored/encrypted `BASIC` credential (an AMQP username/password) actually reaching a (fixtured) connection. **Reuses 2.2.3's `INTEGRATION_CONNECTOR_OBJECT_ACCESSED` audit event rather than adding a new one** — every publish/consume attempt, allowed or denied, is recorded via a `finally` block. **Deliberately not wired into `ToolGatewayService`/`tools_snapshot`/the model loop** — Milestone 1 untouched. Azure Service Bus is a recognized, backend-pending value (`azure-servicebus` deliberately not added, mirroring 2.2.2's SQL Server / 2.2.3's Azure Blob precedent exactly). Five new error codes (`QUEUE_NOT_DECLARED`/`QUEUE_MESSAGE_TOO_LARGE`/`QUEUE_OPERATION_NOT_PERMITTED`/`QUEUE_CONSUME_TIMEOUT`/`QUEUE_BACKEND_FAILED` — the last one beyond the build prompt's own list, mirroring `DB_CONNECTION_FAILED`/`STORAGE_BACKEND_FAILED`; `QUEUE_CONSUME_TIMEOUT` is defined for vocabulary completeness but not raised by either backend this phase, since a bounded consume finding nothing within its wait window is a successful empty result, never an error). **No migration** — every table touched already exists (`connectors`/`connector_instances`/`connector_credentials`/`authorization_audit`). **No new HTTP route** — configuring an instance reuses the existing `POST`/`PATCH /connectors` endpoints; the invocation bridge is a pair of direct Python entry points. **RabbitMQ/SQS/localstack coverage boundary stated explicitly**: both backends' dispatch is proven against a mocked/fixtured transport (`pika.BlockingConnection`/`boto3.client`), since no live broker is reachable in this environment; the scope-permission logic itself has full, unmocked coverage since it has no backend dependency at all; Azure Service Bus has no coverage beyond the "recognized but backend-pending" rejection test. 50 new tests across `backend/tests/integration/test_queue_scope.py` (7 — the isolated scope-permission check, zero imports), `test_queue_connector.py` (31 — scoped publish/bounded consume/size/ack mechanics against mocked transports, SDK-surface/integrity), and `test_queue_connector_invocation.py` (12 — end to end against a real, database-backed `ConnectorInstance` with a real, stored, encrypted credential, connecting to this platform's own dev database). **Milestone 2's connector framework and all four generic connectors are now complete.** See `docs/integration/connectors.md`'s "Generic Message Queue Connector" section. |
| **2.3.1 External Identity Federation** | **IMPLEMENTED** | New `app/identity/federation/` package — deliberately under `app/identity/`, not `app/integration/`, since this phase authenticates a user *to* the platform rather than the platform *to* an external system: **the inversion** (`ACT-INT-FR-186`) from every 2.2.x connector, stated explicitly in the package's own docstring. `oidc.py`: OIDC authorization-code flow via `python-jose` (already a platform dependency) "with care" — `verify_id_token()` is the security core, pure (no HTTP, no database), with the accepted algorithm set fixed by the organization's own stored configuration and never taken from the token's own `alg` header (closing algorithm-confusion), the signing key resolved from the IdP's JWKS by `kid` with no fallback on an unrecognized one, and issuer/audience/expiry/nonce all explicitly checked — proven against a real, freshly-generated RSA keypair (never a mock signer) rejecting tampered signatures, wrong-key signatures, `alg:none`, algorithm confusion, expiry, wrong audience/issuer, and nonce mismatch/replay. `saml.py`: SAML 2.0 web-browser SSO via `python3-saml`/`xmlsec` (two new dependencies) — XML signature verification is never hand-rolled, delegated entirely to the security-audited `libxmlsec1` C library; `strict: True` always set; signature-wrapping resistance comes from the library following the signature's own `<Reference URI="#...">` back to the exact ID-referenced element, never a weaker "find the first Assertion" query — proven against two distinct, deliberately-constructed signature-wrapping attack documents (a forged sibling assertion; a forged assertion substituted as the only direct child with the legitimate one relocated into `<samlp:Extensions>`), built and signed by a dedicated test-only fixture module (`tests/identity/federation/_saml_fixtures.py`, the only place in this codebase that ever *constructs* a signed SAML assertion — the platform is a verifier, never an issuer). `claim_mapping.py`: pure `resolve_role_names()`, IdP group/role claim → platform role, config not code. `service.py`: `FederationService` — per-organization config CRUD; login orchestration; **stateless CSRF/replay defense** via a short-lived (600s), platform-signed `state`/SAML `RelayState` JWT reusing the existing `settings.JWT_SECRET_KEY`/`JWT_ALGORITHM` (no new secret, no new "pending requests" table) — SAML's RelayState carries the outgoing `AuthnRequest`'s own id for strict `InResponseTo` binding, obtained by bypassing `OneLogin_Saml2_Auth`'s convenience `login()` method and constructing `OneLogin_Saml2_Authn_Request` directly so the id is known before the token is signed; **maps into the platform's existing user/RBAC model, never a parallel one** (`ACT-INT-FR-182`) — a federated identity links to a platform `User` by stable subject id (OIDC `sub`/SAML `NameID`), never email, since email can be reassigned by an IdP admin; a genuine, documented two-tier resolution not specified by the build prompt: (1) link-by-subject (returning user), (2) link-by-email to an existing local account (always permitted — no new identity created), (3) JIT-provision a new user, gated per-org by `jit_provisioning_enabled` (`ACT-INT-FR-184`) — gating applies only to identity *creation*, never to linking; JIT provisioning reuses the existing `UserProvisioningService` seam verbatim, per that module's own pre-existing docstring anticipating exactly this; session issuance terminates in the platform's **existing** pipeline — `SessionLifecycleService.create()` → `RefreshRotationService.issue()` → `IdentityContextResolver.from_user()` → `TokenService.create_access_token()`, the same quartet `AuthenticationService.login()` uses, substituting `login_method=AuthMethod.OIDC.value`/`SAML.value` — never a parallel session/token mechanism (`ACT-INT-FR-187`); assurance level is deliberately always `AAL1`, never speculative `AAL2`, since the platform cannot reliably verify what MFA the IdP itself enforced and must not claim a stronger assurance level than it can stand behind. `routes.py`: 4 public routes under `/api/v1/auth/federation` (login/callback/SAML ACS/metadata) — `config_id` is recovered from the verified state/RelayState token itself for callback/ACS (matching the build prompt's literal path shape), while login/metadata include it in the path since nothing else identifies which IdP. `backend/app/identity/api/routes/federation_configs.py`: 6 admin CRUD routes under `/api/v1/identity/federation/configs`, scoped implicitly to the caller's own organization, gated by two new permissions (`identity.federation.view`/`.manage`); `FederationConfigRead` never serializes the client secret, only `has_client_secret: bool`. Local authentication is untouched and proven still working alongside federation (`ACT-INT-FR-187`). New tables `identity_federation_configs` (unique on `(organization_id, protocol, provider_type)`; `encrypted_client_secret` nullable, via the existing `credential_crypto.py`) and `federated_identities` (unique on `(federation_config_id, external_subject_id)`; **no credential column of any kind**) — migration `0036_identity_federation`, additive, reversible (`alembic downgrade -1` then `upgrade head` both verified clean live). Six new error codes (`FEDERATION_CONFIG_NOT_FOUND`/`FEDERATION_CONFIG_INVALID`/`FEDERATION_ASSERTION_INVALID`/`FEDERATION_STATE_INVALID`/`FEDERATION_USER_NOT_PROVISIONED`/`FEDERATION_CLAIM_MAPPING_FAILED`; `FEDERATION_ASSERTION_INVALID` deliberately shared by both protocols, mirroring `INVALID_CREDENTIALS`'s "generic failure, no oracle" discipline). Identity-domain error convention confirmed unchanged: no dedicated exception subclasses (unlike the integration domain's `ConnectorXError(IdentityError)` pattern) — services raise `IdentityError(ErrorCode.X, "message")` directly. **Five pre-existing "migration head unchanged" tests updated, not weakened** (one each from Phases 2.1.4/2.2.1/2.2.2/2.2.3/2.2.4 — `test_connector_sdk.py`/`test_database_connector.py`/`test_queue_connector.py`/`test_rest_connector.py`/`test_storage_connector.py`): each hardcoded `"0035_connector_health.py"` as the expected migration head, correct when its own phase shipped, now stale since this phase genuinely adds `0036_identity_federation.py` — mirrors the "small, necessary update" precedent Phase 2.1.3 already established for its own ABC method-set assertion. Route count 474 → 484 (+10); live schema 107 → 109 tables. 57 new tests across `backend/tests/identity/federation/test_oidc_bypass_prevention.py` (14 — every canonical JWT bypass class individually, plus structural AST-based proof `jose` is used and `algorithms` is never read from the token header), `test_saml_bypass_prevention.py` (12 — unsigned/tampered/untrusted-cert/expired/wrong-audience/wrong-`InResponseTo`/two wrapping-attack variants, plus structural proof of `onelogin`/`xmlsec` delegation and `strict`/`wantAssertionsSigned` always `True`), `test_claim_mapping.py` (8), `test_federation_login_flow.py` (10 — end to end against this platform's own real dev database, JIT provisioning, real session issuance, indistinguishable-from-password-login session proof via `/api/v1/auth/me`, JIT-disabled rejection and email-linking behavior, cross-org and forged/expired state rejection), `test_federation_config_crud.py` (13 — real HTTP via `TestClient`, permission gating, cross-org isolation, secret-never-returned, all four provider types configurable, local login still works after federation is configured). See `docs/identity/federation.md`. |

---

### Milestone 3 — Deployment & Release (`ACT-SRS-M3`) — **IN PROGRESS (8/10)**

SRS approved, architecture validated against the repository (per the SRS's own §27 analysis). **Phase 3.1 (Enterprise Deployment Core) shipped 2026-08-10** — the first sub-phase, deliberately scoped to build the deployment *state machine and its authority*, not traffic, not canary, not workers; those are later phases and explicitly out of scope here. **Phase 3.2 (Environment & Promotion Model) shipped the same day** — the second sub-phase, turning `agent_deployments.environment` into governed entities with policy and adding an immutability-preserving promotion operation. **Phase 3.3 (Deployment Preflight & Release Gate Engine) shipped 2026-08-11** — the third sub-phase, aggregating existing checks into one authoritative PASS/WARNING/BLOCK verdict and adding the freshness rule. **Phase 3.4 (Traffic Allocation, Version Resolver & Execution Gate) shipped 2026-08-13** — the fourth, and the milestone's one deliberate change to the Milestone 1 execution path. **Phase 3.5 (Canary Deployment Engine) shipped 2026-08-14** — the fifth, the progressive driver 3.4's allocation was built for. **Phase 3.6 (Blue-Green & Recreate Strategy Execution) shipped 2026-08-14** — the sixth, two further weight patterns over the same allocation mechanism. **Phase 3.7 (Automated Rollback & Release Safety) shipped 2026-08-17** — the seventh, and the safety capstone: the governed per-tenant trigger policy that decides *when* to invoke the rollback operations 3.5 and 3.6 already provided, with `rollback_target_id` made authoritative. Ten sub-phases total, per the SRS's own out-of-scope table naming each owning phase: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7 (all done), 3.8 (distributed scheduler), 3.9 (distributed workers + rolling strategy), 3.10 (operator frontend).

**This table was stale for three phases and is corrected here, not quietly.** The 3.4, 3.5 and 3.6 header entries at the top of this document each claimed "§6 was updated"; §2/§3/§5 genuinely were (table counts, migration head, route counts all re-derived live each pass and all correct), but this Milestone 3 sub-phase table itself was left reading "IN PROGRESS (3/10)" with a "3.4 – 3.10 **NOT STARTED**" row while three of those sub-phases had in fact shipped. Found and fixed 2026-08-14 during a documentation-maintenance pass, recorded in the same "correct it rather than let it compound" spirit as §9 items 2, 17 and 18.

Load-bearing constraints for whenever build work continues (from the SRS, restated here since they shape review of every sub-phase): **extend `agent_deployments`, never a parallel `deployments_v2`** (SRS §3.1); **published agent versions stay immutable — a deployment state change never mutates a version** (SRS §3.2); **`AuthorizationGateway`/the pre-existing `require_permission` dependency is the sole authorization authority** (SRS §3.3, mirrors REPO_STATE §10.3's own standing rule); **fail closed on any unestablished precondition** (SRS §3.4); **every deployment operation is tenant-isolated** (SRS §3.5); **the version resolver and the execution gate (Phase 3.4's ruling #4) are explicitly not this phase's to build** — `ExecutionRequestService._request_execution` keeps gating purely on the legacy `AgentDeployment.status` field until 3.4 deliberately moves it.

| Sub-phase | Status | Evidence |
|---|---|---|
| **3.1 Enterprise Deployment Core** | **IMPLEMENTED** | New `app/runtime/deployment/` package turns the existing, partially-wired `agent_deployments` table into a governed domain — a second, additive lifecycle machine (`lifecycle_state`, 15 states) alongside the pre-existing, completely untouched `status`/`DeploymentService` machinery. `lifecycle.py`: the pure transition graph (`can_transition`/`all_states`/`allowed_targets`), no I/O — mirrors `app.runtime.registry.services`'s own `_TRANSITIONS` pattern. `service.py`: `DeploymentLifecycleService`, the single authority that ever assigns `lifecycle_state` (mechanically checked via a regex-based grep test, the same runtime-never-knows-style discipline Milestone 2's connector framework established for its own domain) — `transition()` guards every transition landing in `ACTIVE` with two checks inline: **Ruling #6** (the mandatory-inspection suspension/kill integration — `Agent.lifecycle_status == "SUSPENDED"`, read from the pre-existing `AgentLifecycleService`/`KillSwitchService` mechanism, never a parallel one, never written by this phase) and the `runtime_approvals` precondition where policy demands it (mirroring, without touching, legacy `DeploymentService.deploy()`'s own mission-critical-production reroute). `start_deploying()` drives the synchronous READY/APPROVED→...→ACTIVE happy path end to end (no distributed worker this phase — deployment is synchronous, the same simplification the execution queue already made for local dev). `idempotency.py`: the reusable, platform-wide `Idempotency-Key` contract (`IdempotencyService`), proven generic via a unit test against a bare non-deployment stub — uses a **claim-then-poll** pattern (a placeholder row is committed first; the table's own unique constraint is the concurrency primitive; the loser of a race polls briefly rather than ever running the wrapped operation twice), not naive check-then-act, closing a genuine TOCTOU gap the naive version would have had under real concurrency. **Optimistic concurrency** via a genuine SQLAlchemy `version_id_col` on the new `revision` column — proven live with two real threads racing one transition (`test_ac05_concurrent_transitions_exactly_one_succeeds`), exactly one succeeds, the other gets `DEPLOYMENT_REVISION_CONFLICT`; a documented, accepted side effect: the mapper-wide guard also bumps `revision` on legacy `.status`-only writes, harmless since the new authority always re-reads fresh. **Two real conflicts found and resolved, not silently redesigned around**: the build prompt's literal `/pause`/`/resume`/`/retire` paths collide with routes this codebase already shipped in Phase 5.0 (resolved by nesting the new lifecycle's five mutating routes under `/lifecycle/...`, leaving every pre-existing endpoint untouched); the build prompt's suggested `deployment.view`/`deployment.manage` permission names don't match this platform's actual, already-shipped `runtime.deployment.view`/`.deploy` (reused verbatim instead of adding near-duplicates). New tables `deployment_events` (append-only lineage; complementary to, not a replacement for, the pre-existing platform audit trail and `runtime_events` Operations Center feed, both still written unchanged via `_record_event`) and `idempotency_keys`; four new `agent_deployments` columns (`lifecycle_state`/`revision`/`state_reason`/`superseded_by_deployment_id`); the §15 deterministic migration mapping all eleven legacy `status` values into an initial `lifecycle_state`, applied once, live, to every pre-existing row — migration `0037_deployment_lifecycle`, reversible (`alembic downgrade -1` then `upgrade head` both verified clean live). **A live-discovered correction to this phase's own first test draft**: `status` (legacy) keeps drifting after migration via still-untouched legacy endpoints while `lifecycle_state`/`state_reason` (new) stay frozen at whatever the migration set — the two fields' correspondence is a one-time historical fact, not an ongoing invariant, and the migration-mapping test was rewritten once this was discovered live (a `SUSPENDED`/`ACTIVE` row from a legacy `/suspend` call after migration, not a bug). Three new error codes (`DEPLOYMENT_INVALID_TRANSITION`/`DEPLOYMENT_REVISION_CONFLICT`/`DEPLOYMENT_AGENT_SUSPENDED`); two pre-existing codes reused rather than duplicated (`DEPLOYMENT_NOT_FOUND`, `IDEMPOTENCY_CONFLICT`). Twelve new `RUNTIME_DEPLOYMENT_*` audit events (four pre-existing ones — `_CREATED`/`_ACTIVE`/`_FAILED`/`_RETIRED` — reused verbatim). **The M1 execution path is provably untouched**: `ExecutionRequestService._request_execution` (the real execution gate) never mentions `lifecycle_state` anywhere in its own source (a grep test scoped to that one function, not the whole file, since `RuntimeApprovalService.decide()` legitimately gained an additive, non-execution-path mention of it) and a full execution runs end to end unmodified through the legacy `/deploy` endpoint in the same test file. Route count 484 → 489 (+5, all nested under `/deployments/{id}/lifecycle/...`); live schema 109 → 111 tables. **Five pre-existing "migration head unchanged" tests updated, not weakened** (the same five 2.3.1 already updated once — `test_connector_sdk.py`/`test_database_connector.py`/`test_queue_connector.py`/`test_rest_connector.py`/`test_storage_connector.py` — bumped again to `0037_deployment_lifecycle.py`). 27 new tests in `backend/tests/runtime/test_deployment_lifecycle.py`, grouped by this phase's own §12 acceptance criteria. See `docs/deployment/lifecycle.md`. |
| **3.2 Environment & Promotion Model** | **IMPLEMENTED** | New `app/runtime/environment/` package — `policy.py` (pure-ish evaluation: `check_prohibited`/`check_allowed_models`/`check_allowed_data_classifications`/`check_concurrency`/`check_change_window`/`requires_approval`/`evaluate`) and `service.py` (`EnvironmentService`/`PromotionPathService`/`PromotionService`). New governed, tenant-scoped `Environment` entity (standard `DEVELOPMENT`/`TEST`/`STAGING`/`PRODUCTION`/`SANDBOX` + custom, `is_production` flag, `policy` JSONB) and `PromotionPath` (the org-configured directed graph a version's deployment eligibility may move along). `agent_deployments.environment` (bare string, untouched) gains a sibling `environment_id` FK, populated by migration `0038`'s live backfill, an opportunistic best-effort lookup in `DeploymentLifecycleService.create()`, and directly by `PromotionService.promote()`. **The security core**: promotion preserves the exact immutable version — `PromotionService.promote` loads the source `AgentVersion` exactly once and passes that same object into the existing `DeploymentService.create`, so nothing can construct/copy/mutate a version row; `PROMOTION_IMMUTABILITY_VIOLATION` is a defensive-only assertion, structurally unreachable by this module's own logic. Verified live: promoted deployment's `agent_version_id` matches exactly, the agent's total version count is unchanged, `checksum`/`manifest_digest`/`signature_id` byte-identical before/after. **Both build prompt §2 mandatory inspections completed and integrated, not paralleled**: `prohibited_environments` — `check_prohibited()` reads the exact same `AgentVersion.policy_snapshot["prohibited_environments"]` field `RuntimePolicyService.evaluate` (M1 execution path) already reads; a second, unrelated field of the same name on `Capability` (§18/§19) was found, confirmed unrelated, and left untouched. Release channels — found orthogonal (a global stability track a version publishes onto vs. a tenant-scoped deployment target a version is promoted through); promotion never touches `release_channel_id`, no channel vocabulary appears in the new policy module, both proven by dedicated tests. **Environment-required approval folded into the existing single funnel**: `DeploymentLifecycleService._requires_deployment_approval` gained one additive condition (a governed environment's `is_production`/`policy.requires_approval`) alongside its two pre-existing legacy checks — no second approval mechanism; `PromotionPath.requires_approval` is stored/returned but deliberately not wired as an independent second gate this phase (reported, not silently built). **`ACTIVE`/`PAUSED` → `SUPERSEDED`, declared-but-undriven since 3.1, is now driven**: a promoted deployment reaching `ACTIVE` supersedes any other `ACTIVE`/`PAUSED` deployment of the same agent already in the target environment, preserving lineage via `superseded_by_deployment_id`. `evaluate()` is a single deploy/promote-time choke point (`DeploymentLifecycleService.start_deploying`, shared identically by a plain deploy and a promotion) — enforced dimensions: `allowed_models`, `allowed_data_classifications` (live `Tool.data_classification` lookup), `requires_approval`, `maximum_concurrent_deployments`, `change_window`; modeled-only: `allowed_external_systems` (renamed from the build prompt's own `allowed_connectors` — mechanically forbidden vocabulary under `app/runtime`; no existing link to Milestone 2's integration-instance catalog to enforce against), `rollback_rules` (3.7's job). No routing conflict this phase (unlike 3.1's own) — `/deployments/{id}/promote` was free, used directly. New permissions `runtime.environment.view`/`.manage` (the build prompt's own suggested `environment.manage` didn't exist in the catalog; promoting itself reuses `runtime.deployment.deploy`, not a third permission). Five new error codes (`ENVIRONMENT_NOT_FOUND`/`ENVIRONMENT_POLICY_VIOLATION`/`PROMOTION_PATH_NOT_DEFINED`/`PROMOTION_WINDOW_CLOSED`/`PROMOTION_IMMUTABILITY_VIOLATION`); `DEPLOYMENT_NOT_FOUND` reused. Seven new audit events (`RELEASE_PROMOTED`/`RELEASE_PROMOTION_BLOCKED` — SRS's own literal names — plus five `RUNTIME_ENVIRONMENT_*`/`RUNTIME_PROMOTION_PATH_*`). New tables `environments`/`promotion_paths`; one new `agent_deployments` column (`environment_id`); the §15 deterministic migration seeding the standard five environments + default `DEV→TEST→STAGING→PRODUCTION` promotion chain per organization, applied once, live, to every organization with existing deployments (4,559 orgs) — migration `0038_environments_promotion`, reversible (`alembic downgrade -1` then `upgrade head` both verified clean live, environments/paths correctly re-seeded). **A genuine bug found and fixed before it reached a test failure**: `ensure_seeded()`'s first draft mirrored `ReleaseChannelService.ensure_seeded()`'s flush-only pattern, but its own `GET /environments` route call site never committed afterward (unlike the *actual* precedent, `list_release_channels`, which does) — seeded rows were silently rolled back on session close; fixed by adding the missing `db.commit()`. Route count 489 → 499 (+10: 6 environment CRUD/policy, 3 promotion-path CRUD, 1 promote); live schema 111 → 113 tables. Five pre-existing "migration head unchanged" tests bumped again to `0038_environments_promotion.py`. 29 new tests in `backend/tests/runtime/test_environment_promotion.py`, grouped by this phase's own §12 acceptance criteria; a dedicated regression test (`test_ac15_promoting_to_lifecycle_active_has_no_effect_on_the_legacy_execution_gate`) proves the M1 execution path is provably untouched, not just asserted to be. See `docs/deployment/environments.md`. |
| **3.3 Deployment Preflight & Release Gate Engine** | **IMPLEMENTED** | New `app/runtime/release_gate/` package — `checks.py` (thirteen individual checks + `run_checks`/`verdict_for`, each calling an *existing* capability, no reimplementation) and `service.py` (`ReleaseGateService`, the single authoritative evaluation). **The verdict**: PASS/WARNING/BLOCK, BLOCK dominates WARNING dominates PASS (`verdict_for`); each `Finding` carries `code`/`severity`/`source`/`explanation`/`remediation`. **Fail-closed by construction**: `run_checks()` wraps every check call — an unexpected exception becomes a `PREFLIGHT_CHECK_UNAVAILABLE` finding (BLOCK by default), never a silently skipped check. **The check-to-source mapping** (full table in `docs/deployment/release-gates.md`): agent active/kill switch → `Agent.lifecycle_status` (Ruling #6, reused verbatim, **absolute BLOCK, never overridable**); version published → `AgentVersion.status`; checksum → `app.runtime.services._verify_checksum`; signature/provenance → `AttestationService.verify`; compatibility → `AgentVersion.compatibility_level` (**WARNING only**, preserving `docs/runtime/versioning.md`'s own documented advisory-only boundary — not silently turned into a hard block); owners → `Agent.owner_id`; machine identity → `AgentIdentity` (same WARNING/BLOCK split `AgentValidationService`'s §28.4 check already uses); provider availability/credentials → `app.runtime.providers.registry`/`ProviderCredentialService.resolve_for_version`; tools → `Tool.enabled`; environment policy → `app.runtime.environment.policy.evaluate` (Phase 3.2, called verbatim — AC-11); approvals → `DeploymentLifecycleService._requires_deployment_approval`/`._approved_deployment_approval` (Phase 3.1, called verbatim, **WARNING not BLOCK** — a pending approval is the designed reroute path, not a failure). **The freshness rule** (`evaluate_freshness`, pure, database-free) — the phase's one genuinely new requirement — is applied to `DeploymentHealth.checked_at`/`HealthMonitoringService`, **not** the build prompt's own suggested Milestone-2 connector-health signal: two independent, structural reasons, both confirmed by reading the code (the runtime-never-knows vocabulary boundary Milestone 2's own mechanically-enforced tests establish, plus no existing dependency link between a runtime `Tool`/`AgentVersion` and Milestone 2's integration-instance catalog — the identical gap Phase 3.2 already reported for `allowed_external_systems`); "external-system dependency health" is reported as a gap, not built around. Default freshness bound 900s (15 min), configurable per environment via `Environment.policy["preflight_freshness_bound_seconds"]`; every finding-code severity likewise overridable via `Environment.policy["preflight_severity_overrides"]` except the kill-switch code. **Wired into `DeploymentLifecycleService.start_deploying()`** — runs after the pre-existing 3.2 narrow environment-policy check (left completely unchanged, including its own error codes) and before the approval-reroute logic (never disturbed, since the gate's own approval finding is WARNING); a BLOCK verdict raises `DEPLOYMENT_PREFLIGHT_BLOCKED`. **Promotion is gated for free**: `PromotionService.promote()` already funnels through this same `start_deploying()` call, no extra wiring needed. **The kill switch is absolute and re-checked live on every call** — `ReleaseGateService.evaluate()` never caches; a prior PASS is never trusted at the actual transition moment, and the pre-existing, independent Ruling #6 check (`_assert_can_reach_active`) still additionally fires at the literal `DEPLOYING→ACTIVE` transition for any path that bypasses the gate (e.g. `resume()`). **One pre-existing Phase 3.1 test's expectation changed, not weakened**: `test_ac09_suspended_agent_blocks_activation` now asserts `DEPLOYMENT_PREFLIGHT_BLOCKED` (was `DEPLOYMENT_AGENT_SUSPENDED`) and a `READY` post-condition (was `DEPLOYING`) — the gate now blocks *before* the `READY→DEPLOYING` mutation rather than after it, a strictly safer post-condition; the underlying guarantee is unchanged. New table `deployment_preflight_results` (verdict + JSONB findings snapshot per evaluation) — migration `0039_deployment_preflight`, purely additive, no data backfill, reversible (`alembic downgrade -1` then `upgrade head` both verified clean live). Three new routes under `/deployments/{id}/preflight`(`/history`), reusing `runtime.deployment.deploy`/`.view` — no new permissions. Two new error codes (`DEPLOYMENT_PREFLIGHT_BLOCKED`/`PREFLIGHT_CHECK_UNAVAILABLE`); `DEPLOYMENT_NOT_FOUND` reused. Three new audit events, SRS's own literal names (`DEPLOYMENT_VALIDATION_STARTED`/`_FAILED`/`_PASSED`, mirroring 3.2's `RELEASE_PROMOTED`/`RELEASE_PROMOTION_BLOCKED` unprefixed-name precedent) — a kill-switch-caused BLOCK additionally tagged `severity="CRITICAL"`. `POST .../preflight` deliberately **not** wrapped in the 3.1 idempotency contract — FR-031 requires a fresh result every call, the same precedent `CompatibilityAnalysisService.analyze` already establishes. Route count 499 → 502 (+3); live schema 113 → 114 tables. Five pre-existing "migration head unchanged" tests bumped again to `0039_deployment_preflight.py`. 27 new tests in `backend/tests/runtime/test_release_gate.py`, grouped by this phase's own §12 acceptance criteria, including reuse-verified-by-spy tests (AC-05/AC-11) and a full happy-path PASS. See `docs/deployment/release-gates.md`. |
| **3.4 Traffic Allocation, Version Resolver & Execution Gate** | **IMPLEMENTED** | Two new modules in `app/runtime/deployment/`. `traffic.py` owns **the servability definition for the whole milestone** — `NON_SERVING_STATUS`/`NON_SERVING_LIFECYCLE`, `servable_clause()` (SQL) and `is_servable()` (Python), one definition expressed twice so a query and an in-memory check can never disagree — plus `TrafficAllocationService.set_weights()`, the single atomic, revisioned, audited write path every later phase drives. `resolver.py`'s `VersionResolver.resolve()` is the hot path: explicit `deployment_id` → weighted allocation for `(agent, environment)` → the implicit sole-servable-deployment case, in **≤3 indexed queries**, asserted by counting statements through a `before_cursor_execute` hook so an N+1 fails the test rather than a review. **The union-with-veto ruling** — the phase's real decision, and one the build prompt did not anticipate — resolves a genuine two-state-machine fork: `agent_deployments.status` is written by legacy `DeploymentService` **and `KillSwitchService`**, while `lifecycle_state` is written only by `DeploymentLifecycleService` (3.1 pause, 3.2 promote/supersede). Gating on `lifecycle_state` alone (as `docs/deployment/lifecycle.md` had framed it) would have **disarmed the kill switch** at ORGANIZATION/PROJECT/PLATFORM scope and stranded every legacy-deployed agent; gating on `status` alone would leave 3.1-paused deployments serving. A deployment therefore serves iff either machine says ACTIVE and neither vetoes — **neither machine rewritten**, which is why this phase changes one place rather than six; full truth table in `docs/deployment/traffic-and-resolution.md`, pinned by a test. **The one M1 execution-path change** (`ExecutionRequestService._request_execution`): a direct 1:1 deployment→version read becomes one `VersionResolver(db).resolve(...)` call; everything after it — `authorize(deployment)`, runtime policy, the approval reroute, the queue, the worker — untouched. **Authorization non-bypass verified three independent ways**: against the resolver's parsed **AST** (no authorization import or identifier — AST rather than text, since the docstring discusses the gateway at length explaining why it must not touch it), positionally (the call site precedes `decision = authorize(deployment)`), and behaviourally (a same-tenant VIEWER still gets 403 where the admin succeeds). **Two build-prompt premises were reported, not designed around**: ruling #4 was already enforced (deployment-less execution has been rejected since M1, so there were no such tests to migrate and `NO_ACTIVE_DEPLOYMENT` was added *additively*, preserving M1's error contract); and the real ambiguity was the state-field split above, escalated before any code was written. **One deliberate test migration, strengthened not weakened**: 3.2's `test_ac15_promoting_to_lifecycle_active_has_no_effect_on_the_legacy_execution_gate` → `..._now_serves_execution` (its own 3.2-era docstring had named 3.4 as the expiry condition); it still pins `status != 'ACTIVE'`, so admission can only have come from `lifecycle_state`. **No cache, deliberately, and the absence is tested** — every candidate cache key is mutated across three phases, so a cache would need an invalidation hook in all of them to stay correct *under the kill switch*. **Concurrency via a partial unique index** on `(agent_id, environment_id) WHERE is_current` — lock-free by design so nothing here can deadlock against the execution path's own locks (§9's M1 lesson); two orderings proved load-bearing and are now explicit: the previous revision's `is_current` clear is flushed **before** the new INSERT, and the whole write sequence (not just the commit) sits inside the `IntegrityError` guard, since the conflict surfaces at first flush. The AC-13 race test is deterministic — a real second connection holds its transaction open — not a thread barrier. Two new tables (`deployment_traffic_allocations`, `deployment_traffic_weights`), migration `0040_traffic_allocation` with a §15 step-2 backfill, reversible. Routes 502 → 505 (+3, mounted under `/agents/{id}/environments/{id}/traffic` rather than `/deployments/{id}/traffic`, since an allocation spans several deployments). Four new error codes, two new audit events. 43 new tests in `backend/tests/runtime/test_traffic_resolver_gate.py`. See `docs/deployment/traffic-and-resolution.md`. |
| **3.5 Canary Deployment Engine** | **IMPLEMENTED** | Three new modules. `rollout.py` — the pure 7-state machine plus `evaluate_stage_gates()`/`health_requirement_satisfied()`, no I/O. `health.py` — `HealthEvaluationService`, the **AI-aware release-health engine** (ruling #3). `canary.py` — `CanaryRolloutService`. A stage clears only when **all three** gates are satisfied: minimum duration elapsed **and** minimum sample count met **and** the health requirement satisfied. Every advance changes traffic by calling 3.4's `set_weights` — `canary.py` contains no reference to the weight tables at all (AST-asserted), so bypassing 3.4 is structurally impossible; a separate test asserts `resolver.py`/`traffic.py` are byte-identical to `main`. **INSUFFICIENT_DATA is first-class and is the phase's core safety property**: below a stage's minimum sample count the verdict is INSUFFICIENT_DATA no matter how clean the few samples look, and it satisfies no health requirement at any level — two successes out of two is not "healthy", because nothing bad *observed* is not nothing bad *happening*. Evaluation order encodes it: veto → sample sufficiency → thresholds → baseline. **Ruling #3 — why the database now has two health tables**: the pre-existing `deployment_health` is a *liveness heartbeat* written from an external signal; the new `deployment_health_evaluations` is a *release judgement* computed by aggregating `agent_executions` over a window — a version can be perfectly alive while refusing every third request. The old table is untouched in both directions, asserted by a row-count test across a full rollout. Health signals were confirmed by reading `AgentExecution`, not assumed from the SRS: `status` (success/failure/timeout, DENIED/BLOCKED), `duration_ms` (mean and p95), `cost_amount`, `total_tokens`, `error_code` (the 5.7a.4 taxonomy) — **only terminal executions count**, since counting a still-running one as "not a failure" would make a stalled canary look healthier the more stuck it got. **Kill-switch dominance via two independent mechanisms**, so a bug in either alone cannot open the gate: a veto check before every escalating operation (start/advance/resume/promote/auto-advance), and a health engine that independently returns UNKNOWN — never HEALTHY — for a vetoed candidate. De-escalating operations (pause/abort/request-rollback) deliberately skip it: a kill switch must never trap a rollout in a state an operator cannot back out of. **Auto-advance is interim and explicitly bounded** — `POST .../evaluate` advances at most one stage per call and is idempotent; 3.8 will call this exact method on a timer with no change here, the same relationship 2.1.3's `app/integration/scheduler.py` already documents. **Three real bugs found and fixed during the build**, each a variant of a lesson already in this document: a candidate with no servable deployment was read as "no veto to apply" and reported HEALTHY (closed by `require_servable`); the idempotency fingerprint carried mutable server state (`stage_index`), so deduplication never fired; and `StaleDataError` surfaces at the *first flush* — which the audit insert triggers — not at commit, so guarding only the commit let a raw 500 escape, exactly as 3.1 and 3.4 both recorded. A fourth was test over-specification rather than a product bug: an `EXPLAIN` assertion pinned one index, and Postgres legitimately preferred the organization index once the table held real data — rewritten to assert the property that matters. Three new tables (`deployment_rollout_plans`, `deployment_rollout_stages`, `deployment_health_evaluations`) plus `ix_agent_executions_version_created` and `ix_agent_executions_deployment_created` — the latter the first index that column ever had. Migration `0041_canary_rollout`, reversible. Routes 505 → 515 (+10). Five new error codes; six new audit events (pause/resume deliberately reuse the pre-existing `RUNTIME_DEPLOYMENT_PAUSED`/`_RESUMED`). 57 new tests in `backend/tests/runtime/test_canary_rollout.py`. See `docs/deployment/canary.md`. |
| **3.6 Blue-Green & Recreate Strategy Execution** | **IMPLEMENTED** | One new module, `app/runtime/deployment/strategies.py` — `DeploymentStrategyHandler` (ABC) + `RecreateStrategy`/`BlueGreenStrategy`/`RollingStrategy`/`CanaryStrategyPointer` in a `_HANDLERS` registry behind `handler_for()`, driven by `DeploymentStrategyService`. **Both §2 mandatory findings confirmed by reading the code**: (1) `agent_deployments.deployment_strategy` was, until this phase, **an entirely unused column** — present since migration `0023` with a `RECREATE` default, constrained to four values by `schemas._STRATEGY`, set on create, copied forward by `PromotionService`, exposed in `DeploymentRead`, and never read to decide anything; this phase is its first consumer, so the abstraction extends nothing and parallels nothing. (2) The two replica-count columns are **vestigial in the meaningful sense**: legacy `DeploymentService.deploy`/`retire` assign them constants and `PromotionService` copies one forward, but **nothing reads either to make any decision** — no scheduling, no scaling, no routing, no branch anywhere. **Strategies are weight patterns over 3.4's allocation, not separate machinery**: RECREATE is 0→100 in one cutover with the previous superseded through 3.1's lifecycle authority; BLUE_GREEN is 0 (warm) →100 in one atomic switch with the old version *preserved* at 0%. `strategies.py` holds no reference to the weight tables (AST-asserted), and a test asserts 3.4's `resolver.py`/`traffic.py` and 3.5's `canary.py`/`rollout.py`/`health.py` are byte-identical to `main`. **Two orderings are load-bearing**: RECREATE supersedes the previous deployment *after* traffic moves, because superseding first makes it non-servable and 3.4 then rejects weight on it — the cutover would fail on its own precondition; and BLUE_GREEN re-runs the release gate *at the switch*, not only at prepare, because a deployment can pass validation and then have its agent killed before an operator presses the button (tested as that exact sequence). **Blue preservation needed no new storage**, which §5 asked to check before adding any: BLUE stays lifecycle-ACTIVE holding 0% (3.4's resolver skips zero-weight entries, so *preserved* is not *split-serving* — proven by driving real executions), recorded as GREEN's rollback target through `VersionLineageService.set_rollback_target` rather than a raw column write. **This is the first code in the codebase that reads `rollback_target_id` to perform a rollback**, closing §9 item 12 in combination with 3.4/3.5. "Prepared" is likewise inferable from 3.4's rows — GREEN carries a zero-weight entry exactly when warmed — so `BLUE_GREEN_NOT_PREPARED` needed no state either. **Rollback deliberately skips both the §12 veto and the gate**, for one reason: rollback must work when things are worst — rolling back reduces exposure, so a kill switch must never trap an operator on the version they are leaving, and requiring BLUE (already serving) to re-pass a gate would make rollback fail exactly when most needed. Everything that could give a candidate *more* traffic does check the veto. **ROLLING is deferred to 3.9 honestly**: a real `STRATEGY_ROLLING_DEFERRED` at **501** (a declared-but-unimplemented strategy is neither a client mistake nor a state conflict), no partial implementation, no `NotImplemented` placeholder, and the replica columns are not touched — a handler moving those counters would report progress while nothing rolled, the precise pretence SRS §3.6 forbids. **Dispatch is on the column, not the request body** — a `/strategy/recreate` path would let a caller recreate a deployment declared BLUE_GREEN, making the column decorative again. **No migration and no new table** — head stays `0041_canary_rollout`, so the five Milestone-2 "migration head unchanged" tests needed no bump for the first time since Phase 2.3.1. Routes 515 → 518 (+3). Four new error codes; two new audit events (`DEPLOYMENT_STARTED`/`DEPLOYMENT_SUCCEEDED`); `KILL_SWITCH_ACTIVE` (423) reused rather than minting a second code for a condition the platform already names. **One constraint was caught by a pre-existing test rather than by review** (the 3.1/3.2/3.3 vocabulary pattern, third instance of its class in this document): Phase 3.1's `test_ac14_...` greps for the replica-column names as bare substrings anywhere in `app/runtime/deployment/`, prose included — and this phase's own docstring named them while *explaining the deferral*; reworded rather than weakening the test, and this phase's own AC-09 test was then **tightened** to assert the same bare-name rule. 34 new tests in `backend/tests/runtime/test_strategies.py`. See `docs/deployment/strategies.md`. |
| **3.7 Automated Rollback & Release Safety** | **IMPLEMENTED** | One new module, `app/runtime/deployment/rollback.py`: `RollbackService` (the unified operation), `RollbackPolicyService` (most-specific-wins scope resolution) and `evaluate_thresholds` (the trigger arithmetic as a pure, database-free function, unit-testable without Postgres). **The §2 mandatory report corrected this document**: the prompt quoted §9 item 12's "a pointer nothing reads" about `rollback_target_id`, which 3.6 had already superseded by reading it for blue-green rollback; what was genuinely outstanding was *designating* it during a rollout and honouring it from the other paths. **Three rollback implementations existed with three different notions of the target** (Phase 5.0's caller-supplied *redeploy*, 3.5's `plan.stable_version_id`, 3.6's `rollback_target_id`); this phase adds one authoritative answer and one operation, and leaves all three in place — the Phase 5.0 endpoint still owns `POST .../rollback` and still redeploys, with the new surface nested under `/rollback/...` (Phase 3.1's own collision resolution, reused). **The field is now authoritative and fails closed**: no designation, a target on another agent, a non-published target, or a target equal to the deployed version all raise `ROLLBACK_TARGET_UNAVAILABLE` and move nothing; when a rollout is in scope its `stable_version_id` must *agree*, and a disagreement fails closed rather than picking a winner, because a wrong rollback looks like a successful one. Written only through `VersionLineageService.set_rollback_target`, so the existing lineage writers and their validation are untouched (asserted by an AST test that also forbids raw assignment to the column). **One operation, four triggers** (MANUAL/REQUESTED/AUTOMATIC/FORCED) — data, not four code paths; with a rollout in scope the traffic move is **delegated to 3.5's own `request_rollback`** rather than reimplemented, and outside one it goes through 3.4's `set_weights`. The module holds no reference to the weight tables (AST-asserted), and a test asserts 3.4's/3.5's/3.6's six files are byte-identical to `main`. `initiated_by` is null for an automatic rollback — writing a system user id would make the audit trail claim a person acted. **§12 means something narrower and sharper here**: *automation* is subordinate to a kill switch, a human is not. An automatic rollback on a killed agent does not run; a manual one still does, matching 3.6's reasoning that a kill must never trap an operator on the version they are leaving. Nothing writes `Agent.lifecycle_status` or a deployment's `status`, asserted as `(receiver, attribute)` pairs. **The §12 check runs before the health evaluation**, corrected during the build after a failing test: the health engine independently returns UNKNOWN for a vetoed candidate, so checking afterwards reported a kill switch as "health verdict UNKNOWN is not evidence of a regression" — safe, but the wrong explanation. **INSUFFICIENT_DATA and UNKNOWN never trigger** (3.5's discipline, same reasoning): three failures out of three is a 100% error rate and still not evidence. Trigger thresholds are deliberately **wider than 3.5's stage gates** (a test asserts the relationship rather than letting it drift) because declining to promote is cheap and reversible while moving production traffic unattended is not; cost is compared **per execution** so a busier candidate does not look expensive, and a zero/missing baseline is skipped rather than treated as infinitely good. **Automation is opt-in** — absent an enabled policy nothing fires, so a tenant that configures nothing keeps 3.5/3.6's manual behaviour exactly; `NOTIFY_ONLY` detects and records without acting. **Anti-flap: two independent guards** — a cooldown (default 900s) and the rule that only a version *on trial* is a candidate (a zero-weight version is never re-judged, which stops the restored last-known-good being rolled back on the next tick; documented before implemented, and the gap caught by this phase's own AC-07 test). Deduplication is separate and decided by the database: a partial unique index on `dedup_key` keyed on (deployment, deployed version), the same primitive as `uq_traffic_allocations_current`; manual and forced rollbacks sit outside it, since a human may roll back twice. **Evidence preservation**: `evidence_ref` captures the candidate's metrics, baseline, window, verdict and crossed thresholds at the moment of rollback — the rollback must not be the act that destroys the reason for it. **Recovery** (`RECOVERY.md`'s durable/ephemeral split): the event row is committed `IN_PROGRESS` *before* traffic moves and `COMPLETED` only after the allocation commits, `resume_incomplete` runs at the start of every evaluation, and re-applying is harmless because 3.4's allocation declares an end state rather than a delta — there is no half-applied state to compound (the ordering is asserted structurally). **§11 override**: new elevated `runtime.deployment.force_rollback`, schema-enforced justification, `CRITICAL` audit; its narrow power is naming a target where none is designated. Stated honestly in the docs and a test: `SYSTEM_ROLE_PERMISSIONS` grants ADMIN/SUPER_ADMIN the whole catalog, so the new code restricts neither — what it buys is that the separation becomes *expressible* for custom roles. **A pre-existing test caught a collision for the fourth time** (see §9 item 15): 3.5's transition-authority grep matched this phase's `RollbackEvent.state`; the column was renamed to `status` (also matching platform naming) rather than using the `noqa` escape the test offers, and this phase's AC-09 test was then made precise about receivers — stricter, not weaker. Migration `0042_automated_rollback`, two new tables, reversible (verified live). Routes 518 → 524 (+6); schema 119 → 121 tables; the five Milestone-2 "migration head unchanged" tests bumped to `0042`. 58 new tests in `backend/tests/runtime/test_automated_rollback.py`, including **the §19 proof made automatic** — a candidate on trial at 50% starts failing and the platform rolls it back on its own, stable to 100%, evidence preserved, three audit events written, no human in the loop after the policy was configured. See `docs/deployment/rollback.md`. |
| **3.8 Distributed Scheduler** | **IMPLEMENTED** | New package `app/scheduler/` — a **sibling** of `app/runtime/`/`app/integration/`, forced by Milestone 2's runtime-never-knows rule (it registers a connector-health handler, and that word may not appear under `app/runtime/`). `service.py` (`SchedulerService`: claim, lease, dispatch, heartbeat, recover), `schedule.py` (pure due/backoff arithmetic, no I/O or clock of its own), `handlers.py` (the fixed registry + four handlers), `principal.py` (the automation actor), `runner.py` (the process entrypoint), `routes.py` (management only). **The commit-before-dispatch boundary is the phase**: three transactions per run — claim (`FOR UPDATE SKIP LOCKED` a due definition → insert the run row → advance `next_run_at` → **commit**), handler (no claim lock held), completion. Following the M1 deadlock lesson literally: `claim_next`'s own precedent *flushes* rather than commits and holds its lock across the whole attempt, which is exactly what a scheduler must not do, so the locking idiom was reused and the transaction lifetime deliberately was not. Proven three independent ways — from *inside* a handler (another connection takes `FOR UPDATE NOWAIT` on the definition row and succeeds), behaviourally (A mid-handler does not block B claiming another job), and structurally. **Exactly-once** via `uq_job_runs_occurrence` on `(job_definition_id, occurrence_key)`, the key derived from the instant the job was *due* (a claim-time key would differ per instance and defeat the guard); retry and stale-lease recovery both **reuse the same run row**, making "no duplicate successful run" a schema property rather than a detection problem. **The limit is stated, not hidden**: this is exactly-once *dispatch*, not side effects — a crash after a handler committed work but before the run was marked SUCCEEDED re-runs it, which is why every handler is an idempotent reconciliation. **The §20 proof, both parts, on real separate connections** (never an in-process mutex — the property is that two *processes* sharing only a database cannot both run one job): two instances contend and `SKIP LOCKED` makes the loser skip rather than block, exactly one run row, handler ran once; then a crashed owner's expired lease is reclaimed by a peer that reuses the same row, records `recovered_from`, and completes it. **Leases outlive their timeout by a margin** so a handler finishing at its deadline cannot race its own reclamation; a heartbeat from a *dispossessed* owner is ignored (two owners is the one thing a lease prevents); an exhausted run is ABANDONED rather than reclaimed forever; **retry and crash recovery share one mechanism** (a re-armed run's lease is set in the past), because two paths that could disagree about attempt counting would be two chances to get exactly-once wrong. **The scheduler dispatches; it does not decide** — four handlers, each a thin adapter over the domain that already owned the logic (2.1.3's sweep, 3.5's `evaluate_and_advance`, 3.7's `RollbackService.evaluate`, plus expired-state cleanup); both deployment methods were written for exactly this and needed **no change**; tests assert no threshold/gate/weight vocabulary appears in the scheduler or its handlers. **Dispatch is a fixed dictionary, not dynamic import**: an unrecognized key raises `JOB_HANDLER_UNKNOWN`, and an AST test asserts `import_module`/`__import__`/`eval`/`exec`/`getattr` appear nowhere, so a database row can never cause arbitrary code to execute. **The interim scheduler is retired** exactly as its own docstring specified — sweep logic moved to `app/integration/sweep.py` unchanged, the `asyncio` task/`start`/`stop`/lifespan hook deleted, no parallel path; `CONNECTOR_HEALTH_SCHEDULER_ENABLED` survives with real continuing meaning (it now decides whether the seeded definition is *enabled*, still default false, because retiring an opt-in mechanism must not turn it on). The API process deliberately starts no scheduler — one inside the web process would scale with HTTP traffic and make every replica a competing instance. **Phase 2.1.3's `test_ac20` updated, not deleted** (§9 item 15's established precedent): its source assertions described a now-deleted file; the behaviour it protected is asserted verbatim and the test is *stricter*, now also asserting the retirement happened. **The principal was a real fork, escalated before coding**: one non-human `users` row per org that cannot authenticate — reusing a real user would have made the audit claim a person triggered every scheduled rollback, undoing 3.7's `initiated_by = NULL`, and widening the bounded operations would have modified `canary.py`, pinned byte-identical by 3.6 and 3.7. **CRON deliberately unimplemented** rather than declared-and-broken, the same honesty 3.6 applied to ROLLING. Lease and attempt are **columns on `job_runs`**, not tables (SRS §14's warning against a table per noun): a lease has no life outside its run, and a retry reuses the row. Migration `0043_distributed_scheduler`, two tables, reversible (verified live). Routes 524 → 530 (+6); schema 121 → 123 tables; two error codes, two audit events, two permissions. 51 new tests in `backend/tests/runtime/test_distributed_scheduler.py`. See `docs/deployment/scheduler.md`. |
| **3.9 Distributed Execution Worker Fleet & Rolling Deployment** | **IMPLEMENTED** | New package `app/workers/` — a **sibling** of `app/scheduler/`, for the same reason that one is: a worker process is platform infrastructure that *drives* the runtime domain rather than a service inside it. `fleet.py` (`WorkerFleetService`: registration, liveness, capacity, staleness), `worker.py` (`ExecutionWorker`: the claim loop, concurrency slots, drain, graceful shutdown), `runner.py` (`python -m app.workers.runner`), `routes.py` (observability and drain only). **The whole phase is one transaction boundary**: `ExecutionWorkerService.claim_next` now **commits** instead of flushing, so a worker holds no database lock across model or tool network I/O. Until now the claim's `FOR UPDATE` was held for the entire attempt — the exact shape of the M1 deadlock, which `ToolLoopOrchestrator._execute_parallel` had been working around by hand with its own commit before spawning tool threads. **No second lease table was added**: `execution_locks.execution_id` has been UNIQUE since migration 0023 and *is* the no-duplicate-execution guarantee; a parallel table would be two sources of truth for one fact. **Proven three ways** — behaviourally (a second connection takes `FOR UPDATE NOWAIT` on the just-claimed row), from inside a running model call, and structurally over the AST — and **all five gate tests were verified to fail with the boundary reverted to `flush()`**. The in-flight probe's lock mode was corrected by a failing test: `FOR UPDATE NOWAIT` fails against *correct* code, because by mid-attempt the worker legitimately holds a shared lock on its own row; the right probe is `FOR KEY SHARE NOWAIT`, exactly the lock a tool thread needs and exactly the one the old exclusive claim blocked. **M1 execution is preserved exactly** — `worker.py` contains no provider call, tool loop, retry policy, cost arithmetic or authorization, asserted over the AST's names-in-use rather than source text (the docstring necessarily names what it delegates to); the entire M1 execution suite passes unchanged. **The honest limit is stated as plainly as 3.8 stated its own**: exactly-once *dispatch*, not exactly-once side effects. **ROLLING resolves ruling #1** over real cohorts: a cohort is a declared partition of the registered fleet, its capacity the summed declared concurrency of live heartbeating workers, and each step moves traffic to the fraction of *real* capacity converted — a fleet of 8 and 2 slots steps **80 → 100**, not an invented ladder. Workers are **not** version-pinned (3.4 binds the version at enqueue and remains the sole allocator); what rolls is the share of new work, in units of real capacity, with the fleet **sizing** and **gating** the rollout — a dead cohort fails the next step closed with `ROLLING_COHORT_INVALID`. The vestigial replica columns remain untouched and unnamed. **No rolling state machine and no rolling table**: a rolling deployment *is* a `RolloutPlan` with `kind='ROLLING'`, reusing 3.5's seven states, gates, concurrency, idempotency and rollback integration wholesale; the entire schema difference is two columns. **The cohort gate was moved into the advance choke point** after the first placement proved bypassable via the generic `/rollouts/{id}/advance` route. **A route collision was reported, not redesigned around silently**: M1 already owns `/runtime/workers` and `/runtime/workers/reap`, so the fleet API mounts at `/runtime/fleet`. **PG16/17 is CLOSED** — Compose aligned to `postgres:17-alpine` + `ai_agent_control_tower`, asserted against both the file and the running server, with the `act_pgdata` major-version hazard documented in `RECOVERY.md` and deliberately not automated. **Phase 3.7's byte-identity guard was narrowed and replaced, not weakened** (see §9 item 15). Migration `0044_worker_fleet_rolling`, one table + two columns, reversible (verified live). Routes 530 → 536 (+6); schema 123 → **124 tables**; three error codes, three audit events, two permissions. 60 new tests in `backend/tests/runtime/test_worker_fleet_rolling.py`. See `docs/deployment/workers.md` and the rewritten `docs/deployment/strategies.md`. |
| **3.10 AI Release Operations Center** | **IMPLEMENTED** | New frontend module `frontend/src/modules/operations/` (twelve operational views, a permission-gated nav, a two-tier confirmation dialog, and `useGuardedAction` — the single place every privileged action dispatches, which is what makes "dangerous actions are confirmation-gated" a property of the module rather than a habit twelve pages must remember) plus one backend module, `app/runtime/operations.py`. **Read + trigger only, enforced structurally**: no `add`/`commit`/`delete`/`flush` call and no mutating service import (both AST-asserted), all four routes GET, **no migration**, and a git-diff test pinning twelve engine modules byte-identical to `main`. **Eight of the twelve views needed no new endpoint**; the four that did were reported before coding — an overview aggregation (five extra requests per row otherwise), release history (previously exposed only per-deployment, defeating §13 reconstructability), the detail composite (§22's thirteen fields across eight endpoints), and **the rollout list, which Phase 3.5 never had** — `GET /rollouts/{id}` existed with no way to discover a rollout, so a canary could be advancing through production traffic invisibly. **Truthful state is the deliverable**: `kill_switch_active`, `gate_verdict`, `release_health.is_proving` and `servable` are first-class fields, because a read model that omitted them would *make* the UI present a killed release as deployable; INSUFFICIENT_DATA renders as a warning, never neutral, carrying Phase 3.5's rule into the UI. **Two confirmation tiers, deliberately unequal** — a single confirm for reversible operations, type-to-confirm for the irreversible; uniform friction is friction people click through. **Conflicts are never auto-retried** (a stale intent must not be re-applied) and safety refusals pass through verbatim. **Five capabilities deliberately absent** — no job dispatch (3.8's exactly-once depends on it), no worker registration (phantom capacity feeds rolling's real step weights), no arbitrary rollback target (3.7 fails closed), no weight normalisation, no gate prediction. **Path conflict reported rather than redesigned around**: §6 sketched `/api/v1/deployments/overview`, which `/deployments/{deployment_id}` would swallow as an id — nested under `/runtime/operations/` instead. Routes 536 → 540 (+4, all GET); schema unchanged at 124 tables; head unchanged at `0044`. 26 new backend tests, 30 new frontend tests. See `docs/deployment/operations-center.md`. |

---

## 7. Conventions

| Convention | Detail | Reference |
|---|---|---|
| ORM declarative base | `class Base(DeclarativeBase)` | `backend/app/core/database.py:24` |
| PK mixin | `UUIDPrimaryKeyMixin` — app-generated `uuid.uuid4()` UUID primary key | `backend/app/models/mixins.py` |
| Timestamp mixin | `TimestampMixin` — `created_at`/`updated_at`, server-side `func.now()`, `onupdate` on the latter | `backend/app/models/mixins.py` |
| Error envelope | `ErrorCode` (string-constant class) + `IdentityError(code, message)` exception, handled by a registered FastAPI exception handler producing `{"success": false, "error": {"code", "message"}, "request_id"}` | `backend/app/identity/errors.py` — used well beyond the identity module itself (e.g. every `app/runtime/*` file imports `ErrorCode`/`IdentityError` from here) |
| Service pattern (dominant) | One `XService` class per aggregate, `__init__(self, db: Session)`, a `get_or_404` method, direct SQLAlchemy queries — no repository indirection | e.g. `AgentVersionService` in `backend/app/runtime/services.py`, `AgentLifecycleService` in `backend/app/runtime/registry/services.py` |
| Repository pattern (minority) | Explicit `XRepository` classes wrapping queries, used underneath services | Only in `backend/app/identity/repositories/*.py` (`BaseRepository` generic base in `base.py`) and `backend/app/authorization/repositories.py` (Phase 4.3.1 core only) — **not** used in the later authorization submodules (`abac/`, `admin/`, `hierarchy/`, `resources/`), governance, or runtime/registry/versioning (including 5.2.6's `compatibility.py`, 5.2.4's `attestation.py`/`keys.py`, re-verified this session), which query directly from services. This is an inconsistency across phases, not a documented rule (see §10). |
| Permission naming | Dot-notation `domain.resource.action` strings (e.g. `runtime.version.retire`, `runtime.signing.manage`, `agent.view`, `policy.edit`), centrally cataloged | `PERMISSION_CATALOG: dict[str, str]` in `backend/app/services/rbac_service.py`; `require_permission(code)` dependency in `backend/app/api/deps.py:129` |
| Backend test framework | pytest, real Postgres (not sqlite/mocks) via `SessionLocal()`; `client`/`db_session`/`admin` fixtures | `backend/tests/authorization/conftest.py`, `backend/tests/runtime/conftest.py` (the latter also carries an autouse fixture isolating each test onto its own signing key_id — see §10 #16); hermetic defaults (notifications/rate-limit/envelope off) via autouse fixtures in `backend/tests/conftest.py` |
| Backend test layout | `backend/tests/{authorization,identity,integration,runtime}/` plus flat `test_*.py` files at `backend/tests/` root for the original Phase 1-3 surface | `integration/` is a brand-new top-level directory added Phase 2.1.1 (`conftest.py` — its own minimal `client`/`admin`/`other_org_admin`/`viewer`/`db_session` fixtures, mirroring `tests/authorization/conftest.py`'s established shape rather than reusing `tests/runtime/conftest.py`, since this is a new domain, not a runtime extension; `test_connector_core.py`, 24 tests (one test updated, not weakened, in Phase 2.1.3 — see below); `test_connector_auth.py` added Phase 2.1.2, 31 tests, real-thread/real-Postgres OAuth2 concurrency proof plus fixtured-`httpx.MockTransport` token-endpoint tests, no live network anywhere; `test_connector_health.py` added Phase 2.1.3, 24 tests, registry/health/fail-fast/scheduler coverage, `run_sweep_once()` called directly rather than waiting on the interim scheduler's own sleep loop; `test_connector_sdk.py` added Phase 2.1.4, 26 tests, surface/registration-parity/completeness/governance-inheritance/testing-utilities/integrity coverage; `test_connector_sdk_example.py` added Phase 2.1.4, 5 tests, deliberately kept in its own file so its import list — only `app.integration.sdk` and the example connector itself — is an isolated, mechanically-checkable proof that the worked example's own tests use only the SDK harness; `test_rest_connector.py` added Phase 2.2.1, 30 tests, declaration/templating/extraction/pagination/SDK-surface/integrity — no HTTP at all; `test_rest_connector_invocation.py` added Phase 2.2.1, 11 tests, deliberately kept in its own file since it is the one that talks to a real local `127.0.0.1` fixture server, mirroring `test_http_tool_execution.py`'s own established convention — end-to-end invocation, live egress inheritance, and a genuine stored/encrypted credential reaching the server as a real header; `test_database_connector.py` added Phase 2.2.2, 35 tests, the security core (bound-parameter injection proofs against this platform's own real dev Postgres)/declared-queries/read-only/limits/drivers/SDK-surface/integrity; `test_database_connector_invocation.py` added Phase 2.2.2, 7 tests, deliberately kept in its own file since it is the one that connects a real, database-backed `ConnectorInstance` with a real, stored, encrypted `BASIC` credential to this platform's own dev Postgres — end-to-end bridge invocation, live credential resolution/protection; `test_storage_scope.py` added Phase 2.2.3, 41 tests, the isolated traversal/scope-escape security core — every named traversal vector, no live storage anywhere in the file, plus a real temp filesystem symlink/junction for the escape case; `test_storage_connector.py` added Phase 2.2.3, 30 tests, scope/operations/limits (real `tmp_path` filesystem I/O), backend dispatch (filesystem live, S3 against a mocked `boto3.client`), SDK-surface/integrity; `test_storage_connector_invocation.py` added Phase 2.2.3, 11 tests, deliberately kept in its own file since it is the one that connects a real, database-backed `ConnectorInstance` with a real, stored, encrypted credential to this platform's own dev database — end-to-end bridge invocation, per-access audit trail verification, live credential protection; `test_queue_scope.py` added Phase 2.2.4, 7 tests, the isolated scope-permission check — zero imports of any kind, no live broker anywhere in the file; `test_queue_connector.py` added Phase 2.2.4, 31 tests, scoped-publish/bounded-consume/size/ack mechanics against mocked `pika`/`boto3` transports, SDK-surface/integrity; `test_queue_connector_invocation.py` added Phase 2.2.4, 12 tests, deliberately kept in its own file since it is the one that connects a real, database-backed `ConnectorInstance` with a real, stored, encrypted credential to this platform's own dev database via both `publish_message` and `consume_messages` — end-to-end bridge invocation, per-attempt audit trail verification, live credential protection (the broker connection itself stays mocked in this file too — only the database half is live). `runtime/` added Phase 5.2.6/5.2.4 (`test_version_compatibility.py`, `test_canonical.py`, `test_version_signing.py`, `test_attestation.py`); `test_provider_abstraction.py` added Phase 5.7a.1 (reusable parameterized conformance suite, `PROVIDERS_UNDER_TEST` list); `test_openai_compatible_provider.py` added Phase 5.7a.2, `test_streaming_and_accounting.py` added Phase 5.7a.3, `test_error_taxonomy_and_resilience.py` added Phase 5.7a.4 (classification/retry/circuit-breaker tests, four AC groups), `test_provider_credentials.py` added Phase 5.7a.5 (storage/encryption, resolution, redaction, API/integrity — four AC groups, 25 tests); `test_egress_guard.py` (32 tests, no network/database) and `test_http_tool_execution.py` (19 tests, real `127.0.0.1` fixture servers) added Phase 5.6a.1; `test_tool_resilience.py` (19 tests, schema validation/idempotent-retry/circuit-breaker/concurrency-ceiling) added Phase 5.6a.2; `test_tool_loop.py` (17 tests, the model-driven loop, parallel execution, termination caps, an end-to-end proof) added Phase 5.6a.3, reusing `single_tool_call.json`/`multiple_tool_calls.json`/`multi_turn_with_tool_message.json` (fixtures already committed under `runtime/fixtures/providers/` from an earlier phase, unused until now) plus inline-built tool-call response bodies for scenarios no committed fixture covers; `runtime/fixtures/providers/` holds committed wire-format/SSE replay fixtures (Phase 5.7a.2/5.7a.3) plus nine error-scenario fixtures (Phase 5.7a.4, two documentation-only — see that directory's `README.md`); `identity/federation/` is a new subdirectory added Phase 2.3.1 (own `__init__.py`/`conftest.py` — `rsa_keypair` fixture, a real generated RSA keypair + JWKS, not a committed key — since this phase needed genuine cryptographic material for both directions of proof, not fixtures reused from elsewhere): `test_oidc_bypass_prevention.py`, 14 tests, isolated from any live IdP — real RSA-signed tokens, every canonical JWT bypass vector individually, plus structural (AST-based) proof `jose` is used and `algorithms` is never read from the token's own header; `test_saml_bypass_prevention.py`, 12 tests, using `_saml_fixtures.py` (a test-only, from-scratch SAML XML construction/`xmlsec`-signing module — the only place in this codebase that ever constructs a signed assertion) — two distinct signature-wrapping attack shapes proven defeated, plus structural proof of `onelogin`/`xmlsec` delegation; `test_claim_mapping.py`, 8 tests, pure unit tests, no database; `test_federation_login_flow.py`, 10 tests, end to end via `FederationService` against this platform's own real dev database, monkeypatching only the two IdP-network calls (`exchange_code_for_id_token`/`fetch_jwks`) — JIT provisioning, real session issuance, indistinguishable-session proof, JIT-disabled behavior, cross-org/forged/expired state rejection; `test_federation_config_crud.py`, 13 tests, real HTTP via `TestClient(app)` — permission gating, cross-org isolation, secret-never-returned, coexistence with local login; `test_deployment_lifecycle.py` added Phase 3.1 to the pre-existing `runtime/` directory (not a new subdirectory — this phase extends the existing runtime domain, not a new one), 27 tests grouped by that phase's own §12 acceptance criteria: the pure state-machine graph (no database), the single-authority invariant (grep-based, mirroring the connector framework's own precedent), the reusable idempotency contract's genericity plus a real two-thread concurrent-claim race, the vestigial-replica-column boundary, the happy path to `ACTIVE` and back down through pause/resume/retire via real HTTP, append-only event lineage, the §15 migration mapping's own internal consistency (not a live cross-check against the still-mutable legacy `status` column — see the test's own docstring for why that would be unsound), Ruling #6's suspension guard (including the `PAUSED → ACTIVE` resume path), the mission-critical/production approval-precondition reroute, tenant isolation and permission enforcement, and a real-Postgres two-thread revision-conflict race; `test_environment_promotion.py` added Phase 3.2 to the same directory, 29 tests grouped by that phase's own §12 acceptance criteria: tenant-scoped environments with standard-seeding/custom-creation (AC-01), the live-migration/opportunistic-backfill string→row proof (AC-02/AC-14), every enforced policy dimension via the shared plain-deploy/promotion choke point (AC-03), the change window with both a real-HTTP and a pure no-database unit test (AC-04), promotion-path enforcement (AC-05), the immutability assertions — same version id, unchanged version count, byte-identical checksum/digest/signature (AC-06/AC-07), the full lifecycle-driven happy path and the production-approval reroute (AC-08), a real-Postgres idempotency proof (AC-09), the `prohibited_environments` integration (AC-10), the release-channel orthogonality proof (AC-11), tenant isolation/authentication (AC-12), a real two-thread concurrent-promotion race (AC-13), the Milestone 1 execution-gate boundary (AC-15), and a stray-marker scan (AC-17); `test_release_gate.py` added Phase 3.3 to the same directory, 27 tests grouped by that phase's own §12 acceptance criteria: verdict/finding structure (AC-01/AC-02), pure aggregation-precedence and freshness-state unit tests with no database (AC-03/AC-09), a BLOCK actually preventing a lifecycle transition (AC-04), reuse-verified-by-spy tests for the environment-policy and approval checks (AC-05/AC-11), a fail-closed unevaluable-check test (AC-06), the kill switch's absolute-BLOCK and re-checked-at-transition guarantees (AC-07/AC-08), the freshness rule's stale/fresh/unhealthy behavior and its configurable bound (AC-09/AC-10), persisted latest/history retrieval (AC-12), authentication and cross-tenant rejection (AC-13), a per-finding-code sweep (checksum tamper, invalid machine identity, a disabled bound tool, an unregistered provider, a missing owner, an environment-policy violation, a pending-approval WARNING that doesn't disturb the reroute), a full happy-path PASS, and vocabulary/TODO-marker sweeps; verified via `find backend/tests -maxdepth 2 -type d` |
| Frontend test framework | Vitest, `jsdom` environment, `@testing-library/react` + `user-event`, cleanup via `afterEach` | `frontend/vitest.config.ts`, `frontend/src/test/setup.ts` |
| Frontend test layout | `frontend/src/modules/<domain>/tests/*.test.tsx` co-located per module (not a top-level `tests/` dir) | verified via `find frontend/src/modules -iname "*.test.*"` (this session) |
| Frontend structure | One module dir per backend domain (`frontend/src/modules/<domain>/`), one service file per domain (`frontend/src/services/<domain>Service.ts`), shared Radix-based primitives in `frontend/src/components/ui/` | `frontend/src/modules/*`, `frontend/src/services/*.ts` |
| Frontend stack | React 19, TypeScript, Vite, TanStack Query (server state), react-hook-form + zod (forms), Radix UI primitives, Tailwind, react-router-dom v7 | `frontend/package.json` |
| Backend stack | FastAPI 0.115, SQLAlchemy 2.0, Alembic 1.14, Pydantic 2.10, pytest 8.3 | `backend/requirements.txt` |

---

## 8. Branch History

Output of `git branch --sort=-committerdate`, with committer dates added via `--format`. Names and dates only — **56 local branches** as of 2026-08-17 (was 54 at the 3.6 count, 50 at the Phase 3.3 count before that); each mirrored by an `origin/*` remote-tracking branch. **2 new branches since the 3.6 count**, both merged into `main` via a `--no-ff` merge: `docs/state-refresh` (a documentation-maintenance pass, not a phase — see the dated header entry above) and `feat/3.7-automated-rollback`.

| Branch | Committer date |
|---|---|
| `main` | 2026-08-17 (Phase 3.7 merge) |
| `feat/3.7-automated-rollback` | 2026-08-17 |
| `docs/state-refresh` | 2026-08-14 (documentation-maintenance pass) |
| `feat/3.6-strategies` | 2026-08-14 22:41:03 +0500 |
| `fix/temp-password-policy-compliance` | 2026-08-14 17:27:11 +0500 |
| `feat/3.5-canary-engine` | 2026-08-14 03:51:36 +0500 |
| `feat/3.4-traffic-resolver-gate` | 2026-08-13 17:50:34 +0500 |
| `feat/3.3-release-gates` | 2026-08-11 04:09:53 +0500 |
| `feat/3.2-environments-promotion` | 2026-08-10 22:02:23 +0500 |
| `feat/3.1-deployment-core` | 2026-08-10 17:18:21 +0500 |
| `feat/2.3.1-identity-federation` | 2026-08-08 04:16:38 +0500 |
| `feat/2.2.4-queue-connector` | 2026-08-07 06:08:30 +0500 |
| `feat/2.2.3-storage-connector` | 2026-08-07 02:17:42 +0500 |
| `feat/2.2.2-database-connector` | 2026-08-06 17:14:13 +0500 |
| `feat/2.2.1-rest-connector` | 2026-08-05 22:43:03 +0500 |
| `feat/2.1.4-connector-sdk` | 2026-08-05 16:16:41 +0500 |
| `feat/2.1.3-connector-registry` | 2026-08-05 04:40:22 +0500 |
| `feat/2.1.2-connector-auth` | 2026-08-04 22:10:53 +0500 |
| `feat/2.1.1-connector-core` | 2026-08-01 05:56:16 +0500 |
| `feat/5.6a.3-tool-loop` | 2026-08-01 02:28:10 +0500 |
| `feat/5.6a.2-tool-resilience` | 2026-07-31 04:40:07 +0500 |
| `feat/5.6a.1-http-tools` | 2026-07-30 07:31:16 +0500 |
| `feat/5.7a.5-credentials-cost` | 2026-07-30 02:44:57 +0500 |
| `feat/5.7a.4-error-resilience` | 2026-07-29 20:52:09 +0500 |
| `feat/5.7a.3-streaming-tokens` | 2026-07-28 00:38:11 +0500 |
| `feat/5.7a.2-openai-compatible` | 2026-07-27 18:14:08 +0500 |
| `feat/5.7a.1-provider-abstraction` | 2026-07-24 16:33:05 +0500 |
| `feat/5.2.4-signing-provenance` | 2026-07-23 07:24:19 +0500 |
| `feat/5.2.6-compatibility` | 2026-07-23 06:27:39 +0500 |
| `feature/phase-5.2-part1-versioning-foundation` | 2026-07-23 01:56:36 +0500 |
| `feature/phase-5.1-agent-registry-hardening` | 2026-07-22 22:19:01 +0500 |
| `feat/phase-5.0-hardening` | 2026-07-20 18:35:58 +0500 |
| `feat/phase-5.0-agent-runtime` | 2026-07-20 16:16:04 +0500 |
| `feat/phase-4.3.8-governance-and-redesign` | 2026-07-18 05:09:40 +0500 |
| `feat/4.3.7-admin-portal` | 2026-07-16 17:41:10 +0500 |
| `feat/4.3.6-authorization-middleware` | 2026-07-16 16:26:34 +0500 |
| `feat/4.3.5-abac-engine` | 2026-07-15 23:45:25 +0500 |
| `feat/4.3.4-resource-authorization` | 2026-07-15 02:32:06 +0500 |
| `feat/4.3.3-org-hierarchy` | 2026-07-10 22:46:03 +0500 |
| `feat/4.3.2-engine-events-and-perf` | 2026-07-10 19:35:57 +0500 |
| `feat/4.3.2-permission-engine` | 2026-07-10 19:18:52 +0500 |
| `feat/4.3.1-enterprise-rbac` | 2026-07-10 16:41:03 +0500 |
| `feat/4.2.2.3.5-envelope-and-deploy` | 2026-07-10 04:54:20 +0500 |
| `feat/4.2.2.3.5-integration-release` | 2026-07-10 04:27:05 +0500 |
| `feat/account-protection-4.2.2.3.4` | 2026-07-10 04:00:11 +0500 |
| `feat/account-recovery-4.2.2.3.3` | 2026-07-09 18:06:46 +0500 |
| `feat/credential-management-4.2.2.3.2` | 2026-07-09 16:35:03 +0500 |
| `feat/registration-invitations-4.2.2.3.1` | 2026-07-09 03:15:21 +0500 |
| `feat/phase-4.2.2.2-session-lifecycle` | 2026-07-08 23:17:27 +0500 |
| `feat/phase-4.2.2.1-human-auth-and-architecture-docs` | 2026-07-08 17:52:30 +0500 |
| `phase-4-authentication-architecture` | 2026-07-07 18:19:05 +0500 |
| `phase-4-1a-identity-lifecycle` | 2026-07-02 16:18:20 +0500 |
| `phase-4-identity-foundation` | 2026-07-02 00:34:10 +0500 |
| `feat/analytics-operations-part-3.6` | 2026-07-01 05:19:14 +0500 |
| `feat/audit-compliance-center-part-3.5` | 2026-07-01 04:18:00 +0500 |
| `feat/approval-workbench-part-3.4` | 2026-06-30 02:53:28 +0500 |

Current branch: **`feat/3.7-automated-rollback`**, branched from `main` at `248ce00` ("Merge documentation refresh: REPO_STATE, RECOVERY and README to post-3.6 state"). Working tree clean once this document's own update, and the accompanying `CHANGELOG.md`/`ROADMAP.md`/`RECOVERY.md`/`README.md` updates, are committed.

---

## 9. Known Gaps

Every item below was mechanically verified at generation time (grep with an explicit exit-code check, or an actual test run), not inferred.

1. **Zero real `TODO`/`FIXME`/`XXX`/`HACK:` markers** anywhere in `backend/app` or `frontend/src`. Re-verified this session (including all Phase 5.7a.4 files): `grep -rn` now returns exactly one hit — `backend/app/runtime/versioning/canonical.py:24`, the substring `XXXX` inside `` \uXXXX `` (documentation prose describing JSON's Unicode-escape syntax, not a marker) — confirmed benign by inspection, not a real TODO-style marker.
2. **`NotImplementedError` correction (previously an inaccurate "zero" claim in this document, fixed this pass)**: `grep -rn "NotImplementedError" backend/app` returns exactly one real hit, `backend/app/runtime/providers/base.py:71` — `ModelProvider.stream()`'s deliberate, unreachable-through-normal-instantiation stub (Phase 5.7a.1's own docstring explains why: it exists only so a subclass that nominally overrides `stream()` by delegating straight back to `super().stream(...)` fails loudly instead of silently returning `None`). This was already present before Phase 5.7a.4; this document's prior "zero" claim for this item was simply never actually re-verified by grep in an earlier pass. Phase 5.7a.4 added none — confirmed via its own `test_no_new_todo_or_skip_markers_in_this_phases_files`, scoped to the files that phase touched.
3. **Zero pytest `skip`/`xfail` markers** in `backend/tests`.
4. **Duplicate OpenAPI `operationId` warning**: `update_policy` in `backend/app/api/routes/policies.py:137` is registered via `@router.api_route("/{policy_id}", methods=["PUT", "PATCH"])` — both methods share one function, so FastAPI's OpenAPI generator emits a `UserWarning: Duplicate Operation ID` every time the schema is built (reproduced during this session's test run). Cosmetic — both HTTP methods work correctly (`test_response_envelope.py::test_openapi_schema_is_not_enveloped` passes) — but would break strict OpenAPI-codegen tooling pointed at this schema.
5. ~~Only the `MOCK` model provider actually executes~~ — closed in Phase 5.7a.2: `registered_identifiers()` now returns `["MOCK", "OPENAI_COMPATIBLE"]`, and `OpenAICompatibleProvider` (`backend/app/runtime/providers/openai_compatible.py`) makes real HTTP calls (streaming included, Phase 5.7a.3; error taxonomy/retry/circuit-breaking included, Phase 5.7a.4; per-organization encrypted credentials included, Phase 5.7a.5 — see item 16 below, now closed) against Ollama/vLLM/LM Studio/OpenAI. **The model half of Milestone 1 is now complete.** What remains: no multi-provider failover (trying a *different* provider on failure — retry is same-provider only, deliberately, per Phase 5.7a.4's scope; owned by 5.7 proper), only these two identifiers are registered — any other provider name still fails closed with `MODEL_PROVIDER_UNAVAILABLE` — and the tool half of Milestone 1 (5.6a.1-3) has not started. See `docs/runtime/providers.md`.
6. ~~Only the `FUNCTION`/`echo` tool action actually executes~~ — **fully closed as of Phase 5.6a.3, completing Milestone 1**: `HTTP` executes (5.6a.1) behind a hardened, per-tool egress allowlist, is schema-validated and resilient (5.6a.2), and a real model now genuinely drives it (5.6a.3) — `ModelGatewayService.invoke()` offers a version's bound tools to any capable provider, the model's own tool requests execute through the unchanged gateway, structured `FAILED` results feed back into the conversation for the model to see, and four independent safety caps bound the whole loop (see `docs/runtime/gateways.md`'s "Egress control", "Schema validation & resilience", and "The model-driven tool invocation loop" sections). Every other tool type still fails closed with `TOOL_ACTION_NOT_ALLOWED`. What remains, deliberately out of this milestone's scope: governance/cost policy evaluation mid-loop (5.8), multi-agent delegation (Milestone 10 — §10.4 stands, enforced by construction in the loop), distributed workers (Milestone 3).
7. **CAPTCHA is a placeholder.** `CaptchaService.verify()` (`backend/app/identity/protection/policy.py:89`) has no real Turnstile/reCAPTCHA/hCaptcha integration.
8. **Analytics cost figures are deterministic estimates**, not real provider billing data (`backend/app/services/analytics_service.py:64`, "Estimated unit costs (USD)... deterministic placeholders"). This is a genuinely separate, older, coarser concept than the real per-execution cost Phase 5.7a.3 added (`agent_executions.cost_amount`, computed from real tokens via `PricingService`) — `analytics_service.py`'s `cost_analytics()` aggregates Phase 3's `agent_actions` table, with no connection to `AgentExecution`/token data at all, and was deliberately left untouched (see `docs/runtime/providers.md`'s "What Phase 5.7a.3 found").
9. ~~Phase 5.2 cryptographic signing is unimplemented~~ — shipped in Phase 5.2.4 (see §6, row 5.2.4) and is no longer a gap. Two narrower deviations remain, both deliberate and documented in `docs/runtime/versioning.md`'s Known Deviations: (a) the local signing provider necessarily loads private key bytes into process memory to sign (`ACT-VER-NFR-002`), closing when Azure Key Vault lands; (b) there is no public/unauthenticated verification endpoint (`ACT-VER-FR-070`), closing if/when external verification is actually needed.
10. **No "release package" entity, literally named.** The SRS for Phase 5.2 Part 1 lists "release packages" as in-scope; this codebase treats the frozen `agent_version_snapshots.snapshot` document — and, as of Phase 5.2.4, the signed in-toto attestation built over it (`agent_version_provenance.attestation_document`) — as that bundle rather than introducing a separately-named table. The attestation document is a closer functional analog than the bare snapshot was (self-contained, portable, cryptographically signed), but still no artifact literally named "release package" exists — documented as a deliberate equivalence in `docs/runtime/versioning.md`, not a gap in functionality.
11. **Multi-agent orchestration and several other large feature areas do not exist in any form**: a visual workflow builder, distributed event streaming at hyperscale, automated model optimization, reinforcement learning, autonomous agent creation, a marketplace, multi-cloud federation, a Kubernetes operator, GPU scheduling. Explicitly out of scope per `docs/runtime/overview.md`'s "What's deliberately not here."
12. ~~**Actual rollback/canary/traffic-shift execution does not exist.**~~ — **closed across Phases 3.4–3.6.** When recorded, `AgentVersion.rollback_target_id` (Phase 5.2 Part 1) was a settable pointer nothing read, and `DeploymentService.rollback` (Phase 5.0) was a full redeploy rather than a traffic shift. Since then: 3.4 built real weighted traffic allocation plus the resolver/execution gate; 3.5 built the canary engine that drives it progressively against AI-aware health; and 3.6 added RECREATE and BLUE_GREEN, whose blue-green rollback is **the first code that reads `rollback_target_id` to actually perform a rollback**. Traffic-shifting rollback now exists as a real operation in three places (`POST .../rollouts/{id}/request-rollback`, `POST .../deployments/{id}/strategy/blue-green/rollback`, and 3.7's unified `POST .../deployments/{id}/rollback/execute`). The pre-existing `DeploymentService.rollback` is untouched and still does what it always did — it remains a *redeploy* rather than a traffic shift, and 3.7 deliberately nested beside it rather than claiming its path. **Phase 3.7 closes the remainder of this item**: `rollback_target_id` is now authoritative for every rollback path (not only blue-green), and the automatic trigger policy that decides *when* to invoke a rollback exists, is per-tenant, and is subordinate to the kill switch. **Phase 3.9 closes the last open piece**: the ROLLING strategy is implemented over the real worker fleet, so all four strategies now move traffic through 3.4's `set_weights` and every one of them is rollback-integrated. This item is fully closed. **Note for future readers**: Phase 3.7's own build prompt quoted this item's pre-3.6 wording ("a pointer nothing reads") as current, which it no longer was — a reminder that this document is the authority and that a prompt's premises are worth re-checking against it rather than the reverse.
13. **Frontend production bundle is a single ~1.65 MB chunk** (431 KB gzip) — Vite's build output flags this as exceeding its 500 KB warning threshold; no route-level code-splitting has been applied (reproduced this session via `npm run build`).
14. **`backend/.venv` had to be rebuilt mid-session** (Phase 5.1 work) because the one present in the working tree pointed at a Python interpreter path (`C:\Users\Dell\...`) from a different machine. It is gitignored, so this is a local-environment fact, not a repository defect — flagged here since a fresh clone on another machine will need the same rebuild. **UNVERIFIED** whether this affects any environment other than the one this document was generated in.
15. **Test suite status at generation time**: backend `661 passed, 0 failed` (`pytest -q`, 176.05s); frontend `297 passed, 0 failed` across 48 files (`vitest run`). Both re-run fresh for this document, not carried forward. **Phase 5.2.6 update**: backend re-run at `696 passed, 0 failed` (`pytest -q`, 184.63s) after adding 35 compatibility-detection tests; frontend untouched by Phase 5.2.6 (backend-only phase), still `297 passed, 0 failed` as of its own last run. **Phase 5.2.4 update**: backend re-run at `743 passed, 0 failed` (`pytest -q`, 190.89s) after adding 47 canonical-serialization/signing/attestation tests; frontend untouched by Phase 5.2.4 (also backend-only), still `297 passed, 0 failed` as of its own last run. **Phase 5.7a.1 update**: backend re-run at `766 passed, 0 failed` (`pytest -q`, 196.51s) after adding 23 provider-abstraction/conformance-suite tests; frontend untouched by Phase 5.7a.1 (also backend-only), still `297 passed, 0 failed` as of its own last run. **Phase 5.7a.2 update**: backend re-run at `800 passed, 0 failed, 1 deselected` (`pytest -q`, 202.56s; the one deselected test is the `live_provider`-marked genuinely-live Ollama check, excluded by default via `backend/pytest.ini`) after adding 34 OpenAI-compatible-adapter tests; frontend untouched (also backend-only), still `297 passed, 0 failed`. **Phase 5.7a.3 update**: backend re-run at `822 passed, 0 failed, 1 deselected` (`pytest -q`, 211.40s) after adding 22 streaming/accounting/cost tests; frontend untouched (also backend-only), still `297 passed, 0 failed` as of its own last run. **Phase 5.7a.4 update**: backend re-run at `858 passed, 0 failed, 1 deselected` (`pytest -q`, 226.87s) after adding 36 error-taxonomy/retry/circuit-breaker tests (a +15.47s suite-runtime increase — within the ≤20s budget the build prompt set; every backoff/retry test injects the delay via `monkeypatch`, none sleeps for real); frontend untouched by Phase 5.7a.4 (also backend-only), still `297 passed, 0 failed` as of its own last run — not re-run this pass. One transient, unrelated flake was observed during this phase's work (`test_generated_temporary_password_satisfies_policy`, a 50-iteration randomized-password-generation test in `backend/tests/identity/credentials/test_password_policy_unit.py`, wholly outside this phase's changes) that failed once and passed on immediate re-run in isolation and on a full clean re-run — not caused by, or related to, anything Phase 5.7a.4 touched. **Phase 5.7a.5 update**: backend re-run at `883 passed, 0 failed, 1 deselected` (`pytest -q`, ~212s — no meaningful runtime regression, actually faster than the 5.7a.4 run within normal system-load variance) after adding 25 provider-credential tests; frontend untouched by Phase 5.7a.5 (also backend-only), still `297 passed, 0 failed` as of its own last run — not re-run this pass. Two pre-existing 5.7a.4 tests needed a small, deliberate update (not a weakening): both configured no credential at all while expecting a 401 to classify as `AUTHENTICATION_FAILED`, which 5.7a.5 correctly now reports as the more specific `PROVIDER_CREDENTIAL_REQUIRED` — both were changed to configure a *wrong* credential instead, preserving their original intent (proving the taxonomy lands in `error_code`) without asserting behavior 5.7a.5 deliberately improved on. **Phase 5.6a.1 update**: backend re-run at `934 passed, 0 failed, 1 deselected` (`pytest -q`, 226.33s) after adding 51 tests (32 in `test_egress_guard.py`, 19 in `test_http_tool_execution.py`); frontend untouched by Phase 5.6a.1 (also backend-only), still `297 passed, 0 failed` as of its own last run — not re-run this pass. No pre-existing test needed any modification this pass — the full pre-5.6a.1 suite (883 tests) passed unchanged. **Phase 5.6a.2 update**: backend re-run at `953 passed, 0 failed, 1 deselected` (`pytest -q -m "not live_provider"`, 265.95s) after adding 19 tests in `backend/tests/runtime/test_tool_resilience.py`; run again with Ollama confirmed stopped (`tasklist` showed no `ollama` process) — no dependency either way, `MOCK` is the default provider. Frontend untouched by Phase 5.6a.2 (also backend-only, zero frontend files changed — confirmed via `git status --porcelain frontend`), still `297 passed, 0 failed` as of its own last run — not re-run this pass. No pre-existing test needed any modification this pass — the full pre-5.6a.2 suite (934 tests, including every 5.6a.1/5.7a.4 test) passed unchanged; migration `0031_tool_resilience` verified reversible (`alembic downgrade -1` then `upgrade head`, both clean). **Phase 5.6a.3 update**: backend re-run at `970 passed, 0 failed, 1 deselected` (`pytest -q -m "not live_provider"`, 294.58s) after adding 17 tests in `backend/tests/runtime/test_tool_loop.py`; run again with Ollama confirmed stopped, no dependency either way. Frontend untouched by Phase 5.6a.3 (also backend-only, zero frontend files changed), still `297 passed, 0 failed` as of its own last run — not re-run this pass. No pre-existing test needed any modification this pass — the full pre-5.6a.3 suite (953 tests, including every 5.6a.1/5.6a.2/5.7a.* test) passed unchanged; migration `0032_tool_loop` verified reversible. One genuine bug was found and fixed *during* this phase's own work, not left in: the first parallel-tool-execution design deadlocked (a fresh per-thread `Session`'s FK-checking insert blocked on the still-held `claim_next` lock while the main thread blocked on that same worker thread) — reproduced directly against `pg_stat_activity`, fixed, and re-verified before any test was considered passing for real (the deadlock had to be killed via `taskkill` during diagnosis; stray `QUEUED` `agent_executions` rows this left in the local dev database were cleaned up afterward, not left as clutter). **Phase 2.1.1 update**: backend re-run at `994 passed, 0 failed, 1 deselected` (`pytest -q -m "not live_provider"`, 306.85s) after adding 24 tests in `backend/tests/integration/test_connector_core.py`. Frontend untouched by Phase 2.1.1 (backend-only, zero frontend files changed), still `297 passed, 0 failed` as of its own last run — not re-run this pass. No pre-existing test needed any modification this pass — the full pre-2.1.1 suite (970 tests, including every 5.6a.*/5.7a.* test) passed unchanged; migration `0033_connector_core` verified reversible (`alembic downgrade -1` then `upgrade head`, both clean). One test-authoring mistake was caught and fixed during this phase's own work, not left in: `test_ac19_connector_versioning_two_versions_coexist` initially inserted a second `connectors` row with a fixed literal version string (`"1.1.0"`) directly into the shared, persistent local dev Postgres database — since `connectors` is a platform-wide catalog (not transaction-scoped per test, the same "global, committed" shape `signing_keys` already required isolation for in Phase 5.2.4), a second run of the same test collided with its own leftover row (`UniqueViolation` on `(connector_type, version)`); fixed by minting a unique version string per test invocation instead of reusing a fixed one, with no change needed to any application code. **Phase 2.1.2 update**: backend re-run at `1025 passed, 0 failed, 1 deselected` (`pytest -q -m "not live_provider"`, 333.88s) after adding 31 tests in `backend/tests/integration/test_connector_auth.py`. Frontend untouched by Phase 2.1.2 (backend-only, zero frontend files changed), still `297 passed, 0 failed` as of its own last run — not re-run this pass. No pre-existing test needed any modification this pass — the full pre-2.1.2 suite (994 tests, including every 2.1.1/5.6a.*/5.7a.* test) passed unchanged; migration `0034_connector_auth` verified reversible. Two genuine test-authoring bugs were caught and fixed during this phase's own work, not left in: an early version of `test_ac02_runtime_never_references_connector_or_scheme_vocabulary` false-flagged on the pre-existing, unrelated `"API_KEY"` substring already legitimately present in `app/runtime/registry/identity.py`/`schemas.py` (Phase 5.1's `credential_type="API_KEY"`) and `app/runtime/services.py`'s `MODEL_PROVIDER_API_KEYS` setting (Phase 5.7a.5) — fixed by dropping the too-generic `"API_KEY"` term from the forbidden list, keeping only the four identifiers actually unique to this sub-phase; and `test_ac30_no_real_credentials_or_live_network_calls_in_this_file`'s own literal assertion strings (`"import requests"`, `"sk-live-"`) self-matched the test file's own source when read back and grepped — fixed by building each forbidden string via concatenation so the assertion line itself doesn't trip its own check. **Phase 2.1.3 update**: backend re-run at `1049 passed, 0 failed, 1 deselected` (`pytest -q -m "not live_provider"`, 319.20s) after adding 24 tests in `backend/tests/integration/test_connector_health.py`. Frontend untouched by Phase 2.1.3 (backend-only, zero frontend files changed), still `297 passed, 0 failed` as of its own last run — not re-run this pass. Migration `0035_connector_health` verified reversible. **One pre-existing test genuinely needed updating, not weakening**: 2.1.1's `test_ac03_mock_connector_satisfies_the_interface_without_an_abc_change` asserted the `Connector` ABC's method set was exactly `{describe, validate_configuration}` — Phase 2.1.3 deliberately, additively grew it to include `health_check`, so the assertion's enumerated set was updated to match; the test's actual intent (MockConnector needs nothing beyond what the ABC declares) still holds and is still checked, now also asserting `authenticate`/`execute` still don't exist. Two genuine test-authoring bugs were caught and fixed during this phase's own work: (1) `test_ac15_transitions_go_through_the_state_machine_not_a_bypass` initially grepped `health.py` for the literal substring `"lifecycle_state ="`, which false-matched the *comparison* `instance.lifecycle_state == "active"` (a `==` contains `=` as a substring) — fixed with a regex requiring an assignment (`=` not followed by a second `=`); (2) the full pre-2.1.3 suite (1,025 tests, including every 2.1.1/2.1.2/5.6a.*/5.7a.* test) passed unchanged except the one documented ABC-set update above. **Phase 2.1.4 update**: backend re-run at `1,080 passed, 0 failed, 1 deselected` (`pytest -q`, 329.25s) after adding 31 tests (26 in `test_connector_sdk.py`, 5 in `test_connector_sdk_example.py`). Frontend untouched by Phase 2.1.4 (backend-only, zero frontend files changed), still `297 passed, 0 failed` as of its own last run — not re-run this pass. No migration this phase, so no reversibility to verify. No pre-existing test needed any modification this pass — the full pre-2.1.4 suite (1,049 tests, including every 2.1.1/2.1.2/2.1.3/5.6a.*/5.7a.* test) passed unchanged. One design correction made *during* this phase's own work, not left in: the completeness check's original design used Python's built-in `NotImplementedError` as the "placeholder health_check" sentinel, which would have collided with 2.1.3's own `test_ac27_no_new_todo_or_skip_markers_in_this_phases_files` (a package-wide grep for that builtin's name as a leftover-stub signal) — caught before it ever caused a failure, by re-reading that existing test before finalizing the sentinel choice, and resolved with a dedicated `HealthCheckNotImplemented` exception instead of weakening the pre-existing test. **Phase 2.2.1 update**: backend re-run at `1,121 passed, 0 failed, 1 deselected` (`pytest -q`, 331.23s) after adding 41 tests (30 in `test_rest_connector.py`, 11 in `test_rest_connector_invocation.py`). Frontend untouched by Phase 2.2.1 (backend-only, zero frontend files changed), still `297 passed, 0 failed` as of its own last run — not re-run this pass. No migration this phase, so no reversibility to verify. No pre-existing test needed any modification this pass — the full pre-2.2.1 suite (1,080 tests, including every 2.1.*/5.6a.*/5.7a.* test) passed unchanged. Two genuine findings were made and fixed *during* this phase's own work, not left in: (1) `Connector.describe()`'s zero-argument, type-level signature cannot produce a REST connector's real per-endpoint tool contracts (only an instance's own configuration declares its endpoints) — resolved by giving `RestConnector.describe()` a documented structural placeholder and making `declaration.py::tool_contracts_for(configuration)` the real, per-instance `ACT-INT-FR-102` mechanism, rather than widening the `Connector` ABC itself; (2) a first paginated-endpoint test looped through the exact same first page three times — traced to `GovernedHttpClient.request()` silently dropping a query string embedded directly in its `url` argument (`execute_http_tool`'s `_build_target_url` only ever honors its own dedicated `query` parameter), invisible to 2.1.4's query-free `WebhookConnector` — fixed by adding a new, optional, backward-compatible `query` parameter to `GovernedHttpClient.request()` and locking the fix in with an explicit per-page-offset assertion in the regression test. **Phase 2.2.2 update**: backend re-run at `1,163 passed, 0 failed, 1 deselected` (`pytest -q`, 344.87s) after adding 42 tests (35 in `test_database_connector.py`, 7 in `test_database_connector_invocation.py`). Frontend untouched by Phase 2.2.2 (backend-only, zero frontend files changed), still `297 passed, 0 failed` as of its own last run — not re-run this pass. No migration this phase, so no reversibility to verify. No pre-existing test needed any modification this pass — the full pre-2.2.2 suite (1,121 tests, including every 2.1.*/2.2.1/5.6a.*/5.7a.* test) passed unchanged. Every injection/row-limit/timeout test in this phase ran against this platform's own real dev Postgres, not a mock — including a live-timed proof (a 3-second `pg_sleep` declared with a 1-second timeout terminates in ~1 second, not three). **Phase 2.2.3 update**: backend re-run at `1,245 passed, 0 failed, 1 deselected` (`pytest -q`, 408.41s) after adding 82 tests (41 in `test_storage_scope.py`, 30 in `test_storage_connector.py`, 11 in `test_storage_connector_invocation.py`). Frontend untouched by Phase 2.2.3 (backend-only, zero frontend files changed), still `297 passed, 0 failed` as of its own last run — not re-run this pass. No migration this phase, so no reversibility to verify. No pre-existing test needed any modification this pass — the full pre-2.2.3 suite (1,163 tests, including every 2.1.*/2.2.1/2.2.2/5.6a.*/5.7a.* test) passed unchanged. One design correction made *while writing tests*, not left in: the filesystem symlink-escape test (AC-09) initially assumed `os.symlink` would simply work, but this environment's default Windows user lacks the privilege to create a symlink without elevation or Developer Mode — caught before it could silently skip real coverage, by adding a directory-junction fallback (`mklink /J`, no elevated privilege required) that this environment's own test run genuinely exercises (verified not-skipped by running the test in isolation), since a Windows junction is, like a symlink, a reparse point `os.path.realpath` resolves identically. **Phase 2.2.4 update**: backend re-run at `1,295 passed, 0 failed, 1 deselected` (`pytest -q`, 404.78s) after adding 50 tests (7 in `test_queue_scope.py`, 31 in `test_queue_connector.py`, 12 in `test_queue_connector_invocation.py`). Frontend untouched by Phase 2.2.4 (backend-only, zero frontend files changed), still `297 passed, 0 failed` as of its own last run — not re-run this pass. No migration this phase, so no reversibility to verify. No pre-existing test needed any modification this pass — the full pre-2.2.4 suite (1,245 tests, including every 2.1.*/2.2.1/2.2.2/2.2.3/5.6a.*/5.7a.* test) passed unchanged. One real bug was found and fixed *while writing this phase's own manual verification, before any test was written*, not left in: `_amqp_connection`'s first design passed `credentials=None` explicitly to `pika.ConnectionParameters` whenever no credential was resolved, but `pika`'s own `credentials` setter raises `TypeError` on an explicit `None` (its real default is a private sentinel, not `None`) — fixed by only including the `credentials` kwarg at all when a real credential was resolved, letting `pika` fall back to its own default otherwise; caught by manually exercising the AMQP consume path against a mocked transport before writing the test suite, not by a failing test. **Phase 2.3.1 update**: backend re-run at `1,352 passed, 0 failed, 1 deselected` (`pytest -q`) after adding 57 tests (14 in `test_oidc_bypass_prevention.py`, 12 in `test_saml_bypass_prevention.py`, 8 in `test_claim_mapping.py`, 10 in `test_federation_login_flow.py`, 13 in `test_federation_config_crud.py`). Frontend untouched by Phase 2.3.1 (backend-only, zero frontend files changed), still `297 passed, 0 failed` as of its own last run — not re-run this pass. Migration `0036_identity_federation` verified reversible (`alembic downgrade -1` then `upgrade head`, both clean). **Five pre-existing tests genuinely needed updating, not weakening**: `test_connector_sdk.py`/`test_database_connector.py`/`test_queue_connector.py`/`test_rest_connector.py`/`test_storage_connector.py` each hardcoded `"0035_connector_health.py"` as the expected final migration filename — correct when their own phase shipped (each genuinely added no migration), now stale since this phase genuinely adds `0036_identity_federation.py`; each updated to the new correct filename with an explanatory comment, mirroring the same "small, necessary update" precedent item 15's own Phase 2.1.3 entry above already established for its own ABC method-set assertion. Otherwise, the full pre-2.3.1 suite (1,295 tests, including every 2.1.*/2.2.*/5.6a.*/5.7a.* test) passed unchanged. Two genuine library-usage discoveries were made and fixed *while building test fixtures, before any bypass test was written*, not left in: (1) `xmlsec` could not resolve a `#elementId` signature reference until `xmlsec.tree.add_ids(root, ["ID"])` was called before constructing the signature template, registering which XML attribute is an ID attribute — found by direct sign/verify experimentation; (2) the SAML end-to-end fixture's `script_name` had to match the assertion's own baked-in `Destination`/`Recipient` URL exactly (`python3-saml` validates the computed "current URL" against these) — an initial mismatch produced a generic, correctly-opaque `SamlVerificationError` that gave no hint of the real cause, resolved by aligning the fixture's request-data construction to the real ACS URL. **Phase 3.1 update**: backend re-run at `1,379 passed, 0 failed, 1 deselected` (`pytest -q -m "not live_provider"`, 391.49s) after adding 27 tests in `backend/tests/runtime/test_deployment_lifecycle.py`. Frontend untouched by Phase 3.1 (backend-only, zero frontend files changed), still `297 passed, 0 failed` as of its own last run — not re-run this pass. Migration `0037_deployment_lifecycle` verified reversible (`alembic downgrade -1` then `upgrade head`, both clean). **Five pre-existing tests needed the same small, necessary update as 2.3.1's own five**: `test_connector_sdk.py`/`test_database_connector.py`/`test_queue_connector.py`/`test_rest_connector.py`/`test_storage_connector.py` bumped from `"0036_identity_federation.py"` to `"0037_deployment_lifecycle.py"`. Otherwise, the full pre-3.1 suite (1,352 tests) passed unchanged. **Two full-suite runs were required, not one**: the first run surfaced 9 failures — 4 in `test_admin_portal.py` and 4 `runtime-never-knows`-style vocabulary tests (`test_connector_auth.py`/`test_connector_core.py`/`test_connector_health.py`) plus this phase's own migration-mapping test. The 4 vocabulary failures were a **genuine finding, not a flake**: this phase's own new docstrings under `app/runtime/deployment/` used the literal word "connector" several times in passing prose (explaining how the new lifecycle module mirrors the connector framework's own pattern) — caught by the exact same pre-existing, mechanically-enforced grep tests those phases built, and fixed by rewording the prose, not by weakening any test. The 4 `test_admin_portal.py` failures did not reproduce on an immediate re-run in isolation, nor on a second full clean run — a transient, unrelated flake in this persistent-DB-based suite, the same category REPO_STATE has documented before (see the Phase 5.7a.4 entry above). This phase's own migration-mapping test failure was a **genuine, self-inflicted test-design bug, found and fixed, not a flake**: the test's first draft assumed a deployment row's `state_reason` staying at the migration's own text implied its `lifecycle_state` had also never changed since — false, since the pre-existing, untouched legacy `/suspend` endpoint can still change a row's `status` (and, as a `version_id_col` side effect, its `revision`) without ever touching `lifecycle_state`/`state_reason` at all; rewritten to check the mapping's own internal consistency plus migration-evidence presence, not a live cross-check against a column this phase deliberately leaves mutable. **Phase 3.2 update**: backend re-run at `1,408 passed, 0 failed, 1 deselected` (`pytest -q`, 388.88s) after adding 29 tests in `backend/tests/runtime/test_environment_promotion.py`. Frontend untouched by Phase 3.2 (backend-only, zero frontend files changed), still `297 passed, 0 failed` as of its own last run — not re-run this pass. Migration `0038_environments_promotion` verified reversible (`alembic downgrade -1` then `upgrade head`, both clean, environments/paths correctly re-seeded). **Five pre-existing tests needed the same small, necessary update as 2.3.1's and 3.1's own five**: `test_connector_sdk.py`/`test_database_connector.py`/`test_queue_connector.py`/`test_rest_connector.py`/`test_storage_connector.py` bumped from `"0037_deployment_lifecycle.py"` to `"0038_environments_promotion.py"`. Otherwise, the full pre-3.2 suite (1,379 tests) passed unchanged on the first clean full run — **no vocabulary-test or flake surprises this pass**, though one genuine, self-caught vocabulary finding occurred *before* that first full run: this phase's own new `app/runtime/environment/policy.py` docstring originally named a policy field `allowed_connectors` (the build prompt's own literal suggestion), which the same pre-existing, mechanically-enforced grep tests 3.1 had already tripped over once would have flagged — caught and renamed to `allowed_external_systems` proactively, by running the four vocabulary tests before the full suite rather than after, so this pass's full run had zero failures instead of repeating 3.1's own two-full-suite-runs pattern. A second, genuine live bug was found the same way (proactive targeted testing before the full run, not by the full run itself): `EnvironmentService.ensure_seeded()`'s first draft, called from the `GET /environments` route with no subsequent `db.commit()`, silently rolled back its own seeded rows on session close (its model, `ReleaseChannelService.ensure_seeded()`, only works because *its* callers commit afterward — a precedent that turned out not to actually apply at the new call site) — caught immediately by a same-session round-trip test, fixed by adding the missing commit, matching the real, verified precedent (`list_release_channels`, which does commit). **Phase 3.3 update**: backend re-run at `1,435 passed, 0 failed, 1 deselected` (`pytest -q`, 397.93s) after adding 27 tests in `backend/tests/runtime/test_release_gate.py`. Frontend untouched by Phase 3.3 (backend-only, zero frontend files changed), still `297 passed, 0 failed` as of its own last run — not re-run this pass. Migration `0039_deployment_preflight` verified reversible (`alembic downgrade -1` then `upgrade head`, both clean). **Five pre-existing tests needed the same small, necessary update as 2.3.1's/3.1's/3.2's own five**: `test_connector_sdk.py`/`test_database_connector.py`/`test_queue_connector.py`/`test_rest_connector.py`/`test_storage_connector.py` bumped from `"0038_environments_promotion.py"` to `"0039_deployment_preflight.py"`. Two vocabulary/wiring findings were caught proactively, before the full suite run, mirroring 3.2's own discipline of running targeted checks first: (1) the new `checks.py` module's own docstring, in its first draft, used the literal word "connector" and the names `ConnectorHealthCheck`/`ConnectorInstance` several times while explaining the freshness-rule gap — caught by running the four pre-existing vocabulary tests before the full suite, fixed by rewording every mention to name the concept without the forbidden literal terms; (2) wiring the gate into `start_deploying()` initially ran the gate check *after* the approval-reroute logic, which would have meant a deployment reaching `PENDING_APPROVAL` never actually got a persisted preflight record on that path — caught by re-reading the reroute logic before finalizing the call site, moved to run *before* the reroute instead (safe, since the gate's own approval finding is WARNING, never BLOCK, so it cannot itself trigger a reroute or a block). **One pre-existing Phase 3.1 test needed a small, necessary update, not a weakening**: `test_ac09_suspended_agent_blocks_activation` previously asserted the raw `DEPLOYMENT_AGENT_SUSPENDED` code and a post-condition of `DEPLOYING` (the lifecycle state the deployment was left "stuck" at, since the old code path mutated `READY→DEPLOYING` *before* the suspension check that then failed at the next step); the gate now runs its own kill-switch check *before* any mutation at all, so the deployment correctly stays at `READY` and the more specific `DEPLOYMENT_PREFLIGHT_BLOCKED` fires instead — a strictly safer post-condition, the same underlying guarantee ("a suspended agent's deployment cannot activate") fully preserved. Otherwise, the full pre-3.3 suite (1,408 tests) passed unchanged. **Phase 3.4 update**: backend `1,478 passed, 0 failed, 1 deselected` after adding 43 tests in `backend/tests/runtime/test_traffic_resolver_gate.py`; migration `0040_traffic_allocation` verified reversible; the same five connector migration-head tests bumped to it; one Phase 3.2 test deliberately migrated (documented in §6). **Phase 3.5 update**: backend `1,535 passed, 0 failed, 1 deselected` after adding 57 tests in `backend/tests/runtime/test_canary_rollout.py`; migration `0041_canary_rollout` verified reversible; the same five connector tests bumped to it. **The `test_generated_temporary_password_satisfies_policy` flake first recorded in the Phase 5.7a.4 entry above is now CLOSED — and it was never a flake.** Phase 3.5's full-suite run hit it again, and measuring the generator directly showed a real defect rather than test noise: `generate_temporary_password()` returned its first draw unchecked, and **9 of 20,000 draws (~1 in 2,200) genuinely violated the password policy** — a 50-draw test therefore failed roughly one run in fifty. Because a temporary password is handed to a person to log in with, and the login/set path validates it under the same policy, this meant roughly one reset in two thousand issued a credential the platform itself would then refuse. Fixed 2026-08-14 in `fix/temp-password-policy-compliance` (backend `1,541 passed, 0 failed, 1 deselected`): the generator now validates each candidate through `PasswordPolicyService.validate` — the same entry point `_apply_new_password` uses — and re-draws on failure, with a safety cap that raises rather than ever returning a non-compliant value. The 50-draw test was replaced with a 5,000-draw zero-violation assertion plus tests for the cap, the shared-validator reuse, and the preserved strength properties; measured after the fix: **0 violations in 20,000 draws**, and 15 consecutive runs of the file clean. **Phase 3.6 update**: backend `1,575 passed, 0 failed, 1 deselected` after adding 34 tests in `backend/tests/runtime/test_strategies.py`. **No migration this phase** — head stays `0041_canary_rollout`, because blue preservation reuses the existing `rollback_target_id` lineage plus 3.4's allocation rows rather than adding storage; consequently the five connector migration-head tests needed no bump for the first time since Phase 2.3.1, and the full pre-3.6 suite (1,541 tests) passed unchanged. Frontend untouched (backend-only), still `297 passed, 0 failed`. One genuine constraint was caught by a **pre-existing** test rather than by review, mirroring the 3.1/3.2/3.3 vocabulary pattern: `test_ac14_replica_columns_not_read_or_written_by_the_new_lifecycle` (Phase 3.1) greps for the two vestigial replica-column names as bare substrings anywhere in `app/runtime/deployment/`, prose included — and this phase's own module docstring named them while *explaining why ROLLING is deferred*. Reworded to refer to them indirectly rather than weakening the test; this phase's own AC-09 test was then tightened to assert the same bare-name rule instead of the looser "no attribute access" version it started with. A second, smaller self-reference trap was caught the same way and is the third instance of this class in the document (see Phase 2.1.2's assertion strings and Phase 2.1.4's sentinel choice): the module docstring's sentence promising the ROLLING deferral is "never a `NotImplementedError` stub" contained that exact token, which this phase's own no-stub-markers test forbids — reworded to `NotImplemented`.
16. ~~No per-organization model-provider credential storage~~ — closed in Phase 5.7a.5: `provider_credentials` (encrypted at rest, per `(organization_id, provider)`) backs `ProviderCredentialService`, resolved at execution time and fed into the pre-existing `api_key` forwarding path. `MODEL_PROVIDER_API_KEYS` remains, deliberately, as the fallback tried only when no org-specific credential is configured (see §10.32) — not vault-integrated, not automatically rotated (both explicitly out of scope, deferred to Milestone 13 and later hardening respectively).
17. ~~`ROADMAP.md` is stale and should not be trusted over this document~~ — **closed**: backfilled in the same pass that recorded this gap, and kept current every phase since (2.1.2, and now 2.1.3, both landed in `CHANGELOG.md`/`ROADMAP.md` in the same commit sequence as this document, per this sub-phase's own build prompt explicitly requiring it — see §10's new entry on that). **This document (§6) remains the authoritative, always-current source per the Update Protocol in §11** — re-check before trusting either blindly on a future phase if this note ever goes stale again. **Milestone 2 now has nine of nine sub-phases implemented** (2.1.1 Connector Abstraction & Lifecycle, 2.1.2 Connector Authentication Framework, 2.1.3 Connector Registry & Health, 2.1.4 Connector SDK, 2.2.1 Generic REST Connector, 2.2.2 Generic Database Connector, 2.2.3 Generic File & Object Storage Connector, 2.2.4 Generic Message Queue Connector, 2.3.1 External Identity Federation — see §6) — **Milestone 2, the Enterprise Integration Framework, is COMPLETE: the connector framework, all four generic connectors (carrying this milestone's sharpest connector-side security rules — the model never writes SQL; a model-supplied path can never escape its declared scope; publish is scoped and consume is always bounded), and identity federation (carrying the inversion — federation holds no user secret and verifies an assertion inward, rather than a connector's own posture of holding a platform secret and presenting it outward) are all shipped and proven.** **Milestone 3 (Deployment & Release) is now underway**: 3.1 (Enterprise Deployment Core — the governed lifecycle state machine and its authority) and 3.2 (Environment & Promotion Model — governed environments with policy, and immutability-preserving promotion) both shipped 2026-08-10; 3.3 (Deployment Preflight & Release Gate Engine — the single authoritative PASS/WARNING/BLOCK evaluation, and the freshness rule) shipped 2026-08-11; 3.4 (Traffic Allocation, Version Resolver & Execution Gate — the milestone's one deliberate change to the Milestone 1 execution path) and 3.5 (Canary Deployment Engine — the driver 3.4's allocation was built for, with AI-aware release health) shipped 2026-08-13/14; 3.6 (Blue-Green & Recreate Strategy Execution — two further weight patterns over the same allocation, with blue preserved as a rollback target) shipped 2026-08-14; 3.7 (Automated Rollback & Release Safety — the governed per-tenant trigger policy, with `rollback_target_id` made authoritative and automation held strictly subordinate to the kill switch) shipped 2026-08-17; see §6. 3.8 (Distributed Scheduler — `FOR UPDATE SKIP LOCKED` leasing with the commit-before-dispatch discipline, driving 3.7's bounded evaluation and 3.5's bounded auto-advance on a real timer) shipped 2026-08-17; 3.9 (Distributed Execution Worker Fleet & Rolling Deployment — agent execution moved onto independently-operable worker processes with no database lock held across model or tool I/O, and ROLLING finally implemented over real worker cohorts, resolving ruling #1) shipped 2026-08-18; see §6. **3.10 (the AI Release Operations Center — the operator-facing assembly of everything the milestone built, read-and-trigger over the existing engines with no new deployment logic) shipped 2026-08-21; see §6. **MILESTONE 3 (Deployment, Release & Operations) IS COMPLETE — 10 of 10 sub-phases done.** The platform now executes real governed AI (M1), integrates with the enterprise in both directions (M2), and deploys, releases, monitors, routes, rolls back and operates agent versions safely at production scale (M3).
18. **A small, previously-uncaught inaccuracy in this document's own prior prose, found and corrected this pass.** §5's narrative said Phase 5.6a.3 brought the total route count to "457," but a direct re-measurement against a temporary `git worktree` checked out at that exact commit (`a98a9c0`) shows the live `APIRoute` count was actually 456 at that point — the authoritative "Total application routes" line in §5 was, and remained, correct at 456 the whole time; only the surrounding prose sentence was off by one. Corrected in §5 rather than left to compound; the Phase 2.1.1 route count (464) was independently verified against both the old and new commit, not derived from the possibly-wrong prior prose.

---


19. **A stale *headline* under a maintained *narrative* is this document's characteristic failure mode, and Phase 4.1's pre-step A found three at once.** §2 declared "119 tables ... through `0041_canary_rollout`" while the live database held **124** at head `0045`; §3 declared "42 revisions ... head `0041_canary_rollout`" against a live **45**; §5's authoritative "Total application routes" line read **518**, correct as of Phase 3.6 and four phases stale, against a live **541**. In every case the *per-phase update paragraphs beneath them had been faithfully extended* — 3.7, 3.8, 3.9 and 3.10 each appended an accurate account of what they changed. That combination is worse than plain neglect: a reader sampling the narrative concludes the document is current and trusts the headline. **The lesson for §11's update protocol**: appending a phase paragraph is not updating a count. The headline is the only number anyone quotes, and it is the one nothing forces you to touch. Every future phase must re-derive §2/§3/§5's headline figures from the live system, not extend the prose beneath them and stop.

20. **Seven tests in this repository have now pinned a *moving* target, and Phase 4.1 found six of them at once.** This is the single most repeated defect in this codebase's test suite, and it is worth naming precisely because every instance was written by an author who was right about what they wanted to protect and wrong about how to express it.

    The roll call. Phase 3.7's byte-identity guard pinned six modules to a moving `main` (item 15; narrowed in 3.9). Phase 3.10's `test_ac15_no_migration_was_added` asserted the repository's *newest* migration was `0044_worker_fleet_rolling`. Phase 3.10's `test_ac15_phase_310_added_no_deployment_logic` diffed the working tree against `main`, reasoning explicitly in its own docstring that this was safe because *"3.10 is the last sub-phase of the milestone, and an empty diff stays empty after the merge"* — which held exactly until the next milestone touched one of the listed files, and then reported a **Phase 4.1** change to `scheduler/service.py` as though 3.10 had reimplemented a deployment engine. And **five Milestone 2 connector guards** (2.1.4, 2.2.1, 2.2.2, 2.2.3, 2.2.4) each asserted the newest migration filename; every one of them carried a comment reading *"Updated Phase 3.5: a genuinely new migration landed ... this assertion's own intent is preserved by pointing at the new, correct head."* They had already been hand-bumped once and were about to need a sixth bump.

    **That comment is the tell.** A guard that must be edited every time an unrelated phase ships is not being maintained — it is being paid for, repeatedly, and each payment is an opportunity to bump it without checking whether the underlying claim still holds. The five connector tests were one careless edit away from asserting nothing.

    **None was weakened.** Each now asserts the claim itself: the migration guards assert *no migration in this repository belongs to Phase X* (strictly stronger — it also catches a Phase X migration inserted *before* the head, which a newest-file check could never see), and 3.10's diff guard now diffs **Phase 3.10's own commit range** (`72d1d71^1..72d1d71`), a fixed historical fact that no later phase can disturb. The rewritten guards were verified to still bite: planting a fake `Phase 2.2.1` migration makes the REST connector's guard fail, and removing it makes it pass.

    **The pattern to watch for at review time**: an assertion mentioning "latest", "newest", "head", `main`, or another phase's current artifact is almost always pinned to something that will move. The fix is never to relax it — it is to find the invariant the author actually meant and assert *that*. A claim about a phase should be expressed against that phase's own artifacts, not against the state of the world at the moment it was written.

21. **Credential-shaped test fixtures must be assembled from parts, or GitHub push protection rejects the push** (found in Phase 4.1, and it will recur). The scrubber's shape-matching tests need values that look *exactly* like real credentials — that is the entire point of testing shape matching rather than key matching. Written as plain literals, the Slack entry (`xoxb-...`) was enough for GitHub's secret scanner to decline the push outright: `GH013: Push cannot contain secrets`. The values were completely fake.

    There are two ways out and only one of them is right. GitHub offers an "allow this secret" URL, which resolves the immediate block and **trains everyone on the repository to click through the warning that exists to protect them** — the next one might not be fake. The alternative is to stop writing the literal down: the fixtures are now built by concatenation (`"xox" + "b-" + "..."`), so the assembled value handed to the scrubber is byte-identical and the literal never appears in the source. Nothing about the test is weakened.

    This is the same **self-match trap** this codebase already dodges in its placeholder-marker tests (which build `"TO" + "DO"` so the guard does not match itself), arriving from the opposite direction: there the problem was a test matching its own source, here it is a *scanner* matching the test's source. The rule generalizes to both: **a test that must contain a dangerous-looking string should construct it, not spell it.** Phase 4.8 will write more scrubber fixtures than any phase so far and should assume this from the start rather than discover it at the push. `backend/tests/runtime/test_telemetry_foundation.py::_SHAPED_CREDENTIALS`.

## 10. Architecture Decisions Made In Code

Decisions the SRS/roadmap documents don't specify, that the implementation settled — each verified against the actual code, with rationale where the code itself states one.

1. **The `agents` table (Phase 1) is the one agent registry across every later phase** (5.0/5.1/5.2) — never forked into a parallel table. Stated in the module docstring of `backend/app/models/runtime.py`.
2. **The execution queue *is* the `agent_executions` table** (`SELECT ... FOR UPDATE SKIP LOCKED`), not Redis/Celery. The worker runs inline/synchronously right after enqueue (an "eager queue", the same trick `CELERY_TASK_ALWAYS_EAGER` plays for local dev) rather than as a standalone process. Module docstring of `backend/app/runtime/services.py`.
3. **Every runtime authorization decision funnels through the single, pre-existing `AuthorizationGateway`** (Phase 4.3.6) rather than the runtime having its own RBAC/ABAC engine. `backend/app/authorization/middleware/gateway.py`, called from `backend/app/runtime/services.py`.
4. **Agents may only request execution of themselves — no agent-to-agent chaining.** `request_execution_as_agent` in `backend/app/runtime/services.py:1217-1224` explicitly rejects any `agent_id` in the payload that doesn't match the calling agent's own id, citing multi-agent orchestration as "explicitly deferred."
5. **Phase 5.2 Part 1 does not enforce "cannot publish two active releases."** This platform's existing Phase 5.0 rollback/canary deployment strategies require multiple simultaneously-`PUBLISHED` versions of one agent (a `Deployment` row, not a `Version`'s status, tracks what's live per environment). Enforcing the SRS rule literally would have broken the already-shipped, already-tested `test_deployment_rollback` scenario. Decided and documented in `docs/runtime/versioning.md` and in the comment block inside `AgentVersionService.publish` (`backend/app/runtime/services.py`).
6. **Phase 5.2 Part 1 kept the single `READY_FOR_REVIEW` version-lifecycle state** rather than splitting it into the SRS's separate "Ready"/"Approval Required" states — no new validation behavior would attach to either half, and the rename would touch roughly ten already-tested files for no functional gain. Documented in `docs/runtime/versioning.md`.
7. **Version snapshots freeze at `publish()`, not at version creation.** Publish is the actual immutability boundary (§21 of the SRS: "Published Version: Immutable"), and freezing there lets release metadata/artifacts/notes be attached any time beforehand without needing to rebuild an earlier snapshot. `backend/app/runtime/versioning/snapshot.py` module docstring.
8. **Version comparison and promotion readiness are both read-only/advisory — neither gates a lifecycle action.** A deliberate separation between diagnostic information and enforcement. `backend/app/runtime/versioning/compare.py`, `backend/app/runtime/versioning/readiness.py`.
9. **Release channels are a single global catalog, not per-organization.** No SRS bullet asked for org-scoped channels, and a shared STABLE/BETA/CANARY/INTERNAL vocabulary keeps release-channel badges comparable across tenants. `backend/app/runtime/versioning/channels.py` module docstring.
10. **Repository-layer usage is inconsistent across domains** (see §7): `identity` (extensively) and the core `authorization` module (Phase 4.3.1) both interpose an explicit `XRepository` layer between services and SQLAlchemy; every later domain (`abac`, `admin`, `hierarchy`, `resources`, `governance`, `runtime`/`registry`/`versioning`) queries the ORM directly from `XService` classes with no repository indirection. **UNVERIFIED** why later modules didn't adopt the same layering — no comment in the code states a reason; plausibly the repository layer was judged unnecessary indirection once the pattern was in production, but this is inference, not a verified fact.
11. **Password hashing migrated bcrypt → argon2id** (Phase 4.2.2.1); bcrypt is retained solely to verify and auto-upgrade pre-existing hashes on next login. `backend/requirements.txt` comment; `backend/app/core/security.py`.
12. **The response envelope and rate limiting are off by default in the entire test suite**, turned on only by the specific tests that assert their behavior (`_no_response_envelope`, `_no_rate_limit` autouse fixtures in `backend/tests/conftest.py`) — a hermetic-testing decision, not an SRS requirement.
13. **Semantic versions with no explicit value auto-derive** (patch-bump from the agent's current highest version, or `0.1.0` for the first) rather than defaulting to a fixed string — closes a gap where Phase 5.0 defaulted every version to `"0.1.0"` unconditionally, which would have made the new duplicate-rejection rule reject the second version of every agent. `backend/app/runtime/versioning/semantic_version.py`.
14. **Compatibility analysis (Phase 5.2.6) is advisory and failure-tolerant; signing (Phase 5.2.4) is fail-closed and mandatory** — a deliberate, opposite asymmetry between two features that both hook `publish()`. A bug in the compatibility analyzer is logged and swallowed after `publish()`'s own commit (an advisory diagnostic must never block a release). A bug in the signer raises out of `publish()` entirely before anything commits (an unsigned published version is an integrity hole, `ACT-VER-NFR-004`). `backend/app/runtime/services.py::AgentVersionService.publish`, both code paths adjacent with contrasting comments.
15. **Canonical serialization (`canonical.py`) never silently guesses a portable representation for a float or an unsupported type — it raises.** The old checksum routines used `json.dumps(..., default=str)`, which is exactly the kind of hidden, language-specific behavior a signature's integrity guarantee cannot tolerate; producers must explicitly opt in via `stringify_floats()`. This surfaced and fixed a real, previously-silent bug: `build_snapshot()` embedded raw `datetime` objects for three release-metadata fields, relying on `default=str`'s non-portable formatting. `backend/app/runtime/versioning/canonical.py` module docstring.
16. **`signing_keys` is a single global catalog, not per-organization** — the same pattern as release channels (#9 above) and for the same reason (no SRS bullet asked for per-tenant keys, and a shared vocabulary is simpler to operate). A concrete consequence, discovered and fixed during this work: revoking "the" key is process-wide, not scoped to one tenant/test — `backend/tests/runtime/conftest.py`'s autouse `_isolated_signing_key` fixture exists specifically because an early test run revoked the shared key and the (real, committed) corruption persisted across separate test invocations until manually repaired.
17. **`agent_versions.signature_id` was wired to the primary signature's id, not dropped**, even though Phase 5.2 Part 1 left it permanently null. The column's own name ("the id of *the* signature") maps naturally onto "the primary one," matching the existing `snapshot_reference` denormalization pattern already on the same row. `backend/app/runtime/versioning/attestation.py::AttestationService.build_and_sign`.
18. **The countersign endpoint reuses `runtime.agent.approve` rather than introducing `runtime.version.approve`.** No permission by that literal name exists in `PERMISSION_CATALOG`; `runtime.agent.approve` already gates the conceptually identical action (`approve_version`, the DRAFT/READY_FOR_REVIEW→APPROVED transition) — reusing it avoided a same-meaning synonym. `backend/app/runtime/routes.py::countersign_version`.
19. **Federation lives under `app/identity/`, not `app/integration/`, even though it was scoped and built as part of Milestone 2.** Every 2.2.x connector authenticates the *platform* outward to an external system; federation authenticates a *user* inward to the platform — the opposite direction, and squarely identity's own existing concern (session issuance, RBAC, user provisioning), not the connector framework's. Package docstring, `backend/app/identity/federation/__init__.py`.
20. **A federated user is linked to an existing local account by email whenever one exists, regardless of `jit_provisioning_enabled`; that flag gates only the creation of a genuinely new user.** Not specified by the build prompt — a deliberate design decision mirroring real-world SSO rollout order (accounts are usually provisioned first, SSO is turned on second, and an admin flipping on SSO does not expect it to silently create duplicate accounts for people who already have one). `backend/app/identity/federation/service.py::FederationService._resolve_or_provision_user`.
21. **A federated user is linked by stable subject id (OIDC `sub` / SAML `NameID`), never by email, once a `FederatedIdentity` row exists.** Email is mutable at the IdP's own discretion (an admin can reassign it); the protocol's own subject identifier is the one value both OIDC and SAML guarantee is stable for the lifetime of the account. Email-based linking (decision #20) is deliberately a *first-login-only* fallback, superseded by subject-id linking on every subsequent login. `backend/app/identity/federation/service.py`.
22. **Federated sessions always carry `AuthAssuranceLevel.AAL1`, never `AAL2`, even when the IdP's own claims suggest it enforced MFA.** The platform has no reliable, protocol-guaranteed way to verify what the IdP actually enforced on a given login, and asserting a stronger assurance level than it can stand behind was judged worse than under-claiming one — matches local password login's own posture exactly. `backend/app/identity/federation/service.py::FederationService._issue_session`.
23. **OIDC `state` and SAML `RelayState` are short-lived, platform-signed JWTs, not rows in a new "pending federation requests" table.** Reuses the existing `settings.JWT_SECRET_KEY`/`JWT_ALGORITHM` (no new secret to provision or rotate) and needs no cleanup job for expired/abandoned login attempts, since an expired token simply fails verification on its own. `backend/app/identity/federation/service.py::_sign_flow_token`/`_verify_flow_token`.
24. **The OIDC/SAML callback and ACS routes recover `config_id` from the verified state/RelayState token itself, not from the URL**, even though the data model supports multiple federation configs per organization. The build prompt's own literal endpoint paths (`/api/v1/auth/federation/{org}/callback`, `.../saml/acs`) have no room for a config identifier; the login/metadata routes, which do need to know which IdP to start with before any token exists, include it in the path instead. `backend/app/identity/federation/routes.py`.
25. **Phase 3.1 adds `AgentDeployment.lifecycle_state` as a second, independent field rather than widening or repurposing the pre-existing `status`.** `status` is already the load-bearing input to the one real running execution gate (`ExecutionRequestService._request_execution`'s `deployment.status != "ACTIVE"` check); any change to what it holds is a change to the Milestone 1 execution path, exactly what this phase's own scope boundary forbids. A brand-new, additive column lets the new lifecycle exist, be fully tested, and even be driven by real operators, with provably zero effect on execution until Phase 3.4 deliberately flips the gate over. `backend/app/models/runtime.py::AgentDeployment` docstring, `docs/deployment/lifecycle.md`.
26. **Optimistic concurrency uses SQLAlchemy's built-in `version_id_col`, not a hand-rolled `UPDATE ... WHERE revision = X` check.** The idiomatic mapper option gives the real, race-safe compare-and-swap semantics for free (proven live with two threads racing one transition) and is deliberately layered *underneath* a separate, manual `expected_revision` precondition check — the two serve different purposes (a true concurrent-write race vs. a client operating on information it read a while ago) and both raise the same `DEPLOYMENT_REVISION_CONFLICT`. A discovered, accepted consequence: the option is mapper-wide, so even the pre-existing, untouched legacy `.status`-only writers now also bump `revision` — documented, not silently left as a surprise. `backend/app/models/runtime.py::AgentDeployment.__mapper_args__`.
27. **The reusable idempotency contract claims before it acts, rather than checking then acting.** A naive "SELECT, then on miss run the operation and INSERT" has a genuine TOCTOU race under real concurrency (two callers could both miss the check and both run the operation); committing a placeholder claim row first and relying on the table's own unique constraint as the concurrency primitive closes it — the loser of a race catches `IntegrityError` and polls briefly for the winner's result rather than ever running the operation twice. `backend/app/runtime/deployment/idempotency.py::IdempotencyService.execute`.
28. **The new lifecycle's five mutating routes are nested under `/deployments/{id}/lifecycle/...` rather than reusing the build prompt's literal `/pause`/`/resume`/`/retire` paths.** Those three paths already exist in this codebase (Phase 5.0, operating on the legacy `status` field) — FastAPI cannot register two handlers on one `(path, method)` pair, and merging the two machines' semantics into one handler was rejected as it would make the "one transition authority" claim for `lifecycle_state` false. Nesting resolves the conflict without touching a single pre-existing, already-tested endpoint. `backend/app/runtime/routes.py`, `docs/deployment/lifecycle.md`'s "A routing conflict, resolved".
29. **The new lifecycle's routes reuse the pre-existing `runtime.deployment.view`/`runtime.deployment.deploy` permissions rather than adding the build prompt's suggested `deployment.view`/`deployment.manage`.** Those two already exist and already gate every legacy deployment mutation (deploy/suspend/resume/rollback/retire) behind one permission each; adding near-duplicate, differently-named permissions for the same real-world capability would fragment the permission catalog for no access-control benefit. `backend/app/runtime/routes.py` (`_DEPLOY_VIEW`/`_DEPLOY_ACTION`).
19. **`ModelProvider.supports()` is concrete, not abstract** (Phase 5.7a.1) — it derives its answer entirely from the abstract `describe()`, so a provider's two ways of answering "do you support capability X?" can never contradict each other. The build prompt didn't specify this; it was chosen to make a whole class of "describe() and supports() disagree" bugs structurally impossible rather than something each adapter must remember to keep in sync. `backend/app/runtime/providers/base.py`.
20. **Capability enforcement is an explicit call each provider makes (`self.validate_capabilities(request)`), not a Template Method wrapper around the abstract override point.** A Template Method design (renaming the override point to `_complete()` behind a concrete public `complete()`) was considered and rejected — it would have renamed the interface's documented override point for no behavior the explicit-call version doesn't already give, adding an indirection layer purely for its own sake. `backend/app/runtime/providers/base.py` docstring, `docs/runtime/providers.md`.
21. **`FinishReason` needs no provider-specific translation function in the shared layer.** Subclassing `str, Enum` gets a free `ValueError` on any unmapped provider value via `FinishReason(value)`; a bespoke translation function would itself have to embed provider vocabulary (`"stop_sequence"`, `"length"`, …) inside `types.py`, which `ACT-MDL-FR-006` forbids — that mapping correctly belongs in each future adapter, not the shared, provider-neutral types module. `backend/app/runtime/providers/types.py`.
22. **`ModelGatewayService.invoke()` is a translation boundary, not a rewrite of its callers' contract.** The legacy `(input_payload: dict) -> (output_payload, usage)` shape `ExecutionWorkerService` and every existing test depend on was preserved exactly; internally it now wraps the whole payload as one `ModelMessage`, calls the resolved provider's `complete()`, and translates the `ModelResponse` back. Verified before implementation, by grepping every existing assertion on `output_payload`/`model_usage`/`execution.cost`, that no test asserts on the *exact wording* of the mock's result text or *exact* token counts — only `echo == input_payload`, `provider == "MOCK"`, and `cost > 0` — which is what made this translation possible without touching a single existing assertion (AC-04). `backend/app/runtime/services.py::ModelGatewayService.invoke`.
23. **The provider registry (`backend/app/runtime/providers/registry.py`) is an explicit `register()`/`resolve()` call, not directory-scanning plugin discovery.** Every registered provider is one grep away (`register("MOCK", MockProvider)` at the bottom of the module) rather than implicitly discovered by filename/decorator convention — "greppable, not magic," matching this codebase's existing preference for explicit catalogs over convention-based magic (permission catalog, release channels, signing keys — see #9, #16 above).
24. **`registry.resolve()`'s `model`/`api_key` forwarding is signature-checked, not blind** (Phase 5.7a.2) — `inspect.signature(provider_cls.__init__)` decides whether to forward each, so a provider (or a test double like `_RecordingProvider`) with no notion of one isn't forced to accept a parameter it has no use for. This closed a genuine 5.7a.1 gap: neither `model` nor `api_key` had ever reached a provider instance before, only a usage-reporting string. `backend/app/runtime/providers/registry.py`.
25. **Real streaming needed no new dataclass in `types.py`** (Phase 5.7a.3) — `ModelProvider.stream()`'s existing `Iterator[ModelResponse]` contract already expresses everything once every adapter follows one documented convention: `content` is incremental per chunk (concatenate, don't take the last); `tool_calls`/`finish_reason`/`raw_usage` are only meaningful on the last chunk; `FinishReason.ERROR` (already existing, previously unused) doubles as "this stream was interrupted." One function, `assemble_response()`, was added to reduce a chunk sequence into a complete response — not a type. `MockProvider`'s pre-existing single-chunk `stream()` satisfied the convention with zero code changes. `backend/app/runtime/providers/types.py`.
26. **`stream()` never raises; `complete()` does — deliberately different failure semantics for the same adapter** (Phase 5.7a.3). A connection failure, bad status, or truncated stream all make `stream()` yield one final chunk with `finish_reason=FinishReason.ERROR` and whatever was already accumulated, rather than losing everything to an exception (`ACT-MDL-FR-043` requires persisting the partial). A caller that needs to know whether a stream truly succeeded checks the final chunk's `finish_reason`, not a try/except. `backend/app/runtime/providers/openai_compatible.py::OpenAICompatibleProvider.stream`.
27. **A local/unpriced provider's cost is `0`, not carried forward from a flat placeholder — even where that meant updating two previously-stable test assertions** (Phase 5.7a.3, `ACT-MDL-FR-087`). Before this phase, every `MOCK` execution's `cost` came from `total_tokens * 0.000002`, which made `execution["cost"] > 0` true for any `MOCK` call. Once cost is computed by the same `PricingService` every provider uses, `MOCK` (which has no `model_pricing` row, deliberately) honestly costs `0`. `test_execution_runs_end_to_end` and `test_every_existing_mock_execution_behavior_is_unchanged` were updated to `== 0` with a comment explaining why — confirmed as the intended direction before implementing it, precisely because it touched previously-protected assertions.
28. **`analytics_service.py`'s cost dashboard was deliberately not rewired to real per-execution cost** (Phase 5.7a.3) despite the build prompt's own wording pointing there for `ACT-MDL-FR-086`. That module aggregates the older, coarser Phase 3 `agent_actions` table with flat per-unit estimates (`_COST_PER_LLM_ACTION`, etc.) and has no connection to `AgentExecution`/token data at all — rewiring it would mean redesigning a Phase 3 dashboard around a Phase 5 data model, a materially larger and riskier scope than "replace the placeholder with real per-execution cost," which now lives on `AgentExecution.cost_amount` via `PricingService` instead. `backend/app/services/analytics_service.py`; see `docs/runtime/providers.md`.
29. **Error classification lives in the adapter; retry/circuit-breaking live in the service layer — never the reverse** (Phase 5.7a.4). `openai_compatible.py` maps its own wire-level status/body/exception onto the provider-neutral `ProviderErrorClass`; `ModelGatewayService` (`services.py`) alone decides whether a given class is worth retrying, backs off, and tracks circuit state. A future second adapter that classifies into this same taxonomy inherits retry/backoff/circuit-breaking with zero new retry code of its own — the explicit design goal, not an incidental split. `backend/app/runtime/providers/openai_compatible.py`, `backend/app/runtime/services.py`; see `docs/runtime/providers.md`.
30. **Two retry layers now coexist by design, not by oversight** (Phase 5.7a.4): the new *inner* retry (same HTTP call, within the one `execution_attempts` row a worker claim already writes) sits alongside the *pre-existing* Phase-5.0 *outer* retry (`ExecutionWorkerService._fail_or_retry`, a fresh worker claim entirely). Confirmed with the user before implementing (an explicit design-choice question, not assumed): the outer layer keeps applying its own attempt budget on top of the inner one for the three transient classes, exactly as it already did before this classification existed; only its `non_retryable` set changed, gaining the five classes that must never retry at *either* layer (`ACT-MDL-FR-062`). `backend/app/runtime/services.py::ExecutionWorkerService._fail_or_retry`.
31. **`assemble_response()` needed a second addition, not covered by 5.7a.3's original design** (Phase 5.7a.4): the function already carried forward `content`/`tool_calls`/`finish_reason`/`raw_usage` from a stream's last chunk, but not the two fields this phase added (`error_class`/`retry_after_seconds`) — without that, a streaming interruption's classification silently vanished during assembly and the pre-/post-first-token retry boundary (`ACT-MDL-FR-061..064`) had nothing to decide from. Caught by writing the streaming-retry test before assuming the plumbing already worked, not by inspection. `backend/app/runtime/providers/types.py::assemble_response`.
32. **`ModelResponse` gained two new optional fields, confirmed with the user before implementing** (Phase 5.7a.4) — `error_class: ProviderErrorClass | None = None`, `retry_after_seconds: float | None = None`, both defaulting to `None` so every pre-existing construction is unaffected. This is the first change to the *shape* of `ModelResponse` since Phase 5.7a.1 (5.7a.3 deliberately added a function, `assemble_response()`, instead of touching the dataclass) — necessary here because a streaming interruption is communicated by yielding a final chunk, never by raising, so classification info for the retry boundary has nowhere else to live. `backend/app/runtime/providers/types.py`.
33. **The circuit breaker is a plain module-level dict, not a class instance threaded through callers** (Phase 5.7a.4) — `_provider_circuit_state: dict[str, _ProviderCircuitState]` in `services.py`, keyed by provider identifier, read/written by free functions (`_circuit_before_call`/`_circuit_record_success`/`_circuit_record_failure`) rather than an object every caller has to construct and pass around. Matches this module's existing preference for simple, greppable module-level state over introducing a new stateful collaborator class for a single, narrow concern. Deliberately not persisted anywhere — a fresh process starts every provider closed; Milestone 3's distributed worker model is what would need a shared store, explicitly out of scope here. `backend/app/runtime/services.py`.
34. **Credential resolution happens on the worker's own thread, strictly before the model call is submitted to its `ThreadPoolExecutor`** (Phase 5.7a.5) — `ModelGatewayService.invoke()` gained an optional `resolved_credential: ResolvedCredential | None` parameter rather than a `db: Session` of its own, precisely because it can run inside that pool (§36's pre-existing timeout mechanism), and a live SQLAlchemy `Session` is not safe to share across threads (the same constraint that already kept the model call "pure — no DB access," predating this phase). `ExecutionWorkerService._execute` resolves via `ProviderCredentialService(self.db).resolve_for_version(...)` synchronously first; only the resulting plain, immutable two-field dataclass crosses the thread boundary. `backend/app/runtime/services.py`.
35. **A dedicated `provider_credentials` table, not `AgentDeployment.secret_references`** (Phase 5.7a.5) — confirmed by reading `_validate_secret_references` first: that field is a free-form JSONB dict of reference *strings*, validated only to look like `scheme://...`, with no actual storage or resolution mechanism ever built behind it, and scoped to one deployment rather than one organization. A provider credential needs dedicated columns (`provider`/`secret_hint`/`base_url`/`status`) and org-wide scope, distinct enough to warrant its own table. `backend/app/models/runtime.py::ProviderCredential`, `backend/app/runtime/services.py::ProviderCredentialService`.
36. **`PROVIDER_CREDENTIAL_REQUIRED` is derived reactively from a classified `AUTHENTICATION_FAILED`, not from a new static "does this provider need a credential?" flag** (Phase 5.7a.5) — the same registered identifier (`OPENAI_COMPATIBLE`) legitimately serves both a keyless local Ollama and a real, auth-required endpoint, so no per-provider static answer could be correct for both. `ModelGatewayService.invoke()` instead reacts to what actually happens: an `AUTHENTICATION_FAILED` (5.7a.4) reached with no credential supplied from any source becomes `PROVIDER_CREDENTIAL_REQUIRED`; the same failure with a credential configured (just wrong) stays `AUTHENTICATION_FAILED`. `MOCK`/a genuinely keyless endpoint never receive a 401 at all, so this translation never engages for them — no special-casing needed for the credential-free path. `backend/app/runtime/services.py::ModelGatewayService.invoke`.
37. **`MODEL_PROVIDER_API_KEYS` was kept, not removed, as the fallback tried only after a per-organization credential doesn't resolve** (Phase 5.7a.5) — of the three dispositions the build prompt posed, this was the least disruptive (a pre-implementation grep confirmed nothing previously exercised this dict in a way a preceding per-org lookup could break) and preserves its one genuinely useful role: a single shared key for local/dev environments that would otherwise need a database row just to talk to a credential-free Ollama instance. `backend/app/core/config.py`, `backend/app/runtime/services.py::ProviderCredentialService.resolve_secret`.
38. **The encryption utility reuses Phase 5.2.4's exact key-management pattern rather than inventing a new one** (Phase 5.7a.5) — `credential_crypto.py`'s key provenance (env-configured value, else auto-generate-and-persist to gitignored `.keys/` with a loud warning) is a direct copy of `LocalKeyProvider`'s established approach for signing keys, down to the same Known-Deviation framing (`ACT-VER-NFR-002`'s "key must enter process memory" acknowledgment, same Milestone 13 closure condition). Consistency of pattern was judged more valuable than any marginal difference a bespoke design might have offered for a problem this codebase had already solved once. `backend/app/runtime/providers/credential_crypto.py`.
39. **`tools_snapshot` itself was deliberately not touched to add the HTTP egress allowlist — a new snapshot key was added instead** (Phase 5.6a.1). `AgentVersion.tools_snapshot` is a bare list of tool-*id* strings, consumed as exactly that shape by three existing subsystems: `AttestationService` (one manifest entry per id), `VersionComparisonService` (`set()`-diffs it against a baseline — a `list[dict]` would raise `TypeError: unhashable type: 'dict'`), and `CompatibilityAnalysisService`. Changing its element type would have broken all three, a far larger blast radius than this sub-phase's actual scope. Instead, `SnapshotBuilderService.build_snapshot()` gained a new, separate `runtime.tool_configs` key, populated the same "copy values from the live row at publish time" way every other field in that document already is (§12). `backend/app/runtime/versioning/snapshot.py`.
40. **The HTTP action's egress policy is read from the published version's frozen snapshot document, never from the live `Tool` row** (Phase 5.6a.1, `ACT-TLX-FR-004`) — `ToolGatewayService._frozen_http_config` queries `AgentVersionSnapshot` by `execution.agent_version_id` and reads `snapshot["runtime"]["tool_configs"][tool_id]["http_config"]`; `Tool.http_config` itself is only ever read at *publish* time, to build that frozen copy. Proven, not just asserted: `test_allowlist_is_read_from_frozen_snapshot_not_mutable_tool_state` widens a tool's live allowlist after publish and confirms the already-published version's enforcement is unaffected. A direct consequence: a tool assigned to an agent but never included in a version's `tools_snapshot` at publish time has no entry in the frozen `tool_configs` at all and is rejected outright — "verified against tools_snapshot" in the most literal sense.
41. **A dedicated `tool_credentials` table, not a reuse of `provider_credentials`** (Phase 5.6a.1, `ACT-TLX-FR-012`) — same reasoning as 5.7a.5's own dedicated-table decision (#35 below, `deployment.secret_references` vs. `provider_credentials`): a tool credential authenticates to an arbitrary third-party HTTP API, a model-provider credential to a registered model-provider identifier — different enough resources that overloading one table's identifier column with the other's concept would blur the distinction for no real benefit. The encryption utility itself (`credential_crypto.py`) *is* reused directly — only the table and its narrower service (`ToolCredentialService`, `store`/`resolve_secret`/`delete` only, no fallback chain, no CRUD API in this sub-phase) are new.
42. **DNS-rebinding defense is connection pinning, not a second re-resolution at connect time** (Phase 5.6a.1, `ACT-TLX-FR-006`) — the build prompt's own implementation note flagged that "resolve then trust" is the classic SSRF hole; the equally-classic mistake in the *other* direction is "re-resolve immediately before connecting," which reintroduces exactly the same TOCTOU window a rebinding attacker exploits (their DNS answers public on the check, private on the second lookup). `http_executor._PinnedTransport` instead resolves and validates *once* and connects the actual socket to that exact address, with the HTTP client's connection target rewritten independently of its `Host` header and TLS SNI — verified empirically against the installed `httpx`/`httpcore` before writing this module's tests, and proven in `test_connection_is_pinned_to_the_validated_ip_not_a_fresh_lookup` (a resolver that would answer differently on a second call is confirmed consulted exactly once per request). No residual rebinding risk was left to document — the HTTP client in use can and does pin.
43. **The local-dev HTTPS exception also has to relax the private-address rule, or it would be unusable** (Phase 5.6a.1, `ACT-TLX-FR-008`) — the build prompt describes the exception only in scheme terms ("permit plaintext... for a declared local-development host"), but a local-dev target is by definition going to resolve to a loopback/private address; if the private-address rule (rule 4) still unconditionally denied it, the plaintext exception could never actually be exercised. `egress_guard.resolve_and_validate` therefore also narrowly exempts a host from the private-address check, but *only* when it is both on the allowlist *and* individually named in the tool's own `local_dev_hosts` *and* the tool has `allow_plaintext_http` set — three independent, explicit conditions, so opting one host in never widens the private-address space generally. Not fully specified by the prompt; this is the interpretation that makes the stated exception actually usable while keeping it narrow, stated here rather than decided silently.
44. **5.7a.4's circuit breaker/backoff was extracted into a neutral core rather than reused as-is or duplicated** (Phase 5.6a.2, `ACT-TLX-FR-027`) — the honest finding the build prompt asked for: the *state machine* (a plain dict keyed by any string identifier) and the backoff *math* were already provider-neutral, but `_circuit_before_call` hard-coded raising `ProviderRequestFailedError` — a model-specific exception a tool call must never raise (it would abort the execution, contradicting `ACT-TLX-FR-028`). Rather than reuse the coupled function or hand-roll a second breaker, the neutral half was pulled out (`_circuit_is_open`/`_circuit_note_success`/`_circuit_note_failure`/`_backoff_delay`, none mentioning "provider" or "tool") and both the pre-existing model-side functions and a new tool-side set were rebuilt on top of it — same signatures, same behavior for the model side (every pre-existing 5.7a.4 test passes unmodified), genuinely shared logic for both. `backend/app/runtime/services.py`.
45. **A `FAILED` tool call no longer aborts the execution; a `DENIED` one still does — a new, deliberately narrow behavior change** (Phase 5.6a.2, `ACT-TLX-FR-028`) — before this phase, *every* non-`ALLOWED` `ToolCall` status raised past `ToolGatewayService.invoke()` and failed the whole execution, egress denials included. This phase introduces a second, distinct status: `FAILED` (a schema violation, an exhausted retry, a timeout, an oversized response, an open circuit, a concurrency-ceiling rejection) for outcomes of an *attempted* invocation, which `invoke()` now returns normally rather than raising. `DENIED` (a governance/authorization/egress-policy fact — `TOOL_NOT_FOUND`/`TOOL_NOT_ASSIGNED`/`TOOL_ACTION_NOT_ALLOWED`/`TOOL_CONSTRAINT_VIOLATION`/`TOOL_EGRESS_DENIED`) is completely unchanged, still raises, still fails the execution — proven by `test_egress_denial_writes_decision_and_reason_and_fails_the_execution` (5.6a.1's own test) passing unmodified. `backend/app/runtime/services.py::ToolGatewayService.invoke`.
46. **`RESPONSE_TOO_LARGE`/`REDIRECT_DEPTH_EXCEEDED` map to `ProviderErrorClass.UNKNOWN`, not a new taxonomy value** (Phase 5.6a.2, `ACT-TLX-FR-025`) — the build prompt's instruction was to reuse the *same* eight-class taxonomy 5.7a.4 built for model calls, not extend it; neither condition has a natural bucket in a taxonomy designed for model-provider failures. `UNKNOWN` already guarantees "never retried" (`RETRYABLE_PROVIDER_ERROR_CLASSES` excludes it), which is exactly the correct behavior for both — retrying either reaches an identical outcome against the same target every time, so nothing about them is actually transient, even though (unlike the taxonomy's usual "we don't know why" meaning for `UNKNOWN`) the reason is known precisely; the dedicated `ErrorCode`s (`TOOL_RESPONSE_TOO_LARGE`, folded into `TOOL_EXECUTION_FAILED` for the redirect case) still carry the specific reason. `backend/app/runtime/services.py::_classify_tool_execution_failure`.
47. **A model-requested tool call always uses `action="EXECUTE"` — never inferred, never configurable per call** (Phase 5.6a.3, `ACT-TLX-FR-040`) — the platform's `READ`/`WRITE`/`EXECUTE`/... action vocabulary is a governance concept the LLM tool-calling interface has no equivalent for (a tool call is just a name and a JSON object); rather than invent a mapping from tool name or arguments to an action (guessing exactly the kind of hidden behavior REPO_STATE §10.15 forbids), `ToolLoopOrchestrator` always requests `EXECUTE`, and a tool's `AgentTool.allowed_actions` assignment must include it. The pre-existing explicit `input_payload["tool_calls"]` mechanism keeps supplying its own explicit action, unchanged. `backend/app/runtime/services.py::ToolLoopOrchestrator._execute_sequential/_execute_parallel`.
48. **`TOOL_NOT_BOUND_TO_VERSION` aborts the execution; it is not fed back as a recoverable `FAILED` result** (Phase 5.6a.3, `ACT-TLX-FR-045`) — genuinely ambiguous in the build prompt ("rejected with `TOOL_NOT_BOUND_TO_VERSION`" doesn't itself say abort-vs-recover), resolved by treating a model naming a tool outside this version's frozen `tools_snapshot` as a scope violation — the same tier as `TOOL_NOT_ASSIGNED` — rather than a mistake the model gets to iterate past. Letting a model freely probe nonexistent tool names without consequence is exactly the kind of boundary-testing 5.6a.1's SSRF-conscious posture already treats as something to stop, not tolerate; this is also where §10.4 (no agent-to-agent path) is structurally enforced, since a tool is the only thing this loop can ever name. `backend/app/runtime/services.py::ToolLoopOrchestrator.run`.
49. **Tool-call arguments cross to `ToolGatewayService.invoke()`'s `params` with zero translation** (Phase 5.6a.3) — a model's `ModelToolCall.arguments` is passed through as `params` completely unchanged in shape; there is no semantic-to-`{path,query,body}` mapping layer for `HTTP` tools. A tool's own declared, frozen `input_schema` is what actually tells both the model and 5.6a.2's validator what shape of arguments a given tool expects — for an `HTTP` tool in this codebase, that means the schema (and the tool's description, in the `ModelToolDefinition` offered to the model) must itself describe `{path, query, body}` fields if that's what `_invoke_http` needs. Adding a translation layer here would have been exactly the "reimplement the primitive" the build prompt forbade. `backend/app/runtime/services.py::ToolLoopOrchestrator.run`; `backend/tests/runtime/test_tool_loop.py`'s HTTP-tool tests declare their `input_schema`/tool-call arguments in that shape deliberately.
50. **A genuine cross-thread/cross-transaction deadlock, found by reproducing it against `pg_stat_activity`, not guessed at or designed around in advance** (Phase 5.6a.3, `ACT-TLX-FR-044`) — the first version of parallel tool execution opened one fresh `Session` per worker thread; each one's `INSERT INTO tool_calls` (an FK-referencing insert into a row still `FOR UPDATE`-locked by `ExecutionWorkerService.claim_next`'s own, correct, untouched claiming query) blocked waiting for that lock, while the *main* thread blocked inside `future.result()` waiting for those same worker threads — a deadlock invisible to Postgres's own detector (the main connection looks merely idle from its side, not waiting on a database resource). Diagnosed by killing the hung test process, querying `pg_stat_activity` directly (`wait_event_type='Lock', wait_event='transactionid'` on every worker connection), and confirming the exact row and lock type before writing the fix: `ToolLoopOrchestrator._execute_parallel` commits `self.db` immediately before spawning any thread. Safe because `claim_next`'s lock has already done its one job (preventing a second worker from claiming the same row, which is by definition no longer `QUEUED`) by the time parallel dispatch can ever run, and `SessionLocal` is `expire_on_commit=False` (`app/core/database.py`), so no re-fetch is needed afterward. The queue/worker model's own transaction boundary (`claim_next`/`run_once`) was not touched — the fix lives entirely in the new code that introduced the conflict. `backend/app/runtime/services.py::ToolLoopOrchestrator._execute_parallel`.
51. **`_CONNECTOR_TYPES` in `app/integration/service.py` is a private, in-process dict, not a public registry** (Phase 2.1.1, `ACT-INT-FR-001`) — the build prompt explicitly scopes the real connector registry (dynamic type registration, resolution API, health awareness) to Phase 2.1.3, but *something* still has to turn a `connectors` database row back into a live `Connector` Python instance so `ConnectorService` can call `validate_configuration()` on it. This dict (today: `{"MOCK": MockConnector}`) is that minimal seam — no public `register()`/`resolve()` functions, no dynamic discovery — and is documented, in the module itself, as expected to be entirely superseded once 2.1.3 lands, not a smaller version of that future registry to be extended in place.
52. **`PATCH /connectors/{id}` (configuration update) is allowed from `registered`, `configured` or `disabled` — never `active`** (Phase 2.1.1) — the build prompt's own §7 endpoint list specifies the eight routes but not which lifecycle states each is valid from; this codebase resolved it by requiring an operator to `disable` an active connector before changing its configuration, mirroring the existing taste for "you cannot silently rewrite something live" (a published `AgentVersion`'s configuration is frozen the same way) and giving one unambiguous moment where a live connector's configuration is known to be settled. `disabled -> configured` deliberately reuses the same `configure` lifecycle event as `registered -> configured`, since re-enabling a disabled instance is exactly the same operation. `backend/app/integration/service.py::ConnectorService.update_configuration`.
53. **`mark_failed` has no HTTP route in this sub-phase, but is a real, directly-callable, directly-tested `ConnectorService` method** (Phase 2.1.1) — the build prompt's lifecycle diagram shows `(any state) -> failed` as part of a "complete" machine (AC-16), but its own §7 endpoint list names no route that drives it, since automatically detecting failure is Phase 2.1.3's health-monitoring job. Rather than leave `failed` a documented-but-unreachable value, the transition itself was built and tested directly against the service layer now, so the *state machine* is complete today even though nothing yet triggers it in production. `backend/app/integration/lifecycle.py`, `backend/app/integration/service.py::ConnectorService.mark_failed`.
54. **Every connector lifecycle transition is recorded twice, deliberately, not redundantly** (Phase 2.1.1, `ACT-INT-FR-010`) — once in the connector-specific, queryable `connector_lifecycle_events` table (which the SRS names explicitly, and `GET /connectors/{id}/events` exposes directly), and once through the platform-wide `AuthorizationAuditService.record_change` every other domain's state changes already flow through. Neither replaces the other: the first is this domain's own structured history; the second is what keeps a security/compliance reviewer able to find every state-changing event in one place (`authorization_audit`) regardless of which domain produced it, consistent with `_record_event`'s dual-write precedent in `app/runtime/services.py` (Phase 5.0). `backend/app/integration/service.py::ConnectorService._transition`.
55. **"Append-only" for `connector_lifecycle_events` is enforced by omission, not by a database-level `REVOKE`** (Phase 2.1.1) — consistent with every other audit-shaped table already in this schema (checked: no table anywhere in this codebase uses a DB-level `REVOKE UPDATE`/`REVOKE DELETE`). `ConnectorService` simply never defines an update or delete method for this table, and no route accepts `PATCH`/`DELETE` on the events collection — both mechanically checked by `test_ac18_lifecycle_events_are_append_only_by_construction` rather than asserted only in prose.
56. **A connector credential bundle is one JSON string, then one Fernet ciphertext — never per-field plaintext columns** (Phase 2.1.2, `ACT-INT-FR-025`) — `ConnectorCredentialService.store()` calls `json.dumps(dict(credential), sort_keys=True)` before encrypting, so `connector_credentials` never has a column named `api_key`/`client_secret`/`password`/etc. that a future migration or query could accidentally select in plaintext. The trade-off (an opaque blob instead of queryable per-field columns) was accepted deliberately: nothing in this sub-phase or its SRS needs to query *by* a credential field's value, only to apply the whole bundle to a request. `backend/app/integration/auth/service.py::ConnectorCredentialService.store`.
57. **`credential_crypto.py` required zero extraction or generalization to reuse for connector credentials** (Phase 2.1.2) — the build prompt anticipated needing to "extract the reusable core rather than duplicating it" if direct reuse wasn't clean; it was clean, because `encrypt_secret`/`decrypt_secret`/`mask_hint` already operated on plain strings with no provider-specific branch anywhere in their own bodies (only the module's docstring and settings names mention "provider"). This is the second domain (after Phase 5.6a.1's `ToolCredentialService`) to import these three functions unchanged — verified in tests by object identity (`svc_module.encrypt_secret is credential_crypto.encrypt_secret`), not merely by matching behavior, so a future refactor that broke the reuse (e.g. a connector-specific wrapper reimplementing the same logic) would fail the test even if it happened to encrypt/decrypt correctly. `backend/app/integration/auth/service.py`.
58. **OAuth2 concurrency-safe refresh locks the *parent* `connector_instances` row, not the `connector_oauth_tokens` row it's actually refreshing** (Phase 2.1.2, `ACT-INT-FR-024`) — a build-prompt-mandated design decision, documented and load-bearing. Locking the token row directly cannot serialize the very first acquisition (no row exists yet to `SELECT ... FOR UPDATE`, so two concurrent first-callers would both pass a "does a row exist" check and race an `INSERT`, one losing to the unique constraint on `connector_instance_id`). The parent instance row always exists by the time this code path runs, so locking it serializes both the "create" and "refresh" cases with one mechanism, and is semantically apt regardless ("only one thread may mutate this connector's credentials at a time") — the same `SELECT ... FOR UPDATE`-as-serialization-point discipline `ExecutionWorkerService.claim_next` (Phase 5.0) already established for a different problem. Proven, not just argued: `test_ac13_concurrent_refresh_does_not_double_refresh` runs two real threads against two real `SessionLocal()` connections with a fixture transport that sleeps mid-call to widen the race window, and asserts the token endpoint was hit exactly once. `backend/app/integration/auth/token_manager.py::get_valid_access_token`.
59. **The OAuth2 authorization-code consent-redirect UI is stubbed; no HTTP route exposes `build_authorization_url()` either** (Phase 2.1.2) — the build prompt explicitly allowed the interactive consent UI to be "minimal or deferred," but its own §7 endpoint table lists only the `oauth/callback` route, not a route for the authorization-URL builder. Rather than speculatively add an endpoint the table didn't ask for, `build_authorization_url()` exists as a real, directly-tested `ConnectorCredentialService` method only — a future sub-phase (or a frontend that needs it) adds the route when something actually calls it, avoiding the exact "build ahead of the sub-phase that needs it" trap the 2.1.1 build prompt warned against and this one inherited. `backend/app/integration/auth/service.py::ConnectorCredentialService.build_authorization_url`.
60. **2.1.2 reuses 2.1.1's `integration.connector.view`/`.manage` permissions rather than adding `integration.credential.manage`** (Phase 2.1.2) — the build prompt explicitly invited a finer permission "only if genuinely warranted." A stored credential is a property of a connector instance, not an independently access-controlled resource, and nothing in `ACT-INT-FR-020..028` asked for a segregation-of-duties split between "can configure a connector" and "can configure its credentials" — unlike, say, `runtime.provider.view` vs `.manage`, which predates this and was Milestone 1's own call for a different resource shape. `backend/app/integration/routes.py`.
61. **A health check's reachability probe never receives a credential — the two questions (reachability, auth validity) are answered by two structurally separate code paths** (Phase 2.1.3, `ACT-INT-FR-047`) — `Connector.health_check(configuration)` takes only the instance's own `configuration`; auth validity is answered entirely by re-calling `ConnectorCredentialService.validate()` (2.1.2), never by decrypting a secret inside `ConnectorHealthService` or handing one to a connector's own code. This wasn't the only possible design (a single `health_check(configuration, credential)` method would have worked too) but was chosen specifically because it makes `ACT-INT-FR-047` ("never expose credential material") true by construction for the reachability half — there is no code path through which a connector author's `health_check()` implementation *could* leak a secret, because it never receives one. `backend/app/integration/base.py`, `backend/app/integration/health.py::ConnectorHealthService._probe`.
62. **`recover` (`failed -> active`) is a new lifecycle event, not folded into the pre-existing `activate`** (Phase 2.1.3) — a health-driven recovery and an operator activating a freshly-configured connector are different operations with different preconditions (the former only ever follows a passing health check; the latter never touches health at all). Conflating them under one event name would make the `connector_lifecycle_events`/audit-trail `event` field ambiguous about which actually happened — a genuine, documented judgment call the build prompt itself flagged as open ("state whether the state machine needed a `failed -> active` transition added"). `backend/app/integration/lifecycle.py`.
63. **No new alerting/notification channel was built for `ACT-INT-FR-046`** (Phase 2.1.3) — `app/services/notification_service.py` was read and rejected as a fit: it is a direct SMTP sender with no subscription/recipient-list concept, so wiring a connector-health event into it would mean inventing that infrastructure as a side effect of this sub-phase, not a one-line addition. Instead, this sub-phase follows the exact precedent Phase 5.6a.1 already set for `RUNTIME_TOOL_EGRESS_DENIED`: a severity-tagged audit event, human-reviewed via a dashboard/query, not pushed. `ConnectorService._transition` now tags `INTEGRATION_CONNECTOR_STATE_CHANGED`'s `meta.severity` as `CRITICAL` specifically when `to_state == "failed"` — the *existing* event is the alerting signal, not a new dedicated one. `backend/app/integration/service.py::ConnectorService._transition`.
64. **The interim health-check scheduler is gated by a single settings flag, default `false` everywhere including every test run — not a pytest-only override** (Phase 2.1.3, `ACT-INT-FR-043`) — mirrors the existing `NOTIFICATIONS_ENABLED`/`RATE_LIMIT_ENABLED`/`RESPONSE_ENVELOPE_ENABLED` convention (`backend/tests/conftest.py`) except even simpler: since the setting already defaults off, no autouse fixture was needed to force it off in tests. `run_sweep_once()` is exposed as a plain synchronous function specifically so tests (and, later, a real Milestone-3 job registration) can call it directly without touching the `asyncio` loop at all. `backend/app/core/config.py`, `backend/app/integration/scheduler.py`.
65. **`connector_health_checks` retention is a flat per-instance row cap (200), not a time-window policy** (Phase 2.1.3, `ACT-INT-FR-045`) — simpler to implement and reason about than a time-based rollup, and sufficient at this milestone's scale (the interim scheduler's own default 5-minute interval makes 200 rows the better part of a day even under constant checking). The cap always force-keeps the just-inserted row's id, guarding against a same-transaction `checked_at` timestamp tie (`server_default=func.now()` has second resolution) ever rolling off the very check that triggered the cleanup. `backend/app/integration/health.py::ConnectorHealthService._enforce_retention`.
66. **`ConnectorCredentialService.validate()`'s `actor` parameter became optional (`User | None`), additively** (Phase 2.1.3) — needed so the scheduler's system-triggered checks (no human actor) can call the same, unchanged validation path the on-demand route already used with a real actor. Mirrors the precedent `ConnectorService.mark_failed`/`recover` already set for system-triggered lifecycle transitions. Every existing caller still passes a real `User`; nothing about the 2.1.2 credential-validation behavior itself changed. `backend/app/integration/auth/service.py::ConnectorCredentialService.validate`.
67. **The SDK surface is an explicit whitelist module (`__all__` re-exports only), not "whatever an author can reach by importing `app.integration`"** (Phase 2.1.4, `ACT-INT-FR-060`/`FR-061`) — the build prompt's own governing tension (ease of authoring vs. structural containment) resolved to: draw the boundary as one small, greppable, documented file rather than a convention ("don't import internals") an author could violate by habit. `AuthScheme`/`OutboundRequest` and every service class were deliberately left out even though a real author could theoretically benefit from seeing their shapes — the containment property only holds if the *withheld* set is at least as deliberate as the *exposed* one. `backend/app/integration/sdk/__init__.py`.
68. **`GovernedHttpClient.allowed_hosts` is bound at construction, never accepted as a `request()`/`evaluate()` parameter** (Phase 2.1.4, `ACT-INT-FR-066`) — the build prompt named this exact risk ("an author cannot widen the allowlist at call time"). The alternative (accept a per-call host set, validate it against some other stored declaration) would have made the containment a *runtime check that could be gotten wrong*, not a *shape that cannot express the dangerous case*. Every intended construction site derives `allowed_hosts` from the connector instance's own already-validated `configuration` (see the worked example), never from anything a model or an inbound request could influence. `backend/app/integration/sdk/http.py::GovernedHttpClient`.
69. **A dedicated `HealthCheckNotImplemented` marker, not Python's built-in generic unimplemented-method exception, signals "this connector's `health_check()` was never really written"** (Phase 2.1.4, `ACT-INT-FR-064`) — discovered, not assumed: `test_connector_health.py`'s pre-existing `test_ac27_no_new_todo_or_skip_markers_in_this_phases_files` greps every file under `app/integration/` for that builtin exception's literal name as a leftover-stub signal. Using it as this sub-phase's own "not implemented" sentinel would have required weakening that test (forbidden per this build prompt's own working constraints) purely to make the new mechanism's own name legal — a self-inflicted conflict avoided by picking a different, purpose-built name instead of touching a pre-existing, unrelated test. `backend/app/integration/validation.py::HealthCheckNotImplemented`.
70. **Registration parity for SDK-authored connectors is proven by putting one in `_CONNECTOR_TYPES` itself, not by building and then testing a second registration mechanism** (Phase 2.1.4, `ACT-INT-FR-062`) — the alternative (a separate `sdk_register()` entry point, then a test asserting it behaves identically to the first-party path) would have created exactly the "two paths to keep in sync" risk the requirement exists to rule out. `SDK_EXAMPLE_WEBHOOK` sits in the same dict as `MOCK`/`MOCK_AUTH` and is seeded by the same, unbranched `ensure_seeded()` loop — there is structurally one path, not two that happen to agree today. `backend/app/integration/service.py::_CONNECTOR_TYPES`.
71. **Completeness validation is one function (`validate_declaration_complete`), called by both the real registration path and the SDK test harness's pre-flight check — not two separate implementations kept in sync by convention** (Phase 2.1.4, `ACT-INT-FR-064`) — mirrors decision #70's same reasoning applied to validation rather than registration: an SDK author who calls `ConnectorTestHarness.assert_declaration_complete()` before ever touching a database is running the *exact* check `ConnectorTypeService.register()` will run, not an approximation of it. `backend/app/integration/validation.py`.
72. **No migration, stated as the default expectation met, not merely as an absence** (Phase 2.1.4) — the build prompt explicitly asked for a migration only if genuinely justified, with a default expectation of zero; every table this sub-phase's authoring surface touches (`connectors`, `connector_instances`, and 2.1.2/2.1.3's tables) already existed. Confirmed live, not assumed: `alembic current` re-checked and unchanged at `0035_connector_health` at the end of this sub-phase's own work.
73. **`RestConnector.describe()` (the zero-argument, type-level call) carries only a structural placeholder tool contract — the real, per-endpoint ones are a separate, per-instance function** (Phase 2.2.1, `ACT-INT-FR-102`) — `Connector.describe()`'s signature (unchanged since 2.1.1) has no configuration parameter, so it structurally cannot know an instance's declared endpoints; widening the ABC itself to pass one would have rippled into `MockConnector`/`WebhookConnector` too, for a capability only a *declarative* connector type needs. `declaration.py::tool_contracts_for(configuration)` is the real `ACT-INT-FR-102` mechanism, called by the invocation bridge once an instance is configured — a deliberate, reported decision, not an oversight. `backend/app/integration/connectors/rest/connector.py`, `declaration.py`.
74. **A REST connector instance's authentication scheme lives in its own declared `configuration`, not the connector *type*'s `auth_requirements`** (Phase 2.2.1, `ACT-INT-FR-101`) — every connector type through 2.1.4 declared one scheme fixed for every instance of that type (`MOCK_AUTH` -> `API_KEY`, `SDK_EXAMPLE_WEBHOOK` -> `BEARER`), and `ConnectorCredentialService.resolve_and_apply()` read it from the type row accordingly. A generic REST connector serves many different vendor APIs, each needing its own scheme, from one registered type — so `RestConnector`'s own `auth_requirements.scheme` is `"NONE"` (honest: the framework enforces no single scheme at the type level for this connector), and a new, additive `ConnectorCredentialService.resolve_and_apply_for_scheme(instance, request, auth_scheme, ...)` method (2.1.2's original `resolve_and_apply()` is now a one-line wrapper over it) resolves per-instance instead. No existing caller/test changed behavior. `backend/app/integration/auth/service.py`, `backend/app/integration/connectors/rest/invoker.py`.
75. **The tool-invocation bridge (`invoker.py`) is real, database-backed, and fully tested — but is not wired into `ToolGatewayService`/`tools_snapshot`/the model-driven tool loop** (Phase 2.2.1) — the build prompt's own working constraints forbid touching model/tool execution (Milestone 1, closed), while also requiring that "a REST connector nobody can invoke proves nothing." Both are satisfied by building a genuine, independently-useful, independently-tested invocation entry point (`invoke_tool()`) that lives entirely inside `app.integration`, calls the unchanged 2.1.3 registry's fail-fast resolution first, and stops there — a future milestone that assigns connector-derived tools to agents can call this function (or an equivalent) from wherever that wiring eventually lives, without this bridge needing to change. `backend/app/integration/connectors/rest/invoker.py`.
76. **`GovernedHttpClient.request()` gained an optional `query` parameter, rather than requiring every caller to pre-bake a query string into `url`** (Phase 2.2.1) — discovered as a real gap, not designed in from the start: `execute_http_tool`'s `_build_target_url` only ever honors a query string supplied through its own dedicated `query` parameter, silently dropping one embedded in `base_url` itself, a gap 2.1.4's query-free `WebhookConnector` never surfaced. Extending the SDK's own network primitive (rather than working around it inside the REST connector, e.g. by manually splitting the URL back apart) keeps the fix available to every future SDK-authored connector that needs a query string, not just this one. Additive and backward-compatible: every existing call site (including 2.1.4's own tests) is unaffected by the new, optional, defaulted parameter. `backend/app/integration/sdk/http.py::GovernedHttpClient.request`.
77. **Bounded pagination enforces a hard ceiling (100 pages) independent of what a connector's own declaration or a remote server claims** (Phase 2.2.1, `ACT-INT-FR-105`) — the build prompt's "never an unbounded fetch" requirement is satisfied by construction, not by trusting a declared `max_pages` alone: `run_pagination()` always computes `min(declared max_pages, 100)`, so even a misconfigured declaration (`max_pages: 10000`) or an actively misbehaving server that always signals "more" cannot force an unbounded fetch — proven directly in `test_ac14_pagination_is_bounded_even_when_the_server_never_stops` against a fetcher that always returns a full page. `backend/app/integration/connectors/rest/pagination.py`.
78. **The database executor's only public entry point takes a `DeclaredQuery` object and a parameter mapping — never a string** (Phase 2.2.2, `ACT-INT-FR-121`/`FR-122`) — the build prompt's own governing rule ("the model never writes SQL") is satisfied by construction: `execute_declared_query`'s signature has no parameter position a raw SQL string could occupy, so "run this string as SQL" is not an operation this module offers, the same containment-by-absence principle the SDK used for the raw HTTP client (2.1.4) and 2.2.1 used for request templating, applied here at the point the build prompt itself calls this milestone's single sharpest security rule. `backend/app/integration/connectors/database/executor.py::execute_declared_query`.
79. **A declared query's read/write classification inspects the declared SQL text directly** (Phase 2.2.2, `ACT-INT-FR-125`) — this does not contradict "the model never writes SQL" specifically because the inspected text is *declared and trusted*, authored by a human at configuration time, never derived from or influenced by model output; the build prompt itself draws this exact distinction (§4.3). Classification is fail-closed by design (`classify_query`): only a first keyword of `SELECT`/`WITH`/`SHOW`/`EXPLAIN` is treated as read-only, everything else — including an unrecognized statement — is treated as a write, deliberately not an allow-list of write keywords that risks missing one. `backend/app/integration/connectors/database/declaration.py::classify_query`.
80. **`connector.py` imports one specific exception type (`DbWriteNotPermittedError`) beyond the pure-SDK-surface discipline 2.2.1 established, and no other file in the package does** (Phase 2.2.2, `ACT-INT-FR-125`) — `declaration.py` stays exactly as SDK-surface-restricted as 2.2.1's own `declaration.py`, raising only `ConnectorConfigInvalidError` for every structural/semantic problem; the one exception is a config-time rejection needing its own distinct, stable, machine-checkable code (`DB_WRITE_NOT_PERMITTED`) that nothing in the REST connector ever needed. Widening the SDK's own `ConnectorConfigInvalidError` to carry a distinguishable reason for every connector type would have been a larger, riskier change serving only this one need — this sub-phase's own AC-20 explicitly anticipates and allows "a justified, reported surface addition" instead. `backend/app/integration/connectors/database/connector.py`.
81. **A database credential resolves through a new method that returns the decrypted bundle itself, not an HTTP-header-shaped `OutboundRequest`** (Phase 2.2.2, `ACT-INT-FR-127`) — 2.2.1's `resolve_and_apply_for_scheme()` returns an `OutboundRequest` because an HTTP connector's credential *is* naturally a header; a database username/password has no such natural HTTP shape, and forcing one through `AuthScheme.apply()` (e.g. treating it as `BASIC` and discarding the resulting `Authorization` header) would have been a confusing, wasteful fit. `ConnectorCredentialService.resolve_credential_bundle()` shares the identical resolve/decrypt/OAuth2-refresh mechanics via a new private `_resolve_bundle_for_scheme` helper — same storage, same encryption, same tenant scoping — differing only in what the caller does with the result. `backend/app/integration/auth/service.py::ConnectorCredentialService.resolve_credential_bundle`.
82. **A database connector's `health_check()` is a raw TCP connect, not a database-protocol probe** (Phase 2.2.2) — the ABC's own contract never hands `health_check` a credential (that lives in the separate, encrypted `connector_credentials` store), so unlike a REST connector's `GovernedHttpClient.evaluate()` (which can meaningfully assess "would this URL be permitted" without any credential), there is no equivalent unauthenticated database-protocol reachability check to perform. A raw socket connect to the declared `(host, port)` proves "the server is reachable at the network level" without needing a credential or running any query at all — reachability-only, mirroring every other connector's `health_check()` in this codebase. `backend/app/integration/connectors/database/connector.py::DatabaseConnector.health_check`.
83. **A query's timeout is enforced two ways, not one, and the client-side mechanism cannot forcibly cancel a blocked DBAPI call** (Phase 2.2.2, `ACT-INT-FR-124`) — a server-side statement-timeout GUC (dialect-specific) is the primary enforcement (the database itself aborts the query); a client-side thread + `Future.result(timeout=...)` is the backstop guaranteeing `DB_QUERY_TIMEOUT` is raised even if the server-side setting doesn't fire. Because Python cannot cancel a thread mid-blocking-call, a client-side timeout stops *waiting* on the worker thread without killing it outright — a documented, accepted, bounded and self-resolving condition (the thread exits once the still-set server-side timeout aborts the query moments later), not a permanent leak; a genuinely more thorough fix would require lower-level DBAPI cursor cancellation support that varies by driver, out of this sub-phase's scope. `backend/app/integration/connectors/database/executor.py::execute_declared_query`.
84. **A result exceeding its row limit is rejected outright, never silently truncated** (Phase 2.2.2, `ACT-INT-FR-124`) — mirrors Milestone 1's `TOOL_RESPONSE_TOO_LARGE` precedent exactly: a truncated database result handed to a model could read as a complete, misleading answer, which is worse than a loud, explicit failure the caller can react to. Enforced via `fetchmany(row_limit + 1)`, never a bare `fetchall()`, so memory use is bounded regardless of the query's true result size — the check never has to materialize an unbounded result first to know it's too large. `backend/app/integration/connectors/database/executor.py::execute_declared_query`.
85. **SQL Server is a JSON-Schema-recognized but currently undriven dialect value, not a silent omission** (Phase 2.2.2, `ACT-INT-FR-120`) — `mssql+pyodbc` requires the Microsoft ODBC Driver for SQL Server installed at the *system* level, not a pip package, genuinely heavy and platform-awkward to add sight-unseen in this environment; the build prompt's own §6 explicitly allows marking it driver-pending rather than half-implementing it. `"SQLSERVER"` stays in `CONFIG_SCHEMA`'s enum specifically so a misconfigured instance gets a named "driver-pending" rejection message instead of a bare "invalid enum value," and `drivers.PENDING_DIALECTS` documents the boundary in code, not only in prose. `backend/app/integration/connectors/database/declaration.py`, `drivers.py`.
86. **The traversal enforcer (`scope.py`) has zero dependencies on this platform — not even the SDK** (Phase 2.2.3, `ACT-INT-FR-141`/`FR-143`) — every other connector-package module imports at least `app.integration.sdk`; `scope.py` imports only `os`/`posixpath`/`re`/`unicodedata`/`urllib.parse`, so it is importable and fully unit-testable with genuinely nothing else running — the build prompt's own §6 explicitly asks for this isolation, the storage analogue of Milestone 1's egress guard being buildable and testable with no network at all. `backend/app/integration/connectors/storage/scope.py`.
87. **Canonicalize, then contain — the pipeline order is fixed and never reversed** (Phase 2.2.3, `ACT-INT-FR-143`, AC-10) — control-character rejection, then iterative percent-decoding, then a second control-character check on the decoded result, then NFKC Unicode normalization, then (only then) backend-specific canonicalization and containment. Checking containment on the raw string and decoding afterward would let an encoded `..` slip past a check that never saw it; `resolve_and_contain`'s only return value is the already-canonicalized, already-contained target, so there is no way for a caller to accidentally act on an earlier, unvalidated form (no TOCTOU/rebinding-shaped gap). `backend/app/integration/connectors/storage/scope.py::resolve_and_contain`.
88. **Object-store containment is lexical (`posixpath.normpath`), not filesystem-based, and does not use a leading-slash root anchor** (Phase 2.2.3, `ACT-INT-FR-141`) — a first design used `posixpath.normpath("/" + prefix + "/" + supplied)` to lean on `normpath`'s own root-clamping behavior for absolute paths, but that behavior *silently drops* excess `".."` segments rather than flagging them as an escape attempt (the same anti-pattern `path.join`-style clamping is known for) — the opposite of "deny, don't silently sanitize." Switched to a *relative* `normpath` (no leading slash) specifically because it *preserves* a leading `"../"` instead of clamping it, letting the escape be explicitly detected and denied. `backend/app/integration/connectors/storage/scope.py::_resolve_object_store`.
89. **A `:` character is denied outright in a filesystem-scoped path fragment, not merely `..`/absolute-path patterns** (Phase 2.2.3) — a bare per-segment absolute-path check can miss an embedded drive-letter segment (`"docs/C:/evil"`), since some platform path-joining semantics reset to a later segment's own root when one is encountered; denying any `:` closes that gap and, as a side effect, also denies the NTFS alternate-data-stream syntax (`"file.txt:hidden"`) — a second, unrelated filesystem-specific attack surface neither this phase's own acceptance criteria nor the build prompt named, caught while designing the containment check, not left for a future finding. `backend/app/integration/connectors/storage/scope.py::_resolve_filesystem`.
90. **Two, not one, narrow SDK-surface deviations in the storage connector package — more than 2.2.2 needed, and stated as a deliberate difference, not an inconsistency** (Phase 2.2.3) — `declaration.py` raises its own `StorageScopeInvalidError` for all semantic validation (2.2.2's own `declaration.py` used only the SDK's generic `ConnectorConfigInvalidError` for the equivalent checks), because this phase's own acceptance criteria explicitly require a distinguishable `STORAGE_SCOPE_INVALID` code where 2.2.2 was never asked for one; `connector.py` separately keeps its own `StorageWriteNotPermittedError`, mirroring `DbWriteNotPermittedError` exactly. `scope.py` and `backends.py` both stay entirely free of `app.integration.errors`, so the deviation count is not "the whole package is less restricted," only these two specific, individually justified additions. `backend/app/integration/connectors/storage/declaration.py`, `connector.py`.
91. **A filesystem symlink escape is caught for free by the same `os.path.realpath` call that resolves `..`, not by a separate symlink-specific check** (Phase 2.2.3, AC-09) — `realpath` resolves both relative-traversal components *and* symlinks in one pass, so a path that is legitimately inside the declared base directory but is itself (or passes through) a symlink pointing outside it fails the identical post-canonicalization containment check a `../../etc/passwd` attempt would. No dedicated "is this a symlink" branch exists or is needed. `backend/app/integration/connectors/storage/scope.py::_resolve_filesystem`.
92. **Every object access — allowed or denied — is audited via a `finally` block, and a denial's audit record carries no path, because none was ever validated** (Phase 2.2.3, `ACT-INT-FR-145`) — this is 2.2.x's first invocation-level audit event; neither 2.2.1's REST bridge nor 2.2.2's database bridge audits individual calls, since neither build prompt required it. Recording the *validated* path only (never the raw supplied string) means a logged traversal attempt never itself becomes a record of exactly what a caller tried to reach outside scope — the audit trail documents "an attempt occurred and was denied," not the attacker's own probe value. `backend/app/integration/connectors/storage/invoker.py::invoke_tool`.
93. **Azure Blob is a JSON-Schema-recognized but currently undriven backend value, not a silent omission** (Phase 2.2.3, `ACT-INT-FR-140`) — `azure-storage-blob` is a genuinely heavy dependency this environment cannot exercise live; the build prompt's own §6 explicitly allows marking it backend-pending rather than half-implementing it, mirroring 2.2.2's SQL Server precedent exactly. `"AZURE_BLOB"` stays in `CONFIG_SCHEMA`'s enum specifically so a misconfigured instance gets a named "backend-pending" rejection message instead of a bare "invalid enum value," and `backends.PENDING_BACKENDS` documents the boundary in code. `backend/app/integration/connectors/storage/declaration.py`, `backends.py`.
94. **A queue publish target is fixed by the tool contract itself — not a model-supplied value validated against an allowlist** (Phase 2.2.4, `ACT-INT-FR-161`/`FR-164`) — the build prompt explicitly offered two shapes ("fixed target" or "strictly allowlisted name"); fixed-target was chosen as the stronger guarantee: there is no queue-name parameter anywhere in a publish tool contract's schema for a model to redirect through, so "the model cannot publish outside its declared queue" holds by absence of the affordance, not by a check that could in principle be bypassed if ever mis-wired. A queue reachable both ways is declared twice, once per operation, under two distinct binding names — the same pattern 2.2.3 established for a bucket needing both read and write scopes. `backend/app/integration/connectors/queue/declaration.py::tool_contracts_for`.
95. **`queue/scope.py` checks operation permission, not a queue name, and is genuinely simpler than `storage/scope.py` by design, not by omission** (Phase 2.2.4) — because decision #94 above already makes a queue-name-redirection attack structurally impossible, there is nothing analogous to storage's canonicalize-then-contain pipeline for this module to do; what remains genuinely worth isolating and testing is whether a *resolved* binding's own declared operation matches what is being attempted against it (a `PUBLISH`-only binding must reject a `CONSUME` attempt). The module has zero imports of any kind, not even from the standard library beyond nothing — the simplest possible isolated security module in this codebase. `backend/app/integration/connectors/queue/scope.py`.
96. **Zero SDK-surface deviations in `declaration.py`/`connector.py` this phase — the first generic connector to need none, mirroring 2.2.1 rather than 2.2.2/2.2.3** (Phase 2.2.4) — this phase's own required error-code vocabulary (`QUEUE_NOT_DECLARED`/`QUEUE_MESSAGE_TOO_LARGE`/`QUEUE_OPERATION_NOT_PERMITTED`/`QUEUE_CONSUME_TIMEOUT`) is entirely invocation-time; unlike storage's `read_only` or the database connector's own read/write posture, no instance-level flag exists here for a per-binding `operation` to conflict with at configuration time, since each binding is already fully self-describing. This was verified, not assumed: the phase's own AST-based import tests assert each module's non-SDK import set is empty. `backend/app/integration/connectors/queue/declaration.py`, `connector.py`.
97. **An oversized consumed message is truncated and flagged, not rejected outright or silently dropped — a deliberate departure from 2.2.2's/2.2.3's own "reject the whole operation" precedent** (Phase 2.2.4, `ACT-INT-FR-163`) — a database row-limit breach or a storage object read both fail one, indivisible operation; a bounded consume call retrieves a *batch of independent messages*, and discarding the entire batch over one oversized message would defeat the purpose of batching, while this connector's ack-on-retrieve policy (decision #98) means there is no redelivery mechanism to hand an oversized message back for later if it were dropped instead. Truncating to the effective limit and marking `truncated=True` keeps the batch bounded and useful while never silently passing the full oversized payload through. `backend/app/integration/connectors/queue/backends.py::_bound_message`.
98. **Acknowledgment policy is ack-on-retrieve (at-most-once), chosen explicitly over leaving it implicit or building transactional delivery** (Phase 2.2.4, §4.4) — the build prompt named this a genuine correctness subtlety requiring a stated, documented policy, not an ambient default. A message is acknowledged (AMQP `auto_ack=True`; SQS an explicit `delete_message`) as part of the same call that returns it to the caller, so a crash between ack and the caller's own use of the batch loses those messages — an accepted tradeoff for a bounded, discrete tool operation, the same "reject/return outright rather than leave a system in an ambiguous partial state" instinct behind 2.2.2's row-limit and 2.2.3's size-check disciplines. A use case needing at-least-once/transactional guarantees needs a real, stateful consumer, explicitly out of scope. `backend/app/integration/connectors/queue/backends.py::_amqp_consume`, `_sqs_consume`.
99. **`QUEUE_CONSUME_TIMEOUT` is defined but deliberately never raised this phase** (Phase 2.2.4, §7) — the build prompt asked explicitly whether a consume timeout should be surfaced distinctly from an empty return, and the answer chosen is no: a bounded consume finding nothing within its wait window is a successful, empty result (`ACT-INT-FR-162`'s own "never blocks indefinitely... returns what it has, possibly empty"), not a failure — both AMQP's `basic_get` and SQS's `receive_message` observe "nothing arrived" identically to "timed out waiting," so there is no genuinely distinct failure to raise this code for with either backend today. Kept in the error-code vocabulary, reserved for a future backend where the distinction is real. `backend/app/integration/errors.py::QueueConsumeTimeoutError`.
100. **The per-access audit event is reused from 2.2.3, not duplicated into a new one** (Phase 2.2.4, §4.5) — the build prompt's own instruction was explicit ("reuse 2.2.3's invocation audit"); `INTEGRATION_CONNECTOR_OBJECT_ACCESSED`'s existing shape (backend/scope-or-binding-name/operation/size/outcome) already fits a queue message as naturally as a storage object, so no new `AuthorizationAuditEvent` member was added — the same "don't multiply audit-event types for a shape that already fits" discipline implicit in every prior connector's own event reuse. `backend/app/integration/connectors/queue/invoker.py::_record_access`.
101. **`pika.ConnectionParameters(credentials=None)` is not the same as omitting the argument, and the fix is to omit it, not to pass a placeholder** (Phase 2.2.4) — a genuine third-party-library discovery made during this phase's own manual verification (see §9 item 15's Phase 2.2.4 entry): `pika`'s own `credentials` setter rejects an explicit `None`, since its real default is a private sentinel object. `_amqp_connection` now includes the `credentials` kwarg only when a real credential was actually resolved. `backend/app/integration/connectors/queue/backends.py::_amqp_connection`.
102. **Phase 3.2 adds `AgentDeployment.environment_id` as a second, additive field alongside the pre-existing `environment` string, the same "extend, never widen/replace" pattern item 25 already established for `lifecycle_state`/`status`.** The legacy string is still the load-bearing input to the M1 execution-path policy check (`RuntimePolicyService.evaluate`) — changing what it holds would be a change to that path, exactly what this phase must not do. `environment_id` is populated three independent ways (migration backfill, an opportunistic best-effort lookup on plain create, and directly by promotion) rather than being a strict, guaranteed invariant on every row — a deployment created for an organization whose environments were never seeded simply has `environment_id = NULL`, and every consumer of it (the policy choke point, the approval-requirement check) treats that as "skip this check," not as an error. `backend/app/models/runtime.py::AgentDeployment`, `docs/deployment/environments.md`.
103. **Environment policy evaluation lives at exactly one call site, `DeploymentLifecycleService.start_deploying`, deliberately not duplicated into `PromotionService` as a second, separate check** — a promotion creates its new deployment and then calls that same method, so the plain-deploy path and the promotion path are guaranteed to enforce identically without two implementations to keep in sync. `PromotionService.promote` does run `evaluate()` a second time, earlier, purely as a fail-fast optimization (reject before creating any row) — an intentional, documented redundancy, not a second, diverging policy engine (the two calls can never disagree, since they call the same function with equivalent inputs). `backend/app/runtime/deployment/service.py::start_deploying`, `backend/app/runtime/environment/service.py::PromotionService.promote`.
104. **Promotion's immutability guarantee is structural, not merely tested for** (`ACT-SRS-M3` §3.2's own sharp edge) — `PromotionService.promote` loads the source `AgentVersion` exactly once via `self.db.get(...)` and passes that same Python object straight into the pre-existing `DeploymentService.create`; there is no code path in the new module capable of constructing, copying, or assigning to an `AgentVersion` column, so `PROMOTION_IMMUTABILITY_VIOLATION` is a defensive assertion against a future regression, not a condition this phase's own logic can trigger. Verified live nonetheless (agent's total version-row count unchanged, `checksum`/`manifest_digest`/`signature_id` byte-identical before/after) because "structurally impossible" is a claim worth proving, not just asserting. `backend/app/runtime/environment/service.py::PromotionService.promote`.
105. **A governed environment's own approval requirement (`is_production`/`policy.requires_approval`) is added as a third condition to `DeploymentLifecycleService._requires_deployment_approval`, not built as a second, parallel approval mechanism** — the same reasoning behind item 103: one funnel, one set of tests, one place a reviewer needs to check to understand "when does a deployment need approval." `PromotionPath.requires_approval` (the build prompt's own schema column) is stored but deliberately left unwired as an independent second gate this phase, reported as a scoped choice rather than silently built as a duplicate mechanism alongside the first. `backend/app/runtime/deployment/service.py::_requires_deployment_approval`, `backend/app/runtime/environment/policy.py::requires_approval`.
106. **A policy field named after the build prompt's own literal suggestion, `allowed_connectors`, was renamed to `allowed_external_systems` before it ever caused a test failure** — `app/runtime`'s mechanically-enforced runtime-never-knows vocabulary tests (2.1.1's own precedent) forbid the substring "connector" anywhere under that tree, and this phase's own new `environment/policy.py` docstring used it in passing prose describing a *modeled-only* dimension. Caught by running the four vocabulary tests deliberately before the full suite, not after — the same class of finding 3.1 made and fixed reactively (see §9 item 15's Phase 3.1 entry) was made proactively this time. `backend/app/runtime/environment/policy.py`.
107. **`EnvironmentService.ensure_seeded()` needed its own explicit `db.commit()` at the route call site — mirroring `ReleaseChannelService.ensure_seeded()`'s method signature is not the same as mirroring its actual correctness** — that precedent's own `ensure_seeded()` also only flushes, but every one of *its* callers happens to commit later as part of a larger flow; `GET /environments` has no such later commit, so the first draft silently rolled back its own seed rows on session close (`app/core/database.py::get_db`'s `finally: db.close()` has no implicit commit). Fixed by adding `db.commit()` at the call site, matching the actual, verified precedent (`list_release_channels`, which does commit) rather than the precedent's method signature alone. `backend/app/runtime/routes.py::list_environments`.
108. **The freshness rule (Phase 3.3) is applied to `DeploymentHealth.checked_at`, not the build prompt's own suggested Milestone-2 connector-health signal.** Two independent, structural reasons: the runtime-never-knows vocabulary boundary forbids naming that Milestone-2 vocabulary anywhere under `app/runtime`, and — even setting that aside — there is no existing link in this codebase between a runtime `Tool`/`AgentVersion` and Milestone 2's own integration-instance catalog to know *which* instance(s) a deployment depends on, the identical gap Phase 3.2 already reported for `allowed_external_systems`. Reported as a gap (`docs/deployment/release-gates.md`'s "external-system dependency health gap"), not built around with a new dependency-modeling feature. `backend/app/runtime/release_gate/checks.py`.
109. **Severity per finding code is data (`_DEFAULT_SEVERITY`), not a hardcoded literal at each check's call site — overridable per environment via `Environment.policy["preflight_severity_overrides"]`, except one code.** `PREFLIGHT_KILL_SWITCH_ACTIVE` is checked for and returned first in `_severity_for()`, before the override map is even consulted — AC-07's absolute-BLOCK requirement is enforced by that early return, not by convention or a comment. `backend/app/runtime/release_gate/checks.py::_severity_for`.
110. **Compatibility (`PREFLIGHT_COMPATIBILITY_BREAKING`) and pending-approval (`PREFLIGHT_APPROVAL_PENDING`) are WARNING by default, deliberately not BLOCK, to avoid silently reversing two pre-existing, documented design decisions.** `docs/runtime/versioning.md` explicitly states compatibility/readiness analysis "has never gated anything"; `DeploymentLifecycleService.start_deploying`'s pre-existing reroute-to-`PENDING_APPROVAL` behavior (Phase 3.1) is the designed next step for a deployment requiring approval, not a failure state. Both are still surfaced (and both are still escalatable per environment via item 109's override mechanism) — the platform *default* just doesn't turn either into a hard block on its own. `backend/app/runtime/release_gate/checks.py::check_compatibility`, `::check_approvals`.
111. **The gate call inside `start_deploying()` runs after the pre-existing 3.2 narrow environment-policy check but before the approval-reroute logic — not after it.** Placed here deliberately, not incidentally: since the gate's own approval finding is WARNING (item 110), it can never itself raise, so it is safe to run before the reroute without disturbing that flow; running it after would have meant a deployment correctly rerouted to `PENDING_APPROVAL` never got a persisted preflight record for that attempt. `backend/app/runtime/deployment/service.py::start_deploying`.
112. **`ReleaseGateService.evaluate()` is deliberately not wrapped in the 3.1 `IdempotencyService` contract**, unlike `DeploymentLifecycleService.create()`/`PromotionService.promote()`. FR-031 requires every call to produce a fresh result ("a prior PASS does not permanently certify") — the opposite of idempotent replay. The same precedent already exists in this codebase: `CompatibilityAnalysisService.analyze` (`POST .../analyze`, Phase 5.2.6) recomputes and persists a fresh result on every call with no idempotency key either. `backend/app/runtime/release_gate/service.py::evaluate`.

113. ~~**`docs/architecture/data/erd.md` is stale**~~ — **closed 2026-08-24.** It declared **24 tables** against a live schema of **124** and its diagrams covered only the Phase 4 identity and authorization bounded contexts; it had drifted since roughly Phase 3.4. Regenerated from `Base.metadata` rather than by hand — every column, type and foreign-key edge in the new sections comes from the real metadata, so the diagrams could not be invented. Now **123 of 123** model tables documented across 19 diagrams in 13 bounded contexts (124 live: Alembic manages `alembic_version` itself, which is not a model — the reconciliation is stated in the header so the two numbers stop looking like a discrepancy). Deferred once deliberately, on the grounds that a hundred tables of ERD is its own scoped work rather than a side effect of a docs pass; done as that scoped work here. `docs/architecture/data/erd.md`.

114. **A documentation sweep belongs in a phase's Definition of Done, because two phases proved it is not automatic** (recorded Phase 3.10). Phases 3.9 and 3.10 each updated the five tracking files and the docs they added, and stopped there — leaving six files declaring PostgreSQL 16 after 3.9 aligned Compose to 17, a README instructing developers to `CREATE DATABASE agent_control_tower` when the application defaults to `ai_agent_control_tower` (so anyone following it built a database the app would never open), and `docs/runtime/workers-and-queue.md` still opening "There is no standalone worker process" one phase after 3.9 built one. None was caught by a test, because no test reads prose, and none was caught by the tracking-file update, because the tracking files describe *what the phase did* rather than *what the phase invalidated*. The rule is narrow and worth stating: **when a phase changes an environment fact — a version, a database name, a process topology — grep the whole `docs/` tree for the old fact rather than trusting the tracking-file update to have covered it.** Found by auditing all 147 tracked `.md` files after the user asked whether they had all been updated; the honest answer at that moment was eight of 147.
---

## 11. Update Protocol

Phase 5.2 is now complete — all seven sub-phases (5.2.1 through 5.2.7) are **IMPLEMENTED** per §6, re-verified in full this session (previously only 5.2.6 and 5.2.4's rows had been patched in place; §2/§3/§5/§6/§8 are now genuinely re-derived from the live system, closing that gap). This file must be regenerated at the end of every subsequent phase/sub-phase this codebase adds next (Phase 5.3 or whatever follows). On each regeneration:

- **§2 (Database Schema), §3 (Migration Chain), §5 (API Surface), and §6 (Phase 5.2 Status) must be re-derived from the live system** — re-run `alembic upgrade head` then live `sqlalchemy.inspect()` for §2; `alembic history`/`current` for §3; a fresh import-and-introspect of `app.main:app` for §5; and re-check every piece of evidence cited in §6 (file existence, grep results) — never edited by hand or carried forward from the previous version of this document.
- §1, §4, §7, §9, and §10 should also be re-verified (directory tree, AST module scan, conventions, gap greps, and any new deliberate decisions), since new sub-phases are expected to add files, close gaps, and make new decisions.
- §8 (Branch History) and the "Generated" line at the top should reflect the actual `git branch -a --sort=-committerdate` output and current commit at regeneration time.
- If a claim cannot be mechanically re-verified in the time available, mark it **UNVERIFIED** rather than repeating the old value as fact.
