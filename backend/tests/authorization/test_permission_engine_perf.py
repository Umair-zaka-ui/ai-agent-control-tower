"""Phase 4.3.2 performance-shaped tests (§29).

These exercise the throughput, cold-vs-warm cache, hit ratio and role-update
invalidation behaviours. Timing is *reported* (not hard-asserted) so the suite is
not flaky on a loaded machine; correctness of the cache behaviour is asserted.
"""

from __future__ import annotations

import time
import uuid

from fastapi.testclient import TestClient


def _check(client, admin, permission):
    resp = client.post(
        "/api/v1/authorization/check", json={"permission": permission}, headers=admin["headers"]
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_100_authorization_checks(client: TestClient, admin: dict) -> None:
    """100 checks all succeed; the vast majority are cache hits (warm path)."""
    started = time.perf_counter()
    hits = 0
    for _ in range(100):
        r = _check(client, admin, "agent.view")
        assert r["allowed"] is True
        if r["cache_hit"]:
            hits += 1
    elapsed = time.perf_counter() - started
    # Only the first is a cold miss; the rest should hit the cache.
    assert hits >= 98, f"cache hit ratio too low: {hits}/100"
    print(f"\n100 authorization checks in {elapsed*1000:.1f}ms "
          f"({elapsed*1000/100:.3f}ms avg), {hits}/100 cache hits")


def test_cold_vs_warm_cache(client: TestClient, admin: dict) -> None:
    cold = _check(client, admin, "policy.view")
    warm = _check(client, admin, "policy.view")
    assert cold["cache_hit"] is False   # first build
    assert warm["cache_hit"] is True    # served from cache
    assert "PERMISSION_CACHE_REFRESHED" in cold["events"]
    assert "PERMISSION_CACHE_REFRESHED" not in warm["events"]


def test_role_update_invalidates_cache(client: TestClient, admin: dict) -> None:
    # Warm the cache.
    assert _check(client, admin, "agent.view")["cache_hit"] is False
    assert _check(client, admin, "agent.view")["cache_hit"] is True

    # Any org-scoped role change bumps the org version -> next check is a cold miss.
    resp = client.post(
        "/api/v1/roles",
        json={"name": f"perf_{uuid.uuid4().hex[:8]}", "permissions": ["agent.view"]},
        headers=admin["headers"],
    )
    assert resp.status_code == 201, resp.text

    after = _check(client, admin, "agent.view")
    assert after["cache_hit"] is False, "cache was not invalidated by a role change"
