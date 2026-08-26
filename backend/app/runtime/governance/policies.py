"""Governance policy CRUD and scope resolution (M4-4.3-FR-014).

Resolution is most-specific-wins, the same rule ``RollbackTriggerPolicy``
already uses for the same shape of question, so an operator who has learned one
of this platform's scoped-policy models has learned both.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.errors import ErrorCode, IdentityError
from app.models.user import User
from app.models.runtime import RuntimeGovernancePolicy
from app.runtime.governance.constraints import validate_constraints


class GovernancePolicyService:
    """CRUD plus most-specific-wins resolution.

    **Tenant isolation is applied on every query**, including the resolution
    used on the execution path: a policy belonging to another organization can
    neither be read, written, nor allowed to govern this tenant's executions.
    The only cross-tenant rows are *platform defaults* (``organization_id IS
    NULL``), which no tenant-facing method here can create — see ``create``.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Resolution — the execution path
    # ------------------------------------------------------------------ #
    def resolve(self, organization_id: uuid.UUID, *, environment_id: uuid.UUID | None,
                agent_id: uuid.UUID | None) -> list[RuntimeGovernancePolicy]:
        """Every enabled policy that applies, most specific first.

        A **list**, not a single winner, and that is the substantive difference
        from ``RollbackTriggerPolicyService.resolve``. Rollback answers "which
        rule fires", where picking one is right. Governance answers "what may
        this execution do", where picking one would mean a narrow per-agent
        policy *silently switched off* the organization-wide mandatory ceiling
        above it. Constraints accumulate; the most specific is merely evaluated
        first, so its message is the one an operator sees when several would
        object.

        Returning an empty list is a real answer and the safe one: absent any
        configured policy, only the engine's built-in loop-safety caps apply,
        which is exactly the pre-4.3 behaviour.
        """
        rows = list(self.db.execute(
            select(RuntimeGovernancePolicy).where(
                RuntimeGovernancePolicy.enabled.is_(True),
                RuntimeGovernancePolicy.organization_id.in_([organization_id, None]),
            )
        ).scalars())

        def applies(row: RuntimeGovernancePolicy) -> bool:
            if row.environment_id is not None and row.environment_id != environment_id:
                return False
            if row.agent_id is not None and row.agent_id != agent_id:
                return False
            return True

        def specificity(row: RuntimeGovernancePolicy) -> tuple[int, int, int]:
            # Most specific first; ties broken by creation order so resolution
            # is deterministic rather than dependent on plan order.
            return (
                -(2 if row.environment_id is not None else 0)
                - (1 if row.agent_id is not None else 0),
                0 if row.organization_id is not None else 1,
                0,
            )

        matching = [row for row in rows if applies(row)]
        matching.sort(key=lambda row: (specificity(row), row.created_at, str(row.id)))
        return matching

    # ------------------------------------------------------------------ #
    # CRUD — the management API
    # ------------------------------------------------------------------ #
    def get_or_404(self, actor: User, policy_id: uuid.UUID) -> RuntimeGovernancePolicy:
        """A policy in another organization is reported as *not found*, never
        as forbidden (§34): distinguishing the two would confirm the row
        exists to a tenant that must not know it does. Platform defaults
        (``organization_id IS NULL``) are readable by any tenant they govern —
        a rule you are subject to but cannot see is not governance."""
        policy = self.db.get(RuntimeGovernancePolicy, policy_id)
        if policy is None or (policy.organization_id is not None
                              and policy.organization_id != actor.organization_id):
            raise IdentityError(ErrorCode.GOVERNANCE_POLICY_NOT_FOUND, "Runtime governance policy not found.")
        return policy

    def list(self, actor: User, *, enabled: bool | None = None) -> list[RuntimeGovernancePolicy]:
        stmt = select(RuntimeGovernancePolicy).where(
            RuntimeGovernancePolicy.organization_id.in_([actor.organization_id, None]))
        if enabled is not None:
            stmt = stmt.where(RuntimeGovernancePolicy.enabled.is_(enabled))
        return list(self.db.execute(
            stmt.order_by(RuntimeGovernancePolicy.created_at.desc())).scalars())

    def create(self, actor: User, payload: dict) -> RuntimeGovernancePolicy:
        self._validate(payload.get("constraints"))
        policy = RuntimeGovernancePolicy(
            # Always the actor's own organization. A tenant cannot author a
            # platform default (``organization_id IS NULL``) through this API,
            # because a row written here governs every organization on the
            # platform and no per-tenant permission should be able to reach
            # that far -- the same reasoning that makes the PLATFORM kill-switch
            # scope check identity rather than only an RBAC grant (§60).
            organization_id=actor.organization_id,
            environment_id=payload.get("environment_id"),
            agent_id=payload.get("agent_id"),
            name=payload["name"],
            description=payload.get("description"),
            constraints=payload.get("constraints") or {},
            mandatory=bool(payload.get("mandatory", False)),
            enabled=bool(payload.get("enabled", True)),
            created_by=actor.id,
        )
        self.db.add(policy)
        self.db.commit()
        self.db.refresh(policy)
        return policy

    def update(self, actor: User, policy_id: uuid.UUID, payload: dict) -> RuntimeGovernancePolicy:
        policy = self.get_or_404(actor, policy_id)
        if policy.organization_id is None:
            raise IdentityError(
                ErrorCode.PERMISSION_DENIED,
                "Platform-default governance policies cannot be modified by an organization.")
        if "constraints" in payload:
            self._validate(payload.get("constraints"))
            policy.constraints = payload["constraints"] or {}
        for field in ("name", "description", "mandatory", "enabled", "environment_id", "agent_id"):
            if field in payload:
                setattr(policy, field, payload[field])
        self.db.commit()
        self.db.refresh(policy)
        return policy

    @staticmethod
    def _validate(constraints) -> None:
        if constraints is None:
            return
        problems = validate_constraints(constraints)
        if problems:
            raise IdentityError(ErrorCode.GOVERNANCE_POLICY_INVALID, " ".join(problems))
