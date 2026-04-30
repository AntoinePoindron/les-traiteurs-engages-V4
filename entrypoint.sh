#!/bin/sh
set -e

echo "Running migrations..."
alembic upgrade head

# init_db.py now only handles bootstrap admin (no schema work).
# Skipped automatically when ADMIN_INITIAL_PASSWORD is unset.
python init_db.py

# Seeding demo data is opt-in via env. Never run in prod.
if [ "${ENABLE_DEMO_SEED}" = "1" ]; then
    echo "ENABLE_DEMO_SEED=1 — seeding demo data..."
    python seed_data.py || true
fi

echo "Starting gunicorn..."
# Local dev: GUNICORN_RELOAD=1 (set in docker-compose.dev.yml) makes gunicorn
# watch the mounted source tree and restart workers on every save. Stays
# off in staging/prod where workers should be stable.
GUNICORN_OPTS=""
if [ "${GUNICORN_RELOAD}" = "1" ]; then
    echo "GUNICORN_RELOAD=1 — enabling --reload (dev mode)."
    GUNICORN_OPTS="--reload"
fi
exec gunicorn --bind 0.0.0.0:${PORT:-8000} ${GUNICORN_OPTS} "app:create_app()"
