"""Phase 5.2 (M5.2) - the discovery-adapter contract.

Structural twin of ``app.integration.base.Connector`` (Phase 2.1.1), because
discovery *is* a read-only connector variant: containment by construction,
not convention. The one deliberate difference from ``Connector`` is
``fetch()``'s signature -- **it takes no ``Session`` parameter, at all,
anywhere in its type**. That is the structural half of AC-06 ("no DB lock or
open transaction held across the external call"): an adapter that wanted to
touch the database during a fetch would have no object to touch it with, not
merely an instruction not to. ``test_ac06_...`` in
``tests/discovery/test_discovery_framework.py`` asserts this via
``inspect.signature`` over every registered adapter, not just this one.

``fetch()`` also never receives a database session for a second reason: an
adapter's job is to talk to one external system and produce plain data, the
same "connector never sees a session" containment 2.1.4's SDK already
enforces for tool-invoking connectors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping

from app.integration.sdk import GovernedHttpClient


@dataclass(frozen=True, slots=True)
class DiscoveryAdapterDescriptor:
    """What a source-management UI/API needs to offer this adapter: its
    identifier, a human label, and the JSON Schema its ``config`` must
    satisfy (validated the same way a connector's configuration is,
    reusing ``validate_configuration_schema``)."""

    adapter_key: str
    display_name: str
    config_schema: dict = field(default_factory=dict)
    requires_secret: bool = False


@dataclass(frozen=True, slots=True)
class RawDiscoveryItem:
    """One item exactly as an external source reported it -- before
    normalization. Never persisted in this shape; ``normalize()`` turns it
    into a :class:`NormalizedObservation`."""

    external_identifier: str
    payload: dict


@dataclass(frozen=True, slots=True)
class DiscoveryFetchResult:
    """Everything one ``fetch()`` call produced, plus enough to resume or
    report degradation -- never raises for a partial/degraded fetch (SRS
    M5.2 §11, "fails open"); a hard failure (unreachable source, auth
    rejected) is the one case ``fetch()`` may raise, and the caller
    (``DiscoveryRunService``) turns that into a FAILED run, never a platform
    error."""

    items: tuple[RawDiscoveryItem, ...]
    next_checkpoint: dict = field(default_factory=dict)
    complete: bool = True
    #: Set when the source truncated results (rate limit, page cap) --
    #: drives a PARTIAL run status rather than SUCCEEDED, per SRS M5.2 §11.
    degraded: bool = False
    degraded_reason: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedObservation:
    """The canonical, source-neutral shape every adapter's ``normalize()``
    produces. ``confidence`` is a deterministic, source-reported or
    source-class-derived number in [0, 1] -- never an opaque ML score (SRS
    M5.2 §I, §7.4). ``raw`` is scrubbed by the caller
    (``app.observability.scrubbing.scrub``) before persistence; an adapter
    author does not need to scrub it themselves, but must not smuggle a
    secret into ``external_identifier`` (which is never scrubbed, since it
    is also used, unscrubbed, as the reconciliation matching key)."""

    external_identifier: str
    name: str
    agent_type: str = "ASSISTANT"
    origin_provider: str = "UNKNOWN"
    description: str | None = None
    confidence: Decimal = Decimal("1.00")
    raw: dict = field(default_factory=dict)


class DiscoveryAdapter(ABC):
    """The contract every discovery adapter *type* implementation satisfies."""

    @abstractmethod
    def describe(self) -> DiscoveryAdapterDescriptor:
        """This adapter type's declaration: identifier, display name, and the
        configuration schema a ``DiscoverySource`` row must satisfy."""

    @abstractmethod
    def validate_configuration(self, configuration: Mapping[str, Any]) -> None:
        """Validates a prospective source ``config``, raising
        ``DiscoveryConfigInvalidError`` on failure."""

    @abstractmethod
    def build_client(self, configuration: Mapping[str, Any]) -> GovernedHttpClient:
        """Builds the one network primitive this fetch may use, bound (at
        construction, per ``GovernedHttpClient``'s own containment rule) to
        exactly the hosts this source's configuration declares."""

    @abstractmethod
    def fetch(
        self,
        client: GovernedHttpClient,
        configuration: Mapping[str, Any],
        secret: str | None,
        checkpoint: Mapping[str, Any] | None,
    ) -> DiscoveryFetchResult:
        """Performs the external call(s) via ``client`` only. **Deliberately
        no ``Session``/``db`` parameter anywhere in this signature** -- see
        this module's docstring. Must tolerate and report partial failure
        (rate limits, a truncated page) via ``DiscoveryFetchResult.degraded``
        rather than raising; may raise only for a hard failure (source
        entirely unreachable, authentication rejected)."""

    @abstractmethod
    def normalize(self, item: RawDiscoveryItem) -> NormalizedObservation:
        """Pure function: one source-shaped item -> one canonical
        observation. No I/O, no database, no side effect."""
