"""Phase 3.9 -- the distributed execution worker fleet.

A sibling of ``app/scheduler/`` and for the same reason: a worker process is
platform infrastructure that *drives* the runtime domain rather than a service
inside it. Launch one with ``python -m app.workers.runner``.
"""
