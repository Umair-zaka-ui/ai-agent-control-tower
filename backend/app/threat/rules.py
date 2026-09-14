"""Phase 5.6 (M5.6) - the deterministic runtime-threat rule catalog.

Same discipline as ``app.posture.rules`` (which itself mirrors ``app.behavior``,
which mirrors the Phase 3.5 engine shape): each rule is a **pure function of
(runtime signals + graph evidence)** over a lookback window, no ML
(``test_ac02_no_ml_import`` walks the AST). A threat rule answers *"did this
happen recently"*, which is what makes it a runtime **event** rather than
Phase 5.5's standing **state** — the posture/threat boundary (ADR-0020): an
agent depending on an unapproved MCP server is posture; the agent actually
*invoking* a tool that unapproved server exposes is a threat
(``unapproved_mcp_tool_invoked`` below is exactly that example).

A rule returns ``FINDING`` (the condition held within the window — open/sustain
a threat finding) or ``CLEAR`` (it evaluated and nothing suspicious is in the
window — auto-resolve any open finding for it). Detection fails open at the
evaluator, not here: a rule that raises is caught by the caller and produces
no finding.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import cached_property
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.graph import ControlGraphEdge, McpServer
from app.models.posture import PostureFinding
from app.models.runtime import AgentExecution, BehavioralFinding, RuntimeGovernanceDecision, ToolCall

THREAT_RULESET_VERSION = "1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RuleOutcome:
    outcome: str  # "FINDING" | "CLEAR"
    severity: str | None = None
    reason: str = ""
    evidence: dict = field(default_factory=dict)
    attribution: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ThreatRule:
    id: str
    severity: str
    version: str
    default_params: dict
    summary: str
    fn: "Callable[[ThreatContext, dict], RuleOutcome]"

    def evaluate(self, ctx: "ThreatContext", params: dict) -> RuleOutcome:
        merged = {**self.default_params, **(params or {})}
        return self.fn(ctx, merged)


class ThreatContext:
    """The runtime-signal bundle for one agent, evaluated over a lookback
    window. Cached accessors mirror ``app.posture.rules.PostureContext``."""

    def __init__(self, db: Session, organization_id: uuid.UUID, agent: Agent,
                *, window: timedelta = timedelta(hours=1)) -> None:
        self.db = db
        self.organization_id = organization_id
        self.agent = agent
        self.window_end = _now()
        self.window_start = self.window_end - window

    @cached_property
    def anomalous_behavioral_findings(self) -> list[BehavioralFinding]:
        return list(
            self.db.execute(
                select(BehavioralFinding).where(
                    BehavioralFinding.organization_id == self.organization_id,
                    BehavioralFinding.agent_id == self.agent.id,
                    BehavioralFinding.state == "ANOMALOUS",
                    BehavioralFinding.evaluated_at >= self.window_start,
                )
            ).scalars()
        )

    @cached_property
    def governance_denial_count(self) -> int:
        return int(
            self.db.execute(
                select(func.count(RuntimeGovernanceDecision.id))
                .join(AgentExecution, AgentExecution.id == RuntimeGovernanceDecision.execution_id)
                .where(
                    AgentExecution.organization_id == self.organization_id,
                    AgentExecution.agent_id == self.agent.id,
                    RuntimeGovernanceDecision.decision.in_(("STOP", "DENY")),
                    RuntimeGovernanceDecision.evaluated_at >= self.window_start,
                )
            ).scalar()
            or 0
        )

    @cached_property
    def egress_denied_tool_calls(self) -> list[ToolCall]:
        return list(
            self.db.execute(
                select(ToolCall).where(
                    ToolCall.agent_id == self.agent.id,
                    ToolCall.egress_decision == "DENIED",
                    ToolCall.created_at >= self.window_start,
                )
            ).scalars()
        )

    @cached_property
    def schema_invalid_tool_calls(self) -> list[ToolCall]:
        return list(
            self.db.execute(
                select(ToolCall).where(
                    ToolCall.agent_id == self.agent.id,
                    ToolCall.validation_error.is_not(None),
                    ToolCall.created_at >= self.window_start,
                )
            ).scalars()
        )

    @cached_property
    def observed_unapproved_mcp_tool_calls(self) -> list[dict]:
        """OBSERVED dependency edges (this agent actually invoked the tool)
        onto a tool exposed by an MCP server whose trust_status != APPROVED,
        cross-referenced against real ``tool_calls`` rows in the window — the
        posture-vs-threat distinguishing example: 5.4/5.5 already know the
        *dependency*; this rule asks whether it was *used*."""
        edges = list(
            self.db.execute(
                select(ControlGraphEdge).where(
                    ControlGraphEdge.organization_id == self.organization_id,
                    ControlGraphEdge.source_type == "AGENT",
                    ControlGraphEdge.source_id == self.agent.id,
                    ControlGraphEdge.edge_type == "DEPENDS_ON_TOOL",
                    ControlGraphEdge.revoked_at.is_(None),
                )
            ).scalars()
        )
        out: list[dict] = []
        for edge in edges:
            if (edge.evidence or {}).get("mode") != "OBSERVED":
                continue
            tool_id = edge.target_id
            mcp_edge = self.db.execute(
                select(ControlGraphEdge).where(
                    ControlGraphEdge.organization_id == self.organization_id,
                    ControlGraphEdge.edge_type == "MCP_EXPOSES_TOOL",
                    ControlGraphEdge.target_type == "TOOL",
                    ControlGraphEdge.target_id == tool_id,
                    ControlGraphEdge.revoked_at.is_(None),
                )
            ).scalars().first()
            if mcp_edge is None:
                continue
            server = self.db.get(McpServer, mcp_edge.source_id)
            if server is None or server.organization_id != self.organization_id:
                continue
            if server.trust_status == "APPROVED":
                continue
            recent_call = self.db.execute(
                select(ToolCall.id).where(
                    ToolCall.agent_id == self.agent.id,
                    ToolCall.tool_id == tool_id,
                    ToolCall.created_at >= self.window_start,
                ).limit(1)
            ).first()
            if recent_call is None:
                continue
            out.append({
                "tool_id": str(tool_id), "mcp_server_id": str(server.id),
                "mcp_server_name": server.name, "trust_status": server.trust_status,
                "dependency_edge_id": str(edge.id), "tool_call_id": str(recent_call[0]),
            })
        return out

    @cached_property
    def open_credential_posture_findings(self) -> list[PostureFinding]:
        return list(
            self.db.execute(
                select(PostureFinding).where(
                    PostureFinding.organization_id == self.organization_id,
                    PostureFinding.subject_id == self.agent.id,
                    PostureFinding.status.in_(("OPEN", "ACKNOWLEDGED")),
                    PostureFinding.outcome == "FINDING",
                    PostureFinding.rule_id.in_(("stale_credential", "expired_credential_still_active")),
                )
            ).scalars()
        )

    @cached_property
    def recent_activity_count(self) -> int:
        return int(
            self.db.execute(
                select(func.count(AgentExecution.id)).where(
                    AgentExecution.organization_id == self.organization_id,
                    AgentExecution.agent_id == self.agent.id,
                    AgentExecution.created_at >= self.window_start,
                )
            ).scalar()
            or 0
        )


# --------------------------------------------------------------------------- #
# The rules
# --------------------------------------------------------------------------- #
def _rule_behavioral_anomaly(ctx: ThreatContext, params: dict) -> RuleOutcome:
    findings = ctx.anomalous_behavioral_findings
    if not findings:
        return RuleOutcome("CLEAR")
    signals = sorted({f.signal_type for f in findings})
    return RuleOutcome(
        "FINDING",
        reason=(f"{len(findings)} ANOMALOUS behavioral finding(s) in the last "
                f"{int((ctx.window_end - ctx.window_start).total_seconds() // 60)} minutes: "
                f"{', '.join(signals)}."),
        evidence={"refs": [{"table": "behavioral_findings", "id": str(f.id)} for f in findings],
                  "signal_types": signals},
    )


def _rule_governance_denial_spike(ctx: ThreatContext, params: dict) -> RuleOutcome:
    threshold = int(params.get("min_denials", 3))
    count = ctx.governance_denial_count
    if count < threshold:
        return RuleOutcome("CLEAR")
    return RuleOutcome(
        "FINDING",
        reason=(f"{count} governance STOP/DENY decisions for this agent's executions in the "
                f"lookback window (threshold {threshold}) - a probing or misuse pattern."),
        evidence={"refs": [{"table": "runtime_governance_decisions"}], "count": count,
                  "threshold": threshold},
    )


def _rule_repeated_tool_egress_denial(ctx: ThreatContext, params: dict) -> RuleOutcome:
    threshold = int(params.get("min_denials", 3))
    calls = ctx.egress_denied_tool_calls
    if len(calls) < threshold:
        return RuleOutcome("CLEAR")
    return RuleOutcome(
        "FINDING",
        reason=(f"{len(calls)} tool calls denied by the egress guard in the lookback window "
                f"(threshold {threshold}) - a possible SSRF/egress-boundary probe."),
        evidence={"refs": [{"table": "tool_calls", "id": str(c.id)} for c in calls],
                  "count": len(calls), "threshold": threshold},
    )


def _rule_tool_schema_validation_failure(ctx: ThreatContext, params: dict) -> RuleOutcome:
    threshold = int(params.get("min_failures", 2))
    calls = ctx.schema_invalid_tool_calls
    if len(calls) < threshold:
        return RuleOutcome("CLEAR")
    return RuleOutcome(
        "FINDING",
        reason=(f"{len(calls)} tool calls failed input/output schema validation in the lookback "
                f"window (threshold {threshold}) - evidence of a malicious or malfunctioning "
                f"tool/MCP response."),
        evidence={"refs": [{"table": "tool_calls", "id": str(c.id)} for c in calls],
                  "count": len(calls), "threshold": threshold},
    )


def _rule_unapproved_mcp_tool_invoked(ctx: ThreatContext, params: dict) -> RuleOutcome:
    hits = ctx.observed_unapproved_mcp_tool_calls
    if not hits:
        return RuleOutcome("CLEAR")
    servers = sorted({h["mcp_server_name"] for h in hits})
    return RuleOutcome(
        "FINDING",
        reason=(f"The agent invoked a tool exposed by an unapproved/unknown-provenance MCP "
                f"server in the lookback window: {', '.join(servers)}. This is a runtime event, "
                f"not the standing dependency (Phase 5.5) - the tool was actually called."),
        evidence={"refs": [{"table": "tool_calls", "id": h["tool_call_id"]} for h in hits]
                  + [{"table": "mcp_servers", "id": h["mcp_server_id"]} for h in hits],
                  "hits": hits},
        attribution={"kind": "mcp_supply_chain", "servers": servers},
    )


def _rule_flagged_credential_used(ctx: ThreatContext, params: dict) -> RuleOutcome:
    findings = ctx.open_credential_posture_findings
    if not findings or ctx.recent_activity_count == 0:
        return RuleOutcome("CLEAR")
    return RuleOutcome(
        "FINDING",
        severity="WARNING",
        reason=(f"The agent has {ctx.recent_activity_count} execution(s) in the lookback window "
                f"while holding a credential already flagged stale/expired by posture "
                f"({', '.join(sorted({f.rule_id for f in findings}))})."),
        evidence={"refs": [{"table": "posture_findings", "id": str(f.id)} for f in findings],
                  "recent_activity_count": ctx.recent_activity_count},
    )


RULES: tuple[ThreatRule, ...] = (
    ThreatRule("behavioral_anomaly_threat", "HIGH", "1", {},
               "An ANOMALOUS behavioral finding occurred recently.", _rule_behavioral_anomaly),
    ThreatRule("governance_denial_spike", "HIGH", "1", {"min_denials": 3},
               "A spike of governance STOP/DENY decisions - probing or misuse.",
               _rule_governance_denial_spike),
    ThreatRule("repeated_tool_egress_denial", "HIGH", "1", {"min_denials": 3},
               "Repeated egress-guard denials - a possible SSRF probe.",
               _rule_repeated_tool_egress_denial),
    ThreatRule("tool_schema_validation_failure", "HIGH", "1", {"min_failures": 2},
               "Repeated tool schema-validation failures - malicious/malformed tool output.",
               _rule_tool_schema_validation_failure),
    ThreatRule("unapproved_mcp_tool_invoked", "CRITICAL", "1", {},
               "An unapproved-MCP-exposed tool was actually invoked.",
               _rule_unapproved_mcp_tool_invoked),
    ThreatRule("flagged_credential_used", "WARNING", "1", {},
               "Recent activity while holding a posture-flagged credential.",
               _rule_flagged_credential_used),
)

RULES_BY_ID: dict[str, ThreatRule] = {r.id: r for r in RULES}

# --------------------------------------------------------------------------- #
# Evidence-gap note (mirrors app.posture.rules): "prompt/indirect-injection"
# and "cross-agent/delegation abuse" are named in the SRS's rule examples but
# are NOT delivered here. Neither has a deterministic signal in the current
# schema: there is no reason-code taxonomy for content-based denials to key
# an injection rule off, and 5.3's delegation edges are human<->human with no
# timestamped "used after revocation" evidence to key an abuse rule off.
# Recorded here and in docs/threat/rules.md rather than fabricated.
# --------------------------------------------------------------------------- #

__all__ = [
    "THREAT_RULESET_VERSION",
    "RuleOutcome",
    "ThreatRule",
    "ThreatContext",
    "RULES",
    "RULES_BY_ID",
]
