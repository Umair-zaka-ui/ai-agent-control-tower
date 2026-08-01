"""Phase 2.1.1 SRS ACT-INT-FR-002, FR-007 — connector-neutral declaration types.

Mirrors ``app/runtime/providers/types.py``'s two hard rules exactly, for
the same reason: every current and future connector translates to/from
these types, so nothing connector- or vendor-specific may appear here
(``ACT-INT-FR-006``, the runtime-never-knows principle) — no ``sap_``/
``salesforce_`` prefix, no field only one connector has. All types are
immutable: frozen, slotted dataclasses with tuples for ordered
collections and ``MappingProxyType`` wrapping for dict-shaped fields, so a
caller can't mutate a descriptor through a nested dict either (AC-06).

``ToolContract`` is the *declaration* of a tool a connector exposes — the
shape a future tool-bridge (out of scope this sub-phase, see the build
prompt's §3) will convert into an actual invokable ``Tool`` row. Nothing
here executes anything; ``parameters`` is a JSON-Schema object, the same
shape used everywhere else in this codebase for input/output contracts
(``AgentDefinition.input_schema``, ``ModelToolDefinition.parameters``)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


def _frozen_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


class ConnectorLifecycleState(str, Enum):
    """``ACT-INT-FR-003`` — the five states a ``ConnectorInstance`` can be
    in. String values match the database column exactly (lowercase, per
    the SRS's own table definition in §5) — ``app/integration/lifecycle.py``
    is the single authority on which transitions between them are valid."""

    REGISTERED = "registered"
    CONFIGURED = "configured"
    ACTIVE = "active"
    DISABLED = "disabled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ToolContract:
    """One tool a connector declares it can expose (``ACT-INT-FR-007``) —
    declaration only; nothing here binds it into a real ``Tool`` row or
    invokes it. That bridge is explicitly out of scope for this
    sub-phase (see the build prompt's §3 "On the tool bridge")."""

    name: str
    description: str
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", _frozen_mapping(self.parameters))


@dataclass(frozen=True, slots=True)
class ConnectorDescriptor:
    """A connector type's full declaration (``ACT-INT-FR-002``), returned
    by ``Connector.describe()`` — analogous to ``ModelCapabilities``, but
    broader, since a connector declares more than raw capability flags: its
    identifier, contract version, capability set, configuration schema,
    authentication *requirements* (declared, never performed — that
    framework is Phase 2.1.2), and the tool contract(s) it exposes."""

    connector_type: str
    version: str
    capabilities: Mapping[str, Any] = field(default_factory=dict)
    config_schema: Mapping[str, Any] = field(default_factory=dict)
    auth_requirements: Mapping[str, Any] = field(default_factory=dict)
    tool_contracts: tuple[ToolContract, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "capabilities", _frozen_mapping(self.capabilities))
        object.__setattr__(self, "config_schema", _frozen_mapping(self.config_schema))
        object.__setattr__(self, "auth_requirements", _frozen_mapping(self.auth_requirements))
        object.__setattr__(self, "tool_contracts", tuple(self.tool_contracts))
