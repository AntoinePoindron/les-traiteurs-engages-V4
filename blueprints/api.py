import logging
import uuid

from flask import Blueprint, abort, g, jsonify, request
from sqlalchemy import or_, select

import config
from extensions import csrf, limiter
from blueprints.middleware import login_required
from database import get_db
from models import Caterer, Message, Notification, Order, OrderStatus, Payment, PaymentStatus, User
from services.notifications import create_notification, get_unread_count, mark_as_read
from services.stripe_service import verify_webhook_signature

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api")


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
        event = verify_webhook_signature(payload, sig_header, config.STRIPE_WEBHOOK_SECRET)
    except ValueError:
        logger.warning("Invalid Stripe webhook signature")
        return jsonify({"error": "invalid signature"}), 400

    # `event` is a stripe.Event (not a plain dict and not a subclass of dict
    # in current SDKs) — use subscript access + getattr-style helpers instead
    # of `.get(...)`. Audit finding #2 (2026-04-24).
    event_type = event["type"]
    data_object = event["data"]["object"]

    def _field(obj, key, default=None):
        """Read a field from a StripeObject OR plain dict."""
        try:
            return obj[key]
        except (KeyError, TypeError):
            return default

    if event_type == "invoice.paid":
        stripe_invoice_id = _field(data_object, "id")
        db = get_db()
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
        db = get_db()
        payment = db.scalar(
            select(Payment).where(Payment.stripe_invoice_id == stripe_invoice_id)
        )
        if payment:
            payment.status = PaymentStatus.failed
        db.commit()

    elif event_type == "account.updated":
        account_id = _field(data_object, "id")
        db = get_db()
        caterer = db.scalar(
            select(Caterer).where(Caterer.stripe_account_id == account_id)
        )
        if caterer:
            caterer.stripe_charges_enabled = _field(data_object, "charges_enabled", False)
            caterer.stripe_payouts_enabled = _field(data_object, "payouts_enabled", False)
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
        .order_by(Message.created_at.asc())
    )
    if not is_admin:
        stmt = stmt.where(
            or_(Message.sender_id == user.id, Message.recipient_id == user.id)
        )
    messages = db.scalars(stmt).all()

    db.execute(
        Message.__table__.update()
        .where(Message.thread_id == thread_id, Message.recipient_id == user.id, Message.is_read.is_(False))
        .values(is_read=True)
    )
    db.commit()

    result = []
    for msg in messages:
        sender = db.get(User, msg.sender_id)
        result.append({
            "id": str(msg.id),
            "thread_id": str(msg.thread_id),
            "sender_id": str(msg.sender_id),
            "recipient_id": str(msg.recipient_id),
            "sender_name": f"{sender.first_name} {sender.last_name}" if sender else "Inconnu",
            "body": msg.body,
            "is_read": msg.is_read,
            "created_at": msg.created_at.isoformat(),
        })
    return jsonify({"messages": result})


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

    # DESIGN: thread_id is deterministic per pair of users.
    # Any two users share exactly one thread, for life — messages about order
    # #42 and order #87 pile up together. `Message.order_id` and
    # `Message.quote_request_id` still scope individual messages, but the
    # thread itself is one continuous conversation between the pair.
    #
    # Consequences: no archival, no per-context threads, no group chats.
    # If the product ever needs any of those, generate a fresh random
    # thread_id per conversation and attach it to the spawning context
    # (order, quote_request) instead of hashing the user pair here.
    pair = sorted([str(user.id), str(recipient_id)])
    thread_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{pair[0]}:{pair[1]}")

    db = get_db()
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
    result = [{
        "id": str(n.id),
        "type": n.type,
        "title": n.title,
        "body": n.body,
        "created_at": n.created_at.isoformat(),
    } for n in notifications]
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
