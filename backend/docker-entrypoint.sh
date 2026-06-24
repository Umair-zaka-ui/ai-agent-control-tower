#!/usr/bin/env bash
set -e

# Wait for the database, run migrations, then hand off to the CMD (uvicorn).
echo "Running database migrations..."
alembic upgrade head

# Optionally seed demo data when SEED_ON_START=true.
if [ "${SEED_ON_START:-false}" = "true" ]; then
  echo "Seeding demo data..."
  python -m app.seed || echo "Seeding skipped/failed (continuing)."
fi

echo "Starting application: $*"
exec "$@"
