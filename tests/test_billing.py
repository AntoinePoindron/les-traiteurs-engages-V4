"""Tests pour `services.billing` — facturation Stripe en deux phases.

Phase 1 (`queue_invoice`) : pure DB, aucun appel Stripe. C'est ce que
tests dans ce fichier couvrent. Phase 2 (`send_stripe_invoice`) sera
testée séparément avec des mocks Stripe.
"""
import datetime as _dt
import uuid
from decimal import Decimal

import pytest

from models import (
    Caterer,
    CatererStructureType,
    CommissionInvoice,
    Company,
    Invoice,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    Quote,
    QuoteLine,
    QuoteRequest,
    QuoteRequestStatus,
    QuoteStatus,
    User,
)
from services import billing


@pytest.fixture
def session(app):
    from database import session_factory
    s = session_factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _seed_delivered_order_with_lines(s) -> Order:
    """Crée la chaîne complète : Caterer → QR → Quote+Lines → Order(delivered).
    Retourne l'Order. Les lignes valent 100€ HT, TVA 10%, 1 quantité."""
    from sqlalchemy import select

    acme = s.scalar(select(Company).where(Company.siret == "12345678901234"))
    alice = s.scalar(select(User).where(User.email == "alice@test.local"))

    caterer = Caterer(
        name=f"Caterer Bill {uuid.uuid4().hex[:6]}",
        siret=f"44{uuid.uuid4().hex[:12]}",
        structure_type=CatererStructureType.ESAT,
        invoice_prefix=f"B{uuid.uuid4().hex[:5]}",
        is_validated=True,
    )
    s.add(caterer)
    s.flush()

    qr = QuoteRequest(
        company_id=acme.id,
        user_id=alice.id,
        guest_count=10,
        status=QuoteRequestStatus.completed,
        event_address="1 rue Test",
        event_city="Paris",
        event_zip_code="75001",
        event_date=_dt.date.today() + _dt.timedelta(days=30),
    )
    s.add(qr)
    s.flush()

    quote = Quote(
        quote_request_id=qr.id,
        caterer_id=caterer.id,
        reference=f"DEVIS-BLG-{uuid.uuid4().hex[:8]}",
        total_amount_ht=Decimal("100"),
        status=QuoteStatus.accepted,
    )
    s.add(quote)
    s.flush()

    s.add(QuoteLine(
        quote_id=quote.id,
        position=0,
        section="principal",
        description="Buffet test",
        quantity=Decimal("1"),
        unit_price_ht=Decimal("100"),
        tva_rate=Decimal("10"),
    ))

    order = Order(
        quote_id=quote.id,
        client_admin_id=alice.id,
        status=OrderStatus.delivered,
        delivery_date=_dt.date.today() + _dt.timedelta(days=14),
        delivery_address="1 rue Test, 75001 Paris",
    )
    s.add(order)
    s.flush()

    # Charge les relations pour que `billing.queue_invoice` les voie sans round-trip.
    _ = quote.lines
    _ = quote.quote_request
    return order


def test_queue_invoice_creates_payment_invoice_and_commissions(session):
    """Phase 1 : un Payment + Invoice + 2 CommissionInvoice côté DB.
    Aucun appel Stripe."""
    from sqlalchemy import select

    order = _seed_delivered_order_with_lines(session)

    payment = billing.queue_invoice(session, order=order)
    session.flush()

    assert payment.order_id == order.id
    assert payment.status == PaymentStatus.pending
    assert payment.stripe_invoice_id is None
    # 100€ HT + 10% TVA = 110€ TTC ; fee 5€ HT + 20% TVA = 6€ ; total Stripe 116€
    assert payment.amount_total_cents == 11600
    assert payment.application_fee_cents == 600
    assert payment.amount_to_caterer_cents == 11000

    invoices = session.scalars(
        select(Invoice).where(Invoice.order_id == order.id)
    ).all()
    assert len(invoices) == 1
    assert invoices[0].amount_ht == Decimal("100.00")
    assert invoices[0].amount_ttc == Decimal("110.00")

    commissions = session.scalars(
        select(CommissionInvoice).where(CommissionInvoice.order_id == order.id)
    ).all()
    assert len(commissions) == 2
    parties = sorted(c.party for c in commissions)
    assert parties == ["caterer", "client"]
    for c in commissions:
        assert c.amount_ht == Decimal("5.00")
        assert c.amount_ttc == Decimal("6.00")


def test_queue_invoice_is_idempotent_via_unique_order_id(session):
    """Un second appel pour la même Order lève IntegrityError au flush
    via `UNIQUE(payments.order_id)` — c'est l'idempotence DB-only.
    Le caller doit rollback et récupérer le Payment existant."""
    from sqlalchemy.exc import IntegrityError

    order = _seed_delivered_order_with_lines(session)

    billing.queue_invoice(session, order=order)
    session.flush()

    # Le 2e appel ajoute un nouveau Payment pour le même order ; le flush
    # doit échouer sur UNIQUE(order_id).
    with pytest.raises(IntegrityError):
        billing.queue_invoice(session, order=order)
        session.flush()


def test_queue_invoice_does_not_call_stripe(session, monkeypatch):
    """Garde-fou : la Phase 1 ne doit AUCUN appel Stripe."""
    import stripe

    def _explode(*args, **kwargs):
        raise AssertionError("Stripe must not be called in Phase 1")

    monkeypatch.setattr(stripe.Invoice, "create", _explode)
    monkeypatch.setattr(stripe.InvoiceItem, "create", _explode)
    monkeypatch.setattr(stripe.Customer, "create", _explode)

    order = _seed_delivered_order_with_lines(session)
    billing.queue_invoice(session, order=order)
    session.flush()
