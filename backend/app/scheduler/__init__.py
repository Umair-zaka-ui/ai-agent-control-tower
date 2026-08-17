"""Phase 3.8 -- the distributed scheduler.

A **sibling** of ``app/runtime/`` and ``app/integration/``, not a child of
either. The placement is forced rather than stylistic: this package registers a
connector-health handler, and Milestone 2's mechanically-enforced
runtime-never-knows rule fails the build if the word "connector" appears
anywhere under ``app/runtime/``. A scheduler that drives both domains cannot
live inside one of them -- and that constraint turns out to describe the right
architecture anyway, since the scheduler is platform infrastructure that
happens to run deployment and integration work, not part of either.

Entry points:

- ``SchedulerService`` -- claim, lease, dispatch, heartbeat, recover.
- ``app.scheduler.handlers`` -- the fixed registry; business logic lives in the
  domains these handlers call, never here.
- ``app.scheduler.runner`` -- the process entrypoint (``python -m
  app.scheduler.runner``); run it more than once to get a fleet.
"""

from app.scheduler.service import SchedulerService, default_instance_id

__all__ = ["SchedulerService", "default_instance_id"]
