#!/bin/sh
set -e

echo "Running migrations..."
alembic upgrade head

# init_db.py now only handles bootstrap admin (no schema work).
# Skipped automatically when ADMIN_INITIAL_PASSWORD is unset.
python init_db.py

# Audit C-3 follow-up (2026-05-13): the ENABLE_DEMO_SEED hook used to
# live here was a sibling of the Procfile postdeploy block this PR
# removed — same exposure, same `|| true` that would have swallowed
# seed_data.py's new SystemExit(2) guard. Demo seeding is now strictly
# operator-initiated: `docker compose exec app python seed_data.py`
# under the dev overlay. Never wired into the boot path again.

echo "Starting gunicorn..."
# Bind, workers, threads, timeout, --preload, and the SQLAlchemy fork-safety
# hook all live in gunicorn.conf.py (auto-discovered from CWD). Tunables:
# WEB_CONCURRENCY, GUNICORN_THREADS, GUNICORN_TIMEOUT, PORT, GUNICORN_RELOAD.
exec gunicorn "app:create_app()"
