import json

from flask import (
    abort,
    flash,
    g,
    redirect,
    render_template,
    request as flask_request,
    url_for,
)
from sqlalchemy import select

from blueprints.middleware import login_required, role_required
from blueprints.scoping import get_caterer_qrc, get_caterer_quote
from database import get_db
from forms.caterer import QuoteForm
from models import (
    MEAL_TYPE_LABELS,
    Order,
    QRCStatus,
    Quote,
    QuoteRequest,
    QuoteRequestCaterer,
    QuoteStatus,
)
from services import workflow
from services.quotes import (
    calculate_quote_totals,
    generate_quote_reference,
    lines_from_dicts,
)


def _parse_line_dicts(raw: str) -> list[dict]:
    """Parse JSON quote lines and reject non-flat structures."""
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list) or not all(
        isinstance(d, dict)
        and all(isinstance(v, (str, int, float, bool, type(None))) for v in d.values())
        for d in data
    ):
        return []
    return data


def _derive_qrc_display_status(qr, caterer_id):
    """Map the caterer's own Quote state to a single user-facing badge code.

    Returns one of: 'new', 'sent', 'quotes_refused', 'quote_accepted'.
    These map to the four labels visible in the caterer UI:
    Nouvelle / Devis envoyé / Devis refusé / Commande créée.

    The truth lives on the caterer's Quote, not on QRC.status — the
    latter only tracks the admin-side workflow (selected, transmitted, …).
    """
    caterer_quote = next(
        (q for q in qr.quotes if q.caterer_id == caterer_id),
        None,
    )
    if caterer_quote is None or caterer_quote.status == QuoteStatus.draft:
        return "new"
    if caterer_quote.status == QuoteStatus.refused:
        return "quotes_refused"
    if caterer_quote.status == QuoteStatus.accepted:
        return "quote_accepted"
    # sent / expired collapse to "Devis envoyé" — what matters here is
    # that the caterer has already acted on the request.
    return "sent"


def register(bp):
    @bp.route("/requests")
    @login_required
    @role_required("caterer")
    def requests_list():
        caterer = g.current_user.caterer
        status_filter = flask_request.args.get("status")
        db = get_db()
        stmt = select(QuoteRequestCaterer).where(
            QuoteRequestCaterer.caterer_id == caterer.id
        )
        if status_filter:
            try:
                status_enum = QRCStatus(status_filter)
            except ValueError:
                status_filter = None
            else:
                stmt = stmt.where(QuoteRequestCaterer.status == status_enum)
        qrcs = db.scalars(stmt.order_by(QuoteRequestCaterer.id.desc())).all()
        for qrc in qrcs:
            qr = qrc.quote_request
            _ = qr.company  # eager load for template
            qrc.display_status = _derive_qrc_display_status(qr, caterer.id)
        return render_template(
            "caterer/requests/list.html",
            user=g.current_user,
            qrcs=qrcs,
            status_filter=status_filter,
            meal_type_labels=MEAL_TYPE_LABELS,
        )

    @bp.route("/requests/<uuid:qr_id>")
    @login_required
    @role_required("caterer")
    def request_detail(qr_id):
        caterer = g.current_user.caterer
        db = get_db()
        qrc = get_caterer_qrc(qr_id, caterer.id)
        qr = qrc.quote_request
        _ = qr.company
        _ = qr.user  # contact for the right-hand client card
        existing_quote = db.scalar(
            select(Quote)
            .where(Quote.quote_request_id == qr_id)
            .where(Quote.caterer_id == caterer.id)
        )
        qrc.display_status = _derive_qrc_display_status(qr, caterer.id)
        # Past orders this caterer fulfilled for the same client (excluding the
        # current request). Powers the "Historique avec ce client" card.
        previous_orders = db.scalars(
            select(Order)
            .join(Quote, Order.quote_id == Quote.id)
            .join(QuoteRequest, Quote.quote_request_id == QuoteRequest.id)
            .where(Quote.caterer_id == caterer.id)
            .where(QuoteRequest.company_id == qr.company_id)
            .where(QuoteRequest.id != qr.id)
            .order_by(Order.created_at.desc())
            .limit(5)
        ).all()
        # When the caterer already has a quote (sent / refused / accepted),
        # we render a read-only PDF preview as an in-page modal — opened by
        # the "Voir le devis" button. Pre-compute the aggregates the partial
        # template needs so the template stays free of arithmetic.
        pdf_preview = None
        if existing_quote and existing_quote.lines:
            line_dicts = [ln.as_dict() for ln in existing_quote.lines]
            totals = calculate_quote_totals(
                line_dicts,
                qr.guest_count,
                commission_rate=caterer.commission_rate,
            )
            lines_by_section: dict[str, list] = {}
            for ln in existing_quote.lines:
                lines_by_section.setdefault(ln.section, []).append(ln)
            pdf_preview = {
                "lines_by_section": lines_by_section,
                "totals": totals,
            }
        return render_template(
            "caterer/requests/detail.html",
            user=g.current_user,
            qr=qr,
            qrc=qrc,
            existing_quote=existing_quote,
            previous_orders=previous_orders,
            meal_type_labels=MEAL_TYPE_LABELS,
            pdf_preview=pdf_preview,
        )

    @bp.route("/requests/<uuid:qr_id>/reject", methods=["POST"])
    @login_required
    @role_required("caterer")
    def request_reject(qr_id):
        """Caterer declines a request before sending any quote.

        Flips QRC.status to rejected. Refused once a quote has already
        left the draft stage — at that point the workflow is the client's
        call.
        """
        caterer = g.current_user.caterer
        db = get_db()
        qrc = get_caterer_qrc(qr_id, caterer.id)
        existing_quote = db.scalar(
            select(Quote)
            .where(Quote.quote_request_id == qr_id)
            .where(Quote.caterer_id == caterer.id)
        )
        if existing_quote and existing_quote.status != QuoteStatus.draft:
            flash("Impossible de refuser une demande après envoi du devis.", "error")
            return redirect(url_for("caterer.request_detail", qr_id=qr_id))
        qrc.status = QRCStatus.rejected
        db.commit()
        flash("La demande a été refusée.", "info")
        return redirect(url_for("caterer.requests_list"))

    @bp.route("/requests/<uuid:qr_id>/quote/new", methods=["GET"])
    @login_required
    @role_required("caterer")
    def quote_new(qr_id):
        caterer = g.current_user.caterer
        db = get_db()
        qrc = get_caterer_qrc(qr_id, caterer.id)
        qr = qrc.quote_request
        _ = qr.company
        # Pre-compute a reference to display read-only in the editor.
        # The server re-generates the real reference at POST time so this
        # is informational only and cannot be tampered with by the client.
        preview_reference = generate_quote_reference(db, caterer)
        return render_template(
            "caterer/quotes/editor.html",
            user=g.current_user,
            qr=qr,
            qrc=qrc,
            quote=None,
            initial_lines=[],
            preview_reference=preview_reference,
            meal_type_labels=MEAL_TYPE_LABELS,
        )

    @bp.route("/requests/<uuid:qr_id>/quote", methods=["POST"])
    @login_required
    @role_required("caterer")
    def quote_create(qr_id):
        caterer = g.current_user.caterer
        db = get_db()
        qrc = get_caterer_qrc(qr_id, caterer.id)
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
                preview_reference=generate_quote_reference(db, caterer),
                meal_type_labels=MEAL_TYPE_LABELS,
            ), 400
        line_dicts = _parse_line_dicts(form.details.data)
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
                preview_reference=generate_quote_reference(db, caterer),
                meal_type_labels=MEAL_TYPE_LABELS,
            ), 400
        totals = calculate_quote_totals(
            line_dicts, qr.guest_count, commission_rate=caterer.commission_rate
        )
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
        # action=send saves the draft AND sends it in one go, so the caterer
        # doesn't have to navigate away and come back. Default is 'draft'.
        action = flask_request.form.get("action", "draft")
        if action == "send":
            try:
                workflow.submit_quote(
                    db,
                    request_id=qr_id,
                    quote_id=quote.id,
                    caterer=caterer,
                )
                db.commit()
            except workflow.QuoteNotFound:
                abort(404)
            flash("Devis enregistre et envoye au client.", "success")
        else:
            flash("Devis enregistre en brouillon.", "success")
        return redirect(url_for("caterer.request_detail", qr_id=qr_id))

    @bp.route("/requests/<uuid:qr_id>/quote/<uuid:q_id>/edit", methods=["GET"])
    @login_required
    @role_required("caterer")
    def quote_edit(qr_id, q_id):
        caterer = g.current_user.caterer
        quote = get_caterer_quote(qr_id, q_id, caterer.id)
        qr = quote.quote_request
        _ = qr.company
        qrc = get_caterer_qrc(qr_id, caterer.id)
        return render_template(
            "caterer/quotes/editor.html",
            user=g.current_user,
            qr=qr,
            qrc=qrc,
            quote=quote,
            initial_lines=[ln.as_dict() for ln in quote.lines],
            preview_reference=quote.reference,
            meal_type_labels=MEAL_TYPE_LABELS,
        )

    @bp.route("/requests/<uuid:qr_id>/quote/<uuid:q_id>/edit", methods=["POST"])
    @login_required
    @role_required("caterer")
    def quote_update(qr_id, q_id):
        caterer = g.current_user.caterer
        db = get_db()
        quote = get_caterer_quote(qr_id, q_id, caterer.id)
        if quote.status != QuoteStatus.draft:
            flash("Ce devis a déjà été envoyé et ne peut plus être modifié.", "error")
            return redirect(url_for("caterer.request_detail", qr_id=qr_id))
        qr = quote.quote_request
        qrc = get_caterer_qrc(qr_id, caterer.id)
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
                preview_reference=quote.reference,
                meal_type_labels=MEAL_TYPE_LABELS,
            ), 400
        line_dicts = _parse_line_dicts(form.details.data)
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
                preview_reference=quote.reference,
                meal_type_labels=MEAL_TYPE_LABELS,
            ), 400
        totals = calculate_quote_totals(
            line_dicts, qr.guest_count, commission_rate=caterer.commission_rate
        )
        quote.lines = new_lines
        quote.total_amount_ht = totals["total_ht"]
        quote.amount_per_person = totals["amount_per_person"]
        quote.valorisable_agefiph = totals["valorisable_agefiph"]
        quote.notes = form.notes.data or ""
        quote.valid_until = (
            form.valid_until.data if form.valid_until.data else quote.valid_until
        )
        db.commit()
        # Same as quote_create: action=send chains save + send so the
        # caterer can ship the quote without leaving the editor.
        action = flask_request.form.get("action", "draft")
        if action == "send":
            try:
                workflow.submit_quote(
                    db,
                    request_id=qr_id,
                    quote_id=quote.id,
                    caterer=caterer,
                )
                db.commit()
            except workflow.QuoteNotFound:
                abort(404)
            flash("Devis mis a jour et envoye au client.", "success")
        else:
            flash("Devis mis a jour.", "success")
        return redirect(url_for("caterer.request_detail", qr_id=qr_id))

    @bp.route("/requests/<uuid:qr_id>/quote/<uuid:q_id>/send", methods=["POST"])
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
