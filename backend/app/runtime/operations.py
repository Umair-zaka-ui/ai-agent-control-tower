"""ACT-SRS-M3 §Phase-3.10 (M3-3.10-FR-030/031) -- read models for the Release
Operations Center.

**Everything here is read-only, and that is the phase's central constraint
rather than an incidental property.** Phases 3.1-3.9 own every rule about how
a deployment changes: the lifecycle authority, the release gate, the traffic
allocator, the canary engine, the rollback policy, the scheduler and the
worker fleet. This module computes no domain state, decides nothing, and
writes nothing. It reads what those engines already produced and *shapes* it
for a screen.

That is enforced structurally, not just promised: nothing in this module
imports a service that mutates, and a test asserts no ``add``/``commit``/
``delete``/``flush`` call appears anywhere in it.

**Why these four read models exist at all**, when the rule is "reuse the
existing endpoints":

- ``overview`` -- the deployment list already exists, but a row on the
  overview screen needs the agent's name, the version's semantic version and
  signature state, the environment's name, the current traffic weight, any
  active rollout and the latest health verdict. Fetching those per row is
  five extra requests per deployment; a fleet of forty deployments becomes
  two hundred round trips to render one table. This does it in a fixed number
  of batched queries regardless of row count.
- ``release_history`` -- genuinely missing. Lifecycle events and rollback
  history are both exposed *per deployment*, so reconstructing "what shipped
  this week" required knowing every deployment id in advance. §13 requires
  a release be reconstructable; this is the endpoint that makes that true.
- ``deployment_detail`` -- §22 lists thirteen things the detail view must
  show, spread across eight endpoints. Composing client-side would make the
  most important screen in the product the slowest, and would let it render
  in an inconsistent half-state as each request lands.
- rollout listing (``rollouts``) -- also genuinely missing, and the sharpest
  gap of the four: Phase 3.5 exposed ``GET /rollouts/{id}`` and no way to
  *find* a rollout. Until now the only way to see a canary in the API was to
  have kept the id returned when you created it.

**Truthful state is a design requirement here** (§10, M3-3.10-FR-022). These
read models deliberately surface the uncomfortable facts rather than the
convenient summary: a suspended agent (the kill switch), a BLOCK preflight
verdict, ``INSUFFICIENT_DATA`` health, a paused or rolling-back plan. A read
model that quietly omitted them would let the UI present a killed release as
deployable, which is the one thing §10 forbids -- and the UI cannot show what
it was never told.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.runtime import (
    AgentDeployment,
    AgentVersion,
    DeploymentEvent,
    DeploymentHealthEvaluation,
    DeploymentPreflightResult,
    DeploymentTrafficAllocation,
    DeploymentTrafficWeight,
    Environment,
    RollbackEvent,
    RolloutPlan,
    RolloutStage,
    RuntimeApproval,
)
from app.models.user import User
from app.runtime.deployment.traffic import is_servable

#: Rollout states that are still live. A rollout in one of these is something
#: an operator may still have to act on, which is what makes it "active" for
#: an overview screen rather than history.
LIVE_ROLLOUT_STATES: frozenset[str] = frozenset({"PENDING", "IN_PROGRESS", "PAUSED"})

#: Health verdicts that are the *absence* of evidence rather than evidence of
#: health. Named here so the UI is handed the distinction explicitly instead
#: of having to infer it from a string -- Phase 3.5 established that not
#: knowing is never the same as being fine, and a screen that rendered
#: INSUFFICIENT_DATA as a reassuring grey badge would quietly undo that.
NON_PROVING_HEALTH: frozenset[str] = frozenset({"UNKNOWN", "INSUFFICIENT_DATA"})


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class OperationsReadModel:
    """Read-only aggregation over the Milestone 3 engines.

    Tenant scope is applied to the *first* query of every method and carried
    through every subsequent lookup by id, so a row from another organization
    has no path into any response here."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ----------------------------------------------------------------- #
    # Shared batch loaders -- the reason this module exists
    # ----------------------------------------------------------------- #
    def _agents(self, ids: set[uuid.UUID]) -> dict[uuid.UUID, Agent]:
        if not ids:
            return {}
        return {a.id: a for a in self.db.execute(
            select(Agent).where(Agent.id.in_(ids))).scalars()}

    def _versions(self, ids: set[uuid.UUID]) -> dict[uuid.UUID, AgentVersion]:
        if not ids:
            return {}
        return {v.id: v for v in self.db.execute(
            select(AgentVersion).where(AgentVersion.id.in_(ids))).scalars()}

    def _environments(self, organization_id: uuid.UUID) -> dict[uuid.UUID, Environment]:
        return {e.id: e for e in self.db.execute(
            select(Environment).where(Environment.organization_id == organization_id)).scalars()}

    def _current_weights(self, organization_id: uuid.UUID) -> dict[tuple, int]:
        """Current traffic weight per (agent, environment, version).

        Read from Phase 3.4's own current-allocation rows rather than
        recomputed -- this module has no business deciding what the weights
        are, only reporting what 3.4 recorded."""
        rows = self.db.execute(
            select(DeploymentTrafficAllocation, DeploymentTrafficWeight)
            .join(DeploymentTrafficWeight,
                  DeploymentTrafficWeight.allocation_id == DeploymentTrafficAllocation.id)
            .where(DeploymentTrafficAllocation.organization_id == organization_id,
                   DeploymentTrafficAllocation.is_current.is_(True))
        ).all()
        return {(a.agent_id, a.environment_id, w.agent_version_id): w.weight
                for a, w in rows}

    def _live_rollouts(self, organization_id: uuid.UUID) -> dict[tuple, RolloutPlan]:
        """The live rollout per (agent, environment), newest first.

        At most one is expected -- Phase 3.9's rolling start refuses to run
        beside another plan -- but this does not *assume* it: canary predates
        that guard, so the newest wins and the rest remain visible through the
        rollout list."""
        plans = self.db.execute(
            select(RolloutPlan)
            .where(RolloutPlan.organization_id == organization_id,
                   RolloutPlan.state.in_(tuple(LIVE_ROLLOUT_STATES)))
            .order_by(RolloutPlan.created_at.desc())
        ).scalars().all()
        out: dict[tuple, RolloutPlan] = {}
        for plan in plans:
            out.setdefault((plan.agent_id, plan.environment_id), plan)
        return out

    def _latest_health(self, organization_id: uuid.UUID) -> dict[uuid.UUID, DeploymentHealthEvaluation]:
        """The most recent health verdict per deployment."""
        rows = self.db.execute(
            select(DeploymentHealthEvaluation)
            .where(DeploymentHealthEvaluation.organization_id == organization_id,
                   DeploymentHealthEvaluation.deployment_id.isnot(None))
            .order_by(DeploymentHealthEvaluation.evaluated_at.desc())
        ).scalars().all()
        out: dict[uuid.UUID, DeploymentHealthEvaluation] = {}
        for row in rows:
            out.setdefault(row.deployment_id, row)
        return out

    def _latest_preflight(self, organization_id: uuid.UUID) -> dict[uuid.UUID, DeploymentPreflightResult]:
        rows = self.db.execute(
            select(DeploymentPreflightResult)
            .where(DeploymentPreflightResult.organization_id == organization_id)
            .order_by(DeploymentPreflightResult.evaluated_at.desc())
        ).scalars().all()
        out: dict[uuid.UUID, DeploymentPreflightResult] = {}
        for row in rows:
            out.setdefault(row.deployment_id, row)
        return out

    # ----------------------------------------------------------------- #
    # Shaping
    # ----------------------------------------------------------------- #
    @staticmethod
    def _version_identity(version: AgentVersion | None) -> dict | None:
        """M3-3.10-FR-024 -- the immutable artifact's identity.

        An operator looking at a production deployment needs to be able to
        answer "is what is running the signed, reviewed thing we approved?".
        ``signature_state`` collapses the three columns into the one word
        that answers it, because a screen that showed a null ``signed_at``
        next to a populated ``checksum`` leaves the reader doing forensics."""
        if version is None:
            return None
        signed = version.signature_id is not None and version.signed_at is not None
        return {
            "id": str(version.id),
            "semantic_version": version.semantic_version,
            "status": version.status,
            "checksum": version.checksum,
            "checksum_algorithm": version.checksum_algorithm,
            "signature_id": version.signature_id,
            "signed_at": _iso(version.signed_at),
            "manifest_digest": version.manifest_digest,
            "signature_state": "SIGNED" if signed else "UNSIGNED",
            "rollback_target_id": (str(version.rollback_target_id)
                                   if version.rollback_target_id else None),
        }

    @staticmethod
    def _health_shape(evaluation: DeploymentHealthEvaluation | None) -> dict | None:
        if evaluation is None:
            return None
        return {
            "health_state": evaluation.health_state,
            # Handed over explicitly rather than left for the UI to infer from
            # the string: "we do not know" must never render as "fine".
            "is_proving": evaluation.health_state not in NON_PROVING_HEALTH,
            "sample_count": evaluation.sample_count,
            "metrics": evaluation.metrics,
            "evaluated_at": _iso(evaluation.evaluated_at),
        }

    @staticmethod
    def _rollout_shape(plan: RolloutPlan | None) -> dict | None:
        if plan is None:
            return None
        return {
            "id": str(plan.id),
            "kind": plan.kind,
            "state": plan.state,
            "current_stage_index": plan.current_stage_index,
            "state_reason": plan.state_reason,
        }

    # ----------------------------------------------------------------- #
    # M3-3.10-FR-001/002 -- overview + environment matrix
    # ----------------------------------------------------------------- #
    def overview(self, actor: User, *, environment_id: uuid.UUID | None = None) -> dict:
        """Every deployment in the caller's organization, enriched.

        Serves both the Deployment Overview and the Environment Matrix: the
        matrix is the same rows pivoted by environment, and computing it twice
        on the server would be two things to keep in agreement."""
        organization_id = actor.organization_id
        stmt = select(AgentDeployment).where(
            AgentDeployment.organization_id == organization_id)
        if environment_id is not None:
            stmt = stmt.where(AgentDeployment.environment_id == environment_id)
        deployments = list(self.db.execute(
            stmt.order_by(AgentDeployment.deployed_at.desc().nullslast(),
                          AgentDeployment.id)).scalars())

        agents = self._agents({d.agent_id for d in deployments})
        versions = self._versions({d.agent_version_id for d in deployments})
        environments = self._environments(organization_id)
        weights = self._current_weights(organization_id)
        rollouts = self._live_rollouts(organization_id)
        health = self._latest_health(organization_id)
        preflight = self._latest_preflight(organization_id)

        rows = []
        for deployment in deployments:
            agent = agents.get(deployment.agent_id)
            environment = (environments.get(deployment.environment_id)
                           if deployment.environment_id else None)
            gate = preflight.get(deployment.id)
            rows.append({
                "deployment_id": str(deployment.id),
                "agent_id": str(deployment.agent_id),
                "agent_name": agent.name if agent else None,
                # The kill switch, surfaced as a first-class field rather than
                # buried in a lifecycle string the UI would have to know how to
                # read. §10: never present a killed release as deployable.
                "agent_lifecycle_status": agent.lifecycle_status if agent else None,
                "kill_switch_active": bool(agent and agent.lifecycle_status == "SUSPENDED"),
                "environment_id": (str(deployment.environment_id)
                                   if deployment.environment_id else None),
                "environment_name": environment.name if environment else deployment.environment,
                "is_production": bool(environment.is_production) if environment else False,
                "version": self._version_identity(versions.get(deployment.agent_version_id)),
                "deployment_strategy": deployment.deployment_strategy,
                "status": deployment.status,
                "lifecycle_state": deployment.lifecycle_state,
                "revision": deployment.revision,
                "state_reason": deployment.state_reason,
                # Phase 3.4's union-with-veto predicate, reported rather than
                # re-derived in the browser -- two implementations of
                # "is this actually serving?" would eventually disagree.
                "servable": is_servable(deployment),
                "traffic_weight": weights.get(
                    (deployment.agent_id, deployment.environment_id,
                     deployment.agent_version_id)),
                "health_status": deployment.health_status,
                "release_health": self._health_shape(health.get(deployment.id)),
                "gate_verdict": gate.verdict if gate else None,
                "gate_evaluated_at": _iso(gate.evaluated_at) if gate else None,
                "active_rollout": self._rollout_shape(
                    rollouts.get((deployment.agent_id, deployment.environment_id))),
                "deployed_at": _iso(deployment.deployed_at),
                "updated_at": _iso(deployment.updated_at),
            })

        return {
            "deployments": rows,
            "environments": [
                {"id": str(e.id), "name": e.name, "display_name": e.display_name,
                 "is_production": e.is_production}
                for e in sorted(environments.values(), key=lambda e: (not e.is_production, e.name))
            ],
            "summary": {
                "total": len(rows),
                "serving": sum(1 for r in rows if r["servable"]),
                "kill_switched": sum(1 for r in rows if r["kill_switch_active"]),
                "blocked": sum(1 for r in rows if r["gate_verdict"] == "BLOCK"),
                "rolling_out": sum(1 for r in rows if r["active_rollout"] is not None),
            },
        }

    # ----------------------------------------------------------------- #
    # M3-3.10-FR-003 -- release history
    # ----------------------------------------------------------------- #
    def release_history(self, actor: User, *, limit: int = 100, offset: int = 0,
                        agent_id: uuid.UUID | None = None,
                        environment_id: uuid.UUID | None = None) -> list[dict]:
        """The audited release timeline: lifecycle transitions and rollbacks,
        merged and newest-first.

        Two sources, both durable and both typed. ``deployment_events`` is
        Phase 3.1's append-only lineage of every lifecycle transition, which
        includes promotions and deployments; ``rollback_events`` is Phase
        3.7's record of every rollback and its trigger. The platform-wide
        audit stream is deliberately *not* used as the source here: it is the
        security record, it carries entries this screen has no business
        showing, and filtering it down to releases would mean this module
        deciding what counts as a release -- which is exactly the kind of
        domain judgement a read model must not make. These two tables already
        are the answer."""
        organization_id = actor.organization_id

        stmt = (select(DeploymentEvent, AgentDeployment)
                .join(AgentDeployment, AgentDeployment.id == DeploymentEvent.deployment_id)
                .where(DeploymentEvent.organization_id == organization_id))
        if agent_id is not None:
            stmt = stmt.where(AgentDeployment.agent_id == agent_id)
        if environment_id is not None:
            stmt = stmt.where(AgentDeployment.environment_id == environment_id)
        lifecycle = self.db.execute(
            stmt.order_by(DeploymentEvent.created_at.desc()).limit(limit + offset)).all()

        rollback_stmt = (select(RollbackEvent, AgentDeployment)
                         .join(AgentDeployment, AgentDeployment.id == RollbackEvent.deployment_id)
                         .where(RollbackEvent.organization_id == organization_id))
        if agent_id is not None:
            rollback_stmt = rollback_stmt.where(AgentDeployment.agent_id == agent_id)
        if environment_id is not None:
            rollback_stmt = rollback_stmt.where(AgentDeployment.environment_id == environment_id)
        rollbacks = self.db.execute(
            rollback_stmt.order_by(RollbackEvent.created_at.desc()).limit(limit + offset)).all()

        agents = self._agents({d.agent_id for _, d in lifecycle} |
                              {d.agent_id for _, d in rollbacks})
        environments = self._environments(organization_id)

        def _scope(deployment: AgentDeployment) -> dict:
            agent = agents.get(deployment.agent_id)
            environment = (environments.get(deployment.environment_id)
                           if deployment.environment_id else None)
            return {
                "deployment_id": str(deployment.id),
                "agent_id": str(deployment.agent_id),
                "agent_name": agent.name if agent else None,
                "environment_name": environment.name if environment else deployment.environment,
            }

        entries: list[dict] = []
        for event, deployment in lifecycle:
            entries.append({
                "id": str(event.id),
                "kind": "LIFECYCLE",
                "event_type": event.event_type,
                "from_state": event.from_state,
                "to_state": event.to_state,
                "reason": event.reason,
                "actor_id": str(event.actor_id) if event.actor_id else None,
                "occurred_at": _iso(event.created_at),
                **_scope(deployment),
            })
        for event, deployment in rollbacks:
            entries.append({
                "id": str(event.id),
                "kind": "ROLLBACK",
                "event_type": f"ROLLBACK_{event.trigger}",
                "from_state": None,
                "to_state": event.status,
                # An automatic rollback has no human actor, and Phase 3.7
                # deliberately leaves ``initiated_by`` null rather than
                # attributing it to a system user. The timeline says
                # "automation" instead of inventing a name.
                "reason": event.reason,
                "actor_id": str(event.initiated_by) if event.initiated_by else None,
                "trigger": event.trigger,
                "occurred_at": _iso(event.created_at),
                **_scope(deployment),
            })

        entries.sort(key=lambda e: e["occurred_at"] or "", reverse=True)
        return entries[offset:offset + limit]

    # ----------------------------------------------------------------- #
    # M3-3.10-FR-004 -- the deployment detail composite
    # ----------------------------------------------------------------- #
    def deployment_detail(self, actor: User, deployment_id: uuid.UUID) -> dict:
        """§22's full field set for one deployment, in one response."""
        deployment = self.db.get(AgentDeployment, deployment_id)
        if deployment is None or deployment.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.DEPLOYMENT_NOT_FOUND, "Deployment not found.")

        agent = self.db.get(Agent, deployment.agent_id)
        version = self.db.get(AgentVersion, deployment.agent_version_id)
        rollback_target = (self.db.get(AgentVersion, version.rollback_target_id)
                           if version and version.rollback_target_id else None)
        environment = (self.db.get(Environment, deployment.environment_id)
                       if deployment.environment_id else None)

        allocation = self.db.execute(select(DeploymentTrafficAllocation).where(
            DeploymentTrafficAllocation.organization_id == deployment.organization_id,
            DeploymentTrafficAllocation.agent_id == deployment.agent_id,
            DeploymentTrafficAllocation.environment_id == deployment.environment_id,
            DeploymentTrafficAllocation.is_current.is_(True),
        )).scalars().first()
        weights: list[dict] = []
        if allocation is not None:
            rows = self.db.execute(select(DeploymentTrafficWeight).where(
                DeploymentTrafficWeight.allocation_id == allocation.id)).scalars().all()
            by_version = self._versions({w.agent_version_id for w in rows})
            weights = [{
                "agent_version_id": str(w.agent_version_id),
                "semantic_version": (by_version[w.agent_version_id].semantic_version
                                     if w.agent_version_id in by_version else None),
                "weight": w.weight,
            } for w in sorted(rows, key=lambda w: -w.weight)]

        plan = self.db.execute(
            select(RolloutPlan)
            .where(RolloutPlan.organization_id == deployment.organization_id,
                   RolloutPlan.agent_id == deployment.agent_id,
                   RolloutPlan.environment_id == deployment.environment_id)
            .order_by(RolloutPlan.created_at.desc())
        ).scalars().first()
        stages: list[dict] = []
        if plan is not None:
            stages = [{
                "stage_index": s.stage_index,
                "target_weight": s.target_weight,
                "min_duration_seconds": s.min_duration_seconds,
                "min_samples": s.min_samples,
                "health_requirement": s.health_requirement,
                "advance_mode": s.advance_mode,
                "entered_at": _iso(s.entered_at),
            } for s in self.db.execute(select(RolloutStage).where(
                RolloutStage.rollout_plan_id == plan.id
            ).order_by(RolloutStage.stage_index)).scalars()]

        gate = self.db.execute(
            select(DeploymentPreflightResult)
            .where(DeploymentPreflightResult.deployment_id == deployment.id)
            .order_by(DeploymentPreflightResult.evaluated_at.desc())
        ).scalars().first()

        health = self.db.execute(
            select(DeploymentHealthEvaluation)
            .where(DeploymentHealthEvaluation.deployment_id == deployment.id)
            .order_by(DeploymentHealthEvaluation.evaluated_at.desc())
        ).scalars().first()

        approvals = self.db.execute(
            select(RuntimeApproval)
            .where(RuntimeApproval.organization_id == deployment.organization_id,
                   RuntimeApproval.deployment_id == deployment.id)
            .order_by(RuntimeApproval.created_at.desc())
        ).scalars().all()

        events = self.db.execute(
            select(DeploymentEvent)
            .where(DeploymentEvent.deployment_id == deployment.id)
            .order_by(DeploymentEvent.created_at.desc())
        ).scalars().all()

        rollbacks = self.db.execute(
            select(RollbackEvent)
            .where(RollbackEvent.deployment_id == deployment.id)
            .order_by(RollbackEvent.created_at.desc())
        ).scalars().all()

        return {
            "deployment_id": str(deployment.id),
            "agent": {"id": str(deployment.agent_id),
                      "name": agent.name if agent else None,
                      "lifecycle_status": agent.lifecycle_status if agent else None},
            "kill_switch_active": bool(agent and agent.lifecycle_status == "SUSPENDED"),
            "version": self._version_identity(version),
            "rollback_target": self._version_identity(rollback_target),
            "environment": ({"id": str(environment.id), "name": environment.name,
                             "is_production": environment.is_production}
                            if environment else {"id": None, "name": deployment.environment,
                                                 "is_production": False}),
            "deployment_strategy": deployment.deployment_strategy,
            "status": deployment.status,
            "lifecycle_state": deployment.lifecycle_state,
            "revision": deployment.revision,
            "state_reason": deployment.state_reason,
            "servable": is_servable(deployment),
            "health_status": deployment.health_status,
            "release_health": self._health_shape(health),
            "gate": ({"verdict": gate.verdict, "findings": gate.findings,
                      "evaluated_at": _iso(gate.evaluated_at)} if gate else None),
            "allocation": ({"revision": allocation.revision,
                            "weights": weights,
                            "updated_at": _iso(allocation.created_at)}
                           if allocation is not None else None),
            "rollout": (None if plan is None else {
                **self._rollout_shape(plan), "cohort_plan": plan.cohort_plan,
                "stages": stages}),
            "approvals": [{
                "id": str(a.id), "status": a.status, "requested_action": a.requested_action,
                "reviewed_by": str(a.reviewed_by) if a.reviewed_by else None,
                "decision_comment": a.decision_comment,
                "created_at": _iso(a.created_at),
            } for a in approvals],
            "initiated_by": str(deployment.deployed_by) if deployment.deployed_by else None,
            "deployed_at": _iso(deployment.deployed_at),
            "retired_at": _iso(deployment.retired_at),
            "updated_at": _iso(deployment.updated_at),
            "duration_seconds": (
                int((deployment.retired_at - deployment.deployed_at).total_seconds())
                if deployment.deployed_at and deployment.retired_at else None),
            "timeline": sorted(
                [{"id": str(e.id), "kind": "LIFECYCLE", "event_type": e.event_type,
                  "from_state": e.from_state, "to_state": e.to_state, "reason": e.reason,
                  "actor_id": str(e.actor_id) if e.actor_id else None,
                  "occurred_at": _iso(e.created_at)} for e in events]
                + [{"id": str(r.id), "kind": "ROLLBACK",
                    "event_type": f"ROLLBACK_{r.trigger}", "from_state": None,
                    "to_state": r.status, "reason": r.reason, "trigger": r.trigger,
                    "actor_id": str(r.initiated_by) if r.initiated_by else None,
                    "occurred_at": _iso(r.created_at)} for r in rollbacks],
                key=lambda e: e["occurred_at"] or "", reverse=True),
        }

    # ----------------------------------------------------------------- #
    # The missing rollout list (Phase 3.5 exposed only get-by-id)
    # ----------------------------------------------------------------- #
    def rollouts(self, actor: User, *, agent_id: uuid.UUID | None = None,
                 environment_id: uuid.UUID | None = None, active_only: bool = False,
                 limit: int = 100) -> list[dict]:
        stmt = select(RolloutPlan).where(
            RolloutPlan.organization_id == actor.organization_id)
        if agent_id is not None:
            stmt = stmt.where(RolloutPlan.agent_id == agent_id)
        if environment_id is not None:
            stmt = stmt.where(RolloutPlan.environment_id == environment_id)
        if active_only:
            stmt = stmt.where(RolloutPlan.state.in_(tuple(LIVE_ROLLOUT_STATES)))
        plans = list(self.db.execute(
            stmt.order_by(RolloutPlan.created_at.desc()).limit(limit)).scalars())

        agents = self._agents({p.agent_id for p in plans})
        versions = self._versions({p.candidate_version_id for p in plans}
                                  | {p.stable_version_id for p in plans if p.stable_version_id})
        environments = self._environments(actor.organization_id)

        stage_counts: dict[uuid.UUID, int] = {}
        if plans:
            for plan_id, in self.db.execute(
                select(RolloutStage.rollout_plan_id).where(
                    RolloutStage.rollout_plan_id.in_([p.id for p in plans]))).all():
                stage_counts[plan_id] = stage_counts.get(plan_id, 0) + 1

        return [{
            **self._rollout_shape(plan),
            "agent_id": str(plan.agent_id),
            "agent_name": agents[plan.agent_id].name if plan.agent_id in agents else None,
            "environment_id": str(plan.environment_id),
            "environment_name": (environments[plan.environment_id].name
                                 if plan.environment_id in environments else None),
            "candidate_version": (versions[plan.candidate_version_id].semantic_version
                                  if plan.candidate_version_id in versions else None),
            "stable_version": (versions[plan.stable_version_id].semantic_version
                               if plan.stable_version_id in versions else None),
            "stage_count": stage_counts.get(plan.id, 0),
            "is_live": plan.state in LIVE_ROLLOUT_STATES,
            "created_at": _iso(plan.created_at),
            "updated_at": _iso(plan.updated_at),
        } for plan in plans]
