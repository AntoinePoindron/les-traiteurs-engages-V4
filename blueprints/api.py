import logging
import uuid

from flask import Blueprint, abort, g, jsonify, request
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

import config
from extensions import csrf, limiter
from blueprints.middleware import login_required, validated_caterer_required
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
from services.notifications import (
    caterer_user_ids,
    company_admin_user_ids,
    create_notification,
    get_unread_count,
    mark_as_read,
    notify_users,
)
from services.stripe_service import verify_webhook_signature

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api")

# Terminal payment states that a subsequent webhook must NEVER downgrade.
# Stripe delivers events out of order and retries on failure, so a stale
# `invoice.payment_failed` can arrive after `invoice.paid`.
_TERMINAL_PAID_STATES = {PaymentStatus.succeeded, PaymentStatus.refunded}

# Hard cap on message body length. Matches the HTML maxlength on the
# send-message modal so the API doesn't accept payloads the UI can't
# produce; the DB column is TEXT so this is enforced here, not at the
# schema level.
MESSAGE_BODY_MAX = 5000


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

    # Atomic dedup + business mutations: the StripeEvent INSERT and every
    # mutation it gates MUST share one transaction. Audit C-1 (2026-05-13):
    # the previous shape committed the dedup row first, so if the business
    # commit failed the dedup row survived — Stripe's retry hit the UNIQUE
    # violation, returned 200, and the payment was permanently lost.
    #
    # `flush()` raises IntegrityError on duplicate without persisting the
    # row outside the surrounding transaction; on the happy path the
    # single `commit()` at the end makes both INSERT and mutations durable
    # atomically. On exception we `rollback()` and return 500 so Stripe
    # retries — the dedup row is undone with everything else.
    db = get_db()
    db.add(StripeEvent(id=event_id, event_type=event_type))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        logger.info("Ignoring duplicate Stripe event %s (%s)", event_id, event_type)
        return jsonify({"status": "duplicate"}), 200

    # Audit C-2 (2026-05-13): wrap the body so an exception in
    # `notify_review_invite`, a flush failure, or any future side-effect
    # cannot leak an HTML 500 page into the Stripe dashboard. Stripe sees
    # a structured 500 with the event_id and retries; ops sees a logged
    # exception they can grep on.
    try:
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
                    # Notify both sides that the cycle is closed. The
                    # caterer's payout is processed downstream by Stripe
                    # Connect; we just confirm receipt here.
                    qr = order.quote.quote_request
                    notify_users(
                        db,
                        company_admin_user_ids(db, qr.company_id),
                        type="order_paid",
                        title="Paiement enregistré",
                        body="Le paiement de votre commande a été enregistré. Merci !",
                        related_entity_type="order",
                        related_entity_id=order.id,
                    )
                    notify_users(
                        db,
                        caterer_user_ids(db, order.quote.caterer_id),
                        type="order_paid",
                        title="Paiement reçu",
                        body="Le paiement de la commande a été reçu et sera viré sous peu.",
                        related_entity_type="order",
                        related_entity_id=order.id,
                    )
                    # Invite the original requester to review the caterer.
                    # The helper is idempotent (skips on retry/redelivery).
                    from services.reviews import notify_review_invite

                    notify_review_invite(db, order=order)

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
    except Exception:
        db.rollback()
        logger.exception(
            "Stripe webhook handler failed",
            extra={"event_id": event_id, "event_type": event_type},
        )
        # JSON 500 (not HTML): Stripe shows the body in its dashboard, and
        # the event_id lets ops correlate with the rolled-back transaction.
        return jsonify({"error": "internal", "event_id": event_id}), 500

    return jsonify({"status": "ok"}), 200


@api_bp.route("/messages/<uuid:thread_id>")
@login_required
@validated_caterer_required
def get_messages(thread_id):
    user = g.current_user
    db = get_db()
    # Every role — super_admin included — only reads threads it takes
    # part in. The admin is a real participant of its own conversations,
    # not a platform-wide observer.
    messages = db.scalars(
        select(Message)
        .where(Message.thread_id == thread_id)
        .where(or_(Message.sender_id == user.id, Message.recipient_id == user.id))
        .options(joinedload(Message.sender))
        .order_by(Message.created_at.asc())
    ).all()

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

    # Split the allowed set by side. A client-side user can reach every
    # solicited caterer on the QR; a caterer-side user can only reach the
    # client (NOT the other caterers also solicited on the same QR — they
    # are competitors). The previous shape merged both sides into one set
    # so caterer A could DM caterer B about a shared QR.
    allowed: set[uuid.UUID] = set()
    if user_in_company:
        if caterer_ids:
            allowed.update(
                db.scalars(
                    select(User.id).where(User.caterer_id.in_(caterer_ids))
                ).all()
            )
        if company_id:
            allowed.update(
                db.scalars(select(User.id).where(User.company_id == company_id)).all()
            )
    elif user_in_caterers:
        if company_id:
            allowed.update(
                db.scalars(select(User.id).where(User.company_id == company_id)).all()
            )
        # Same-caterer teammates stay reachable; competitors do not.
        allowed.update(
            db.scalars(select(User.id).where(User.caterer_id == user.caterer_id)).all()
        )
    allowed.discard(user.id)
    return allowed


@api_bp.route("/messages", methods=["POST"])
@login_required
@validated_caterer_required
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
    # Mirrors the textarea maxlength in the send_message_modal macro.
    # Without a server-side cap, a curl client could shove arbitrary
    # payloads at us — the constant lives at module scope so the cap
    # stays in one place if either side changes.
    if len(body) > MESSAGE_BODY_MAX:
        return jsonify(
            {"error": f"Le message ne peut pas depasser {MESSAGE_BODY_MAX} caracteres."}
        ), 400

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

    # Thread per user-pair: look up existing thread or create a random one.
    db = get_db()
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

    # The recipient must be a real, active account no matter who sends —
    # otherwise the message lands on a ghost row no one can read.
    is_admin = user.role == "super_admin"
    recipient = db.get(User, recipient_id)
    if recipient is None or not recipient.is_active:
        return jsonify({"error": "Destinataire introuvable ou inactif."}), 404

    # VULN-04: gate every message on a currently-active business
    # relationship — not just the first message of a thread. Persisting
    # access on a stale thread would let a user keep messaging a contact
    # after they leave the company, after a QR is rejected, or after an
    # order is deleted.
    #
    # Two parties skip the business-relationship gate outright:
    #   - a super_admin sender — a platform operator can reach anyone;
    #   - any sender writing TO a designated support inbox — the platform
    #     admin is a universal contact, so a client/caterer must be able
    #     to reply or open a ticket. When `SUPPORT_USER_EMAILS` is set,
    #     only the listed super_admin addresses qualify as "support";
    #     other super_admin accounts still require the business gate so a
    #     random staffer can't be enumerated as a free-form contact.
    #
    # Contexts to gate against otherwise:
    #   - if the caller passed order_id / quote_request_id explicitly,
    #     use them (single context).
    #   - otherwise, inherit from the thread's history: every distinct
    #     (order_id, quote_request_id) pair seen on a prior message.
    #     Allow if any of them still resolves to a live relationship.
    #     This preserves the standalone-Messagerie UX (no need to thread
    #     QR/order context through every reply) while re-validating the
    #     gate on every send.
    recipient_is_support = recipient.role == "super_admin" and (
        not config.SUPPORT_USER_EMAILS
        or recipient.email.lower() in config.SUPPORT_USER_EMAILS
    )
    if not is_admin and not recipient_is_support:
        if recipient.role == "super_admin":
            # A non-support super_admin is never a free-form contact for a
            # regular user: it belongs to no company and no caterer, so no
            # order/QR context could ever place it in `_allowed_recipients_for`.
            # Reject directly rather than hinting at a missing context.
            return jsonify({"error": "Destinataire non autorise."}), 403
        gate_contexts: list[tuple] = []
        if order_id or quote_request_id:
            gate_contexts.append((order_id, quote_request_id))
        elif existing is not None:
            gate_contexts = [
                (oid, qrid)
                for oid, qrid in db.execute(
                    select(Message.order_id, Message.quote_request_id)
                    .where(Message.thread_id == existing)
                    .where(
                        or_(
                            Message.order_id.is_not(None),
                            Message.quote_request_id.is_not(None),
                        )
                    )
                    .distinct()
                ).all()
            ]

        if not gate_contexts:
            return jsonify(
                {
                    "error": "Le message doit etre lie a une commande ou une demande de devis."
                }
            ), 400

        if not any(
            recipient_id
            in _allowed_recipients_for(db, user, order_id=oid, quote_request_id=qrid)
            for oid, qrid in gate_contexts
        ):
            return jsonify({"error": "Destinataire non autorise."}), 403

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

    # Trace every admin-initiated outgoing message — the platform admin
    # writing to a regular user is a sensitive action (support touch,
    # qualification message, escalation) and must leave an audit row.
    # Admin↔admin chatter is excluded as internal noise.
    if is_admin and recipient.role != "super_admin":
        log_admin_action(
            db,
            user,
            "message.admin_send",
            target_type="user",
            target_id=recipient_id,
            extra={
                "thread_id": str(thread_id),
                "body_length": len(body),
                "order_id": str(order_id) if order_id else None,
                "quote_request_id": str(quote_request_id) if quote_request_id else None,
            },
        )

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
@validated_caterer_required
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
@validated_caterer_required
def notification_read(notification_id):
    user = g.current_user
    db = get_db()
    notification = db.get(Notification, notification_id)
    if not notification or notification.user_id != user.id:
        return jsonify({"error": "Non trouve."}), 404
    mark_as_read(db, notification_id)
    db.commit()
    return jsonify({"status": "ok"})
