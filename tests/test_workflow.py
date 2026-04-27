"""Tests directs des transitions workflow — pas de contexte HTTP.

Stratégie d'isolation : la fixture `session` rollback à la fin. Les
helpers de seed font `flush()`, jamais `commit()`, pour que rien ne
persiste entre tests.

Convention d'imports lazy : `database` (et donc `config.DATABASE_URL`)
est importé *à l'intérieur* des fonctions, pas au top-level. Sinon le
`engine` est figé sur la DB de dev avant que conftest ne switch sur
`traiteurs_test`. Voir `tests/test_accept_quote_guards.py` pour le même
pattern.
"""
import datetime as _dt
import uuid
from decimal import Decimal

import pytest

from models import (
    Caterer,
    Company,
    Order,
    OrderStatus,
    QRCStatus,
    Quote,
    QuoteRequest,
    QuoteRequestCaterer,
    QuoteRequestStatus,
    QuoteStatus,
    User,
    UserRole,
)
from services import workflow


@pytest.fixture
def session(app):
    """Session SQLAlchemy par test, rollback à la fin (isolation)."""
    from database import session_factory
    s = session_factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _seed_qr_with_quotes(s, *, statuses: list[QuoteStatus]) -> tuple[uuid.UUID, list[uuid.UUID]]:
    from sqlalchemy import select

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

    quote_ids = []
    for i, st in enumerate(statuses):
        q = Quote(
            quote_request_id=qr.id,
            caterer_id=caterer.id,
            reference=f"DEVIS-TST-{qr.id.hex[:8]}-{i}",
            total_amount_ht=Decimal("100"),
            status=st,
        )
        s.add(q)
        s.flush()
        quote_ids.append(q.id)
    return qr.id, quote_ids


def test_refuse_quote_marks_refused_and_keeps_request_open(session):
    from sqlalchemy import select

    qr_id, qids = _seed_qr_with_quotes(session, statuses=[QuoteStatus.sent, QuoteStatus.sent])
    alice = session.scalar(select(User).where(User.email == "alice@test.local"))

    workflow.refuse_quote(
        session,
        request_id=qr_id,
        quote_id=qids[0],
        user=alice,
        reason="trop cher",
    )
    session.flush()

    refused = session.scalar(select(Quote).where(Quote.id == qids[0]))
    qr = session.scalar(select(QuoteRequest).where(QuoteRequest.id == qr_id))
    assert refused.status == QuoteStatus.refused
    assert refused.refusal_reason == "trop cher"
    assert qr.status == QuoteRequestStatus.sent_to_caterers


def test_refuse_last_sent_quote_closes_request(session):
    from sqlalchemy import select

    qr_id, qids = _seed_qr_with_quotes(session, statuses=[QuoteStatus.sent])
    alice = session.scalar(select(User).where(User.email == "alice@test.local"))

    workflow.refuse_quote(
        session,
        request_id=qr_id,
        quote_id=qids[0],
        user=alice,
        reason=None,
    )
    session.flush()

    qr = session.scalar(select(QuoteRequest).where(QuoteRequest.id == qr_id))
    assert qr.status == QuoteRequestStatus.quotes_refused


def test_refuse_quote_for_other_company_raises_request_not_found(session):
    qr_id, qids = _seed_qr_with_quotes(session, statuses=[QuoteStatus.sent])

    other_co = Company(name="Other Co Test", siret=f"99{uuid.uuid4().hex[:12]}")
    session.add(other_co)
    session.flush()
    intruder = User(
        email=f"intruder-{uuid.uuid4()}@test.local",
        password_hash="x",
        first_name="I", last_name="N",
        role=UserRole.client_admin,
        company_id=other_co.id,
    )
    session.add(intruder)
    session.flush()

    with pytest.raises(workflow.RequestNotFound):
        workflow.refuse_quote(
            session,
            request_id=qr_id,
            quote_id=qids[0],
            user=intruder,
            reason=None,
        )


def test_refuse_unknown_quote_raises_quote_not_found(session):
    from sqlalchemy import select

    qr_id, _ = _seed_qr_with_quotes(session, statuses=[QuoteStatus.sent])
    alice = session.scalar(select(User).where(User.email == "alice@test.local"))

    with pytest.raises(workflow.QuoteNotFound):
        workflow.refuse_quote(
            session,
            request_id=qr_id,
            quote_id=uuid.uuid4(),
            user=alice,
            reason=None,
        )


# --- accept_quote ---------------------------------------------------------


def _set_valid_until(s, quote_id: uuid.UUID, valid_until: _dt.date | None) -> None:
    from sqlalchemy import select

    quote = s.scalar(select(Quote).where(Quote.id == quote_id))
    quote.valid_until = valid_until
    s.flush()


def test_accept_quote_creates_order_and_refuses_peers(session):
    from sqlalchemy import select

    qr_id, qids = _seed_qr_with_quotes(session, statuses=[QuoteStatus.sent, QuoteStatus.sent])
    _set_valid_until(session, qids[0], _dt.date.today() + _dt.timedelta(days=7))
    alice = session.scalar(select(User).where(User.email == "alice@test.local"))

    order = workflow.accept_quote(
        session,
        request_id=qr_id,
        quote_id=qids[0],
        user=alice,
    )
    session.flush()

    accepted = session.scalar(select(Quote).where(Quote.id == qids[0]))
    peer = session.scalar(select(Quote).where(Quote.id == qids[1]))
    qr = session.scalar(select(QuoteRequest).where(QuoteRequest.id == qr_id))
    assert accepted.status == QuoteStatus.accepted
    assert peer.status == QuoteStatus.refused
    assert peer.refusal_reason == "Un autre devis a ete accepte."
    assert qr.status == QuoteRequestStatus.completed
    assert order.status == OrderStatus.confirmed
    assert order.quote_id == qids[0]


def test_accept_draft_quote_raises_not_available(session):
    from sqlalchemy import select

    qr_id, qids = _seed_qr_with_quotes(session, statuses=[QuoteStatus.draft])
    alice = session.scalar(select(User).where(User.email == "alice@test.local"))

    with pytest.raises(workflow.QuoteNotAvailable):
        workflow.accept_quote(session, request_id=qr_id, quote_id=qids[0], user=alice)
    assert session.scalar(select(Order).where(Order.quote_id == qids[0])) is None


def test_accept_refused_quote_raises_not_available(session):
    from sqlalchemy import select

    qr_id, qids = _seed_qr_with_quotes(session, statuses=[QuoteStatus.refused])
    alice = session.scalar(select(User).where(User.email == "alice@test.local"))

    with pytest.raises(workflow.QuoteNotAvailable):
        workflow.accept_quote(session, request_id=qr_id, quote_id=qids[0], user=alice)


def test_accept_expired_quote_raises_expired(session):
    from sqlalchemy import select

    qr_id, qids = _seed_qr_with_quotes(session, statuses=[QuoteStatus.sent])
    _set_valid_until(session, qids[0], _dt.date.today() - _dt.timedelta(days=1))
    alice = session.scalar(select(User).where(User.email == "alice@test.local"))

    with pytest.raises(workflow.QuoteExpired):
        workflow.accept_quote(session, request_id=qr_id, quote_id=qids[0], user=alice)
    assert session.scalar(select(Order).where(Order.quote_id == qids[0])) is None


def test_accept_quote_for_other_company_raises_request_not_found(session):
    qr_id, qids = _seed_qr_with_quotes(session, statuses=[QuoteStatus.sent])

    other_co = Company(name="Other Co Test 2", siret=f"88{uuid.uuid4().hex[:12]}")
    session.add(other_co)
    session.flush()
    intruder = User(
        email=f"intruder2-{uuid.uuid4()}@test.local",
        password_hash="x",
        first_name="I", last_name="N",
        role=UserRole.client_admin,
        company_id=other_co.id,
    )
    session.add(intruder)
    session.flush()

    with pytest.raises(workflow.RequestNotFound):
        workflow.accept_quote(session, request_id=qr_id, quote_id=qids[0], user=intruder)


# --- approve_quote_request / reject_quote_request -------------------------


def _seed_pending_review_qr(s, *, with_geo: bool) -> uuid.UUID:
    """QR en pending_review. `with_geo=True` met lat/lng pour permettre le matching."""
    from sqlalchemy import select

    acme = s.scalar(select(Company).where(Company.siret == "12345678901234"))
    alice = s.scalar(select(User).where(User.email == "alice@test.local"))
    qr = QuoteRequest(
        company_id=acme.id,
        user_id=alice.id,
        guest_count=10,
        status=QuoteRequestStatus.pending_review,
        event_address="1 rue Test",
        event_city="Paris",
        event_zip_code="75001",
        event_date=_dt.date.today() + _dt.timedelta(days=30),
        event_latitude=48.8566 if with_geo else None,
        event_longitude=2.3522 if with_geo else None,
    )
    s.add(qr)
    s.flush()
    return qr.id


def test_approve_quote_request_dispatches_to_matching_caterers(session):
    from sqlalchemy import select

    qr_id = _seed_pending_review_qr(session, with_geo=True)
    # Aligne le caterer seedé avec la demande pour qu'il soit matché.
    caterer = session.scalar(select(Caterer).where(Caterer.siret == "98765432109876"))
    caterer.latitude = 48.8566
    caterer.longitude = 2.3522
    caterer.delivery_radius_km = 50
    session.flush()

    qrcs = workflow.approve_quote_request(session, request_id=qr_id)
    session.flush()

    assert len(qrcs) >= 1
    qr = session.scalar(select(QuoteRequest).where(QuoteRequest.id == qr_id))
    assert qr.status == QuoteRequestStatus.sent_to_caterers
    persisted = session.scalars(
        select(QuoteRequestCaterer).where(QuoteRequestCaterer.quote_request_id == qr_id)
    ).all()
    assert len(persisted) == len(qrcs)
    assert all(q.status == QRCStatus.selected for q in persisted)


def test_approve_quote_request_with_no_matches_raises(session):
    from sqlalchemy import select

    qr_id = _seed_pending_review_qr(session, with_geo=False)

    with pytest.raises(workflow.NoMatchingCaterers):
        workflow.approve_quote_request(session, request_id=qr_id)

    qr = session.scalar(select(QuoteRequest).where(QuoteRequest.id == qr_id))
    assert qr.status == QuoteRequestStatus.pending_review


def test_approve_unknown_request_raises_not_found(session):
    with pytest.raises(workflow.RequestNotFound):
        workflow.approve_quote_request(session, request_id=uuid.uuid4())


def test_reject_quote_request_marks_cancelled_with_reason(session):
    from sqlalchemy import select

    qr_id = _seed_pending_review_qr(session, with_geo=True)

    workflow.reject_quote_request(session, request_id=qr_id, reason="hors zone")
    session.flush()

    qr = session.scalar(select(QuoteRequest).where(QuoteRequest.id == qr_id))
    assert qr.status == QuoteRequestStatus.cancelled
    assert qr.message_to_caterer == "hors zone"


def test_reject_unknown_request_raises_not_found(session):
    with pytest.raises(workflow.RequestNotFound):
        workflow.reject_quote_request(session, request_id=uuid.uuid4(), reason=None)
