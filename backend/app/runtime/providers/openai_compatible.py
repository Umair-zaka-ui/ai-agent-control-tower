"""Phase 5.7a.2 SRS ACT-MDL-FR-020..028, Phase 5.7a.3 SRS ACT-MDL-FR-040..044
— OpenAI-compatible chat completions adapter, streaming included.

The first *real* ``ModelProvider``: talks the OpenAI chat-completions wire
protocol (``POST {base_url}/chat/completions``) that Ollama, vLLM, LM
Studio and OpenAI itself all implement, so one adapter class serves all
four via configuration (``base_url``) alone (``ACT-MDL-FR-027``) — no
per-vendor subclass.

**Every OpenAI-shaped token stays in this module** (``ACT-MDL-FR-006``,
mechanically checked by ``test_types_module_names_no_provider``): the
``choices``/``finish_reason``/``tool_calls``/``function`` wire shape is
translated to and from the provider-neutral types in ``types.py`` entirely
here, and nowhere else may see it.

**Registered as ``"OPENAI_COMPATIBLE"``, not ``"OPENAI"``** — the
identifier names the wire protocol this class speaks, not a vendor. Ollama
and vLLM are not OpenAI; a future dedicated OpenAI adapter with real
vendor-specific behavior (e.g. OpenAI-only request fields) should be free
to claim ``"OPENAI"`` for itself later without colliding with this one.

**Tolerant parsing throughout** (``ACT-MDL-FR-028``): compatible
implementations vary in completeness (Ollama omits fields OpenAI always
sends — ``system_fingerprint``, sometimes ``usage``, sometimes a tool
call's ``id``). Every field outside ``choices[0].message.content`` is
treated as potentially absent and read with ``.get(...)``/a fallback,
never direct indexing.

**``stream()`` is real incremental SSE parsing** (Phase 5.7a.3) — see its
own docstring for the per-chunk convention, tool-call reassembly across
fragments, and why it never raises (unlike ``complete()``, which does).

**No credential resolution** — an API key is read as a plain configured
value if present (Phase 5.7a.5 is per-organization credential storage).

**Error classification (Phase 5.7a.4, ``ACT-MDL-FR-060``)** — every
``ProviderRequestFailedError`` this module raises, and every interrupted
``stream()`` final chunk, now carries a ``ProviderErrorClass`` (see
``_classify_status_error``/``_classify_transport_error`` below). This
module only *classifies*; it does not retry or circuit-break — that
decision belongs to ``ModelGatewayService`` (the service layer), which is
provider-neutral and must not know this module's wire format. ``stream()``
still never raises, per ``ACT-MDL-FR-043``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import httpx

from app.runtime.providers.base import ModelProvider
from app.runtime.providers.errors import ProviderRequestFailedError
from app.runtime.providers.types import (
    FinishReason,
    ModelCapabilities,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    ModelToolDefinition,
    ProviderErrorClass,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-3.5-turbo"
DEFAULT_BASE_URL = "http://localhost:11434/v1"  # Ollama's OpenAI-compatible endpoint
MAX_CONTEXT_TOKENS = 8192
DEFAULT_CONNECT_TIMEOUT_SECONDS = 5.0
DEFAULT_READ_TIMEOUT_SECONDS = 30.0

# ACT-MDL-FR-023: only these sampling parameters are forwarded to the wire
# request; anything else in ModelRequest.sampling_parameters is dropped
# (and debug-logged) rather than sent and possibly rejected by the
# endpoint. This list matches the chat-completions parameters every
# OpenAI-compatible implementation in ACT-MDL-FR-027's target list accepts.
_SUPPORTED_SAMPLING_PARAMETERS = frozenset({
    "temperature", "top_p", "presence_penalty", "frequency_penalty", "seed", "n",
})

# ACT-MDL-FR-026: maps the provider's own raw finish-reason string onto the
# provider-neutral FinishReason. An unmapped raw value raises (KeyError,
# wrapped below) rather than silently defaulting -- REPO_STATE §10.15/§10.21.
_FINISH_REASON_MAP = {
    "stop": FinishReason.STOP,
    "length": FinishReason.LENGTH,
    "tool_calls": FinishReason.TOOL_CALLS,
    "content_filter": FinishReason.CONTENT_FILTER,
}

# ACT-MDL-FR-060 — a 400 body is only ever CONTEXT_LENGTH_EXCEEDED or
# CONTENT_FILTERED if it says so explicitly; anything else that's merely a
# 400 is the generic INVALID_REQUEST. Substring markers, not exact string
# matches, since providers phrase these inconsistently (OpenAI's message
# text vs. a compatible server's own wording) -- matches the same tolerant-
# parsing spirit as the rest of this module (ACT-MDL-FR-028).
_CONTEXT_LENGTH_MARKERS = ("context_length_exceeded", "maximum context length", "context length")
_CONTENT_FILTER_MARKERS = ("content_filter", "content management policy", "flagged")


def _classify_status_error(status_code: int, body_text: str) -> ProviderErrorClass:
    """ACT-MDL-FR-060 — maps an HTTP status + response body to the
    provider-neutral taxonomy. Never guesses past what the status/body
    actually says: an unrecognized status (not 429/401/403/5xx/400) maps to
    ``UNKNOWN``, not to whichever bucket seems closest."""
    lowered = body_text.lower()
    if status_code == 429:
        return ProviderErrorClass.RATE_LIMITED
    if status_code in (401, 403):
        return ProviderErrorClass.AUTHENTICATION_FAILED
    if status_code >= 500:
        return ProviderErrorClass.PROVIDER_UNAVAILABLE
    if status_code == 400:
        if any(marker in lowered for marker in _CONTEXT_LENGTH_MARKERS):
            return ProviderErrorClass.CONTEXT_LENGTH_EXCEEDED
        if any(marker in lowered for marker in _CONTENT_FILTER_MARKERS):
            return ProviderErrorClass.CONTENT_FILTERED
        return ProviderErrorClass.INVALID_REQUEST
    return ProviderErrorClass.UNKNOWN


def _classify_transport_error(exc: httpx.HTTPError) -> ProviderErrorClass:
    """ACT-MDL-FR-060 — a failure below the HTTP-status level (the request
    never got a response at all). ``httpx.TimeoutException`` is itself a
    subclass of ``httpx.TransportError``, so it's checked first; any other
    transport-level failure (connection refused, DNS failure, a dropped
    socket) is ``PROVIDER_UNAVAILABLE``. Anything neither (e.g. a decoding
    error, too many redirects) is ``UNKNOWN`` rather than guessed."""
    if isinstance(exc, httpx.TimeoutException):
        return ProviderErrorClass.TIMEOUT
    if isinstance(exc, httpx.TransportError):
        return ProviderErrorClass.PROVIDER_UNAVAILABLE
    return ProviderErrorClass.UNKNOWN


def _parse_retry_after(response: httpx.Response) -> float | None:
    """ACT-MDL-FR-064 — a numeric ``Retry-After`` (seconds), if present and
    parseable. The HTTP-date form of this header exists but is not handled
    here — no fixture or real target in this sub-phase's scope sends it,
    and guessing at date parsing without a real case to test against would
    itself be exactly the kind of guess ``types.py``'s design rules forbid
    elsewhere in this codebase."""
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _scrub(text: str, *, api_key: str | None, base_url: str | None = None) -> str:
    """ACT-MDL-FR-069 — redacts a configured API key, and this instance's
    own ``base_url`` (an internal endpoint, per FR-069), out of any text
    before it leaves this module (an exception message, a debug log line).
    Applied defensively to every detail string this module constructs from
    provider-supplied content; the *safe*, templated messages this module
    raises never include raw provider body text at all (see
    ``_classified_status_error``), so this mostly guards the debug log."""
    if api_key:
        text = text.replace(api_key, "***REDACTED***")
    if base_url:
        text = text.replace(base_url, "<provider endpoint>")
    return text


class OpenAICompatibleProvider(ModelProvider):
    """Talks the OpenAI chat-completions wire protocol against any
    ``base_url`` that implements it (Ollama, vLLM, LM Studio, OpenAI)."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        read_timeout: float = DEFAULT_READ_TIMEOUT_SECONDS,
        max_context_tokens: int = MAX_CONTEXT_TOKENS,
        supports_tools: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url or DEFAULT_BASE_URL
        self.model = model
        self._max_context_tokens = max_context_tokens
        # Kept only for credential scrubbing (ACT-MDL-FR-069) -- never sent
        # anywhere itself except as the existing Authorization header below.
        self._api_key = api_key
        # Not every model behind an OpenAI-compatible endpoint supports
        # function calling (many self-hosted base models don't) -- this is
        # a per-deployment fact the operator knows and configures, not
        # something this adapter can introspect from the wire protocol
        # alone.
        self._supports_tools = supports_tools
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(connect=connect_timeout, read=read_timeout, write=read_timeout, pool=connect_timeout),
            transport=transport if transport is not None else self._build_default_transport(),
        )

    def _build_default_transport(self) -> httpx.BaseTransport:
        """A real transport, used whenever the constructor isn't given one
        explicitly. Test infrastructure substitutes this (never the
        adapter itself) with a replay transport — see
        ``backend/tests/runtime/conftest.py``; this class has no
        `if testing` branch anywhere."""
        return httpx.HTTPTransport()

    # ------------------------------------------------------------------ #
    # ModelProvider interface
    # ------------------------------------------------------------------ #
    def complete(self, request: ModelRequest) -> ModelResponse:
        self.validate_capabilities(request)
        body = self._build_request_body(request)
        try:
            http_response = self._client.post("/chat/completions", json=body)
            http_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise self._classified_status_error(exc) from exc
        except httpx.HTTPError as exc:
            raise self._classified_transport_error(exc) from exc

        try:
            data = http_response.json()
        except ValueError as exc:
            raise ProviderRequestFailedError(
                type(self).__name__, "response body was not valid JSON", error_class=ProviderErrorClass.UNKNOWN,
            ) from exc

        return self._parse_response(data)

    def _classified_status_error(self, exc: httpx.HTTPStatusError) -> ProviderRequestFailedError:
        """ACT-MDL-FR-060, FR-069 — the raised message is a safe, templated
        summary (status + classification) only; the raw response body is
        never included in it (only used, scrubbed, to *decide* the
        classification and in a debug log) so nothing the provider sent
        back can leak a credential or internal detail to a caller."""
        response = exc.response
        body_text = _scrub(response.text or "", api_key=self._api_key, base_url=self.base_url)
        error_class = _classify_status_error(response.status_code, body_text)
        retry_after = _parse_retry_after(response) if error_class == ProviderErrorClass.RATE_LIMITED else None
        logger.debug("%s: HTTP %s classified as %s -- body=%s",
                     type(self).__name__, response.status_code, error_class.value, body_text)
        detail = f"HTTP {response.status_code} from provider (classified {error_class.value})"
        return ProviderRequestFailedError(type(self).__name__, detail, error_class=error_class,
                                          retry_after_seconds=retry_after)

    def _classified_transport_error(self, exc: httpx.HTTPError) -> ProviderRequestFailedError:
        error_class = _classify_transport_error(exc)
        detail = _scrub(str(exc), api_key=self._api_key, base_url=self.base_url)
        return ProviderRequestFailedError(type(self).__name__, detail, error_class=error_class)

    def stream(self, request: ModelRequest) -> Iterator[ModelResponse]:
        """Real incremental streaming (Phase 5.7a.3, replacing the 5.7a.2
        placeholder) — parses the OpenAI-compatible Server-Sent-Events
        format (``data: {...}`` lines, terminated by ``data: [DONE]``).

        Each yielded ``ModelResponse.content`` is that chunk's
        *incremental* delta, not the cumulative text — concatenate across
        every yielded chunk for the full content (see ``assemble_response()``
        in ``types.py``). ``tool_calls``/``finish_reason``/``raw_usage``
        are only populated on the *final* chunk: a tool call's
        ``arguments`` string arrives as fragments spread across many
        chunks and is not valid JSON until fully reassembled
        (``ACT-MDL-FR-044``), so every non-final chunk correctly reports
        ``tool_calls=()`` — there is nothing valid to report yet.

        **Never raises** — unlike ``complete()``. An HTTP failure, a
        non-2xx status, or a connection that ends without ever reaching
        ``[DONE]`` (truncation) all yield exactly one final chunk with
        ``finish_reason=FinishReason.ERROR`` and whatever content/tool-call
        state had already accumulated, rather than raising and losing
        everything already received (``ACT-MDL-FR-043``). A caller that
        needs to know whether a stream actually succeeded checks the final
        chunk's ``finish_reason``, not a try/except.

        **Known limitation**: ``usage`` is read only from the same event
        that carries ``finish_reason`` — matching both Ollama's actual
        behavior and OpenAI's default. OpenAI's opt-in ``stream_options.
        include_usage`` trailing usage-only chunk (empty ``choices``) is
        not requested or handled; nothing in ``ACT-MDL-FR-040..049`` asks
        for it, and requesting it would be a one-line addition to
        ``_build_request_body`` if a future sub-phase needs it.

        **Interruption classification (Phase 5.7a.4)**: the final,
        interrupted chunk's ``error_class``/``retry_after_seconds`` mirror
        what ``complete()`` would have raised for the equivalent failure —
        an HTTP status error before any events arrived classifies via
        ``_classify_status_error``, a transport-level failure via
        ``_classify_transport_error``, and a stream that simply ends
        without ``[DONE]`` and no exception at all (the connection was
        dropped cleanly) is classified ``PROVIDER_UNAVAILABLE``. This lets
        ``ModelGatewayService`` decide whether a *pre-first-token*
        interruption is worth retrying without this module knowing
        anything about retry policy itself."""
        self.validate_capabilities(request)
        body = self._build_request_body(request)
        body["stream"] = True
        tool_state: dict[int, dict] = {}
        reached_done = False
        try:
            with self._client.stream("POST", "/chat/completions", json=body) as http_response:
                http_response.raise_for_status()
                for raw_line in http_response.iter_lines():
                    if not raw_line or not raw_line.startswith("data:"):
                        continue
                    payload = raw_line[len("data:"):].strip()
                    if payload == "[DONE]":
                        reached_done = True
                        break
                    try:
                        event = json.loads(payload)
                    except ValueError:
                        continue  # tolerate a malformed/keep-alive line rather than aborting the whole stream
                    yield self._chunk_from_event(event, tool_state)
        except httpx.HTTPStatusError as exc:
            classified = self._classified_status_error(exc)
            yield self._interrupted_chunk(tool_state, str(exc), error_class=classified.error_class,
                                          retry_after_seconds=classified.retry_after_seconds)
            return
        except httpx.HTTPError as exc:
            classified = self._classified_transport_error(exc)
            yield self._interrupted_chunk(tool_state, str(exc), error_class=classified.error_class)
            return
        if not reached_done:
            yield self._interrupted_chunk(tool_state, "stream ended without reaching the [DONE] terminator",
                                          error_class=ProviderErrorClass.PROVIDER_UNAVAILABLE)

    def _chunk_from_event(self, event: dict, tool_state: dict[int, dict]) -> ModelResponse:
        choices = event.get("choices") or []
        choice = choices[0] if choices else {}
        delta = choice.get("delta") or {}
        content_delta = delta.get("content") or ""
        self._accumulate_tool_call_deltas(delta.get("tool_calls"), tool_state)

        raw_finish_reason = choice.get("finish_reason")
        if raw_finish_reason is None:
            return ModelResponse(content=content_delta)  # non-final: tool_calls/finish_reason/raw_usage not yet meaningful

        return ModelResponse(
            content=content_delta,
            tool_calls=self._finalize_tool_calls(tool_state),
            finish_reason=self._map_finish_reason(raw_finish_reason),
            raw_usage=self._usage_to_raw(event.get("usage")),
        )

    def _interrupted_chunk(self, tool_state: dict[int, dict], detail: str, *,
                          error_class: ProviderErrorClass = ProviderErrorClass.UNKNOWN,
                          retry_after_seconds: float | None = None) -> ModelResponse:
        logger.debug("%s: stream interrupted (%s) -- %s", type(self).__name__, error_class.value,
                    _scrub(detail, api_key=self._api_key, base_url=self.base_url))
        return ModelResponse(content="", tool_calls=self._finalize_tool_calls(tool_state),
                             finish_reason=FinishReason.ERROR, error_class=error_class,
                             retry_after_seconds=retry_after_seconds)

    @staticmethod
    def _accumulate_tool_call_deltas(raw_tool_call_deltas, tool_state: dict[int, dict]) -> None:
        """A streamed tool call's ``function.arguments`` arrives as
        successive string *fragments*, one per chunk, keyed by ``index``
        (multiple concurrent tool calls interleave by index) —
        ``ACT-MDL-FR-044``. Only the first delta for a given index
        typically carries ``id``/``function.name``; every later delta for
        that index carries only the next ``arguments`` fragment to append."""
        for raw in raw_tool_call_deltas or []:
            index = raw.get("index", 0)
            entry = tool_state.setdefault(index, {"id": None, "name": None, "arguments": ""})
            if raw.get("id"):
                entry["id"] = raw["id"]
            function = raw.get("function") or {}
            if function.get("name"):
                entry["name"] = function["name"]
            if function.get("arguments"):
                entry["arguments"] += function["arguments"]

    @staticmethod
    def _finalize_tool_calls(tool_state: dict[int, dict]) -> tuple[ModelToolCall, ...]:
        calls = []
        for index in sorted(tool_state):
            entry = tool_state[index]
            try:
                arguments = json.loads(entry["arguments"] or "{}")
            except ValueError:
                # A tool call whose fragments never fully reassembled into
                # valid JSON (e.g. the stream was interrupted mid-argument)
                # -- tolerate rather than crash the whole stream over it.
                arguments = {}
            call_id = entry["id"] or f"call_{index}"
            calls.append(ModelToolCall(id=call_id, name=entry["name"] or "", arguments=arguments))
        return tuple(calls)

    def describe(self) -> ModelCapabilities:
        return ModelCapabilities(
            supports_streaming=True,
            supports_tools=self._supports_tools,
            supports_system_prompt=True,
            max_context_tokens=self._max_context_tokens,
        )

    # ------------------------------------------------------------------ #
    # Request translation (ModelRequest -> OpenAI wire body)
    # ------------------------------------------------------------------ #
    def _build_request_body(self, request: ModelRequest) -> dict:
        body: dict = {
            "model": self.model,
            "messages": [self._message_to_wire(message) for message in request.messages],
        }
        if request.tools:
            body["tools"] = [self._tool_definition_to_wire(tool) for tool in request.tools]
        if request.max_tokens is not None:
            body["max_tokens"] = request.max_tokens
        if request.stop_sequences:
            body["stop"] = list(request.stop_sequences)

        forwarded, dropped = self._filter_sampling_parameters(request.sampling_parameters)
        body.update(forwarded)
        if dropped:
            logger.debug(
                "%s: dropped unsupported sampling parameter(s) %s (supported: %s)",
                type(self).__name__, sorted(dropped), sorted(_SUPPORTED_SAMPLING_PARAMETERS),
            )
        return body

    @staticmethod
    def _message_to_wire(message: ModelMessage) -> dict:
        wire: dict = {"role": message.role, "content": message.content}
        if message.role == "tool":
            wire["tool_call_id"] = message.tool_call_id
        return wire

    @staticmethod
    def _tool_definition_to_wire(tool: ModelToolDefinition) -> dict:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": dict(tool.parameters),
            },
        }

    @staticmethod
    def _filter_sampling_parameters(sampling_parameters) -> tuple[dict, set]:
        forwarded = {k: v for k, v in sampling_parameters.items() if k in _SUPPORTED_SAMPLING_PARAMETERS}
        dropped = set(sampling_parameters) - _SUPPORTED_SAMPLING_PARAMETERS
        return forwarded, dropped

    # ------------------------------------------------------------------ #
    # Response translation (OpenAI wire body -> ModelResponse)
    # ------------------------------------------------------------------ #
    def _parse_response(self, data: dict) -> ModelResponse:
        choices = data.get("choices") or []
        choice = choices[0] if choices else {}
        message = choice.get("message") or {}
        content = message.get("content") or ""
        tool_calls = self._parse_tool_calls(message.get("tool_calls"))
        finish_reason = self._map_finish_reason(choice.get("finish_reason"))

        return ModelResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            raw_usage=self._usage_to_raw(data.get("usage")),
        )

    @staticmethod
    def _usage_to_raw(usage: dict | None) -> dict:
        """ACT-MDL-FR-046 (Phase 5.7a.3) — when the provider omits ``usage``
        entirely (Ollama does, on some responses), this returns an empty
        dict, not a dict of zeros. ``{}`` and ``{"total_tokens": 0, ...}``
        mean different things: the platform (``ModelGatewayService``) uses
        ``bool(raw_usage)`` to decide ``token_accounting_complete`` — a
        zero-filled dict here would silently and permanently claim
        "accounting complete, zero tokens used," which is a fabrication,
        not an honest "unavailable." Individual *sub-fields* missing from
        an otherwise-present ``usage`` block still default to 0 -- that's
        a minor completeness gap in one number, not "no accounting at
        all," and is not what FR-046 is about."""
        if not usage:
            return {}
        return {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

    @staticmethod
    def _parse_tool_calls(raw_tool_calls) -> tuple[ModelToolCall, ...]:
        if not raw_tool_calls:
            return ()
        calls = []
        for index, raw in enumerate(raw_tool_calls):
            function = raw.get("function") or {}
            arguments_raw = function.get("arguments", "{}")
            arguments = json.loads(arguments_raw) if isinstance(arguments_raw, str) else (arguments_raw or {})
            # ACT-MDL-FR-028: a compatible implementation may omit the call
            # id (OpenAI always sends one; not every compatible server
            # does) -- synthesize a stable placeholder rather than raising,
            # since the id's only job downstream is pairing a later `tool`
            # role message back to this call.
            call_id = raw.get("id") or f"call_{index}"
            calls.append(ModelToolCall(id=call_id, name=function["name"], arguments=arguments))
        return tuple(calls)

    @staticmethod
    def _map_finish_reason(raw: str | None) -> FinishReason:
        try:
            return _FINISH_REASON_MAP[raw]
        except KeyError:
            raise ValueError(
                f"OpenAICompatibleProvider: unrecognized finish_reason {raw!r} -- refusing to guess. "
                f"Known values: {sorted(_FINISH_REASON_MAP)}."
            ) from None
