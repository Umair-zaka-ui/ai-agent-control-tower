"""Phase 5.7a.2 SRS ACT-MDL-FR-020..028 — OpenAI-compatible chat completions adapter.

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

**``stream()`` is a placeholder** — see the module-level note near its
definition. Real incremental streaming (parsing Server-Sent Events chunk by
chunk) is Phase 5.7a.3.

**No credential resolution, no retry/backoff, no error taxonomy** — an API
key is read as a plain configured value if present; any HTTP failure or
unparseable response raises the one coarse ``ProviderRequestFailedError``.
Both are deliberately out of scope here; see Phase 5.7a.4/5.7a.5.
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
            raise ProviderRequestFailedError(
                type(self).__name__, f"HTTP {exc.response.status_code} from provider"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderRequestFailedError(type(self).__name__, str(exc)) from exc

        try:
            data = http_response.json()
        except ValueError as exc:
            raise ProviderRequestFailedError(type(self).__name__, "response body was not valid JSON") from exc

        return self._parse_response(data)

    def stream(self, request: ModelRequest) -> Iterator[ModelResponse]:
        """Placeholder: delegates to ``complete()`` and yields the whole
        response as a single terminal chunk. This satisfies the interface
        (every provider must implement ``stream()``) without pretending to
        stream — no SSE parsing happens here. **Closure condition**: Phase
        5.7a.3 replaces this with real incremental parsing of the
        provider's ``stream=true`` SSE response; nothing about this
        adapter's other methods needs to change when that happens."""
        yield self.complete(request)

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
        usage = data.get("usage") or {}

        return ModelResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            raw_usage={
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
        )

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
