import json

from flask import abort, flash, g, redirect, render_template, request as flask_request, url_for
from sqlalchemy import select

from blueprints.middleware import login_required, role_required
from database import get_db
from forms.caterer import QuoteForm
from models import (
    QRCStatus,
    Quote,
    QuoteRequest,
    QuoteRequestCaterer,
    QuoteStatus,
)
from services import workflow
from services.quotes import calculate_quote_totals, generate_quote_reference, lines_from_dicts


def register(bp):
    @bp.route("/requests")
    @login_required
    @role_required("caterer")
    def requests_list():
        caterer = g.current_user.caterer
        status_filter = flask_request.args.get("status")
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
        for qrc in qrcs:
            _ = qrc.quote_request
            _ = qrc.quote_request.company
        return render_template(
            "caterer/requests/list.html",
            user=g.current_user,
            qrcs=qrcs,
            status_filter=status_filter,
        )

    @bp.route("/requests/<uuid:qr_id>")
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

    @bp.route("/requests/<uuid:qr_id>/quote/new", methods=["GET"])
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

    @bp.route("/requests/<uuid:qr_id>/quote", methods=["POST"])
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

    @bp.route("/requests/<uuid:qr_id>/quote/<uuid:q_id>/edit", methods=["GET"])
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

    @bp.route("/requests/<uuid:qr_id>/quote/<uuid:q_id>/edit", methods=["POST"])
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
