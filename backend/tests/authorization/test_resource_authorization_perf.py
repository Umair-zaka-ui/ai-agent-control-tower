"""Phase 4.3.4 performance-shaped tests (§25).

Resource-level evaluation, ACL/ownership/sharing/delegation lookups. Timing is
*reported* (not hard-asserted) so the suite is not flaky on a loaded machine;
the §25 targets (<15ms evaluation, <10ms ACL/share/delegation lookup, <5ms
ownership lookup) are checked as generous smoke bounds on the average.
"""

from __future__ import annotations

import time
import uuid

from fastapi.testclient import TestClient

PASSWORD = "T3st!Passw0rd#Ok"


def _setup_resource(client: TestClient, admin: dict) -> dict:
    r = client.post("/api/v1/resources", headers=admin["headers"], json={
        "resource_type": "ai_agent", "name": f"perf_{uuid.uuid4().hex[:6]}",
        "visibility": "ORGANIZATION",
    })
    assert r.status_code == 201, r.text
    return r.json()


def _timed(fn, n: int = 50) -> float:
    started = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - started) * 1000 / n


def test_resource_authorization_evaluation_speed(client: TestClient, admin: dict) -> None:
    res = _setup_resource(client, admin)
    # Realistic metadata: a few ACL entries and a share.
    for _ in range(3):
        assert client.post(f"/api/v1/resources/{res['id']}/acl", headers=admin["headers"], json={
            "principal_type": "USER", "principal_id": str(uuid.uuid4()),
            "permission": "ai_agent.update", "effect": "ALLOW",
        }).status_code == 201

    def one():
        r = client.post(f"/api/v1/resources/{res['id']}/authorize",
                        json={"permission": "ai_agent.update"}, headers=admin["headers"])
        assert r.status_code == 200 and r.json()["allowed"] is True

    avg = _timed(one)
    print(f"\nresource authorize avg {avg:.2f}ms/eval (target <15ms core evaluation)")
    # Generous end-to-end bound (includes HTTP + auth + audit write).
    assert avg < 250, f"resource evaluation unexpectedly slow: {avg:.1f}ms"


def test_lookup_speeds(client: TestClient, admin: dict) -> None:
    res = _setup_resource(client, admin)
    h = admin["headers"]
    pk = res["id"]

    owner_avg = _timed(lambda: client.get(f"/api/v1/resources/{pk}/owner", headers=h))
    acl_avg = _timed(lambda: client.get(f"/api/v1/resources/{pk}/acl", headers=h))
    share_avg = _timed(lambda: client.get(f"/api/v1/resources/{pk}/shares", headers=h))
    deleg_avg = _timed(lambda: client.get(f"/api/v1/resources/{pk}/delegations", headers=h))
    print(f"\nlookups avg ms — owner {owner_avg:.2f} | acl {acl_avg:.2f} | "
          f"shares {share_avg:.2f} | delegations {deleg_avg:.2f}")
    for name, avg in (("owner", owner_avg), ("acl", acl_avg),
                      ("shares", share_avg), ("delegations", deleg_avg)):
        assert avg < 250, f"{name} lookup unexpectedly slow: {avg:.1f}ms"
