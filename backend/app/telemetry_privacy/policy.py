"""Phase 4.8 -- capture-policy resolution and management (M4-4.8-FR-001..004).

**Precedence (most specific wins):**

    classification  >  agent  >  environment  >  tenant  >  platform-default

A policy row applies to the intersection of the scope columns it sets. Given a
query ``(organization, environment, agent, classification)``, every *enabled*
row whose set scope columns all match the query is a candidate; the candidate
with the most specific scope wins, ties broken by most-recently-updated then id
so the effective mode is a pure function of the stored rows.

**Conservative default (M4-4.8-FR-002).** When no row matches:

- a production environment, or one whose policy declares a sensitive data
  classification, resolves to ``METADATA_ONLY``;
- every other scope also resolves to ``METADATA_ONLY``.

Content is opt-in everywhere. A malformed stored mode is coerced toward
``METADATA_ONLY`` (:func:`app.telemetry_privacy.modes.coerce`), never toward a
content mode -- a misconfiguration fails toward *less* capture.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.runtime import (
    AgentDeployment,
    AgentExecution,
    Environment,
    TelemetryCapturePolicy,
)
from app.telemetry_privacy.modes import (
    CAPTURE_MODES,
    CaptureMode,
    CONSERVATIVE_DEFAULT,
    PLATFORM_DEFAULT,
    coerce,
)

#: Data-classification values a policy may target and that the resolver treats
#: as "sensitive" for the conservative-default decision. Deliberately a small
#: closed set -- an operator naming a classification outside it gets a
#: validation error, not a silently-ignored policy.
KNOWN_CLASSIFICATIONS: frozenset[str] = frozenset(
    {"PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED", "PII", "PHI", "REGULATED"}
)
SENSITIVE_CLASSIFICATIONS: frozenset[str] = frozenset(
    {"CONFIDENTIAL", "RESTRICTED", "PII", "PHI", "REGULATED"}
)

_NIL = uuid.UUID("00000000-0000-0000-0000-000000000000")

# Specificity weights -- higher is more specific. The ordering, not the exact
# numbers, is what matters; they are chosen so no combination of lower tiers can
# outweigh a single higher tier.
_W_CLASSIFICATION = 8
_W_AGENT = 4
_W_ENVIRONMENT = 2
_W_ORGANIZATION = 1


class CapturePolicyError(ValueError):
    """A capture-policy payload is malformed. Mapped to
    ``TELEMETRY_POLICY_INVALID`` (422); it never reaches an execution."""


@dataclass(frozen=True)
class EffectiveMode:
    """The resolved capture mode for a scope, with an explanation an operator
    can read (M4-4.8-FR-003)."""

    mode: CaptureMode
    source: str  # "policy" | "conservative-default" | "platform-default"
    policy_id: uuid.UUID | None = None
    matched_scope: dict = field(default_factory=dict)
    reason: str = ""
    considered: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "source": self.source,
            "policy_id": str(self.policy_id) if self.policy_id else None,
            "matched_scope": self.matched_scope,
            "reason": self.reason,
            "considered": self.considered,
            "precedence": "classification > agent > environment > tenant > platform-default",
        }


def _row_scope(row: TelemetryCapturePolicy) -> dict:
    return {
        "organization_id": str(row.organization_id) if row.organization_id else None,
        "environment_id": str(row.environment_id) if row.environment_id else None,
        "agent_id": str(row.agent_id) if row.agent_id else None,
        "classification": row.classification,
    }


def _matches(row: TelemetryCapturePolicy, *, organization_id: uuid.UUID,
             environment_id: uuid.UUID | None, agent_id: uuid.UUID | None,
             classification: str | None) -> bool:
    if row.organization_id is not None and row.organization_id != organization_id:
        return False
    if row.environment_id is not None and row.environment_id != environment_id:
        return False
    if row.agent_id is not None and row.agent_id != agent_id:
        return False
    if row.classification is not None and row.classification != classification:
        return False
    return True


def _specificity(row: TelemetryCapturePolicy) -> int:
    score = 0
    if row.classification is not None:
        score += _W_CLASSIFICATION
    if row.agent_id is not None:
        score += _W_AGENT
    if row.environment_id is not None:
        score += _W_ENVIRONMENT
    if row.organization_id is not None:
        score += _W_ORGANIZATION
    return score


def _is_sensitive_environment(env: Environment | None) -> tuple[bool, str]:
    if env is None:
        return False, ""
    if env.is_production:
        return True, f"environment {env.name!r} is production"
    policy = env.policy if isinstance(env.policy, dict) else {}
    declared = policy.get("data_classification") or policy.get("classification")
    if isinstance(declared, str) and declared.upper() in SENSITIVE_CLASSIFICATIONS:
        return True, f"environment {env.name!r} declares classification {declared!r}"
    allowed = policy.get("allowed_data_classifications")
    if isinstance(allowed, list) and any(
        isinstance(c, str) and c.upper() in SENSITIVE_CLASSIFICATIONS for c in allowed
    ):
        return True, f"environment {env.name!r} permits a sensitive data classification"
    return False, ""


def resolve_capture_mode(
    db: Session, *, organization_id: uuid.UUID,
    environment_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    classification: str | None = None,
) -> EffectiveMode:
    """Resolve the effective capture mode for a scope (M4-4.8-FR-001, FR-003).

    Pure read. The result carries the winning policy (if any), the scope it
    matched, and every candidate considered, so ``GET .../effective-mode`` is
    fully explainable."""
    rows = list(db.execute(
        select(TelemetryCapturePolicy).where(
            TelemetryCapturePolicy.enabled.is_(True),
            (TelemetryCapturePolicy.organization_id == organization_id)
            | (TelemetryCapturePolicy.organization_id.is_(None)),
        )
    ).scalars())

    candidates = [
        r for r in rows
        if _matches(r, organization_id=organization_id, environment_id=environment_id,
                    agent_id=agent_id, classification=classification)
    ]
    considered = [
        {**_row_scope(r), "mode": r.mode, "specificity": _specificity(r),
         "policy_id": str(r.id)}
        for r in sorted(candidates, key=_specificity, reverse=True)
    ]

    if candidates:
        best = max(
            candidates,
            key=lambda r: (_specificity(r), r.updated_at or r.created_at, str(r.id)),
        )
        mode = coerce(best.mode)
        return EffectiveMode(
            mode=mode, source="policy", policy_id=best.id,
            matched_scope=_row_scope(best),
            reason=(f"policy {best.id} (specificity {_specificity(best)}) sets "
                    f"{mode.value}"),
            considered=considered,
        )

    # No explicit policy -- conservative default.
    env = db.get(Environment, environment_id) if environment_id else None
    sensitive, why = _is_sensitive_environment(env)
    sensitive_class = (
        isinstance(classification, str)
        and classification.upper() in SENSITIVE_CLASSIFICATIONS
    )
    if sensitive or sensitive_class:
        reason = why or f"classification {classification!r} is sensitive"
        return EffectiveMode(
            mode=CONSERVATIVE_DEFAULT, source="conservative-default",
            reason=(f"no policy matched; {reason}; defaulting conservatively to "
                    f"{CONSERVATIVE_DEFAULT.value} (never FULL_CONTENT without an "
                    f"explicit policy)"),
            considered=considered,
        )
    return EffectiveMode(
        mode=PLATFORM_DEFAULT, source="platform-default",
        reason=(f"no policy matched; platform default is {PLATFORM_DEFAULT.value} -- "
                f"content capture is opt-in everywhere"),
        considered=considered,
    )


def resolve_for_execution(db: Session, execution: AgentExecution) -> EffectiveMode:
    """Resolve the effective mode for the scope an execution belongs to.

    Environment is taken from the execution's deployment
    (``environment_id`` first, then the bare ``environment`` name matched to an
    ``Environment`` row); classification from the environment policy if it
    declares one. Best-effort: an unresolvable environment simply narrows the
    scope to ``(organization, agent)``."""
    environment_id: uuid.UUID | None = None
    classification: str | None = None
    if execution.deployment_id:
        deployment = db.get(AgentDeployment, execution.deployment_id)
        if deployment is not None:
            environment_id = deployment.environment_id
            if environment_id is None and deployment.environment:
                env = db.execute(
                    select(Environment).where(
                        Environment.organization_id == execution.organization_id,
                        Environment.name == deployment.environment,
                    )
                ).scalar_one_or_none()
                environment_id = env.id if env else None
    if environment_id is not None:
        env = db.get(Environment, environment_id)
        if env is not None and isinstance(env.policy, dict):
            declared = env.policy.get("data_classification") or env.policy.get("classification")
            if isinstance(declared, str):
                classification = declared.upper()
    return resolve_capture_mode(
        db, organization_id=execution.organization_id,
        environment_id=environment_id, agent_id=execution.agent_id,
        classification=classification,
    )


# --------------------------------------------------------------------------- #
# Management
# --------------------------------------------------------------------------- #
def validate_capture_policy(payload: dict) -> dict:
    """Validate a create/update payload; return the clean dict."""
    out: dict = {}
    mode = payload.get("mode")
    if mode not in CAPTURE_MODES:
        raise CapturePolicyError(
            f"Unknown mode {mode!r}. Known: {list(CAPTURE_MODES)}.")
    out["mode"] = mode

    classification = payload.get("classification")
    if classification is not None:
        classification = str(classification).strip().upper()
        if classification not in KNOWN_CLASSIFICATIONS:
            raise CapturePolicyError(
                f"Unknown classification {classification!r}. "
                f"Known: {sorted(KNOWN_CLASSIFICATIONS)}.")
        out["classification"] = classification

    for key in ("environment_id", "agent_id"):
        value = payload.get(key)
        if value is not None:
            out[key] = _as_uuid(value, key)

    if "enabled" in payload and payload["enabled"] is not None:
        if not isinstance(payload["enabled"], bool):
            raise CapturePolicyError("enabled must be a boolean.")
        out["enabled"] = payload["enabled"]
    return out


def _as_uuid(value, field_name: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise CapturePolicyError(f"{field_name} must be a UUID.") from None


class CapturePolicyService:
    """Tenant-scoped CRUD over ``telemetry_capture_policies``.

    A caller never reaches the ``organization_id IS NULL`` platform-default row
    through this service -- every statement pins the actor's organization."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, organization_id: uuid.UUID) -> list[TelemetryCapturePolicy]:
        return list(self.db.execute(
            select(TelemetryCapturePolicy)
            .where(TelemetryCapturePolicy.organization_id == organization_id)
            .order_by(TelemetryCapturePolicy.created_at.desc())
        ).scalars())

    def get_or_none(self, organization_id: uuid.UUID,
                    policy_id: uuid.UUID) -> TelemetryCapturePolicy | None:
        row = self.db.get(TelemetryCapturePolicy, policy_id)
        if row is None or row.organization_id != organization_id:
            return None
        return row

    def create(self, organization_id: uuid.UUID, actor_id: uuid.UUID | None,
               payload: dict) -> TelemetryCapturePolicy:
        clean = validate_capture_policy(payload)
        self._reject_duplicate_scope(
            organization_id, clean.get("environment_id"), clean.get("agent_id"),
            clean.get("classification"), exclude_id=None)
        row = TelemetryCapturePolicy(
            organization_id=organization_id, created_by=actor_id,
            environment_id=clean.get("environment_id"),
            agent_id=clean.get("agent_id"),
            classification=clean.get("classification"),
            mode=clean["mode"], enabled=clean.get("enabled", True),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def update(self, row: TelemetryCapturePolicy, payload: dict) -> TelemetryCapturePolicy:
        merged = {
            "mode": payload.get("mode", row.mode),
            "classification": payload.get("classification", row.classification),
            "environment_id": payload.get("environment_id", row.environment_id),
            "agent_id": payload.get("agent_id", row.agent_id),
            "enabled": payload.get("enabled", row.enabled),
        }
        clean = validate_capture_policy(merged)
        self._reject_duplicate_scope(
            row.organization_id, clean.get("environment_id"), clean.get("agent_id"),
            clean.get("classification"), exclude_id=row.id)
        row.mode = clean["mode"]
        row.classification = clean.get("classification")
        row.environment_id = clean.get("environment_id")
        row.agent_id = clean.get("agent_id")
        row.enabled = clean.get("enabled", row.enabled)
        self.db.flush()
        return row

    def delete(self, row: TelemetryCapturePolicy) -> None:
        self.db.delete(row)
        self.db.flush()

    def _reject_duplicate_scope(self, organization_id, environment_id, agent_id,
                                classification, *, exclude_id) -> None:
        stmt = select(TelemetryCapturePolicy.id).where(
            TelemetryCapturePolicy.organization_id == organization_id,
            TelemetryCapturePolicy.environment_id.is_(environment_id)
            if environment_id is None
            else TelemetryCapturePolicy.environment_id == environment_id,
            TelemetryCapturePolicy.agent_id.is_(agent_id)
            if agent_id is None
            else TelemetryCapturePolicy.agent_id == agent_id,
            TelemetryCapturePolicy.classification.is_(classification)
            if classification is None
            else TelemetryCapturePolicy.classification == classification,
        )
        existing = self.db.execute(stmt).first()
        if existing is not None and existing[0] != exclude_id:
            raise CapturePolicyError(
                "A capture policy for this exact scope already exists; edit it "
                "instead of creating a second contradictory one.")
