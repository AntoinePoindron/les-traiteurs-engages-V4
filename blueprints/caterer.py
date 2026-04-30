import json
import logging
from datetime import date, datetime

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select

from blueprints.middleware import login_required, role_required
from database import get_db
from forms.caterer import CatererProfileForm, QuoteForm
from models import (
    MEAL_TYPE_LABELS,
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
from pydantic import ValidationError

from services import workflow
from services.json_schemas import ServiceConfig
from services.quotes import (
    calculate_quote_totals, generate_quote_reference, lines_from_dicts,
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

    # KPI 1 : nouvelles demandes (QRC selected, pas encore traitees par le caterer)
    new_requests_count = db.scalar(
        select(func.count(QuoteRequestCaterer.id))
        .where(QuoteRequestCaterer.caterer_id == caterer.id)
        .where(QuoteRequestCaterer.status == QRCStatus.selected)
    ) or 0

    # KPI 2 : devis envoyes en attente de reponse client
    pending_quotes_count = db.scalar(
        select(func.count(Quote.id))
        .where(Quote.caterer_id == caterer.id)
        .where(Quote.status == QuoteStatus.sent)
    ) or 0

    # KPI 3 : commandes en cours (post-acceptation, avant paiement complete)
    orders_in_progress_count = db.scalar(
        select(func.count(Order.id))
        .join(Quote, Order.quote_id == Quote.id)
        .where(Quote.caterer_id == caterer.id)
        .where(Order.status.in_([
            OrderStatus.confirmed,
            OrderStatus.delivered,
            OrderStatus.invoicing,
            OrderStatus.invoiced,
        ]))
    ) or 0

    # KPI 4 : CA realise (paiements Stripe succeeded)
    total_revenue = db.scalar(
        select(func.sum(Payment.amount_to_caterer_cents))
        .join(Order, Payment.order_id == Order.id)
        .join(Quote, Order.quote_id == Quote.id)
        .where(Quote.caterer_id == caterer.id)
        .where(Payment.status == PaymentStatus.succeeded)
    ) or 0

    # Liste 1 : demandes a traiter (les nouvelles QRC)
    new_requests = db.scalars(
        select(QuoteRequestCaterer)
        .where(QuoteRequestCaterer.caterer_id == caterer.id)
        .where(QuoteRequestCaterer.status == QRCStatus.selected)
        .order_by(QuoteRequestCaterer.id.desc())
        .limit(10)
    ).all()

    # Liste 2 : commandes a venir (livraisons confirmees pas encore passees)
    upcoming_deliveries = db.scalars(
        select(Order)
        .join(Quote, Order.quote_id == Quote.id)
        .where(Quote.caterer_id == caterer.id)
        .where(Order.status == OrderStatus.confirmed)
        .where(Order.delivery_date >= date.today())
        .order_by(Order.delivery_date)
        .limit(5)
    ).all()

    return render_template(
        "caterer/dashboard.html",
        user=g.current_user,
        new_requests_count=new_requests_count,
        pending_quotes_count=pending_quotes_count,
        orders_in_progress_count=orders_in_progress_count,
        total_revenue=total_revenue / 100,
        new_requests=new_requests,
        upcoming_deliveries=upcoming_deliveries,
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
    # Photos lifecycle:
    #   1. The form submits one hidden `photos_order` input per item shown
    #      in the UI grid, in DOM order. Each value is either:
    #        - an existing photo URL (kept if still in DB and not deleted)
    #        - the literal "__NEW__" sentinel (consume the next uploaded file)
    #      This lets the user drag a freshly-dropped photo into the
    #      Vitrine slots BEFORE saving — the order survives end-to-end.
    #   2. Any URL listed in `photo_delete` is dropped.
    #   3. Files in `request.files.getlist("photos")` not consumed by a
    #      __NEW__ sentinel are appended at the end (graceful fallback
    #      for non-JS clients or buggy front-end states).
    #   4. Hard cap at 10 entries; surplus is silently truncated.
    PHOTOS_MAX = 10
    existing_photos = set(caterer.photos or [])
    delete_urls = set(request.form.getlist("photo_delete"))
    requested_order = request.form.getlist("photos_order")
    new_files = [f for f in request.files.getlist("photos") if f and f.filename]
    new_iter = iter(new_files)

    final: list[str] = []
    for token in requested_order:
        if token == "__NEW__":
            file = next(new_iter, None)
            if file is None:
                continue
            url = save_upload(file, subfolder="caterers")
            if url:
                final.append(url)
        elif token in existing_photos and token not in delete_urls:
            final.append(token)

    # Append leftover uploads (no JS, or more files than __NEW__ tokens).
    for file in new_iter:
        url = save_upload(file, subfolder="caterers")
        if url:
            final.append(url)

    # If photos_order was empty (e.g. very old client), keep existing minus deletes.
    if not requested_order and not new_files:
        final = [u for u in (caterer.photos or []) if u not in delete_urls]

    caterer.photos = final[:PHOTOS_MAX]

    # Logo : champ optionnel. La case "logo_delete" prend le pas si cochee
    # ET aucun nouveau fichier n'est envoye en meme temps. Un nouvel upload
    # remplace silencieusement l'ancien.
    logo_file = request.files.get("logo")
    if logo_file and logo_file.filename:
        new_logo_url = save_upload(logo_file, subfolder="caterers/logos")
        if new_logo_url:
            caterer.logo_url = new_logo_url
        else:
            flash("Logo refuse : format ou taille invalide.", "error")
    elif request.form.get("logo_delete") == "1":
        caterer.logo_url = None

    specialties_raw = form.specialties.data or ""
    caterer.specialties = [s.strip() for s in specialties_raw.split(",") if s.strip()] if specialties_raw else caterer.specialties
    service_config_raw = form.service_config.data or ""
    if service_config_raw:
        # VULN-25: validate the JSON shape strictly. Pydantic with extra="forbid"
        # rejects unknown keys (typos, attempted bloat) and enforces the
        # MealType -> bool contract that services/matching.py relies on.
        try:
            parsed = json.loads(service_config_raw)
            validated = ServiceConfig.model_validate(parsed)
            caterer.service_config = validated.model_dump()
        except json.JSONDecodeError:
            flash("Configuration JSON : syntaxe invalide.", "error")
            return redirect(url_for("caterer.profile"))
        except ValidationError as exc:
            # Surface the first error in human terms (full report goes to logs).
            first = exc.errors()[0]
            field = ".".join(str(p) for p in first["loc"]) or "(racine)"
            flash(f"Configuration JSON invalide en '{field}' : {first['msg']}.", "error")
            return redirect(url_for("caterer.profile"))
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
        try:
            status_enum = QRCStatus(status_filter)
        except ValueError:
            status_filter = None
        else:
            stmt = stmt.where(QuoteRequestCaterer.status == status_enum)
    qrcs = db.scalars(stmt.order_by(QuoteRequestCaterer.id.desc())).all()
    # For each candidacy, derive a single human-friendly status that the
    # caterer cares about (Nouvelle / Devis envoyé / Devis refusé /
    # Commande créée). The truth lives on the caterer's own Quote, not on
    # qrc.status — the latter only reflects the admin-side workflow.
    for qrc in qrcs:
        qr = qrc.quote_request
        _ = qr.company  # eager load for template
        caterer_quote = next(
            (q for q in qr.quotes if q.caterer_id == caterer.id),
            None,
        )
        if caterer_quote is None or caterer_quote.status == QuoteStatus.draft:
            qrc.display_status = "new"
        elif caterer_quote.status == QuoteStatus.refused:
            qrc.display_status = "quotes_refused"
        elif caterer_quote.status == QuoteStatus.accepted:
            qrc.display_status = "quote_accepted"
        else:
            # sent / expired — both surface as "Devis envoyé" since the
            # caterer's action (sending the quote) is what matters here.
            qrc.display_status = "sent"
    return render_template(
        "caterer/requests/list.html",
        user=g.current_user,
        qrcs=qrcs,
        status_filter=status_filter,
        meal_type_labels=MEAL_TYPE_LABELS,
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
    totals = calculate_quote_totals(line_dicts, qr.guest_count, commission_rate=caterer.commission_rate)
    reference = generate_quote_reference(db, caterer)
    quote = Quote(
        quote_request_id=qr_id,
        caterer_id=caterer.id,
        reference=reference,
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
    if quote.status != QuoteStatus.draft:
        flash("Ce devis a déjà été envoyé et ne peut plus être modifié.", "error")
        return redirect(url_for("caterer.request_detail", qr_id=qr_id))
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
    totals = calculate_quote_totals(line_dicts, qr.guest_count, commission_rate=caterer.commission_rate)
    quote.lines = new_lines
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
    db = get_db()
    try:
        workflow.submit_quote(
            db,
            request_id=qr_id,
            quote_id=q_id,
            caterer=g.current_user.caterer,
        )
    except workflow.QuoteNotFound:
        abort(404)
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
    """Deliver an order. Phase 1 (DB-only) is synchronous; phase 2 (Stripe
    invoice) is enqueued in dramatiq so the caterer doesn't wait on a
    multi-second Stripe round-trip. P3.4."""
    caterer = g.current_user.caterer
    db = get_db()
    try:
        order = workflow.mark_delivered(db, order_id=order_id, caterer=caterer)
    except workflow.OrderNotFound:
        abort(404)

    if caterer.stripe_account_id and caterer.stripe_charges_enabled:
        # Mark as `invoicing` BEFORE commit so the worker can't pick up
        # the order and race ahead while we're still mid-transaction.
        order.status = OrderStatus.invoicing
        db.commit()
        # Enqueue the Stripe call. send() returns immediately; the actor
        # runs in the worker container.
        from services.billing_tasks import send_invoice_for_order
        send_invoice_for_order.send(order_id=str(order.id))
        flash(
            "Commande livree. La facture Stripe est en cours de generation.",
            "success",
        )
    else:
        db.commit()
        flash("Commande marquee comme livree.", "success")
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
