"""Phase 5.7a.1 SRS ACT-MDL-FR-003, FR-005, FR-010 — provider registry.

Explicit registration, not directory-scanning discovery — greppable, not
magic. ``_REGISTRY`` is populated once, at the bottom of this module, the
single place every provider gets registered — 5.7a.2 added one more
``register(...)`` line there, plus ``resolve()``'s ``model``/``api_key``
forwarding below (a genuine 5.7a.1 gap: nothing previously threaded either
through to the provider instance, only into usage-reporting strings)."""

from __future__ import annotations

import inspect

from app.runtime.providers.base import ModelProvider
from app.runtime.providers.errors import ProviderUnavailableError
from app.runtime.providers.mock import MockProvider
from app.runtime.providers.openai_compatible import OpenAICompatibleProvider

_REGISTRY: dict[str, type[ModelProvider]] = {}


def register(identifier: str, provider_cls: type[ModelProvider]) -> None:
    """Registers ``provider_cls`` under ``identifier`` (case-insensitive —
    stored upper-cased, matching ``AgentVersion.model_configuration``'s
    existing ``provider`` convention, e.g. ``"MOCK"``)."""
    _REGISTRY[identifier.upper()] = provider_cls


def resolve(
    identifier: str, *, base_url: str | None = None, model: str | None = None, api_key: str | None = None,
) -> ModelProvider:
    """Instantiates the provider registered under ``identifier``.
    ``ACT-MDL-FR-005``: an unregistered identifier raises
    ``ProviderUnavailableError`` (``MODEL_PROVIDER_UNAVAILABLE``) —
    preserves the pre-abstraction fail-closed behavior exactly.

    ``model``/``api_key`` (added Phase 5.7a.2) are each forwarded to the
    provider's constructor only if that constructor actually declares the
    matching parameter — checked via ``inspect.signature`` rather than
    assumed, so a provider with no notion of "model" or no need for an API
    key (``MockProvider`` accepts ``model`` only for cosmetic labeling and
    has no notion of a key at all; the test-only ``_RecordingProvider``
    accepts neither) isn't forced to add a parameter it has no use for.
    When either is ``None`` (not configured), nothing is forwarded and the
    provider's own constructor default applies — unchanged from 5.7a.1's
    behavior for callers that never pass either."""
    provider_cls = _REGISTRY.get((identifier or "").upper())
    if provider_cls is None:
        raise ProviderUnavailableError(identifier)
    accepted = inspect.signature(provider_cls.__init__).parameters
    kwargs: dict[str, object] = {"base_url": base_url}
    if model is not None and "model" in accepted:
        kwargs["model"] = model
    if api_key is not None and "api_key" in accepted:
        kwargs["api_key"] = api_key
    return provider_cls(**kwargs)


def registered_identifiers() -> list[str]:
    return sorted(_REGISTRY)


register("MOCK", MockProvider)
# "OPENAI_COMPATIBLE" names the wire protocol, not a vendor -- Ollama, vLLM
# and LM Studio all speak it and are not OpenAI (ACT-MDL-FR-027). A future
# dedicated OpenAI adapter with vendor-specific behavior can still claim
# "OPENAI" for itself later without colliding with this one.
register("OPENAI_COMPATIBLE", OpenAICompatibleProvider)
