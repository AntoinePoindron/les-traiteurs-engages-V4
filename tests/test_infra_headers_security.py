"""Tests for the H-3 finding of the 2026-05-13 security audit.

H-3 — `_limiter_storage_uri()` refuses to start on `memory://` outside
       an explicit dev / test opt-in.
"""

from __future__ import annotations

import pytest


def test_limiter_refuses_memory_storage_without_marker(monkeypatch):
    """The classic prod misconfig: no REDIS_URL, multi-worker gunicorn,
    rate limits silently per-process. Must hard-fail at boot."""
    # Import `extensions` before clearing env so the module body (which
    # calls `_limiter_storage_uri()` at import time on the `Limiter(...)`
    # line) runs against the conftest-blessed env. Otherwise a cold
    # import here raises SystemExit *outside* the pytest.raises block
    # and the test crashes regardless of whether the implementation is
    # correct — fragile to test ordering.
    import extensions

    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    monkeypatch.delenv("LIMITER_ALLOW_MEMORY", raising=False)

    with pytest.raises(SystemExit) as excinfo:
        extensions._limiter_storage_uri()
    assert "REDIS_URL" in str(excinfo.value)


@pytest.mark.parametrize(
    "marker, value",
    [
        ("FLASK_DEBUG", "1"),
        ("LIMITER_ALLOW_MEMORY", "1"),
        ("LIMITER_ALLOW_MEMORY", "true"),
        ("LIMITER_ALLOW_MEMORY", "YES"),
    ],
)
def test_limiter_memory_allowed_with_explicit_marker(monkeypatch, marker, value):
    """Either FLASK_DEBUG=1 (the existing dev marker) or
    LIMITER_ALLOW_MEMORY=1 (the explicit opt-in) unlocks the in-memory
    store. Case-insensitive on the truthy value."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    monkeypatch.delenv("LIMITER_ALLOW_MEMORY", raising=False)
    monkeypatch.setenv(marker, value)

    import extensions

    assert extensions._limiter_storage_uri() == "memory://"


def test_limiter_uses_redis_db_one_when_url_is_set(monkeypatch):
    """When REDIS_URL is set, the limiter carves out DB index 1 so
    Dramatiq queues (DB 0) and rate-limiter keys never collide."""
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    import extensions

    assert extensions._limiter_storage_uri() == "redis://localhost:6379/1"
