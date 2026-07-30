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
"http_config"}}` — populated by copying each assigned tool's *current*
`http_config` by value at publish time, the same "never reference a
mutable record, copy values" discipline (§12) every other field in that
document already follows. `ToolGatewayService._invoke_http` reads the
allowlist from `AgentVersionSnapshot.snapshot["runtime"]["tool_configs"]`,
**never from `Tool.http_config` directly** — proven by
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

### Response caps — basic here, tuned in 5.6a.2

A per-tool `max_response_bytes` (default 1 MiB) aborts the transfer mid-
stream the moment it's exceeded — `http_executor` reads the response body
in chunks via `httpx`'s streaming API and stops as soon as the running
total crosses the cap, never buffering the whole thing first. A per-tool
timeout (via each tool's existing `timeout_seconds` column) terminates a
hanging call. Retry, timeout *tuning*, and circuit-breaking beyond this
basic cap are Phase 5.6a.2's job, not this one's.

## How one worker attempt composes both

`ExecutionWorkerService._execute`:

```python
output_payload, model_usage = ModelGatewayService().invoke(version, execution.input_payload)
for call_request in execution.input_payload.get("tool_calls", []):
    ToolGatewayService().invoke(db, execution, agent,
                                call_request["tool_name"], call_request["action"], call_request["params"])
```

Model invocation happens exactly once per attempt; tool calls happen zero
or more times, sequentially, in the order given in `input_payload`. A
tool-call failure propagates the same as a model failure (see retry policy
in [workers-and-queue.md](workers-and-queue.md)) — there is no partial-
success execution state; either the whole attempt succeeds or it doesn't.
