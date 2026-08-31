"""Phase 4.6 -- the bounded span buffer (M4-4.6-FR-021, AC-07).

**This is the module the §9 memory trap lives in.** "Buffer telemetry, retry
when the collector comes back" is the obvious design and it is an unbounded
queue: a collector down for an hour buffers an hour of spans and the process
runs out of memory, converting an observability outage into an execution
outage. So this buffer has a hard maximum -- measured in *spans*, the unit the
§36 "memory bounded" claim is about -- and a declared policy when it is reached.
Past that point it *drops*, visibly (every drop is counted), rather than grows.

**The lock is never held across the network.** Producers append under the lock;
the dispatcher drains a batch under the lock and then releases it *before*
touching the sink. A slow or hung collector therefore blocks nothing but the
dispatcher's own thread -- never a producer, never an execution. Same commit-
before-dispatch discipline the rest of the runtime uses, applied to export.

Items are opaque to the buffer; it only needs each to report how many spans it
carries via ``len()``. That keeps the buffer free of any trace/OTel type while
still capping on the real memory driver.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class BufferStats:
    """A point-in-time view of the buffer, for the health surface (FR-022)."""

    item_count: int
    span_count: int
    capacity_spans: int
    enqueued_spans_total: int
    dropped_spans_total: int
    drained_spans_total: int
    full_policy: str

    def as_dict(self) -> dict:
        return {
            "item_count": self.item_count,
            "span_count": self.span_count,
            "capacity_spans": self.capacity_spans,
            "enqueued_spans_total": self.enqueued_spans_total,
            "dropped_spans_total": self.dropped_spans_total,
            "drained_spans_total": self.drained_spans_total,
            "full_policy": self.full_policy,
            "utilization": round(self.span_count / self.capacity_spans, 4)
            if self.capacity_spans else 0.0,
        }


def _weight(item) -> int:
    try:
        return max(1, len(item))
    except TypeError:  # pragma: no cover - defensive
        return 1


class BoundedSpanBuffer:
    """A thread-safe FIFO of export items, hard-capped on total span count.

    Not ``queue.Queue``: that blocks a producer when full and gives no cheap
    "drop oldest" primitive. This drops per an explicit policy and counts every
    drop, which is what turns "buffering" into "bounded buffering"."""

    def __init__(self, *, capacity: int, full_policy: str = "drop_oldest",
                 block_timeout_seconds: float = 0.5) -> None:
        if capacity < 1:
            raise ValueError("buffer capacity must be >= 1")
        self._capacity = capacity
        self._policy = full_policy
        self._block_timeout = block_timeout_seconds
        self._lock = threading.Lock()
        self._not_full = threading.Condition(self._lock)
        self._items: deque = deque()
        self._span_count = 0
        self._enqueued = 0
        self._dropped = 0
        self._drained = 0

    # ------------------------------------------------------------------ #
    # Producer side
    # ------------------------------------------------------------------ #
    def offer(self, item) -> int:
        """Add one item, applying the full-policy. Returns spans dropped.

        Never raises, never blocks unboundedly. ``block_bounded`` waits at most
        ``block_timeout_seconds`` for room, then drops -- "bounded block", never
        "block until"."""
        w = _weight(item)
        dropped = 0
        with self._lock:
            if w >= self._capacity:
                # A single trace larger than the whole buffer: keep only it,
                # drop everything else. Pathological, but must terminate.
                dropped += self._span_count
                self._items.clear()
                self._span_count = 0
            while self._span_count + w > self._capacity:
                freed = self._make_room_locked()
                if freed == 0:
                    # drop_newest, or block_bounded timed out: the incoming item
                    # is the casualty.
                    self._dropped += w
                    return dropped + w
                dropped += freed
            self._items.append(item)
            self._span_count += w
            self._enqueued += w
        return dropped

    def _make_room_locked(self) -> int:
        """Free capacity per the policy; returns spans freed. Caller holds lock."""
        if self._policy == "drop_newest":
            return 0
        if self._policy == "block_bounded":
            deadline = time.monotonic() + self._block_timeout
            while self._items and self._span_count >= self._capacity \
                    and time.monotonic() < deadline:
                self._not_full.wait(timeout=max(0.0, deadline - time.monotonic()))
            if self._span_count < self._capacity:
                return 0
            # fall through to dropping the oldest
        if not self._items:
            return 0
        oldest = self._items.popleft()
        freed = _weight(oldest)
        self._span_count -= freed
        self._dropped += freed
        return freed

    # ------------------------------------------------------------------ #
    # Consumer side (the dispatcher, single-threaded)
    # ------------------------------------------------------------------ #
    def drain(self, span_limit: int) -> list:
        """Remove and return whole items, oldest first, up to ~``span_limit``
        spans. Always returns at least one item if the buffer is non-empty, so
        an item larger than ``span_limit`` still makes progress.

        Holds the lock only for the pops -- the caller then does network I/O
        with nothing held."""
        out: list = []
        taken = 0
        with self._lock:
            while self._items and (taken == 0 or taken < span_limit):
                item = self._items.popleft()
                w = _weight(item)
                self._span_count -= w
                taken += w
                out.append(item)
            if taken:
                self._drained += taken
            self._not_full.notify_all()
        return out

    def requeue(self, items) -> int:
        """Return unexported items to the *front* of the buffer, capped.

        A brief collector blip should not lose telemetry, so a failed batch is
        retried next cycle. But it goes back *under the same cap*: if producers
        filled the buffer while the export was in flight, the re-queued batch
        loses to the newer data. That is what stops "retry" meaning "unbounded"."""
        items = list(items)
        dropped = 0
        with self._lock:
            for item in reversed(items):
                w = _weight(item)
                if self._span_count + w > self._capacity:
                    self._dropped += w
                    dropped += w
                    continue
                self._items.appendleft(item)
                self._span_count += w
        return dropped

    # ------------------------------------------------------------------ #
    def stats(self) -> BufferStats:
        with self._lock:
            return BufferStats(
                item_count=len(self._items),
                span_count=self._span_count,
                capacity_spans=self._capacity,
                enqueued_spans_total=self._enqueued,
                dropped_spans_total=self._dropped,
                drained_spans_total=self._drained,
                full_policy=self._policy,
            )

    def span_count(self) -> int:
        with self._lock:
            return self._span_count

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
