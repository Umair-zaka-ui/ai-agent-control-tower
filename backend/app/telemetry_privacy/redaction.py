"""Phase 4.8 -- classification redaction, on top of the 4.1 secret scrubber
(M4-4.8-FR-011..013, §14, §7).

The pipeline, in order, and not interchangeable:

1. :func:`app.observability.capture.strip_reasoning` -- remove every
   chain-of-thought field. Unconditional, mode-independent (§7). No mode
   enables reasoning capture; this is the structural floor.
2. :func:`app.observability.scrubbing.scrub` -- remove every secret class
   (§14). Runs in **every** content-capturing mode, ``FULL_CONTENT`` included:
   full content is full business content, never full secrets.
3. **Classification redaction** (this module) -- only for ``REDACTED_CONTENT``:
   mask the value of every field whose name implies a sensitive payload, and
   truncate long free text, so the shape of a flow is visible without the
   payload being persisted verbatim.

All three run **before** anything is written to
:class:`~app.models.runtime.TraceContent`. Redaction is a property of the write
path, never of the display layer (§14).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.observability.capture import strip_reasoning
from app.observability.scrubbing import contains_secret, normalize_key, scrub

#: The literal a classification-redacted value is replaced with. Distinct from
#: the scrubber's ``***REDACTED***`` so an auditor can tell a *secret* removal
#: apart from a *classification* redaction.
MASKED = "***MASKED***"

#: Field names whose *value* is a sensitive payload under REDACTED_CONTENT.
#: Names, normalised the way the scrubber normalises keys. Recognising by name
#: is deliberate: it is how prompts, tool arguments and results are labelled
#: everywhere in this codebase.
_REDACT_FIELDS: frozenset[str] = frozenset({
    "prompt", "prompttext", "input", "inputpayload", "inputsummary",
    "output", "outputpayload", "outputsummary", "completion", "content",
    "message", "messages", "text", "body", "toolargs", "toolarguments",
    "arguments", "requestbody", "responsebody", "result", "response",
    "document", "documentbody", "attachment", "email", "phone", "address",
    "ssn", "dob", "name", "firstname", "lastname", "fullname",
})

#: Under REDACTED_CONTENT, free text longer than this is truncated (with a
#: marker) rather than persisted whole -- enough to recognise a flow, not
#: enough to be the payload.
_MAX_TEXT = 120


@dataclass(frozen=True)
class RedactionResult:
    body: Any
    redacted: bool
    secret_scrubbed: bool


def _redact_classified(value: Any, *, _depth: int = 0) -> tuple[Any, bool]:
    """Mask sensitive-named fields and truncate long text. Returns
    ``(value, any_redaction_happened)``."""
    if _depth >= 12:
        return MASKED, True
    changed = False
    if isinstance(value, dict):
        out: dict = {}
        for key, item in value.items():
            if isinstance(key, str) and normalize_key(key) in _REDACT_FIELDS:
                out[key] = MASKED
                changed = True
            else:
                sub, sub_changed = _redact_classified(item, _depth=_depth + 1)
                out[key] = sub
                changed = changed or sub_changed
        return out, changed
    if isinstance(value, (list, tuple)):
        items = []
        for item in value:
            sub, sub_changed = _redact_classified(item, _depth=_depth + 1)
            items.append(sub)
            changed = changed or sub_changed
        return (tuple(items) if isinstance(value, tuple) else items), changed
    if isinstance(value, str) and len(value) > _MAX_TEXT:
        return value[:_MAX_TEXT] + f"...[+{len(value) - _MAX_TEXT} chars redacted]", True
    return value, changed


def redact_for_capture(value: Any, *, mode: str, classification: str | None = None) -> RedactionResult:
    """Run the full pipeline for a content-capturing ``mode``.

    ``mode`` is a 4.8 capture-mode string; only ``REDACTED_CONTENT`` and
    ``FULL_CONTENT`` should reach here (callers gate on
    :func:`app.telemetry_privacy.modes.permits_content`).

    - ``FULL_CONTENT``: strip reasoning, scrub secrets. No classification
      masking.
    - ``REDACTED_CONTENT``: strip reasoning, scrub secrets, then mask
      sensitive-named fields and truncate long text.
    """
    stripped = strip_reasoning(value)
    had_secret = contains_secret(stripped)
    scrubbed = scrub(stripped)

    if mode == "REDACTED_CONTENT":
        body, redacted = _redact_classified(scrubbed)
    else:  # FULL_CONTENT
        body, redacted = scrubbed, False

    return RedactionResult(body=body, redacted=redacted, secret_scrubbed=had_secret)
