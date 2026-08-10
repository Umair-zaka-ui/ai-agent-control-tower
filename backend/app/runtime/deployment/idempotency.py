"""ACT-SRS-M3 §3.1 (M3-3.1-FR-010..013) -- the reusable, platform-wide
``Idempotency-Key`` contract. Every later Milestone 3 command (promotion,
rollout, rollback, ...) reuses ``IdempotencyService`` directly rather than
redefining its own key->result bookkeeping -- proven generic, not just
documented as such, by ``test_deployment_lifecycle.py``'s AC-08 test, which
exercises ``execute()`` against a bare non-deployment stub callable.

Deliberately a *different*, more general mechanism from the pre-existing
``app.runtime.services.IdempotencyService``/``IdempotencyRecord`` (Phase 5.0
§33): that one dedupes execution requests specifically, scoped to
``agent_id`` and resolving to a hard FK on ``AgentExecution`` -- it sits on
the M1 execution path this phase must not touch, and its narrower shape
(one execution per key, nothing else) cannot represent an arbitrary command's
result. This module's ``IdempotencyKey`` table is scoped to
``(organization, operation)`` and stores an opaque JSON ``result_ref``
instead, so it fits any command.

``execute()`` uses a claim-then-poll pattern, not a naive check-then-act: a
plain "SELECT, then on miss call fn() and INSERT" has a genuine TOCTOU gap
under real concurrency (M3-3.1-FR-030/031's own requirement) -- two callers
racing the same key could both miss the check and both run ``fn()``, exactly
the double-execution the whole contract exists to prevent. Instead, a caller
first *commits* a placeholder claim row; the table's own
``(organization, operation, idempotency_key)`` unique constraint is the
concurrency primitive -- Postgres guarantees only one of two racing inserts
for the same key can ever commit. The loser catches the resulting
``IntegrityError`` and polls briefly for the winner's real result rather
than running ``fn()`` at all."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.identity.errors import ErrorCode, IdentityError
from app.models.runtime import IdempotencyKey
from app.runtime.services import _now

_PENDING = {"_pending": True}


def fingerprint(payload: dict) -> str:
    """A stable hash of a request payload -- used to detect the same key
    reused with a genuinely different request (M3-3.1-FR-012), never to
    identify the request on its own (the key does that)."""
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class IdempotencyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _find(self, organization_id: uuid.UUID, operation: str, key: str) -> IdempotencyKey | None:
        return self.db.execute(select(IdempotencyKey).where(
            IdempotencyKey.organization_id == organization_id,
            IdempotencyKey.operation == operation,
            IdempotencyKey.idempotency_key == key,
        )).scalars().first()

    def check(self, organization_id: uuid.UUID, operation: str, key: str,
             request_fingerprint: str) -> dict | None:
        """Returns the previously stored result if ``key`` was already used
        for this ``(organization, operation)`` with an identical payload;
        ``None`` if the key is unused, expired, or still mid-flight (the
        pending placeholder). Raises ``IDEMPOTENCY_CONFLICT`` if the key is
        reused with a *different* payload (M3-3.1-FR-012) -- never silently
        replays the stale result."""
        record = self._find(organization_id, operation, key)
        if record is None:
            return None
        if record.expires_at < _now():
            # Expired -- treat exactly as if the key had never been used.
            self.db.delete(record)
            self.db.commit()
            return None
        if record.request_fingerprint != request_fingerprint:
            raise IdentityError(ErrorCode.IDEMPOTENCY_CONFLICT,
                               "Idempotency key reused with a different request payload.")
        if record.result_ref == _PENDING:
            return None
        return record.result_ref

    def _await_result(self, organization_id: uuid.UUID, operation: str, key: str,
                      request_fingerprint: str, *, timeout_seconds: float = 5.0,
                      poll_interval: float = 0.05) -> dict:
        """Called only by the loser of the claim race (below): the winner's
        own transaction is typically sub-second, so this is a short bounded
        wait, not an indefinite block."""
        deadline = time.monotonic() + timeout_seconds
        while True:
            self.db.rollback()  # start each poll on a fresh READ COMMITTED snapshot
            cached = self.check(organization_id, operation, key, request_fingerprint)
            if cached is not None:
                return cached
            if time.monotonic() >= deadline:
                raise IdentityError(
                    ErrorCode.IDEMPOTENCY_CONFLICT,
                    "This idempotency key is still being processed by a concurrent request; retry.",
                )
            time.sleep(poll_interval)

    def execute(self, *, organization_id: uuid.UUID, operation: str, key: str | None,
               payload: dict, fn: Callable[[], dict]) -> tuple[dict, bool]:
        """Runs ``fn`` at most once per ``(organization, operation, key)``.
        Returns ``(result, replayed)`` -- ``replayed`` is ``True`` when a
        prior result was returned without calling ``fn`` again
        (M3-3.1-FR-011). ``fn`` must return a JSON-serializable ``dict``
        (the value stored verbatim in ``result_ref``). ``key=None`` means the
        caller made no idempotency request for this call: ``fn`` always runs,
        and nothing is stored -- this is the generic, reusable entry point;
        it has no idea whether ``fn`` creates a deployment, a promotion, or
        anything else (M3-3.1-FR-013)."""
        if key is None:
            return fn(), False

        request_fingerprint = fingerprint(payload)
        cached = self.check(organization_id, operation, key, request_fingerprint)
        if cached is not None:
            return cached, True

        claim = IdempotencyKey(
            organization_id=organization_id, operation=operation, idempotency_key=key,
            request_fingerprint=request_fingerprint, result_ref=dict(_PENDING),
            expires_at=_now() + timedelta(hours=24),
        )
        self.db.add(claim)
        try:
            self.db.commit()
        except IntegrityError:
            # Lost the race: a concurrent caller already committed a claim
            # for this exact key first (M3-3.1-FR-030). Never run `fn()`.
            self.db.rollback()
            return self._await_result(organization_id, operation, key, request_fingerprint), True

        # Won the claim -- run the real work and fill the placeholder in. If
        # `fn()` itself raises, the claim is removed (best-effort) rather
        # than left stuck at the pending placeholder for its full 24h TTL,
        # so an immediate retry with the same key is not needlessly blocked
        # by a failed attempt.
        try:
            result = fn()
        except Exception:
            self.db.rollback()
            fresh = self._find(organization_id, operation, key)
            if fresh is not None and fresh.result_ref == _PENDING:
                self.db.delete(fresh)
                self.db.commit()
            raise
        claim.result_ref = result
        self.db.commit()
        return result, False
