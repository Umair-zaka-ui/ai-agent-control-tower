"""V0.1 guard negative control (scratch, NOT committed).

Proves the deterministic guard bites: insert ONE NATIVE+DISCOVERED row, run the
guard (must FAIL naming the row), delete the row, run again (must PASS).
The row is removed in a finally block whatever happens.
Run from backend/:  python <this file>
"""
import subprocess
import sys
import uuid

sys.path.insert(0, ".")
from sqlalchemy import text  # noqa: E402

from app.core.database import engine  # noqa: E402

TEST = "tests/runtime/test_agent_asset_model.py::test_ac09_existing_agents_are_backfilled_native_and_governed"
PY = sys.executable


def run_guard() -> tuple[int, str]:
    p = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", TEST],
                       capture_output=True, text=True)
    return p.returncode, p.stdout


org = None
with engine.connect() as c:
    org = c.execute(text("select organization_id from agents where origin_category='NATIVE' limit 1")).scalar()
aid = uuid.uuid4()
name = "v01-guard-negative-control"
try:
    with engine.begin() as c:
        c.execute(text("""
            INSERT INTO agents (id, organization_id, name, agent_type, api_key_hash, status,
                                origin_category, origin_provider, control_state)
            VALUES (:id, :org, :name, 'ASSISTANT', 'x', 'ACTIVE', 'NATIVE', 'ACT_NATIVE', 'DISCOVERED')
        """), {"id": str(aid), "org": org, "name": name})
    rc, out = run_guard()
    tail = out.strip().splitlines()[-1] if out.strip() else ""
    named = name in out
    print(f"WITH one planted violating row: rc={rc} (expected 1) guard names the row={named} :: {tail}")
    assert rc == 1 and named, "guard did not bite"
finally:
    with engine.begin() as c:
        n = c.execute(text("delete from agents where id = :id and name = :name"), {"id": str(aid), "name": name}).rowcount
    print(f"planted row deleted: {n}")
rc, out = run_guard()
print(f"AFTER deletion: rc={rc} (expected 0) :: {out.strip().splitlines()[-1]}")
assert rc == 0
with engine.connect() as c:
    print("invariant violations now:", c.execute(text(
        "select count(*) from agents where origin_category='NATIVE' and (control_state<>'GOVERNED' or origin_provider<>'ACT_NATIVE')")).scalar())
