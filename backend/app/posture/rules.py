"""Phase 5.5 (M5.5) - the deterministic posture rule catalog.

Each rule is a **pure function of (asset state + graph evidence + policy)**:
given the same evidence it produces the same outcome, and every finding
explains itself from its own record (rule, evidence rows, the condition it
crossed, severity, remediation). No ML, no scoring inside a rule -- the
``test_ac04`` AST assertion forbids the imports, mirroring Phase 4.5.

A rule returns a list of :class:`RuleOutcome`:

  * ``FINDING``           - the condition holds; open (or sustain) a finding.
  * ``INSUFFICIENT_DATA`` - the rule cannot evaluate because the evidence it
                            needs is absent. Recorded **explicitly** -- never
                            a silent "no finding = healthy" (unknown != safe).
  * ``CLEAR``             - the rule evaluated and the condition does not
                            hold; auto-resolve any open finding for it.

``PostureContext`` batches the evidence for one agent so the rules read
cached attributes rather than issuing their own queries.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import cached_property
from typing import Callable

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.api_key import AgentApiKey
from app.models.graph import DEPENDENCY_EDGE_TYPES, ControlGraphEdge, McpServer
from app.models.runtime import (
    AgentDeployment,
    AgentExecution,
    AgentTool,
    AgentVersion,
    Environment,
    RuntimeGovernancePolicy,
    SLODefinition,
)

POSTURE_RULESET_VERSION = "1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RuleOutcome:
    outcome: str  # "FINDING" | "INSUFFICIENT_DATA" | "CLEAR"
    dedup_suffix: str | None = None
    severity: str | None = None  # overrides the rule default when set
    reason: str = ""
    remediation: str = ""
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PostureRule:
    id: str
    control_id: str
    severity: str
    shadow_class: bool
    version: str
    default_params: dict
    summary: str
    fn: "Callable[[PostureContext, dict], list[RuleOutcome]]"

    def evaluate(self, ctx: "PostureContext", params: dict) -> list[RuleOutcome]:
        merged = {**self.default_params, **(params or {})}
        return self.fn(ctx, merged)


# --------------------------------------------------------------------------- #
# Evidence bundle
# --------------------------------------------------------------------------- #
class PostureContext:
    """Everything the rules read about one agent, batched. Cached accessors
    keep each rule deterministic given the database state without N queries
    per rule."""

    def __init__(self, db: Session, organization_id: uuid.UUID, agent: Agent) -> None:
        self.db = db
        self.organization_id = organization_id
        self.agent = agent

    # --- ownership / provenance / lifecycle ---------------------------- #
    @cached_property
    def has_accountable_owner(self) -> bool:
        a = self.agent
        return any((a.owner_id, a.technical_owner_id, a.compliance_owner_id))

    # --- credentials -------------------------------------------------- #
    @cached_property
    def api_keys(self) -> list[AgentApiKey]:
        return list(
            self.db.execute(
                select(AgentApiKey).where(AgentApiKey.agent_id == self.agent.id)
            ).scalars()
        )

    @cached_property
    def active_api_keys(self) -> list[AgentApiKey]:
        return [k for k in self.api_keys if str(getattr(k.status, "value", k.status)) == "ACTIVE"]

    # --- deployments / environment ---------------------------------- #
    @cached_property
    def deployments(self) -> list[AgentDeployment]:
        return list(
            self.db.execute(
                select(AgentDeployment).where(
                    AgentDeployment.agent_id == self.agent.id,
                    AgentDeployment.organization_id == self.organization_id,
                )
            ).scalars()
        )

    @cached_property
    def _production_env_ids(self) -> set[uuid.UUID]:
        return set(
            self.db.execute(
                select(Environment.id).where(
                    Environment.organization_id == self.organization_id,
                    Environment.is_production.is_(True),
                )
            ).scalars()
        )

    @cached_property
    def has_production_deployment(self) -> bool:
        for d in self.deployments:
            if d.status in ("RETIRED",) or d.lifecycle_state in ("RETIRED", "DRAFT"):
                continue
            if d.environment == "PRODUCTION" or (
                d.environment_id is not None and d.environment_id in self._production_env_ids
            ):
                return True
        return False

    # --- executions -------------------------------------------------- #
    @cached_property
    def _exec_stats(self) -> tuple[int, datetime | None, datetime | None]:
        row = self.db.execute(
            select(
                func.count(AgentExecution.id),
                func.max(AgentExecution.created_at),
                func.min(AgentExecution.created_at),
            ).where(
                AgentExecution.organization_id == self.organization_id,
                AgentExecution.agent_id == self.agent.id,
            )
        ).one()
        return int(row[0] or 0), row[1], row[2]

    @property
    def total_execution_count(self) -> int:
        return self._exec_stats[0]

    @property
    def last_execution_at(self) -> datetime | None:
        return self._exec_stats[1]

    @property
    def first_execution_at(self) -> datetime | None:
        return self._exec_stats[2]

    def executions_since(self, since: datetime) -> int:
        return int(
            self.db.execute(
                select(func.count(AgentExecution.id)).where(
                    AgentExecution.organization_id == self.organization_id,
                    AgentExecution.agent_id == self.agent.id,
                    AgentExecution.created_at >= since,
                )
            ).scalar()
            or 0
        )

    def executions_in_production(self) -> int:
        return int(
            self.db.execute(
                select(func.count(AgentExecution.id))
                .join(AgentDeployment, AgentDeployment.id == AgentExecution.deployment_id)
                .where(
                    AgentExecution.organization_id == self.organization_id,
                    AgentExecution.agent_id == self.agent.id,
                    (AgentDeployment.environment == "PRODUCTION")
                    | (AgentDeployment.environment_id.in_(self._production_env_ids)),
                )
            ).scalar()
            or 0
        )

    # --- governance / SLO ------------------------------------------ #
    @cached_property
    def governance_policies(self) -> list[RuntimeGovernancePolicy]:
        env_ids = [d.environment_id for d in self.deployments if d.environment_id]
        stmt = select(RuntimeGovernancePolicy).where(
            RuntimeGovernancePolicy.enabled.is_(True),
            (RuntimeGovernancePolicy.organization_id == self.organization_id)
            | (RuntimeGovernancePolicy.organization_id.is_(None)),
        )
        rows = list(self.db.execute(stmt).scalars())
        # applicable = platform/org default, or scoped to this agent, or to an
        # environment this agent is deployed to.
        out = []
        for p in rows:
            if p.agent_id is not None and p.agent_id != self.agent.id:
                continue
            if p.environment_id is not None and p.environment_id not in env_ids:
                continue
            out.append(p)
        return out

    @cached_property
    def slos(self) -> list[SLODefinition]:
        return list(
            self.db.execute(
                select(SLODefinition).where(
                    SLODefinition.organization_id == self.organization_id,
                    SLODefinition.enabled.is_(True),
                    (SLODefinition.scope_type == "ORGANIZATION")
                    | (
                        (SLODefinition.scope_type == "AGENT")
                        & (SLODefinition.scope_id == self.agent.id)
                    ),
                )
            ).scalars()
        )

    # --- dependency graph (5.4) ----------------------------------- #
    @cached_property
    def dependency_edges(self) -> list[ControlGraphEdge]:
        return list(
            self.db.execute(
                select(ControlGraphEdge).where(
                    ControlGraphEdge.organization_id == self.organization_id,
                    ControlGraphEdge.source_type == "AGENT",
                    ControlGraphEdge.source_id == self.agent.id,
                    ControlGraphEdge.edge_type.in_(DEPENDENCY_EDGE_TYPES),
                    ControlGraphEdge.revoked_at.is_(None),
                )
            ).scalars()
        )

    @cached_property
    def has_any_dependency_evidence(self) -> bool:
        return bool(self.dependency_edges)

    @cached_property
    def mcp_dependencies(self) -> list[tuple[ControlGraphEdge, McpServer]]:
        out: list[tuple[ControlGraphEdge, McpServer]] = []
        for e in self.dependency_edges:
            if e.edge_type != "DEPENDS_ON_MCP_SERVER":
                continue
            server = self.db.get(McpServer, e.target_id)
            if server is not None and server.organization_id == self.organization_id:
                out.append((e, server))
        return out

    @cached_property
    def tool_dependency_count(self) -> int:
        return len({e.target_id for e in self.dependency_edges if e.edge_type == "DEPENDS_ON_TOOL"})

    @cached_property
    def agent_tools(self) -> list[AgentTool]:
        return list(
            self.db.execute(
                select(AgentTool).where(AgentTool.agent_id == self.agent.id)
            ).scalars()
        )

    @cached_property
    def published_model(self) -> dict | None:
        row = self.db.execute(
            select(AgentVersion.model_configuration)
            .where(AgentVersion.agent_id == self.agent.id, AgentVersion.status == "PUBLISHED")
            .order_by(AgentVersion.version.desc())
            .limit(1)
        ).first()
        return row[0] if row and isinstance(row[0], dict) else None

    def reachable_sensitive_resources(self, kinds: list[str]) -> list[dict]:
        """RESOURCE nodes this agent can reach through its dependency edges
        whose ``resource_type`` is in ``kinds`` -- per-hop tenant-bounded
        (reuses the 5.3/5.4 ``traverse``). Returns [] when the agent has no
        dependency edges at all -- callers treat that as INSUFFICIENT_DATA,
        not CLEAR."""
        from app.graph.traversal import traverse

        reached = traverse(
            self.db,
            self.organization_id,
            start_type="AGENT",
            start_id=self.agent.id,
            edge_types=list(DEPENDENCY_EDGE_TYPES),
            direction="out",
            max_depth=8,
        )
        resource_ids = [n.node_id for n in reached if n.node_type == "RESOURCE"]
        if not resource_ids:
            return []
        rows = self.db.execute(
            text(
                "SELECT id, COALESCE(name, resource_type), resource_type FROM resources "
                "WHERE organization_id = :org AND id = ANY(CAST(:ids AS uuid[])) "
                "AND resource_type = ANY(:kinds)"
            ),
            {
                "org": str(self.organization_id),
                "ids": [str(r) for r in resource_ids],
                "kinds": list(kinds),
            },
        ).all()
        return [{"resource_id": str(r[0]), "label": r[1], "kind": r[2]} for r in rows]


# --------------------------------------------------------------------------- #
# The rules
# --------------------------------------------------------------------------- #
def _rule_no_accountable_owner(ctx: PostureContext, params: dict) -> list[RuleOutcome]:
    if ctx.has_accountable_owner:
        return [RuleOutcome("CLEAR")]
    return [
        RuleOutcome(
            "FINDING",
            reason=(
                "The agent has no business, technical or compliance owner recorded "
                "(agents.owner_id / technical_owner_id / compliance_owner_id all null)."
            ),
            remediation="Assign an accountable owner via the agent registry (ownership tab).",
            evidence={"refs": [{"table": "agents", "id": str(ctx.agent.id)}],
                      "owner_id": None, "technical_owner_id": None, "compliance_owner_id": None},
        )
    ]


def _rule_unowned_with_production_access(ctx: PostureContext, params: dict) -> list[RuleOutcome]:
    if ctx.has_accountable_owner:
        return [RuleOutcome("CLEAR")]
    if not (ctx.has_production_deployment or ctx.executions_in_production() > 0):
        return [RuleOutcome("CLEAR")]
    return [
        RuleOutcome(
            "FINDING",
            reason=(
                "The agent has production activity (a production deployment or "
                "production executions) but no accountable owner."
            ),
            remediation="Assign an owner and confirm the agent should be in production.",
            evidence={
                "refs": [{"table": "agents", "id": str(ctx.agent.id)}],
                "has_production_deployment": ctx.has_production_deployment,
                "production_executions": ctx.executions_in_production(),
            },
        )
    ]


def _rule_discovered_outside_lifecycle(ctx: PostureContext, params: dict) -> list[RuleOutcome]:
    if ctx.agent.control_state == "DISCOVERED":
        return [
            RuleOutcome(
                "FINDING",
                reason=(
                    "The agent is at control_state=DISCOVERED - it was observed by "
                    "discovery (Phase 5.2) and never claimed or brought under governance."
                ),
                remediation="Claim the agent and move it through the registration lifecycle, or retire it.",
                evidence={
                    "refs": [{"table": "agents", "id": str(ctx.agent.id)}],
                    "control_state": ctx.agent.control_state,
                    "discovery_source_ref": ctx.agent.discovery_source_ref,
                },
            )
        ]
    return [RuleOutcome("CLEAR")]


def _rule_unmanaged_external_agent(ctx: PostureContext, params: dict) -> list[RuleOutcome]:
    if ctx.agent.origin_category == "EXTERNAL" and ctx.agent.control_state in ("DISCOVERED", "CLAIMED"):
        return [
            RuleOutcome(
                "FINDING",
                reason=(
                    f"The agent originates outside ACT (origin_category=EXTERNAL) and is "
                    f"only at control_state={ctx.agent.control_state}, not GOVERNED."
                ),
                remediation="Bring the external agent under governance or record an explicit exception.",
                evidence={
                    "refs": [{"table": "agents", "id": str(ctx.agent.id)}],
                    "origin_category": ctx.agent.origin_category,
                    "origin_provider": ctx.agent.origin_provider,
                    "control_state": ctx.agent.control_state,
                },
            )
        ]
    return [RuleOutcome("CLEAR")]


def _rule_production_activity_without_governance(ctx: PostureContext, params: dict) -> list[RuleOutcome]:
    in_prod = ctx.has_production_deployment or ctx.executions_in_production() > 0
    if not in_prod:
        return [RuleOutcome("CLEAR")]
    if ctx.agent.control_state == "GOVERNED" and ctx.governance_policies:
        return [RuleOutcome("CLEAR")]
    return [
        RuleOutcome(
            "FINDING",
            reason=(
                f"The agent has production activity but is not enrolled in governance "
                f"(control_state={ctx.agent.control_state}, "
                f"{len(ctx.governance_policies)} applicable runtime governance policies)."
            ),
            remediation="Move the agent to control_state=GOVERNED and attach a runtime governance policy.",
            evidence={
                "refs": [{"table": "agents", "id": str(ctx.agent.id)}],
                "control_state": ctx.agent.control_state,
                "applicable_policies": len(ctx.governance_policies),
                "has_production_deployment": ctx.has_production_deployment,
            },
        )
    ]


def _rule_missing_runtime_governance_policy(ctx: PostureContext, params: dict) -> list[RuleOutcome]:
    if ctx.agent.lifecycle_status not in ("ACTIVE",):
        return [RuleOutcome("CLEAR")]
    if ctx.governance_policies:
        return [RuleOutcome("CLEAR")]
    severity = "HIGH" if ctx.agent.control_state == "GOVERNED" else "WARNING"
    reason = (
        "The agent is ACTIVE but no enabled runtime governance policy applies to it "
        "(no platform default, org, environment or agent-scoped policy)."
    )
    if severity == "HIGH":
        reason += " control_state=GOVERNED implies it should be governed - this is a mismatch."
    return [
        RuleOutcome(
            "FINDING",
            severity=severity,
            reason=reason,
            remediation="Create or scope a runtime governance policy that covers this agent.",
            evidence={
                "refs": [{"table": "agents", "id": str(ctx.agent.id)}],
                "control_state": ctx.agent.control_state,
                "lifecycle_status": ctx.agent.lifecycle_status,
            },
        )
    ]


def _rule_missing_slo(ctx: PostureContext, params: dict) -> list[RuleOutcome]:
    if ctx.agent.lifecycle_status != "ACTIVE" or not ctx.has_production_deployment:
        return [RuleOutcome("CLEAR")]
    if ctx.slos:
        return [RuleOutcome("CLEAR")]
    return [
        RuleOutcome(
            "FINDING",
            reason="The agent is ACTIVE in production but no SLO (agent- or org-scoped) covers it.",
            remediation="Define at least one SLO (e.g. success_rate) scoped to the agent or the organization.",
            evidence={"refs": [{"table": "agents", "id": str(ctx.agent.id)}]},
        )
    ]


def _rule_expired_credential_still_active(ctx: PostureContext, params: dict) -> list[RuleOutcome]:
    now = _now()
    outcomes: list[RuleOutcome] = []
    for k in ctx.active_api_keys:
        if k.expires_at is not None and k.expires_at < now:
            outcomes.append(
                RuleOutcome(
                    "FINDING",
                    dedup_suffix=str(k.id),
                    reason=f"API key {k.key_prefix}… is still ACTIVE but expired at {k.expires_at.isoformat()}.",
                    remediation="Rotate or revoke the expired key.",
                    evidence={"refs": [{"table": "agent_api_keys", "id": str(k.id),
                                        "key_prefix": k.key_prefix}],
                              "expires_at": k.expires_at.isoformat()},
                )
            )
    return outcomes or [RuleOutcome("CLEAR")]


def _rule_stale_credential(ctx: PostureContext, params: dict) -> list[RuleOutcome]:
    max_age_days = int(params.get("max_age_days", 90))
    cutoff = _now() - timedelta(days=max_age_days)
    outcomes: list[RuleOutcome] = []
    for k in ctx.active_api_keys:
        if k.expires_at is not None and k.expires_at < _now():
            continue  # the expired-credential rule owns that one
        reference = k.last_used_at or k.created_at
        if reference is not None and reference < cutoff:
            last = "never used" if k.last_used_at is None else f"last used {k.last_used_at.isoformat()}"
            outcomes.append(
                RuleOutcome(
                    "FINDING",
                    dedup_suffix=str(k.id),
                    reason=(f"API key {k.key_prefix}… is ACTIVE and stale ({last}; "
                            f"older than the {max_age_days}-day threshold)."),
                    remediation="Rotate the key, or revoke it if the agent no longer needs one.",
                    evidence={"refs": [{"table": "agent_api_keys", "id": str(k.id),
                                        "key_prefix": k.key_prefix}],
                              "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                              "threshold_days": max_age_days},
                )
            )
    return outcomes or [RuleOutcome("CLEAR")]


def _rule_dormant_agent_with_active_credential(ctx: PostureContext, params: dict) -> list[RuleOutcome]:
    dormant_days = int(params.get("dormant_days", 60))
    if not ctx.active_api_keys:
        return [RuleOutcome("CLEAR")]
    cutoff = _now() - timedelta(days=dormant_days)
    if ctx.total_execution_count == 0 and (
        ctx.agent.created_at is None or ctx.agent.created_at > cutoff
    ):
        return [
            RuleOutcome(
                "INSUFFICIENT_DATA",
                reason=(f"The agent has no executions and is younger than {dormant_days} days; "
                        "not enough history to call it dormant."),
            )
        ]
    if ctx.last_execution_at is not None and ctx.last_execution_at >= cutoff:
        return [RuleOutcome("CLEAR")]
    when = ("never executed" if ctx.last_execution_at is None
            else f"last executed {ctx.last_execution_at.isoformat()}")
    return [
        RuleOutcome(
            "FINDING",
            reason=(f"The agent is dormant ({when}, threshold {dormant_days} days) but holds "
                    f"{len(ctx.active_api_keys)} ACTIVE API key(s)."),
            remediation="Revoke the agent's credentials while it is dormant, or retire the agent.",
            evidence={
                "refs": [{"table": "agents", "id": str(ctx.agent.id)}]
                + [{"table": "agent_api_keys", "id": str(k.id)} for k in ctx.active_api_keys],
                "last_execution_at": ctx.last_execution_at.isoformat() if ctx.last_execution_at else None,
                "threshold_days": dormant_days,
            },
        )
    ]


def _rule_unknown_provenance(ctx: PostureContext, params: dict) -> list[RuleOutcome]:
    a = ctx.agent
    unknown = a.origin_category == "UNKNOWN" or (
        a.origin_category == "EXTERNAL"
        and (not a.origin_provider or a.origin_provider.upper() in ("UNKNOWN", ""))
    )
    if not unknown:
        return [RuleOutcome("CLEAR")]
    return [
        RuleOutcome(
            "FINDING",
            reason=(f"The agent's provenance is unknown (origin_category={a.origin_category}, "
                    f"origin_provider={a.origin_provider!r})."),
            remediation="Establish and record where the agent came from, or retire it.",
            evidence={"refs": [{"table": "agents", "id": str(a.id)}],
                      "origin_category": a.origin_category, "origin_provider": a.origin_provider},
        )
    ]


def _rule_unapproved_mcp_dependency(ctx: PostureContext, params: dict) -> list[RuleOutcome]:
    outcomes: list[RuleOutcome] = []
    for edge, server in ctx.mcp_dependencies:
        if server.trust_status == "APPROVED":
            continue
        outcomes.append(
            RuleOutcome(
                "FINDING",
                dedup_suffix=str(server.id),
                reason=(f"The agent depends on MCP server {server.name!r} whose trust status is "
                        f"{server.trust_status} (provenance {server.provenance}) - unknown != safe."),
                remediation=("Review and approve the MCP server, remove the dependency, or record "
                             "an explicit exception."),
                evidence={
                    "refs": [
                        {"table": "control_graph_edges", "id": str(edge.id), "edge_type": edge.edge_type},
                        {"table": "mcp_servers", "id": str(server.id), "name": server.name},
                    ],
                    "trust_status": server.trust_status,
                    "provenance": server.provenance,
                    "dependency_evidence": dict(edge.evidence or {}),
                },
            )
        )
    return outcomes or [RuleOutcome("CLEAR")]


def _rule_dangerous_dependency(ctx: PostureContext, params: dict) -> list[RuleOutcome]:
    kinds = list(params.get("sensitive_resource_kinds",
                            ["payroll", "customer_financial", "pii", "secrets"]))
    if not ctx.has_any_dependency_evidence:
        return [
            RuleOutcome(
                "INSUFFICIENT_DATA",
                reason=("No dependency edges are recorded for this agent; its blast radius to "
                        "sensitive resources cannot be evaluated. Run a dependency rebuild "
                        "(POST /graph/agents/{id}/dependencies/rebuild). Absence is not safety."),
            )
        ]
    reached = ctx.reachable_sensitive_resources(kinds)
    if not reached:
        return [RuleOutcome("CLEAR")]
    return [
        RuleOutcome(
            "FINDING",
            reason=(f"The agent can reach {len(reached)} sensitive resource(s) "
                    f"({', '.join(sorted({r['kind'] for r in reached}))}) through its dependency graph."),
            remediation=("Confirm the agent should reach these resources; tighten the tool / "
                         "credential scope or add a governance control if not."),
            evidence={
                "refs": [{"table": "resources", "id": r["resource_id"], "kind": r["kind"]}
                         for r in reached],
                "sensitive_kinds": kinds,
                "reached": reached,
            },
        )
    ]


def _rule_prohibited_model(ctx: PostureContext, params: dict) -> list[RuleOutcome]:
    prohibited = {str(m).lower() for m in params.get("prohibited_models", [])}
    prohibited_providers = {str(p).lower() for p in params.get("prohibited_providers", [])}
    if not prohibited and not prohibited_providers:
        return [RuleOutcome("CLEAR")]  # nothing configured to prohibit
    model_cfg = ctx.published_model
    if model_cfg is None:
        return [RuleOutcome("CLEAR")]
    model = str(model_cfg.get("model") or "").lower()
    provider = str(model_cfg.get("provider") or "").lower()
    if model in prohibited or provider in prohibited_providers:
        return [
            RuleOutcome(
                "FINDING",
                reason=(f"The agent's published version uses a prohibited model "
                        f"(provider={provider}, model={model})."),
                remediation="Move the agent to an approved model and publish a new version.",
                evidence={"refs": [{"table": "agent_versions", "id": str(ctx.agent.id)}],
                          "provider": provider, "model": model,
                          "prohibited_models": sorted(prohibited),
                          "prohibited_providers": sorted(prohibited_providers)},
            )
        ]
    return [RuleOutcome("CLEAR")]


def _rule_unapproved_tool(ctx: PostureContext, params: dict) -> list[RuleOutcome]:
    if ctx.agent.lifecycle_status != "ACTIVE":
        return [RuleOutcome("CLEAR")]
    outcomes: list[RuleOutcome] = []
    for at in ctx.agent_tools:
        if at.status != "APPROVED":
            outcomes.append(
                RuleOutcome(
                    "FINDING",
                    dedup_suffix=str(at.id),
                    severity="WARNING",
                    reason=(f"The ACTIVE agent has a tool assignment in status {at.status} "
                            f"(not APPROVED)."),
                    remediation="Approve the tool grant through the tool-governance workflow, or remove it.",
                    evidence={"refs": [{"table": "agent_tools", "id": str(at.id),
                                        "tool_id": str(at.tool_id)}],
                              "assignment_status": at.status},
                )
            )
    return outcomes or [RuleOutcome("CLEAR")]


def _rule_excessive_tool_scope(ctx: PostureContext, params: dict) -> list[RuleOutcome]:
    threshold = int(params.get("max_tools", 15))
    count = ctx.tool_dependency_count
    if count <= threshold:
        return [RuleOutcome("CLEAR")]
    return [
        RuleOutcome(
            "FINDING",
            reason=(f"The agent depends on {count} tools, above the scope threshold of {threshold} - "
                    "a broad tool surface widens its blast radius if compromised."),
            remediation="Review the agent's tool dependencies and remove any it does not need.",
            evidence={"refs": [{"table": "control_graph_edges", "id": str(ctx.agent.id)}],
                      "tool_count": count, "threshold": threshold},
        )
    ]


# --------------------------------------------------------------------------- #
# The catalog
# --------------------------------------------------------------------------- #
RULES: tuple[PostureRule, ...] = (
    PostureRule("no_accountable_owner", "OWNERSHIP.ACCOUNTABLE_OWNER", "CRITICAL", False, "1", {},
                "The agent has no business/technical/compliance owner.", _rule_no_accountable_owner),
    PostureRule("unowned_with_production_access", "OWNERSHIP.PRODUCTION_ACCOUNTABILITY", "HIGH", True, "1", {},
                "An unowned agent has production activity.", _rule_unowned_with_production_access),
    PostureRule("discovered_outside_lifecycle", "LIFECYCLE.GOVERNED_ONBOARDING", "HIGH", True, "1", {},
                "The agent is at control_state=DISCOVERED - never brought under governance.",
                _rule_discovered_outside_lifecycle),
    PostureRule("unmanaged_external_agent", "LIFECYCLE.EXTERNAL_ENROLLMENT", "HIGH", True, "1", {},
                "An external-origin agent is not GOVERNED.", _rule_unmanaged_external_agent),
    PostureRule("production_activity_without_governance", "GOVERNANCE.PRODUCTION_ENROLLMENT", "HIGH", True, "1", {},
                "The agent has production activity without governance enrollment.",
                _rule_production_activity_without_governance),
    PostureRule("missing_runtime_governance_policy", "GOVERNANCE.POLICY_COVERAGE", "WARNING", False, "1", {},
                "No enabled runtime governance policy applies to an ACTIVE agent.",
                _rule_missing_runtime_governance_policy),
    PostureRule("missing_slo", "RELIABILITY.SLO_COVERAGE", "WARNING", False, "1", {},
                "An ACTIVE production agent has no SLO.", _rule_missing_slo),
    PostureRule("expired_credential_still_active", "CREDENTIAL.EXPIRY", "CRITICAL", False, "1", {},
                "An ACTIVE API key is past its expiry.", _rule_expired_credential_still_active),
    PostureRule("stale_credential", "CREDENTIAL.ROTATION", "HIGH", False, "1", {"max_age_days": 90},
                "An ACTIVE API key has not been used within the rotation window.", _rule_stale_credential),
    PostureRule("dormant_agent_with_active_credential", "CREDENTIAL.LEAST_STANDING", "HIGH", False, "1",
                {"dormant_days": 60},
                "A dormant agent still holds active credentials.", _rule_dormant_agent_with_active_credential),
    PostureRule("unknown_provenance", "PROVENANCE.ESTABLISHED_ORIGIN", "WARNING", False, "1", {},
                "The agent's provenance is unknown.", _rule_unknown_provenance),
    PostureRule("unapproved_mcp_dependency", "SUPPLY_CHAIN.MCP_TRUST", "HIGH", False, "1", {},
                "The agent depends on an unapproved/unknown-provenance MCP server.",
                _rule_unapproved_mcp_dependency),
    PostureRule("dangerous_dependency", "BLAST_RADIUS.SENSITIVE_RESOURCE", "HIGH", False, "1",
                {"sensitive_resource_kinds": ["payroll", "customer_financial", "pii", "secrets"]},
                "The agent can reach a sensitive resource through its dependency graph.",
                _rule_dangerous_dependency),
    PostureRule("prohibited_model", "MODEL.APPROVED_MODELS", "HIGH", False, "1",
                {"prohibited_models": [], "prohibited_providers": []},
                "The agent uses a model on the organization's prohibited list.", _rule_prohibited_model),
    PostureRule("unapproved_tool", "TOOL.APPROVED_GRANTS", "WARNING", False, "1", {},
                "An ACTIVE agent has an un-approved tool assignment.", _rule_unapproved_tool),
    PostureRule("excessive_tool_scope", "TOOL.LEAST_PRIVILEGE", "WARNING", False, "1", {"max_tools": 15},
                "The agent depends on an excessive number of tools.", _rule_excessive_tool_scope),
)

RULES_BY_ID: dict[str, PostureRule] = {r.id: r for r in RULES}

#: The shadow-class rules. "Shadow agents" = agents with an open finding whose
#: rule_id is in this set (``app.posture.shadow``). Derived, disputable, never
#: a boolean column.
SHADOW_RULE_IDS: frozenset[str] = frozenset(r.id for r in RULES if r.shadow_class)


# --------------------------------------------------------------------------- #
# Evidence-gap note (SRS §2 mandatory report #3 / working-constraint):
# "excessive privilege" as an RBAC concept is NOT delivered as a rule - an
# agent does not hold RBAC role assignments (roles bind to users), and 5.3's
# delegation edges are human<->human, so an "excessive delegated authority"
# rule would have no evidence to read. The privilege-scope concern is covered
# instead by `excessive_tool_scope` (dependency-graph derived) and
# `unapproved_tool`. This gap is recorded here and in docs/posture/rules.md
# rather than fabricated (unknown != safe, but also != a fabricated finding).
# --------------------------------------------------------------------------- #

__all__ = [
    "POSTURE_RULESET_VERSION",
    "RuleOutcome",
    "PostureRule",
    "PostureContext",
    "RULES",
    "RULES_BY_ID",
    "SHADOW_RULE_IDS",
]
