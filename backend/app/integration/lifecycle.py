"""Phase 2.1.1 SRS ACT-INT-FR-003 — the connector instance lifecycle state
machine. The single authority on valid transitions; ``ConnectorService``
consults this module for every state change and never inlines the graph
itself (mirroring how ``app/runtime/services.py``'s
``_EXECUTION_TRANSITIONS`` is the one place execution status transitions
are decided).

Graph (extended in Phase 2.1.3 — the original diagram is in that phase's
own history; ``recover`` is the one addition)::

    registered --configure--> configured --activate--> active
                                   ^                       |
                                   |                    disable
                                   |                       v
                                   +-------------------  disabled
                                                            |
            (any state) --mark_failed--> failed <----------+
                                            |
                                         recover
                                            v
                                          active

Five states, five named transition events. ``mark_failed`` is reachable
from *any* state (including ``failed`` itself is not re-enterable from
failed by this event) — the machine was already complete per Phase
2.1.1's own AC-16 even before anything drove it automatically. Phase
2.1.3's ``ConnectorHealthService`` is what actually drives both
directions now: a failing health check calls the same, unchanged
``mark_failed`` (``active -> failed``); a subsequent passing check calls
the new ``recover`` (``failed -> active``) — see that module for the
full policy. No HTTP endpoint calls ``mark_failed``/``recover`` directly
(§7 of the 2.1.1/2.1.3 build prompts lists no such routes) — both exist
as real, tested ``ConnectorService`` methods so the states and
transitions are genuine, not merely documented.

``disabled -> configured`` reuses the same ``configure`` event name as
``registered -> configured``: re-enabling a disabled instance is exactly
the same operation (supply/re-validate ``configuration``, land in
``configured``) as configuring a fresh one — see
``ConnectorService.update_configuration``'s docstring for the full
API-to-transition mapping this sub-phase settled on, since the build
prompt's §7 endpoint list underdetermines it (a genuine, documented
judgment call).

**Phase 2.1.3 decision**: ``recover`` (``failed -> active``) is a new
event, not folded into ``activate`` (``configured -> active``) — a
health-driven recovery and an operator activating a freshly-configured
connector are different operations with different preconditions (the
former only ever fires after a passing health check; the latter never
touches health at all), and conflating them would make the audit trail
(``event`` in ``connector_lifecycle_events``/the audit meta) ambiguous
about which actually happened."""

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
    # Phase 2.1.3, ACT-INT-FR-044 -- a passing health check recovers a
    # failed instance back to active. Only reachable from `failed`,
    # deliberately: recovering a `disabled` instance is an operator
    # decision (re-`activate` after reconfiguring), not something a
    # health check should ever do on its own.
    "recover": {
        S.FAILED.value: S.ACTIVE.value,
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
