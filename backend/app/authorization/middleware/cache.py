"""Decision cache (Phase 4.3.6 §19, §23).

Caches *final gateway decisions* keyed by identity × permission × resource ×
organization × permission-cache version × ABAC policy generation, so any role,
assignment, ACL, hierarchy or policy change rotates the key and stale entries
simply stop matching (§19). Entries also carry a short TTL because parts of
the ABAC context are time-based (business hours) and must not be pinned.

Never cached (§19): decisions evaluated with caller-supplied dynamic context
(risk scores, ai.* signals, row counts …), challenge decisions whose obligation
state is per-request (approval, MFA, justification), and decisions for
revoked-session identities (`invalidate_identity` is called on revocation).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

_DEFAULT_TTL_SECONDS = 60.0

# Challenge decisions depend on per-request state (approval queue, MFA step-up,
# justification) and must be re-evaluated every time.
_UNCACHEABLE_DECISIONS = {"REQUIRE_APPROVAL", "REQUIRE_MFA", "REQUIRE_JUSTIFICATION"}


@dataclass(frozen=True)
class _Entry:
    payload: dict[str, Any]
    expires_at: float


class DecisionCacheService:
    """In-process (single-node) decision cache with version-composed keys."""

    _store: dict[tuple, _Entry] = {}
    _identity_epoch: dict[str, int] = {}
    hits: int = 0
    misses: int = 0
    ttl_seconds: float = _DEFAULT_TTL_SECONDS

    # ------------------------------------------------------------------ #
    # Key composition (§23): identity, permission, resource, organization
    # and both subsystem versions. Any change to either version — role /
    # assignment / permission mutations bump the RBAC version, policy /
    # attribute mutations bump the ABAC generation — makes old keys dead.
    # ------------------------------------------------------------------ #
    @classmethod
    def _key(
        cls,
        *,
        identity_id: uuid.UUID,
        permission: str,
        resource_type: str | None,
        resource_id: uuid.UUID | None,
        organization_id: uuid.UUID | None,
        rbac_version: int,
        abac_generation: int,
    ) -> tuple:
        return (
            str(identity_id),
            cls._identity_epoch.get(str(identity_id), 0),
            permission,
            resource_type,
            str(resource_id) if resource_id else None,
            str(organization_id) if organization_id else None,
            rbac_version,
            abac_generation,
        )

    @classmethod
    def get(cls, **key_parts) -> dict[str, Any] | None:
        entry = cls._store.get(cls._key(**key_parts))
        if entry is None or entry.expires_at < time.monotonic():
            cls.misses += 1
            return None
        cls.hits += 1
        return dict(entry.payload)

    @classmethod
    def put(cls, payload: dict[str, Any], **key_parts) -> None:
        if payload.get("decision") in _UNCACHEABLE_DECISIONS:
            return
        cls._store[cls._key(**key_parts)] = _Entry(
            payload=dict(payload), expires_at=time.monotonic() + cls.ttl_seconds
        )

    # ------------------------------------------------------------------ #
    # Invalidation (§19, §23)
    # ------------------------------------------------------------------ #
    @classmethod
    def invalidate_identity(cls, identity_id: uuid.UUID) -> None:
        """Session revoked / account state changed → all cached decisions for
        this identity stop matching immediately."""
        key = str(identity_id)
        cls._identity_epoch[key] = cls._identity_epoch.get(key, 0) + 1

    @classmethod
    def reset(cls) -> None:
        cls._store.clear()
        cls._identity_epoch.clear()
        cls.hits = 0
        cls.misses = 0

    @classmethod
    def metrics(cls) -> dict[str, Any]:
        total = cls.hits + cls.misses
        return {
            "decision_cache_entries": len(cls._store),
            "decision_cache_hits": cls.hits,
            "decision_cache_misses": cls.misses,
            "decision_cache_hit_ratio": round(cls.hits / total, 3) if total else 0.0,
        }
