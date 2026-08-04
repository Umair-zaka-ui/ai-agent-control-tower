"""Phase 2.1.2 SRS ACT-INT-FR-020, FR-021 — the authentication scheme contract.

Structural twin of ``app/integration/base.py``'s ``Connector`` ABC and
``app/runtime/providers/base.py``'s ``ModelProvider``: every scheme
implementation (six today — see ``schemes/``) satisfies exactly this
interface, registered explicitly (``registry.py``), never resolved by a
branching ``if scheme == "..."`` ladder anywhere in connector or runtime
code (``ACT-INT-FR-021`` — adding a scheme is a new registered subclass
and nothing else).

``OutboundRequest`` is the connector-neutral request fixture a scheme
applies a credential to — the auth-framework analog of
``app/runtime/providers/types.py``'s ``ModelRequest``. It carries no
connector-specific shape (no vendor field names), is immutable (frozen,
slotted, ``MappingProxyType``-wrapped headers), and ``apply()`` always
returns a *new* instance rather than mutating in place, the same
never-mutate-in-place discipline every neutral type in this codebase
already follows.

mTLS is deliberately **not** expressed as a header: a client certificate
configures the TLS handshake itself, not an HTTP header, so
``OutboundRequest`` carries a dedicated, optional ``tls_client_cert``
field (``(cert_pem, key_pem)``) that only the mTLS scheme ever sets.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Mapping


def _frozen_mapping(value: Mapping[str, str] | None) -> Mapping[str, str]:
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True, slots=True)
class OutboundRequest:
    """A connector-neutral outbound HTTP request fixture. Proven against
    ``MockConnector``/fixtures in this sub-phase — no real connector
    invokes yet (that needs 2.1.3's registry and a real connector, 2.2.x)."""

    method: str = "GET"
    url: str = ""
    headers: Mapping[str, str] = field(default_factory=dict)
    tls_client_cert: tuple[str, str] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", _frozen_mapping(self.headers))

    def with_headers(self, **new_headers: str) -> "OutboundRequest":
        merged = dict(self.headers)
        merged.update(new_headers)
        return replace(self, headers=merged)

    def with_tls_client_cert(self, cert_pem: str, key_pem: str) -> "OutboundRequest":
        return replace(self, tls_client_cert=(cert_pem, key_pem))


class AuthScheme(ABC):
    """The contract every authentication scheme implementation satisfies."""

    @abstractmethod
    def required_fields(self) -> tuple[str, ...]:
        """The credential bundle fields ``ConnectorCredentialService.store()``
        requires before it will encrypt and persist a credential for this
        scheme (``ACT-INT-FR-020``). For the two OAuth2 schemes, these are
        the *stored client configuration* fields (e.g. ``client_id``/
        ``client_secret``/``token_url``) — not ``access_token``, which is
        never stored directly here; see ``token_manager.py``."""

    @abstractmethod
    def apply(self, request: OutboundRequest, credential: Mapping[str, Any]) -> OutboundRequest:
        """Returns a new ``OutboundRequest`` with this scheme's credential
        applied. ``credential`` is always a **fully resolved**, ready-to-
        apply mapping — for the two OAuth2 schemes,
        ``ConnectorCredentialService.resolve_and_apply()`` has already
        called ``token_manager`` to obtain a valid, non-expired
        ``access_token`` and merged it in before this method ever runs;
        this method itself never acquires or refreshes a token."""
