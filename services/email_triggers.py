"""High-level email trigger functions.

Each function here owns the "should we send this email?" decision +
the template-context assembly. The route handlers stay one-liners:

    email_triggers.notify_quote_transmitted(db, quote=quote, caterer=caterer)

Why a separate module rather than inlining in each route?
  * Keeps the email logic out of the request/response layer so the
    route handler stays focused on HTTP concerns;
  * Lets services/workflow.py call the trigger without dragging Flask
    into workflow tests (the trigger itself handles the lazy
    `render_template` import + Flask context expectations);
  * One place to grep when we add a new email use-case.

All triggers are best-effort : they wrap the dramatiq enqueue in a
try/except so a Brevo / queue hiccup never sinks the underlying
business operation. Failures are logged at WARNING; the queued job
itself has its own retry policy (cf. services.email).
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from models import (
    Caterer,
    Order,
    QRCStatus,
    Quote,
    QuoteRequest,
    QuoteRequestCaterer,
    User,
)
from services.email import render_and_send_async


logger = logging.getLogger(__name__)


def _safe(label: str):
    """Decorator wrapping the trigger so a queue / template error doesn't
    bubble up into the calling route. The business write is already
    committed at the call point; an email failure shouldn't roll it back."""

    def deco(fn):
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception:  # noqa: BLE001
                logger.warning("email trigger %s failed", label, exc_info=True)
                return None

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper

    return deco


# --- E2 — Welcome email ---------------------------------------------------


@_safe("welcome_signup")
def welcome_signup(user: User, *, role_kind: str, cta_path: str) -> None:
    """Send the role-specific welcome email after a successful signup.

    `role_kind` ∈ {"client", "caterer", "admin"} drives the body. The
    user account is already persisted at the call site; we just queue
    the email.
    """
    render_and_send_async(
        to=user.email,
        subject="Bienvenue chez Les Traiteurs Engagés",
        template_name="welcome",
        user=user,
        role_kind=role_kind,
        cta_url=f"{config.BASE_URL}{cta_path}",
    )


# --- E5 — Quote received --------------------------------------------------


@_safe("quote_received")
def quote_received(db: Session, *, quote: Quote, caterer: Caterer) -> None:
    """Email the client when one of their solicited caterers transmits a
    quote (rank 1, 2 or 3 of the "first 3 responders" rule).

    No-ops when:
      * the corresponding QRC is NOT in `transmitted_to_client` (the 4th+
        responder doesn't trigger the email — they're closed out);
      * the QR has no user_id (defensive — should never happen);
      * the requester is inactive.
    """
    qrc = db.scalar(
        select(QuoteRequestCaterer).where(
            QuoteRequestCaterer.quote_request_id == quote.quote_request_id,
            QuoteRequestCaterer.caterer_id == caterer.id,
        )
    )
    if qrc is None or qrc.status != QRCStatus.transmitted_to_client:
        return
    qr = db.get(QuoteRequest, quote.quote_request_id)
    if qr is None or qr.user_id is None:
        return
    user = db.get(User, qr.user_id)
    if user is None or not user.is_active:
        return

    cta_url = f"{config.BASE_URL}/client/requests/{qr.id}"
    render_and_send_async(
        to=user.email,
        subject="Vous avez reçu un devis",
        template_name="quote_received",
        user=user,
        caterer=caterer,
        event_date=qr.event_date,
        total_amount_ht=quote.total_amount_ht,
        amount_per_person=quote.amount_per_person,
        valid_until=quote.valid_until,
        cta_url=cta_url,
    )


# --- E6 — Order confirmed (caterer side) ---------------------------------


@_safe("order_confirmed")
def order_confirmed(db: Session, *, order: Order) -> None:
    """Email every active user of the caterer that the client just
    accepted their quote and the order is confirmed.

    Multi-user caterers: send to each. Brevo's `to` field accepts a
    list, but bumping it through `render_and_send_async` per user keeps
    the rendering simple and lets one bad address not sink the others.
    """
    quote = db.get(Quote, order.quote_id)
    if quote is None:
        return
    caterer = db.get(Caterer, quote.caterer_id) if quote.caterer_id else None
    qr = (
        db.get(QuoteRequest, quote.quote_request_id) if quote.quote_request_id else None
    )
    if caterer is None or qr is None:
        return

    company = qr.company  # eager via relationship; falls back to a query
    recipients = [u for u in (caterer.users or []) if u.is_active]
    if not recipients:
        return

    cta_url = f"{config.BASE_URL}/caterer/orders/{order.id}"
    for user in recipients:
        render_and_send_async(
            to=user.email,
            subject="Votre devis a été accepté",
            template_name="order_confirmed",
            user=user,
            caterer=caterer,
            company=company,
            quote_reference=quote.reference,
            event_date=qr.event_date,
            guest_count=qr.guest_count,
            delivery_address=order.delivery_address,
            total_amount_ht=quote.total_amount_ht,
            cta_url=cta_url,
        )
