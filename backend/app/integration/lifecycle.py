"""Phase 2.1.1 SRS ACT-INT-FR-003 — the connector instance lifecycle state
machine. The single authority on valid transitions; ``ConnectorService``
consults this module for every state change and never inlines the graph
itself (mirroring how ``app/runtime/services.py``'s
``_EXECUTION_TRANSITIONS`` is the one place execution status transitions
are decided).

Graph (exactly as drawn in the build prompt's §4.2)::

    registered --configure--> configured --activate--> active
                                   ^                       |
                                   |                    disable
                                   |                       v
                                   +-------------------  disabled
                                                            |
            (any state) --mark_failed--> failed <----------+

Five states, four named transition events. ``mark_failed`` is reachable
from *any* state (including ``failed`` itself is not re-enterable from
failed by this event — see ``_TRANSITIONS`` below) — the machine is
complete per AC-16 even though nothing in this sub-phase *drives* it
automatically; that is Phase 2.1.3's health monitoring. No HTTP endpoint
calls ``mark_failed`` in this sub-phase (§7 lists no such route) — it
exists as a real, tested service method so the state and the transition
into it are both genuine, not merely documented.

``disabled -> configured`` reuses the same ``configure`` event name as
``registered -> configured``: re-enabling a disabled instance is exactly
the same operation (supply/re-validate ``configuration``, land in
``configured``) as configuring a fresh one — see
``ConnectorService.update_configuration``'s docstring for the full
API-to-transition mapping this sub-phase settled on, since the build
prompt's §7 endpoint list underdetermines it (a genuine, documented
judgment call)."""

from __future__ import annotations

from app.integration.types import ConnectorLifecycleState as S

# Event name -> {from_state: to_state}. An event only ever has one
# destination per source state in this graph, so a flat mapping (not a
# from/to pair keyed separately) is sufficient and keeps `can_transition`
# and `transition` trivially symmetric.
_TRANSITIONS: dict[str, dict[str, str]] = {
    "configure": {
        S.REGISTERED.value: S.CONFIGURED.value,
        S.DISABLED.value: S.CONFIGURED.value,
    },
    "activate": {
        S.CONFIGURED.value: S.ACTIVE.value,
    },
    "disable": {
        S.ACTIVE.value: S.DISABLED.value,
    },
    "mark_failed": {
        S.REGISTERED.value: S.FAILED.value,
        S.CONFIGURED.value: S.FAILED.value,
        S.ACTIVE.value: S.FAILED.value,
        S.DISABLED.value: S.FAILED.value,
    },
}


def can_transition(event: str, from_state: str) -> bool:
    return _TRANSITIONS.get(event, {}).get(from_state) is not None


def target_state(event: str, from_state: str) -> str | None:
    """The state ``from_state`` lands in after ``event``, or ``None`` if
    that transition is not valid — callers (``ConnectorService``) turn a
    ``None`` into ``ConnectorInvalidTransitionError``, never silently
    ignore it."""
    return _TRANSITIONS.get(event, {}).get(from_state)


def all_states() -> tuple[str, ...]:
    return tuple(state.value for state in S)
