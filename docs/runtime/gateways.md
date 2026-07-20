# Model Gateway & Tool Gateway

## Model Gateway (§40-§42, §4.5 model agnosticism)

`ModelGatewayService.invoke(version, input_payload)` is the *only* way a
worker calls a model — the provider is read from
`version.model_configuration.provider` (defaulting to `MOCK`), never
hardcoded per agent.

Only `MOCK` is a working adapter in this environment: it's fully
deterministic (no network call, no API key), returns a stub completion
referencing the configured `model` name, and reports token usage estimated
from payload length (`len(text) // 4`) so cost tracking has real numbers to
aggregate. Any other provider name — `OPENAI`, `ANTHROPIC`,
`AZURE_OPENAI`, `BEDROCK`, … — raises `MODEL_PROVIDER_UNAVAILABLE`
immediately rather than silently falling back to `MOCK` or failing in some
provider-specific way. This is the same "default deny" discipline (§36)
applied to model providers, not just permissions: an unconfigured provider
should be *loud*.

With only `MOCK` implemented, `invoke()` has no per-provider branching yet
— it *is* the mock behavior. Adding a real provider means giving `invoke()`
a provider dispatch and adding that provider's call (§41's contract:
`invoke`, `validate_configuration`, `estimate_cost`, `health_check`) plus
adding it to `SUPPORTED_PROVIDERS` — additive to this one method, not a
rewrite of the surrounding gateway; nothing about the caller
(`ExecutionWorkerService._execute`) or the `(output_payload, usage)` return
shape needs to change. Credentials would
be resolved via `deployment.secret_references` (§45) — never stored on the
agent version itself, which only ever holds a secret *reference* string
like `"vault://production/openai/api-key"`.

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
