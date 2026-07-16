"""Phase 4.3.6 performance tests (§37) — 1,000 authorization requests through
the gateway, decision-cache hit ratio, cold vs warm latency and concurrent
enforcement through the live check endpoint."""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.authorization.middleware.cache import DecisionCacheService

BASE = "/api/v1/authorization"


def _user(db, user_id: str):
    from app.models.user import User

    return db.get(User, uuid.UUID(user_id))


def test_1000_gateway_authorizations(client: TestClient, admin: dict, db_session) -> None:
    from app.authorization.middleware.gateway import AuthorizationGateway

    user = _user(db_session, admin["user_id"])
    gateway = AuthorizationGateway(db_session)
    DecisionCacheService.reset()

    started = time.perf_counter()
    for _ in range(1000):
        decision = gateway.authorize(user, "agent.view", audit_events=False,
                                     record_decision=False)
        assert decision.allowed
    elapsed = time.perf_counter() - started

    avg_ms = elapsed / 1000 * 1000
    assert avg_ms < 25, f"avg {avg_ms:.2f}ms per authorization (budget 25ms)"


def test_decision_cache_hit_ratio_when_warm(client: TestClient, admin: dict,
                                            db_session) -> None:
    from app.authorization.middleware.gateway import AuthorizationGateway

    user = _user(db_session, admin["user_id"])
    gateway = AuthorizationGateway(db_session)
    DecisionCacheService.reset()

    for _ in range(100):
        gateway.authorize(user, "policy.view", audit_events=False, record_decision=False)
    metrics = DecisionCacheService.metrics()
    assert metrics["decision_cache_hit_ratio"] > 0.9, metrics


def test_cold_vs_warm_latency(client: TestClient, admin: dict, db_session) -> None:
    from app.authorization.middleware.gateway import AuthorizationGateway

    user = _user(db_session, admin["user_id"])
    gateway = AuthorizationGateway(db_session)
    DecisionCacheService.reset()

    t0 = time.perf_counter()
    cold = gateway.authorize(user, "approval.view", audit_events=False,
                             record_decision=False)
    cold_ms = (time.perf_counter() - t0) * 1000

    warm_ms = []
    for _ in range(50):
        t0 = time.perf_counter()
        warm = gateway.authorize(user, "approval.view", audit_events=False,
                                 record_decision=False)
        warm_ms.append((time.perf_counter() - t0) * 1000)
        assert warm.cache_hit
    avg_warm = sum(warm_ms) / len(warm_ms)

    assert not cold.cache_hit and cold.allowed and warm.allowed
    assert avg_warm < 5, f"warm path {avg_warm:.2f}ms (budget 5ms)"
    assert avg_warm <= cold_ms, (avg_warm, cold_ms)


def test_concurrent_check_requests(client: TestClient, admin: dict) -> None:
    def _one(_: int) -> bool:
        r = client.post(f"{BASE}/check", headers=admin["headers"],
                        json={"permission": "audit.view"})
        return r.status_code == 200 and r.json()["allowed"]

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(_one, range(100)))
    assert all(results)
