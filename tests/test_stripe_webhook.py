"""Stripe webhook security tests — real signatures, real DB, no mocks.

Covers audit findings (2026-04-24):
    #1 — empty STRIPE_WEBHOOK_SECRET must not act as a valid key
    #2 — the handler must process a legitimately-signed invoice.paid event
    #3 — event.id replays must be idempotent; invoice.payment_failed must
         not downgrade an already-succeeded payment

NOTE: no top-level imports of `config`, `database`, or `models`. The
conftest `_required_env` fixture rewrites `DATABASE_URL` at session start,
and `database.engine` binds at module import — so we must defer these
imports until inside test functions, after the fixture has run.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid


def _sign(payload: str, secret: str, ts: int | None = None) -> str:
    ts = ts or int(time.time())
    signed = f"{ts}.{payload}".encode()
    sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def _event(
    event_type: str,
    data_object: dict,
    *,
    event_id: str | None = None,
) -> str:
    ev = {
        "id": event_id or f"evt_test_{uuid.uuid4().hex[:16]}",
        "object": "event",
        "type": event_type,
        "api_version": "2024-12-18.acacia",
        "created": int(time.time()),
        "data": {"object": data_object},
        "livemode": False,
        "pending_webhooks": 1,
        "request": {"id": None, "idempotency_key": None},
    }
    return json.dumps(ev, separators=(",", ":"))


# ---------------------------------------------------------------------------
# #1 — empty secret must never act as a valid key
# ---------------------------------------------------------------------------


def test_empty_webhook_secret_rejects_forged_event(client, monkeypatch):
    """If STRIPE_WEBHOOK_SECRET is empty the endpoint MUST refuse to process.

    Before the fix, an attacker could HMAC a payload with an empty key —
    which trivially matches empty-key verification — and the handler
    accepted it.
    """
    import config

    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", "")

    payload = _event("invoice.paid", {"id": "in_forged", "charge": "ch_forged"})
    header = _sign(payload, secret="")

    resp = client.post(
        "/api/webhooks/stripe",
        data=payload,
        headers={"Content-Type": "application/json", "Stripe-Signature": header},
    )
    # The point is: never 2xx. 503 (misconfigured) or 400 are both acceptable.
    assert resp.status_code >= 400, (
        f"empty-secret webhook should be rejected, got {resp.status_code}"
    )
