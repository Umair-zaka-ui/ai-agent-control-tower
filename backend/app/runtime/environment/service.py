"""ACT-SRS-M3 §3.2 -- ``EnvironmentService`` (the governed environment
catalog), ``PromotionPathService`` (the org-configured graph of legal
promotions), and ``PromotionService`` (the promotion operation itself).

``PromotionService.promote`` is the sharp edge of this phase (SRS §3.2):
it must move a version's deployment eligibility into a new environment
while preserving the *exact same* immutable ``AgentVersion`` row -- same
id, same ``checksum``, same ``manifest_digest``, same ``signature_id``.
It does this structurally, not by convention: the new deployment is built
by ``app.runtime.services.DeploymentService.create`` from the *same*
``AgentVersion`` object already loaded from the source deployment
(``self.db.get(AgentVersion, deployment.agent_version_id)``) -- nothing
here ever constructs a new ``AgentVersion`` row, copies one, or assigns to
any of its columns; ``PROMOTION_IMMUTABILITY_VIOLATION`` exists only as a
defensive assertion against a future regression, not as a code path this
module's own logic can actually reach.

Driven entirely through Phase 3.1's own machinery, never a parallel one:
the new deployment is created via the legacy ``DeploymentService.create``
(the same constructor 3.1's own ``DeploymentLifecycleService.create``
uses) and then advanced via ``DeploymentLifecycleService.transition``/
``start_deploying`` -- the *only* writer of ``lifecycle_state``. Promotion
is idempotent via the exact same reusable ``IdempotencyService``
(``app.runtime.deployment.idempotency``) 3.1 built, scoped to the
``"deployment.promote"`` operation -- not a new mechanism.

Supersession: per ``app.runtime.deployment.lifecycle``'s own module
docstring, the ``ACTIVE|PAUSED -> SUPERSEDED`` edge is declared in 3.1 but
left undriven until "3.2 drives this when a newer deployment is promoted
into the same environment slot" -- implemented here: after a promoted
deployment reaches ``ACTIVE``, any other deployment of the same agent
already ``ACTIVE``/``PAUSED`` in the *target* environment is moved to
``SUPERSEDED`` (never ``RETIRED`` -- a superseded deployment's lineage to
its successor is preserved via ``superseded_by_deployment_id``, unlike a
plain retirement)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.runtime import AgentDeployment, AgentVersion, DeploymentEvent, Environment, PromotionPath
from app.models.user import User
from app.runtime.deployment.idempotency import IdempotencyService
from app.runtime.deployment.service import DeploymentLifecycleService
from app.runtime.environment import policy as environment_policy
from app.runtime.services import DeploymentService, _record_event

# M3-3.2-FR-001 -- the standard set every organization is entitled to;
# ``PRODUCTION`` defaults ``is_production=True`` (stricter approval
# defaults, see ``environment_policy.requires_approval``), the rest do not.
_STANDARD_ENVIRONMENTS: tuple[tuple[str, str, bool], ...] = (
    ("DEVELOPMENT", "Development", False),
    ("TEST", "Test", False),
    ("STAGING", "Staging", False),
    ("PRODUCTION", "Production", True),
    ("SANDBOX", "Sandbox", False),
)

# M3-3.2 §15 -- the default promotion graph seeded for every organization
# that gets its standard environments seeded (migration 0038 and this
# service's own ``ensure_seeded``, kept identical so a brand-new org and a
# migrated one end up in the same state). The build prompt explicitly
# allows either choice ("seed default paths... or document that paths
# start empty"); a linear DEV->TEST->STAGING->PRODUCTION chain is seeded
# because the build prompt itself gives that exact chain as the running
# example throughout, and an org with zero configured paths cannot
# promote *anything* out of the box, which would make the promotion API
# untestable/unusable without an extra, undocumented setup step.
# STAGING->PRODUCTION alone defaults ``requires_approval=True``, mirroring
# the pre-existing mission-critical-production precedent
# (``DeploymentService.deploy``/``DeploymentLifecycleService.
# _requires_deployment_approval``). SANDBOX is deliberately left out of the
# chain -- an isolated environment, not a promotion rung.
_DEFAULT_PATHS: tuple[tuple[str, str, bool], ...] = (
    ("DEVELOPMENT", "TEST", False),
    ("TEST", "STAGING", False),
    ("STAGING", "PRODUCTION", True),
)


class EnvironmentService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, actor: User) -> list[Environment]:
        stmt = select(Environment).where(
            Environment.organization_id == actor.organization_id
        ).order_by(Environment.name)
        return list(self.db.execute(stmt).scalars())

    def get_or_404(self, actor: User, environment_id: uuid.UUID) -> Environment:
        environment = self.db.get(Environment, environment_id)
        if environment is None or environment.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.ENVIRONMENT_NOT_FOUND, "Environment not found.")
        return environment

    def get_by_name(self, organization_id: uuid.UUID, name: str) -> Environment | None:
        stmt = select(Environment).where(
            Environment.organization_id == organization_id, Environment.name == name.upper(),
        )
        return self.db.execute(stmt).scalars().first()

    def ensure_seeded(self, organization_id: uuid.UUID) -> list[Environment]:
        """Defensive get-or-create for the standard set, mirroring
        ``ReleaseChannelService.ensure_seeded``'s own precedent -- called
        from ``list``/``create`` so an organization created before this
        phase (or whose migration-time seed rows were somehow removed)
        still gets a usable catalog on first touch, per-organization
        (unlike the global release-channel catalog)."""
        existing = {e.name for e in self.db.execute(
            select(Environment).where(Environment.organization_id == organization_id)
        ).scalars()}
        created: dict[str, Environment] = {}
        for name, display_name, is_production in _STANDARD_ENVIRONMENTS:
            if name not in existing:
                env = Environment(organization_id=organization_id, name=name,
                                  display_name=display_name, is_production=is_production)
                self.db.add(env)
                created[name] = env
        if created:
            self.db.flush()
            all_envs = {**{e.name: e for e in self.db.execute(
                select(Environment).where(Environment.organization_id == organization_id)
            ).scalars()}}
            for from_name, to_name, requires_approval in _DEFAULT_PATHS:
                from_env, to_env = all_envs.get(from_name), all_envs.get(to_name)
                if from_env is None or to_env is None:
                    continue
                path_exists = self.db.execute(select(PromotionPath).where(
                    PromotionPath.organization_id == organization_id,
                    PromotionPath.from_environment_id == from_env.id,
                    PromotionPath.to_environment_id == to_env.id,
                )).scalars().first()
                if path_exists is None:
                    self.db.add(PromotionPath(
                        organization_id=organization_id, from_environment_id=from_env.id,
                        to_environment_id=to_env.id, requires_approval=requires_approval,
                    ))
            self.db.flush()
        return self.list_by_org(organization_id)

    def list_by_org(self, organization_id: uuid.UUID) -> list[Environment]:
        stmt = select(Environment).where(Environment.organization_id == organization_id).order_by(Environment.name)
        return list(self.db.execute(stmt).scalars())

    def create(self, actor: User, payload: dict) -> Environment:
        self.ensure_seeded(actor.organization_id)
        name = payload["name"].strip().upper()
        if self.get_by_name(actor.organization_id, name) is not None:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, f"Environment '{name}' already exists.")
        environment = Environment(
            organization_id=actor.organization_id, name=name,
            display_name=payload.get("display_name") or name.title(),
            is_production=bool(payload.get("is_production", False)),
            policy=payload.get("policy") or {},
        )
        self.db.add(environment)
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_ENVIRONMENT_CREATED, actor,
                     organization_id=actor.organization_id, meta={"name": name})
        self.db.commit()
        self.db.refresh(environment)
        return environment

    def update(self, actor: User, environment_id: uuid.UUID, payload: dict) -> Environment:
        environment = self.get_or_404(actor, environment_id)
        if payload.get("display_name") is not None:
            environment.display_name = payload["display_name"]
        if payload.get("is_production") is not None:
            environment.is_production = bool(payload["is_production"])
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_ENVIRONMENT_UPDATED, actor,
                     organization_id=actor.organization_id, meta={"environment_id": str(environment.id)})
        self.db.commit()
        self.db.refresh(environment)
        return environment

    def set_policy(self, actor: User, environment_id: uuid.UUID, policy: dict) -> Environment:
        environment = self.get_or_404(actor, environment_id)
        environment.policy = policy
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_ENVIRONMENT_POLICY_UPDATED, actor,
                     organization_id=actor.organization_id, meta={"environment_id": str(environment.id)})
        self.db.commit()
        self.db.refresh(environment)
        return environment


class PromotionPathService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, actor: User) -> list[PromotionPath]:
        stmt = select(PromotionPath).where(PromotionPath.organization_id == actor.organization_id)
        return list(self.db.execute(stmt).scalars())

    def get_or_404(self, actor: User, path_id: uuid.UUID) -> PromotionPath:
        path = self.db.get(PromotionPath, path_id)
        if path is None or path.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.PROMOTION_PATH_NOT_DEFINED, "Promotion path not found.")
        return path

    def create(self, actor: User, from_environment_id: uuid.UUID, to_environment_id: uuid.UUID, *,
              requires_approval: bool = False) -> PromotionPath:
        env_service = EnvironmentService(self.db)
        env_service.get_or_404(actor, from_environment_id)
        env_service.get_or_404(actor, to_environment_id)
        existing = self.db.execute(select(PromotionPath).where(
            PromotionPath.organization_id == actor.organization_id,
            PromotionPath.from_environment_id == from_environment_id,
            PromotionPath.to_environment_id == to_environment_id,
        )).scalars().first()
        if existing is not None:
            return existing
        path = PromotionPath(
            organization_id=actor.organization_id, from_environment_id=from_environment_id,
            to_environment_id=to_environment_id, requires_approval=requires_approval,
        )
        self.db.add(path)
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_PROMOTION_PATH_CREATED, actor,
                     organization_id=actor.organization_id,
                     meta={"from_environment_id": str(from_environment_id), "to_environment_id": str(to_environment_id)})
        self.db.commit()
        self.db.refresh(path)
        return path

    def delete(self, actor: User, path_id: uuid.UUID) -> None:
        path = self.get_or_404(actor, path_id)
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_PROMOTION_PATH_DELETED, actor,
                     organization_id=actor.organization_id, meta={"promotion_path_id": str(path_id)})
        self.db.delete(path)
        self.db.commit()


class PromotionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _blocked(self, actor: User, deployment: AgentDeployment, environment: Environment | None,
                code: str, message: str) -> None:
        """Records the SRS §8 governance signal (a blocked promotion is
        audited, not just rejected) *before* raising -- the commit here
        persists independently of the exception unwinding the rest of the
        request; ``IdempotencyService.execute`` (the caller two frames up)
        still correctly discards its own now-orphaned pending claim row on
        the way out (see that module's own docstring)."""
        _record_event(self.db, AuthorizationAuditEvent.RELEASE_PROMOTION_BLOCKED, actor,
                     organization_id=actor.organization_id, agent_id=deployment.agent_id,
                     deployment_id=deployment.id, severity="WARNING",
                     meta={"target_environment": environment.name if environment else None,
                           "code": code, "reason": message})
        self.db.commit()
        raise IdentityError(code, message)

    def promote(self, actor: User, deployment: AgentDeployment, to_environment_id: uuid.UUID, *,
               reason: str | None = None, idempotency_key: str | None = None) -> tuple[dict, bool]:
        from app.runtime.schemas import DeploymentRead  # local import: schemas is a leaf module

        def _do() -> dict:
            to_environment = EnvironmentService(self.db).get_or_404(actor, to_environment_id)
            from_environment_id = deployment.environment_id
            if from_environment_id is None:
                self._blocked(actor, deployment, to_environment, ErrorCode.PROMOTION_PATH_NOT_DEFINED,
                             "The source deployment has no governed environment; it cannot be promoted "
                             "until it is re-created or migrated onto one.")
            path = self.db.execute(select(PromotionPath).where(
                PromotionPath.organization_id == actor.organization_id,
                PromotionPath.from_environment_id == from_environment_id,
                PromotionPath.to_environment_id == to_environment.id,
            )).scalars().first()
            if path is None:
                self._blocked(actor, deployment, to_environment, ErrorCode.PROMOTION_PATH_NOT_DEFINED,
                             "No promotion path is configured between the source and target environments.")

            agent = self.db.get(Agent, deployment.agent_id)
            # THE immutable source version, loaded once and never re-constructed,
            # copied, or written to anywhere below (SRS §3.2's own sharp edge).
            version = self.db.get(AgentVersion, deployment.agent_version_id)

            # Fail fast, before any deployment row is created, so an obvious
            # policy violation never leaves an orphan DRAFT deployment behind.
            # ``DeploymentLifecycleService.start_deploying`` below runs this
            # exact same check again (its own single choke point, shared with
            # a plain deploy) once the new deployment exists -- intentionally
            # redundant, not a second, diverging policy engine.
            violation = environment_policy.evaluate(self.db, to_environment, version, agent.id)
            if violation is not None:
                self._blocked(actor, deployment, to_environment, violation.code, violation.message)

            new_payload = {
                "environment": to_environment.name,
                "environment_id": to_environment.id,
                "deployment_strategy": deployment.deployment_strategy,
                "desired_replicas": deployment.desired_replicas,
                "configuration": dict(deployment.configuration or {}),
                "secret_references": dict(deployment.secret_references or {}),
                "runtime_limits": dict(deployment.runtime_limits or {}),
            }
            new_deployment = DeploymentService(self.db).create(actor, agent, version, new_payload)
            # Defensive only -- structurally impossible given the line above
            # passes this exact, already-loaded `version` object straight
            # through; see this module's own docstring.
            if new_deployment.agent_version_id != version.id:
                raise IdentityError(ErrorCode.PROMOTION_IMMUTABILITY_VIOLATION,
                                   "Promotion must preserve the exact source version.")
            self.db.add(DeploymentEvent(
                deployment_id=new_deployment.id, organization_id=new_deployment.organization_id,
                from_state=None, to_state="DRAFT",
                event_type=AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_CREATED.value,
                actor_id=actor.id, idempotency_key=idempotency_key,
            ))
            self.db.commit()
            self.db.refresh(new_deployment)

            lifecycle_service = DeploymentLifecycleService(self.db)
            reason_text = reason or (
                f"Promoted version {version.version} from {deployment.environment} to {to_environment.name}."
            )
            new_deployment = lifecycle_service.transition(actor, new_deployment, "VALIDATING", reason=reason_text)
            new_deployment = lifecycle_service.transition(actor, new_deployment, "READY", reason=reason_text)
            new_deployment = lifecycle_service.start_deploying(actor, new_deployment, reason=reason_text)

            if new_deployment.lifecycle_state == "ACTIVE":
                others = self.db.execute(select(AgentDeployment).where(
                    AgentDeployment.agent_id == agent.id,
                    AgentDeployment.environment_id == to_environment.id,
                    AgentDeployment.id != new_deployment.id,
                    AgentDeployment.lifecycle_state.in_(("ACTIVE", "PAUSED")),
                )).scalars().all()
                for other in others:
                    other.superseded_by_deployment_id = new_deployment.id
                    lifecycle_service.transition(
                        actor, other, "SUPERSEDED",
                        reason=f"Superseded by promoted deployment {new_deployment.id}.")

            _record_event(self.db, AuthorizationAuditEvent.RELEASE_PROMOTED, actor,
                         organization_id=actor.organization_id, agent_id=agent.id,
                         deployment_id=new_deployment.id,
                         meta={"source_deployment_id": str(deployment.id),
                               "from_environment": deployment.environment, "to_environment": to_environment.name,
                               "agent_version_id": str(version.id), "checksum": version.checksum})
            self.db.commit()
            self.db.refresh(new_deployment)
            return DeploymentRead.model_validate(new_deployment).model_dump(mode="json")

        request_payload = {
            "deployment_id": str(deployment.id), "to_environment_id": str(to_environment_id), "reason": reason,
        }
        return IdempotencyService(self.db).execute(
            organization_id=actor.organization_id, operation="deployment.promote",
            key=idempotency_key, payload=request_payload, fn=_do,
        )
