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
exec gunicorn --bind 0.0.0.0:${PORT:-8000} "app:create_app()"
