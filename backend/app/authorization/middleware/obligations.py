"""Obligation processing (Phase 4.3.6 §16).

Obligations never replace authorization — they modify execution. The executor
turns the gateway's obligation list into concrete enforcement outcomes for the
calling enforcement point:

- challenge obligations (approval / MFA / justification) become instructions
  the enforcement point must satisfy before proceeding;
- constraint obligations are applied here (``mask_fields``) or returned as
  parameter clamps (``limits``) the caller must honour;
- ``NOTIFY_SECURITY`` and ``LOG_ONLY`` are executed immediately (audit event).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import ActorType
from app.services import audit_service

_MASK = "***"

# Limit obligations the middleware recognizes (§16); anything else in a
# LIMIT_ACTION payload is passed through untouched for the caller to interpret.
KNOWN_LIMITS = {
    "maximum_export_rows", "limit_rows", "limit_tokens", "limit_cost",
    "limit_export", "target_count",
}


@dataclass
class ObligationOutcome:
    """What the enforcement point must do before/while executing."""

    requires_approval: bool = False
    requires_mfa: bool = False
    requires_justification: bool = False
    approval: dict[str, Any] | None = None       # priority / reviewer_role / policy_id
    masked_fields: tuple[str, ...] = ()
    limits: dict[str, Any] = field(default_factory=dict)
    notified_security: bool = False
    instructions: list[dict] = field(default_factory=list)  # normalized passthrough


class ObligationExecutor:
    """§16, §21 — processes obligations after the decision is made."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def execute(
        self,
        obligations: list[dict],
        *,
        organization_id: uuid.UUID | None,
        identity_id: uuid.UUID | None,
        identity_kind: str = "USER",
        action: str = "",
        request_id: str | None = None,
    ) -> ObligationOutcome:
        outcome = ObligationOutcome()
        for ob in obligations or []:
            kind = ob.get("type")
            if kind == "CREATE_APPROVAL":
                outcome.requires_approval = True
                outcome.approval = {
                    "priority": ob.get("priority", "HIGH"),
                    "reviewer_role": ob.get("reviewer_role"),
                    "policy_id": ob.get("policy_id"),
                }
            elif kind == "REQUIRE_MFA":
                outcome.requires_mfa = True
            elif kind == "REQUIRE_JUSTIFICATION":
                outcome.requires_justification = True
            elif kind == "MASK_FIELDS":
                outcome.masked_fields = tuple(ob.get("fields") or ())
            elif kind == "LIMIT_ACTION":
                outcome.limits.update(ob.get("limits") or {})
            elif kind == "NOTIFY_SECURITY":
                self._notify_security(ob, organization_id=organization_id,
                                      identity_id=identity_id, identity_kind=identity_kind,
                                      action=action, request_id=request_id)
                outcome.notified_security = True
            # LOG_ONLY observations were already audited by the ABAC engine.
            outcome.instructions.append(dict(ob))
        return outcome

    # ------------------------------------------------------------------ #
    # Constraint helpers — pure, reusable by any enforcement point.
    # ------------------------------------------------------------------ #
    @staticmethod
    def mask_fields(payload: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
        """Return a copy of ``payload`` with the restricted fields replaced.
        Nested dicts are masked recursively; the original is never mutated."""
        if not fields:
            return dict(payload)
        masked: dict[str, Any] = {}
        for key, value in payload.items():
            if key in fields:
                masked[key] = _MASK
            elif isinstance(value, dict):
                masked[key] = ObligationExecutor.mask_fields(value, fields)
            elif isinstance(value, list):
                masked[key] = [
                    ObligationExecutor.mask_fields(v, fields) if isinstance(v, dict) else v
                    for v in value
                ]
            else:
                masked[key] = value
        return masked

    @staticmethod
    def apply_limits(params: dict[str, Any], limits: dict[str, Any]) -> dict[str, Any]:
        """Clamp request parameters to the obligated maxima. A parameter named
        like a known limit (``row_count`` vs ``limit_rows`` /
        ``maximum_export_rows``) is capped; unknown limits are attached as
        ``_limits`` for the caller."""
        clamped = dict(params)
        aliases = {
            "maximum_export_rows": ("row_count", "rows", "export_rows"),
            "limit_rows": ("row_count", "rows", "export_rows"),
            "limit_tokens": ("max_tokens", "tokens"),
            "limit_cost": ("max_cost", "estimated_cost"),
            "limit_export": ("export_size",),
            "target_count": ("target_count",),
        }
        passthrough: dict[str, Any] = {}
        for limit_name, maximum in (limits or {}).items():
            targets = aliases.get(limit_name)
            if targets is None or not isinstance(maximum, (int, float)):
                passthrough[limit_name] = maximum
                continue
            for target in targets:
                value = clamped.get(target)
                if isinstance(value, (int, float)) and value > maximum:
                    clamped[target] = maximum
        if passthrough:
            clamped["_limits"] = passthrough
        return clamped

    def _notify_security(self, ob: dict, *, organization_id, identity_id,
                         identity_kind: str, action: str, request_id: str | None) -> None:
        actor_type = ActorType.AGENT if identity_kind == "AGENT" else (
            ActorType.SYSTEM if identity_kind == "SYSTEM" else ActorType.USER)
        audit_service.log_event(
            self.db,
            organization_id=organization_id,
            actor_type=actor_type,
            actor_id=identity_id,
            event_type="SECURITY_NOTIFICATION",
            entity_type="authorization",
            entity_id=None,
            request_id=request_id,
            metadata={"action": action, "obligation": {k: v for k, v in ob.items()
                                                       if k != "type"}},
        )
