"""Instance-level access scoping helpers.

Every query that fetches a resource owned by a client company or caterer
MUST go through these helpers so the ownership filter cannot be forgotten.
"""

from flask import abort
from sqlalchemy import select

from database import get_db
from models import (
    CompanyEmployee,
    CompanyService,
    Order,
    Quote,
    QuoteRequest,
    QuoteRequestCaterer,
    User,
)


# ---------------------------------------------------------------------------
# Client-side: scope by company_id
# ---------------------------------------------------------------------------


def get_company_request(request_id, company_id):
    """Fetch a QuoteRequest owned by `company_id`, or abort 404."""
    db = get_db()
    qr = db.execute(
        select(QuoteRequest).where(
            QuoteRequest.id == request_id,
            QuoteRequest.company_id == company_id,
        )
    ).scalar_one_or_none()
    if not qr:
        abort(404)
    return qr


def get_company_order(order_id, company_id):
    """Fetch an Order whose QuoteRequest belongs to `company_id`, or abort 404."""
    db = get_db()
    order = db.execute(
        select(Order)
        .join(Quote, Order.quote_id == Quote.id)
        .join(QuoteRequest, Quote.quote_request_id == QuoteRequest.id)
        .where(Order.id == order_id, QuoteRequest.company_id == company_id)
    ).scalar_one_or_none()
    if not order:
        abort(404)
    return order


def get_company_service(service_id, company_id):
    """Fetch a CompanyService owned by `company_id`, or abort 404."""
    db = get_db()
    service = db.scalar(
        select(CompanyService).where(
            CompanyService.id == service_id,
            CompanyService.company_id == company_id,
        )
    )
    if not service:
        abort(404)
    return service


def get_company_employee(employee_id, company_id):
    """Fetch a CompanyEmployee owned by `company_id`, or abort 404."""
    db = get_db()
    employee = db.scalar(
        select(CompanyEmployee).where(
            CompanyEmployee.id == employee_id,
            CompanyEmployee.company_id == company_id,
        )
    )
    if not employee:
        abort(404)
    return employee


def get_pending_user(user_id, company_id):
    """Fetch a pending User in `company_id`, or abort 404."""
    from models import MembershipStatus

    db = get_db()
    user = db.scalar(
        select(User).where(
            User.id == user_id,
            User.company_id == company_id,
            User.membership_status == MembershipStatus.pending,
        )
    )
    if not user:
        abort(404)
    return user


# ---------------------------------------------------------------------------
# Caterer-side: scope by caterer_id
# ---------------------------------------------------------------------------


def get_caterer_qrc(qr_id, caterer_id):
    """Fetch a QuoteRequestCaterer for `caterer_id`, or abort 404."""
    db = get_db()
    qrc = db.scalar(
        select(QuoteRequestCaterer)
        .where(QuoteRequestCaterer.quote_request_id == qr_id)
        .where(QuoteRequestCaterer.caterer_id == caterer_id)
    )
    if not qrc:
        abort(404)
    return qrc


def get_caterer_quote(qr_id, quote_id, caterer_id):
    """Fetch a Quote owned by `caterer_id` for a given request, or abort 404."""
    db = get_db()
    quote = db.scalar(
        select(Quote)
        .where(Quote.id == quote_id)
        .where(Quote.caterer_id == caterer_id)
        .where(Quote.quote_request_id == qr_id)
    )
    if not quote:
        abort(404)
    return quote


def get_caterer_order(order_id, caterer_id):
    """Fetch an Order whose Quote belongs to `caterer_id`, or abort 404."""
    db = get_db()
    order = db.scalar(
        select(Order)
        .join(Quote, Order.quote_id == Quote.id)
        .where(Order.id == order_id)
        .where(Quote.caterer_id == caterer_id)
    )
    if not order:
        abort(404)
    return order
