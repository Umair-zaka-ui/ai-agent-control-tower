"""Phase 4.6 -- assembled trace -> provider-neutral export records
(M4-4.6-FR-001, FR-004, AC-01, AC-10).

**This module is the seam.** On its left is 4.2's :class:`~app.observability.
assembly.AssembledTrace` -- domain rows walked into a span tree. On its right is
:class:`ExportSpan`, a flat, vendor-neutral record that a sink turns into OTLP.
Nothing here imports ``opentelemetry``: the neutral record is what lets the
buffer, the dispatcher and the tests reason about "a span to export" without a
vendor SDK in scope, and what lets a second sink (a future grpc one, a test
double) consume the same records.

**Metadata only, and re-checked here even though 4.2 already guarantees it.**
The assembler never reads a content column, so an assembled span carries only
identities, timings, statuses and this platform's own templated decision text.
This module still runs the 4.1 scrubber over every attribute value and drops
any attribute whose *name* is sensitive or high-cardinality -- defense in depth,
because the thing crossing the boundary to a third party is exactly the thing
worth checking twice (§10).

**Ids are derived, deterministically.** OTLP wants a 16-byte trace id and an
8-byte span id; 4.2's are UUID5 strings or arbitrary correlation strings. We
hash them (blake2b, digest-sized) so the same execution always exports under the
same OTLP ids -- a trace re-exported after a restart is the same trace to the
collector, which matters for any backend that dedupes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.observability.assembly import AssembledSpan, AssembledTrace
from app.observability.attributes import (
    HIGH_CARDINALITY_ATTRIBUTES,
    SENSITIVE_ATTRIBUTES,
)
from app.observability.scrubbing import scrub

#: OTel span-kind names. Our gate/queue/finalization phases and the execution
#: root are INTERNAL; a model call or external HTTP leg is CLIENT (we called
#: out); nothing here is a SERVER span because the platform is not the OTLP
#: server in these traces.
_KIND_BY_SPAN: dict[str, str] = {
    "model_call": "CLIENT",
    "tool_call": "CLIENT",
    "external_call": "CLIENT",
}

#: Attribute names that may appear on an exported span even though they are
#: high-cardinality: they are *identities of the subject*, exactly what a trace
#: is for (§12 draws the line at *metric labels*, not trace attributes). Listed
#: explicitly so everything else high-cardinality is dropped by default.
_ALLOWED_IDENTITY_ATTRS: frozenset[str] = frozenset({
    "organization_id", "agent_id", "agent_version_id", "deployment_id",
    "execution_id", "tool_id", "worker_id", "environment", "provider", "model",
    "status", "error_class", "error_code", "target_host",
})

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class ExportSpan:
    """One span, flattened and vendor-neutral, ready for a sink to encode."""

    trace_id_hex: str            # 32 hex chars / 16 bytes
    span_id_hex: str             # 16 hex chars / 8 bytes
    parent_span_id_hex: str | None
    name: str
    kind: str                    # INTERNAL | CLIENT
    start_unix_nano: int
    end_unix_nano: int
    status_code: str             # OK | ERROR | UNSET
    status_message: str
    attributes: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "trace_id": self.trace_id_hex,
            "span_id": self.span_id_hex,
            "parent_span_id": self.parent_span_id_hex,
            "name": self.name,
            "kind": self.kind,
            "start_unix_nano": self.start_unix_nano,
            "end_unix_nano": self.end_unix_nano,
            "status_code": self.status_code,
            "status_message": self.status_message,
            "attributes": self.attributes,
        }


@dataclass(frozen=True)
class ExportResource:
    """The OTLP Resource -- what produced these spans. Bounded, non-sensitive."""

    attributes: dict[str, str]

    @classmethod
    def for_platform(cls, *, environment: str | None = None) -> "ExportResource":
        attrs = {"service.name": "ai-agent-control-tower", "service.namespace": "runtime"}
        if environment:
            attrs["deployment.environment"] = str(environment)
        return cls(attributes=attrs)


def _hex_trace_id(raw: str) -> str:
    return hashlib.blake2b(raw.encode("utf-8"), digest_size=16).hexdigest()


def _hex_span_id(raw: str) -> str:
    return hashlib.blake2b(raw.encode("utf-8"), digest_size=8).hexdigest()


def _unix_nano(value: datetime | None, fallback: datetime | None = None) -> int:
    dt = value or fallback or _EPOCH
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000_000)


def _status(span: AssembledSpan) -> tuple[str, str]:
    """Map a domain status onto OTLP's three-value status.

    Error codes and a handful of terminal domain statuses are ERROR; a clean
    terminal status is OK; anything still open or unknown is UNSET. The message
    is this platform's own ``error_code`` -- a bounded token, never free text
    from a model or a user."""
    if span.error_code:
        return "ERROR", str(span.error_code)
    status = (span.status or "").upper()
    if status in {"FAILED", "ERROR", "DENIED", "BLOCKED", "TIMEOUT", "TIMED_OUT", "CANCELLED"}:
        return "ERROR", status
    if status in {"SUCCEEDED", "COMPLETED", "ALLOWED", "PASSED", "CLAIMED", "OK"}:
        return "OK", ""
    return "UNSET", ""


def _clean_attributes(raw: dict[str, str]) -> dict[str, str]:
    """Scrub values, drop sensitive or unlisted-high-cardinality names.

    The assembler produces clean metadata, but this is the last code that runs
    before the data leaves the platform, so it re-checks rather than trusts."""
    scrubbed = scrub(dict(raw)) or {}
    out: dict[str, str] = {}
    for key, value in scrubbed.items():
        name = str(key)
        if name in SENSITIVE_ATTRIBUTES:
            continue
        if name in HIGH_CARDINALITY_ATTRIBUTES and name not in _ALLOWED_IDENTITY_ATTRS:
            continue
        if value is None:
            continue
        out[name] = str(value)
    return out


def span_to_export(trace: AssembledTrace, span: AssembledSpan) -> ExportSpan:
    trace_hex = _hex_trace_id(trace.trace_id)
    start = span.started_at
    end = span.ended_at or span.started_at
    code, message = _status(span)
    attrs = _clean_attributes({**trace.attributes, **span.attributes})
    attrs.setdefault("act.span.kind", span.kind.value)
    if span.source_table:
        attrs["act.source.table"] = span.source_table
        if span.source_id:
            attrs["act.source.id"] = span.source_id
    if span.duration_ms is not None:
        attrs["act.duration_ms"] = str(span.duration_ms)
    return ExportSpan(
        trace_id_hex=trace_hex,
        span_id_hex=_hex_span_id(span.span_id),
        parent_span_id_hex=_hex_span_id(span.parent_span_id) if span.parent_span_id else None,
        name=span.name,
        kind=_KIND_BY_SPAN.get(span.kind.value, "INTERNAL"),
        start_unix_nano=_unix_nano(start),
        end_unix_nano=_unix_nano(end, start),
        status_code=code,
        status_message=message,
        attributes=attrs,
    )


def trace_to_export(trace: AssembledTrace) -> list[ExportSpan]:
    """Every span of one assembled trace, as neutral export records."""
    return [span_to_export(trace, span) for span in trace.spans]
