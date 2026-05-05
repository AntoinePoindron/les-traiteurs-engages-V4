"""Gunicorn config — prod-tuned concurrency + SQLAlchemy fork-safety.

Auto-discovered from the working directory by gunicorn (>=19.7), so
`gunicorn "app:create_app()"` picks it up without `--config`.

Defaults: 4 workers x 2 threads x 60s timeout — roughly 5-10x the
single sync worker / 30s previously hard-coded in entrypoint.sh.
Override per environment via WEB_CONCURRENCY, GUNICORN_THREADS,
GUNICORN_TIMEOUT.

In dev (GUNICORN_RELOAD=1), workers drop to 1 and --preload turns off
because gunicorn's auto-reload requires the app to be re-imported per
worker — incompatible with preload.

Fork-safety: with --preload the DB engine and its socket pool are
created in the master, then forked into workers. SQLAlchemy cannot
detect the fork, so without intervention multiple workers would race
on the same FDs. `post_fork` discards each worker's inherited pool
references (`close=False` so the master's still-live sockets are not
torn down); workers then open fresh connections on first checkout.
"""

import os

_RELOAD = os.getenv("GUNICORN_RELOAD") == "1"

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
workers = int(os.getenv("WEB_CONCURRENCY", "1" if _RELOAD else "4"))
threads = int(os.getenv("GUNICORN_THREADS", "2"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
reload = _RELOAD
preload_app = not _RELOAD


def post_fork(server, worker):
    import sys

    db = sys.modules.get("database")
    if db is not None:
        db.engine.dispose(close=False)
