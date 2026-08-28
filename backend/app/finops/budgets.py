"""Budget definitions, scope resolution and utilization (M4-4.4-FR-010..013)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.runtime import AgentDeployment, AgentExecution, AgentVersion, Budget
from app.models.user import User
from app.finops.reservations import BudgetState, ReservationService, period_key

@dataclass(frozen=True)
class _ScopeStub:
    """The two fields ``BudgetGuard._observed_state`` reads off an execution,
    for the utilization endpoint, which has a budget but no execution. A stub
    rather than a nullable parameter so the guard's signature keeps saying it
    needs an execution -- on the hot path it always has one."""

    organization_id: uuid.UUID
    id: uuid.UUID


SCOPE_TYPES = ("ORGANIZATION", "PROJECT", "AGENT", "ENVIRONMENT", "MODEL")
MODES = ("INFORMATIONAL", "WARNING", "HARD_LIMIT", "APPROVAL_REQUIRED")
PERIODS = ("DAILY", "MONTHLY", "EXECUTION")

# Most specific first, the same ordering convention `RollbackTriggerPolicy` and
# `RuntimeGovernancePolicy` already use for the same kind of question.
_SPECIFICITY = {"AGENT": 0, "MODEL": 1, "ENVIRONMENT": 2, "PROJECT": 3, "ORGANIZATION": 4}


@dataclass(frozen=True)
class ExecutionScope:
    """The scope values one execution belongs to, resolved once.

    Assembled by the caller from rows it already has, so budget resolution
    costs no extra query on the execution path beyond the budget lookup
    itself."""

    organization_id: uuid.UUID
    agent_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    environment: str | None = None
    environment_id: uuid.UUID | None = None
    model: str | None = None

    def matches(self, budget: Budget) -> bool:
        if budget.scope_type == "ORGANIZATION":
            return True
        if budget.scope_type == "AGENT":
            return budget.scope_id is not None and budget.scope_id == self.agent_id
        if budget.scope_type == "PROJECT":
            return budget.scope_id is not None and budget.scope_id == self.project_id
        if budget.scope_type == "ENVIRONMENT":
            if budget.scope_id is not None:
                return budget.scope_id == self.environment_id
            return budget.scope_value is not None and budget.scope_value == self.environment
        if budget.scope_type == "MODEL":
            return budget.scope_value is not None and budget.scope_value == self.model
        return False


class BudgetService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Resolution — the execution path
    # ------------------------------------------------------------------ #
    def resolve(self, scope: ExecutionScope) -> list[Budget]:
        """Every enabled budget that applies to this execution, most specific
        first.

        A **list**, not a winner, for the reason Phase 4.3's policy resolution
        returns one: picking a single budget would let a narrow per-agent
        allowance silently switch off the organization-wide ceiling above it.
        Every applicable budget must be satisfied, so the most specific is
        merely evaluated first and its message is the one an operator sees."""
        rows = list(self.db.execute(
            select(Budget).where(
                Budget.organization_id == scope.organization_id,
                Budget.enabled.is_(True),
            )
        ).scalars())
        matching = [b for b in rows if scope.matches(b)]
        matching.sort(key=lambda b: (_SPECIFICITY.get(b.scope_type, 9), b.created_at, str(b.id)))
        return matching

    def scope_for_execution(self, execution: AgentExecution) -> ExecutionScope:
        """Resolve one execution's scope values. Used off the hot path (the
        orchestrator assembles its own from rows it already holds)."""
        agent = self.db.get(Agent, execution.agent_id)
        version = self.db.get(AgentVersion, execution.agent_version_id)
        deployment = (self.db.get(AgentDeployment, execution.deployment_id)
                      if execution.deployment_id else None)
        return ExecutionScope(
            organization_id=execution.organization_id,
            agent_id=execution.agent_id,
            project_id=agent.project_id if agent else None,
            environment=deployment.environment if deployment else None,
            environment_id=deployment.environment_id if deployment else None,
            model=(version.model_configuration or {}).get("model") if version else None,
        )

    # ------------------------------------------------------------------ #
    # Utilization
    # ------------------------------------------------------------------ #
    def utilization(self, budget: Budget, *, execution_id: uuid.UUID | None = None) -> BudgetState:
        """M4-4.4-FR-013 — spent / reserved / remaining for the current period.

        An ``EXECUTION``-period budget has no "current" period of its own — its
        bucket *is* an execution — so asking for its utilization without naming
        one reports the ceiling with nothing committed, which is the honest
        answer rather than an error."""
        from app.finops.guard import BudgetGuard
        from app.finops.reservations import RESERVING_MODES

        if budget.mode not in RESERVING_MODES:
            # A signalling budget keeps no reservation ledger, so reporting its
            # ledger would report 0% forever. See BudgetGuard._observed_state
            # for why the two modes account differently.
            return BudgetGuard(self.db)._observed_state(
                budget, _ScopeStub(budget.organization_id,
                                   execution_id or uuid.UUID(int=0)))
        key = period_key(budget.period, execution_id or uuid.UUID(int=0))
        return ReservationService(self.db).state(budget, key=key)

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #
    def get_or_404(self, actor: User, budget_id: uuid.UUID) -> Budget:
        """Another tenant's budget is reported as *not found*, never as
        forbidden: a financial record's existence is itself information (§34)."""
        budget = self.db.get(Budget, budget_id)
        if budget is None or budget.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.BUDGET_NOT_FOUND, "Budget not found.")
        return budget

    def list(self, actor: User, *, enabled: bool | None = None,
             scope_type: str | None = None) -> list[Budget]:
        stmt = select(Budget).where(Budget.organization_id == actor.organization_id)
        if enabled is not None:
            stmt = stmt.where(Budget.enabled.is_(enabled))
        if scope_type is not None:
            stmt = stmt.where(Budget.scope_type == scope_type)
        return list(self.db.execute(stmt.order_by(Budget.created_at.desc())).scalars())

    def create(self, actor: User, payload: dict) -> Budget:
        self._validate(payload)
        budget = Budget(
            organization_id=actor.organization_id,
            name=payload["name"], description=payload.get("description"),
            scope_type=payload["scope_type"], scope_id=payload.get("scope_id"),
            scope_value=payload.get("scope_value"),
            mode=payload.get("mode", "INFORMATIONAL"),
            period=payload.get("period", "MONTHLY"),
            limit_amount=payload["limit_amount"],
            currency=payload.get("currency", "USD"),
            reservation_estimate=payload.get("reservation_estimate"),
            threshold_percent=payload.get("threshold_percent", 80),
            enabled=bool(payload.get("enabled", True)),
            created_by=actor.id,
        )
        self.db.add(budget)
        self.db.commit()
        self.db.refresh(budget)
        return budget

    def update(self, actor: User, budget_id: uuid.UUID, payload: dict) -> Budget:
        budget = self.get_or_404(actor, budget_id)
        merged = {
            "name": payload.get("name", budget.name),
            "scope_type": payload.get("scope_type", budget.scope_type),
            "scope_id": payload.get("scope_id", budget.scope_id),
            "scope_value": payload.get("scope_value", budget.scope_value),
            "mode": payload.get("mode", budget.mode),
            "period": payload.get("period", budget.period),
            "limit_amount": payload.get("limit_amount", float(budget.limit_amount)),
            "threshold_percent": payload.get("threshold_percent", budget.threshold_percent),
            "reservation_estimate": payload.get("reservation_estimate",
                                                budget.reservation_estimate),
        }
        self._validate(merged)
        for field in ("name", "description", "scope_type", "scope_id", "scope_value", "mode",
                      "period", "limit_amount", "currency", "reservation_estimate",
                      "threshold_percent", "enabled"):
            if field in payload:
                setattr(budget, field, payload[field])
        self.db.commit()
        self.db.refresh(budget)
        return budget

    def delete(self, actor: User, budget_id: uuid.UUID) -> None:
        """Disables rather than deletes.

        A budget's reservations are its accounting history, and deleting the
        row would cascade them away — erasing the record of money that was
        actually spent under it. Disabling stops it governing anything while
        leaving what it governed reconstructable."""
        budget = self.get_or_404(actor, budget_id)
        budget.enabled = False
        self.db.commit()

    @staticmethod
    def _validate(payload: dict) -> None:
        if payload.get("scope_type") not in SCOPE_TYPES:
            raise IdentityError(ErrorCode.BUDGET_INVALID,
                                f"scope_type must be one of {', '.join(SCOPE_TYPES)}.")
        if payload.get("mode", "INFORMATIONAL") not in MODES:
            raise IdentityError(ErrorCode.BUDGET_INVALID,
                                f"mode must be one of {', '.join(MODES)}.")
        if payload.get("period", "MONTHLY") not in PERIODS:
            raise IdentityError(ErrorCode.BUDGET_INVALID,
                                f"period must be one of {', '.join(PERIODS)}.")
        limit = payload.get("limit_amount")
        if limit is None or float(limit) < 0:
            raise IdentityError(ErrorCode.BUDGET_INVALID,
                                "limit_amount must be a non-negative number.")
        threshold = payload.get("threshold_percent", 80)
        if not isinstance(threshold, int) or not 1 <= threshold <= 100:
            raise IdentityError(ErrorCode.BUDGET_INVALID,
                                "threshold_percent must be an integer between 1 and 100.")
        estimate = payload.get("reservation_estimate")
        if estimate is not None and float(estimate) < 0:
            raise IdentityError(ErrorCode.BUDGET_INVALID,
                                "reservation_estimate must not be negative.")
        # A scope that names nothing cannot resolve to anything, so it would be
        # a budget that silently governs no execution -- the same failure mode
        # Phase 4.3 refused for a misspelled constraint key.
        scope_type = payload["scope_type"]
        if scope_type in ("AGENT", "PROJECT") and payload.get("scope_id") is None:
            raise IdentityError(ErrorCode.BUDGET_INVALID,
                                f"{scope_type} scope requires scope_id.")
        if scope_type == "MODEL" and not payload.get("scope_value"):
            raise IdentityError(ErrorCode.BUDGET_INVALID,
                                "MODEL scope requires scope_value (the model identifier).")
        if scope_type == "ENVIRONMENT" and payload.get("scope_id") is None \
                and not payload.get("scope_value"):
            raise IdentityError(
                ErrorCode.BUDGET_INVALID,
                "ENVIRONMENT scope requires scope_id or scope_value (the environment name).")
