"""Phase 3.8 -- schedule arithmetic, as pure functions.

No I/O, no ORM, no clock of its own: every function takes ``now`` explicitly.
That is what lets the due-computation and retry-backoff rules be tested
exhaustively without a database or a sleep, which matters more here than
usual -- a scheduler whose timing rules can only be tested by waiting is a
scheduler whose timing rules are effectively untested.

**CRON is deliberately not implemented.** The build prompt offered it "if
justified", and it is not: every job this phase registers is an interval sweep,
cron would require either a new dependency or a hand-rolled expression parser
(a notorious source of subtle bugs), and ``schedule_kind`` is a checked
constraint that a later phase can widen additively when a real calendar
requirement appears. Declaring a value the platform cannot honour would be the
same pretence Phase 3.6 refused for ROLLING.
"""

from __future__ import annotations

from datetime import datetime, timedelta

#: Kinds this phase genuinely implements. Mirrored by a CHECK constraint in
#: migration 0043 -- the database refuses anything else, so an unimplemented
#: kind cannot reach the dispatch loop even by a direct INSERT.
SCHEDULE_KINDS: frozenset[str] = frozenset({"INTERVAL", "ONE_TIME"})

DEFAULT_INTERVAL_SECONDS = 300.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 30.0
#: A lease outlives its job's timeout so a handler that is merely slow is not
#: reclaimed out from under itself; the heartbeat extends it further while the
#: handler genuinely runs.
LEASE_MARGIN_SECONDS = 60.0


def interval_seconds(spec: dict | None) -> float:
    """Positive interval from a schedule spec, defaulting rather than raising.

    A malformed spec is tenant-authored data, and a scheduler that crashes on
    one bad row stops running every *other* job too -- the blast radius of
    strictness here is the whole system, so a sane default wins."""
    value = (spec or {}).get("interval_seconds", DEFAULT_INTERVAL_SECONDS)
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_SECONDS
    return seconds if seconds > 0 else DEFAULT_INTERVAL_SECONDS


def run_at(spec: dict | None) -> datetime | None:
    """The one-time firing instant, if the spec carries a parseable one."""
    raw = (spec or {}).get("run_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def initial_next_run_at(schedule_kind: str, spec: dict | None, now: datetime) -> datetime | None:
    """When a newly created or re-enabled definition first becomes due.

    An INTERVAL job is due *immediately* rather than one interval from now.
    A five-minute sweep that does nothing for its first five minutes looks
    broken to whoever just enabled it, and there is no correctness reason to
    wait."""
    if schedule_kind == "ONE_TIME":
        return run_at(spec) or now
    return now


def next_run_after(schedule_kind: str, spec: dict | None, scheduled_for: datetime,
                   now: datetime) -> datetime | None:
    """The occurrence after the one just claimed.

    ``None`` means "never again" -- how a ONE_TIME job retires itself without
    needing a separate 'fired' flag.

    For INTERVAL, this deliberately **skips missed occurrences** rather than
    queueing them. If a scheduler fleet is down for an hour, a five-minute
    sweep should resume sweeping, not run twelve catch-up sweeps back to back:
    the sweeps are idempotent state reconciliations, not events with individual
    meaning, and a thundering herd of them on recovery is exactly what an
    already-struggling system does not need."""
    if schedule_kind == "ONE_TIME":
        return None
    step = timedelta(seconds=interval_seconds(spec))
    nxt = scheduled_for + step
    if nxt <= now:
        # Advance to the first occurrence strictly in the future.
        missed = int((now - nxt).total_seconds() // step.total_seconds()) + 1
        nxt = nxt + step * missed
    return nxt


def occurrence_key(schedule_kind: str, scheduled_for: datetime) -> str:
    """The identity of one scheduled occurrence.

    Derived from the instant the job was *due*, not from the instant it was
    claimed, so two instances that both see the same due job compute the same
    key and the unique index can do its job. A key based on claim time would
    differ per instance and defeat the guard entirely.

    A ONE_TIME job has exactly one occurrence ever, so its key is constant --
    which also means a re-enabled one-time job cannot silently fire twice."""
    if schedule_kind == "ONE_TIME":
        return "once"
    return f"i:{scheduled_for.isoformat()}"


def max_attempts(retry_policy: dict | None) -> int:
    value = (retry_policy or {}).get("max_attempts", DEFAULT_MAX_ATTEMPTS)
    try:
        attempts = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_ATTEMPTS
    return max(1, attempts)


def backoff_seconds(retry_policy: dict | None, attempt: int) -> float:
    """Exponential backoff, capped, matching the shape Phase 5.7a.4 already
    established for provider retries rather than inventing a second curve."""
    base = (retry_policy or {}).get("backoff_seconds", DEFAULT_BACKOFF_SECONDS)
    try:
        base_seconds = float(base)
    except (TypeError, ValueError):
        base_seconds = DEFAULT_BACKOFF_SECONDS
    if base_seconds < 0:
        base_seconds = DEFAULT_BACKOFF_SECONDS
    return min(base_seconds * (2 ** max(0, attempt - 1)), 3600.0)


def lease_expiry(now: datetime, timeout_seconds: int) -> datetime:
    """A lease deliberately outlives the handler's own timeout.

    If they were equal, a handler finishing at exactly its deadline would race
    its own reclamation, and two instances could briefly both consider
    themselves the owner. The margin makes the timeout the thing that stops a
    slow handler, and the lease the thing that detects a *dead* one -- two
    different failures that must not be conflated."""
    return now + timedelta(seconds=timeout_seconds + LEASE_MARGIN_SECONDS)
