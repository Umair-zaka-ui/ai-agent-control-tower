"""Pipeline metrics (Phase 4.3.6 §34).

In-process counters mirroring the ABAC metrics style; exposed through
``GET /api/v1/authorization/middleware/metrics``. The snapshot merges the
decision-cache metrics so operators see hit ratios in one place.
"""

from __future__ import annotations


class PipelineMetricsService:
    counters: dict[str, int] = {
        "authorization_requests_total": 0,
        "authorization_denied_total": 0,
        "authorization_approval_required_total": 0,
        "authorization_mfa_required_total": 0,
        "authorization_policy_errors_total": 0,
        "authorization_pipeline_errors_total": 0,
    }
    latencies_ms: list[float] = []

    @classmethod
    def observe(cls, *, decision: str, latency_ms: float, error: bool = False) -> None:
        cls.counters["authorization_requests_total"] += 1
        if decision == "DENY":
            cls.counters["authorization_denied_total"] += 1
        elif decision == "REQUIRE_APPROVAL":
            cls.counters["authorization_approval_required_total"] += 1
        elif decision == "REQUIRE_MFA":
            cls.counters["authorization_mfa_required_total"] += 1
        if error:
            cls.counters["authorization_pipeline_errors_total"] += 1
        cls.latencies_ms.append(latency_ms)
        if len(cls.latencies_ms) > 1000:
            del cls.latencies_ms[: len(cls.latencies_ms) - 1000]

    @classmethod
    def policy_error(cls) -> None:
        cls.counters["authorization_policy_errors_total"] += 1

    @classmethod
    def snapshot(cls) -> dict:
        from app.authorization.middleware.cache import DecisionCacheService

        lat = sorted(cls.latencies_ms)
        return {
            **cls.counters,
            "authorization_latency_ms_avg": round(sum(lat) / len(lat), 3) if lat else 0.0,
            "authorization_latency_ms_p95": round(lat[int(len(lat) * 0.95) - 1], 3)
            if len(lat) >= 20 else (round(lat[-1], 3) if lat else 0.0),
            **DecisionCacheService.metrics(),
        }

    @classmethod
    def reset(cls) -> None:
        for key in cls.counters:
            cls.counters[key] = 0
        cls.latencies_ms.clear()
