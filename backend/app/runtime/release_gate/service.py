"""ACT-SRS-M3 §Phase-3.3 -- ``ReleaseGateService``, the single authoritative
deployment-readiness evaluation (build prompt §0: "It aggregates existing
checks... into one verdict"). Direct SQLAlchemy queries, no repository layer
-- matching the rest of the runtime domain (REPO_STATE §7).

Wired into ``DeploymentLifecycleService.start_deploying`` (see that method's
own comment) so a BLOCK verdict prevents a deployment from reaching
DEPLOYING/ACTIVE (AC-04) -- and, since ``PromotionService.promote`` already
funnels through that same method (Phase 3.2), a promotion is gated for free
with no extra wiring (build prompt §1: "If wiring into promotion is trivial
via 3.2's path, it's acceptable -- state it." -- this is that case).

``evaluate()`` is intentionally **not** wrapped in the 3.1
``IdempotencyService`` contract: FR-031 requires every call to produce a
*fresh* result ("a prior PASS does not permanently certify"), which is the
opposite of idempotent replay -- the same precedent
``CompatibilityAnalysisService.analyze`` (Phase 5.2.6, also a POST that
recomputes and persists a fresh result every call) already establishes for
this codebase."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.models.agent import Agent
from app.models.runtime import AgentVersion, DeploymentPreflightResult, Environment
from app.models.user import User
from app.runtime.release_gate import checks
from app.runtime.services import DeploymentService, _record_event


class ReleaseGateService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _build_context(self, deployment) -> checks.GateContext:
        agent = self.db.get(Agent, deployment.agent_id)
        version = self.db.get(AgentVersion, deployment.agent_version_id)
        environment = self.db.get(Environment, deployment.environment_id) if deployment.environment_id else None
        return checks.GateContext(db=self.db, agent=agent, version=version, deployment=deployment,
                                  environment=environment)

    def evaluate(self, actor: User | None, deployment) -> DeploymentPreflightResult:
        """Runs every check (``checks.run_checks``), persists the verdict +
        findings, audits it, and returns the persisted row. Called both by
        the explicit preview API (``POST .../preflight``) and internally by
        ``DeploymentLifecycleService.start_deploying`` -- one evaluation
        path, no divergence between preview and enforcement (build prompt
        §0: "one authoritative evaluation")."""
        ctx = self._build_context(deployment)

        _record_event(self.db, AuthorizationAuditEvent.DEPLOYMENT_VALIDATION_STARTED, actor,
                     organization_id=deployment.organization_id, agent_id=deployment.agent_id,
                     deployment_id=deployment.id, meta={})

        findings = checks.run_checks(ctx)
        verdict = checks.verdict_for(findings)

        result = DeploymentPreflightResult(
            deployment_id=deployment.id, organization_id=deployment.organization_id, verdict=verdict,
            findings=[finding.as_dict() for finding in findings], evaluated_by=actor.id if actor else None,
        )
        self.db.add(result)

        # The kill-switch finding is always security-relevant (SRS §12,
        # AC-07) regardless of the overall verdict's own severity.
        kill_switch_active = any(finding.code == "PREFLIGHT_KILL_SWITCH_ACTIVE" for finding in findings)
        event = (AuthorizationAuditEvent.DEPLOYMENT_VALIDATION_FAILED if verdict == "BLOCK"
                else AuthorizationAuditEvent.DEPLOYMENT_VALIDATION_PASSED)
        _record_event(
            self.db, event, actor, organization_id=deployment.organization_id, agent_id=deployment.agent_id,
            deployment_id=deployment.id, severity="CRITICAL" if kill_switch_active else "INFO",
            meta={"verdict": verdict, "codes": [finding.code for finding in findings],
                 "severities": [finding.severity for finding in findings]},
        )

        self.db.commit()
        self.db.refresh(result)
        return result

    def get_latest(self, actor: User, deployment_id: uuid.UUID) -> DeploymentPreflightResult | None:
        DeploymentService(self.db).get_or_404(actor, deployment_id)  # tenant-scope check
        return self.db.execute(
            select(DeploymentPreflightResult).where(DeploymentPreflightResult.deployment_id == deployment_id)
            .order_by(DeploymentPreflightResult.evaluated_at.desc()).limit(1)
        ).scalars().first()

    def get_history(self, actor: User, deployment_id: uuid.UUID, *,
                    limit: int = 50, offset: int = 0) -> list[DeploymentPreflightResult]:
        DeploymentService(self.db).get_or_404(actor, deployment_id)  # tenant-scope check
        return list(self.db.execute(
            select(DeploymentPreflightResult).where(DeploymentPreflightResult.deployment_id == deployment_id)
            .order_by(DeploymentPreflightResult.evaluated_at.desc()).limit(limit).offset(offset)
        ).scalars())
