"""Phase 4.1 -- the runtime-event contract, emitted best-effort (ACT-SRS-M4
§9, §13, §20-§22).

**Three planes, three records, and they are not interchangeable** (§5):

* The **domain** plane is authoritative. ``agent_executions``, ``tool_calls``,
  ``execution_attempts`` -- these say what happened, and a disagreement between
  them and anything else is resolved in their favour.
* The **audit** plane is the compliance record. ``authorization_audit`` answers
  "who was allowed to do what", is written on the transaction that made the
  decision, and must not be lossy.
* The **telemetry** plane is derived and best-effort. It exists to make the
  system observable, and it is explicitly allowed to lose an event rather than
  fail an execution.

``runtime_events`` is the telemetry plane's table, and **it already existed**
before this phase -- ~297,000 rows of it. What it did not have was a contract:
events were written by ``_record_event`` in ``app/runtime/services.py`` with a
raw ``meta`` dict as payload, no trace identity (``correlation_id`` was null on
essentially every row), and no scrubbing. This module supplies the contract
that table was missing. It adds no table, which is the §13 answer: the storage
was already there and was already the right shape.

**Non-gating is the whole design constraint** (§9). Everything else in this
codebase fails closed -- an authorization error denies, a policy error blocks,
a gate failure halts a rollout. Telemetry is the deliberate inverse. An
execution that ran correctly but whose telemetry write failed is a *successful
execution with missing telemetry*, and any other reading of it turns the
observability layer into a new way for production to break.

That is enforced two ways, and both are necessary:

1. :func:`emit` catches ``Exception`` and returns ``False``. Obvious, and on
   its own insufficient.
2. The write happens inside a **SAVEPOINT**. Without it, a failed ``INSERT``
   leaves the caller's transaction in a failed state, so the *caller's* commit
   raises later -- and an exception swallowed here would surface as a
   corrupted execution three frames up. Catching the exception without
   isolating the transaction would look correct in a unit test and fail in
   production, which is precisely the kind of bug the §9 rule exists to
   prevent.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from app.observability.attributes import SemanticAttributes
from app.observability.capture import filter_for_capture
from app.observability.trace import SpanContext, TraceContext

logger = logging.getLogger(__name__)


class Outcome(str, Enum):
    """The result an event records. Bounded on purpose -- ``outcome`` is a
    metric-eligible dimension in all but name, and a free-text field here would
    reintroduce the cardinality problem §12 forbids."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    DENIED = "DENIED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    #: The event records a state change with no pass/fail character (a claim,
    #: a queue transition). Distinct from SUCCESS, which asserts something
    #: worked.
    INFO = "INFO"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RuntimeEventRecord:
    """The structured shape of one telemetry event (M4-4.1-FR-020, FR-021).

    Deliberately *not* the ORM model. This is the contract -- what a caller
    supplies and what every consumer can rely on being present -- and keeping
    it separate from ``app.models.runtime.RuntimeEvent`` means the contract can
    be constructed, validated and asserted about in a unit test with no
    database, and that a storage change does not silently become a contract
    change.

    Note what is absent: no free-text ``message``. An event carries a bounded
    ``event_type``, a bounded ``outcome``, structured attributes and a scrubbed
    payload. A prose field would be the easiest possible place for a prompt or
    a credential to arrive in the telemetry plane by accident."""

    event_type: str
    outcome: Outcome
    occurred_at: datetime
    trace_id: str
    span_id: str | None = None
    parent_span_id: str | None = None
    request_id: str | None = None
    attributes: SemanticAttributes = field(default_factory=SemanticAttributes)
    #: Already filtered and scrubbed by :meth:`build`. There is no path that
    #: sets this from raw caller input.
    payload: dict | None = None
    severity: str = "INFO"

    @classmethod
    def build(cls, *, event_type: str, outcome: Outcome = Outcome.INFO,
              trace: TraceContext | None = None, span: SpanContext | None = None,
              attributes: SemanticAttributes | None = None,
              payload: dict | None = None, severity: str = "INFO",
              occurred_at: datetime | None = None) -> "RuntimeEventRecord":
        """Construct a record, filtering and scrubbing the payload on the way in.

        The filtering happens *here*, at construction, not at persistence. That
        placement is the guarantee: there is no way to hold a
        ``RuntimeEventRecord`` whose payload has not been through
        :func:`~app.observability.capture.filter_for_capture`, so a future
        caller cannot construct one and reach storage by another route."""
        resolved_attributes = attributes or (span.attributes if span else None) \
            or (trace.attributes if trace else SemanticAttributes())
        return cls(
            event_type=event_type,
            outcome=outcome,
            occurred_at=occurred_at or _now(),
            trace_id=(span.trace_id if span else None) or (trace.trace_id if trace else "")
                     or str(uuid.uuid4()),
            span_id=span.span_id if span else None,
            parent_span_id=span.parent_span_id if span else None,
            request_id=trace.request_id if trace else None,
            attributes=resolved_attributes,
            payload=filter_for_capture(payload),
            severity=severity,
        )

    def as_dict(self) -> dict[str, Any]:
        """The wire/log shape. Consistent keys across every event (FR-021)."""
        return {
            "event_type": self.event_type,
            "outcome": self.outcome.value,
            "severity": self.severity,
            "occurred_at": self.occurred_at.isoformat(),
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "request_id": self.request_id,
            "attributes": self.attributes.as_dict(),
            "payload": self.payload,
        }


def emit(db: Session, record: RuntimeEventRecord) -> bool:
    """Persist one telemetry event. **Never raises.** Returns whether it stored.

    The SAVEPOINT is the important part; see this module's docstring for why
    ``try/except`` alone is not enough.

    On the hot path this is a plain local ``INSERT`` with no lock taken and
    nothing held across model or tool I/O -- the standing M1 deadlock
    discipline (see ``docs/runtime/workers-and-queue.md``). It does not commit:
    the row joins the caller's transaction and lands when the caller commits,
    so telemetry never introduces a second commit point into an execution."""
    try:
        from app.models.runtime import RuntimeEvent

        attributes = record.attributes
        with db.begin_nested():
            db.add(RuntimeEvent(
                organization_id=_as_uuid(attributes.organization_id),
                agent_id=_as_uuid(attributes.agent_id),
                deployment_id=_as_uuid(attributes.deployment_id),
                execution_id=_as_uuid(attributes.execution_id),
                event_type=record.event_type,
                severity=record.severity,
                payload=record.payload,
                request_id=record.request_id,
                correlation_id=record.trace_id,
                span_id=record.span_id,
            ))
        return True
    except Exception:  # noqa: BLE001 -- §9: telemetry never gates execution
        # Logged, not raised, and logged at warning rather than error: a
        # dropped telemetry event is a degradation of observability, not an
        # incident in the execution it describes. An operator needs to see it;
        # a pager does not.
        logger.warning(
            "telemetry: dropped runtime event %r for trace %s",
            record.event_type, record.trace_id, exc_info=True,
        )
        return False


def emit_event(db: Session, *, event_type: str, outcome: Outcome = Outcome.INFO,
               trace: TraceContext | None = None, span: SpanContext | None = None,
               attributes: SemanticAttributes | None = None,
               payload: dict | None = None, severity: str = "INFO") -> bool:
    """Build and emit in one call. Never raises.

    The construction is inside the guard as well as the write: building a
    record scrubs a payload, and a payload pathological enough to break the
    scrubber must not be able to break the execution either."""
    try:
        record = RuntimeEventRecord.build(
            event_type=event_type, outcome=outcome, trace=trace, span=span,
            attributes=attributes, payload=payload, severity=severity,
        )
    except Exception:  # noqa: BLE001 -- §9
        logger.warning("telemetry: could not build runtime event %r", event_type, exc_info=True)
        return False
    return emit(db, record)


def _as_uuid(value: Any) -> uuid.UUID | None:
    """Coerce an attribute back to a UUID for the FK columns, or ``None``.

    Attributes are normalized to strings (they have to be -- they travel to
    logs and exporters), but the columns are real foreign keys. A value that is
    not a UUID returns ``None`` rather than raising: an unparseable id is a
    reason to store an event with a missing link, not a reason to lose the
    event."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None
