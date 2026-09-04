"""Phase 5.2 (M5.2) - the fixed adapter registry.

Mirrors ``app.scheduler.handlers``'s own registry exactly: a module-level
dict populated by decorator at import time, never a dynamic import keyed by a
database value. A ``DiscoverySource.adapter_key`` can never make the platform
import or execute arbitrary code -- an unrecognized key raises
``DISCOVERY_ADAPTER_UNKNOWN``.
"""

from __future__ import annotations

from collections.abc import Callable

from app.discovery.adapters.base import DiscoveryAdapter
from app.identity.errors import ErrorCode, IdentityError

_ADAPTERS: dict[str, DiscoveryAdapter] = {}


def register(adapter_key: str) -> Callable[[type[DiscoveryAdapter]], type[DiscoveryAdapter]]:
    def decorator(cls: type[DiscoveryAdapter]) -> type[DiscoveryAdapter]:
        if adapter_key in _ADAPTERS:
            raise RuntimeError(f"Duplicate discovery adapter key: {adapter_key}")
        _ADAPTERS[adapter_key] = cls()
        return cls
    return decorator


def resolve(adapter_key: str) -> DiscoveryAdapter:
    adapter = _ADAPTERS.get(adapter_key)
    if adapter is None:
        raise IdentityError(
            ErrorCode.DISCOVERY_ADAPTER_UNKNOWN,
            f"'{adapter_key}' is not a registered discovery adapter. Known adapters: "
            f"{', '.join(registered_keys())}.",
        )
    return adapter


def registered_keys() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))


def _ensure_reference_adapter_registered() -> None:
    """Importing this module alone must be enough to see the reference
    adapter registered -- so callers (routes, the scheduler handler, tests)
    never need to remember a separate import for side effects."""
    from app.discovery.adapters import http_agent_registry  # noqa: F401


_ensure_reference_adapter_registered()

__all__ = ["register", "resolve", "registered_keys"]
