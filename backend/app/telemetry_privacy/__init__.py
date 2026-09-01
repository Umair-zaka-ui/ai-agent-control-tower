"""Phase 4.8 -- telemetry privacy, retention & access governance.

This package turns the telemetry plane into a governed, security-sensitive data
system (ACT-SRS-M4 §3.5, §4.8):

- **Capture policy** (:mod:`.policy`) -- per tenant / environment / agent /
  data-classification, a resolved mode: ``METADATA_ONLY`` / ``REDACTED_CONTENT``
  / ``FULL_CONTENT`` / ``DISABLED``. Production and sensitive scopes default
  conservatively; a misconfiguration fails toward *less* capture.
- **Content capture & redaction** (:mod:`.content`, :mod:`.redaction`) -- when a
  policy permits content, secrets are scrubbed (§14, the 4.1 scrubber) and
  fields are redacted per classification **before** anything is persisted to
  the governed :class:`~app.models.runtime.TraceContent` store. Chain-of-thought
  is never captured, in any mode (§7).
- **Access governance** -- reading trace content requires
  ``runtime.trace.content.view``, a distinct permission strictly stronger than
  the 4.2 metadata view; it is not implied by executing an agent or by seeing
  metadata, and every content view is audited (``RUNTIME_TRACE_CONTENT_VIEWED``).
- **Retention per class** (:mod:`.retention`) -- metrics aggregates, trace
  metadata, trace content, alert history each expire on their own schedule
  while domain truth and financial/audit evidence persist.

Nothing here is on the enforcement path: no capture or retention operation ever
stops or alters an execution (§9).
"""

from app.telemetry_privacy.content import TraceContentService
from app.telemetry_privacy.modes import (
    CAPTURE_MODES,
    CONTENT_MODES,
    CaptureMode,
    permits_content,
)
from app.telemetry_privacy.policy import (
    CapturePolicyError,
    CapturePolicyService,
    EffectiveMode,
    resolve_capture_mode,
)
from app.telemetry_privacy.retention import (
    RETENTION_FLOORS,
    TELEMETRY_CLASSES,
    RetentionPolicyError,
    RetentionPolicyService,
    RetentionSweeper,
)

__all__ = [
    "CAPTURE_MODES",
    "CONTENT_MODES",
    "CaptureMode",
    "permits_content",
    "CapturePolicyError",
    "CapturePolicyService",
    "EffectiveMode",
    "resolve_capture_mode",
    "TraceContentService",
    "RETENTION_FLOORS",
    "TELEMETRY_CLASSES",
    "RetentionPolicyError",
    "RetentionPolicyService",
    "RetentionSweeper",
]
