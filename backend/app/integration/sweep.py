"""Connector-health sweep (Phase 2.1.3 ``ACT-INT-FR-043``, rehoused in 3.8).

This is the *work* the interim in-process scheduler used to do, extracted
verbatim when that scheduler was retired in Phase 3.8. The functions below are
byte-for-byte the ones Phase 2.1.3 wrote and tested; only their address
changed. What did **not** survive the move is the machinery around them -- the
``asyncio`` background task, the ``start``/``stop`` pair, and the
``app/main.py`` lifespan hook -- because that is precisely the interim
scheduling mechanism Phase 3.8's real distributed scheduler replaces.

The interim module's own docstring specified this retirement in advance:
*"delete this module, delete its one call site in ``app/main.py``'s lifespan,
register the same iteration as a real job. Nothing here is designed to be
extended in place into that system."* It was not extended in place.

``run_sweep_once`` is now called by the ``integration.connector_health_sweep``
handler (``app/scheduler/handlers.py``), on a lease, from whichever scheduler
instance claims the job -- so the sweep gained distribution and crash recovery
without its own logic changing at all.

``settings.CONNECTOR_HEALTH_SCHEDULER_ENABLED`` still governs whether sweeping
happens automatically; it now decides whether the seeded job definition is
created **enabled** rather than whether an in-process task starts. Default
remains false, so a deployment that never opted in is unaffected by the
retirement, and on-demand checks via ``ConnectorHealthService.check()`` remain
the deterministic path this codebase's own tests use.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.database import SessionLocal
from app.integration.health import ConnectorHealthService
from app.models.integration import ConnectorInstance

logger = logging.getLogger("control_tower.integration.sweep")


def _active_instance_ids() -> list[tuple]:
    db = SessionLocal()
    try:
        return list(db.execute(
            select(ConnectorInstance.id, ConnectorInstance.organization_id)
            .where(ConnectorInstance.lifecycle_state == "active")
        ).all())
    finally:
        db.close()


def _check_one(instance_id, organization_id) -> None:
    db = SessionLocal()
    try:
        ConnectorHealthService(db).check(None, organization_id, instance_id, check_type="SCHEDULED")
    except Exception:  # noqa: BLE001 -- one instance's failure must never take down the sweep
        logger.exception("scheduled health check failed for connector instance %s", instance_id)
    finally:
        db.close()


def run_sweep_once() -> int:
    """One full pass over every active instance -- synchronous, blocking.

    Uses its own short-lived ``Session`` per instance rather than the caller's.
    That was already true before the move and matters more now: the scheduler
    commits its claim transaction *before* dispatching a handler, and a sweep
    that held the dispatching session open across dozens of health probes would
    reintroduce exactly the long-lived-transaction shape the M1 deadlock taught
    this codebase to avoid."""
    rows = _active_instance_ids()
    for instance_id, organization_id in rows:
        _check_one(instance_id, organization_id)
    return len(rows)
