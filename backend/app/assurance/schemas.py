"""Phase 5.9 (M5.9) - assurance request/response schemas.

Note what no response model here carries: there is no ``compliant`` field, no
``status``, no score and no coverage percentage. The absence is deliberate and
is asserted by ``test_ac04`` — a field that does not exist cannot be rendered
as a badge, and the contract is the right place to make that impossible rather
than relying on every view to remember.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EvaluationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    control_id: str
    catalog_version: str
    scope: str
    subject_id: uuid.UUID | None
    #: PASS / FAIL / INSUFFICIENT_EVIDENCE — never a compliance verdict.
    result: str
    reason: str
    #: What the control read, or the absence it found.
    evidence: dict
    evidence_as_of: datetime | None
    stale: bool
    remediation: str | None
    exception_reason: str | None
    exception_at: datetime | None
    evaluated_at: datetime


class TenantEvaluateResponse(BaseModel):
    evaluated: int
    passed: int
    failed: int
    #: Reported as its own count, never folded into failed or passed.
    insufficient_evidence: int
    stale: int


class ExceptionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class EvidenceBundleResponse(BaseModel):
    bundle_id: uuid.UUID
    content_digest: str
    signed: bool
    signature: dict | None
    signing_key_id: str | None
    #: Says in words whether this bundle is tamper-evident. A caller must not
    #: have to infer that from a null signature.
    tamper_evidence: str
    document: dict


__all__ = [
    "EvaluationRead",
    "TenantEvaluateResponse",
    "ExceptionRequest",
    "EvidenceBundleResponse",
]
