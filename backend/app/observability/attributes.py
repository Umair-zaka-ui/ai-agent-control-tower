"""Phase 4.1 -- stable semantic attributes and bounded metric cardinality
(ACT-SRS-M4 §12).

**The distinction this module exists to enforce.** There are two different
things telemetry does with an identifier, and conflating them is how an
observability stack falls over:

*Trace attributes* answer "which execution was this?". They are allowed, and
required, to be high-cardinality -- an ``execution_id`` that were not unique
per execution would be useless. They are attached to a trace or a row, both of
which are stored once per occurrence, so their cost is linear in traffic.

*Metric labels* answer "how many, grouped by what?". A time-series database
allocates one series per distinct combination of label values. Putting an
``execution_id`` on a counter does not produce a counter -- it produces one
series per execution, forever, and takes the metrics backend down with it. The
cost is not linear in traffic; it is the product of every label's cardinality.

So: **every identity is a legal trace attribute; only the bounded set is a
legal metric label.** :data:`METRIC_DIMENSIONS` is that set, and
:func:`metric_labels` is the only supported way to build a label dict, so the
rule is enforced structurally rather than remembered.

There is no metrics *backend* in this phase -- exporters are 4.6 and SLOs are
4.7. The allowlist lands now anyway, because the cheapest moment to make a
mistake impossible is before anything can make it.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------- #
# The stable attribute names (M4-4.1-FR-010)
# --------------------------------------------------------------------------- #
# One spelling, defined once. Every later M4 phase reads these constants rather
# than typing the string, so renaming an attribute is a change in one file
# instead of an archaeology exercise across six.
ATTR_ORGANIZATION_ID = "organization_id"
ATTR_AGENT_ID = "agent_id"
ATTR_AGENT_VERSION_ID = "agent_version_id"
ATTR_DEPLOYMENT_ID = "deployment_id"
ATTR_EXECUTION_ID = "execution_id"
ATTR_ENVIRONMENT = "environment"
ATTR_PROVIDER = "provider"
ATTR_MODEL = "model"
ATTR_TOOL_ID = "tool_id"
ATTR_WORKER_ID = "worker_id"
ATTR_STATUS = "status"
ATTR_ERROR_CLASS = "error_class"
ATTR_MODEL_CATEGORY = "model_category"

SEMANTIC_ATTRIBUTES: frozenset[str] = frozenset({
    ATTR_ORGANIZATION_ID, ATTR_AGENT_ID, ATTR_AGENT_VERSION_ID, ATTR_DEPLOYMENT_ID,
    ATTR_EXECUTION_ID, ATTR_ENVIRONMENT, ATTR_PROVIDER, ATTR_MODEL, ATTR_TOOL_ID,
    ATTR_WORKER_ID, ATTR_STATUS, ATTR_ERROR_CLASS, ATTR_MODEL_CATEGORY,
})

# --------------------------------------------------------------------------- #
# The bounded set -- what MAY be a metric label (M4-4.1-FR-011)
# --------------------------------------------------------------------------- #
# Each of these takes values from a small, closed vocabulary that does not grow
# with traffic. ``environment`` is per-tenant configuration (a handful);
# ``status`` and ``error_class`` are enumerations this codebase already owns;
# ``provider`` is the registry's list; ``model_category`` is deliberately the
# *category*, never the raw model string, because a raw model name grows every
# time a vendor ships one and a caller may pass an arbitrary string.
METRIC_DIMENSIONS: frozenset[str] = frozenset({
    ATTR_ENVIRONMENT,
    ATTR_STATUS,
    ATTR_PROVIDER,
    ATTR_MODEL_CATEGORY,
    ATTR_ERROR_CLASS,
})

# Identities that are legal on a trace and illegal on a metric. Listed
# explicitly, and separately from "anything not in METRIC_DIMENSIONS", so the
# error message can say *why* -- an engineer who is told "execution_id is
# high-cardinality" fixes the call, while one told "not allowed" files a ticket
# asking for it to be allowed.
HIGH_CARDINALITY_ATTRIBUTES: frozenset[str] = frozenset({
    ATTR_ORGANIZATION_ID, ATTR_AGENT_ID, ATTR_AGENT_VERSION_ID, ATTR_DEPLOYMENT_ID,
    ATTR_EXECUTION_ID, ATTR_TOOL_ID, ATTR_WORKER_ID, ATTR_MODEL,
    "correlation_id", "trace_id", "span_id", "request_id", "parent_span_id",
    "routing_key", "idempotency_key", "occurrence_key",
})

# Names that carry a person or a payload rather than an identity. These are not
# merely unbounded, they are *sensitive* (§12 forbids them as labels outright),
# and they must never reach a metrics backend even if someone decides the
# cardinality is acceptable.
SENSITIVE_ATTRIBUTES: frozenset[str] = frozenset({
    "email", "email_address", "username", "user_name", "full_name", "display_name",
    "ip_address", "user_agent", "phone", "prompt", "prompt_text", "input", "input_payload",
    "output", "output_payload", "content", "message", "messages", "tool_args",
    "tool_arguments", "arguments", "completion", "response_body", "request_body",
    "reasoning", "chain_of_thought", "thinking",
})


class MetricCardinalityError(ValueError):
    """Raised when a label outside :data:`METRIC_DIMENSIONS` is offered.

    A ``ValueError`` rather than this codebase's ``IdentityError``: this is a
    programming mistake caught at the call site, not a runtime condition a
    tenant can trigger, and it must never be mapped to an HTTP error code."""


def is_metric_eligible(name: str) -> bool:
    """True if ``name`` may be used as a metric label."""
    return name in METRIC_DIMENSIONS


def metric_labels(**labels: Any) -> dict[str, str]:
    """Build a metric label dict, rejecting anything outside the bounded set.

    This is the *only* supported way to produce labels. It raises rather than
    dropping the offending label, because silently discarding a dimension gives
    a metric that looks right and aggregates wrong -- the worst possible
    failure mode for a number someone will page on.

    ``None`` values are dropped: an absent dimension is genuinely absent (a
    tool call has no provider), and "None" is not a useful series."""
    out: dict[str, str] = {}
    for name, value in labels.items():
        if name in SENSITIVE_ATTRIBUTES:
            raise MetricCardinalityError(
                f"{name!r} is a sensitive attribute and can never be a metric label "
                f"(ACT-SRS-M4 §12). It is not permitted on a metric in any form."
            )
        if name in HIGH_CARDINALITY_ATTRIBUTES:
            raise MetricCardinalityError(
                f"{name!r} is a high-cardinality identity: it belongs on a trace or a "
                f"domain row, never on a metric label (ACT-SRS-M4 §12). One series per "
                f"distinct value would be created. Allowed labels: "
                f"{sorted(METRIC_DIMENSIONS)}."
            )
        if not is_metric_eligible(name):
            raise MetricCardinalityError(
                f"{name!r} is not a declared metric dimension. Allowed labels: "
                f"{sorted(METRIC_DIMENSIONS)}. If this dimension is genuinely bounded, "
                f"add it to METRIC_DIMENSIONS deliberately rather than at the call site."
            )
        if value is None:
            continue
        out[name] = str(value)
    return out


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


@dataclass(frozen=True)
class SemanticAttributes:
    """The stable attribute set for one telemetry subject (M4-4.1-FR-010).

    Frozen, because an attribute set describes a subject at a moment; mutating
    one after it has been attached to a span would silently rewrite history.

    Every field is optional. A deployment-level event has no ``execution_id``;
    a tool span has no ``provider``. Encoding that as ``None`` rather than as
    a required-everywhere field is what keeps one attribute vocabulary usable
    across every span kind instead of needing one per kind."""

    organization_id: str | None = None
    agent_id: str | None = None
    agent_version_id: str | None = None
    deployment_id: str | None = None
    execution_id: str | None = None
    environment: str | None = None
    provider: str | None = None
    model: str | None = None
    tool_id: str | None = None
    worker_id: str | None = None
    status: str | None = None
    error_class: str | None = None

    @classmethod
    def build(cls, **values: Any) -> "SemanticAttributes":
        """Construct from loosely-typed values (UUIDs, ints, ORM ids).

        Unknown keys are ignored rather than raising. A caller assembling
        attributes from a domain row should not have to filter the row first,
        and a stricter contract here would push exactly that boilerplate into
        every call site."""
        known = {f: _str_or_none(values.get(f)) for f in cls.__dataclass_fields__}
        return cls(**known)

    def as_dict(self) -> dict[str, str]:
        """The non-null attributes, for attaching to a span or an event."""
        return {
            name: value
            for name, value in self.__dict__.items()
            if value is not None
        }

    @property
    def model_category(self) -> str | None:
        """The bounded stand-in for ``model`` (M4-4.1-FR-011).

        A raw model string is unbounded -- vendors ship new ones constantly and
        a caller may pass anything -- so the metric dimension is the vendor
        family, derived by taking the segment before the first separator.
        ``gpt-4o-mini`` and ``gpt-4.1`` both become ``gpt``; ``llama3.2:3b``
        becomes ``llama3``. Coarse on purpose: a dimension precise enough to be
        interesting is usually precise enough to be unbounded."""
        if not self.model:
            return None
        head = re.split(r"[-:/@]", self.model, maxsplit=1)[0]
        return head.lower() or None

    def metric_labels(self) -> dict[str, str]:
        """The subset of this attribute set that may legally label a metric.

        Note what is *not* here: no organization, agent, version, deployment,
        execution, tool or worker id, and not the raw model. Those are on the
        trace. This is the §12 rule expressed as code rather than as a comment
        -- calling this can never produce an unbounded label set."""
        return metric_labels(
            environment=self.environment,
            status=self.status,
            provider=self.provider,
            model_category=self.model_category,
            error_class=self.error_class,
        )
