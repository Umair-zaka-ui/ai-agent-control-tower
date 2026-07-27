# Model Provider Abstraction

`backend/app/runtime/providers/` · Phase 5.7a.1 SRS `ACT-MDL-FR-001..010`,
Phase 5.7a.2 SRS `ACT-MDL-FR-020..028`, Phase 5.7a.3 SRS
`ACT-MDL-FR-040..049`, `FR-084..089`.

## Why this exists

Every layer above the runtime — registry, versioning, signing, governance,
authorization — has been built and tested against a real executing agent.
Until Phase 5.7a.1, "executing" meant `ModelGatewayService` running a
single hardcoded `MOCK` branch and failing closed
(`MODEL_PROVIDER_UNAVAILABLE`) for anything else. That phase replaced the
branch with a real interface, a registry, and a provider-neutral internal
representation — proven by migrating `MOCK` onto it with **zero change in
observable behavior** — but registered no real adapter, deliberately, so
the interface's shape wasn't distorted by one concrete implementation's
assumptions while it was still being designed.

**Phase 5.7a.2 is the first real test of that interface**: an
`OpenAICompatibleProvider` that actually calls a model, over HTTP, and the
answer to whether the 5.7a.1 abstraction held is in the section below
titled "What Phase 5.7a.2 proved about the abstraction."

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
def resolve(identifier: str, *, base_url: str | None = None,
           model: str | None = None, api_key: str | None = None) -> ModelProvider: ...
def registered_identifiers() -> list[str]: ...

register("MOCK", MockProvider)
register("OPENAI_COMPATIBLE", OpenAICompatibleProvider)   # added Phase 5.7a.2
```

Registration is **explicit**, at the bottom of `registry.py` — one line
per provider, not directory-scanning discovery. Explicit registration is
greppable: `grep "^register(" backend/app/runtime/providers/registry.py`
tells you every provider this deployment knows about; a discovery
mechanism would require actually running the code to find out. Adding
Phase 5.7a.2's real provider meant exactly one more `register(...)` call
here.

`resolve()` upper-cases the identifier before lookup (matching
`AgentVersion.model_configuration`'s existing `"provider": "MOCK"`
convention) and raises `ProviderUnavailableError`
(`MODEL_PROVIDER_UNAVAILABLE`) for anything unregistered — the exact
fail-closed behavior `ModelGatewayService` had before Phase 5.7a.1, still
true today.

### `model`/`api_key` forwarding (added Phase 5.7a.2)

5.7a.1 left `model_configuration.model` reaching only the reported
`usage.model` in `ModelGatewayService.invoke()` — never the provider
instance itself (`MockProvider` didn't need it: its cosmetic `self.model`
only affected output text nothing asserts on). A real adapter genuinely
needs to know which model to ask for (and, if the endpoint requires one,
an API key), so `resolve()` now accepts optional `model`/`api_key`
parameters and forwards each **only if the target provider's constructor
actually declares that parameter** — checked via `inspect.signature`, not
assumed:

```python
accepted = inspect.signature(provider_cls.__init__).parameters
kwargs = {"base_url": base_url}
if model is not None and "model" in accepted:
    kwargs["model"] = model
if api_key is not None and "api_key" in accepted:
    kwargs["api_key"] = api_key
return provider_cls(**kwargs)
```

This is the one change 5.7a.2 made to `registry.py` itself, and it was
made carefully to avoid breaking `test_base_url_configuration_reaches_the_
provider`'s `_RecordingProvider` test double, whose constructor accepts
only `base_url` — the signature check means neither `model` nor `api_key`
is forwarded to it, exactly as before. Every other provider that does
declare `model` (both `MockProvider` and `OpenAICompatibleProvider`) now
actually receives the version's configured value; `api_key` is read from
`settings.MODEL_PROVIDER_API_KEYS` (keyed by provider identifier, the same
shape as `MODEL_PROVIDER_BASE_URLS`) and forwarded the same way.

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
   (provider_name), model=config.get("model"), api_key=settings.MODEL_
   PROVIDER_API_KEYS.get(provider_name))` — unregistered still raises
   `MODEL_PROVIDER_UNAVAILABLE` (`ACT-MDL-FR-005`). The `model`/`api_key`
   forwarding (Phase 5.7a.2) is new; see "The registry" section above.
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
MODEL_PROVIDER_BASE_URLS: dict[str, str] = {}          # {"SOME_IDENTIFIER": "https://..."}
MODEL_PROVIDER_DEFAULT_MODELS: dict[str, str] = {}     # {"SOME_IDENTIFIER": "llama3"} -- Phase 5.7a.2
MODEL_PROVIDER_CONNECT_TIMEOUT_SECONDS: float = 5.0    # Phase 5.7a.2
MODEL_PROVIDER_READ_TIMEOUT_SECONDS: float = 30.0      # Phase 5.7a.2
MODEL_PROVIDER_API_KEYS: dict[str, str] = {}           # Phase 5.7a.2 -- plain value, see note below
```

`MODEL_PROVIDER_BASE_URLS` lets one adapter *class* serve multiple
compatible endpoints under different registered identifiers —
`ACT-MDL-FR-010`. `MOCK` has nothing to call, but still accepts and stores
a `base_url` in its constructor so the end-to-end wiring (settings →
registry → provider constructor) is proven before any real provider
depends on it (see `test_base_url_configuration_reaches_the_provider`).
`OpenAICompatibleProvider` (5.7a.2) is the first provider that actually
uses it.

`MODEL_PROVIDER_API_KEYS` is a plain configured value, read as-is and sent
as `Authorization: Bearer <value>` — **not** credential storage.
Per-organization credential resolution (e.g. from `deployment.secret_
references`, a vault reference string, rotation) is Phase 5.7a.5; this is
deliberately the simplest thing that could work for a single environment
variable today.

## The OpenAI-compatible adapter (`openai_compatible.py`, Phase 5.7a.2)

`OpenAICompatibleProvider` talks the OpenAI chat-completions wire protocol
— `POST {base_url}/chat/completions` — which Ollama, vLLM, LM Studio and
OpenAI itself all implement. One class, one `base_url`/`model` pair per
registered identifier, no per-vendor subclass (`ACT-MDL-FR-027`).

### Naming: `"OPENAI_COMPATIBLE"`, not `"OPENAI"`

The registered identifier names the *wire protocol*, not a vendor. Ollama
and vLLM are not OpenAI. Registering this class as `"OPENAI"` would have
made a future, genuinely OpenAI-specific adapter (one that used
OpenAI-only request fields or auth) awkward to add without a naming
collision. `"OPENAI_COMPATIBLE"` leaves `"OPENAI"` free for that.

### Translation boundary

All OpenAI wire-format vocabulary — `choices`, `message.tool_calls`,
`function.arguments` (a JSON-encoded string, decoded here), `finish_
reason`'s raw values (`"stop"`/`"length"`/`"tool_calls"`/
`"content_filter"`) — is translated to and from `ModelRequest`/
`ModelResponse` entirely inside this one module (`ACT-MDL-FR-006`).
`test_no_openai_wire_vocabulary_outside_this_module` checks `base.py`,
`registry.py` and `types.py` directly for a set of unambiguous wire tokens
(`choices`, `prompt_tokens`, `completion_tokens`, the endpoint path,
`system_fingerprint`) — deliberately excluding `finish_reason`/
`tool_calls`, since those are `ModelResponse`'s *own* field names, chosen
on their own terms and only coincidentally spelled the same as OpenAI's.

Finish-reason mapping is a small local dict (`_FINISH_REASON_MAP`), per
`types.py`'s own design rule — an unrecognized raw value raises `ValueError`
rather than defaulting to `STOP`/`ERROR`
(`test_unrecognized_finish_reason_raises_rather_than_defaulting`).

### Tolerant parsing (`ACT-MDL-FR-028`)

Ollama's OpenAI-compatible layer doesn't always send every field OpenAI's
own API does — `usage`, `system_fingerprint`, `id`, even a tool call's
`id` can be absent. Every field outside `choices[0].message.content` is
read with `.get(...)`/a fallback, never direct indexing; a missing tool
call `id` gets a synthesized placeholder (`call_<index>`) rather than
raising, since its only downstream job is pairing a later `tool`-role
message back to this call. See `omitted_optional_fields.json` and
`test_response_omitting_optional_fields_parses_without_error`.

### Sampling parameters

Only `temperature`, `top_p`, `presence_penalty`, `frequency_penalty`,
`seed` and `n` are forwarded from `ModelRequest.sampling_parameters`;
anything else (e.g. `top_k`, `repeat_penalty` — knobs some
llama.cpp-family servers accept but OpenAI's own API doesn't) is silently
dropped from the wire request and logged at `DEBUG` naming exactly what
was dropped, so a developer wondering why a parameter had no effect can
find out (`ACT-MDL-FR-023`).

### Tool-calling capability is configurable, not assumed

Not every model behind an OpenAI-compatible endpoint supports function
calling — many self-hosted base models don't. `describe().supports_tools`
is `True` by default but can be set `False` per instance
(`OpenAICompatibleProvider(supports_tools=False, ...)`), so a deployment
known not to support tools fails closed with `CapabilityUnsupportedError`
(`MODEL_CAPABILITY_UNSUPPORTED`) instead of silently sending tool
definitions the server will ignore or reject.

### `stream()` — the placeholder, and its closure condition

`stream()` delegates to `complete()` and yields the whole response as one
terminal chunk — it satisfies the interface without pretending to stream.
**Closure condition**: Phase 5.7a.3 replaces this with real SSE parsing of
the provider's `stream=true` response; nothing about `complete()`, request
translation, or response parsing needs to change when that happens.

### Errors

One coarse exception, deliberately not a taxonomy:
`ProviderRequestFailedError` (`MODEL_PROVIDER_REQUEST_FAILED`, HTTP 502)
covers a connection failure, a timeout, a non-2xx response, and an
unparseable body alike. Classifying these (timeout vs. 5xx vs. malformed
body) for retry/backoff purposes is Phase 5.7a.4's job — building that
classification now, before seeing a second real provider's failure modes,
would likely produce a worse design.

### Timeouts

`connect_timeout`/`read_timeout` (seconds, defaulting to 5/30) are
constructor parameters, backed by `MODEL_PROVIDER_CONNECT_TIMEOUT_SECONDS`/
`MODEL_PROVIDER_READ_TIMEOUT_SECONDS`. A hanging provider call raises
`ProviderRequestFailedError` rather than hanging the worker indefinitely —
no retry/backoff, that's still 5.7a.4.

## Fixtures & the `live_provider` marker

Every test in `test_openai_compatible_provider.py` replays a committed,
raw wire-format JSON fixture through an `httpx.MockTransport` — no test
opens a real socket (AC-23, verified by running the full suite with no
Ollama instance reachable). See `backend/tests/runtime/fixtures/providers/
README.md` for what each of the six fixtures covers and — importantly —
their actual provenance in this environment (hand-authored to match
Ollama's documented response shape, since no local Ollama was reachable
here; regenerate them for real with the recorder below if you have one).

**Recording fixtures for real**, against a local Ollama:

```bash
ollama pull llama3
python -m scripts.record_provider_fixtures --base-url http://localhost:11434/v1 --model llama3
```

The recorder (`backend/scripts/record_provider_fixtures.py`) is run
manually only, never from CI or any test — it strips any `Authorization`
header before writing, and the adapter itself has no knowledge the
recorder or the replay transport exist.

**Running the one genuinely live test** (excluded by default —
`backend/pytest.ini` registers the `live_provider` marker and sets
`addopts = -m "not live_provider"`):

```bash
pytest backend/tests/runtime/test_openai_compatible_provider.py -m live_provider
```

Requires `ollama serve` running locally with `llama3` pulled.

## What Phase 5.7a.2 proved about the abstraction

**The 5.7a.1 interface held without modification.** `ModelProvider`
(`base.py`), the registry's `register`/`resolve`/`registered_identifiers`
functions, and `types.py` are all **unchanged** except for one addition:
`resolve()` gained an optional `model` parameter (see above) — a genuine
gap 5.7a.1 left (every caller's configured model reached only a usage-
reporting string, never the provider instance), surfaced by building a
provider that actually needs to know which model to ask for. Nothing about
`ModelRequest`/`ModelResponse`/`ModelCapabilities`/`FinishReason` needed to
change to express the OpenAI chat-completions protocol faithfully.

**One field the internal types still cannot express**: an assistant
message's own prior tool-call request, for use in conversation history.
`ModelMessage` has `tool_call_id` (set on a `role="tool"` message,
answering a call) but no field for "this assistant message itself
requested these tool calls." A real multi-turn tool-use loop replaying
full history therefore can't yet reconstruct a prior assistant tool
invocation as a `ModelMessage` — only `ModelResponse.tool_calls` carries
that, at the moment of the response itself. This wasn't fixed here: the
tool invocation loop that would actually need it is Phase 5.6a.3's job,
explicitly out of scope for this sub-phase, and guessing at the right
shape without that consumer in hand risked distorting `types.py` for a use
case not yet built. Flagged here for whoever builds 5.6a.3.

## Streaming (`stream()`, Phase 5.7a.3)

`OpenAICompatibleProvider.stream()` replaced the 5.7a.2 placeholder
(`yield self.complete(request)`) with real Server-Sent-Events parsing:
`POST .../chat/completions` with `"stream": true`, reading `data: {...}`
lines via `httpx.Client.stream()` (never buffering the full response
first — `ACT-MDL-FR-041`), terminated by `data: [DONE]`.

### The per-chunk convention — no new type needed

Every yielded `ModelResponse`'s `content` is that chunk's **incremental**
delta, not the cumulative text — concatenate across every yielded chunk
for the full content. `tool_calls`/`finish_reason`/`raw_usage` are only
meaningful on the **last** chunk yielded: a streamed tool call's
`arguments` arrives as a string fragment per chunk and isn't valid JSON
until fully reassembled (`ACT-MDL-FR-044`), so every non-final chunk
correctly reports `tool_calls=()` — there's nothing valid to report yet.

`types.py` gained exactly one addition for this: `assemble_response()`, a
module-level function reducing a chunk sequence into the single complete
`ModelResponse` a non-streaming caller would have received
(`ACT-MDL-FR-042`) — not a new dataclass. **No change to `ModelResponse`,
`ModelProvider`, or `MockProvider` was needed.** The existing
`Iterator[ModelResponse]` contract already expresses everything real
streaming needs once every adapter follows the convention above:
`MockProvider`'s single-chunk `stream()` already satisfies it with zero
code changes, since its one chunk's content *is* the whole completion and
it *is* the last (only) chunk.

**Interruption reuses an existing enum value.** `FinishReason.ERROR` (already
defined in 5.7a.1, unused until now) doubles as "this stream was
interrupted" on the final chunk — no new type needed there either. A
connection failure, a non-2xx status, or a stream that ends without ever
reaching `[DONE]` (truncation) all make `stream()` yield exactly one final
chunk with `finish_reason=FinishReason.ERROR` and whatever content/tool-
call state had already accumulated (`ACT-MDL-FR-043`), rather than raising
and losing everything already received. **This is deliberately different
from `complete()`, which does raise** (`ProviderRequestFailedError`) on
the same failures — a caller that needs to know whether a stream actually
succeeded checks the final chunk's `finish_reason`, not a try/except.

### Tool-call reassembly across chunks

A streamed tool call's `function.arguments` arrives as successive string
*fragments*, one per chunk, keyed by `index` (multiple concurrent tool
calls interleave by index — `ACT-MDL-FR-044`). `_accumulate_tool_call_
deltas` keeps a per-index `{id, name, arguments}` accumulator; only the
first delta for a given index typically carries `id`/`function.name`,
every later delta for that index appends to `arguments`.
`_finalize_tool_calls` JSON-parses each accumulated argument string only
once, at the end — tolerating (rather than crashing on) an argument
string that never fully reassembled into valid JSON, by falling back to
an empty `{}`.

### Known limitation

`stream()` reads `usage` only from the same event that carries
`finish_reason` — matching Ollama's actual behavior and OpenAI's default.
OpenAI's opt-in `stream_options.include_usage` trailing usage-only chunk
(empty `choices`) is not requested or handled; nothing in
`ACT-MDL-FR-040..049` asks for it.

## The platform-side streaming boundary (`ModelGatewayService`)

`invoke(version, input_payload)` **keeps its exact signature and
`(output_payload, usage)` contract** for every existing caller
(`ACT-MDL-FR-042`'s "same tuple" requirement, and this phase's own
governing principle: "a streamed call must still yield the same tuple to
any caller that does not opt into streaming"). A version opts into
streaming via `model_configuration = {..., "stream": true}`;
`config.get("stream", False)` defaults every pre-5.7a.3 configuration
(none of which set this key) to the unchanged non-streaming path.

`_invoke_streaming()` is the new internal path, used only when streaming
is requested:

1. Iterates `provider.stream(request)` chunk by chunk — never collecting
   the whole thing before starting.
2. Measures **time to first token** — the elapsed time until the first
   chunk carrying non-empty `content` (`ACT-MDL-FR-048`).
3. Enforces `settings.MODEL_STREAM_MAX_DURATION_SECONDS` (default 120s,
   `ACT-MDL-FR-049`) by simply **no longer calling `next()`** on the
   generator once the budget is exceeded — the abandoned generator's own
   `with`-managed HTTP connection closes on garbage collection; no
   separate thread or signal needed.
4. Reassembles whatever chunks were consumed via `assemble_response()`
   and measures **total generation duration**.
5. Distinguishes *why* a stream ended: a real `FinishReason.ERROR` final
   chunk from the adapter reports as "provider stream ended unexpectedly";
   the platform's own duration cutoff reports as "exceeded the maximum
   response duration," with `finish_reason` left `null` in `usage` (the
   adapter never got to report one) — both set `stream_interrupted=true`
   and a human-readable `interruption_reason`, distinctly.

There is deliberately **no HTTP-level streaming endpoint** in this
sub-phase — an SSE `GET .../stream` surfaced to a browser is Phase 5.9 or
a later UI phase's job. This phase makes the *provider* stream and makes
the *platform* correctly reassemble, account for, and persist that
stream — internal correctness, not a new API surface.

## Token accounting (`ACT-MDL-FR-045..048`)

`usage` (the dict `ModelGatewayService.invoke()` returns) grew several
keys, present for **both** streaming and non-streaming calls alike:
`token_accounting_complete`, `was_streamed`, `stream_interrupted`,
`interruption_reason`, `time_to_first_token_ms`, `generation_duration_ms`,
`finish_reason` — alongside the pre-existing `provider`/`model`/
`input_tokens`/`output_tokens`/`total_tokens`.

**The never-estimate rule (`ACT-MDL-FR-046`)**: `OpenAICompatibleProvider.
_usage_to_raw()` returns `{}` — not a dict of zeros — when the provider's
response omits `usage` entirely. `{}` and `{"total_tokens": 0, ...}` mean
different things: the latter is a real, if boring, measurement; the
former means "no measurement was possible." `ModelGatewayService` uses
`bool(raw_usage)` to compute `token_accounting_complete`, and
`ExecutionWorkerService._execute` honors it explicitly — when accounting
is incomplete, `agent_executions.prompt_tokens`/`completion_tokens`/
`total_tokens` are set to **`NULL`**, never `0`. This is also why
`test_response_omitting_optional_fields_parses_without_error` now asserts
`raw_usage == {}` rather than a zero-filled dict — the old assertion (from
5.7a.2, before this rule existed) was itself testing the exact
estimate-that-looks-real shape this rule forbids.

**Per-attempt, not only per-execution (`ACT-MDL-FR-047`)**:
`execution_attempts` gained the same three token columns plus
`token_accounting_complete`, written alongside the `agent_executions` row
in the same `_execute()` call — a retried execution's earlier attempts
keep their own usage, not only the final attempt's.

## Cost (`ACT-MDL-FR-084..089`)

### `model_pricing` and effective dating

One new table, `provider`/`model_name`/`prompt_cost_per_1k`/
`completion_cost_per_1k`/`currency`/`pricing_version`/`effective_from`/
`effective_to`, unique on `(provider, model_name, effective_from)`.
**A price change is never an `UPDATE`.** `PricingService.set_price()`
closes whatever row is currently open (`effective_to IS NULL`) by setting
its `effective_to` to the new price's `effective_from`, then inserts the
new price as a new row. `PricingService.resolve_price(provider, model,
at)` picks the row whose `[effective_from, effective_to)` window contains
`at`. This is what keeps an execution's already-computed cost accurate
after a price changes later — resolving a price *at* a past instant
always returns whatever was actually in effect then, regardless of what's
been added since.

### Pricing seed data

Migration `0028_streaming_and_pricing` seeds three rows under provider
`"OPENAI_COMPATIBLE"` (the only adapter capable of calling them):

| Model | Prompt $/1K | Completion $/1K | Pricing version | Effective from |
|---|---|---|---|---|
| `gpt-3.5-turbo` | 0.0005 | 0.0015 | `2025-01-seed` | 2025-01-01 |
| `gpt-4o-mini` | 0.00015 | 0.0006 | `2025-01-seed` | 2025-01-01 |
| `gpt-4o` | 0.0025 | 0.01 | `2025-01-seed` | 2025-01-01 |

**These are illustrative, approximately-dated figures, not live prices.**
An operator pointing this adapter at a real metered endpoint must verify
current rates and maintain them via `PricingService.set_price()` — never
by hand-editing this migration after the fact, and never by mutating a
`model_pricing` row's price columns directly (that would silently corrupt
every historical cost computed against it).

### Local/unpriced providers cost zero, not null (`ACT-MDL-FR-087`)

`PricingService.calculate_cost()` returns `CostResult(amount=0.0,
currency="USD", pricing_version=None)` when no `model_pricing` row
matches `(provider, model)` at the execution's time — this is the
ordinary case for `MOCK` (no pricing row exists for it, deliberately) and
for a real provider pointed at a self-hosted/local endpoint. Zero is a
definite, known answer ("this call cost nothing to run"), not "unknown."

**This changed one existing, previously-protected assertion.** Before
5.7a.3, every MOCK execution's `cost` came from a flat
`total_tokens * 0.000002` placeholder in `ExecutionWorkerService`, which
made `execution["cost"] > 0` true for any MOCK call — asserted in both
`test_execution_runs_end_to_end` and
`test_every_existing_mock_execution_behavior_is_unchanged`. Once cost is
computed by the same `PricingService` every provider uses, MOCK (which
has no pricing row) honestly costs `0`. Both assertions were updated to
`== 0`, with a comment explaining why: the old `> 0` was itself testing
the exact fake-positive-number-that-looks-real problem `ACT-MDL-FR-087`
exists to retire, not a behavior worth preserving.

### Legacy placeholder rows (`ACT-MDL-FR-086`)

Every `agent_executions` row with a non-zero `cost` from before this
migration was computed by that same flat placeholder formula — never a
real per-model rate. Migration `0028` runs one `UPDATE agent_executions
SET cost_is_estimated = true WHERE cost <> 0` (1,538 rows, in this
environment's dev database) — **flagging, never recomputing or deleting**
a single existing value. `analytics_service.py`'s cost dashboard (Phase
3's `_COST_PER_LLM_ACTION` and friends) is a separate, older, coarser
concept entirely — a flat per-`AgentAction`-row estimate with no
connection to `AgentExecution`/token data at all, not touched by this
migration or this sub-phase; see "What Phase 5.7a.3 found" below for why.

## What Phase 5.7a.3 found (honest findings)

- **The 5.7a.2 abstraction held for real streaming, with zero changes to
  `ModelResponse`, `ModelProvider`, or `MockProvider`** — one addition to
  `types.py` (`assemble_response()`, a function, not a new dataclass) and
  the documented per-chunk convention above were enough.
- **`analytics_service.py`'s cost estimates are not the same "placeholder
  cost" `ACT-MDL-FR-086` describes**, despite the build prompt's own
  wording pointing there. That module's `cost_analytics()` aggregates
  Phase 3's `AgentAction` table (a coarser, older business-action audit
  concept) with flat per-unit estimates (`_COST_PER_LLM_ACTION = 0.03`,
  etc.) — it has no connection whatsoever to `AgentExecution`/
  `model_usage`/real token counts, and rewriting it to use real per-
  execution costs would mean redesigning a Phase 3 dashboard around a
  Phase 5 data model, a much larger and riskier scope than this
  sub-phase's actual mandate. The genuinely real, token-grounded cost this
  phase was asked to build lives on `AgentExecution` (`cost_amount`,
  attributable to execution/agent/version/org/model — exactly
  `ACT-MDL-FR-088`'s shape), which is what `PricingService` computes.
  `analytics_service.py` was deliberately left untouched.
- **MOCK's cost became 0, not a preserved positive placeholder** — see
  above. This was confirmed as the intended direction before implementing
  it, since it meant updating two existing, previously-stable assertions.

## What's deferred

A real error taxonomy and retry semantics, and per-organization credential
storage, remain out of scope — owned by Phase 5.7a.4 and 5.7a.5
respectively. The interface, registry, one real adapter, real streaming,
and real token/cost accounting all exist so each of those can be added
without another rewrite of the surrounding contract.
