"""Phase 5.7a.1 SRS ACT-MDL-FR-003, FR-005, FR-010 — provider registry.

Explicit registration, not directory-scanning discovery — greppable, not
magic. ``_REGISTRY`` is populated once, at the bottom of this module, the
single place every provider gets registered as more are built in later
sub-phases (5.7a.2 adds one line here, nothing else).
"""

from __future__ import annotations

from app.runtime.providers.base import ModelProvider
from app.runtime.providers.errors import ProviderUnavailableError
from app.runtime.providers.mock import MockProvider

_REGISTRY: dict[str, type[ModelProvider]] = {}


def register(identifier: str, provider_cls: type[ModelProvider]) -> None:
    """Registers ``provider_cls`` under ``identifier`` (case-insensitive —
    stored upper-cased, matching ``AgentVersion.model_configuration``'s
    existing ``provider`` convention, e.g. ``"MOCK"``)."""
    _REGISTRY[identifier.upper()] = provider_cls


def resolve(identifier: str, *, base_url: str | None = None) -> ModelProvider:
    """Instantiates the provider registered under ``identifier``.
    ``ACT-MDL-FR-005``: an unregistered identifier raises
    ``ProviderUnavailableError`` (``MODEL_PROVIDER_UNAVAILABLE``) —
    preserves the pre-abstraction fail-closed behavior exactly."""
    provider_cls = _REGISTRY.get((identifier or "").upper())
    if provider_cls is None:
        raise ProviderUnavailableError(identifier)
    return provider_cls(base_url=base_url)


def registered_identifiers() -> list[str]:
    return sorted(_REGISTRY)


register("MOCK", MockProvider)
