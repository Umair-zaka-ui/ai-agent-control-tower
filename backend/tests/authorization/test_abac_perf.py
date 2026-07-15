"""Phase 4.3.5 performance-shaped tests (§41, §42).

Targets (§41): policy resolution <10ms, attribute context <20ms, compiled
evaluation <15ms, complete evaluation <40ms, cached retrieval <5ms. Core
timings are *reported*; assertions use generous end-to-end bounds (HTTP + auth
+ audit included) so the suite stays stable on a loaded machine — the same
convention as the 4.3.2/4.3.4 perf tests.
"""

from __future__ import annotations

import time
import uuid

from fastapi.testclient import TestClient

BASE = "/api/v1/authorization"


def _seed_policies(client: TestClient, admin: dict, action: str, count: int = 25) -> None:
    """Many active policies with distinct targets + a handful matching ``action``."""
    for i in range(count):
        target_action = action if i % 5 == 0 else f"other.op{i}"
        r = client.post(f"{BASE}/abac/policies", headers=admin["headers"], json={
            "name": f"perf_{uuid.uuid4().hex[:6]}", "effect": "LOG_ONLY" if i % 2 else "ALLOW",
            "priority": i, "target": {"actions": [target_action]},
            "conditions": {"all": [
                {"attribute": "action.name", "operator": "EQUALS", "value": target_action},
                {"any": [
                    {"attribute": "environment.business_hours", "operator": "EXISTS"},
                    {"attribute": "identity.risk_score", "operator": "NOT_EXISTS"},
                ]},
            ]},
        })
        assert r.status_code == 201, r.text
        assert client.post(f"{BASE}/abac/policies/{r.json()['id']}/publish",
                           headers=admin["headers"]).status_code == 200


def test_100_concurrent_style_evaluations(client: TestClient, admin: dict) -> None:
    action = f"perf.op{uuid.uuid4().hex[:6]}"
    _seed_policies(client, admin, action)

    started = time.perf_counter()
    for _ in range(100):
        r = client.post(f"{BASE}/abac/evaluate", headers=admin["headers"],
                        json={"action": action, "context": {}})
        assert r.status_code == 200
    elapsed = (time.perf_counter() - started) * 1000
    core = r.json()["evaluation_time_ms"]
    print(f"\n100 ABAC evaluations in {elapsed:.1f}ms ({elapsed/100:.2f}ms avg end-to-end, "
          f"last core evaluation {core:.2f}ms; §41 target <40ms core)")
    assert elapsed / 100 < 250, "evaluation unexpectedly slow"

    # Warm cache: after the first evaluation the policy set is served from cache.
    metrics = client.get(f"{BASE}/abac/metrics", headers=admin["headers"]).json()
    assert metrics["abac_cache_hit_ratio"] > 0.5, metrics


def test_deeply_nested_condition_tree_speed() -> None:
    from app.authorization.abac.conditions import ConditionEvaluator

    # 12-level nested ALL/ANY tree, ~2^6 leaves.
    def tree(depth: int) -> dict:
        if depth == 0:
            return {"attribute": "identity.risk_score", "operator": "LESS_THAN", "value": 90}
        key = "all" if depth % 2 else "any"
        return {key: [tree(depth - 1), tree(depth - 1)]} if depth <= 6 else \
            {key: [tree(depth - 1)]}

    node = tree(12)
    ctx = {"identity.risk_score": 42}
    started = time.perf_counter()
    for _ in range(100):
        ok, _trace = ConditionEvaluator.evaluate(node, ctx)
        assert ok is True
    per_eval = (time.perf_counter() - started) * 1000 / 100
    print(f"\ndeep condition tree: {per_eval:.3f}ms/eval (§41 target <15ms)")
    assert per_eval < 15, "compiled condition evaluation exceeds the §41 target"


def test_cold_vs_warm_policy_cache(client: TestClient, admin: dict) -> None:
    from app.authorization.abac.policies import PolicyCache, PolicyResolver
    from app.core.database import SessionLocal

    action = f"cache.op{uuid.uuid4().hex[:6]}"
    _seed_policies(client, admin, action, count=10)

    db = SessionLocal()
    try:
        org = uuid.UUID(admin["organization_id"]) if "organization_id" in admin else None
        if org is None:
            me = client.get("/api/v1/auth/me", headers=admin["headers"]).json()
            org = uuid.UUID(me["user"]["organization_id"])
        resolver = PolicyResolver(db)

        PolicyCache.invalidate(org)
        started = time.perf_counter()
        resolver.active_policies(org)
        cold_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        for _ in range(50):
            resolver.active_policies(org)
        warm_ms = (time.perf_counter() - started) * 1000 / 50
        print(f"\npolicy set: cold {cold_ms:.2f}ms, warm {warm_ms:.4f}ms "
              f"(§41 targets: resolution <10ms, cached <5ms)")
        assert warm_ms < 5, "cached policy retrieval exceeds the §41 target"
        assert warm_ms < cold_ms
    finally:
        db.close()
