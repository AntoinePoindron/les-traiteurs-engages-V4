import logging
import uuid

from flask import Blueprint, abort, g, jsonify, request
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

import config
from extensions import csrf, limiter
from blueprints.middleware import login_required
from database import get_db
from models import (
    Caterer,
    Message,
    Notification,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    Quote,
    QuoteRequest,
    QuoteRequestCaterer,
    StripeEvent,
    User,
)
from services.audit import log_admin_action
from services.notifications import create_notification, get_unread_count, mark_as_read
from services.stripe_service import verify_webhook_signature

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api")

# Terminal payment states that a subsequent webhook must NEVER downgrade.
# Stripe delivers events out of order and retries on failure, so a stale
# `invoice.payment_failed` can arrive after `invoice.paid`.
_TERMINAL_PAID_STATES = {PaymentStatus.succeeded, PaymentStatus.refunded}


@api_bp.route("/webhooks/stripe", methods=["POST"])
@csrf.exempt
@limiter.exempt  # Stripe retries legitimately and sends bursts
def stripe_webhook():
    # Fail closed when the shared secret is missing. HMAC with an empty key
    # is trivially computable by anyone, so accepting such signatures would
    # let any caller forge events. Audit finding #1 (2026-04-24).
    if not config.STRIPE_WEBHOOK_SECRET:
        logger.error("STRIPE_WEBHOOK_SECRET is not configured; refusing webhook")
        return jsonify({"error": "webhook not configured"}), 503

    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = verify_webhook_signature(
            payload, sig_header, config.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        logger.warning("Invalid Stripe webhook signature")
        return jsonify({"error": "invalid signature"}), 400

    # `event` is a stripe.Event (not a plain dict and not a subclass of dict
    # in current SDKs) — use subscript access + getattr-style helpers instead
    # of `.get(...)`. Audit finding #2 (2026-04-24).
    event_id = event["id"]
    event_type = event["type"]
    data_object = event["data"]["object"]

    def _field(obj, key, default=None):
        """Read a field from a StripeObject OR plain dict."""
        try:
            return obj[key]
        except (KeyError, TypeError):
            return default

    # Atomic dedup: insert the event.id inside its own transaction. A UNIQUE
    # violation means we've seen this event before (Stripe retry, out-of-order
    # redelivery, or signature-window replay attack). Audit finding #3.
    db = get_db()
    try:
        db.add(StripeEvent(id=event_id, event_type=event_type))
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.info("Ignoring duplicate Stripe event %s (%s)", event_id, event_type)
        return jsonify({"status": "duplicate"}), 200

    if event_type == "invoice.paid":
        stripe_invoice_id = _field(data_object, "id")
        payment = db.scalar(
            select(Payment).where(Payment.stripe_invoice_id == stripe_invoice_id)
        )
        if payment:
            payment.status = PaymentStatus.succeeded
            payment.stripe_charge_id = _field(data_object, "charge")
            order = db.scalar(select(Order).where(Order.id == payment.order_id))
            if order:
                order.status = OrderStatus.paid
        db.commit()

    elif event_type == "invoice.payment_failed":
        stripe_invoice_id = _field(data_object, "id")
        payment = db.scalar(
            select(Payment).where(Payment.stripe_invoice_id == stripe_invoice_id)
        )
        if payment and payment.status not in _TERMINAL_PAID_STATES:
            payment.status = PaymentStatus.failed
        elif payment:
            logger.warning(
                "Ignoring stale invoice.payment_failed for payment %s (current status: %s)",
                payment.id,
                payment.status,
            )
        db.commit()

    elif event_type == "account.updated":
        account_id = _field(data_object, "id")
        caterer = db.scalar(
            select(Caterer).where(Caterer.stripe_account_id == account_id)
        )
        if caterer:
            caterer.stripe_charges_enabled = _field(
                data_object, "charges_enabled", False
            )
            caterer.stripe_payouts_enabled = _field(
                data_object, "payouts_enabled", False
            )
        db.commit()

    return jsonify({"status": "ok"}), 200


@api_bp.route("/messages/<uuid:thread_id>")
@login_required
def get_messages(thread_id):
    user = g.current_user
    db = get_db()
    is_admin = user.role == "super_admin"
    stmt = (
        select(Message)
        .where(Message.thread_id == thread_id)
        .options(joinedload(Message.sender))
        .order_by(Message.created_at.asc())
    )
    if not is_admin:
        stmt = stmt.where(
            or_(Message.sender_id == user.id, Message.recipient_id == user.id)
        )
    else:
        log_admin_action(
            db, user, "message.admin_view", target_type="thread", target_id=thread_id
        )
    messages = db.scalars(stmt).all()

    if not is_admin:
        db.execute(
            Message.__table__.update()
            .where(
                Message.thread_id == thread_id,
                Message.recipient_id == user.id,
                Message.is_read.is_(False),
            )
            .values(is_read=True)
        )
    db.commit()

    result = []
    for msg in messages:
        sender = msg.sender
        result.append(
            {
                "id": str(msg.id),
                "thread_id": str(msg.thread_id),
                "sender_id": str(msg.sender_id),
                "recipient_id": str(msg.recipient_id),
                "sender_name": f"{sender.first_name} {sender.last_name}"
                if sender
                else "Inconnu",
                "body": msg.body,
                "is_read": msg.is_read,
                "created_at": msg.created_at.isoformat(),
            }
        )
    return jsonify({"messages": result})


def _allowed_recipients_for(db, user, *, order_id=None, quote_request_id=None):
    """Return the set of user IDs the current user is allowed to message in
    the context of the given order or quote_request. VULN-04 (audit 1).

    Membership rule (Option A — strict):
    - Order context: client company users + the assigned caterer's users.
    - Quote-request context: client company users + every solicited caterer's
      users (so a caterer who hasn't quoted yet can still ask questions).
    Returns an empty set when the current user has no relation to the entity,
    or when the entity does not exist. Self is always excluded.
    """
    qr_id = quote_request_id
    caterer_ids: set[uuid.UUID] = set()
    company_id: uuid.UUID | None = None

    if order_id:
        order = db.get(Order, order_id)
        if not order:
            return set()
        quote = db.get(Quote, order.quote_id)
        if not quote:
            return set()
        qr_id = quote.quote_request_id
        caterer_ids.add(quote.caterer_id)

    if qr_id:
        qr = db.get(QuoteRequest, qr_id)
        if not qr:
            return set()
        company_id = qr.company_id
        # Include every caterer solicited on the QR, not just those who quoted —
        # a caterer reviewing a brief must be able to message the client.
        qrc_caterer_ids = db.scalars(
            select(QuoteRequestCaterer.caterer_id).where(
                QuoteRequestCaterer.quote_request_id == qr_id
            )
        ).all()
        caterer_ids.update(qrc_caterer_ids)

    # Caller must themselves be a party — otherwise a stranger could enumerate
    # company/caterer membership by probing recipient IDs.
    user_in_company = bool(company_id and user.company_id == company_id)
    user_in_caterers = bool(user.caterer_id and user.caterer_id in caterer_ids)
    if not (user_in_company or user_in_caterers):
        return set()

    allowed: set[uuid.UUID] = set()
    if company_id:
        allowed.update(
            db.scalars(select(User.id).where(User.company_id == company_id)).all()
        )
    if caterer_ids:
        allowed.update(
            db.scalars(select(User.id).where(User.caterer_id.in_(caterer_ids))).all()
        )
    allowed.discard(user.id)
    return allowed


@api_bp.route("/messages", methods=["POST"])
@login_required
@limiter.limit("60 per minute")
def send_message():
    user = g.current_user
    data = request.get_json() or {}
    try:
        recipient_id = uuid.UUID(str(data.get("recipient_id", "")))
    except (ValueError, TypeError):
        abort(400)
    body = (data.get("body") or "").strip()
    if not body:
        return jsonify({"error": "Le message ne peut pas etre vide."}), 400

    order_id = None
    if data.get("order_id"):
        try:
            order_id = uuid.UUID(str(data["order_id"]))
        except (ValueError, TypeError):
            order_id = None
    quote_request_id = None
    if data.get("quote_request_id"):
        try:
            quote_request_id = uuid.UUID(str(data["quote_request_id"]))
        except (ValueError, TypeError):
            quote_request_id = None

    # VULN-04: gate the message on a real business relationship. super_admin
    # bypasses the check (operational support over moderation tooling).
    db = get_db()
    is_admin = user.role == "super_admin"
    if not is_admin:
        if not order_id and not quote_request_id:
            return jsonify(
                {
                    "error": "Le message doit etre lie a une commande ou une demande de devis."
                }
            ), 400
        allowed = _allowed_recipients_for(
            db, user, order_id=order_id, quote_request_id=quote_request_id
        )
        if recipient_id not in allowed:
            return jsonify({"error": "Destinataire non autorise."}), 403

    # Thread per user-pair: look up existing thread or create a random one.
    existing = db.scalar(
        select(Message.thread_id)
        .where(
            or_(
                and_(
                    Message.sender_id == user.id, Message.recipient_id == recipient_id
                ),
                and_(
                    Message.sender_id == recipient_id, Message.recipient_id == user.id
                ),
            )
        )
        .limit(1)
    )
    thread_id = existing if existing else uuid.uuid4()

    msg = Message(
        thread_id=thread_id,
        sender_id=user.id,
        recipient_id=recipient_id,
        order_id=order_id,
        quote_request_id=quote_request_id,
        body=body,
    )
    db.add(msg)
    db.flush()

    create_notification(
        db,
        user_id=recipient_id,
        type="new_message",
        title="Nouveau message",
        body=f"{user.first_name} {user.last_name} vous a envoye un message.",
        related_entity_type="message",
        related_entity_id=msg.id,
    )
    db.commit()

    return jsonify({"status": "ok", "thread_id": str(thread_id)}), 201


@api_bp.route("/notifications")
@login_required
def get_notifications():
    user = g.current_user
    db = get_db()
    count = get_unread_count(db, user.id)
    notifications = db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .order_by(Notification.created_at.desc())
        .limit(20)
    ).all()
    result = [
        {
            "id": str(n.id),
            "type": n.type,
            "title": n.title,
            "body": n.body,
            "created_at": n.created_at.isoformat(),
        }
        for n in notifications
    ]
    return jsonify({"unread_count": count, "notifications": result})


@api_bp.route("/notifications/<uuid:notification_id>/read", methods=["POST"])
@login_required
def notification_read(notification_id):
    user = g.current_user
    db = get_db()
    notification = db.get(Notification, notification_id)
    if not notification or notification.user_id != user.id:
        return jsonify({"error": "Non trouve."}), 404
    mark_as_read(db, notification_id)
    db.commit()
    return jsonify({"status": "ok"})
