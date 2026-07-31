# Model Gateway & Tool Gateway

## Model Gateway (§40-§42, §4.5 model agnosticism)

`ModelGatewayService.invoke(version, input_payload)` is the *only* way a
worker calls a model — the provider is read from
`version.model_configuration.provider` (defaulting to
`settings.MODEL_DEFAULT_PROVIDER`, `"MOCK"`), never hardcoded per agent,
and never from mutable agent/deployment state (only the frozen version).

As of **Phase 5.7a.1**, provider resolution goes through a real,
pluggable interface and explicit registry — see
[providers.md](providers.md) for the full design (the `ModelProvider`
contract, the provider-neutral `ModelRequest`/`ModelResponse` types,
capability declaration/enforcement). `invoke()` itself is now just the
translation boundary between the legacy `input_payload: dict`/
`(output_payload, usage)` shape every caller here already depends on, and
the provider-neutral types every adapter actually speaks.

Two adapters are registered today: `MOCK` (fully deterministic, no
network call, no credential — reports a positive token count so cost
tracking has real numbers to aggregate) and `OPENAI_COMPATIBLE` (Phase
5.7a.2), which makes real HTTP calls — streaming (5.7a.3), classified
errors with retry/backoff/circuit-breaking (5.7a.4), and per-organization
encrypted credentials (5.7a.5, below) — against any OpenAI-chat-
completions-compatible endpoint (Ollama, vLLM, LM Studio, OpenAI itself).
Any unregistered provider name — `ANTHROPIC`, `AZURE_OPENAI`, `BEDROCK`, …
— raises `MODEL_PROVIDER_UNAVAILABLE` immediately rather than silently
falling back to `MOCK` or failing in some provider-specific way. This is
the same "default deny" discipline (§36) applied to model providers, not
just permissions: an unconfigured provider should be *loud*.

Adding a further real provider means one more `register(...)` call in
`app/runtime/providers/registry.py` and a new adapter module — additive,
not a rewrite of `invoke()`, the surrounding gateway, or the
`(output_payload, usage)` shape `ExecutionWorkerService` depends on.

### Credentials (Phase 5.7a.5, `ACT-MDL-FR-080..083`)

Credentials are **not** resolved via `deployment.secret_references` (§45)
— that field remains what it always was, a free-form JSONB dict of
reference *strings* (`"vault://..."`) with no actual storage or
resolution mechanism behind it, scoped to one deployment. A model-provider
API key is a distinct, org-wide concern (one org, one deployment or a
hundred, shares the same provider key), so it gets its own table,
`provider_credentials` — one row per `(organization_id, provider)`,
`encrypted_secret` a Fernet ciphertext, never plaintext at rest. See
[providers.md](providers.md#error-taxonomy--resilience-phase-57a4) and
its "Per-organization credentials" section for the full design: storage,
resolution order (per-org → `MODEL_PROVIDER_API_KEYS` fallback → none),
redaction, and the four CRUD/test API endpoints under
`/api/v1/runtime/providers/{provider}/credentials`.

Resolution happens once per execution, on the worker's own thread, via
`ProviderCredentialService.resolve_for_version` — *before* the model call
is handed to the `ThreadPoolExecutor` `ModelGatewayService.invoke()` runs
inside (§36's existing timeout mechanism), never inside it: only the
resulting plain, immutable `ResolvedCredential` value crosses into the
pooled thread, since a live SQLAlchemy `Session` is not safe to share
across threads.

## Tool Gateway (§43, §44)

See [capabilities-and-tools.md](capabilities-and-tools.md) for the full
authorization chain. The gateway contract
(`ToolGatewayService.invoke(db, execution, agent, tool_name, action,
params) -> ToolCall`) is provider-agnostic the same way the Model Gateway
is: a `tool_calls` row is always written (even on denial, `status=DENIED`),
so every attempted tool call is auditable regardless of outcome.

Two tool actions actually execute: `FUNCTION`'s built-in `EXECUTE`/`READ`
echo, unchanged since Phase 5.0, and (Phase 5.6a.1) `HTTP` — a real
outbound request, behind the egress control described below. Every other
tool type is fully modeled but fails closed with `TOOL_ACTION_NOT_ALLOWED`.

## Egress control (`HTTP` tool action, Phase 5.6a.1, `ACT-TLX-FR-001..013`)

**Why this exists.** The moment a tool can make an HTTP request whose
target is influenced by model output, there is a Server-Side Request
Forgery (SSRF) surface: a user's prompt can steer what the model asks a
tool to fetch. A weak allowlist lets an agent be induced to fetch cloud
metadata (`169.254.169.254`), reach internal services, or hit `localhost`
— on a multi-tenant platform holding regulated data, one SSRF hole is a
breach. This is not a feature bolted onto tool execution; it is the
containment boundary that makes real tools safe to ship at all.

### Two isolated modules, one job each

`app/runtime/tools/egress_guard.py` — **pure logic, no network, no
database.** Answers one question: given a target URL and a per-tool
policy, is this request permitted, and if not, which rule denied it.
Deliberately isolated so its correctness is verified exhaustively (every
known SSRF bypass technique, in milliseconds, no infrastructure) in
`backend/tests/runtime/test_egress_guard.py` — 32 tests, none touching a
network or a database.

`app/runtime/tools/http_executor.py` — the only code path that turns an
`EgressDecision` into a real connection. Builds the outbound request,
pins the connection to the validated address, follows redirects only by
re-running the guard on each hop, enforces the response-size cap and
timeout, and never lets the request URL be built from resolving
model-supplied text against the tool's base (see "The request target"
below).

### The rules, in order — every one fails closed

1. **Parse the URL.** Malformed → denied.
2. **Scheme must be `https`**, or `http` only if the tool definition
   explicitly permits plaintext *and* the target host is one of the
   definition's own declared local-development hosts (`ACT-TLX-FR-008`).
   This exception is narrow and explicit: declaring a host as local-dev
   does not allowlist it, and being on the allowlist does not make a host
   local-dev — both are required, independently, before plaintext (and,
   necessarily, that host's private address) is permitted. Without this
   dual requirement the exception would be unusable — a local-dev target
   is by definition going to resolve to a loopback/private address.
3. **Host must be on the tool's allowlist**, exact match (no implicit
   subdomain widening), case-insensitive.
4. **Resolve and validate.** Every resulting address must be public —
   `is_private`/`is_loopback`/`is_link_local`/`is_multicast`/`is_reserved`/
   `is_unspecified`, checked across IPv4, IPv6, and IPv4-mapped IPv6
   (`::ffff:127.0.0.1`, unwrapped and the embedded IPv4 address
   re-classified). One bad candidate among several denies the whole
   resolution — an attacker doesn't get to pick which answer is used.

**Alternate IP encodings are parsed explicitly, not left to the platform
resolver.** `ipaddress.ip_address()` rejects `"2130706433"` (decimal
127.0.0.1) and `"0177.0.0.1"` (octal) outright — but some platforms'
libc resolvers accept exactly these as IP literals during hostname
resolution (an `inet_aton`-family behavior real Linux deployments can
hit). Relying on that would make this guard's behavior platform-
dependent, so `egress_guard._parse_ip_literal` implements the same
decimal/octal/hex/partial-component parsing `inet_aton` does, unconditionally,
before any resolver is ever consulted.

### DNS-rebinding defense — pin, don't re-resolve (`ACT-TLX-FR-006`)

The naive "resolve, validate, then resolve again at connect time" pattern
*is* the rebinding vulnerability: an attacker's DNS answers public on the
security check and private on the real connection. This platform never
resolves twice. `evaluate_url` resolves and validates exactly once,
returning the validated IP; `http_executor._PinnedTransport` then
connects the actual socket **to that exact address**, never to a freshly
re-resolved hostname — there is no second lookup for a rebinding attacker
to win.

**The HTTP client can pin — verified, not assumed.** `httpx`/`httpcore`
(already a dependency) support rewriting a request's connection target
independently of its `Host` header via a custom `httpx.BaseTransport`,
and support TLS SNI override via the `sni_hostname` request extension
(`httpcore/_sync/connection.py`, confirmed in this session against the
installed version before writing this module). `_PinnedTransport`
rewrites `request.url` to the validated IP and sets
`extensions["sni_hostname"]` to the original hostname, while the `Host`
header (already set by `httpx` at request-construction time, before the
transport ever sees the request) is left untouched. Verified empirically
before writing this module's tests: a request built for a hostname that
does not even resolve via DNS still reaches a local test server bound to
the pinned IP, with the server-observed `Host` header intact — see
`test_connection_is_pinned_to_the_validated_ip_not_a_fresh_lookup`, which
proves the resolver is consulted exactly once per request regardless of
what a second call would have returned. **No residual rebinding risk from
an unpinnable client** — this platform's HTTP client can and does pin.

### Redirects — never auto-followed (`ACT-TLX-FR-007`)

`httpx`'s built-in `follow_redirects=True` connects to each hop without
re-running the egress guard — exactly the hole this exists to close.
`follow_redirects=False` is set explicitly; every redirect hop is instead
re-evaluated from scratch by URL, against the same policy, with a
`max_redirects` depth cap (default 5, per-tool configurable) enforced
independently of however many hops a chain that stays *within* the
allowlist takes.

### The request target — model output can shape a path, never a host (`ACT-TLX-FR-010`)

The actual request URL is always `tool.endpoint_reference` (the tool's
own declared, allowlisted base) plus, at most, a *path* component a tool
call's `params` supplies. `http_executor._build_target_url` never
resolves the supplied text as a URL against the base the way
`urllib.parse.urljoin` would — `urljoin("https://good/", "https://evil/")`
returns `"https://evil/"`, exactly the hijack this must never allow.
Instead, only `urlsplit(params["path"]).path` is taken — a caller
supplying an absolute or protocol-relative URL contributes only its path
component; the host is always the tool's own.

### The allowlist is frozen in the version snapshot, not runtime-mutable

**This was Milestone 1 SRS open item OI-3; decided here**: the egress
allowlist is **per-tool, declared in the tool definition, and frozen into
the published version's snapshot document at publish time** — not
per-organization, and not mutable after publish. Rationale: the allowlist
is part of what was reviewed and signed when the version was published;
letting it be widened afterward at the tool level would let someone
expand an already-signed tool's reach without re-review, defeating the
whole point of immutable versioning. An organization-level *ceiling* (a
deny-list no tool may exceed, layered as defense-in-depth) may be added
later — it is explicitly **not** built here.

**Where the freeze actually lives, and why `tools_snapshot` itself was
not touched.** `AgentVersion.tools_snapshot` is a bare list of tool-*id*
strings, consumed as exactly that shape by three existing subsystems —
`AttestationService` (builds a manifest entry per id), `VersionComparisonService`
(`set()`-diffs it against a baseline — a `list[dict]` would raise
`TypeError: unhashable type`), and `CompatibilityAnalysisService`.
Changing its element type to carry full tool config would have broken
all three. Instead, `SnapshotBuilderService.build_snapshot()` gained a
new key, `runtime.tool_configs` — `{tool_id: {"name", "tool_type",
"http_config", "input_schema", "output_schema"}}` (the last two added by
Phase 5.6a.2, see below) — populated by copying each assigned tool's
*current* `http_config`/`input_schema`/`output_schema` by value at
publish time, the same "never reference a mutable record, copy values"
discipline (§12) every other field in that document already follows.
`ToolGatewayService._invoke_http` reads the allowlist from
`AgentVersionSnapshot.snapshot["runtime"]["tool_configs"]`, **never from
`Tool.http_config` directly** — proven by
`test_allowlist_is_read_from_frozen_snapshot_not_mutable_tool_state`,
which widens a tool's live allowlist after publish and confirms the
already-published version's enforcement is unaffected. A tool assigned to
an agent but never included in a version's `tools_snapshot` at publish
time has no entry in `tool_configs` at all and is rejected outright
(`TOOL_ACTION_NOT_ALLOWED`) — "verified against the frozen snapshot" in
the most literal sense: no entry, no policy, no request.

### Credentials (`ACT-TLX-FR-012`)

`tool_credentials` — a new table, the same shape and the same encryption
utility (`app/runtime/providers/credential_crypto.py`) Phase 5.7a.5 built
for model-provider credentials, reused directly. A deliberately separate
table from `provider_credentials`, not a reuse of it: a tool credential
authenticates to an arbitrary third-party API, a model-provider
credential to a registered model provider identifier — different enough
resources that overloading one table's `provider` column with a tool name
would blur the distinction for no real benefit. `ToolCredentialService`
is a smaller surface than `ProviderCredentialService` (`store`/
`resolve_secret`/`delete` only, no fallback chain, no CRUD API in this
sub-phase — likely unnecessary HTTP surface per the build prompt's own
scope guidance) since nothing here needs the extra machinery yet.

Resolved once per HTTP tool call, inside `ToolGatewayService._invoke_http`,
and injected as a header (`credential_header`, default `Authorization`;
`credential_scheme`, default `Bearer` — both tool-declared). The frozen
snapshot only ever carries `http_config.requires_credential: bool` — a
fact, never a value (`ACT-VER-FR-024`, the same reference-not-value rule
`deployment.secret_references` already followed).

### Redaction (`ACT-TLX-FR-013`)

A tool definition declares `sensitive_headers`/`sensitive_body_fields`
(defaulting to `["Authorization"]` for headers). The actual outbound
request always carries the real values — redaction only ever affects what
is *recorded*: the `ToolCall.input_summary._request_headers` field (the
headers actually sent, with sensitive ones replaced by `***REDACTED***`)
and `ToolCall.output_summary.body` (the response body, with declared
sensitive fields in a JSON object redacted the same way). No credential
value ever reaches a `ToolCall` row, a log line, a `RuntimeEvent`, or an
error message — composes with Phase 5.7a.4's adapter-level scrubbing
discipline for the model side.

### Recording (`ACT-TLX-FR-011`) and the security event

Every `HTTP` tool call writes `target_host`, `target_path`, `http_method`,
`http_status`, `request_bytes`, `response_bytes`, `egress_decision`
(`ALLOWED`/`DENIED`), and `egress_denied_reason` (the exact rule that
fired, e.g. `HOST_NOT_ALLOWLISTED`/`PRIVATE_ADDRESS`/`SCHEME_NOT_ALLOWED`)
on the `ToolCall` row — all nullable, all `null` for `FUNCTION`/`echo`
rows, unchanged. A denial also emits `RUNTIME_TOOL_EGRESS_DENIED` at
`CRITICAL` severity — an egress denial is a signal someone may be probing
the boundary, routed to alerting the same way a kill-switch activation
is. A successful call emits `RUNTIME_TOOL_INVOKED` at the default `INFO`
severity. The error an untrusted caller/model actually sees on denial
names the tool, never the target host, resolved IP, or which internal
rule fired (`ACT-TLX-FR-069`'s equivalent for tools) — that detail lives
only on the `ToolCall` row and the security event, both admin-only.

### Response caps — basic in 5.6a.1, per-tool configurable since 5.6a.2

A per-tool `max_response_bytes` (default 1 MiB) aborts the transfer mid-
stream the moment it's exceeded — `http_executor` reads the response body
in chunks via `httpx`'s streaming API and stops as soon as the running
total crosses the cap, never buffering the whole thing first. See
"Schema validation & resilience" below for how the size and timeout caps
became per-tool configurable and frozen (5.6a.2 closed a gap here: 5.6a.1
read the size cap from the frozen snapshot already, but the *timeout* was
still read from the live, mutable `Tool.timeout_seconds` column at
execution time).

## Schema validation & resilience (`HTTP` tool action, Phase 5.6a.2, `ACT-TLX-FR-020..029`)

**Why this is a separate concern from egress control.** 5.6a.1 made tool
calls *safe* — egress security fails *open* if wrong (a breach), so it was
built and reviewed in isolation. This sub-phase makes tool calls *correct
and resilient* — it fails *loud* if wrong (a rejected call or a wasted
retry), a different risk profile entirely. Nothing in this section changes
an egress/SSRF rule; nothing in the section above changed for this phase.

### The unifying idea: reuse the 5.7a.4 taxonomy, don't duplicate it

Phase 5.7a.4 built an eight-class, provider-neutral failure taxonomy
(`app.runtime.providers.types.ProviderErrorClass`), retry-with-backoff for
the three transient classes, and a per-identifier circuit breaker — all
for model-provider calls. A tool's HTTP call has the exact same shape of
problem (a target 429/503/timeout is transient; a 400 or a schema
violation is not), so this sub-phase **reuses that machinery** rather than
building a second, parallel one.

**How neutral the 5.7a.4 build actually was, honestly assessed:** the
*state machine* (`_ProviderCircuitState`, now renamed `_CircuitState`) was
already provider-neutral — a plain dict keyed by any string identifier,
with no provider-specific data in it. The backoff formula
(`_provider_backoff_delay`) was pure math, parameterized only by
`settings.MODEL_PROVIDER_RETRY_*`. But **what happens when the circuit is
open** was not neutral: `_circuit_before_call` raised
`ProviderRequestFailedError` directly — a model-specific exception type a
tool call must never raise (see "Failures never abort the execution"
below). So this sub-phase extracted the neutral core —
`_circuit_is_open`/`_circuit_note_success`/`_circuit_note_failure`/
`_backoff_delay`, all in `services.py`, none mentioning "provider" or
"tool" — and rebuilt both the existing model-side functions
(`_circuit_before_call`/`_circuit_record_success`/`_circuit_record_
failure`/`_provider_backoff_delay`, **same signatures, same behavior**,
verified by every pre-existing 5.7a.4 test passing unmodified) and a new,
parallel tool-side set (`_tool_circuit_is_open`/`_tool_circuit_record_
success`/`_tool_circuit_record_failure`/`_tool_backoff_delay`) on top of
it. Two separate module-level state dicts (`_provider_circuit_state`,
`_tool_circuit_state`) — a burst of tool failures can never trip a model
provider's breaker or vice versa — and two separate settings namespaces
(`MODEL_PROVIDER_CIRCUIT_*`/`MODEL_PROVIDER_RETRY_*` vs. `TOOL_CIRCUIT_*`/
`TOOL_RETRY_*`), same "equal jitter" formula, same three-state (closed/
open/half-open) semantics, same in-process-only, not-persisted-across-
restart limitation as the model side.

`ProviderErrorClass` itself (`RATE_LIMITED`, `PROVIDER_UNAVAILABLE`,
`TIMEOUT`, `AUTHENTICATION_FAILED`, `INVALID_REQUEST`, `UNKNOWN`, plus two
model-only values a tool's HTTP response never produces) is reused
**unchanged** — a tool's HTTP status/transport failure is classified into
this exact enum by `services._classify_tool_execution_failure`, mirroring
`openai_compatible._classify_status_error`'s own status-code buckets
(429→`RATE_LIMITED`, 401/403→`AUTHENTICATION_FAILED`, 5xx→
`PROVIDER_UNAVAILABLE`, other 4xx→`INVALID_REQUEST`). Two tool-specific
conditions with no natural bucket in a taxonomy built for model-provider
failures — `RESPONSE_TOO_LARGE` and `REDIRECT_DEPTH_EXCEEDED` — map
deliberately to `UNKNOWN`: `UNKNOWN` already guarantees "never retried,"
which is exactly correct for both (retrying either reaches an identical
outcome against the same target every time; neither is actually
transient).

### Schema declaration and validation (`ACT-TLX-FR-020..022`)

`Tool.input_schema`/`Tool.output_schema` (JSON Schema, pre-existing
columns from Phase 5.0's original tool model — unused by the execution
path until now) are frozen into `tool_configs[tool_id]` at publish time
alongside `http_config`, for the same reason the allowlist is: a tool's
contract must be exactly as immune to being widened for an already-
published version as its egress declaration already was.

Validation order, inside `ToolGatewayService.invoke`: **arguments are
validated before anything else that could have a side effect** — before
`FUNCTION`'s echo, and before the `HTTP` branch even builds an
`EgressPolicy`, let alone resolves DNS (no point evaluating egress for a
call whose arguments are already invalid). A violation short-circuits
with `TOOL_SCHEMA_INVALID`, a structured (JSON-encoded)
`ToolCall.validation_error` describing exactly what was wrong (the
`jsonschema.ValidationError.message`, `.absolute_path`, and
`.absolute_schema_path`), and **no request is issued**. Validation reuses
the same `jsonschema` library (and the same tool-parameter JSON-Schema
shape already sent to a model) the pre-existing agent-level
`_validate_schema` uses — no second schema language.

A response is validated against `output_schema` **only when one is
declared** — absent, it's skipped entirely rather than guessed at
(§10.15's raise-don't-guess principle), and a successful HTTP response
with no declared output contract is simply `ALLOWED`. An output violation
is reported the same structured way as an input one, but only *after* the
request has actually been issued (the side effect, if any, already
happened — nothing can undo that) — and, unlike a genuine HTTP-level
failure, it never touches the circuit breaker: the target responded
correctly by its own lights, so this is this platform's own contract
check failing, not a signal about the target's reliability.

### The idempotency gate — the critical safety property here (`ACT-TLX-FR-025..026`)

Retrying a non-idempotent tool call — a payment, a message send, a
resource creation — can duplicate a real-world side effect. **Idempotency
is an explicit, opt-in declaration on the tool** (`http_config.idempotent:
true`), never inferred from the HTTP method: `GET`/`HEAD` are
conventionally "safe," but a `GET` *can* trigger a side effect, and a tool
author may know better than a convention. **Undeclared means
non-idempotent means never retried — fail safe.**
`test_idempotency_governed_by_declaration_not_http_method` proves this
directly: a `READ` action (which maps to `GET`) explicitly declared
`idempotent: false` still does not retry on a transient failure.

Only a transient classification (`RATE_LIMITED`/`PROVIDER_UNAVAILABLE`/
`TIMEOUT` — the same `RETRYABLE_PROVIDER_ERROR_CLASSES` set the model side
uses) on a tool declared idempotent ever retries; a schema violation, a
`400`/other non-transient status, or an undeclared/`false` idempotency
flag never does, regardless of classification.

### Per-tool caps, now frozen and configurable (`ACT-TLX-FR-023..024`)

`http_config.timeout_seconds` and `http_config.max_response_bytes` are
both read from the frozen snapshot at execution time — never from the
live `Tool` row. `snapshot.py`'s `_frozen_http_config` defaults
`timeout_seconds` in from the tool's own (coarser, always-present)
`timeout_seconds` column at publish time if `http_config` didn't already
declare a more specific one of its own, closing the one gap 5.6a.1 left
open (its `_invoke_http` read `tool.timeout_seconds` live, at execution
time — the only per-tool value in that sub-phase that wasn't actually
frozen). `test_size_and_timeout_are_read_from_the_frozen_snapshot` proves
it the same way the allowlist's own frozen-not-mutable test does: widen
both the live `http_config` and the live `timeout_seconds` column after
publish, confirm the already-published version's enforcement is
unaffected.

### Per-execution concurrency ceiling (`ACT-TLX-FR-029`)

`app/runtime/tools/concurrency.py` — a small, pure, in-process tracker (no
network, no database, the same isolation discipline `egress_guard.py`
established), keyed by execution id, guarded by a single lock.
`ToolGatewayService._invoke_http` reserves a slot for the duration of each
actual outbound request (never around schema validation, an open-circuit
fast-fail, or the backoff sleep between retries) and releases it
immediately after. Today's `ExecutionWorkerService` issues tool calls
strictly sequentially — this ceiling is never actually contended in
production yet; it exists as the enforcement point 5.6a.3's model-driven
loop (which *will* be able to issue multiple calls from one execution
concurrently) plugs into without needing a new mechanism. Tested directly
with real threads (`test_concurrency_ceiling_is_enforced`), since today's
sequential caller can't exercise contention on its own.

### Failures never abort the execution (`ACT-TLX-FR-028`)

This is the behavioral line this sub-phase draws between two kinds of
`ToolCall` outcome, and it is a genuine change from 5.6a.1:

- **`DENIED`** — a governance/authorization/egress-policy fact
  (`TOOL_NOT_FOUND`/`TOOL_NOT_ASSIGNED`/`TOOL_ACTION_NOT_ALLOWED`/
  `TOOL_CONSTRAINT_VIOLATION`/`TOOL_EGRESS_DENIED`). Unchanged from before
  this sub-phase: `ToolGatewayService.invoke` still raises, and that
  exception still fails the whole execution (see
  `test_egress_denial_writes_decision_and_reason_and_fails_the_execution`,
  passing unmodified).
- **`FAILED`** (new in 5.6a.2) — the outcome of an *attempted* invocation:
  a schema violation, a transient failure whose retries were exhausted (or
  weren't idempotent), a timeout, an oversized response, an open circuit,
  or a concurrency-ceiling rejection. `ToolGatewayService.invoke` **does
  not raise** for this status — it returns the `ToolCall` row normally,
  `ExecutionWorkerService._execute`'s tool-calls loop simply continues,
  and the execution proceeds to `SUCCEEDED` (assuming nothing else fails).
  The structured error — `error_code`, `error_class`, and (for a schema
  violation) `validation_error` — lives on that row, plus a
  `RUNTIME_TOOL_FAILED` event (this platform's `RUNTIME_*`-convention
  realization of the SRS's conceptual `execution.tool.failed` event, the
  same relationship `RUNTIME_EXECUTION_FAILED` already has to "the
  execution failed").

This sub-phase produces that structured error and returns it from the
single tool call — it does **not** build the loop that would feed it back
to the model and let it correct course. That loop is 5.6a.3's job; today,
absent that loop, a failed tool call is simply a recorded fact the
execution completes around.

### Attempt recording — one `ToolCall` row per attempt

A retried idempotent call gets a **new** `ToolCall` row per attempt (not
one row mutated in place), each with its own `attempt_number` (1, 2, 3…),
`error_class`, `started_at`/`completed_at`/`duration_ms`. Every
non-final attempt is flushed to the database before its backoff sleep (so
the retry history is durable even if the process were to die mid-retry);
only the final row is left for `invoke()`'s own uniform completion logic.
A call that never retries still gets `attempt_number = 1` recorded, so the
column is always populated for anything that reached an actual invocation
attempt (schema-rejected and governance-denied calls leave it `null` —
they never attempted anything).

### New error codes

`TOOL_SCHEMA_INVALID` (422 — input or output validation failure),
`TOOL_RESPONSE_TOO_LARGE` (502), `TOOL_TIMEOUT` (504),
`TOOL_EXECUTION_FAILED` (502 — the generic bucket for a classified
HTTP-status/transport failure that wasn't one of the more specific three
above), `TOOL_CONCURRENCY_LIMIT_EXCEEDED` (429). `TOOL_EGRESS_DENIED` and
`TOOL_ACTION_NOT_ALLOWED` (5.6a.1) are unchanged.

## The model-driven tool invocation loop (Phase 5.6a.3, `ACT-TLX-FR-040..049`)

**This is Milestone 1's completion piece.** Everything above this section
makes a tool call *safe* (5.6a.1) and *correct and resilient* (5.6a.2) —
but until this phase, nothing actually connected a model's own tool
request to that machinery. `ModelGatewayService.invoke()` never offered
`tools` to a provider at all, and the only way a tool ever ran was a
caller (a human, a test) hand-writing `input_payload["tool_calls"]` —
never the model itself. `ToolLoopOrchestrator` (`services.py`) closes that
gap: model requests a tool → the platform executes it (through
`ToolGatewayService.invoke()`, completely unchanged) → the result is
appended to the conversation → the model is called again → until a final
answer or one of four independent safety caps ends it.

### The pre-existing explicit mechanism is untouched, not replaced

`ExecutionWorkerService._execute` still has both:

```python
output_payload, model_usage, tool_usage = ToolLoopOrchestrator(self.db).run(
    execution, agent, version, resolved_credential, timeout_seconds=timeout_seconds,
)
# Pre-existing explicit input_payload["tool_calls"] mechanism (Phase 5.0),
# completely unchanged — still handled here, still counted separately.
for call_request in execution.input_payload.get("tool_calls", []):
    ToolGatewayService().invoke(db, execution, agent,
                                call_request["tool_name"], call_request["action"], call_request["params"])
    tool_usage["calls"] += 1
```

`ToolLoopOrchestrator.run()` always runs — but it's a no-op wrapper around
today's exact single model call whenever no tools are offered: `MOCK`
(`describe().supports_tools == False`, always) never receives a `tools`
list at all (`ModelGatewayService.invoke()` checks the provider's own
declared capability before ever populating `ModelRequest.tools`), so it
returns `finish_reason=STOP` on the first call exactly as it always has,
and the loop ends immediately with one iteration. Every 5.6a.1/5.6a.2 test
uses `MOCK` with the explicit mechanism above — this is why all of them
pass completely unmodified (`AC-02`, `AC-21`, `AC-24`): the new loop
genuinely never engages for them.

### `ModelGatewayService.invoke()` — additive, not rebuilt

Two new, both-optional keyword parameters, mirroring `resolved_credential`'s
own precedent exactly: `conversation: tuple[ModelMessage, ...] | None` (the
full accumulated transcript so far — when absent, the single
`json.dumps(input_payload)` user message every pre-5.6a.3 caller already
gets, unchanged) and `tools: tuple[ModelToolDefinition, ...] | None` (only
ever populated by `ToolLoopOrchestrator`, from this version's frozen
`tools_snapshot`). The returned `usage` dict gains one new key,
`tool_calls` — a plain, JSON-safe `[{"id", "name", "arguments"}, ...]` list,
empty whenever the model didn't request one (every existing caller,
always) — the `(output_payload, usage)` contract itself never changes
shape (`AC-06`).

### Tool binding — the model can only use what was signed into the version

Every tool the model may request is read from the frozen
`AgentVersionSnapshot.snapshot["runtime"]["tool_configs"]` — the exact
same source `ToolGatewayService`'s own `_frozen_tool_entry` reads from,
keyed by name instead of id (`ToolLoopOrchestrator._frozen_tool_entries`).
A tool name the model returns that isn't in this set is rejected with
`TOOL_NOT_BOUND_TO_VERSION` — the model cannot invent tools, or reach one
assigned to the agent but never included in *this* published version's
snapshot (`ACT-TLX-FR-045`). This is treated as a scope violation, the
same tier as `TOOL_NOT_ASSIGNED` — it aborts the execution rather than
being fed back as a recoverable failure, deliberately: letting a model
freely probe for tool names that don't exist is exactly the kind of
boundary-testing 5.6a.1's SSRF-conscious posture already treats as
something to stop, not something to let a model iterate its way past.
This is also §10.4's enforcement point for the loop: the only thing it
can ever call is `ToolGatewayService.invoke()`, bound to a `Tool` row —
there is no tool shape that names an `Agent`, and no code path here that
reaches `ExecutionRequestService` at all. A model naming a real second
agent's identifier is simply an unbound tool name, rejected the same way
as any other (`AC-07`).

Every tool call the loop makes — sequential or parallel — still goes
through `ToolGatewayService.invoke()` completely unchanged, so the
existing assignment/`allowed_actions`/constraint checks still run for
every one of them (`AC-05`, `ACT-TLX-FR-046`): a tool bound to the version
but never assigned to the agent via `AgentTool` still fails with
`TOOL_NOT_ASSIGNED`, exactly as it would for the explicit mechanism.

**The action is always `EXECUTE`.** The model's tool-call interface has no
notion of the platform's `READ`/`WRITE`/`EXECUTE`/... action vocabulary —
an LLM tool call is just a name and arguments. The loop always invokes
with `action="EXECUTE"`; a tool's `allowed_actions` assignment must
include it. `arguments` is passed to `ToolGatewayService.invoke()` as
`params`, completely unchanged in shape — a tool's declared `input_schema`
(already frozen and validated by 5.6a.2) is what actually tells the model,
and the validator, what shape of arguments a given tool expects, whether
that's semantic fields for a `FUNCTION` tool or `{path, query, body}` for
an `HTTP` one. The loop adds no translation layer of its own.

### Termination — four independent caps, any one ends the loop

5.6a.2 made a `FAILED` tool result recoverable — which means a model that
keeps retrying an always-failing tool can keep the loop running forever,
burning real tokens and money. Four independent conditions guard against
this, each ending the loop with its own distinct, audited
`termination_reason` (`agent_executions.termination_reason`) and a shared
`error_code`, `TOOL_LOOP_LIMIT_EXCEEDED` (added to `_fail_or_retry`'s
`non_retryable` set — a cap breach reaches the identical outcome on any
retry):

| `termination_reason` | Trigger |
|---|---|
| `COMPLETED` | `finish_reason != TOOL_CALLS` — a normal final answer. |
| `MAX_ITERATIONS` | More than `settings.TOOL_LOOP_MAX_ITERATIONS` (default 10; overridable via `deployment.runtime_limits.maximum_loop_iterations`, mirroring the existing `maximum_retries`/`maximum_execution_seconds` pattern) model turns. |
| `TOKEN_BUDGET` | Cumulative `total_tokens` across every iteration exceeds `settings.TOOL_LOOP_MAX_TOTAL_TOKENS` (default 50,000). |
| `WALL_CLOCK` | Elapsed wall-clock time across the whole loop exceeds `settings.TOOL_LOOP_MAX_WALL_CLOCK_SECONDS` (default 120s) — a new, additional cap layered on top of the existing per-model-call `timeout_seconds`, which still bounds each individual call exactly as it always has. |
| `REPEATED_CALL` | The model requests a `(tool, arguments)` pair identical to one it already made this execution. |

**`REPEATED_CALL` fires before the duplicate is even executed, not after
the iteration cap.** A repeat is non-productive by definition — the same
call reaches the same outcome every time — so waiting for the iteration
cap would just waste N more wasted model calls first. "Identical" reuses
Phase 5.2.4's canonical serialization
(`canonical.digest(canonical.stringify_floats({"tool": name, "arguments":
arguments}))`) — the same discipline that makes a version's checksum
reproducible — so key ordering and float representation can't produce a
false negative. Every call actually attempted in this execution (any
iteration) is tracked; the check runs against the whole batch a turn
requests, before any of them execute, so a repeat anywhere in a parallel
batch stops the *entire* batch.

A model that always retries an always-failing tool (`AC-13`) still
terminates in bounded iterations and bounded tool requests — proven with a
tool declared non-idempotent (so 5.6a.2's own retry never kicks in either)
and a transport that returns a *different* argument each turn (so
`REPEATED_CALL` doesn't intervene first), confirming `MAX_ITERATIONS`
alone is sufficient backstop.

### Parallel tool calls — real concurrency, finally exercised

`app/runtime/tools/concurrency.py`'s per-execution ceiling (5.6a.2) was
wired but never contended — this is where that changes
(`ACT-TLX-FR-044`). When a model returns more than one tool call in a
single turn, `ToolLoopOrchestrator._execute_calls` runs them concurrently
**only when every tool in the batch is declared `idempotent: true`**
(the same 5.6a.2 flag, reused for a second purpose: "safe to run more than
once" is the same property as "safe to run alongside its own siblings
without a coordination guarantee"). A single non-idempotent tool anywhere
in the batch drops the *entire* batch to sequential, model-given order —
conservative by construction, never assumed parallel-safe by default
(`AC-18`). A `FUNCTION` tool has no `idempotent` flag concept at all and
is always treated as safe (no real side effect to duplicate).

Each parallel call runs on its own thread with its own, fresh `Session` —
`ToolGatewayService.invoke()` runs unmodified, but a live SQLAlchemy
`Session` is not safe to share across threads (the same constraint that
already keeps model invocation off `self.db`). Only a plain
`_ToolCallSnapshot` (`status`/`error_code`/`error_class`/`output_summary`/
`validation_error`) crosses back out of each thread — never the ORM row
itself. Results are collected by original submission index, not
completion order, so a slower call earlier in the model's list still
reassembles before a faster one later in it (`AC-16`) — proven with call 1
deliberately the slowest. One call failing among several succeeding
(`AC-17`) is unremarkable: it's a normal `FAILED` result like any other,
the others still succeed, and the loop continues.

**A genuine deadlock, found and fixed before any of this shipped.**
`ExecutionWorkerService.claim_next` claims an execution with `SELECT ...
FOR UPDATE SKIP LOCKED` and holds that lock for the whole attempt's one
long-lived transaction (correct, and untouched — the queue/worker model is
not this phase's to change). The first version of parallel execution
opened a fresh `Session` per thread and had each one `INSERT INTO
tool_calls` — which references the still-`FOR UPDATE`-locked
`agent_executions` row via a foreign key. Postgres's FK check needs a
`FOR KEY SHARE` lock on that row, which conflicts with the outstanding
`FOR UPDATE` and blocks; meanwhile the *main* thread is blocked inside
`future.result()` waiting for that same worker — a real deadlock between
an application-level thread-join and a database-level lock wait that
Postgres's own detector cannot see (the main connection looks merely idle
from its side, not waiting on anything). The fix:
`ToolLoopOrchestrator._execute_parallel` commits `self.db` immediately
before spawning any thread. This is safe — `claim_next` already
transitioned the row out of `QUEUED` long before this method can run, so
the lock has already done its one job (preventing a second worker from
claiming the same row); releasing it early costs nothing, and
`SessionLocal` is configured `expire_on_commit=False`
(`app/core/database.py`), so `execution`/`agent` stay fully usable on the
main thread afterward with no re-fetch needed. Found by reproducing the
hang directly against `pg_stat_activity` (both sides showed `Lock` /
`transactionid` waits on the same row) before writing this explanation —
not guessed at.

### Streaming stays out of the loop, for now

Every model call inside the loop uses non-streaming `invoke()`, regardless
of `model_configuration.stream`. An intermediate turn that only requests
tools has no user-visible content to stream in the first place — its
"output" is a tool request, not prose. Whether a *final* answer turn
should stream out to a caller is a UI/delivery concern this sub-phase
deliberately leaves alone rather than entangling with loop mechanics;
5.7a.3's real incremental streaming is untouched and still available to
any non-loop caller.

### Transcript persistence — `execution_messages` (new table)

Did not exist before this phase (checked first, per the build prompt's own
instruction). One row per turn: the initial `user` message, every
`assistant` turn (a final answer, or a tool request — `tool_calls_
requested` carries the raw `[{"id","name","arguments"}, ...]` on that
row), and every `tool` result (`tool_call_id` pairs it back to the request
it answers) — in strict `sequence` order, exposed at `GET /executions/
{id}/messages`. Per-iteration token/cost/duration accounting
(`ACT-TLX-FR-047`) lives on each `assistant` row, computed by calling
Phase 5.7a.3's `PricingService` once per turn — reused, not rebuilt;
`agent_executions`' own `prompt_tokens`/`completion_tokens`/`total_tokens`/
`cost_amount` remain the *sum* across every iteration, computed by the
exact same, unmodified post-loop code `_execute` already had for a
single-turn call. `agent_executions.loop_iterations`/`termination_reason`
are the two new columns recording how the loop actually ended.

A `FAILED` tool result (a schema violation, a timeout, an exhausted
retry, a concurrency-ceiling rejection...) is appended to the transcript
as a `tool`-role message with the same `error_code`/`error_class`/
`validation_error` an admin already sees on the `ToolCall` row — so the
*next* model turn genuinely sees, and can act on, exactly what went wrong
(`AC-21`).

### New error codes and events

`TOOL_NOT_BOUND_TO_VERSION` (403), `TOOL_LOOP_LIMIT_EXCEEDED` (429 — covers
all four safety-cap terminations, distinguished by `termination_reason`,
not a separate code per reason). `RUNTIME_LOOP_ITERATION` (INFO, per
assistant turn) and `RUNTIME_LOOP_TERMINATED` (INFO for `COMPLETED`,
CRITICAL for any cap breach) — this platform's `RUNTIME_*`-convention
realization of the SRS's conceptual `execution.loop.iteration`/
`execution.loop.terminated` events, matching the same relationship
`RUNTIME_EXECUTION_FAILED` already has to "the execution failed."

## How one worker attempt composes both

`ExecutionWorkerService._execute`, in full:

```python
output_payload, model_usage, tool_usage = ToolLoopOrchestrator(self.db).run(
    execution, agent, version, resolved_credential, timeout_seconds=timeout_seconds,
)
for call_request in execution.input_payload.get("tool_calls", []):
    ToolGatewayService().invoke(db, execution, agent,
                                call_request["tool_name"], call_request["action"], call_request["params"])
    tool_usage["calls"] += 1
```

The loop orchestrator runs exactly once per attempt (one or more model
turns inside it); the pre-existing explicit mechanism still runs zero or
more times afterward, sequentially, exactly as it always has. A tool call
that is **denied** (governance/authorization/egress policy, or a model
naming a tool outside `tools_snapshot`) still propagates and fails the
whole attempt (see retry policy in
[workers-and-queue.md](workers-and-queue.md)). A tool call that **fails**
(a schema violation, an exhausted retry, a timeout, an oversized response,
an open circuit, a concurrency-ceiling rejection) does not — the loop
continues, and the structured error lives both on that call's own
`ToolCall` row and, since 5.6a.3, on the transcript the next model turn
actually reads.

## Milestone 1 — complete

An agent registered, versioned, signed (Phase 5.2.4), and deployed can now
genuinely execute end to end: it calls a real model (`OpenAICompatibleProvider`,
streaming, real token/cost accounting, the eight-class error taxonomy,
retry with backoff, per-provider circuit breaking, per-organization
encrypted credentials), the model requests a real tool, that tool runs
behind an exhaustively-tested SSRF egress guard with schema-validated
arguments and resilient, idempotency-gated retry, the result feeds back,
the model produces a final answer, and every token, every call, every
decision along the way is audited — see
`test_end_to_end_registered_versioned_agent_calls_model_and_real_tool` in
`backend/tests/runtime/test_tool_loop.py` for the proof. What remains
before this is a product someone would actually run in front of real
traffic is everything Milestones 2+ and the platform's own roadmap
already name — governance policy evaluation mid-loop (5.8), multi-agent
delegation (Milestone 10, and explicitly not this), distributed workers
(Milestone 3). What this milestone was for — proving the platform
*works* — is done.
