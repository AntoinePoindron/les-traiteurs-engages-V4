"""Instance-level access scoping helpers.

Every query that fetches a resource owned by a client company or caterer
MUST go through these helpers so the ownership filter cannot be forgotten.

For requests/orders, the role of the caller decides the scope:
  - `client_admin`  → sees every demand/commande of the company.
  - `client_user`   → sees only the demands they created themselves
                      (and the commandes that flow from those).
This keeps a regular user's space focused on their own activity, while
the admin keeps the company-wide overview needed to coordinate.
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
    UserRole,
)


def own_requests_filter(user):
    """SQL predicate restricting QuoteRequest to the user's own demands
    when they are a `client_user`. For `client_admin` (and other roles),
    returns None so the caller can skip the filter without branching.

    Use as:
        stmt = select(QuoteRequest).where(QuoteRequest.company_id == user.company_id)
        own_only = own_requests_filter(user)
        if own_only is not None:
            stmt = stmt.where(own_only)
    """
    if user.role == UserRole.client_user:
        return QuoteRequest.user_id == user.id
    return None


# ---------------------------------------------------------------------------
# Client-side: scope by company_id (and by user_id for client_user)
# ---------------------------------------------------------------------------


def get_company_request(request_id, user):
    """Fetch a QuoteRequest the `user` is allowed to see, or abort 404.

    `user` is the current User; admin sees the whole company, client_user
    sees only their own demands.
    """
    db = get_db()
    stmt = select(QuoteRequest).where(
        QuoteRequest.id == request_id,
        QuoteRequest.company_id == user.company_id,
    )
    own_only = own_requests_filter(user)
    if own_only is not None:
        stmt = stmt.where(own_only)
    qr = db.execute(stmt).scalar_one_or_none()
    if not qr:
        abort(404)
    return qr


def get_company_order(order_id, user):
    """Fetch an Order the `user` is allowed to see, or abort 404.

    Scoped via the underlying QuoteRequest: admins see all the company's
    orders, client_user sees only the orders flowing from QRs they
    themselves created.
    """
    db = get_db()
    stmt = (
        select(Order)
        .join(Quote, Order.quote_id == Quote.id)
        .join(QuoteRequest, Quote.quote_request_id == QuoteRequest.id)
        .where(Order.id == order_id, QuoteRequest.company_id == user.company_id)
    )
    own_only = own_requests_filter(user)
    if own_only is not None:
        stmt = stmt.where(own_only)
    order = db.execute(stmt).scalar_one_or_none()
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
