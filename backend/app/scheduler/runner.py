"""Phase 3.8 -- the scheduler process entrypoint.

    python -m app.scheduler.runner

Run it more than once -- on one machine or many -- to get a fleet. There is no
leader election, no coordination protocol and no configuration listing the
peers: instances discover work by competing for it, and ``SKIP LOCKED`` makes
losing that competition free. Adding an instance is starting another process.

Each tick does at most one unit of work (recover one stale run, else claim one
due job, else nothing) and then sleeps. That is deliberately unambitious: a
tick that drained the whole queue would hold one instance on a long backlog
while its peers idled, and the *fleet* drains faster when every instance takes
one item and comes back.

The loop owns a ``Session`` per tick rather than for its lifetime. A
long-lived session in a polling loop accumulates a snapshot that grows stale --
and this codebase has already been bitten once by a long-lived transaction (see
``SchedulerService``'s module docstring on the M1 deadlock).
"""

from __future__ import annotations

import argparse
import logging
import signal
import time

from app.core.config import settings
from app.core.database import SessionLocal
from app.scheduler.handlers import ensure_platform_jobs
from app.scheduler.service import SchedulerService, default_instance_id

logger = logging.getLogger("control_tower.scheduler.runner")

DEFAULT_POLL_SECONDS = 5.0

_stopping = False


def _handle_signal(signum, _frame) -> None:
    """Stop after the current tick rather than mid-handler.

    A scheduler killed mid-handler is not a correctness problem -- its lease
    expires and a peer recovers the run -- but finishing the tick avoids
    manufacturing that work for no reason."""
    global _stopping
    _stopping = True
    logger.info("scheduler received signal %s; stopping after the current tick", signum)


def tick(instance_id: str) -> bool:
    """One unit of work. Returns whether anything was done.

    Its own session, opened and closed here, so a handler that leaves the
    session in a bad state cannot poison the next tick."""
    db = SessionLocal()
    try:
        return SchedulerService(db, instance_id=instance_id).run_once() is not None
    except Exception:  # noqa: BLE001 -- the loop must outlive any one tick
        logger.exception("scheduler tick failed")
        db.rollback()
        return False
    finally:
        db.close()


def run_forever(instance_id: str | None = None, *, poll_seconds: float = DEFAULT_POLL_SECONDS,
                max_ticks: int | None = None) -> int:
    """The loop. ``max_ticks`` exists so tests can drive a bounded number of
    iterations deterministically instead of racing a sleep."""
    instance_id = instance_id or default_instance_id()
    logger.info("scheduler instance %s starting (poll=%.1fs)", instance_id, poll_seconds)

    ticks = 0
    while not _stopping and (max_ticks is None or ticks < max_ticks):
        did_work = tick(instance_id)
        ticks += 1
        if not did_work and not _stopping:
            # Only sleep when idle: with work available, come straight back for
            # the next item.
            time.sleep(poll_seconds)
    logger.info("scheduler instance %s stopped after %d ticks", instance_id, ticks)
    return ticks


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Agent Control Tower scheduler instance")
    parser.add_argument("--instance-id", default=None,
                        help="Override the derived host:pid identity (useful in containers).")
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--max-ticks", type=int, default=None,
                        help="Exit after this many ticks; omit to run until signalled.")
    parser.add_argument("--seed-platform-jobs", action="store_true",
                        help="Create the platform-level job definitions if absent.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    if args.seed_platform_jobs:
        db = SessionLocal()
        try:
            # Seeded with the same default-off posture the interim scheduler
            # had: retiring an opt-in mechanism must not turn it on.
            created = ensure_platform_jobs(
                db, enabled=settings.CONNECTOR_HEALTH_SCHEDULER_ENABLED)
            logger.info("seeded %d platform job definition(s)", len(created))
        finally:
            db.close()

    run_forever(args.instance_id, poll_seconds=args.poll_seconds, max_ticks=args.max_ticks)


if __name__ == "__main__":
    main()
