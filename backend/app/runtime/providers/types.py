"""Phase 5.7a.1 SRS ACT-MDL-FR-006, FR-007 — provider-neutral internal representation.

This is the most consequential design in the sub-phase: every current and
future adapter translates to and from these types, and changing them later
means touching every adapter. Two hard rules, both mechanically checked by
``test_provider_abstraction.py``:

- **No provider-specific name appears here** (``ACT-MDL-FR-006``) — no
  ``openai_``/``anthropic_`` prefix, no field only one provider has. An
  adapter's own vocabulary (e.g. OpenAI's ``role``/``tool_calls`` JSON
  shape) is translated to/from these types entirely inside that adapter's
  own module; nothing provider-specific crosses this boundary.
- **Never silently guess a representation** (REPO_STATE §10.15, the same
  principle ``canonical.py`` established for checksums) — sampling
  parameters are a free-form ``dict`` rather than fixed fields, since
  providers accept different sets and the *adapter* is responsible for
  filtering/translating them; a construct these types cannot express
  (an unrecognized message role, an unmapped finish reason) raises rather
  than being coerced or dropped. ``FinishReason`` is a plain ``Enum``
  specifically so ``FinishReason("some_unmapped_value")`` raises
  ``ValueError`` for free — an adapter maps its own raw reason strings
  onto these five values explicitly and lets that lookup fail loudly for
  anything it doesn't recognize, rather than defaulting to ``STOP``/``ERROR``.

All types are immutable: frozen, slotted dataclasses with tuples (not
lists) for ordered collections, and ``MappingProxyType`` wrapping for
dict-shaped fields (``sampling_parameters``, ``arguments``, ``parameters``,
``raw_usage``) so a caller can't mutate a request/response through a
nested dict either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

_VALID_ROLES = ("system", "user", "assistant", "tool")


class FinishReason(str, Enum):
    """Why a completion stopped. An adapter maps its provider's own raw
    reason string onto one of these five explicitly (e.g.
    ``FinishReason(_OPENAI_FINISH_MAP[raw])``) — an unrecognized raw value
    must raise, never silently default."""

    STOP = "STOP"
    LENGTH = "LENGTH"
    TOOL_CALLS = "TOOL_CALLS"
    CONTENT_FILTER = "CONTENT_FILTER"
    ERROR = "ERROR"


def _frozen_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True, slots=True)
class ModelToolDefinition:
    """A tool the model may call, described provider-neutrally (JSON
    Schema parameters — the same schema shape used everywhere else in this
    codebase for input/output contracts, see ``AgentDefinition.input_schema``)."""

    name: str
    description: str
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", _frozen_mapping(self.parameters))


@dataclass(frozen=True, slots=True)
class ModelToolCall:
    """A tool invocation the model requested."""

    id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", _frozen_mapping(self.arguments))


@dataclass(frozen=True, slots=True)
class ModelMessage:
    """One turn in a conversation. ``tool_call_id`` is set only on a
    ``role="tool"`` message, referencing the ``ModelToolCall.id`` it answers."""

    role: str
    content: str
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        if self.role not in _VALID_ROLES:
            raise ValueError(f"Unsupported message role {self.role!r}; must be one of {_VALID_ROLES}.")


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """A provider-neutral completion request. ``sampling_parameters`` is a
    free-form dict (temperature, top_p, ...) rather than fixed fields —
    different providers accept different sets, and each adapter is
    responsible for filtering/translating the ones it understands and
    ignoring (or rejecting, via ``ModelProvider.describe()``) the rest."""

    messages: tuple[ModelMessage, ...]
    tools: tuple[ModelToolDefinition, ...] = ()
    sampling_parameters: Mapping[str, Any] = field(default_factory=dict)
    max_tokens: int | None = None
    stop_sequences: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", tuple(self.tools))
        object.__setattr__(self, "stop_sequences", tuple(self.stop_sequences))
        object.__setattr__(self, "sampling_parameters", _frozen_mapping(self.sampling_parameters))


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """A provider-neutral completion response. ``raw_usage`` is structure
    only in this sub-phase — a passthrough dict of whatever token/usage
    numbers the provider reported; formal accounting (cost, normalized
    fields) is Phase 5.7a.3/5.7a.5, not this one."""

    content: str
    tool_calls: tuple[ModelToolCall, ...] = ()
    finish_reason: FinishReason = FinishReason.STOP
    raw_usage: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        object.__setattr__(self, "raw_usage", _frozen_mapping(self.raw_usage))


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """What a provider (and, implicitly, the model/deployment it's
    configured for) actually supports — declared once via
    ``ModelProvider.describe()`` and enforced before every request
    (``ACT-MDL-FR-009``)."""

    supports_streaming: bool
    supports_tools: bool
    supports_system_prompt: bool
    max_context_tokens: int
