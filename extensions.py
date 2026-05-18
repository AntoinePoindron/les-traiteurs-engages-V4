"""Singleton instances of Flask extensions, importable from blueprints
without creating circular imports with app.py.
"""

import logging
import os

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

logger = logging.getLogger(__name__)

csrf = CSRFProtect()


def _is_truthy_env(name: str) -> bool:
    # Match the truthy set Pydantic v2 accepts for bool fields, so
    # `FLASK_DEBUG=on` and `LIMITER_ALLOW_MEMORY=t` behave the same here
    # as on the Settings model in config.py — operators shouldn't need
    # to learn a per-helper truthy dialect.
    return os.getenv(name, "").strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
        "on",
        "t",
    )


def _limiter_storage_uri() -> str:
    """Pick the rate-limiter backend at import time.

    Audit VULN-101 (P0) + H-3 (2026-05-13): in-memory storage is
    per-process, so multi-worker gunicorn (4 workers in prod) silently
    multiplies every limit by N. The login throttle (`10/min`) becomes
    `40/min` and brute-force protection effectively disappears. Worse,
    a worker recycle resets every counter to zero.

    Resolution: reuse the Redis instance already provisioned for Dramatiq
    (P3.4) when REDIS_URL is set. Use a different DB index from the broker
    (1 vs 0) to keep the keyspaces isolated.

    When REDIS_URL is unset we refuse to start unless an explicit dev/test
    marker is in the environment. The marker set:
      * FLASK_DEBUG=1            — local dev (docker-compose.dev.yml)
      * LIMITER_ALLOW_MEMORY=1   — explicit operator opt-in (tests,
                                   niche prod scenarios with one worker)
    """
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        # Carve out a dedicated DB number so dramatiq queues and
        # rate-limiter keys never collide. Strip any trailing /N from
        # REDIS_URL first.
        base = (
            redis_url.rstrip("/").rsplit("/", 1)[0]
            if redis_url.count("/") >= 3
            else redis_url
        )
        return f"{base}/1"

    in_dev = _is_truthy_env("FLASK_DEBUG")
    explicit_opt_in = _is_truthy_env("LIMITER_ALLOW_MEMORY")
    if not (in_dev or explicit_opt_in):
        raise SystemExit(
            "Refusing to start: REDIS_URL is required outside dev/test. "
            "The in-memory rate-limiter store is per-process — in a "
            "multi-worker server it silently bypasses /login throttling. "
            "Set REDIS_URL, or LIMITER_ALLOW_MEMORY=1 if you understand "
            "the trade-off (single-worker only)."
        )
    logger.warning(
        "Rate-limiter using in-memory store — per-process counters, "
        "NOT safe behind multiple gunicorn workers."
    )
    return "memory://"


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per minute", "1000 per hour"],
    storage_uri=_limiter_storage_uri(),
    # moving-window is more expensive but accurate for auth throttling —
    # better than fixed-window which lets a burst slip through at the edge.
    strategy="moving-window",
)
