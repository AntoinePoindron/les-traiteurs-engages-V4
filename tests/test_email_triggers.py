"""Email-trigger functions in services/email_triggers.py.

Strategy : monkey-patch `services.email.send_email_async.send` so each
trigger's call shape is recorded without actually enqueuing on dramatiq.
That way we can assert on subject + recipient + presence of CTA URL +
critical body fragments without needing a real broker.

Convention d'imports lazy : same as test_password_reset.py — services
+ database are imported inside test functions so conftest can switch
DATABASE_URL to traiteurs_test before the engine is created.
"""

import datetime as _dt
import uuid
from decimal import Decimal

import pytest


@pytest.fixture
def session(app):
    from database import session_factory

    s = session_factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def captured_emails(monkeypatch):
    """Capture every send_email_async.send invocation. Each entry is the
    kwargs dict the trigger passed."""
    calls = []

    def _record(**kwargs):
        calls.append(kwargs)

    from services import email as email_module

    monkeypatch.setattr(email_module.send_email_async, "send", _record)
    return calls


def _alice(s):
    from sqlalchemy import select

    from models import User

    return s.scalar(select(User).where(User.email == "alice@test.local"))


# --- E2 — welcome --------------------------------------------------------


def test_welcome_signup_client(app, session, captured_emails):
    from services import email_triggers

    alice = _alice(session)
    with app.app_context():
        email_triggers.welcome_signup(
            alice, role_kind="client", cta_path="/client/settings"
        )
    assert len(captured_emails) == 1
    call = captured_emails[0]
    assert call["to"] == alice.email
    assert "Bienvenue" in call["subject"]
    assert "/client/settings" in call["html"]
    # Plaintext alt body must mention either the demande/devis context
    # so a non-HTML mail client conveys the same intent.
    assert "devis" in call["text"].lower()


def test_welcome_signup_caterer(app, session, captured_emails):
    from sqlalchemy import select

    from models import User
    from services import email_triggers

    cook = session.scalar(select(User).where(User.email == "cook@test.local"))
    with app.app_context():
        email_triggers.welcome_signup(
            cook, role_kind="caterer", cta_path="/caterer/profile"
        )
    assert len(captured_emails) == 1
    assert "/caterer/profile" in captured_emails[0]["html"]
    assert "profil" in captured_emails[0]["text"].lower()


def test_welcome_signup_swallows_render_error(app, session, captured_emails):
    """The @_safe decorator must swallow template errors so a signup
    bug never rolls back the user account."""
    from services import email_triggers

    alice = _alice(session)
    with app.app_context():
        # Pass an unknown role_kind — the template still renders (it
        # falls through the elif chain to the generic CTA branch).
        email_triggers.welcome_signup(alice, role_kind="totally-bogus", cta_path="/x")
    # Either the template handled it (1 captured) or the @_safe ate
    # an exception (0 captured). Both outcomes must NOT raise here.
    assert len(captured_emails) in (0, 1)


# --- E5 — quote received -------------------------------------------------


def _seed_transmitted_quote(session):
    """Seed an end-to-end fixture: company + caterer + QR + quote +
    QRC(transmitted_to_client). Returns (quote, caterer)."""
    from sqlalchemy import select

    from models import (
        Caterer,
        CatererStructureType,
        Company,
        QRCStatus,
        Quote,
        QuoteRequest,
        QuoteRequestCaterer,
        QuoteRequestStatus,
        QuoteStatus,
        User,
    )

    acme = session.scalar(select(Company).where(Company.siret == "12345678901234"))
    alice = session.scalar(select(User).where(User.email == "alice@test.local"))

    caterer = Caterer(
        name=f"Caterer {uuid.uuid4().hex[:6]}",
        siret=f"77{uuid.uuid4().hex[:12]}",
        structure_type=CatererStructureType.ESAT,
        invoice_prefix=f"R{uuid.uuid4().hex[:4]}",
        is_validated=True,
    )
    session.add(caterer)
    session.flush()

    qr = QuoteRequest(
        company_id=acme.id,
        user_id=alice.id,
        guest_count=20,
        status=QuoteRequestStatus.sent_to_caterers,
        event_address="1 rue Test",
        event_city="Paris",
        event_zip_code="75001",
        event_date=_dt.date.today() + _dt.timedelta(days=14),
    )
    session.add(qr)
    session.flush()

    quote = Quote(
        quote_request_id=qr.id,
        caterer_id=caterer.id,
        reference=f"DEVIS-EM-{uuid.uuid4().hex[:8]}",
        total_amount_ht=Decimal("250"),
        amount_per_person=Decimal("12.50"),
        valid_until=_dt.date.today() + _dt.timedelta(days=7),
        status=QuoteStatus.sent,
    )
    session.add(quote)
    session.add(
        QuoteRequestCaterer(
            quote_request_id=qr.id,
            caterer_id=caterer.id,
            status=QRCStatus.transmitted_to_client,
            response_rank=1,
        )
    )
    session.flush()
    return quote, caterer


def test_quote_received_emails_the_requester(app, session, captured_emails):
    from services import email_triggers

    quote, caterer = _seed_transmitted_quote(session)
    with app.app_context():
        email_triggers.quote_received(session, quote=quote, caterer=caterer)
    assert len(captured_emails) == 1
    call = captured_emails[0]
    assert call["to"] == "alice@test.local"
    assert "devis" in call["subject"].lower()
    assert caterer.name in call["html"]
    assert "12.50" in call["html"] or "12,50" in call["html"]
    assert "/client/requests/" in call["html"]


def test_quote_received_skips_when_qrc_not_transmitted(app, session, captured_emails):
    """Defensive : the trigger must noop when the QRC isn't actually
    in `transmitted_to_client`. Models 4th-responder / no-match cases
    where workflow.submit_quote raised before promoting the QRC."""
    from sqlalchemy import select

    from models import QRCStatus, QuoteRequestCaterer
    from services import email_triggers

    quote, caterer = _seed_transmitted_quote(session)
    qrc = session.scalar(
        select(QuoteRequestCaterer).where(
            QuoteRequestCaterer.quote_request_id == quote.quote_request_id,
            QuoteRequestCaterer.caterer_id == caterer.id,
        )
    )
    qrc.status = QRCStatus.responded  # not transmitted
    session.flush()

    with app.app_context():
        email_triggers.quote_received(session, quote=quote, caterer=caterer)
    assert captured_emails == []


# --- E6 — order confirmed ------------------------------------------------


def _seed_order_for_email(session):
    from sqlalchemy import select

    from models import (
        Caterer,
        CatererStructureType,
        Company,
        Order,
        OrderStatus,
        Quote,
        QuoteRequest,
        QuoteRequestStatus,
        QuoteStatus,
        User,
        UserRole,
    )

    acme = session.scalar(select(Company).where(Company.siret == "12345678901234"))
    alice = session.scalar(select(User).where(User.email == "alice@test.local"))

    caterer = Caterer(
        name=f"Caterer {uuid.uuid4().hex[:6]}",
        siret=f"77{uuid.uuid4().hex[:12]}",
        structure_type=CatererStructureType.ESAT,
        invoice_prefix=f"R{uuid.uuid4().hex[:4]}",
        is_validated=True,
    )
    session.add(caterer)
    session.flush()
    cat_user = User(
        email=f"cat-{uuid.uuid4().hex[:6]}@test.local",
        password_hash="x",
        first_name="Cat",
        last_name="X",
        role=UserRole.caterer,
        caterer_id=caterer.id,
    )
    session.add(cat_user)
    session.flush()

    qr = QuoteRequest(
        company_id=acme.id,
        user_id=alice.id,
        guest_count=30,
        status=QuoteRequestStatus.completed,
        event_address="1 rue Test",
        event_city="Paris",
        event_zip_code="75001",
        event_date=_dt.date.today() + _dt.timedelta(days=10),
    )
    session.add(qr)
    session.flush()
    quote = Quote(
        quote_request_id=qr.id,
        caterer_id=caterer.id,
        reference=f"DEVIS-OC-{uuid.uuid4().hex[:8]}",
        total_amount_ht=Decimal("450"),
        status=QuoteStatus.accepted,
    )
    session.add(quote)
    session.flush()
    order = Order(
        quote_id=quote.id,
        client_admin_id=alice.id,
        status=OrderStatus.confirmed,
        delivery_date=qr.event_date,
        delivery_address="1 rue Test, 75001 Paris",
    )
    session.add(order)
    session.flush()
    return order, caterer, cat_user


def test_order_confirmed_emails_each_caterer_user(app, session, captured_emails):
    from services import email_triggers

    order, caterer, cat_user = _seed_order_for_email(session)
    with app.app_context():
        email_triggers.order_confirmed(session, order=order)
    assert len(captured_emails) == 1
    call = captured_emails[0]
    assert call["to"] == cat_user.email
    assert "accepté" in call["subject"] or "accepte" in call["subject"]
    # Company name + reference visible in the body.
    assert "ACME Test" in call["html"]
    assert "/caterer/orders/" in call["html"]


def test_order_confirmed_skips_when_no_active_users(app, session, captured_emails):
    from services import email_triggers

    order, caterer, cat_user = _seed_order_for_email(session)
    cat_user.is_active = False
    session.flush()
    with app.app_context():
        email_triggers.order_confirmed(session, order=order)
    assert captured_emails == []
