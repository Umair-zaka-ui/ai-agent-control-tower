"""Phase 5.6a.2 SRS ACT-TLX-FR-029 -- the per-execution concurrent outbound
request ceiling.

Pure, in-process bookkeeping: a live count of in-flight HTTP tool calls per
execution id, guarded by a single lock -- the same "no network, no
database, isolated and directly testable" discipline ``egress_guard.py``
established for the SSRF boundary.

Today ``ExecutionWorkerService`` issues tool calls strictly sequentially
(one ``ToolGatewayService.invoke()`` call at a time inside a plain
``for`` loop -- see ``services.py``), so this ceiling is never actually
contended in production yet: it exists as the enforcement point 5.6a.3's
model-driven tool loop (which will be able to issue multiple calls from
one execution concurrently) plugs into without needing any new mechanism
of its own. Tested directly with real threads (see
``test_tool_resilience.py``), since today's sequential caller can't
exercise contention on its own.
"""

from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager
from typing import Iterator

_lock = threading.Lock()
_inflight: dict[uuid.UUID, int] = {}


class ToolConcurrencyLimitExceeded(Exception):
    """Raised by ``track()`` when accepting one more concurrent request for
    this execution would exceed the configured ceiling. The caller
    (``ToolGatewayService._invoke_http``) catches this and turns it into a
    normal ``FAILED`` tool-call outcome -- it must never propagate past the
    single call, per this sub-phase's "never abort the execution" rule
    (ACT-TLX-FR-028)."""


@contextmanager
def track(execution_id: uuid.UUID, *, limit: int) -> Iterator[None]:
    """Reserves one concurrent-request slot for ``execution_id`` for the
    duration of the ``with`` block; releases it on the way out regardless
    of how the block exits (success, an exception, anything)."""
    with _lock:
        current = _inflight.get(execution_id, 0)
        if current >= limit:
            raise ToolConcurrencyLimitExceeded(
                f"Execution {execution_id} already has {current} concurrent tool request(s) "
                f"in flight (limit {limit})."
            )
        _inflight[execution_id] = current + 1
    try:
        yield
    finally:
        with _lock:
            remaining = _inflight.get(execution_id, 1) - 1
            if remaining <= 0:
                _inflight.pop(execution_id, None)
            else:
                _inflight[execution_id] = remaining


def current_inflight(execution_id: uuid.UUID) -> int:
    """Test-only introspection hook."""
    with _lock:
        return _inflight.get(execution_id, 0)
