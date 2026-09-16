"""V0 §12 — delete ONLY fixture-attributable residue. Criteria are every fixture
signature at once, not just the invariant violation. Prints ids before and after."""
import sys; sys.path.insert(0, ".")
from sqlalchemy import text
from app.core.database import engine

CRITERIA = """
  a.origin_category = 'NATIVE' AND a.control_state = 'DISCOVERED'
  AND a.origin_provider = 'ACT_NATIVE'
  AND a.api_key_hash = 'x'
  AND a.name = 'agent-' || left(replace(a.id::text, '-', ''), 8)
  AND a.owner_id IS NULL AND a.owner_type IS NULL
  AND a.discovery_source_ref IS NULL AND a.external_reference IS NULL
  AND o.name = 'Posture Org'
"""
with engine.begin() as c:
    inv = c.execute(text("select count(*) from agents where origin_category='NATIVE' and control_state<>'GOVERNED'")).scalar()
    rows = c.execute(text(f"select a.id, a.name, a.created_at from agents a join organizations o on o.id=a.organization_id where {CRITERIA} order by a.created_at")).fetchall()
    print("invalid rows (invariant only):", inv)
    print("rows matching FULL fixture signature:", len(rows))
    assert inv == len(rows), "an invalid row does not match the fixture signature - STOP"
    for r in rows: print("  ", r[0], r[1], r[2])
    # every referencing table (FK or not) must be empty for these ids
    ids = [str(r[0]) for r in rows]
    tabs = c.execute(text("select table_name, column_name from information_schema.columns where table_schema='public' and column_name in ('agent_id','subject_agent_id','source_agent_id','target_agent_id','entity_id','resource_id') and table_name<>'agents'")).fetchall()
    for t, col in tabs:
        n = c.execute(text(f"select count(*) from {t} where {col}::text = any(cast(:ids as text[]))"), {"ids": ids}).scalar()
        assert n == 0, (t, col, n)
    deleted = c.execute(text(f"delete from agents a using organizations o where o.id = a.organization_id and {CRITERIA}")).rowcount
    print("deleted:", deleted)
    assert deleted == len(rows)
with engine.connect() as c:
    print("post-cleanup invalid rows:", c.execute(text("select count(*) from agents where origin_category='NATIVE' and control_state<>'GOVERNED'")).scalar())
    print("post-cleanup total agents:", c.execute(text("select count(*) from agents")).scalar())
