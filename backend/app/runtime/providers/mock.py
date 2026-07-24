"""Phase 5.7a.1 SRS ACT-MDL-FR-008 — MockProvider.

The first (and, this sub-phase, only) concrete ``ModelProvider``: a
deterministic, always-available adapter — proof that the interface can
express a real provider's shape without distorting it. Its *externally
observable* behavior through ``ModelGatewayService.invoke()`` (echoing the
original input payload, a positive token count, ``provider == "MOCK"``) is
unchanged from the pre-abstraction implementation — see
``backend/app/runtime/services.py`` and ``docs/runtime/providers.md`` for
exactly what changed internally versus what every existing test still
asserts.
"""

from __future__ import annotations

from collections.abc import Iterator

from app.runtime.providers.base import ModelProvider
from app.runtime.providers.types import FinishReason, ModelCapabilities, ModelRequest, ModelResponse

DEFAULT_MODEL = "mock-model"
MAX_CONTEXT_TOKENS = 8192


class MockProvider(ModelProvider):
    def __init__(self, *, base_url: str | None = None, model: str = DEFAULT_MODEL) -> None:
        # base_url is accepted (not just tolerated) for interface uniformity
        # with every future provider (ACT-MDL-FR-010) even though MOCK has
        # nothing to call — see test_provider_abstraction.py's AC-10 test.
        self.base_url = base_url
        self.model = model

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.validate_capabilities(request)
        input_text = "".join(message.content for message in request.messages)
        input_tokens = max(1, len(input_text) // 4)
        content = f"[{self.model}] processed {len(request.messages)} message(s)."
        output_tokens = max(1, len(content) // 4)
        return ModelResponse(
            content=content,
            tool_calls=(),
            finish_reason=FinishReason.STOP,
            raw_usage={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        )

    def stream(self, request: ModelRequest) -> Iterator[ModelResponse]:
        """Trivial: yields the whole completion as a single terminal chunk.
        Real incremental streaming is Phase 5.7a.3 — this satisfies the
        interface today without distorting MOCK's behavior, per §4.1."""
        yield self.complete(request)

    def describe(self) -> ModelCapabilities:
        return ModelCapabilities(
            supports_streaming=True,
            supports_tools=False,
            supports_system_prompt=True,
            max_context_tokens=MAX_CONTEXT_TOKENS,
        )
