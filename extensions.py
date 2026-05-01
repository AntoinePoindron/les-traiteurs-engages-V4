"""Singleton instances of Flask extensions, importable from blueprints
without creating circular imports with app.py.
"""

import os

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()


def _limiter_storage_uri() -> str:
    """Pick the rate-limiter backend at import time.

    Audit VULN-101 (P0): in-memory storage is per-process, so multi-worker
    gunicorn (the default in prod) silently multiplies every limit by N.
    The login throttle (`10/min`) becomes `10*N/min` and brute-force
    protection effectively disappears.

    Resolution: reuse the Redis instance already provisioned for Dramatiq
    (P3.4) when REDIS_URL is set. Use a different DB index from the broker
    (1 vs 0) to keep the keyspaces isolated. Falls back to in-memory only
    when REDIS_URL is unset, which is fine for local single-worker dev and
    the test suite.
    """
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return "memory://"
    # Carve out a dedicated DB number so dramatiq queues and rate-limiter
    # keys never collide. Strip any trailing /N from REDIS_URL first.
    base = (
        redis_url.rstrip("/").rsplit("/", 1)[0]
        if redis_url.count("/") >= 3
        else redis_url
    )
    return f"{base}/1"


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per minute", "1000 per hour"],
    storage_uri=_limiter_storage_uri(),
    # moving-window is more expensive but accurate for auth throttling —
    # better than fixed-window which lets a burst slip through at the edge.
    strategy="moving-window",
)
