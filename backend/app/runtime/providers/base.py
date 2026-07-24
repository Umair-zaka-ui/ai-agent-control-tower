"""Phase 5.7a.1 SRS ACT-MDL-FR-001, FR-002, FR-009 — the model provider contract.

Every provider implementation (``MockProvider`` today; a real
OpenAI-compatible adapter in Phase 5.7a.2, others later) satisfies exactly
this interface. Nothing outside a provider's own adapter module may see or
produce provider-specific request/response shapes (``ACT-MDL-FR-006``) —
everything crossing this boundary is expressed in the provider-neutral
types in ``types.py`` (``ACT-MDL-FR-007``).

``complete()``, ``stream()`` and ``describe()`` are abstract — every
concrete provider must implement all three, or it cannot be instantiated
(``ACT-MDL-FR-001``/``ACT-MDL-FR-002``). ``supports()`` is deliberately
*not* abstract: it has a correct, shared default implementation derived
entirely from ``describe()``, so a provider's answer to "do you support
tools?" can never contradict its own capability declaration — a provider
may still override it, but doing so isn't required to satisfy the
interface.

**The one deliberate stub in this codebase, documented as such**:
``stream()`` is declared here (abstract, so every provider must still
implement its own) purely to fix every provider's signature now; real
incremental streaming is Phase 5.7a.3. A provider's own ``stream()`` must
never simply inherit a raising stub — ``MockProvider`` implements it for
real (trivially: the whole completion as one terminal chunk). Nothing in
this base class provides a working default for it, by design — there is
nothing sensible a base implementation of a model call could do.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from app.runtime.providers.errors import CapabilityUnsupportedError
from app.runtime.providers.types import ModelCapabilities, ModelRequest, ModelResponse

_CAPABILITY_FIELDS = {
    "streaming": "supports_streaming",
    "tools": "supports_tools",
    "system_prompt": "supports_system_prompt",
}


class ModelProvider(ABC):
    """The contract every model provider implementation satisfies."""

    @abstractmethod
    def complete(self, request: ModelRequest) -> ModelResponse:
        """Synchronous, non-streaming completion. Concrete implementations
        should call ``self.validate_capabilities(request)`` first (see
        ``MockProvider`` for the pattern) — this is not enforced
        automatically by this base class, so the method a provider
        overrides is exactly the one this interface documents, with no
        renamed template-method indirection."""

    @abstractmethod
    def stream(self, request: ModelRequest) -> Iterator[ModelResponse]:
        """Streaming completion — see the module docstring for why this is
        abstract (every provider must implement it) despite real
        incremental streaming being out of scope until Phase 5.7a.3.

        The ``NotImplementedError`` below is unreachable through normal
        instantiation (Python's ``abstractmethod`` machinery already
        refuses to instantiate any subclass that doesn't override this),
        but it exists so that a subclass which technically satisfies the
        override — e.g. by delegating straight back to
        ``super().stream(...)`` instead of providing a real
        implementation — fails loudly instead of silently returning
        ``None``. This is the one deliberate stub in this codebase; see
        the module docstring."""
        raise NotImplementedError(
            "ModelProvider.stream() has no base implementation -- every concrete provider must supply its "
            "own, even if (like MockProvider today) it is only a single terminal chunk. Real incremental "
            "streaming is Phase 5.7a.3."
        )

    @abstractmethod
    def describe(self) -> ModelCapabilities:
        """Returns this provider's full capability declaration."""

    def supports(self, capability: str) -> bool:
        """Derived from ``describe()`` — see the module docstring for why
        this is concrete rather than abstract."""
        field_name = _CAPABILITY_FIELDS.get(capability)
        if field_name is None:
            raise ValueError(f"Unknown capability {capability!r}; known: {sorted(_CAPABILITY_FIELDS)}.")
        return bool(getattr(self.describe(), field_name))

    def validate_capabilities(self, request: ModelRequest) -> None:
        """Raises ``CapabilityUnsupportedError`` if ``request`` asks this
        provider for something its own ``describe()`` says it doesn't
        support (``ACT-MDL-FR-009``). A shared helper every concrete
        provider's ``complete()``/``stream()`` calls explicitly — see the
        module docstring for why this isn't wired in automatically."""
        capabilities = self.describe()
        name = type(self).__name__
        if request.tools and not capabilities.supports_tools:
            raise CapabilityUnsupportedError(name, "tools")
        if any(message.role == "system" for message in request.messages) and not capabilities.supports_system_prompt:
            raise CapabilityUnsupportedError(name, "system_prompt")
