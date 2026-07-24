# Model Provider Abstraction

`backend/app/runtime/providers/` · Phase 5.7a.1 SRS `ACT-MDL-FR-001..010`.

## Why this exists

Every layer above the runtime — registry, versioning, signing, governance,
authorization — has been built and tested against a real executing agent.
Until this phase, "executing" meant `ModelGatewayService` running a single
hardcoded `MOCK` branch and failing closed (`MODEL_PROVIDER_UNAVAILABLE`)
for anything else. This phase replaces that branch with a real interface,
a registry, and a provider-neutral internal representation — proven by
migrating `MOCK` onto it with **zero change in observable behavior**. No
real provider is implemented here; that's Phase 5.7a.2, deliberately kept
separate so the interface's shape isn't distorted by one concrete
implementation's assumptions while it's still being designed.

## The contract (`base.py`)

```python
class ModelProvider(ABC):
    def complete(self, request: ModelRequest) -> ModelResponse: ...   # abstract
    def stream(self, request: ModelRequest) -> Iterator[ModelResponse]: ...  # abstract
    def describe(self) -> ModelCapabilities: ...                      # abstract
    def supports(self, capability: str) -> bool: ...                  # concrete, derived from describe()
    def validate_capabilities(self, request: ModelRequest) -> None: ...  # concrete, shared helper
```

`complete()`, `stream()`, and `describe()` are abstract — a subclass
missing any one of them cannot be instantiated (Python's `ABC` machinery
enforces this; see `test_subclass_omitting_a_required_method_fails_to_
instantiate`). `supports()` is deliberately **not** abstract: it has a
single, correct, shared implementation derived entirely from `describe()`,
so a provider's answer to "do you support tools?" can never contradict its
own capability declaration. A provider may still override it, but doesn't
have to.

`validate_capabilities(request)` is a shared helper every concrete
provider's `complete()`/`stream()` calls explicitly at the top (see
`MockProvider.complete()`) — it is **not** wired in automatically via a
template-method wrapper. That was a deliberate choice: the method a
provider overrides (`complete()`) is exactly the one this document and the
interface itself name, with no renamed hook underneath it. The cost is
that a future adapter must remember to call it; the benefit is there's
nothing indirect to explain.

### The one deliberate stub

`stream()` is abstract — every provider, including `MockProvider`, must
supply its own implementation — but the *base class's* body raises
`NotImplementedError`. This is unreachable through normal instantiation
(you can't instantiate a subclass that hasn't overridden `stream()` at
all), but it means a subclass that only nominally overrides `stream()` by
delegating straight back to `super().stream(...)` fails loudly instead of
silently returning `None`. Real incremental streaming — actually yielding
partial chunks as a provider produces them — is Phase 5.7a.3's job, not
this one's. `MockProvider.stream()` is trivial today: it yields the whole
completion as a single terminal chunk, which is a real, working
implementation of the interface, not a stub.

## The internal representation (`types.py`)

This is the most consequential design in the sub-phase: every adapter,
now and in the future, translates to and from these types, and changing
them later means touching every adapter.

```python
@dataclass(frozen=True, slots=True)
class ModelMessage:
    role: str                     # "system" | "user" | "assistant" | "tool"
    content: str
    tool_call_id: str | None = None   # set only when role == "tool"

@dataclass(frozen=True, slots=True)
class ModelToolDefinition:
    name: str
    description: str
    parameters: Mapping[str, Any] = {}   # JSON Schema

@dataclass(frozen=True, slots=True)
class ModelToolCall:
    id: str
    name: str
    arguments: Mapping[str, Any] = {}

@dataclass(frozen=True, slots=True)
class ModelRequest:
    messages: tuple[ModelMessage, ...]
    tools: tuple[ModelToolDefinition, ...] = ()
    sampling_parameters: Mapping[str, Any] = {}   # temperature, top_p, ... -- free-form
    max_tokens: int | None = None
    stop_sequences: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class ModelResponse:
    content: str
    tool_calls: tuple[ModelToolCall, ...] = ()
    finish_reason: FinishReason = FinishReason.STOP
    raw_usage: Mapping[str, Any] = {}    # structure only -- accounting is 5.7a.3/5.7a.5

@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    supports_streaming: bool
    supports_tools: bool
    supports_system_prompt: bool
    max_context_tokens: int

class FinishReason(str, Enum):
    STOP = "STOP"
    LENGTH = "LENGTH"
    TOOL_CALLS = "TOOL_CALLS"
    CONTENT_FILTER = "CONTENT_FILTER"
    ERROR = "ERROR"
```

A third-party adapter can be written from this section alone: translate
your provider's own request shape into a `ModelRequest` (one `ModelMessage`
per turn, your provider-specific sampling knobs into
`sampling_parameters`), call your provider's API, translate its response
into a `ModelResponse`.

### Design rules — both mechanically checked by the test suite

1. **No provider-specific name may appear here** (`ACT-MDL-FR-006`) — no
   `openai_`/`anthropic_` prefix, no field only one provider has.
   `test_types_module_names_no_provider` AST-parses every class/field/
   function name in `types.py` and fails if any of them names a known
   provider vocabulary word. (The module's own *docstring* is allowed to
   name OpenAI/Anthropic as examples of what must never leak in — that's
   documentation of the rule, not a violation of it; the test only
   inspects actual identifiers, not prose.)
2. **Sampling parameters are a free-form dict, not fixed fields.**
   Different providers accept different sets (`temperature`, `top_p`,
   `top_k`, `frequency_penalty`, ...) — fixing them as dataclass fields
   would mean this shared type grows a field every time a new provider
   introduces a new knob. Each adapter is responsible for translating the
   subset it understands and ignoring (or rejecting, via capability
   declaration) the rest.
3. **Never silently guess a representation** — the same principle
   `canonical.py` established for checksums (REPO_STATE §10.15). A
   `ModelMessage` with a role outside the four defined ones raises
   `ValueError` at construction, immediately (`ModelMessage.__post_init__`).
   `FinishReason` is a plain `Enum` specifically so that
   `FinishReason("some_provider_string")` raises `ValueError` for free —
   an adapter maps its own raw reason strings onto these five values
   explicitly (e.g. a small provider-local dict), and lets that lookup
   fail loudly for anything unrecognized rather than defaulting to `STOP`
   or `ERROR`. That mapping is deliberately *not* provided here, since the
   raw strings themselves (OpenAI's `"stop"`/`"length"`/... or any other
   provider's own vocabulary) would violate rule 1.
4. **Immutable, all the way down.** `frozen=True, slots=True` dataclasses
   with `tuple` (not `list`) for every ordered collection, and
   `MappingProxyType` wrapping (applied in `__post_init__`) for every
   dict-shaped field — `sampling_parameters`, `arguments`, `parameters`,
   `raw_usage`. Reassigning a field raises `dataclasses.FrozenInstanceError`;
   mutating a "dict" field in place raises `TypeError` (`mappingproxy`
   doesn't support item assignment) — both checked directly in
   `test_model_request_is_immutable`/`test_model_response_is_immutable`.

## The registry (`registry.py`)

```python
def register(identifier: str, provider_cls: type[ModelProvider]) -> None: ...
def resolve(identifier: str, *, base_url: str | None = None) -> ModelProvider: ...
def registered_identifiers() -> list[str]: ...

register("MOCK", MockProvider)   # the only registration today
```

Registration is **explicit**, at the bottom of `registry.py` — one line
per provider, not directory-scanning discovery. Explicit registration is
greppable: `grep "^register(" backend/app/runtime/providers/registry.py`
tells you every provider this deployment knows about; a discovery
mechanism would require actually running the code to find out. Adding
Phase 5.7a.2's real provider means one more `register(...)` call here and
nothing else changes.

`resolve()` upper-cases the identifier before lookup (matching
`AgentVersion.model_configuration`'s existing `"provider": "MOCK"`
convention) and raises `ProviderUnavailableError`
(`MODEL_PROVIDER_UNAVAILABLE`) for anything unregistered — the exact
fail-closed behavior `ModelGatewayService` had before this phase, now
delegated rather than inlined.

## Capability declaration & enforcement

Every provider declares what it supports via `describe()`. A request that
asks for something unsupported — tool definitions sent to a provider whose
`describe()` reports `supports_tools=False` (`MockProvider` today), or a
system-role message sent to one that doesn't support system prompts —
raises `CapabilityUnsupportedError` (`MODEL_CAPABILITY_UNSUPPORTED`, HTTP
422) via `validate_capabilities()`, called explicitly at the top of
`complete()`/`stream()`.

## Wiring: `ModelGatewayService.invoke()`

The pre-existing public method — `invoke(version, input_payload) ->
(output_payload, usage)` — keeps its exact signature; only what happens
inside it changed, from an inline `MOCK`-only branch to:

1. Read `provider_name` from `version.model_configuration` (frozen at
   publish time — never from the agent or deployment, which can still
   change after the version is signed; `ACT-MDL-FR-004`).
2. `resolve(provider_name, base_url=settings.MODEL_PROVIDER_BASE_URLS.get
   (provider_name))` — unregistered still raises `MODEL_PROVIDER_
   UNAVAILABLE` (`ACT-MDL-FR-005`).
3. Translate the legacy `input_payload: dict` into a `ModelRequest` — the
   whole payload becomes the content of one `user`-role message. (This is
   the one place this phase's design is shaped by a pre-existing contract
   rather than the reverse: `ExecutionWorkerService` already expects
   `input_payload`/`(output_payload, usage)` as arbitrary business JSON,
   not a chat-message list — see "What changed vs. what didn't" below.)
4. Call `provider.complete(request)`.
5. Translate the `ModelResponse` back into the legacy `(output_payload,
   usage)` tuple: `output_payload = {"result": response.content, "echo":
   input_payload}`; `usage` carries `provider`/`model` (from
   `model_configuration`, unchanged) plus the token counts from
   `response.raw_usage`.

`AuthorizationGateway` is untouched and unaffected by any of this — it
runs at `ExecutionRequestService.request_execution()` time, when an
execution is first requested, which is a wholly separate, earlier stage of
the pipeline than `ModelGatewayService.invoke()` (called only once a
`QUEUED` execution is actually picked up by the worker). An unauthorized
request never reaches a queued execution at all, so it never reaches
provider resolution either — proven by
`test_authorization_gateway_runs_before_provider_resolution`, which spies
on `registry.resolve()` and confirms it's never called for a denied
request.

### What changed vs. what didn't (`MOCK` migration)

**Unchanged** — everything any existing test or caller actually depends
on:
- `output_payload["echo"] == input_payload` (exact echo)
- `model_usage["provider"] == "MOCK"`
- `model_usage["total_tokens"] > 0` (so `execution.cost` still computes
  positive)
- The `__simulate_slow_seconds__` test-only timeout hook

**Changed** — internal details nothing asserts on:
- The exact wording of `output_payload["result"]` (was `"processed N
  input field(s)."`, counting dict keys; is now `"processed N
  message(s)."`, counting `ModelRequest.messages` — always 1, since the
  whole payload becomes one message). This is a real, visible text change,
  but zero tests anywhere in the suite assert on it (only the boolean
  presence and shape of `output_payload`/`model_usage`, checked before
  this phase started — see `test_every_existing_mock_execution_behavior_
  is_unchanged`).
- The exact token counts (previously derived from `len(json.dumps(input_
  payload))`; now from the length of the wrapped message content) — still
  positive, no longer byte-identical.

If migrating `MOCK` had required changing anything in the *unchanged* list
above, that would have meant the interface was wrong and needed fixing,
not `MOCK`. It didn't come to that.

## Configuration

```python
# backend/app/core/config.py
MODEL_DEFAULT_PROVIDER: str = "MOCK"
MODEL_PROVIDER_BASE_URLS: dict[str, str] = {}   # {"SOME_IDENTIFIER": "https://..."}
```

`MODEL_PROVIDER_BASE_URLS` lets one adapter *class* serve multiple
compatible endpoints under different registered identifiers (e.g. a future
`OpenAICompatibleProvider` registered once as `"OPENAI"` pointed at
OpenAI's own API, and again as `"SELF_HOSTED_LLM"` pointed at an
internally-hosted OpenAI-compatible gateway) — `ACT-MDL-FR-010`. `MOCK` has
nothing to call, but still accepts and stores a `base_url` in its
constructor so the end-to-end wiring (settings → registry → provider
constructor) is proven before any real provider depends on it (see
`test_base_url_configuration_reaches_the_provider`).

## What's deferred

Real provider implementations (Phase 5.7a.2), streaming (5.7a.3), token
accounting/cost (5.7a.3/5.7a.5), a real error taxonomy and retry semantics
(5.7a.4), and credential storage (5.7a.5) are all explicitly out of scope
for this sub-phase — the interface and registry exist so each of those can
be added without another rewrite of the surrounding contract.
