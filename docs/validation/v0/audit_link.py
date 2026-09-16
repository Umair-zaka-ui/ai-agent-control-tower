import sys
sys.path.insert(0, ".")
from sqlalchemy import text
from app.core.database import engine
with engine.connect() as c:
    ids = [str(r[0]) for r in c.execute(text("select id from agents where origin_category='NATIVE' and control_state<>'GOVERNED'"))]
    print("invalid ids:", len(ids))
    n = c.execute(text("select count(*) from audit_logs where entity_id = any(cast(:ids as text[])) or cast(entity_id as text) = any(cast(:ids as text[]))"), {"ids": ids}).scalar() if False else None
    # entity_id type?
    t = c.execute(text("select data_type from information_schema.columns where table_name='audit_logs' and column_name='entity_id'")).scalar()
    print("audit_logs.entity_id type:", t)
    q = "select event_type, count(*) from audit_logs where entity_id::text = any(cast(:ids as text[])) group by 1"
    print("audit events referencing invalid ids:", c.execute(text(q), {"ids": ids}).fetchall())
    q2 = "select event_type, count(*) from audit_logs where metadata::text ilike any(array(select '%' || unnest(cast(:ids as text[])) || '%')) group by 1"
    print("audit events whose metadata mentions an invalid id:", c.execute(text(q2), {"ids": ids}).fetchall())
    # positive control: does product agent creation produce an audit event? sample events for entity_type like agent
    print("audit event types on agent entities (sample):", c.execute(text("select event_type, count(*) from audit_logs where entity_type ilike '%agent%' group by 1 order by 2 desc limit 15")).fetchall())
    # created_at buckets (date, hour)
    print("created buckets:", c.execute(text("select date_trunc('hour', created_at), count(*) from agents where origin_category='NATIVE' and control_state<>'GOVERNED' group by 1 order by 1")).fetchall())
    # discovery observations or discovered links referencing these ids? (5.2 tables)
    dt = [r[0] for r in c.execute(text("select table_name from information_schema.tables where table_schema='public' and (table_name like 'discovery%' or table_name like 'agent_discover%')"))]
    print("discovery tables:", dt)
    for tname in dt:
        cols = [r[0] for r in c.execute(text("select column_name from information_schema.columns where table_name=:t"), {"t": tname})]
        if "agent_id" in cols:
            print("  ", tname, "rows referencing invalid ids:", c.execute(text(f"select count(*) from {tname} where agent_id::text = any(cast(:ids as text[]))"), {"ids": ids}).scalar())
    # orgs: created when, and are there other Posture Org orgs with valid rows (shows the fixture normally creates valid rows in the same org shape)
    print("Posture Org count:", c.execute(text("select count(*) from organizations where name='Posture Org'")).scalar())
    print("agents in Posture Orgs by (cat, cs):", c.execute(text("select a.origin_category, a.control_state, count(*) from agents a join organizations o on o.id=a.organization_id where o.name='Posture Org' group by 1,2 order by 1,2")).fetchall())
