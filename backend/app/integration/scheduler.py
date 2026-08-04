"""Phase 2.1.3 SRS ACT-INT-FR-043 — interim in-process health-check scheduler.

**INTERIM. REPLACEABLE. Not a distributed job system.** REPO_STATE §10.2
confirms this codebase has no distributed scheduler today, deliberately
— Milestone 3 owns building real workers. This module is the simplest
mechanism consistent with that constraint: one ``asyncio`` background
task, started only when ``settings.CONNECTOR_HEALTH_SCHEDULER_ENABLED``
is true (default **false**, including in every test run — on-demand
checks via ``ConnectorHealthService.check()`` directly are the
deterministic, always-available path this codebase's own tests use, per
AC-19), that wakes on a plain interval and runs an on-demand-equivalent
check against every currently-``active`` connector instance across every
organization. There is no persistence of "which check is due," no
distributed lock, no retry queue — a genuinely single-process,
single-task loop. When Milestone 3's real scheduler exists, the
intended replacement is: delete this module, delete its one call site in
``app/main.py``'s lifespan, register the same iteration as a real job.
Nothing here is designed to be extended in place into that system.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.integration.health import ConnectorHealthService
from app.models.integration import ConnectorInstance

logger = logging.getLogger("control_tower.integration.scheduler")

_task: asyncio.Task | None = None


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
    """One full pass over every active instance — synchronous, blocking.
    Also what the async loop below calls via ``asyncio.to_thread``, and
    what a test drives directly instead of waiting on the loop's sleep."""
    rows = _active_instance_ids()
    for instance_id, organization_id in rows:
        _check_one(instance_id, organization_id)
    return len(rows)


async def _run_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(run_sweep_once)
        except Exception:  # noqa: BLE001 -- the loop itself must never die
            logger.exception("connector health scheduler sweep failed")
        await asyncio.sleep(settings.CONNECTOR_HEALTH_CHECK_INTERVAL_SECONDS)


def start() -> None:
    """Called once from ``app/main.py``'s lifespan startup. A no-op
    unless ``CONNECTOR_HEALTH_SCHEDULER_ENABLED`` is true."""
    global _task
    if not settings.CONNECTOR_HEALTH_SCHEDULER_ENABLED:
        return
    _task = asyncio.create_task(_run_loop())


def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
