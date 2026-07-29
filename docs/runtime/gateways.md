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
