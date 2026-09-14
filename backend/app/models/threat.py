"""Phase 5.6 (M5.6) - Runtime Threat Detection & Containment.

``ThreatFinding`` is a **runtime event** (distinct from Phase 5.5's
``PostureFinding``, a standing-state record) — "this happened just now", not
"this is how things stand". It reuses the 4.7 finding-lifecycle *shape*
(``app.slo.states`` imported, not re-spelled) for the same reason
``PostureFinding`` does (ADR-0019, extended by ADR-0020): the row is about
something none of the existing finding/alert tables are about.

``ContainmentAction`` **records; it does not enforce.** It has no status
value produced by enforcement logic of its own — ``EXECUTED`` always points
(``authority_ref``) at a row a *real* existing authority created: a
``KillSwitchService`` audit event, a revoked ``agent_tools``/
``agent_capabilities`` row, a disabled ``connector_instances`` row, an
agent-scoped ``runtime_governance_policies`` row. See
``app/threat/containment.py`` and ADR-0020 for the action -> authority
mapping and the truthful-containment rule (capability derives from
``agents.control_state``, never assumed).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin

THREAT_SEVERITIES = ("INFO", "WARNING", "HIGH", "CRITICAL")
THREAT_STATUSES = ("OPEN", "ACKNOWLEDGED", "RESOLVED", "SUPPRESSED")
THREAT_OUTCOMES = ("FINDING", "INSUFFICIENT_DATA")

#: The seven containment actions this phase offers. Each maps to exactly one
#: existing enforcement authority (app/threat/containment.py::_AUTHORITY_FOR)
#: — there is no eighth action and no action implemented by this package
#: itself.
CONTAINMENT_ACTION_TYPES = (
    "TERMINATE_EXECUTION",   # -> KillSwitchService, scope EXECUTION
    "SUSPEND_AGENT",         # -> KillSwitchService, scope AGENT
    "DENY_TOOL",             # -> ToolRegistryService.revoke (an AgentTool grant)
    "REVOKE_CAPABILITY",     # -> CapabilityService.revoke (an AgentCapability grant)
    "ISOLATE_CREDENTIAL",    # -> api_key_service.revoke_key (an AgentApiKey)
    "DISABLE_INTEGRATION",   # -> ConnectorInstanceService.disable
    "REQUIRE_APPROVAL",      # -> GovernancePolicyService.create (a real, enforced CHALLENGE policy)
)

CONTAINMENT_AUTHORITIES = (
    "KILL_SWITCH", "GOVERNANCE_POLICY", "TOOL_LIFECYCLE", "CAPABILITY_LIFECYCLE",
    "CREDENTIAL_LIFECYCLE", "CONNECTOR_LIFECYCLE",
)
CONTAINMENT_TRIGGERS = ("THREAT", "OPERATOR")

#: RECOMMENDED   - the threat evaluator suggested this action; nothing invoked.
#: PENDING_CONFIRMATION - an operator (or bounded automation) asked for this
#:                 action but it is dangerous, so it is queued for explicit
#:                 confirmation before the real authority is called.
#: EXECUTED       - the real authority was invoked and succeeded; authority_ref
#:                 names the row it produced.
#: REFUSED        - ACT genuinely has no enforcement authority over this agent
#:                 (control_state != GOVERNED) — a truthful refusal, not an
#:                 attempt. Never a fake EXECUTED.
#: FAILED         - the real authority was invoked and raised; a mandatory
#:                 containment that cannot complete fails closed (recorded
#:                 honestly, never silently treated as EXECUTED).
#: REVERTED       - a reversible action was reverted through the same
#:                 authority's own reverse operation.
CONTAINMENT_ACTION_STATUSES = (
    "RECOMMENDED", "PENDING_CONFIRMATION", "EXECUTED", "REFUSED", "FAILED", "REVERTED",
)


class ThreatFinding(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "threat_findings"
    __table_args__ = (
        CheckConstraint(f"severity IN {THREAT_SEVERITIES}", name="ck_threat_findings_severity"),
        CheckConstraint(f"status IN {THREAT_STATUSES}", name="ck_threat_findings_status"),
        CheckConstraint(f"outcome IN {THREAT_OUTCOMES}", name="ck_threat_findings_outcome"),
        Index("ix_threat_findings_org_status_sev", "organization_id", "status", "severity"),
        Index("ix_threat_findings_agent", "agent_id"),
        Index("ix_threat_findings_org_rule", "organization_id", "rule_id"),
        Index(
            "uq_threat_findings_active",
            "organization_id",
            "dedup_key",
            unique=True,
            postgresql_where=text("status IN ('OPEN', 'ACKNOWLEDGED')"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")
    ruleset_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="FINDING")
    severity: Mapped[str] = mapped_column(String(12), nullable=False, default="WARNING")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    #: who/what a threat reaches — 5.3 authority chain / 5.4 blast-radius refs.
    attribution: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: {"refs": [{"table": ..., "id": ...}], ...} — the triggering runtime
    #: evidence (a behavioral_findings row, governance decisions, tool_calls).
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    dedup_key: Mapped[str] = mapped_column(String(180), nullable=False)
    recurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    suppressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suppressed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ContainmentAction(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "containment_actions"
    __table_args__ = (
        CheckConstraint(f"action_type IN {CONTAINMENT_ACTION_TYPES}", name="ck_containment_actions_type"),
        CheckConstraint(f"authority IN {CONTAINMENT_AUTHORITIES}", name="ck_containment_actions_authority"),
        CheckConstraint(f"trigger IN {CONTAINMENT_TRIGGERS}", name="ck_containment_actions_trigger"),
        CheckConstraint(f"status IN {CONTAINMENT_ACTION_STATUSES}", name="ck_containment_actions_status"),
        Index("ix_containment_actions_org_status", "organization_id", "status"),
        Index("ix_containment_actions_agent", "agent_id"),
        Index("ix_containment_actions_threat", "threat_finding_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
    )
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    authority: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    threat_finding_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("threat_findings.id", ondelete="SET NULL"), nullable=True,
    )
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    automated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False,
    )
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    #: the truthful-containment signal, captured at decision time so the
    #: record explains itself even if the agent's control_state later changes.
    control_state_at_time: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="RECOMMENDED")
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    refusal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: {"table": ..., "id": ...} — the row the real authority produced/touched.
    authority_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    reversible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reverted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


__all__ = [
    "THREAT_SEVERITIES",
    "THREAT_STATUSES",
    "THREAT_OUTCOMES",
    "CONTAINMENT_ACTION_TYPES",
    "CONTAINMENT_AUTHORITIES",
    "CONTAINMENT_TRIGGERS",
    "CONTAINMENT_ACTION_STATUSES",
    "ThreatFinding",
    "ContainmentAction",
]
