"""Phase 2.2.4 SRS ACT-INT-FR-161, FR-164 — the queue connector's scope
enforcement: is the requested operation permitted for a resolved,
declared queue binding?

**Deliberately simpler than storage's path-canonicalization enforcer**
(``app/integration/connectors/storage/scope.py``), and it stays that way
on purpose. Storage needed canonicalize-then-contain because the model
supplies a *path fragment* that must be resolved and proven in-bounds.
This connector makes the analogous "the model cannot redirect a publish
outside the declared queue" (``ACT-INT-FR-164``) guarantee a different,
stronger way: **the target queue is fixed by the tool contract itself,
never a value the model supplies at all** (see ``declaration.py``'s own
``tool_contracts_for`` — a publish contract's only parameter is the
message body; a consume contract's only parameter is an optional
``max_messages`` cap). There is no queue-name string to canonicalize,
decode, or validate against an allowlist, because there is no queue-name
input in the first place — containment by absence, the same principle
2.2.2's SQL executor and 2.2.3's own tool-contract shape already
established, applied here to the publish target itself.

What this module *does* check, isolated and unit-testable with zero
dependency on a live broker: whether a specific resolved binding's own
declared operation (``PUBLISH`` or ``CONSUME``, exactly one per binding
— mirrors the storage connector's one-operation-per-scope shape) matches
what is actually being attempted against it. A binding declared for
``PUBLISH`` only must reject a ``CONSUME`` attempt, and vice versa —
tested directly against the bridge's two entry points
(``invoker.publish_message``/``consume_messages``), defense in depth
even though the model-facing tool-contract shape already makes this
mismatch unreachable through ordinary use."""

from __future__ import annotations

PUBLISH = "PUBLISH"
CONSUME = "CONSUME"
_OPERATIONS = frozenset({PUBLISH, CONSUME})


class QueueScopeViolationError(Exception):
    """The requested operation is not permitted for the resolved
    binding. The message never includes a credential or a message
    payload — only the binding name and the mismatched operation."""


def check_operation_permitted(binding_name: str, declared_operation: str, requested_operation: str) -> None:
    """Raises ``QueueScopeViolationError`` unless ``requested_operation``
    exactly matches what ``binding_name`` was declared for. There is no
    ``"BOTH"`` value to widen this check — an author who wants a queue
    reachable both ways declares it twice, once per operation, under two
    distinct binding names, exactly the pattern 2.2.3's storage connector
    established for a bucket needing both read and write scopes."""
    if requested_operation not in _OPERATIONS:
        raise ValueError(f"unknown operation '{requested_operation}'")
    if declared_operation != requested_operation:
        raise QueueScopeViolationError(
            f"binding '{binding_name}' is declared for {declared_operation}, not {requested_operation}"
        )
