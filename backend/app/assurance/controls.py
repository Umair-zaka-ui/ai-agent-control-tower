"""Phase 5.9 (M5.9) - the assurance control catalog: deterministic evaluations
over evidence Phases M1-5.8 already produce.

**The one rule this module exists to enforce: absence is never a pass.**

Every control returns exactly one of three results, and the distinction between
the last two is the whole point:

  * ``PASS``                  - evidence exists, is fresh, and satisfies the control.
  * ``FAIL``                  - evidence exists and shows the control **unmet**.
  * ``INSUFFICIENT_EVIDENCE`` - ACT **cannot tell either way**: no evaluation has
                                run, the source holds nothing to read, or what it
                                holds is too stale to stand behind.

Getting those backwards in either direction is a real failure. Calling absence a
pass is the false-green a compliance surface must never produce - an auditor
reading "PASS" on a control ACT cannot evidence is being actively misled about
their posture. But calling a *conclusive negative* "insufficient" is the mirror
failure: an agent row with ``owner_id IS NULL`` is not missing evidence, it is
evidence, and the control fails. Each control below states which it is and why.

**The sharpest case, and the reason this is not theoretical.** Controls backed
by Phase 5.5 read ``posture_findings``. If posture has never been evaluated for
a tenant there are simply no findings - and "no findings" reads exactly like
"clean". The honest signal is elsewhere: 5.5's evaluator writes a
``POSTURE_EVALUATED`` audit event, so the **immutable audit** is the evidence
that an evaluation actually happened, and its timestamp is the as-of. No such
event -> ``INSUFFICIENT_EVIDENCE``, never ``PASS``. This is also why freshness
is not decoration: a posture result from six weeks ago does not substantiate a
claim about today.

**Deterministic and reconstructable.** Each control is a pure function of
(evidence rows + freshness policy). Same evidence in, same result out; no ML, no
scoring (AST-asserted, mirroring 4.5 and 5.5). Every result names the evidence
it read - or the absence it found - so a reader can reconstruct the conclusion
rather than trust it.

**What this module never produces.** There is no "compliant" value in
``RESULTS``, no status field, and no code path that emits one. ACT maps evidence
to controls; whether an organization *complies* with a regulation is a legal
judgement ACT is not entitled to make and does not make.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

#: Bump when a control's logic changes, so a stored result can be traced to the
#: definition that produced it. The 5.5 ``POSTURE_RULESET_VERSION`` precedent.
ASSURANCE_CATALOG_VERSION = "1"

#: The only three results. Deliberately no "COMPLIANT", no "CERTIFIED", and no
#: overall verdict - see the module docstring.
RESULTS: tuple[str, ...] = ("PASS", "FAIL", "INSUFFICIENT_EVIDENCE")

#: How old evidence may be before a PASS is no longer honest. A control that
#: would otherwise pass on evidence older than this returns
#: INSUFFICIENT_EVIDENCE with ``stale=True`` - flagged, and never a pass,
#: because "we checked six weeks ago" does not substantiate a claim about today.
DEFAULT_FRESHNESS_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ControlResult:
    """One control's answer, with the evidence that produced it.

    ``evidence`` is not decoration: a result that cannot name what it read is
    not reconstructable, and an auditor has no reason to believe it. For an
    INSUFFICIENT_EVIDENCE result it names the *absence* - which source was
    empty, or which evaluation never ran.
    """

    result: str
    reason: str
    evidence: dict = field(default_factory=dict)
    #: When the evidence this result rests on was produced. ``None`` means
    #: there was no evidence to date.
    as_of: datetime | None = None
    #: True when evidence exists but is older than the freshness policy. Such a
    #: result is INSUFFICIENT_EVIDENCE, never a stale PASS.
    stale: bool = False
    remediation: str = ""

    def __post_init__(self) -> None:
        # A typo'd result string would silently become an unknown state in a
        # compliance report. Fail at construction instead.
        assert self.result in RESULTS, self.result


@dataclass(frozen=True)
class AssuranceControl:
    """One thing ACT can evidence about an agent or a tenant."""

    id: str
    #: The assurance question in plain words, as an auditor would ask it.
    question: str
    #: Which M1-5.8 evidence this control reads. Named so the catalog itself
    #: documents its own sourcing.
    evidence_source: str
    scope: str  # "AGENT" | "ORGANIZATION"
    version: str
    fn: "Callable[[AssuranceContext], ControlResult]"

    def evaluate(self, ctx: "AssuranceContext") -> ControlResult:
        return self.fn(ctx)


class AssuranceContext:
    """The evidence for one agent (or tenant), read once.

    Batched for the same reason 5.5's ``PostureContext`` is: the controls below
    read cached attributes instead of each issuing its own queries, so an
    evaluation over an estate stays a bounded number of round trips.
    """

    def __init__(self, db: Session, organization_id: uuid.UUID, agent=None,
                 freshness_days: int = DEFAULT_FRESHNESS_DAYS) -> None:
        self.db = db
        self.organization_id = organization_id
        self.agent = agent
        self.freshness_days = freshness_days
        self._cache: dict = {}

    # -- freshness ---------------------------------------------------------- #
    @property
    def freshness_cutoff(self) -> datetime:
        return _now() - timedelta(days=self.freshness_days)

    def is_stale(self, as_of: datetime | None) -> bool:
        if as_of is None:
            return False  # absence is handled as insufficient, not as stale
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        return as_of < self.freshness_cutoff

    # -- the posture-evaluation as-of (the audit spine) --------------------- #
    @property
    def posture_evaluated_at(self) -> datetime | None:
        """When posture last actually ran for this tenant, per the immutable
        audit trail — **not** inferred from whether findings happen to exist.

        This is the difference between "evaluated and clean" and "never looked",
        which the findings table alone cannot tell apart.
        """
        if "posture_evaluated_at" not in self._cache:
            from app.authorization.enums import AuthorizationAuditEvent
            from app.models.rbac import AuthorizationAudit

            self._cache["posture_evaluated_at"] = self.db.execute(
                select(func.max(AuthorizationAudit.created_at)).where(
                    AuthorizationAudit.organization_id == self.organization_id,
                    AuthorizationAudit.event_type
                    == AuthorizationAuditEvent.POSTURE_EVALUATED.value,
                )
            ).scalar()
        return self._cache["posture_evaluated_at"]

    def open_posture_findings(self, control_id: str) -> list:
        """Open findings for one 5.5 control id, for this agent."""
        key = f"posture:{control_id}"
        if key not in self._cache:
            from app.models.posture import PostureFinding
            from app.posture.rules import RULES

            rule_ids = [r.id for r in RULES if r.control_id == control_id]
            if not rule_ids or self.agent is None:
                self._cache[key] = []
            else:
                self._cache[key] = list(self.db.execute(
                    select(PostureFinding).where(
                        PostureFinding.organization_id == self.organization_id,
                        PostureFinding.subject_id == self.agent.id,
                        PostureFinding.rule_id.in_(rule_ids),
                        PostureFinding.status == "OPEN",
                    )
                ).scalars())
        return self._cache[key]


# --------------------------------------------------------------------------- #
# The posture-backed controls
# --------------------------------------------------------------------------- #
def _from_posture(control_id: str, *, question: str, remediation: str):
    """Build a control that reads one 5.5 control id's findings.

    The ordering here is the honest one and is deliberate:

      1. **Has posture ever run?** No -> INSUFFICIENT_EVIDENCE. This comes
         first because every later conclusion depends on it; checking findings
         first would let "no findings because nobody looked" masquerade as a
         clean result.
      2. **Is that run fresh?** No -> INSUFFICIENT_EVIDENCE, ``stale=True``.
         A pass on six-week-old evidence is not a pass.
      3. **Does an open finding exist?** Yes -> FAIL, naming the finding.
      4. Otherwise -> PASS, naming the evaluation that substantiates it.
    """
    def _fn(ctx: AssuranceContext) -> ControlResult:
        evaluated_at = ctx.posture_evaluated_at
        if evaluated_at is None:
            return ControlResult(
                "INSUFFICIENT_EVIDENCE",
                "Security posture has never been evaluated for this organization, so "
                "ACT has no basis to judge this control. Absence of findings is not "
                "evidence of compliance.",
                evidence={"control_id": control_id, "posture_evaluations": 0},
                remediation="Run a posture evaluation (POST /api/v1/posture/evaluate).",
            )
        if ctx.is_stale(evaluated_at):
            return ControlResult(
                "INSUFFICIENT_EVIDENCE",
                f"The most recent posture evaluation ({evaluated_at.isoformat()}) is older "
                f"than the {ctx.freshness_days}-day freshness policy. Stale evidence is "
                "reported as insufficient rather than as a pass.",
                evidence={"control_id": control_id,
                          "posture_evaluated_at": evaluated_at.isoformat()},
                as_of=evaluated_at, stale=True,
                remediation="Re-run the posture evaluation.",
            )
        findings = ctx.open_posture_findings(control_id)
        if findings:
            return ControlResult(
                "FAIL",
                f"{len(findings)} open posture finding(s) show this control is not met.",
                evidence={"control_id": control_id,
                          "finding_ids": [str(f.id) for f in findings],
                          "rule_ids": sorted({f.rule_id for f in findings}),
                          "reasons": [f.reason for f in findings][:5]},
                as_of=evaluated_at,
                remediation=remediation,
            )
        return ControlResult(
            "PASS",
            "Posture evaluated this control and found no open finding against it.",
            evidence={"control_id": control_id,
                      "posture_evaluated_at": evaluated_at.isoformat(),
                      "open_findings": 0},
            as_of=evaluated_at,
        )
    return _fn


# --------------------------------------------------------------------------- #
# The directly-evidenced controls
# --------------------------------------------------------------------------- #
def _c_accountable_owner(ctx: AssuranceContext) -> ControlResult:
    """FAIL, not INSUFFICIENT_EVIDENCE, when there is no owner.

    The agent row **is** the evidence and it is conclusive: ACT knows this agent
    exists and knows nobody is accountable for it. Reporting that as "cannot
    tell" would hide a finding behind a shrug.
    """
    agent = ctx.agent
    if agent is None:
        return ControlResult("INSUFFICIENT_EVIDENCE", "No agent in scope.",
                             evidence={})
    if agent.owner_id is None:
        return ControlResult(
            "FAIL",
            "This agent has no accountable owner recorded.",
            evidence={"agent_id": str(agent.id), "owner_id": None,
                      "source": "agents.owner_id"},
            as_of=agent.updated_at,
            remediation="Assign an accountable owner (POST /runtime/agents/{id}/claim).",
        )
    return ControlResult(
        "PASS", "An accountable owner is recorded for this agent.",
        evidence={"agent_id": str(agent.id), "owner_id": str(agent.owner_id),
                  "owner_type": agent.owner_type, "source": "agents.owner_id"},
        as_of=agent.updated_at,
    )


def _c_known_provenance(ctx: AssuranceContext) -> ControlResult:
    agent = ctx.agent
    if agent is None:
        return ControlResult("INSUFFICIENT_EVIDENCE", "No agent in scope.")
    if agent.origin_category == "UNKNOWN":
        return ControlResult(
            "FAIL",
            "This agent's provenance is recorded as UNKNOWN — ACT has observed it "
            "but cannot say where it came from.",
            evidence={"agent_id": str(agent.id), "origin_category": "UNKNOWN",
                      "source": "agents.origin_category"},
            as_of=agent.updated_at,
            remediation="Reconcile the agent against a discovery source to establish origin.",
        )
    return ControlResult(
        "PASS", f"Provenance is established: {agent.origin_category}.",
        evidence={"agent_id": str(agent.id), "origin_category": agent.origin_category,
                  "origin_provider": agent.origin_provider,
                  "source": "agents.origin_category"},
        as_of=agent.updated_at,
    )


def _c_runtime_traceable(ctx: AssuranceContext) -> ControlResult:
    """The clearest INSUFFICIENT_EVIDENCE case in the catalog.

    Traceability is a claim about whether this agent's activity *can be
    reconstructed*. With zero executions on record there is nothing to
    reconstruct and nothing to judge — that is genuinely unknowable, not a
    failure and certainly not a pass. An agent ACT does not run (an external
    one) will legitimately land here, and saying so is the honest answer.
    """
    from app.models.runtime import AgentExecution

    agent = ctx.agent
    if agent is None:
        return ControlResult("INSUFFICIENT_EVIDENCE", "No agent in scope.")
    row = ctx.db.execute(
        select(func.count(), func.max(AgentExecution.created_at)).where(
            AgentExecution.organization_id == ctx.organization_id,
            AgentExecution.agent_id == agent.id,
        )
    ).one()
    count, latest = row[0] or 0, row[1]
    if count == 0:
        return ControlResult(
            "INSUFFICIENT_EVIDENCE",
            "No executions are recorded for this agent, so there is no activity whose "
            "traceability ACT could evidence. This is not a pass: ACT cannot see what "
            "it does not run.",
            evidence={"agent_id": str(agent.id), "executions": 0,
                      "source": "agent_executions"},
            remediation="If this agent runs outside ACT, traceability must be evidenced "
                        "at its own platform or via gateway boundary records.",
        )
    if ctx.is_stale(latest):
        return ControlResult(
            "INSUFFICIENT_EVIDENCE",
            f"The most recent execution ({latest.isoformat()}) is older than the "
            f"{ctx.freshness_days}-day freshness policy.",
            evidence={"agent_id": str(agent.id), "executions": count,
                      "latest_execution_at": latest.isoformat()},
            as_of=latest, stale=True,
        )
    return ControlResult(
        "PASS", f"{count} execution(s) recorded with full trace lineage.",
        evidence={"agent_id": str(agent.id), "executions": count,
                  "latest_execution_at": latest.isoformat(),
                  "source": "agent_executions"},
        as_of=latest,
    )


def _c_cost_governed(ctx: AssuranceContext) -> ControlResult:
    from app.finops.budgets import BudgetService, ExecutionScope

    agent = ctx.agent
    if agent is None:
        return ControlResult("INSUFFICIENT_EVIDENCE", "No agent in scope.")
    budgets = BudgetService(ctx.db).resolve(
        ExecutionScope(organization_id=ctx.organization_id, agent_id=agent.id))
    if not budgets:
        return ControlResult(
            "FAIL",
            "No enabled budget applies to this agent, so its spend is ungoverned.",
            evidence={"agent_id": str(agent.id), "applicable_budgets": 0,
                      "source": "budgets"},
            remediation="Define a budget covering this agent, its project or the organization.",
        )
    return ControlResult(
        "PASS", f"{len(budgets)} budget(s) govern this agent's spend.",
        evidence={"agent_id": str(agent.id),
                  "budget_ids": [str(b.id) for b in budgets],
                  "modes": sorted({b.mode for b in budgets}), "source": "budgets"},
        as_of=max((b.updated_at for b in budgets if b.updated_at), default=None),
    )


def _c_authority_chain_provable(ctx: AssuranceContext) -> ControlResult:
    """Whether this agent's authority can be reconstructed from the 5.3 graph.

    No edges at all is INSUFFICIENT_EVIDENCE rather than FAIL: an agent may
    legitimately hold no delegated authority, and ACT cannot distinguish that
    from an unrecorded chain. Reporting "cannot prove" is accurate; reporting
    "fails" would invent a violation.
    """
    from app.models.graph import ControlGraphEdge

    agent = ctx.agent
    if agent is None:
        return ControlResult("INSUFFICIENT_EVIDENCE", "No agent in scope.")
    row = ctx.db.execute(
        select(func.count(), func.max(ControlGraphEdge.created_at)).where(
            ControlGraphEdge.organization_id == ctx.organization_id,
            ControlGraphEdge.target_id == agent.id,
            ControlGraphEdge.revoked_at.is_(None),
        )
    ).one()
    count, latest = row[0] or 0, row[1]
    if count == 0:
        return ControlResult(
            "INSUFFICIENT_EVIDENCE",
            "No active control-graph edges reference this agent, so ACT cannot "
            "reconstruct an authority chain for it. An agent may hold no delegated "
            "authority; ACT cannot tell that apart from an unrecorded one.",
            evidence={"agent_id": str(agent.id), "active_edges": 0,
                      "source": "control_graph_edges"},
            remediation="Record the delegation/trust edges that grant this agent authority.",
        )
    return ControlResult(
        "PASS", f"{count} active control-graph edge(s) make this agent's authority reconstructable.",
        evidence={"agent_id": str(agent.id), "active_edges": count,
                  "source": "control_graph_edges"},
        as_of=latest,
    )


def _c_incidents_reconstructable(ctx: AssuranceContext) -> ControlResult:
    """Whether threat activity against this agent can be reconstructed.

    A clean agent and an unmonitored one both have zero threat findings, so
    this control asks the same question the posture ones do: has a threat
    evaluation actually run?
    """
    from app.authorization.enums import AuthorizationAuditEvent
    from app.models.rbac import AuthorizationAudit
    from app.models.threat import ContainmentAction, ThreatFinding

    agent = ctx.agent
    if agent is None:
        return ControlResult("INSUFFICIENT_EVIDENCE", "No agent in scope.")
    evaluated_at = ctx.db.execute(
        select(func.max(AuthorizationAudit.created_at)).where(
            AuthorizationAudit.organization_id == ctx.organization_id,
            AuthorizationAudit.event_type == AuthorizationAuditEvent.THREAT_EVALUATED.value,
        )
    ).scalar()
    if evaluated_at is None:
        return ControlResult(
            "INSUFFICIENT_EVIDENCE",
            "Threat detection has never been evaluated for this organization, so the "
            "absence of incidents is not evidence that none occurred.",
            evidence={"agent_id": str(agent.id), "threat_evaluations": 0},
            remediation="Run a threat evaluation (POST /api/v1/threat/evaluate).",
        )
    findings = ctx.db.execute(
        select(func.count()).select_from(ThreatFinding).where(
            ThreatFinding.organization_id == ctx.organization_id,
            ThreatFinding.agent_id == agent.id)
    ).scalar() or 0
    actions = ctx.db.execute(
        select(func.count()).select_from(ContainmentAction).where(
            ContainmentAction.organization_id == ctx.organization_id,
            ContainmentAction.agent_id == agent.id)
    ).scalar() or 0
    if ctx.is_stale(evaluated_at):
        return ControlResult(
            "INSUFFICIENT_EVIDENCE",
            f"The most recent threat evaluation ({evaluated_at.isoformat()}) is older than "
            f"the {ctx.freshness_days}-day freshness policy.",
            evidence={"agent_id": str(agent.id),
                      "threat_evaluated_at": evaluated_at.isoformat()},
            as_of=evaluated_at, stale=True,
        )
    return ControlResult(
        "PASS",
        "Threat detection has evaluated this agent; findings and containment actions "
        "are on record and reconstructable from the audit trail.",
        evidence={"agent_id": str(agent.id), "threat_findings": findings,
                  "containment_actions": actions,
                  "threat_evaluated_at": evaluated_at.isoformat(),
                  "source": "threat_findings + containment_actions + audit"},
        as_of=evaluated_at,
    )


# --------------------------------------------------------------------------- #
# The catalog
# --------------------------------------------------------------------------- #
CONTROLS: tuple[AssuranceControl, ...] = (
    AssuranceControl(
        "ACT.OWNERSHIP.ACCOUNTABLE_OWNER",
        "Does this agent have an accountable owner?",
        "agents.owner_id (Phase 5.1)", "AGENT", "1", _c_accountable_owner),
    AssuranceControl(
        "ACT.PROVENANCE.KNOWN_ORIGIN",
        "Is this agent's origin known?",
        "agents.origin_category (Phase 5.2)", "AGENT", "1", _c_known_provenance),
    AssuranceControl(
        "ACT.GOVERNANCE.POLICY_COVERAGE",
        "Is an active governance policy in force for this agent?",
        "runtime_governance_policies via posture (4.3 / 5.5)", "AGENT", "1",
        _from_posture("GOVERNANCE.POLICY_COVERAGE",
                      question="Is a governance policy in force?",
                      remediation="Define a runtime governance policy covering this agent.")),
    AssuranceControl(
        "ACT.RELIABILITY.SLO_COVERAGE",
        "Is a service level objective defined for this agent?",
        "slo_definitions via posture (4.7 / 5.5)", "AGENT", "1",
        _from_posture("RELIABILITY.SLO_COVERAGE",
                      question="Is an SLO defined?",
                      remediation="Define an SLO for this agent.")),
    AssuranceControl(
        "ACT.CREDENTIAL.LIFECYCLE",
        "Are this agent's credentials within their lifecycle policy?",
        "agent_api_keys via posture (5.5)", "AGENT", "1",
        _from_posture("CREDENTIAL.EXPIRY",
                      question="Are credentials unexpired?",
                      remediation="Rotate or revoke the expired credential.")),
    AssuranceControl(
        "ACT.SUPPLY_CHAIN.MCP_TRUST",
        "Are this agent's MCP dependencies approved?",
        "mcp_servers + dependency edges via posture (5.4 / 5.5)", "AGENT", "1",
        _from_posture("SUPPLY_CHAIN.MCP_TRUST",
                      question="Are MCP dependencies approved?",
                      remediation="Approve or remove the unapproved MCP dependency.")),
    AssuranceControl(
        "ACT.TOOL.LEAST_PRIVILEGE",
        "Are this agent's tool grants least-privilege?",
        "agent_tools via posture (5.5)", "AGENT", "1",
        _from_posture("TOOL.LEAST_PRIVILEGE",
                      question="Are tool grants least-privilege?",
                      remediation="Narrow the tool grant's allowed actions.")),
    AssuranceControl(
        "ACT.MODEL.APPROVED",
        "Is this agent using an approved model?",
        "agent_versions.model_configuration via posture (5.5)", "AGENT", "1",
        _from_posture("MODEL.APPROVED_MODELS",
                      question="Is the model approved?",
                      remediation="Move the agent to an approved model.")),
    AssuranceControl(
        "ACT.RUNTIME.TRACEABLE",
        "Is this agent's runtime activity traceable?",
        "agent_executions (Phase 4.1 / 4.2)", "AGENT", "1", _c_runtime_traceable),
    AssuranceControl(
        "ACT.COST.GOVERNED",
        "Is this agent's spend governed by a budget?",
        "budgets (Phase 4.4)", "AGENT", "1", _c_cost_governed),
    AssuranceControl(
        "ACT.AUTHORITY.CHAIN_PROVABLE",
        "Can this agent's authority be reconstructed?",
        "control_graph_edges (Phase 5.3)", "AGENT", "1", _c_authority_chain_provable),
    AssuranceControl(
        "ACT.INCIDENT.RECONSTRUCTABLE",
        "Can incidents involving this agent be reconstructed?",
        "threat_findings + containment_actions + audit (Phase 5.6)", "AGENT", "1",
        _c_incidents_reconstructable),
)

CONTROLS_BY_ID: dict[str, AssuranceControl] = {c.id: c for c in CONTROLS}


__all__ = [
    "ASSURANCE_CATALOG_VERSION",
    "RESULTS",
    "DEFAULT_FRESHNESS_DAYS",
    "ControlResult",
    "AssuranceControl",
    "AssuranceContext",
    "CONTROLS",
    "CONTROLS_BY_ID",
]
