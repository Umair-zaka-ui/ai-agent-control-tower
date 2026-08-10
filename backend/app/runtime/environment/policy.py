"""ACT-SRS-M3 §3.2 (M3-3.2-FR-010..013) -- environment policy evaluation.

An ``Environment.policy`` JSONB document may declare:

- ``allowed_models``: ``list[str] | None`` -- if set, the version's
  ``model_configuration.model`` must be in this list. **Enforced.**
- ``allowed_data_classifications``: ``list[str] | None`` -- if set, every
  tool in the version's frozen ``tools_snapshot`` must carry a
  ``Tool.data_classification`` within this list. **Enforced.**
- ``requires_approval``: ``bool`` -- folded into
  ``DeploymentLifecycleService``'s own, pre-existing single
  approval-reroute funnel (``_requires_deployment_approval``), never a
  second, parallel approval mechanism. **Enforced** (production-class
  environments, ``is_production=True``, require approval unconditionally,
  independent of this flag).
- ``maximum_concurrent_deployments``: ``int | None`` -- how many ``ACTIVE``
  deployments of one agent this environment may hold at once. **Enforced.**
- ``change_window``: ``{"days_of_week": [0-6,...] | None, "start_hour_utc":
  int, "end_hour_utc": int} | None`` -- ``0`` = Monday, matching
  ``datetime.weekday()``; ``days_of_week: None`` means every day. A deploy
  or promotion landing outside the window is rejected
  (``PROMOTION_WINDOW_CLOSED``). **Enforced.**
- ``allowed_external_systems``: ``list[str] | None`` -- **modeled only, not
  enforced this phase.** There is no existing link in this codebase between
  a runtime ``Tool``/``AgentVersion`` row and Milestone 2's own
  integration-instance catalog (deliberately -- the runtime-never-knows
  boundary those instances are built behind, see
  ``app.runtime.environment``'s own package docstring); inventing one to
  check against here is out of this phase's scope. Stored and returned by
  the API so a later phase can wire real enforcement without a schema
  change.
- ``rollback_rules``: ``dict`` -- **modeled only.** Rollback itself is
  Phase 3.7's own job; this phase only reserves the policy field.

``evaluate()`` below is the single deploy/promote-time choke point
(M3-3.2-FR-011) -- called from exactly one place,
``DeploymentLifecycleService.start_deploying`` (``app.runtime.deployment.
service``), which covers both a plain deploy *and* a promotion (a
promotion's own ``PromotionService.promote`` creates the new deployment and
then calls that same method) -- never duplicated at a second call site.
Deliberately does **not** run on every execution request -- that would put
it on the M1 execution path this phase must not touch; ``RuntimePolicyService.
evaluate`` (``app.runtime.services``) is the separate, pre-existing,
unmodified mechanism for that, and this module's own ``prohibited_environments``
check below reads the exact same ``AgentVersion.policy_snapshot`` field that
one already reads, rather than parallel it (Ruling / build-prompt §2's
mandatory-integration requirement)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.runtime import AgentDeployment, AgentVersion, Tool


@dataclass(frozen=True)
class PolicyViolation:
    code: str
    message: str


def check_prohibited(policy_snapshot: dict | None, environment_name: str) -> PolicyViolation | None:
    """Reads the exact same ``prohibited_environments`` list
    ``RuntimePolicyService.evaluate`` already reads at execution time
    (``app.runtime.services``) -- the mandatory ``prohibited_environments``
    integration (build prompt §2): a version barred from an environment by
    that pre-existing mechanism cannot be deployed or promoted into it here
    either, and nothing new is added to represent the same fact twice."""
    prohibited = (policy_snapshot or {}).get("prohibited_environments", [])
    if environment_name in prohibited:
        return PolicyViolation("ENVIRONMENT_POLICY_VIOLATION",
                               f"This version's policy prohibits deployment into '{environment_name}'.")
    return None


def check_allowed_models(policy: dict, model: str | None) -> PolicyViolation | None:
    allowed = policy.get("allowed_models")
    if allowed and model not in allowed:
        return PolicyViolation("ENVIRONMENT_POLICY_VIOLATION",
                               f"Model '{model}' is not in this environment's allowed_models list.")
    return None


def check_allowed_data_classifications(policy: dict, classifications: list[str]) -> PolicyViolation | None:
    allowed = policy.get("allowed_data_classifications")
    if not allowed:
        return None
    for classification in classifications:
        if classification not in allowed:
            return PolicyViolation(
                "ENVIRONMENT_POLICY_VIOLATION",
                f"A bound tool's data classification '{classification}' is not allowed in this environment.",
            )
    return None


def check_concurrency(policy: dict, active_count: int) -> PolicyViolation | None:
    limit = policy.get("maximum_concurrent_deployments")
    if limit is not None and active_count >= limit:
        return PolicyViolation("ENVIRONMENT_POLICY_VIOLATION",
                               "This environment's concurrent-deployment limit has been reached.")
    return None


def check_change_window(policy: dict, *, now: datetime | None = None) -> PolicyViolation | None:
    window = policy.get("change_window")
    if not window:
        return None
    now = now or datetime.now(timezone.utc)
    days = window.get("days_of_week")
    if days is not None and now.weekday() not in days:
        return PolicyViolation("PROMOTION_WINDOW_CLOSED",
                               "Outside this environment's configured change window (wrong day).")
    start_hour = window.get("start_hour_utc", 0)
    end_hour = window.get("end_hour_utc", 24)
    hour = now.hour
    in_range = (start_hour <= hour < end_hour) if start_hour <= end_hour else (hour >= start_hour or hour < end_hour)
    if not in_range:
        return PolicyViolation("PROMOTION_WINDOW_CLOSED",
                               "Outside this environment's configured change window (wrong hour).")
    return None


def requires_approval(environment) -> bool:
    return bool(environment.is_production) or bool((environment.policy or {}).get("requires_approval"))


def _tool_data_classifications(db: Session, version: AgentVersion) -> list[str]:
    tool_ids: list[uuid.UUID] = []
    for raw in version.tools_snapshot or []:
        try:
            tool_ids.append(uuid.UUID(raw))
        except (ValueError, TypeError):
            continue
    if not tool_ids:
        return []
    return list(db.execute(select(Tool.data_classification).where(Tool.id.in_(tool_ids))).scalars())


def _active_deployment_count(db: Session, environment_id: uuid.UUID, agent_id: uuid.UUID, *,
                             exclude_deployment_id: uuid.UUID | None = None) -> int:
    stmt = select(func.count(AgentDeployment.id)).where(
        AgentDeployment.environment_id == environment_id,
        AgentDeployment.agent_id == agent_id,
        AgentDeployment.lifecycle_state == "ACTIVE",
    )
    if exclude_deployment_id is not None:
        stmt = stmt.where(AgentDeployment.id != exclude_deployment_id)
    return db.execute(stmt).scalar_one()


def evaluate(db: Session, environment, version: AgentVersion, agent_id: uuid.UUID, *,
            exclude_deployment_id: uuid.UUID | None = None) -> PolicyViolation | None:
    policy = environment.policy or {}
    violation = check_prohibited(version.policy_snapshot, environment.name)
    if violation is None:
        violation = check_allowed_models(policy, (version.model_configuration or {}).get("model"))
    if violation is None:
        violation = check_allowed_data_classifications(policy, _tool_data_classifications(db, version))
    if violation is None:
        active = _active_deployment_count(db, environment.id, agent_id, exclude_deployment_id=exclude_deployment_id)
        violation = check_concurrency(policy, active)
    if violation is None:
        violation = check_change_window(policy)
    return violation
