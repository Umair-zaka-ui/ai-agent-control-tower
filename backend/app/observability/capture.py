"""Phase 4.1 -- capture classification and the METADATA_ONLY baseline
(ACT-SRS-M4 §7, §4.8; the approved conservative-default ruling).

**The baseline is METADATA_ONLY and it is the default everywhere.** Telemetry
records *that* a model was called, by whom, for how long, at what cost, with
what outcome. It does not record the prompt, the tool arguments, the tool
result, or the model's output. Those are :data:`DataClass.CONTENT`, and this
phase captures none of it.

That is a deliberate choice about what a conservative default costs. A platform
that captured content by default and offered a switch to turn it off would be
correct exactly until the first tenant forgot to flip it. A platform that
captures nothing by default is less immediately useful and cannot leak what it
never held. 4.8 builds the policy system that lets a tenant opt in deliberately,
per environment, with the retention and access controls that decision requires.

**Chain-of-thought is different, and the difference is the point.** Private
model reasoning is not "content that is off by default". It is
:data:`DataClass.NEVER`, and there is no mode -- present or future -- that
enables it. §7 is a structural exclusion, so it is expressed here as a class
that :func:`is_capturable` refuses unconditionally rather than as a mode that
happens not to be set. A policy toggle can be flipped by a future phase in a
hurry; a branch that returns ``False`` for every mode has to be deleted on
purpose, in a diff someone reviews.
"""

from __future__ import annotations

from enum import Enum


class DataClass(str, Enum):
    """What kind of thing a value is, for capture purposes (M4-4.1-FR-034).

    Four classes, ordered by how freely they may be captured. Representing the
    distinction now -- while only ``METADATA`` is ever captured -- is what lets
    4.8 build a real policy on top without first having to invent the
    vocabulary and retrofit it to existing call sites."""

    #: Identifiers, timings, counts, statuses, costs, model/provider names.
    #: Never a payload. This is everything 4.1 captures.
    METADATA = "METADATA"

    #: Prompts, model output, tool arguments, tool results. Off by default;
    #: 4.8 may allow it per environment, and the scrubber runs on it first.
    CONTENT = "CONTENT"

    #: Content that is additionally regulated or personal -- an end user's
    #: message, a document body pulled through a connector. Strictly narrower
    #: than CONTENT: enabling CONTENT does not enable this.
    SENSITIVE_CONTENT = "SENSITIVE_CONTENT"

    #: Credentials of any kind. Never captured, in any mode, ever -- and the
    #: scrubber removes them from anything that *is* captured, so this class
    #: exists to be named and refused rather than to be handled.
    SECRET = "SECRET"

    #: Private model reasoning / chain-of-thought (§7). Structurally excluded:
    #: no mode enables it. Not a policy, a property.
    NEVER = "NEVER"


class CaptureMode(str, Enum):
    """How much a given scope captures (M4-4.1-FR-032).

    ``METADATA_ONLY`` is the platform baseline and the only mode 4.1 activates.
    The other two are *declared*, not implemented: they name the shape 4.8 will
    build so that the vocabulary does not change under later phases, and
    :func:`is_capturable` already answers correctly for them."""

    #: The conservative default. Metadata only; no payload of any kind.
    METADATA_ONLY = "METADATA_ONLY"

    #: Metadata plus scrubbed prompts/outputs/tool payloads. Requires the 4.8
    #: policy system (retention, access control, per-environment opt-in) before
    #: it may be selected; nothing in 4.1 sets it.
    CONTENT = "CONTENT"

    #: Metadata plus content plus regulated/personal content. Requires
    #: everything CONTENT requires, plus a tenant's explicit legal decision.
    SENSITIVE_CONTENT = "SENSITIVE_CONTENT"


#: The platform baseline (§4.8 conservative default). Read through
#: :func:`current_mode` rather than referenced directly, so the one place that
#: resolves the effective mode stays the one place.
DEFAULT_CAPTURE_MODE = CaptureMode.METADATA_ONLY

#: Which data classes each mode admits. ``NEVER`` and ``SECRET`` appear in no
#: mode's set -- that absence *is* the §7 guarantee, and the test asserts it
#: against every member of ``CaptureMode`` rather than against a list, so a
#: mode added later cannot quietly acquire them.
_ALLOWED: dict[CaptureMode, frozenset[DataClass]] = {
    CaptureMode.METADATA_ONLY: frozenset({DataClass.METADATA}),
    CaptureMode.CONTENT: frozenset({DataClass.METADATA, DataClass.CONTENT}),
    CaptureMode.SENSITIVE_CONTENT: frozenset({
        DataClass.METADATA, DataClass.CONTENT, DataClass.SENSITIVE_CONTENT,
    }),
}

#: Field names that carry private model reasoning. Recognized by name because
#: that is how providers expose it -- Anthropic's ``thinking`` blocks,
#: OpenAI's ``reasoning``/``reasoning_content``, the generic
#: ``chain_of_thought``. Matching is normalized (see :func:`is_reasoning_field`).
REASONING_FIELDS: frozenset[str] = frozenset({
    "reasoning", "reasoning_content", "reasoning_details", "reasoning_tokens_detail",
    "chain_of_thought", "chainofthought", "cot", "thinking", "thinking_blocks",
    "thought", "thoughts", "internal_monologue", "scratchpad", "deliberation",
    "hidden_reasoning", "analysis",
})


def current_mode() -> CaptureMode:
    """The effective capture mode.

    One resolution point, so "what does this platform capture?" has one answer
    and one place to change it. 4.1 always answers ``METADATA_ONLY``: the
    per-environment override is 4.8's job, and wiring a settings key for it now
    would create a switch with nothing behind it -- a way to *believe* content
    capture is configured while no code path honours it.

    Deliberately a function, not a constant, so that 4.8 can make it consult
    ``Environment.policy`` without every caller changing."""
    return DEFAULT_CAPTURE_MODE


def is_reasoning_field(name: str) -> bool:
    """True if ``name`` is a private-reasoning field (§7).

    Normalized the same way the scrubber normalizes keys, so ``chain-of-
    thought``, ``chain_of_thought`` and ``ChainOfThought`` are one thing."""
    normalized = "".join(ch for ch in str(name).lower() if ch.isalnum())
    return any(
        normalized == "".join(c for c in field.lower() if c.isalnum())
        for field in REASONING_FIELDS
    )


def classify_field(name: str) -> DataClass:
    """The data class a field name implies.

    Reasoning first, unconditionally -- a field called ``reasoning_content``
    must classify as ``NEVER`` and not as ``CONTENT``, and checking content
    first would get that backwards."""
    if is_reasoning_field(name):
        return DataClass.NEVER
    from app.observability.scrubbing import classify_key
    if classify_key(name) is not None:
        return DataClass.SECRET
    normalized = "".join(ch for ch in str(name).lower() if ch.isalnum())
    if normalized in _CONTENT_FIELDS:
        return DataClass.CONTENT
    return DataClass.METADATA


_CONTENT_FIELDS: frozenset[str] = frozenset({
    "prompt", "prompttext", "input", "inputpayload", "output", "outputpayload",
    "content", "completion", "message", "messages", "toolargs", "toolarguments",
    "arguments", "inputsummary", "outputsummary", "requestbody", "responsebody",
    "text", "body",
})


def is_capturable(data_class: DataClass, mode: CaptureMode | None = None) -> bool:
    """Whether ``data_class`` may be captured under ``mode``.

    ``NEVER`` and ``SECRET`` return ``False`` for every mode, including modes
    that do not exist yet: they are absent from every entry in ``_ALLOWED``, so
    the refusal is a property of the table rather than a special case someone
    could forget to carry forward."""
    effective = mode or current_mode()
    return data_class in _ALLOWED.get(effective, frozenset())


def strip_reasoning(value: object, *, _depth: int = 0) -> object:
    """Remove every private-reasoning field from a structure (§7).

    Applied to anything on its way into the telemetry plane, *before* the
    scrubber and independently of capture mode. A provider that starts
    returning a ``thinking`` block in its usage metadata must not be able to
    smuggle reasoning into telemetry just because the surrounding object was
    classified as metadata.

    The field is dropped entirely rather than redacted. A ``REDACTED`` marker
    would record that reasoning existed and how many turns had it, which is
    still a claim about the model's private state; absence records nothing."""
    if _depth >= 12:
        return None
    if isinstance(value, dict):
        return {
            key: strip_reasoning(item, _depth=_depth + 1)
            for key, item in value.items()
            if not (isinstance(key, str) and is_reasoning_field(key))
        }
    if isinstance(value, (list, tuple)):
        stripped = [strip_reasoning(item, _depth=_depth + 1) for item in value]
        return tuple(stripped) if isinstance(value, tuple) else stripped
    return value


def filter_for_capture(payload: dict | None, mode: CaptureMode | None = None) -> dict | None:
    """Reduce ``payload`` to what ``mode`` permits, then scrub what remains.

    The order matters and is not interchangeable:

    1. **Strip reasoning** -- unconditional, mode-independent (§7).
    2. **Drop non-capturable classes** -- under the baseline this removes every
       content field, so prompts and tool payloads never reach step 3 at all.
    3. **Scrub** -- the surviving metadata still goes through the scrubber,
       because a metadata field can carry a credential (an error message
       quoting a connection string, a header name in a debug blob).

    Step 3 is not redundant with step 2. Step 2 asks "is this the kind of thing
    we capture?"; step 3 asks "does this specific value contain a secret?". A
    field can pass the first and fail the second, which is exactly the case
    that leaks if only one of them runs."""
    if payload is None:
        return None
    from app.observability.scrubbing import scrub

    effective = mode or current_mode()
    stripped = strip_reasoning(payload)
    if not isinstance(stripped, dict):  # pragma: no cover - defensive
        return None

    kept = {
        key: item
        for key, item in stripped.items()
        if is_capturable(classify_field(str(key)), effective)
    }
    return scrub(kept)
