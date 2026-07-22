"""Phase 5.1 performance-shaped tests (SRS §31 performance/load coverage).

Mirrors the convention used by ``test_permission_engine_perf.py`` and
``test_resource_authorization_perf.py``: timing is *reported*, not
hard-asserted, so the suite doesn't flake on a loaded machine — but the
functional behaviour under bulk load (search correctness, pagination,
duplicate detection across a larger candidate pool) is asserted.
"""

from __future__ import annotations

import time
import uuid

from fastapi.testclient import TestClient

PASSWORD = "T3st!Passw0rd#Ok"
RT = "/api/v1/runtime"
BULK_COUNT = 50


def _register_org(client: TestClient, org: str = "Registry Perf Org") -> dict:
    email = f"regperf_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": org, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"],
            "organization_id": me["user"]["organization_id"], "email": email}


def _register_agent(client: TestClient, admin: dict, **overrides) -> dict:
    payload = {
        "name": f"Perf Agent {uuid.uuid4().hex[:8]}", "description": "A test agent.",
        "business_purpose": "Exercise the registry under bulk load.", "agent_type": "ASSISTANT",
        "criticality": "MEDIUM", "owner_type": "USER", "owner_id": admin["user_id"],
        "definition": {"name": "Definition", "framework": "CUSTOM", "entrypoint_type": "PYTHON_MODULE",
                      "entrypoint": f"agents.handler_{uuid.uuid4().hex[:6]}:run"},
    }
    payload.update(overrides)
    r = client.post(f"{RT}/agents", headers=admin["headers"], json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def test_bulk_registration_and_search_throughput(client: TestClient) -> None:
    """Registers BULK_COUNT agents, then exercises paginated search/filtering
    against the resulting inventory — asserting both correctness (every agent
    is findable, pagination totals line up) and reporting throughput."""
    org = _register_org(client)

    started = time.perf_counter()
    created = [_register_agent(client, org) for _ in range(BULK_COUNT)]
    register_elapsed = time.perf_counter() - started

    started = time.perf_counter()
    r = client.get(f"{RT}/agents", headers=org["headers"], params={"page_size": 200})
    search_elapsed = time.perf_counter() - started
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) >= BULK_COUNT
    assert {a["id"] for a in created} <= {a["id"] for a in rows}

    started = time.perf_counter()
    r = client.get(f"{RT}/agents", headers=org["headers"],
                    params={"query": created[0]["name"], "page_size": 10})
    filtered_elapsed = time.perf_counter() - started
    assert r.status_code == 200, r.text
    assert any(a["id"] == created[0]["id"] for a in r.json())

    print(f"\n{BULK_COUNT} registrations in {register_elapsed*1000:.1f}ms "
          f"({register_elapsed*1000/BULK_COUNT:.2f}ms avg); "
          f"unfiltered search {search_elapsed*1000:.1f}ms; "
          f"filtered search {filtered_elapsed*1000:.1f}ms")


def test_duplicate_check_scales_against_a_larger_candidate_pool(client: TestClient) -> None:
    """Runs duplicate detection against BULK_COUNT other agents in the same
    org, including one exact-name and one near-identical-entrypoint match,
    and reports how long detection took against that pool."""
    org = _register_org(client)
    shared_entrypoint = f"agents.shared_{uuid.uuid4().hex[:6]}:run"

    for _ in range(BULK_COUNT):
        _register_agent(client, org)
    exact_match_name = f"Duplicate Target {uuid.uuid4().hex[:6]}"
    _register_agent(client, org, name=exact_match_name)
    _register_agent(client, org, definition={
        "name": "Definition", "framework": "CUSTOM", "entrypoint_type": "PYTHON_MODULE",
        "entrypoint": shared_entrypoint,
    })

    probe = _register_agent(client, org, name=exact_match_name, definition={
        "name": "Definition", "framework": "CUSTOM", "entrypoint_type": "PYTHON_MODULE",
        "entrypoint": shared_entrypoint,
    })

    started = time.perf_counter()
    r = client.post(f"{RT}/agents/{probe['id']}/duplicate-check", headers=org["headers"])
    elapsed = time.perf_counter() - started
    assert r.status_code == 200, r.text
    matches = r.json()
    assert len(matches) >= 1, "duplicate check found nothing against a pool with an exact-name match"

    print(f"\nDuplicate check against a pool of {BULK_COUNT + 2} agents took "
          f"{elapsed*1000:.1f}ms, found {len(matches)} candidate(s)")
