"""V0 §9A — enumerate rows violating the 5.1 NATIVE invariant. Read-only. No secrets."""
import sys
sys.path.insert(0, ".")
from sqlalchemy import text
from app.core.database import engine

Q_INVALID = """
select a.id, a.organization_id, o.name as org_name, a.name, a.origin_category, a.origin_provider,
       a.control_state, a.lifecycle_status, a.owner_id, a.owner_type, a.discovery_source_ref,
       a.external_reference, a.api_key_hash, a.created_at
from agents a left join organizations o on o.id = a.organization_id
where a.origin_category = 'NATIVE'
  and (a.control_state <> 'GOVERNED' or a.origin_provider <> 'ACT_NATIVE' or a.origin_provider is null)
order by a.created_at
"""
with engine.connect() as c:
    print("total agents:", c.execute(text("select count(*) from agents")).scalar())
    print("distribution origin_category x control_state:")
    for r in c.execute(text("select origin_category, control_state, count(*) from agents group by 1,2 order by 1,2")):
        print("  ", r)
    print("NATIVE rows with origin_provider <> ACT_NATIVE:",
          c.execute(text("select count(*) from agents where origin_category='NATIVE' and (origin_provider is distinct from 'ACT_NATIVE')")).scalar())
    cols = [r[0] for r in c.execute(text("select column_name from information_schema.columns where table_name='agents' order by ordinal_position"))]
    print("agents columns:", cols)
    rows = c.execute(text(Q_INVALID)).mappings().all()
    print("INVALID rows:", len(rows))
    for r in rows:
        print("  id=%s org=%s org_name=%r name=%r cat=%s prov=%s cs=%s lc=%s owner=%s/%s dsr=%s extref=%s keyhash=%r created=%s" % (
            r["id"], r["organization_id"], r["org_name"], r["name"], r["origin_category"], r["origin_provider"],
            r["control_state"], r["lifecycle_status"], r["owner_type"], r["owner_id"], r["discovery_source_ref"],
            r["external_reference"], r["api_key_hash"], r["created_at"]))
    ids = [str(r["id"]) for r in rows]
    # audit linkage: any audit event referencing these ids?
    at = [r[0] for r in c.execute(text("select table_name from information_schema.tables where table_schema='public' and table_name like '%audit%'"))]
    print("audit tables:", at)
    for t in at:
        tcols = [r[0] for r in c.execute(text("select column_name from information_schema.columns where table_name=:t"), {"t": t})]
        print("  ", t, "cols:", tcols)
    # per-org: how many agents & are the orgs test-shaped? (users' email domains)
    print("orgs of invalid rows:")
    for org in sorted({str(r["organization_id"]) for r in rows}):
        n = c.execute(text("select count(*) from agents where organization_id = cast(:o as uuid)"), {"o": org}).scalar()
        emails = [r[0] for r in c.execute(text("select email from users where organization_id = cast(:o as uuid) limit 3"), {"o": org})]
        # redact local part
        emails = [e.split("@")[0][:4] + "***@" + e.split("@")[1] for e in emails]
        print("  ", org, "agents_in_org=", n, "user_emails=", emails)
    # negative control: NATIVE rows whose name does NOT match the fixture pattern agent-<hex8>
    nm = [r for r in rows if not (r["name"].startswith("agent-") and len(r["name"]) == 14)]
    print("invalid rows NOT matching fixture name pattern agent-<hex8>:", len(nm))
    # comparison: rows the fixture provably creates with defaults (NATIVE+GOVERNED, name agent-<hex8>, api_key_hash 'x')
    print("fixture-shaped valid rows (name agent-<hex8>, api_key_hash='x', NATIVE, GOVERNED):",
          c.execute(text("select count(*) from agents where name ~ '^agent-[0-9a-f]{8}$' and api_key_hash='x' and origin_category='NATIVE' and control_state='GOVERNED'")).scalar())
    print("any product-created agent has api_key_hash='x'? count of api_key_hash='x' overall:",
          c.execute(text("select count(*) from agents where api_key_hash='x'")).scalar())
    print("count NATIVE+DISCOVERED with api_key_hash='x':",
          c.execute(text("select count(*) from agents where origin_category='NATIVE' and control_state='DISCOVERED' and api_key_hash='x'")).scalar())
