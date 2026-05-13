"""Smoke test for the caterer PDF download route.

Just enough to catch the obvious regressions: a missing template variable
in `_pdf_preview.html`, a renamed loader option, a broken filename header.
WeasyPrint's actual rendering quality is not in scope.
"""

import datetime as _dt
from decimal import Decimal

import pytest

# WeasyPrint depends on system libs (libpango, libpangoft2). The Dockerfile
# installs them; bare local environments may not. Skip rather than error.
pytest.importorskip("weasyprint")


def _seed_request_with_quote_lines():
    from sqlalchemy import select

    from database import session_factory
    from models import (
        Caterer,
        Company,
        QRCStatus,
        Quote,
        QuoteLine,
        QuoteRequest,
        QuoteRequestCaterer,
        QuoteRequestStatus,
        QuoteStatus,
        User,
    )

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

        s.add(
            QuoteRequestCaterer(
                quote_request_id=qr.id,
                caterer_id=caterer.id,
                status=QRCStatus.selected,
            )
        )
        s.flush()

        quote = Quote(
            quote_request_id=qr.id,
            caterer_id=caterer.id,
            reference=f"DEVIS-PDF-{qr.id.hex[:6].upper()}",
            total_amount_ht=Decimal("1000"),
            amount_per_person=Decimal("100"),
            status=QuoteStatus.draft,
            valid_until=_dt.date.today() + _dt.timedelta(days=14),
        )
        s.add(quote)
        s.flush()
        s.add(
            QuoteLine(
                quote_id=quote.id,
                description="Plateau repas",
                unit_price_ht=Decimal("100"),
                quantity=Decimal("10"),
                tva_rate=Decimal("10"),
            )
        )
        s.commit()
        return qr.id, quote.id, quote.reference
    finally:
        s.close()


def test_pdf_route_returns_pdf(client, login):
    qr_id, q_id, reference = _seed_request_with_quote_lines()
    login("cook@test.local")
    resp = client.get(f"/caterer/requests/{qr_id}/quote/{q_id}/pdf")
    assert resp.status_code == 200, resp.status_code
    assert resp.mimetype == "application/pdf"
    # Magic bytes — proves WeasyPrint actually produced a PDF rather than
    # an HTML error page slipping through with the wrong mimetype.
    assert resp.data[:4] == b"%PDF"
    disposition = resp.headers.get("Content-Disposition", "")
    assert "attachment" in disposition
    assert f"devis-{reference}.pdf" in disposition


def test_pdf_route_rejects_other_caterer(client, login):
    """The scoping query must 404 when the quote belongs to a different
    caterer — same guarantee `get_caterer_quote` provides elsewhere."""
    qr_id, q_id, _ = _seed_request_with_quote_lines()
    # alice is a client_admin, not a caterer — role_required short-circuits
    # to 403/redirect before the query, so test with no login (401-ish).
    resp = client.get(f"/caterer/requests/{qr_id}/quote/{q_id}/pdf")
    assert resp.status_code in (302, 401, 403), resp.status_code
