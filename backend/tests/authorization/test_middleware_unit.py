"""Phase 4.3.6 unit tests (§37) — context builder immutability, deterministic
pipeline ordering, the decision cache (keys, TTL, invalidation triggers, cache
poisoning), obligation execution and the standard error mapping."""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from fastapi import status

from app.authorization.middleware.cache import DecisionCacheService
from app.authorization.middleware.context import AuthorizationContextBuilder
from app.authorization.middleware.errors import (
    DECISION_EXCEPTIONS,
    ABACDenied,
    ApprovalRequired,
    AuthenticationFailed,
    JustificationRequired,
    MFARequired,
    PermissionDenied,
    PolicyEvaluationFailed,
    ResourceForbidden,
    SessionExpired,
)
from app.authorization.middleware.metrics import PipelineMetricsService
from app.authorization.middleware.obligations import ObligationExecutor
from app.authorization.middleware.pipeline import (
    AuthorizationPipeline,
    DecisionTrace,
    DecisionTraceService,
)


def _ctx(**overrides):
    kwargs = dict(
        identity_id=uuid.uuid4(), identity_kind="USER",
        organization_id=uuid.uuid4(), permission="agent.view",
    )
    kwargs.update(overrides)
    return AuthorizationContextBuilder(db=None).build(**kwargs)


# --------------------------------------------------------------------------- #
# Context (§5, §36) — immutable, spoof-proof
# --------------------------------------------------------------------------- #
def test_context_is_immutable() -> None:
    ctx = _ctx(attributes={"row_count": 10})
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.permission = "agent.delete"  # type: ignore[misc]
    with pytest.raises(TypeError):
        ctx.attributes["row_count"] = 999_999  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.decision_trace = ("FORGED",)  # type: ignore[misc]


def test_context_with_trace_returns_new_object() -> None:
    ctx = _ctx()
    ctx2 = ctx.with_trace("RBAC ✓")
    assert ctx.decision_trace == ()
    assert ctx2.decision_trace == ("RBAC ✓",)
    assert ctx2 is not ctx


def test_builder_strips_subject_attributes() -> None:
    ctx = _ctx(attributes={"identity.roles": ["ROLE_PLATFORM_OWNER"], "row_count": 5})
    assert "identity.roles" not in ctx.attributes
    assert ctx.attributes["row_count"] == 5


def test_builder_generates_request_and_correlation_ids() -> None:
    ctx = _ctx()
    assert ctx.request_id and ctx.correlation_id == ctx.request_id
    ctx2 = _ctx(request_id="req-1", correlation_id="corr-1")
    assert (ctx2.request_id, ctx2.correlation_id) == ("req-1", "corr-1")


# --------------------------------------------------------------------------- #
# Pipeline ordering (§9, §18) — deterministic
# --------------------------------------------------------------------------- #
def test_pipeline_step_order_is_pinned() -> None:
    assert AuthorizationPipeline.STEPS == (
        "AUTHENTICATION", "IDENTITY_CONTEXT", "SESSION_VALIDATION",
        "ORGANIZATION_CONTEXT", "RBAC", "RESOURCE_AUTHORIZATION", "ABAC",
        "OBLIGATIONS", "AUDIT", "CACHE",
    )


def test_trace_rejects_out_of_order_stages() -> None:
    svc = DecisionTraceService()
    svc.record(AuthorizationPipeline.RBAC, "✓")
    with pytest.raises(ValueError, match="order violation"):
        svc.record(AuthorizationPipeline.AUTHENTICATION, "✓")


def test_trace_rejects_unknown_stage() -> None:
    with pytest.raises(ValueError, match="Unknown pipeline stage"):
        DecisionTrace().record("BUSINESS_LOGIC", "✓")


def test_trace_summary_renders_stage_and_status() -> None:
    svc = DecisionTraceService()
    svc.record(AuthorizationPipeline.AUTHENTICATION, "✓")
    svc.record(AuthorizationPipeline.RBAC, "✗", "explicit deny")
    assert svc.trace.summary() == ["AUTHENTICATION ✓", "RBAC ✗"]
    assert svc.trace.as_list()[1]["detail"] == "explicit deny"


# --------------------------------------------------------------------------- #
# Decision cache (§19, §23) — keys, TTL, invalidation, poisoning
# --------------------------------------------------------------------------- #
def _key_parts(**overrides) -> dict:
    parts = dict(
        identity_id=uuid.uuid4(), permission="agent.view",
        resource_type=None, resource_id=None, organization_id=uuid.uuid4(),
        rbac_version=1, abac_generation=1,
    )
    parts.update(overrides)
    return parts


def _payload(decision: str = "ALLOW") -> dict:
    return {"allowed": decision == "ALLOW", "decision": decision, "reason": "r",
            "permission": "agent.view", "events": []}


def test_cache_hit_and_identity_isolation() -> None:
    DecisionCacheService.reset()
    parts = _key_parts()
    DecisionCacheService.put(_payload(), **parts)
    assert DecisionCacheService.get(**parts) is not None
    # Another identity with the identical remaining key never sees the entry
    # (cache poisoning across principals is impossible by construction).
    other = dict(parts, identity_id=uuid.uuid4())
    assert DecisionCacheService.get(**other) is None


def test_cache_rotates_on_rbac_and_abac_version_changes() -> None:
    DecisionCacheService.reset()
    parts = _key_parts()
    DecisionCacheService.put(_payload(), **parts)
    assert DecisionCacheService.get(**dict(parts, rbac_version=2)) is None      # role change
    assert DecisionCacheService.get(**dict(parts, abac_generation=2)) is None   # policy change
    assert DecisionCacheService.get(**parts) is not None


def test_cache_invalidated_on_session_revocation() -> None:
    DecisionCacheService.reset()
    parts = _key_parts()
    DecisionCacheService.put(_payload(), **parts)
    DecisionCacheService.invalidate_identity(parts["identity_id"])
    assert DecisionCacheService.get(**parts) is None


def test_cache_respects_ttl() -> None:
    DecisionCacheService.reset()
    parts = _key_parts()
    old_ttl = DecisionCacheService.ttl_seconds
    try:
        DecisionCacheService.ttl_seconds = -1.0  # already expired on write
        DecisionCacheService.put(_payload(), **parts)
        assert DecisionCacheService.get(**parts) is None
    finally:
        DecisionCacheService.ttl_seconds = old_ttl


def test_cache_never_stores_challenge_decisions() -> None:
    DecisionCacheService.reset()
    for challenge in ("REQUIRE_APPROVAL", "REQUIRE_MFA", "REQUIRE_JUSTIFICATION"):
        parts = _key_parts()
        DecisionCacheService.put(_payload(challenge), **parts)
        assert DecisionCacheService.get(**parts) is None, challenge


def test_cached_payload_cannot_be_tampered_with() -> None:
    DecisionCacheService.reset()
    parts = _key_parts()
    DecisionCacheService.put(_payload("DENY"), **parts)
    stolen = DecisionCacheService.get(**parts)
    stolen["allowed"] = True
    stolen["decision"] = "ALLOW"
    fresh = DecisionCacheService.get(**parts)
    assert fresh["allowed"] is False and fresh["decision"] == "DENY"


def test_cache_metrics_report_hit_ratio() -> None:
    DecisionCacheService.reset()
    parts = _key_parts()
    DecisionCacheService.put(_payload(), **parts)
    DecisionCacheService.get(**parts)
    DecisionCacheService.get(**_key_parts())
    m = DecisionCacheService.metrics()
    assert m["decision_cache_hits"] == 1 and m["decision_cache_misses"] == 1
    assert m["decision_cache_hit_ratio"] == 0.5


# --------------------------------------------------------------------------- #
# Obligations (§16)
# --------------------------------------------------------------------------- #
def test_obligation_outcome_flags() -> None:
    outcome = ObligationExecutor(db=None).execute(
        [
            {"type": "CREATE_APPROVAL", "priority": "CRITICAL",
             "reviewer_role": "ROLE_AI_REVIEWER", "policy_id": "p1"},
            {"type": "REQUIRE_MFA", "policy_id": "p2"},
            {"type": "REQUIRE_JUSTIFICATION", "policy_id": "p3"},
            {"type": "MASK_FIELDS", "fields": ["ssn"], "policy_id": "p4"},
            {"type": "LIMIT_ACTION", "limits": {"maximum_export_rows": 100}, "policy_id": "p5"},
        ],
        organization_id=uuid.uuid4(), identity_id=uuid.uuid4(), action="dataset.export",
    )
    assert outcome.requires_approval and outcome.approval["priority"] == "CRITICAL"
    assert outcome.requires_mfa and outcome.requires_justification
    assert outcome.masked_fields == ("ssn",)
    assert outcome.limits == {"maximum_export_rows": 100}
    assert len(outcome.instructions) == 5


def test_mask_fields_is_recursive_and_non_destructive() -> None:
    payload = {"name": "x", "ssn": "123", "nested": {"ssn": "456", "ok": 1},
               "rows": [{"ssn": "789"}, {"keep": True}]}
    masked = ObligationExecutor.mask_fields(payload, ("ssn",))
    assert masked["ssn"] == "***" and masked["nested"]["ssn"] == "***"
    assert masked["rows"][0]["ssn"] == "***" and masked["rows"][1]["keep"] is True
    assert payload["ssn"] == "123"  # original untouched


def test_apply_limits_clamps_known_parameters() -> None:
    clamped = ObligationExecutor.apply_limits(
        {"row_count": 50_000, "max_tokens": 9_000, "note": "hi"},
        {"maximum_export_rows": 1_000, "limit_tokens": 4_096, "custom_cap": "x"},
    )
    assert clamped["row_count"] == 1_000
    assert clamped["max_tokens"] == 4_096
    assert clamped["note"] == "hi"
    assert clamped["_limits"] == {"custom_cap": "x"}


# --------------------------------------------------------------------------- #
# Standard errors (§25, §26)
# --------------------------------------------------------------------------- #
def test_error_codes_and_statuses() -> None:
    cases = [
        (AuthenticationFailed(), "AUTHENTICATION_FAILED", status.HTTP_401_UNAUTHORIZED),
        (SessionExpired(), "SESSION_EXPIRED", status.HTTP_401_UNAUTHORIZED),
        (PermissionDenied(), "PERMISSION_DENIED", status.HTTP_403_FORBIDDEN),
        (ResourceForbidden(), "RESOURCE_FORBIDDEN", status.HTTP_403_FORBIDDEN),
        (ABACDenied(), "ABAC_DENIED", status.HTTP_403_FORBIDDEN),
        (ApprovalRequired(), "APPROVAL_REQUIRED", status.HTTP_403_FORBIDDEN),
        (MFARequired(), "MFA_REQUIRED", status.HTTP_401_UNAUTHORIZED),
        (JustificationRequired(), "JUSTIFICATION_REQUIRED", status.HTTP_403_FORBIDDEN),
        (PolicyEvaluationFailed(), "ABAC_EVALUATION_FAILED",
         status.HTTP_500_INTERNAL_SERVER_ERROR),
    ]
    for exc, code, http in cases:
        assert exc.code == code and exc.http_status == http, code


def test_decision_exception_map_covers_every_challenge() -> None:
    assert set(DECISION_EXCEPTIONS) == {
        "DENY", "REQUIRE_APPROVAL", "REQUIRE_MFA", "REQUIRE_JUSTIFICATION",
    }


# --------------------------------------------------------------------------- #
# Metrics (§34)
# --------------------------------------------------------------------------- #
def test_pipeline_metrics_counters_and_snapshot() -> None:
    PipelineMetricsService.reset()
    PipelineMetricsService.observe(decision="ALLOW", latency_ms=1.0)
    PipelineMetricsService.observe(decision="DENY", latency_ms=3.0)
    PipelineMetricsService.observe(decision="REQUIRE_APPROVAL", latency_ms=2.0)
    PipelineMetricsService.observe(decision="REQUIRE_MFA", latency_ms=2.0)
    PipelineMetricsService.policy_error()
    snap = PipelineMetricsService.snapshot()
    assert snap["authorization_requests_total"] == 4
    assert snap["authorization_denied_total"] == 1
    assert snap["authorization_approval_required_total"] == 1
    assert snap["authorization_mfa_required_total"] == 1
    assert snap["authorization_policy_errors_total"] == 1
    assert snap["authorization_latency_ms_avg"] == 2.0
    assert "decision_cache_hit_ratio" in snap
