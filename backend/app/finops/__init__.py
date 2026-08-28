"""Phase 4.4 (ACT-SRS-M4 §4.4, §10, §11) — cost governance and FinOps.

A **sibling** of ``app/runtime`` and ``app/observability``, for the same reason
``app/observability`` is: the dependency direction should be visible in the
import graph rather than only asserted. This package reads the runtime domain;
the runtime domain does not read it, except at one deliberate seam described
below.

**Real cost is authoritative, and this package computes none of it.** Every
figure here is aggregated from ``agent_executions.cost_amount`` — written by
``PricingService`` (Phase 5.7a.3) inside the transaction that made the
execution true, carrying the ``pricing_version`` that produced it. Nothing in
this package recomputes a cost, and nothing stores a second copy of one.

The legacy ``GET /analytics/cost`` (un-prefixed: the Phase-3 analytics router
is mounted through ``api_router`` with ``settings.API_PREFIX``, which is the
empty string) is a different thing entirely: flat
placeholder constants multiplied by ``agent_actions`` row counts, with no
connection to ``AgentExecution``. It is **deprecated in place** — still
working, now marked — rather than rewired, because rewiring the Phase-3
dashboard mid-milestone would couple this phase's risk to a UI it does not
own. See ``docs/runtime/cost-governance.md``.

**The one seam into enforcement.** A ``HARD_LIMIT`` or ``APPROVAL_REQUIRED``
budget does *not* stop an execution. It supplies a constraint that Phase 4.3's
``RuntimeGovernanceEngine`` evaluates at its cost checkpoints, and the engine
returns the DENY/STOP/CHALLENGE. There is still exactly one place that decides
whether a loop may continue, which is the property 4.3 exists to hold. This
package therefore contains no code that terminates an execution — asserted
structurally in ``tests/runtime/test_cost_governance.py``.

Modules:

- ``aggregation`` — the real-cost read model: summary by scope, time series,
  deterministic spend-anomaly surfacing.
- ``budgets`` — budget CRUD, scope resolution, utilization.
- ``reservations`` — reserve-then-reconcile, the §35 concurrency core.
- ``schemas`` / ``routes`` — the read and management API.
"""

from app.finops.aggregation import CostAggregator  # noqa: F401
from app.finops.budgets import BudgetService  # noqa: F401
from app.finops.reservations import ReservationService  # noqa: F401

__all__ = ["BudgetService", "CostAggregator", "ReservationService"]
