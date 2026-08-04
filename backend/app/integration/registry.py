"""Phase 2.1.3 SRS ACT-INT-FR-040, FR-041, FR-044 — the connector registry.

The single lookup surface for resolving a connector identifier to its
implementation, configuration, and (once invocable) credential
reference — "nothing downstream reaches into ``connector_instances``
directly" is the whole point of this module existing separately from
``service.py``'s ``ConnectorTypeService``/``ConnectorService``, which it
wraps rather than duplicates.

Two resolution concerns, matching the build prompt's own §4.1 split:

- **Type resolution** (``resolve_type``/``list_types``) — identifier to
  registered ``Connector`` implementation. Already existed as
  ``ConnectorTypeService.get_or_404``/``list_types`` since 2.1.1; this
  module re-exposes it under the registry's single surface rather than
  reimplementing it.
- **Instance resolution** (``resolve_instance_for_invocation``/
  ``list_instances``) — for an org, an instance id to its configured,
  tenant-scoped row plus its type's declared auth scheme. This is new:
  ``resolve_instance_for_invocation`` is the **fail-fast wiring point**
  (``ACT-INT-FR-044``) — it raises ``ConnectorUnavailableError``
  immediately for a ``failed`` or ``disabled`` instance, before anything
  downstream ever attempts a real call. Phase 2.2.x's tool bridge is
  expected to call this method first and inherit the fail-fast guarantee
  for free, with no fail-fast logic of its own to write.

**Deliberately narrow scope, stated explicitly**: this method only
enforces the ``failed``/``disabled`` fail-fast guarantee
``ACT-INT-FR-044`` names. It does **not** additionally require
``active`` — whether a merely ``registered``/``configured`` (not yet
activated) instance may be invoked is an invocation-semantics decision
that belongs to 2.2.x's tool bridge, not to this registry.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from app.integration.errors import ConnectorUnavailableError
from app.integration.service import ConnectorService, ConnectorTypeService
from app.models.integration import Connector, ConnectorInstance

_FAIL_FAST_STATES = frozenset({"failed", "disabled"})


@dataclass(frozen=True, slots=True)
class ResolvedConnector:
    """A plain, immutable snapshot of everything a caller needs to invoke
    a connector instance — never the ORM row itself, the same
    "cross a boundary with plain values only" discipline
    ``ResolvedCredential`` (5.7a.5) established."""

    instance_id: uuid.UUID
    organization_id: uuid.UUID
    connector_type: str
    lifecycle_state: str
    configuration: Mapping[str, Any]
    auth_scheme: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "configuration", MappingProxyType(dict(self.configuration)))


class ConnectorRegistry:
    def __init__(self, db) -> None:
        self.db = db
        self.types = ConnectorTypeService(db)
        self.instances = ConnectorService(db)

    # --- type resolution (ACT-INT-FR-040) ------------------------------- #
    def resolve_type(self, connector_type: str, version: str | None = None) -> Connector:
        return self.types.get_or_404(connector_type, version)

    def list_types(self) -> list[Connector]:
        return self.types.list_types()

    # --- instance resolution & listing (ACT-INT-FR-041) ------------------ #
    def list_instances(self, organization_id: uuid.UUID) -> list[ConnectorInstance]:
        return self.instances.list_for_org(organization_id)

    def resolve_instance(self, organization_id: uuid.UUID, instance_id: uuid.UUID) -> ConnectorInstance:
        """Plain lookup, tenant-scoped, no fail-fast check — used by
        callers (like health checks) that need to inspect or act on an
        instance regardless of its current state."""
        return self.instances.get_or_404(organization_id, instance_id)

    # --- the fail-fast invocation boundary (ACT-INT-FR-044) --------------- #
    def resolve_instance_for_invocation(self, organization_id: uuid.UUID, instance_id: uuid.UUID) -> ResolvedConnector:
        """Raises ``ConnectorUnavailableError`` immediately if the
        instance is ``failed`` or ``disabled`` — no call is ever
        attempted, no timeout is ever risked. 2.2.x's tool bridge calls
        this before invoking anything."""
        instance = self.instances.get_or_404(organization_id, instance_id)
        if instance.lifecycle_state in _FAIL_FAST_STATES:
            raise ConnectorUnavailableError(instance_id, instance.lifecycle_state)
        type_row = self.db.get(Connector, instance.connector_id)
        return ResolvedConnector(
            instance_id=instance.id, organization_id=instance.organization_id,
            connector_type=type_row.connector_type, lifecycle_state=instance.lifecycle_state,
            configuration=instance.configuration, auth_scheme=(type_row.auth_requirements or {}).get("scheme", "NONE"),
        )
