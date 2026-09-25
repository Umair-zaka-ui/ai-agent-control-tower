"""V9 lab environment binding. Imported FIRST by every V9 script.

Binds the ACT application (unchanged product code) to the DEDICATED V9 lab
database and to lab-only key material, and refuses to run against anything
else. The shared dev database on 127.0.0.1:5432 is never touched (the W-6
accumulation lesson).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
LAB_RUN = ROOT / "lab" / "run"
RESULTS = LAB_RUN / "results"
KEYS = ROOT / "lab" / ".keys" / "v9"            # gitignored via lab/.keys/

PG_HOST, PG_PORT = "127.0.0.1", "55433"
PG_SUPER = ("postgres", "trust-localhost-lab-only")  # host-native lab instance: trust auth on 127.0.0.1 only
APP_USER, APP_PW = "ai_agent_control_tower_app", "v9-app-synthetic-pw"
PG_DATA = ROOT / "lab" / "run" / "pg17" / "data"       # dedicated, ephemeral, gitignored (lab/run/)
PG_BIN = Path(r"C:\Program Files\PostgreSQL\17\bin")


def db_url(dbname: str = "act_v9") -> str:
    return f"postgresql+psycopg2://{APP_USER}:{APP_PW}@{PG_HOST}:{PG_PORT}/{dbname}"


def activate(dbname: str = "act_v9", *, keys_dir: Path | None = None, extra_env: dict | None = None):
    """Set the environment, chdir to backend (so `.env` non-DB settings load),
    import settings and assert the binding is the lab database."""
    keys = keys_dir or KEYS
    keys.mkdir(parents=True, exist_ok=True)
    os.environ["DATABASE_URL"] = db_url(dbname)
    os.environ["SIGNING_KEY_PATH"] = str(keys) + os.sep
    os.environ["MODEL_CREDENTIAL_ENCRYPTION_KEY_PATH"] = str(keys / "model_credentials.key")
    os.environ.setdefault("ENCRYPTION_KEY_ALLOW_BOOTSTRAP", "false")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for k, v in (extra_env or {}).items():
        os.environ[k] = v
    os.chdir(BACKEND)
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from app.core.config import settings  # noqa: WPS433 - deliberate late import

    url = settings.DATABASE_URL
    if f"{PG_HOST}:{PG_PORT}/" not in url or "/act_v9" not in url:
        raise SystemExit(f"REFUSING: settings bound to a non-lab database: {url.split('@')[-1]}")
    if ":5432/" in url:
        raise SystemExit("REFUSING: settings bound to the shared dev database")
    RESULTS.mkdir(parents=True, exist_ok=True)
    return settings


def ensure_lab_encryption_key() -> Path:
    """A lab-only Fernet key so synthetic secrets never touch the dev key."""
    from cryptography.fernet import Fernet
    KEYS.mkdir(parents=True, exist_ok=True)
    p = KEYS / "model_credentials.key"
    if not p.exists():
        p.write_bytes(Fernet.generate_key())
    return p
