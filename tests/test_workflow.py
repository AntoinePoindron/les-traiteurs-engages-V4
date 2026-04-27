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
    Quote,
    QuoteRequest,
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
