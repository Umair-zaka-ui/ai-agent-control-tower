"""V0 §6/§7 — live DB + metadata + route fingerprint. Prints no secrets."""
import os, sys, re
sys.path.insert(0, ".")
from sqlalchemy import text
from app.core.database import engine, Base
from app.core.config import settings
import app.main as m

url = str(engine.url)
safe = re.sub(r"://([^:]+):[^@]+@", r"://\1:***@", url)
print("DB URL (redacted):", safe)
with engine.connect() as c:
    print("PG version:", c.execute(text("select version()")).scalar())
    print("db name:", c.execute(text("select current_database()")).scalar())
    print("alembic_version rows:", c.execute(text("select version_num from alembic_version")).fetchall())
    live = c.execute(text("select count(*) from information_schema.tables where table_schema='public' and table_type='BASE TABLE'")).scalar()
    print("live public base tables:", live)
    live_names = {r[0] for r in c.execute(text("select table_name from information_schema.tables where table_schema='public' and table_type='BASE TABLE'"))}
meta_names = set(Base.metadata.tables.keys())
print("metadata tables:", len(meta_names))
print("in metadata not live:", sorted(meta_names - live_names))
print("in live not metadata:", sorted(live_names - meta_names))
routes = [r for r in m.app.routes if hasattr(r, "methods")]
print("routes with methods:", len(routes))
print("total app.routes:", len(m.app.routes))
# alembic script heads
from alembic.config import Config
from alembic.script import ScriptDirectory
cfg = Config("alembic.ini")
sd = ScriptDirectory.from_config(cfg)
print("script heads:", sd.get_heads())
print("script revisions count:", sum(1 for _ in sd.walk_revisions()))
