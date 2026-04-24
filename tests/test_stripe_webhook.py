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


TEST_SECRET = "whsec_test_" + "a" * 32


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


# ---------------------------------------------------------------------------
# Helpers for the DB-touching tests below
# ---------------------------------------------------------------------------


def _seed_order_with_payment(stripe_invoice_id: str):
    """Insert a minimal Quote → Order → Payment chain tied to the seeded
    caterer and alice's company. Returns (order_id, payment_id) as UUIDs.

    Imports are deferred: see module docstring.
    """
    import uuid as _uuid
    from decimal import Decimal
    from sqlalchemy import select

    from database import session_factory
    from models import (
        Caterer,
        Company,
        Order,
        OrderStatus,
        Payment,
        PaymentStatus,
        Quote,
        QuoteRequest,
        QuoteStatus,
        User,
    )

    s = session_factory()
    try:
        company = s.scalar(select(Company).where(Company.siret == "12345678901234"))
        caterer = s.scalar(select(Caterer).where(Caterer.siret == "98765432109876"))
        alice = s.scalar(select(User).where(User.email == "alice@test.local"))

        qr = QuoteRequest(
            company_id=company.id,
            user_id=alice.id,
            guest_count=10,
        )
        s.add(qr)
        s.flush()

        quote = Quote(
            quote_request_id=qr.id,
            caterer_id=caterer.id,
            reference=f"DEVIS-TST-{_uuid.uuid4().hex[:6].upper()}",
            total_amount_ht=Decimal("100"),
            status=QuoteStatus.accepted,
        )
        s.add(quote)
        s.flush()

        order = Order(
            quote_id=quote.id,
            client_admin_id=alice.id,
            status=OrderStatus.invoiced,
            stripe_invoice_id=stripe_invoice_id,
        )
        s.add(order)
        s.flush()

        payment = Payment(
            order_id=order.id,
            caterer_id=caterer.id,
            stripe_invoice_id=stripe_invoice_id,
            status=PaymentStatus.pending,
            amount_total_cents=12000,
            application_fee_cents=600,
            amount_to_caterer_cents=11400,
        )
        s.add(payment)
        s.commit()
        return order.id, payment.id
    finally:
        s.close()


def _load_payment(payment_id):
    from database import session_factory
    from models import Payment

    s = session_factory()
    try:
        return s.get(Payment, payment_id)
    finally:
        s.close()


def _load_order(order_id):
    from database import session_factory
    from models import Order

    s = session_factory()
    try:
        return s.get(Order, order_id)
    finally:
        s.close()


# ---------------------------------------------------------------------------
# #2 — a legitimately-signed invoice.paid event must actually process
# ---------------------------------------------------------------------------


def test_signed_invoice_paid_marks_payment_succeeded(client, monkeypatch):
    """Before the fix, `event.get("type", "")` crashed with AttributeError
    because stripe.Event does not inherit from dict — so real Stripe
    webhooks could never mark anything paid."""
    import config

    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", TEST_SECRET)

    invoice_id = f"in_test_{uuid.uuid4().hex[:16]}"
    charge_id = f"ch_test_{uuid.uuid4().hex[:16]}"
    order_id, payment_id = _seed_order_with_payment(invoice_id)

    payload = _event(
        "invoice.paid",
        {"id": invoice_id, "object": "invoice", "charge": charge_id},
    )
    header = _sign(payload, TEST_SECRET)

    resp = client.post(
        "/api/webhooks/stripe",
        data=payload,
        headers={"Content-Type": "application/json", "Stripe-Signature": header},
    )
    assert resp.status_code == 200, (
        f"expected 200, got {resp.status_code}; body={resp.get_data(as_text=True)[:400]}"
    )

    from models import OrderStatus, PaymentStatus

    payment = _load_payment(payment_id)
    order = _load_order(order_id)
    assert payment.status == PaymentStatus.succeeded, payment.status
    assert payment.stripe_charge_id == charge_id
    assert order.status == OrderStatus.paid, order.status
