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
# Bind, workers, threads, timeout, --preload, and the SQLAlchemy fork-safety
# hook all live in gunicorn.conf.py (auto-discovered from CWD). Tunables:
# WEB_CONCURRENCY, GUNICORN_THREADS, GUNICORN_TIMEOUT, PORT, GUNICORN_RELOAD.
exec gunicorn "app:create_app()"
