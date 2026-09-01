"""Phase 4.8 -- the four capture modes and what each admits.

These are the *policy* modes (M4-4.8-FR-001). They are related to, but not the
same vocabulary as, ``app.observability.capture.CaptureMode`` (4.1): 4.1 named
``METADATA_ONLY`` / ``CONTENT`` / ``SENSITIVE_CONTENT`` as a declaration of the
shape this phase would build. 4.8 makes the real distinction operators need --
whether content is *redacted* or *full* -- and adds ``DISABLED``. The mapping
between the two is stated in :func:`observability_mode`.

**No mode admits chain-of-thought.** That is a §7 structural floor beneath all
four, enforced by :func:`app.observability.capture.strip_reasoning` running
before any of this. **No mode admits an un-scrubbed secret.** ``FULL_CONTENT``
is "full business content", never "full secrets" (§14): the 4.1 scrubber runs
in every content-capturing mode.
"""

from __future__ import annotations

from enum import Enum


class CaptureMode(str, Enum):
    """What a scope captures (M4-4.8-FR-001).

    Ordered from least to most capture. The **default** everywhere -- and the
    only resolution for a production/sensitive scope with no explicit policy --
    is :attr:`METADATA_ONLY`. A misconfiguration resolves to :attr:`METADATA_ONLY`
    or :attr:`DISABLED`, never to a content mode (M4-4.8-FR-002)."""

    #: Nothing at all -- no content, and no derived telemetry event either. The
    #: strictest boundary: a DISABLED scope produces no telemetry-plane record.
    #: The domain rows still exist (an execution is still an execution); the
    #: telemetry plane simply records nothing about it.
    DISABLED = "DISABLED"

    #: Metadata only -- identities, timings, counts, statuses, costs, outcomes.
    #: No prompt, no tool argument, no tool result, no model output. The 4.1
    #: baseline, unchanged, and the platform default.
    METADATA_ONLY = "METADATA_ONLY"

    #: Metadata plus content, with classification-based field redaction applied
    #: **before persistence** and secrets scrubbed. A regulated tenant that
    #: needs to debug flows without persisting the payloads verbatim.
    REDACTED_CONTENT = "REDACTED_CONTENT"

    #: Metadata plus full business content, secrets **still scrubbed**. The most
    #: permissive mode; a deliberate, permissioned, audited policy choice, never
    #: a default.
    FULL_CONTENT = "FULL_CONTENT"


#: Declaration order is least-to-most capture; used nowhere as a fallback, only
#: for display and validation.
CAPTURE_MODES: tuple[str, ...] = tuple(m.value for m in CaptureMode)

#: The modes that persist any content at all. ``METADATA_ONLY`` and ``DISABLED``
#: are absent -- that absence is the "captures no content" guarantee.
CONTENT_MODES: frozenset[str] = frozenset(
    {CaptureMode.REDACTED_CONTENT.value, CaptureMode.FULL_CONTENT.value}
)

#: The conservative resolution: what a scope gets when nothing explicit applies
#: and the scope is production or sensitively classified.
CONSERVATIVE_DEFAULT = CaptureMode.METADATA_ONLY

#: The conservative resolution for a scope that is neither production nor
#: sensitive and has no explicit policy. Still METADATA_ONLY -- content is
#: always opt-in, everywhere (M4-4.8-FR-002).
PLATFORM_DEFAULT = CaptureMode.METADATA_ONLY


def permits_content(mode: str | CaptureMode) -> bool:
    """True if ``mode`` persists content (redacted or full)."""
    value = mode.value if isinstance(mode, CaptureMode) else str(mode)
    return value in CONTENT_MODES


def is_disabled(mode: str | CaptureMode) -> bool:
    value = mode.value if isinstance(mode, CaptureMode) else str(mode)
    return value == CaptureMode.DISABLED.value


def coerce(mode: str | CaptureMode | None) -> CaptureMode:
    """Parse a stored/incoming mode string. An unrecognised value fails toward
    the conservative default rather than raising on a read path (M4-4.8-FR-002)."""
    if isinstance(mode, CaptureMode):
        return mode
    try:
        return CaptureMode(str(mode))
    except ValueError:
        return CONSERVATIVE_DEFAULT


def observability_mode(mode: CaptureMode):
    """Map a 4.8 policy mode to the 4.1 ``observability.capture.CaptureMode`` the
    scrubbing/strip pipeline understands.

    ``DISABLED`` and ``METADATA_ONLY`` both map to 4.1's ``METADATA_ONLY``
    (4.1's filter keeps only metadata); ``REDACTED_CONTENT`` and
    ``FULL_CONTENT`` both map to 4.1's ``CONTENT`` (4.1's filter keeps content
    fields, and this phase's :mod:`.redaction` then does the mode-specific
    masking on top)."""
    from app.observability.capture import CaptureMode as ObsMode

    if mode in (CaptureMode.DISABLED, CaptureMode.METADATA_ONLY):
        return ObsMode.METADATA_ONLY
    return ObsMode.CONTENT
