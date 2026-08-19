"""Phase 3.9 -- the execution worker entrypoint.

    python -m app.workers.runner
    python -m app.workers.runner --concurrency 4 --cohort canary-a
    python -m app.workers.runner --max-ticks 1        # one poll, then exit

Run as many as you want, on as many machines as you want. They coordinate
through Postgres and nothing else -- no broker, no leader, no membership
protocol. A worker that dies is noticed by whichever peer next sweeps, and the
executions it held are recovered by the lease its claim already wrote.

The API process deliberately does **not** start one, exactly as Phase 3.8
decided for the scheduler. An execution worker consumes provider quota and
spends real money on model calls; that must be an explicit act of deployment,
not a side effect of serving HTTP.
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.core.config import settings
from app.workers.worker import ExecutionWorker

logger = logging.getLogger("app.workers.runner")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.workers.runner",
        description="Run an agent-execution worker against the Postgres queue.")
    parser.add_argument("--worker-id", default=None,
                        help="Stable identity for this process (default: host + random suffix).")
    parser.add_argument("--cohort", default=None,
                        help=f"Rolling cohort to join (default: {settings.WORKER_COHORT!r}).")
    parser.add_argument("--concurrency", type=int, default=None,
                        help=f"Executions to run at once (default: {settings.WORKER_CONCURRENCY}).")
    parser.add_argument("--poll-interval", type=float, default=None,
                        help=f"Seconds between polls (default: {settings.WORKER_POLL_INTERVAL_SECONDS}).")
    parser.add_argument("--max-ticks", type=int, default=None,
                        help="Stop after this many polls. Omit to run until signalled.")
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    worker = ExecutionWorker(worker_id=args.worker_id, cohort=args.cohort,
                             concurrency=args.concurrency)
    worker.install_signal_handlers()
    worker.start()
    logger.info("execution worker %s started (cohort=%s concurrency=%d)",
                worker.worker_id, worker.cohort, worker.concurrency)
    try:
        ticks = worker.run(max_ticks=args.max_ticks, poll_interval=args.poll_interval)
        logger.info("execution worker %s ran %d tick(s)", worker.worker_id, ticks)
    finally:
        # Always graceful: drain, finish what is in flight, then leave the
        # fleet. A worker that exits without this leaves a registration that
        # looks alive until it goes stale, and executions that look owned
        # until their lease lapses -- both recoverable, both avoidable.
        worker.shutdown()
        logger.info("execution worker %s stopped", worker.worker_id)
    return 0


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    sys.exit(main())
