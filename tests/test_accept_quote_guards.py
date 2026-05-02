"""Audit finding #5: accept_quote must refuse draft/refused/expired quotes.

Background:
    POST /client/requests/<id>/accept-quote only scopes by company_id and
    by the quote belonging to the request. It does NOT enforce
        Quote.status == sent
    nor
        Quote.valid_until >= today
    So a client (or a pending attacker pre-fix #4) could "accept" a
    caterer's draft, refused, or long-expired quote — creating an Order
    the caterer never committed to.
"""

import datetime as _dt


def _seed_request_with_quote(status_literal: str, valid_until=None):
    """Create a QuoteRequest for alice's company + a Quote of the given
    status. Returns (quote_request_id, quote_id) as UUIDs."""
    from decimal import Decimal
    from sqlalchemy import select

    from database import session_factory
    from models import (
        Caterer,
        Company,
        Quote,
        QuoteRequest,
        QuoteRequestStatus,
        QuoteStatus,
        User,
    )

    status = QuoteStatus(status_literal)

    s = session_factory()
    try:
        acme = s.scalar(select(Company).where(Company.siret == "12345678901234"))
        caterer = s.scalar(select(Caterer).where(Caterer.siret == "98765432109876"))
        alice = s.scalar(select(User).where(User.email == "alice@test.local"))

        qr = QuoteRequest(
            company_id=acme.id,
            user_id=alice.id,
            guest_count=10,
            status=QuoteRequestStatus.sent_to_caterers,
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
            reference=f"DEVIS-TST-{qr.id.hex[:6].upper()}",
            total_amount_ht=Decimal("100"),
            status=status,
            valid_until=valid_until,
        )
        s.add(quote)
        s.commit()
        return qr.id, quote.id
    finally:
        s.close()


def _order_exists_for_quote(quote_id) -> bool:
    from sqlalchemy import select

    from database import session_factory
    from models import Order

    s = session_factory()
    try:
        return s.scalar(select(Order).where(Order.quote_id == quote_id)) is not None
    finally:
        s.close()


def test_accepting_draft_quote_does_not_create_order(client, login):
    qr_id, quote_id = _seed_request_with_quote("draft")
    login("alice@test.local")
    resp = client.post(
        f"/client/requests/{qr_id}/accept-quote",
        data={"quote_id": str(quote_id)},
    )
    assert resp.status_code in (302, 400, 404), resp.status_code
    assert not _order_exists_for_quote(quote_id), (
        "draft quote should never be acceptable — no Order should exist"
    )


def test_accepting_refused_quote_does_not_create_order(client, login):
    qr_id, quote_id = _seed_request_with_quote("refused")
    login("alice@test.local")
    resp = client.post(
        f"/client/requests/{qr_id}/accept-quote",
        data={"quote_id": str(quote_id)},
    )
    assert resp.status_code in (302, 400, 404)
    assert not _order_exists_for_quote(quote_id)


def test_accepting_expired_quote_does_not_create_order(client, login):
    yesterday = _dt.date.today() - _dt.timedelta(days=1)
    qr_id, quote_id = _seed_request_with_quote("sent", valid_until=yesterday)
    login("alice@test.local")
    resp = client.post(
        f"/client/requests/{qr_id}/accept-quote",
        data={"quote_id": str(quote_id)},
    )
    assert resp.status_code in (302, 400, 404)
    assert not _order_exists_for_quote(quote_id), "expired quote must not be acceptable"


def test_accepting_sent_quote_creates_order(client, login):
    """Regression guard: the happy path still works."""
    tomorrow = _dt.date.today() + _dt.timedelta(days=7)
    qr_id, quote_id = _seed_request_with_quote("sent", valid_until=tomorrow)
    login("alice@test.local")
    resp = client.post(
        f"/client/requests/{qr_id}/accept-quote",
        data={"quote_id": str(quote_id)},
    )
    assert resp.status_code in (200, 302), resp.status_code
    assert _order_exists_for_quote(quote_id)


def test_client_user_can_accept_quote(client, login):
    """Both client_admin and client_user can accept a quote on behalf
    of their company. Bob is a client_user in the same company as alice
    (ACME Test) — he must NOT get a 403 here."""
    tomorrow = _dt.date.today() + _dt.timedelta(days=7)
    qr_id, quote_id = _seed_request_with_quote("sent", valid_until=tomorrow)
    login("bob@test.local")
    resp = client.post(
        f"/client/requests/{qr_id}/accept-quote",
        data={"quote_id": str(quote_id)},
    )
    assert resp.status_code in (200, 302), resp.status_code
    assert _order_exists_for_quote(quote_id)


def test_client_user_can_refuse_quote(client, login):
    """Symmetric with accept: client_user from the same company can
    refuse a quote without a 403."""
    tomorrow = _dt.date.today() + _dt.timedelta(days=7)
    qr_id, quote_id = _seed_request_with_quote("sent", valid_until=tomorrow)
    login("bob@test.local")
    resp = client.post(
        f"/client/requests/{qr_id}/refuse-quote",
        data={"quote_id": str(quote_id), "reason": "trop cher"},
    )
    assert resp.status_code in (200, 302), resp.status_code
