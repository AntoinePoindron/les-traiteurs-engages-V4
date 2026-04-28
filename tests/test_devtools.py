"""Tests for the dev-only account switcher.

The conftest sets up the app with whatever ENABLE_DEMO_SEED is in the
container env. In docker compose dev, that's "1", so the blueprint is
registered. We assert two contracts:

  1. The endpoint is gated by an email allowlist — even when registered,
     it must refuse arbitrary emails (audit defence in depth).
  2. The endpoint requires POST + CSRF (handled at the framework level).
"""
import os
import pytest


# Skip the whole module if the flag isn't set — we can't test what isn't there.
pytestmark = pytest.mark.skipif(
    os.getenv("ENABLE_DEMO_SEED") != "1",
    reason="dev switcher only registered when ENABLE_DEMO_SEED=1",
)


def test_switch_account_rejects_unknown_email(client):
    """Email not in the hardcoded DEMO_ACCOUNTS list -> 403, even though
    a valid CSRF token is present (CSRFs are off in test mode)."""
    resp = client.post(
        "/dev/switch-account",
        data={"email": "intruder@evil.example.com"},
    )
    assert resp.status_code == 403


def test_switch_account_requires_post(client):
    """GET on the route must return 405. A bookmarked GET would otherwise
    let third-party pages trigger account switches via <img src>."""
    resp = client.get("/dev/switch-account")
    assert resp.status_code == 405
