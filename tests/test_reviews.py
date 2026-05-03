"""Caterer-review business rules.

Coverage :
  * gating : only the original requester of a *paid* order can review,
    and only once;
  * aggregates : avg + count round to one decimal, ignore caterers with
    no rows;
  * notify_review_invite : creates exactly one notification, refuses
    duplicates, refuses non-paid orders.

Convention : same as test_workflow.py — lazy `database` import inside
each function, fixture rolls back at end. We re-use _seed_confirmed_order
so the fixtures stay aligned.
"""

import datetime as _dt
import uuid
from decimal import Decimal

import pytest

from models import (
    Caterer,
    CatererReview,
    CatererStructureType,
    Company,
    Notification,
    Order,
    OrderStatus,
    Quote,
    QuoteRequest,
    QuoteRequestStatus,
    QuoteStatus,
    User,
    UserRole,
)
from services import reviews as reviews_service


@pytest.fixture
def session(app):
    from database import session_factory

    s = session_factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _seed_paid_order(s) -> tuple[uuid.UUID, Caterer, User]:
    """Create a Caterer + Company + User + QR + Quote(accepted) +
    Order(paid) tied together. Returns (order_id, caterer, requester).
    The requester is the unique seed user `alice@test.local`.
    """
    from sqlalchemy import select

    acme = s.scalar(select(Company).where(Company.siret == "12345678901234"))
    alice = s.scalar(select(User).where(User.email == "alice@test.local"))

    caterer = Caterer(
        name=f"Caterer {uuid.uuid4().hex[:6]}",
        siret=f"77{uuid.uuid4().hex[:12]}",
        structure_type=CatererStructureType.ESAT,
        invoice_prefix=f"R{uuid.uuid4().hex[:4]}",
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
        event_date=_dt.date.today() + _dt.timedelta(days=14),
    )
    s.add(qr)
    s.flush()

    quote = Quote(
        quote_request_id=qr.id,
        caterer_id=caterer.id,
        reference=f"DEVIS-RV-{uuid.uuid4().hex[:8]}",
        total_amount_ht=Decimal("100"),
        status=QuoteStatus.accepted,
    )
    s.add(quote)
    s.flush()

    order = Order(
        quote_id=quote.id,
        client_admin_id=alice.id,
        status=OrderStatus.paid,
        delivery_date=_dt.date.today() - _dt.timedelta(days=1),
        delivery_address="1 rue Test, 75001 Paris",
    )
    s.add(order)
    s.flush()
    return order.id, caterer, alice


# --- Gating ---------------------------------------------------------------


def test_submit_review_happy_path(session):
    from sqlalchemy import select

    order_id, caterer, alice = _seed_paid_order(session)
    review = reviews_service.submit_review(
        session,
        order_id=order_id,
        viewer=alice,
        rating_raw="4",
        comment_raw="Très bon traiteur",
    )
    session.flush()

    persisted = session.scalar(
        select(CatererReview).where(CatererReview.id == review.id)
    )
    assert persisted is not None
    assert persisted.rating == 4
    assert persisted.comment == "Très bon traiteur"
    assert persisted.caterer_id == caterer.id
    assert persisted.reviewer_user_id == alice.id


def test_submit_review_rating_below_one_raises(session):
    order_id, _, alice = _seed_paid_order(session)
    with pytest.raises(reviews_service.InvalidRating):
        reviews_service.submit_review(
            session, order_id=order_id, viewer=alice, rating_raw="0", comment_raw=None
        )


def test_submit_review_rating_above_five_raises(session):
    order_id, _, alice = _seed_paid_order(session)
    with pytest.raises(reviews_service.InvalidRating):
        reviews_service.submit_review(
            session, order_id=order_id, viewer=alice, rating_raw="6", comment_raw=None
        )


def test_submit_review_non_integer_rating_raises(session):
    order_id, _, alice = _seed_paid_order(session)
    with pytest.raises(reviews_service.InvalidRating):
        reviews_service.submit_review(
            session,
            order_id=order_id,
            viewer=alice,
            rating_raw="abc",
            comment_raw=None,
        )


def test_submit_review_blocks_non_requester(session):
    """A user who didn't create the QR can't review even if they're a
    member of the same company."""
    from sqlalchemy import select

    order_id, _, alice = _seed_paid_order(session)
    # Spawn a same-company colleague — alice's company is acme; reusing
    # the seed lookup keeps this test orthogonal to conftest specifics.
    acme = session.scalar(select(Company).where(Company.siret == "12345678901234"))
    colleague = User(
        email=f"colleague-{uuid.uuid4()}@test.local",
        password_hash="x",
        first_name="Colleague",
        last_name="Doe",
        role=UserRole.client_user,
        company_id=acme.id,
    )
    session.add(colleague)
    session.flush()

    with pytest.raises(reviews_service.OrderNotReviewable):
        reviews_service.submit_review(
            session,
            order_id=order_id,
            viewer=colleague,
            rating_raw="5",
            comment_raw=None,
        )


def test_submit_review_blocks_non_paid_order(session):
    from sqlalchemy import select

    order_id, _, alice = _seed_paid_order(session)
    order = session.scalar(select(Order).where(Order.id == order_id))
    order.status = OrderStatus.delivered
    session.flush()

    with pytest.raises(reviews_service.OrderNotReviewable):
        reviews_service.submit_review(
            session, order_id=order_id, viewer=alice, rating_raw="5", comment_raw=None
        )


def test_submit_review_blocks_second_review(session):
    order_id, _, alice = _seed_paid_order(session)
    reviews_service.submit_review(
        session, order_id=order_id, viewer=alice, rating_raw="3", comment_raw=None
    )
    session.flush()

    with pytest.raises(reviews_service.OrderNotReviewable):
        reviews_service.submit_review(
            session,
            order_id=order_id,
            viewer=alice,
            rating_raw="5",
            comment_raw="Encore mieux",
        )


# --- Aggregates -----------------------------------------------------------


def test_aggregate_for_caterer_with_no_reviews_returns_zero(session):
    _, caterer, _ = _seed_paid_order(session)
    agg = reviews_service.aggregate_for_caterer(session, caterer.id)
    assert agg.count == 0
    assert agg.avg is None


def test_aggregate_averages_and_rounds_to_one_decimal(session):
    """Three reviews with different ratings → avg rounded to 1 decimal."""
    order_id, caterer, alice = _seed_paid_order(session)

    # First review on the existing paid order.
    reviews_service.submit_review(
        session, order_id=order_id, viewer=alice, rating_raw="5", comment_raw=None
    )
    # Spawn two more (caterer_id, order_id, requester) tuples — re-use
    # the seed helper to keep the fixtures aligned.
    extra1, _, alice2 = _seed_paid_order(session)
    extra2, _, alice3 = _seed_paid_order(session)
    # Force these new orders to point to the same caterer so the
    # aggregate covers all three.
    from sqlalchemy import select

    for oid in (extra1, extra2):
        order = session.scalar(select(Order).where(Order.id == oid))
        quote = session.scalar(select(Quote).where(Quote.id == order.quote_id))
        quote.caterer_id = caterer.id
        session.flush()
    reviews_service.submit_review(
        session, order_id=extra1, viewer=alice2, rating_raw="3", comment_raw=None
    )
    reviews_service.submit_review(
        session, order_id=extra2, viewer=alice3, rating_raw="4", comment_raw=None
    )
    session.flush()

    agg = reviews_service.aggregate_for_caterer(session, caterer.id)
    assert agg.count == 3
    # (5 + 3 + 4) / 3 = 4.0
    assert float(agg.avg) == 4.0


# --- Notifications --------------------------------------------------------


def test_notify_review_invite_creates_one_notification(session):
    from sqlalchemy import select

    order_id, _, alice = _seed_paid_order(session)
    order = session.scalar(select(Order).where(Order.id == order_id))
    note = reviews_service.notify_review_invite(session, order=order)
    session.flush()

    assert note is not None
    persisted = session.scalar(
        select(Notification).where(
            Notification.user_id == alice.id,
            Notification.type == "review_invite",
            Notification.related_entity_id == order.id,
        )
    )
    assert persisted is not None


def test_notify_review_invite_is_idempotent(session):
    from sqlalchemy import func, select

    order_id, _, _ = _seed_paid_order(session)
    order = session.scalar(select(Order).where(Order.id == order_id))
    reviews_service.notify_review_invite(session, order=order)
    reviews_service.notify_review_invite(session, order=order)
    session.flush()

    count = session.scalar(
        select(func.count(Notification.id)).where(
            Notification.related_entity_id == order.id,
            Notification.type == "review_invite",
        )
    )
    assert count == 1


def test_notify_review_invite_refuses_non_paid_order(session):
    from sqlalchemy import func, select

    order_id, _, _ = _seed_paid_order(session)
    order = session.scalar(select(Order).where(Order.id == order_id))
    order.status = OrderStatus.delivered
    session.flush()
    note = reviews_service.notify_review_invite(session, order=order)
    assert note is None
    count = session.scalar(
        select(func.count(Notification.id)).where(
            Notification.related_entity_id == order.id,
        )
    )
    assert count == 0


def test_notify_review_invite_skips_already_reviewed(session):
    from sqlalchemy import func, select

    order_id, _, alice = _seed_paid_order(session)
    reviews_service.submit_review(
        session, order_id=order_id, viewer=alice, rating_raw="5", comment_raw=None
    )
    session.flush()
    order = session.scalar(select(Order).where(Order.id == order_id))
    note = reviews_service.notify_review_invite(session, order=order)
    assert note is None
    count = session.scalar(
        select(func.count(Notification.id)).where(
            Notification.type == "review_invite",
            Notification.related_entity_id == order.id,
        )
    )
    assert count == 0
