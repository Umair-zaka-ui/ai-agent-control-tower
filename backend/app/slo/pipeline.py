"""Phase 4.7 -- the interim, idempotent evaluate op (M4-4.7-FR-030, AC-11).

One operation: evaluate every enabled SLO for a tenant, raise an alert for each
breach, resolve the alert for each objective that has recovered, and link an
alert to every significant behavioral finding since the last sweep. It is
**idempotent** at two levels -- Phase 3.1's ``Idempotency-Key`` on the request,
and the ``(slo_id, window_start, window_end)`` / partial-unique-dedup
constraints beneath it -- so Phase 3.8's scheduler can adopt it as a
registration rather than a rewrite, exactly as 4.5, 3.7 and 3.5 built their own
interim ops. **No scheduler is built here.**

Non-gating: a failure anywhere in this op produces no evaluation and no alert
and cannot touch an execution (§9).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.runtime import SLODefinition
from app.slo.alerts import AlertService
from app.slo.evaluator import SLOEvaluator

#: How far back the behavioral-finding link step looks. Bounded so a scheduled
#: run does not re-sweep the entire finding history every cycle.
_FINDING_LOOKBACK = timedelta(days=1)


def run_slo_evaluation(db: Session, *, organization_id: uuid.UUID,
                       window_end: datetime | None = None) -> dict:
    window_end = window_end or datetime.now(timezone.utc)
    evaluator = SLOEvaluator(db)
    alerts = AlertService(db)

    results = evaluator.evaluate_all(organization_id, window_end=window_end)

    raised: list[str] = []
    resolved: list[str] = []
    for result in results:
        if result.breached:
            slo = db.get(SLODefinition, result.slo_id)
            alert = alerts.raise_from_slo(result, slo=slo)
            if alert is not None:
                raised.append(str(alert.id))
        elif result.met:
            cleared = alerts.clear_from_slo(result)
            if cleared is not None:
                resolved.append(str(cleared.id))

    linked = alerts.link_recent_behavioral_findings(
        organization_id, since=window_end - _FINDING_LOOKBACK)

    return {
        "evaluated_at": window_end.isoformat(),
        "slos_evaluated": len(results),
        "states": _tally(r.state.value for r in results),
        "alerts_raised": raised,
        "alerts_resolved": resolved,
        "behavioral_alerts_linked": [str(a.id) for a in linked],
        "evaluations": [
            {
                "slo_id": str(r.slo_id), "sli": r.sli, "state": r.state.value,
                "observed_value": r.observed_value, "target": r.target,
                "sample_count": r.sample_count,
                "budget_consumed": r.budget_consumed,
                "budget_remaining": r.budget_remaining,
                "evaluation_id": str(r.evaluation_id) if r.evaluation_id else None,
            }
            for r in results
        ],
    }


def _tally(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out
