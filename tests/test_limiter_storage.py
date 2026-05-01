"""Lock the rate-limiter storage selection (audit VULN-101).

The limiter MUST point at Redis whenever REDIS_URL is set. A regression
that lets it fall back to in-memory in a multi-worker prod would silently
disable brute-force protection.
"""

import importlib


def _reload_extensions():
    """Re-import extensions module so _limiter_storage_uri runs again
    against the current environment."""
    import extensions

    return importlib.reload(extensions)


def test_limiter_uses_memory_when_redis_url_unset(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    ext = _reload_extensions()
    assert ext.limiter._storage_uri == "memory://", (
        "Without REDIS_URL the limiter should fall back to in-memory storage"
    )


def test_limiter_uses_redis_db1_when_redis_url_set(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    ext = _reload_extensions()
    # We carve out DB 1 to isolate rate-limiter keys from dramatiq's DB 0.
    assert ext.limiter._storage_uri == "redis://redis:6379/1", (
        f"Expected redis://redis:6379/1, got {ext.limiter._storage_uri}"
    )


def test_limiter_handles_redis_url_without_db_suffix(monkeypatch):
    """Some deployments expose REDIS_URL like `redis://host:6379` without
    a trailing /N. The helper must still produce a valid `redis://host:6379/1`."""
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379")
    ext = _reload_extensions()
    assert ext.limiter._storage_uri == "redis://redis:6379/1"


def test_limiter_strategy_is_moving_window():
    """moving-window is more accurate than fixed-window for auth throttling
    (no edge-burst). Lock that choice in. The attribute is private in
    flask-limiter 4.x but stable enough for a regression assertion."""
    from extensions import limiter

    assert limiter._strategy == "moving-window"
