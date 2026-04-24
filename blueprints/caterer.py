import json
import logging
from datetime import date, datetime

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select

from blueprints.middleware import login_required, role_required
from database import get_db
from forms.caterer import CatererProfileForm, QuoteForm
from models import (
    Message,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    QRCStatus,
    Quote,
    QuoteRequest,
    QuoteRequestCaterer,
    QuoteStatus,
    User,
)
from services.quotes import (
    calculate_quote_totals, generate_quote_reference, lines_from_dicts, totals_for_json,
)
from services.uploads import save_upload
from services.stripe_service import (
    create_account_link,
    create_connect_account,
    create_invoice_for_order,
    get_account,
)

logger = logging.getLogger(__name__)

caterer_bp = Blueprint("caterer", __name__, url_prefix="/caterer")


@caterer_bp.route("/dashboard")
@login_required
@role_required("caterer")
def dashboard():
    caterer = g.current_user.caterer
    db = get_db()
    pending_count = db.scalar(
        select(func.count(QuoteRequestCaterer.id))
        .where(QuoteRequestCaterer.caterer_id == caterer.id)
        .where(QuoteRequestCaterer.status == QRCStatus.selected)
    )
    upcoming_deliveries = db.scalars(
        select(Order)
        .join(Quote, Order.quote_id == Quote.id)
        .where(Quote.caterer_id == caterer.id)
        .where(Order.status == OrderStatus.confirmed)
        .where(Order.delivery_date >= date.today())
        .order_by(Order.delivery_date)
        .limit(5)
    ).all()
    total_revenue = db.scalar(
        select(func.sum(Payment.amount_to_caterer_cents))
        .join(Order, Payment.order_id == Order.id)
        .join(Quote, Order.quote_id == Quote.id)
        .where(Quote.caterer_id == caterer.id)
        .where(Payment.status == PaymentStatus.succeeded)
    ) or 0
    return render_template(
        "caterer/dashboard.html",
        user=g.current_user,
        pending_count=pending_count,
        upcoming_deliveries=upcoming_deliveries,
        total_revenue=total_revenue / 100,
    )


@caterer_bp.route("/profile", methods=["GET"])
@login_required
@role_required("caterer")
def profile():
    return render_template("caterer/profile.html", user=g.current_user, caterer=g.current_user.caterer)


@caterer_bp.route("/profile", methods=["POST"])
@login_required
@role_required("caterer")
def profile_save():
    caterer = g.current_user.caterer
    form = CatererProfileForm()
    if not form.validate_on_submit():
        flash("Veuillez corriger les erreurs du formulaire.", "error")
        return render_template("caterer/profile.html", user=g.current_user, caterer=caterer), 400
    db = get_db()
    db.add(caterer)
    if form.name.data is not None:
        caterer.name = form.name.data or caterer.name
    if form.description.data is not None:
        caterer.description = form.description.data or caterer.description
    if form.address.data is not None:
        caterer.address = form.address.data or caterer.address
    if form.city.data is not None:
        caterer.city = form.city.data or caterer.city
    if form.zip_code.data is not None:
        caterer.zip_code = form.zip_code.data or caterer.zip_code
    if form.capacity_min.data is not None:
        caterer.capacity_min = form.capacity_min.data
    if form.capacity_max.data is not None:
        caterer.capacity_max = form.capacity_max.data
    if form.delivery_radius_km.data is not None:
        caterer.delivery_radius_km = form.delivery_radius_km.data
    caterer.dietary_vegetarian = form.dietary_vegetarian.data
    caterer.dietary_vegan = form.dietary_vegan.data
    caterer.dietary_halal = form.dietary_halal.data
    caterer.dietary_casher = form.dietary_casher.data
    caterer.dietary_gluten_free = form.dietary_gluten_free.data
    caterer.dietary_lactose_free = form.dietary_lactose_free.data
    photos = list(caterer.photos or [])
    for file in request.files.getlist("photos"):
        url = save_upload(file, subfolder="caterers")
        if url:
            photos.append(url)
    caterer.photos = photos

    specialties_raw = form.specialties.data or ""
    caterer.specialties = [s.strip() for s in specialties_raw.split(",") if s.strip()] if specialties_raw else caterer.specialties
    service_config_raw = form.service_config.data or ""
    if service_config_raw:
        try:
            caterer.service_config = json.loads(service_config_raw)
        except json.JSONDecodeError:
            pass
    db.commit()
    flash("Profil mis a jour.", "success")
    return redirect(url_for("caterer.profile"))


@caterer_bp.route("/requests")
@login_required
@role_required("caterer")
def requests_list():
    caterer = g.current_user.caterer
    status_filter = request.args.get("status")
    db = get_db()
    stmt = (
        select(QuoteRequestCaterer)
        .where(QuoteRequestCaterer.caterer_id == caterer.id)
    )
    if status_filter:
        stmt = stmt.where(QuoteRequestCaterer.status == status_filter)
    qrcs = db.scalars(stmt.order_by(QuoteRequestCaterer.id.desc())).all()
    for qrc in qrcs:
        _ = qrc.quote_request
        _ = qrc.quote_request.company
    return render_template(
        "caterer/requests/list.html",
        user=g.current_user,
        qrcs=qrcs,
        status_filter=status_filter,
    )


@caterer_bp.route("/requests/<uuid:qr_id>")
@login_required
@role_required("caterer")
def request_detail(qr_id):
    caterer = g.current_user.caterer
    db = get_db()
    qrc = db.scalar(
        select(QuoteRequestCaterer)
        .where(QuoteRequestCaterer.quote_request_id == qr_id)
        .where(QuoteRequestCaterer.caterer_id == caterer.id)
    )
    if not qrc:
        abort(404)
    qr = qrc.quote_request
    _ = qr.company
    existing_quote = db.scalar(
        select(Quote)
        .where(Quote.quote_request_id == qr_id)
        .where(Quote.caterer_id == caterer.id)
    )
    return render_template(
        "caterer/requests/detail.html",
        user=g.current_user,
        qr=qr,
        qrc=qrc,
        existing_quote=existing_quote,
    )


@caterer_bp.route("/requests/<uuid:qr_id>/quote/new", methods=["GET"])
@login_required
@role_required("caterer")
def quote_new(qr_id):
    caterer = g.current_user.caterer
    db = get_db()
    qrc = db.scalar(
        select(QuoteRequestCaterer)
        .where(QuoteRequestCaterer.quote_request_id == qr_id)
        .where(QuoteRequestCaterer.caterer_id == caterer.id)
    )
    if not qrc:
        abort(404)
    qr = qrc.quote_request
    _ = qr.company
    return render_template(
        "caterer/quotes/editor.html",
        user=g.current_user,
        qr=qr,
        qrc=qrc,
        quote=None,
        initial_lines=[],
    )


@caterer_bp.route("/requests/<uuid:qr_id>/quote", methods=["POST"])
@login_required
@role_required("caterer")
def quote_create(qr_id):
    caterer = g.current_user.caterer
    db = get_db()
    qrc = db.scalar(
        select(QuoteRequestCaterer)
        .where(QuoteRequestCaterer.quote_request_id == qr_id)
        .where(QuoteRequestCaterer.caterer_id == caterer.id)
    )
    if not qrc:
        abort(404)
    qr = qrc.quote_request
    form = QuoteForm()
    if not form.validate_on_submit():
        flash("Veuillez corriger les erreurs du formulaire.", "error")
        return render_template(
            "caterer/quotes/editor.html",
            user=g.current_user,
            qr=qr,
            qrc=qrc,
            quote=None,
            initial_lines=[],
        ), 400
    try:
        line_dicts = json.loads(form.details.data or "[]")
    except json.JSONDecodeError:
        line_dicts = []
    try:
        lines = lines_from_dicts(line_dicts)
    except ValueError as exc:
        flash(f"Devis invalide : {exc}", "error")
        return render_template(
            "caterer/quotes/editor.html",
            user=g.current_user,
            qr=qr,
            qrc=qrc,
            quote=None,
            initial_lines=line_dicts,
        ), 400
    totals = calculate_quote_totals(line_dicts, qr.guest_count)
    reference = generate_quote_reference(db, caterer)
    quote = Quote(
        quote_request_id=qr_id,
        caterer_id=caterer.id,
        reference=reference,
        details={"totals": totals_for_json(totals)},
        total_amount_ht=totals["total_ht"],
        amount_per_person=totals["amount_per_person"],
        valorisable_agefiph=totals["valorisable_agefiph"],
        notes=form.notes.data or "",
        valid_until=form.valid_until.data,
        status=QuoteStatus.draft,
        lines=lines,
    )
    db.add(quote)
    db.commit()
    flash("Devis enregistre en brouillon.", "success")
    return redirect(url_for("caterer.request_detail", qr_id=qr_id))


@caterer_bp.route("/requests/<uuid:qr_id>/quote/<uuid:q_id>/edit", methods=["GET"])
@login_required
@role_required("caterer")
def quote_edit(qr_id, q_id):
    caterer = g.current_user.caterer
    db = get_db()
    quote = db.scalar(
        select(Quote)
        .where(Quote.id == q_id)
        .where(Quote.caterer_id == caterer.id)
        .where(Quote.quote_request_id == qr_id)
    )
    if not quote:
        abort(404)
    qr = quote.quote_request
    _ = qr.company
    qrc = db.scalar(
        select(QuoteRequestCaterer)
        .where(QuoteRequestCaterer.quote_request_id == qr_id)
        .where(QuoteRequestCaterer.caterer_id == caterer.id)
    )
    return render_template(
        "caterer/quotes/editor.html",
        user=g.current_user,
        qr=qr,
        qrc=qrc,
        quote=quote,
        initial_lines=[ln.as_dict() for ln in quote.lines],
    )


@caterer_bp.route("/requests/<uuid:qr_id>/quote/<uuid:q_id>/edit", methods=["POST"])
@login_required
@role_required("caterer")
def quote_update(qr_id, q_id):
    caterer = g.current_user.caterer
    db = get_db()
    quote = db.scalar(
        select(Quote)
        .where(Quote.id == q_id)
        .where(Quote.caterer_id == caterer.id)
        .where(Quote.quote_request_id == qr_id)
    )
    if not quote:
        abort(404)
    qr = quote.quote_request
    qrc = db.scalar(
        select(QuoteRequestCaterer)
        .where(QuoteRequestCaterer.quote_request_id == qr_id)
        .where(QuoteRequestCaterer.caterer_id == caterer.id)
    )
    form = QuoteForm()
    if not form.validate_on_submit():
        flash("Veuillez corriger les erreurs du formulaire.", "error")
        return render_template(
            "caterer/quotes/editor.html",
            user=g.current_user,
            qr=qr,
            qrc=qrc,
            quote=quote,
            initial_lines=[ln.as_dict() for ln in quote.lines],
        ), 400
    try:
        line_dicts = json.loads(form.details.data or "[]")
    except json.JSONDecodeError:
        line_dicts = []
    try:
        new_lines = lines_from_dicts(line_dicts)
    except ValueError as exc:
        flash(f"Devis invalide : {exc}", "error")
        return render_template(
            "caterer/quotes/editor.html",
            user=g.current_user,
            qr=qr,
            qrc=qrc,
            quote=quote,
            initial_lines=line_dicts,
        ), 400
    totals = calculate_quote_totals(line_dicts, qr.guest_count)
    quote.lines = new_lines
    quote.details = {"totals": totals_for_json(totals)}
    quote.total_amount_ht = totals["total_ht"]
    quote.amount_per_person = totals["amount_per_person"]
    quote.valorisable_agefiph = totals["valorisable_agefiph"]
    quote.notes = form.notes.data or ""
    quote.valid_until = form.valid_until.data if form.valid_until.data else quote.valid_until
    db.commit()
    flash("Devis mis a jour.", "success")
    return redirect(url_for("caterer.request_detail", qr_id=qr_id))


@caterer_bp.route("/requests/<uuid:qr_id>/quote/<uuid:q_id>/send", methods=["POST"])
@login_required
@role_required("caterer")
def quote_send(qr_id, q_id):
    caterer = g.current_user.caterer
    db = get_db()
    quote = db.scalar(
        select(Quote)
        .where(Quote.id == q_id)
        .where(Quote.caterer_id == caterer.id)
        .where(Quote.quote_request_id == qr_id)
        .where(Quote.status == QuoteStatus.draft)
    )
    if not quote:
        abort(404)
    qrc = db.scalar(
        select(QuoteRequestCaterer)
        .where(QuoteRequestCaterer.quote_request_id == qr_id)
        .where(QuoteRequestCaterer.caterer_id == caterer.id)
    )
    if not qrc:
        abort(404)

    quote.status = QuoteStatus.sent
    qrc.status = QRCStatus.responded
    qrc.responded_at = datetime.utcnow()

    transmitted_count = db.scalar(
        select(func.count(QuoteRequestCaterer.id))
        .where(QuoteRequestCaterer.quote_request_id == qr_id)
        .where(QuoteRequestCaterer.status == QRCStatus.transmitted_to_client)
    )

    if transmitted_count < 3:
        qrc.status = QRCStatus.transmitted_to_client
        qrc.response_rank = transmitted_count + 1

        if transmitted_count + 1 == 3:
            remaining = db.scalars(
                select(QuoteRequestCaterer)
                .where(QuoteRequestCaterer.quote_request_id == qr_id)
                .where(QuoteRequestCaterer.status == QRCStatus.selected)
                .where(QuoteRequestCaterer.caterer_id != caterer.id)
            ).all()
            for r in remaining:
                r.status = QRCStatus.closed

    db.commit()

    flash("Devis envoye au client.", "success")
    return redirect(url_for("caterer.request_detail", qr_id=qr_id))


@caterer_bp.route("/orders")
@login_required
@role_required("caterer")
def orders_list():
    caterer = g.current_user.caterer
    db = get_db()
    orders = db.scalars(
        select(Order)
        .join(Quote, Order.quote_id == Quote.id)
        .where(Quote.caterer_id == caterer.id)
        .order_by(Order.created_at.desc())
    ).all()
    for o in orders:
        _ = o.quote
        _ = o.quote.quote_request
    return render_template("caterer/orders/list.html", user=g.current_user, orders=orders)


@caterer_bp.route("/orders/<uuid:order_id>")
@login_required
@role_required("caterer")
def order_detail(order_id):
    caterer = g.current_user.caterer
    db = get_db()
    order = db.scalar(
        select(Order)
        .join(Quote, Order.quote_id == Quote.id)
        .where(Order.id == order_id)
        .where(Quote.caterer_id == caterer.id)
    )
    if not order:
        abort(404)
    _ = order.quote
    _ = order.quote.quote_request
    _ = order.quote.quote_request.company
    _ = order.payments
    return render_template("caterer/orders/detail.html", user=g.current_user, order=order)


@caterer_bp.route("/orders/<uuid:order_id>/deliver", methods=["POST"])
@login_required
@role_required("caterer")
def order_deliver(order_id):
    caterer = g.current_user.caterer
    db = get_db()
    order = db.scalar(
        select(Order)
        .join(Quote, Order.quote_id == Quote.id)
        .where(Order.id == order_id)
        .where(Quote.caterer_id == caterer.id)
        .where(Order.status == OrderStatus.confirmed)
    )
    if not order:
        abort(404)
    order.status = OrderStatus.delivered
    if caterer.stripe_account_id and caterer.stripe_charges_enabled:
        try:
            create_invoice_for_order(db, order)
            flash("Commande livree et facture Stripe generee.", "success")
        except Exception:
            logger.exception("Stripe invoice creation failed for order %s", order_id)
            flash("Commande marquee comme livree. Erreur lors de la generation de la facture Stripe.", "warning")
    else:
        flash("Commande marquee comme livree.", "success")
    db.commit()
    return redirect(url_for("caterer.order_detail", order_id=order_id))


@caterer_bp.route("/stripe")
@login_required
@role_required("caterer")
def stripe_status():
    caterer = g.current_user.caterer
    if caterer.stripe_account_id:
        try:
            status = get_account(caterer.stripe_account_id)
            db = get_db()
            db.add(caterer)
            caterer.stripe_charges_enabled = status["charges_enabled"]
            caterer.stripe_payouts_enabled = status["payouts_enabled"]
            db.commit()
        except Exception:
            logger.exception("Failed to fetch Stripe account status")
    return render_template("caterer/stripe.html", user=g.current_user, caterer=caterer)


@caterer_bp.route("/stripe/onboard", methods=["POST"])
@login_required
@role_required("caterer")
def stripe_onboard():
    caterer = g.current_user.caterer
    db = get_db()
    db.add(caterer)
    if not caterer.stripe_account_id:
        result = create_connect_account(caterer)
        caterer.stripe_account_id = result["id"]
    refresh_url = url_for("caterer.stripe_status", _external=True)
    return_url = url_for("caterer.stripe_complete", _external=True)
    link_url = create_account_link(caterer.stripe_account_id, refresh_url, return_url)
    db.commit()
    return redirect(link_url)


@caterer_bp.route("/stripe/complete")
@login_required
@role_required("caterer")
def stripe_complete():
    caterer = g.current_user.caterer
    if caterer.stripe_account_id:
        try:
            status = get_account(caterer.stripe_account_id)
            db = get_db()
            db.add(caterer)
            caterer.stripe_charges_enabled = status["charges_enabled"]
            caterer.stripe_payouts_enabled = status["payouts_enabled"]
            if status["charges_enabled"] and status["payouts_enabled"]:
                caterer.stripe_onboarded_at = datetime.utcnow()
                flash("Compte Stripe connecte avec succes.", "success")
            else:
                flash("Verification en cours. Certaines fonctionnalites ne sont pas encore actives.", "warning")
            db.commit()
        except Exception:
            logger.exception("Failed to verify Stripe account on completion")
            flash("Erreur lors de la verification du compte Stripe.", "error")
    return redirect(url_for("caterer.stripe_status"))


@caterer_bp.route("/messages")
@login_required
@role_required("caterer")
def messages():
    user = g.current_user
    db = get_db()
    threads = _get_caterer_threads(db, user.id)
    return render_template("caterer/messages/list.html", user=user, threads=threads)


@caterer_bp.route("/messages/<uuid:thread_id>")
@login_required
@role_required("caterer")
def message_thread(thread_id):
    user = g.current_user
    db = get_db()
    first_msg = db.scalar(
        select(Message).where(
            Message.thread_id == thread_id,
            or_(Message.sender_id == user.id, Message.recipient_id == user.id),
        )
    )
    if not first_msg:
        abort(404)
    other_id = first_msg.recipient_id if first_msg.sender_id == user.id else first_msg.sender_id
    other_user = db.get(User, other_id)
    return render_template(
        "caterer/messages/thread.html",
        user=user,
        thread_id=thread_id,
        other_user=other_user,
    )


def _get_caterer_threads(db, user_id):
    all_messages = db.scalars(
        select(Message)
        .where(or_(Message.sender_id == user_id, Message.recipient_id == user_id))
        .order_by(Message.created_at.desc())
    ).all()
    threads = {}
    for msg in all_messages:
        tid = str(msg.thread_id)
        if tid not in threads:
            other_id = msg.recipient_id if msg.sender_id == user_id else msg.sender_id
            other_user = db.get(User, other_id)
            unread = db.scalar(
                select(func.count(Message.id)).where(
                    Message.thread_id == msg.thread_id,
                    Message.recipient_id == user_id,
                    Message.is_read.is_(False),
                )
            )
            threads[tid] = {
                "thread_id": tid,
                "other_name": f"{other_user.first_name} {other_user.last_name}" if other_user else "Inconnu",
                "last_message": msg.body[:80],
                "last_at": msg.created_at,
                "unread": unread,
            }
    return list(threads.values())
