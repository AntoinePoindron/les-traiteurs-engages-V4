"""Tests pour `services.billing` — facturation Stripe en deux phases.

Phase 1 (`queue_invoice`) : pure DB, aucun appel Stripe. Phase 2
(`send_stripe_invoice`) : Stripe mocké. Imports lazy comme dans
`test_workflow.py` pour ne pas figer `config.DATABASE_URL` à la
collection (sinon `database.engine` pointe sur la DB de dev avant que
conftest ne switch sur `traiteurs_test`).
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
    from services import billing
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
    from services import billing
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
    from services import billing
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


# --- send_stripe_invoice (phase 2) -----------------------------------------


class _FakeStripeObject(dict):
    """dict avec accès attribut + .get() — modélise grossièrement un
    StripeObject pour les besoins des tests."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as e:
            raise AttributeError(name) from e


class _FakeIterable:
    def __init__(self, items):
        self._items = items
    def auto_paging_iter(self):
        return iter(self._items)


def _install_stripe_mocks(monkeypatch, captured: dict):
    """Mocke les 4 endpoints Stripe utilisés par send_stripe_invoice.
    Stocke les kwargs dans `captured` pour assertions."""
    import stripe

    def _customer_create(**kwargs):
        captured.setdefault("customer_create", []).append(kwargs)
        return _FakeStripeObject(id="cus_test_123")

    def _tax_rate_list(**kwargs):
        return _FakeIterable([])  # forcer la création

    def _tax_rate_create(**kwargs):
        captured.setdefault("tax_rate_create", []).append(kwargs)
        return _FakeStripeObject(id=f"txr_{kwargs.get('percentage')}", percentage=kwargs.get("percentage"), country="FR")

    def _invoice_create(**kwargs):
        captured.setdefault("invoice_create", []).append(kwargs)
        return _FakeStripeObject(id="in_test_abc")

    def _invoice_item_create(**kwargs):
        captured.setdefault("invoice_item_create", []).append(kwargs)
        return _FakeStripeObject(id="ii_test")

    def _invoice_finalize(invoice_id):
        captured.setdefault("invoice_finalize", []).append(invoice_id)
        return _FakeStripeObject(id=invoice_id)

    def _invoice_send(invoice_id):
        captured.setdefault("invoice_send", []).append(invoice_id)
        return _FakeStripeObject(id=invoice_id, hosted_invoice_url="https://stripe.test/in_test_abc")

    monkeypatch.setattr(stripe.Customer, "create", _customer_create)
    monkeypatch.setattr(stripe.TaxRate, "list", _tax_rate_list)
    monkeypatch.setattr(stripe.TaxRate, "create", _tax_rate_create)
    monkeypatch.setattr(stripe.Invoice, "create", _invoice_create)
    monkeypatch.setattr(stripe.InvoiceItem, "create", _invoice_item_create)
    monkeypatch.setattr(stripe.Invoice, "finalize_invoice", _invoice_finalize)
    monkeypatch.setattr(stripe.Invoice, "send_invoice", _invoice_send)


def test_send_stripe_invoice_links_id_and_marks_invoiced(session, monkeypatch):
    from services import billing
    from sqlalchemy import select

    captured: dict = {}
    _install_stripe_mocks(monkeypatch, captured)

    order = _seed_delivered_order_with_lines(session)
    payment = billing.queue_invoice(session, order=order)
    session.flush()
    billing.send_stripe_invoice(session, payment=payment)
    session.flush()

    refreshed_payment = session.scalar(select(Payment).where(Payment.id == payment.id))
    refreshed_order = session.scalar(select(Order).where(Order.id == order.id))

    assert refreshed_payment.stripe_invoice_id == "in_test_abc"
    assert refreshed_order.stripe_invoice_id == "in_test_abc"
    assert refreshed_order.stripe_hosted_invoice_url == "https://stripe.test/in_test_abc"
    assert refreshed_order.status == OrderStatus.invoiced

    # Idempotency_key tiré du payment.id : permet le retry sans duplication.
    invoice_create_kwargs = captured["invoice_create"][0]
    assert invoice_create_kwargs["idempotency_key"] == f"payment-{payment.id}"
    assert invoice_create_kwargs["application_fee_amount"] == payment.application_fee_cents
    assert "transfer_data" in invoice_create_kwargs
    # 1 ligne par groupe TVA + 1 ligne fee plateforme = 2 InvoiceItems
    assert len(captured["invoice_item_create"]) == 2
    assert captured["invoice_finalize"] == ["in_test_abc"]
    assert captured["invoice_send"] == ["in_test_abc"]


def test_send_stripe_invoice_is_noop_if_already_sent(session, monkeypatch):
    from services import billing
    captured: dict = {}
    _install_stripe_mocks(monkeypatch, captured)

    order = _seed_delivered_order_with_lines(session)
    payment = billing.queue_invoice(session, order=order)
    payment.stripe_invoice_id = "in_already_sent"
    session.flush()

    billing.send_stripe_invoice(session, payment=payment)

    assert "invoice_create" not in captured, "must not call Stripe when already sent"
    assert "invoice_finalize" not in captured
    assert "invoice_send" not in captured


def test_retry_pending_invoices_completes_phase_2(app, monkeypatch):
    """Le retry CLI doit boucler sur les Payment(stripe_invoice_id IS NULL,
    status=pending, anciens) et appeler send_stripe_invoice. Test sans
    Flask CLI runner — on appelle la fonction sous-jacente avec une
    session jetable et un cleanup explicite (le retry commit, donc la
    fixture rollback ne suffit pas)."""
    import datetime as _dt2

    from sqlalchemy import delete, select

    from database import session_factory
    from services import billing

    captured: dict = {}
    _install_stripe_mocks(monkeypatch, captured)

    setup = session_factory()
    order = _seed_delivered_order_with_lines(setup)
    payment = billing.queue_invoice(setup, order=order)
    setup.commit()
    payment_id = payment.id
    order_id = order.id
    caterer_id = order.quote.caterer_id
    quote_id = order.quote_id
    qr_id = order.quote.quote_request_id
    setup.close()

    try:
        runner = session_factory()
        try:
            # age_threshold=0 pour retenir le Payment fraîchement créé
            success, failed = billing.retry_pending_invoices(
                runner, age_threshold=_dt2.timedelta(seconds=0),
            )
            assert success == 1
            assert failed == 0
        finally:
            runner.close()

        check = session_factory()
        try:
            p = check.scalar(select(Payment).where(Payment.id == payment_id))
            assert p.stripe_invoice_id == "in_test_abc"
            o = check.scalar(select(Order).where(Order.id == order_id))
            assert o.status == OrderStatus.invoiced
        finally:
            check.close()
    finally:
        cleanup = session_factory()
        try:
            cleanup.execute(delete(CommissionInvoice).where(CommissionInvoice.order_id == order_id))
            cleanup.execute(delete(Invoice).where(Invoice.order_id == order_id))
            cleanup.execute(delete(Payment).where(Payment.id == payment_id))
            cleanup.execute(delete(Order).where(Order.id == order_id))
            cleanup.execute(delete(QuoteLine).where(QuoteLine.quote_id == quote_id))
            cleanup.execute(delete(Quote).where(Quote.id == quote_id))
            cleanup.execute(delete(QuoteRequest).where(QuoteRequest.id == qr_id))
            cleanup.execute(delete(Caterer).where(Caterer.id == caterer_id))
            cleanup.commit()
        finally:
            cleanup.close()


def test_retry_pending_invoices_skips_recent_payments(session, monkeypatch):
    """Garde-fou : le retry n'attrape pas les Payment plus récents que
    `age_threshold` (par défaut 2 min) — pour ne pas marcher sur les pieds
    d'une requête HTTP encore en vol."""
    from services import billing

    captured: dict = {}
    _install_stripe_mocks(monkeypatch, captured)

    order = _seed_delivered_order_with_lines(session)
    billing.queue_invoice(session, order=order)
    session.flush()

    success, failed = billing.retry_pending_invoices(session)  # défaut 2 min
    assert success == 0
    assert failed == 0
    assert "invoice_create" not in captured
