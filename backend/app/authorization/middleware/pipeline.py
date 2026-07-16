"""The authorization pipeline (Phase 4.3.6 §4, §9, §18).

The pipeline is a *fixed, deterministic* sequence of named stages. The gateway
walks ``AuthorizationPipeline.STEPS`` in order and records one trace entry per
stage — "✓" (passed), "✗" (failed/decided against) or "-" (not applicable) —
so every decision can be replayed from its audit record (§18).
"""

from __future__ import annotations

from dataclasses import dataclass, field


class AuthorizationPipeline:
    """§9 — the canonical stage order. Changing this order is a breaking,
    security-relevant change; the unit tests pin it."""

    AUTHENTICATION = "AUTHENTICATION"
    IDENTITY_CONTEXT = "IDENTITY_CONTEXT"
    SESSION_VALIDATION = "SESSION_VALIDATION"
    ORGANIZATION_CONTEXT = "ORGANIZATION_CONTEXT"
    RBAC = "RBAC"
    RESOURCE_AUTHORIZATION = "RESOURCE_AUTHORIZATION"
    ABAC = "ABAC"
    OBLIGATIONS = "OBLIGATIONS"
    AUDIT = "AUDIT"
    CACHE = "CACHE"

    STEPS: tuple[str, ...] = (
        AUTHENTICATION,
        IDENTITY_CONTEXT,
        SESSION_VALIDATION,
        ORGANIZATION_CONTEXT,
        RBAC,
        RESOURCE_AUTHORIZATION,
        ABAC,
        OBLIGATIONS,
        AUDIT,
        CACHE,
    )


@dataclass
class DecisionTrace:
    """§18 — ordered stage outcomes plus free-form detail per stage."""

    steps: list[dict] = field(default_factory=list)

    def record(self, stage: str, status: str, detail: str | None = None) -> None:
        if stage not in AuthorizationPipeline.STEPS:
            raise ValueError(f"Unknown pipeline stage: {stage}")
        entry: dict = {"stage": stage, "status": status}
        if detail:
            entry["detail"] = detail
        self.steps.append(entry)

    def as_list(self) -> list[dict]:
        return list(self.steps)

    def summary(self) -> list[str]:
        return [f"{s['stage']} {s['status']}" for s in self.steps]


class DecisionTraceService:
    """§21 — builds pipeline traces and asserts stage ordering is monotonic
    (a stage may only be recorded at or after the previous stage's position)."""

    def __init__(self) -> None:
        self.trace = DecisionTrace()
        self._last_index = -1

    def record(self, stage: str, status: str, detail: str | None = None) -> None:
        index = AuthorizationPipeline.STEPS.index(stage)
        if index < self._last_index:
            raise ValueError(
                f"Pipeline order violation: {stage} recorded after "
                f"{AuthorizationPipeline.STEPS[self._last_index]}"
            )
        self._last_index = index
        self.trace.record(stage, status, detail)
