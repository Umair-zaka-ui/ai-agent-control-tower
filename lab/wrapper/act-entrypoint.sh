#!/usr/bin/env bash
# ACT-under-test entrypoint for the wrapped lab. Runs INSIDE the egress-deny network.
# 1. prove production separation from the inside (masked .env / .keys), 2. migrate the
# fresh act_lab, 3. bootstrap LAB key material (gate on for this one command only),
# 4. serve. Nothing here can reach the host or the internet.
set -e
cd /app
echo "[act] /app/.env size: $(wc -c < /app/.env) bytes (masked); /app/.keys entries: $(ls -A /app/.keys | wc -l) (masked tmpfs)"
mkdir -p /lab/.keys /lab/run/logs
echo "[act] alembic upgrade head"
alembic upgrade head
echo "[act] keys bootstrap (fresh lab identity)"
ENCRYPTION_KEY_ALLOW_BOOTSTRAP=true python -m app.security.keys bootstrap || echo "[act] bootstrap returned non-zero (see status below)"
python -m app.security.keys status
python -m app.security.keys verify
echo "[act] serving on 0.0.0.0:8802 (internal network only)"
exec uvicorn app.main:app --host 0.0.0.0 --port 8802 --log-level info
