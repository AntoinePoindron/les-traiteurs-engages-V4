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

# Audit H-11 (2026-05-13): without `forwarded_allow_ips`, gunicorn
# strips `X-Forwarded-*` from any request whose source IP isn't
# 127.0.0.1 (its default). On Scalingo the dyno receives traffic from
# the managed router on a non-loopback IP, so the headers vanished
# before Werkzeug's ProxyFix could read them. Effect: every request's
# `remote_addr` collapsed to the router's IP, the rate-limiter bucketed
# all clients together, and one attacker on /login DoS'd the entire
# user base by exhausting the shared 10/min window.
#
# `*` is safe ONLY behind a managed proxy that terminates TLS and
# rewrites the headers itself (Scalingo, Caddy with the right config,
# AWS ALB, etc.). Self-hosted operators behind a less-trusted proxy
# must set `FORWARDED_ALLOW_IPS` to the trusted CIDR(s).
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "*")

# Cap request line + per-header size. Defuses trivial DoS via absurdly
# long URIs / headers, well above legitimate traffic — the longest URLs
# the app emits (signed S3 presigns) sit around 2 KB.
limit_request_line = int(os.getenv("GUNICORN_LIMIT_REQUEST_LINE", "8192"))
limit_request_field_size = int(os.getenv("GUNICORN_LIMIT_REQUEST_FIELD_SIZE", "16384"))


def post_fork(server, worker):
    import sys

    db = sys.modules.get("database")
    if db is not None:
        db.engine.dispose(close=False)
