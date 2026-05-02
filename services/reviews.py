"""Caterer-review aggregates + gating helpers.

Two responsibilities :
  1. *Compute* the public-facing aggregates (average rating + count) for
     one caterer or many at once — used by the catalogue list and detail
     pages so they don't re-query per row.
  2. *Gate* the write path : only the original requester of a `paid`
     order can submit a review, and only once. The check lives here so
     the route handler stays a thin wrapper and tests can drive the
     business rule without a full HTTP context.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import (
    Caterer,
    CatererReview,
    Notification,
    Order,
    OrderStatus,
    Quote,
    QuoteRequest,
    User,
)


@dataclass(frozen=True)
class ReviewAggregate:
    """Public summary of a caterer's reviews."""

    avg: Decimal | None  # rounded to 1 decimal — None when count == 0
    count: int


def aggregates_for_caterers(
    db: Session, caterer_ids: list[uuid.UUID]
) -> dict[uuid.UUID, ReviewAggregate]:
    """Return {caterer_id → ReviewAggregate} in a single query.

    Caterers with no reviews are absent from the dict (caller falls back
    to a `count == 0` aggregate). Callers that paginate the catalogue
    should pass *the IDs of the current page only* — the heavy lifting
    is one GROUP BY scoped to those IDs.
    """
    if not caterer_ids:
        return {}
    rows = db.execute(
        select(
            CatererReview.caterer_id,
            func.avg(CatererReview.rating).label("avg"),
            func.count(CatererReview.id).label("count"),
        )
        .where(CatererReview.caterer_id.in_(caterer_ids))
        .group_by(CatererReview.caterer_id)
    ).all()
    return {
        row.caterer_id: ReviewAggregate(
            # Round to 1 decimal so the catalog displays "4.3" not
            # "4.333333" — Python's `round` is half-banker which is fine
            # for a UI-only value.
            avg=Decimal(round(float(row.avg), 1)) if row.avg is not None else None,
            count=int(row.count),
        )
        for row in rows
    }


def aggregate_for_caterer(db: Session, caterer_id: uuid.UUID) -> ReviewAggregate:
    """Single-caterer convenience wrapper around `aggregates_for_caterers`."""
    return aggregates_for_caterers(db, [caterer_id]).get(
        caterer_id, ReviewAggregate(avg=None, count=0)
    )


def list_for_caterer(
    db: Session, caterer_id: uuid.UUID, *, limit: int | None = None
) -> list[CatererReview]:
    """Return the caterer's reviews newest-first, with reviewer eager-loaded
    so the template can read first_name / last_name / company without N+1."""
    from sqlalchemy.orm import joinedload

    stmt = (
        select(CatererReview)
        .where(CatererReview.caterer_id == caterer_id)
        .options(joinedload(CatererReview.reviewer).joinedload(User.company))
        .order_by(CatererReview.created_at.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.scalars(stmt).all())


def format_author(reviewer: User | None) -> str:
    """Public-safe author label for a review.

    Reduces to "FirstName L. — Company" so we don't expose full names or
    email. Falls back gracefully when fields are missing.
    """
    if reviewer is None:
        return "Anonyme"
    first = (reviewer.first_name or "").strip()
    last_initial = ""
    if reviewer.last_name:
        last_initial = f" {reviewer.last_name.strip()[:1]}."
    company = reviewer.company.name if reviewer.company else None
    name = f"{first}{last_initial}".strip() or "Anonyme"
    return f"{name} — {company}" if company else name


# --- Write path -----------------------------------------------------------


class ReviewError(Exception):
    """Base class for review-write errors mapped by the route handler."""


class OrderNotReviewable(ReviewError):
    """Order doesn't exist, or doesn't satisfy the gating predicate
    (status != paid, viewer isn't the original requester, already
    reviewed)."""


class InvalidRating(ReviewError):
    """Rating is missing, non-integer, or outside [1, 5]."""


def _coerce_rating(raw) -> int:
    try:
        rating = int(raw)
    except (TypeError, ValueError) as exc:
        raise InvalidRating from exc
    if rating < 1 or rating > 5:
        raise InvalidRating
    return rating


def _load_reviewable_order(db: Session, *, order_id: uuid.UUID, viewer: User) -> Order:
    """Return the Order if `viewer` is allowed to review it.

    Allowed iff :
      * the order is in `paid` status,
      * `viewer` is the user who created the underlying QuoteRequest
        (i.e. `qr.user_id == viewer.id`),
      * no review exists yet for this order (UNIQUE on order_id provides
        a DB-level backstop, but checking here gives a clean error).
    """
    order = db.get(Order, order_id)
    if order is None or order.status != OrderStatus.paid:
        raise OrderNotReviewable
    quote = db.get(Quote, order.quote_id)
    if quote is None:
        raise OrderNotReviewable
    qr = db.get(QuoteRequest, quote.quote_request_id)
    if qr is None or qr.user_id != viewer.id:
        raise OrderNotReviewable
    if db.scalar(select(CatererReview.id).where(CatererReview.order_id == order_id)):
        raise OrderNotReviewable
    return order


def submit_review(
    db: Session,
    *,
    order_id: uuid.UUID,
    viewer: User,
    rating_raw,
    comment_raw: str | None,
) -> CatererReview:
    """Persist a new CatererReview after gating on the rules above.

    No commit — caller commits.
    """
    rating = _coerce_rating(rating_raw)
    order = _load_reviewable_order(db, order_id=order_id, viewer=viewer)
    quote = db.get(Quote, order.quote_id)
    review = CatererReview(
        caterer_id=quote.caterer_id,
        order_id=order.id,
        reviewer_user_id=viewer.id,
        rating=rating,
        comment=(comment_raw or "").strip() or None,
    )
    db.add(review)
    db.flush()
    return review


def can_review(db: Session, *, order: Order, viewer: User) -> bool:
    """Cheap predicate the order detail template uses to decide whether
    to render the review form. Mirrors `_load_reviewable_order` without
    raising."""
    try:
        _load_reviewable_order(db, order_id=order.id, viewer=viewer)
    except ReviewError:
        return False
    return True


# --- Notifications --------------------------------------------------------


def notify_review_invite(db: Session, *, order: Order) -> Notification | None:
    """Drop a `review_invite` notification on the requester's feed when
    an order has moved to `paid`. Idempotent — bails out silently when:

    * order isn't actually paid (defense in depth);
    * the requester already reviewed the order;
    * a `review_invite` already exists for this order (we don't want to
      double-notify when, say, a webhook redelivers the `invoice.paid`
      event after we manually flipped the status).

    Caller is responsible for committing.
    """
    if order.status != OrderStatus.paid:
        return None

    quote = db.get(Quote, order.quote_id)
    if quote is None:
        return None
    qr = db.get(QuoteRequest, quote.quote_request_id)
    if qr is None or qr.user_id is None:
        return None

    # Already reviewed → no point inviting.
    if db.scalar(select(CatererReview.id).where(CatererReview.order_id == order.id)):
        return None

    # Already invited → don't spam.
    duplicate = db.scalar(
        select(Notification.id).where(
            Notification.user_id == qr.user_id,
            Notification.type == "review_invite",
            Notification.related_entity_type == "order",
            Notification.related_entity_id == order.id,
        )
    )
    if duplicate:
        return None

    caterer = db.get(Caterer, quote.caterer_id) if quote.caterer_id else None
    caterer_name = caterer.name if caterer else "le traiteur"
    note = Notification(
        user_id=qr.user_id,
        type="review_invite",
        title="Laissez votre avis",
        body=(
            f"Votre commande avec {caterer_name} est désormais payée. "
            "Vous pouvez maintenant laisser un avis sur le traiteur."
        ),
        related_entity_type="order",
        related_entity_id=order.id,
    )
    db.add(note)
    db.flush()
    return note
