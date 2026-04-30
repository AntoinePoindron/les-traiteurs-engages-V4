import math
import uuid

from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from blueprints.client._helpers import (
    DIETARY_FLAGS,
    ITEMS_PER_PAGE,
    STATUS_TABS,
    STRUCTURE_GROUPS,
    apply_quote_request_form,
    own_service_id,
)
from blueprints.middleware import login_required, role_required
from blueprints.scoping import get_company_request
from database import get_db
from extensions import limiter
from forms.client import QuoteAcceptForm, QuoteRefuseForm, QuoteRequestForm
from models import (
    MEAL_TYPE_LABELS,
    Caterer,
    CatererStructureType,
    CompanyService,
    QRCStatus,
    Quote,
    QuoteRequest,
    QuoteRequestCaterer,
    QuoteRequestStatus,
    QuoteStatus,
)
from services import workflow
from services.quotes import calculate_quote_totals


# Filter tabs visible on /client/requests. Each tab maps to one of the
# values _derive_request_display_status() returns (or "all").
REQUEST_STATUS_TABS = {
    "all":              "Toutes",
    "awaiting_quotes":  "En attente de devis",
    "quotes_received":  "Devis reçu(s)",
    "completed":        "Commande créée",
    "closed":           "Clôturées",
}

# Quote statuses that count as "the caterer actually responded" (drafts
# don't, since the client can't see them).
_QUOTE_RECEIVED_STATUSES = (
    QuoteStatus.sent,
    QuoteStatus.accepted,
    QuoteStatus.refused,
    QuoteStatus.expired,
)


def _derive_request_display_status(qr):
    """Collapse QR.status + quote presence into a single client-facing code.

    Returns one of: 'awaiting_quotes', 'quotes_received', 'completed',
    'closed' (or 'cancelled', kept distinct so the row badge can stay
    meaningful even though the "Clôturées" tab buckets them together).

    The status_badge component already handles each of these strings
    with a label and a colour, so the template can pass the result
    straight through.
    """
    if qr.status == QuoteRequestStatus.completed:
        return "completed"
    if qr.status == QuoteRequestStatus.cancelled:
        return "cancelled"
    if qr.status == QuoteRequestStatus.quotes_refused:
        return "closed"
    has_received = any(q.status in _QUOTE_RECEIVED_STATUSES for q in qr.quotes)
    return "quotes_received" if has_received else "awaiting_quotes"


def _request_quote_counts(qr):
    """Return (received_count, expected_count) used in the row footer.

    `received` counts quotes the caterer actually sent (drafts excluded).
    `expected` is 1 for single-caterer demands, 3 for compare-mode demands
    — matches the wizard's "Recevoir 3 devis" copy.
    """
    received = sum(1 for q in qr.quotes if q.status in _QUOTE_RECEIVED_STATUSES)
    expected = 1 if not qr.is_compare_mode else 3
    return received, expected


def register(bp):
    @bp.route("/requests")
    @login_required
    @role_required("client_admin", "client_user")
    def requests_list():
        user = g.current_user
        status_filter = request.args.get("status", "all")
        if status_filter not in REQUEST_STATUS_TABS:
            status_filter = "all"
        search_q = (request.args.get("q") or "").strip().lower()

        db = get_db()
        # selectinload(quotes) avoids N+1 when computing display_status
        # and quote counts for every row.
        stmt = (
            select(QuoteRequest)
            .where(QuoteRequest.company_id == user.company_id)
            .options(selectinload(QuoteRequest.quotes))
            .order_by(QuoteRequest.created_at.desc())
        )
        requests = db.execute(stmt).scalars().all()

        # Hydrate row-level helpers used by the template so it stays
        # arithmetic-free.
        for qr in requests:
            qr.display_status = _derive_request_display_status(qr)
            qr.received_quotes, qr.expected_quotes = _request_quote_counts(qr)

        # Tab filter: "closed" buckets cancelled + closed for the user
        # but each row keeps its own badge.
        if status_filter == "closed":
            requests = [r for r in requests if r.display_status in ("closed", "cancelled")]
        elif status_filter != "all":
            requests = [r for r in requests if r.display_status == status_filter]

        # Free-text search across the cheap-to-check fields. Stays in
        # Python because the volume per company is small (< 100 demands).
        if search_q:
            def _matches(qr):
                haystack = " ".join(filter(None, [
                    MEAL_TYPE_LABELS.get(qr.meal_type, "") if qr.meal_type else "",
                    qr.service_type or "",
                    qr.event_city or "",
                    qr.message_to_caterer or "",
                ])).lower()
                return search_q in haystack
            requests = [r for r in requests if _matches(r)]

        return render_template(
            "client/requests/list.html",
            user=user,
            requests=requests,
            current_tab=status_filter,
            tabs=REQUEST_STATUS_TABS,
            search_q=search_q,
            meal_type_labels=MEAL_TYPE_LABELS,
        )

    @bp.route("/requests/new", methods=["GET"])
    @login_required
    @role_required("client_admin", "client_user")
    def requests_new():
        user = g.current_user
        db = get_db()
        services = db.execute(
            select(CompanyService).where(CompanyService.company_id == user.company_id)
        ).scalars().all()
        # When the wizard is opened from a specific caterer profile
        # (?caterer_id=...), prefill target_caterer so the form ships the
        # demand straight to that caterer and bypasses admin matching.
        target_caterer = None
        raw_caterer_id = request.args.get("caterer_id")
        if raw_caterer_id:
            try:
                cid = uuid.UUID(raw_caterer_id)
            except ValueError:
                cid = None
            if cid is not None:
                target_caterer = db.scalar(
                    select(Caterer)
                    .where(Caterer.id == cid)
                    .where(Caterer.is_validated.is_(True))
                )
        return render_template(
            "client/requests/new.html",
            user=user,
            services=services,
            target_caterer=target_caterer,
        )

    @bp.route("/requests/new", methods=["POST"])
    @login_required
    @role_required("client_admin", "client_user")
    def requests_new_post():
        user = g.current_user
        form = QuoteRequestForm()
        if not form.validate_on_submit():
            flash("Veuillez corriger les erreurs du formulaire.", "error")
            db = get_db()
            services = db.execute(
                select(CompanyService).where(CompanyService.company_id == user.company_id)
            ).scalars().all()
            return render_template(
                "client/requests/new.html",
                user=user,
                services=services,
                target_caterer=None,
            ), 400

        db = get_db()
        service_id = own_service_id(db, user, form.company_service_id.data)

        # Resolve target caterer (single-caterer flow). Validate UUID
        # AND that the caterer actually exists + is validated, so a
        # tampered hidden input can't sneak through.
        target_caterer = None
        raw_target = (form.target_caterer_id.data or "").strip()
        if raw_target:
            try:
                cid = uuid.UUID(raw_target)
            except ValueError:
                cid = None
            if cid is not None:
                target_caterer = db.scalar(
                    select(Caterer)
                    .where(Caterer.id == cid)
                    .where(Caterer.is_validated.is_(True))
                )

        if target_caterer is not None:
            # Single-caterer demand: skip admin review entirely, send
            # directly to that caterer with a QRC in 'selected' state
            # (= awaiting the caterer's response, like the admin had
            # transmitted it).
            status = QuoteRequestStatus.sent_to_caterers
            is_compare = False
        else:
            # Standard wizard ("Recevoir 3 devis"): admin curates the
            # candidate list, status sits in pending_review until then.
            is_compare = bool(form.is_compare_mode.data)
            status = (
                QuoteRequestStatus.pending_review
                if is_compare
                else QuoteRequestStatus.sent_to_caterers
            )

        qr = QuoteRequest(
            company_id=user.company_id,
            user_id=user.id,
            company_service_id=service_id,
            status=status,
        )
        apply_quote_request_form(qr, form)
        # Force the persisted is_compare_mode to match the resolved flow
        # (apply_quote_request_form may have written it from the form).
        qr.is_compare_mode = is_compare
        db.add(qr)
        db.flush()

        if target_caterer is not None:
            db.add(QuoteRequestCaterer(
                quote_request_id=qr.id,
                caterer_id=target_caterer.id,
                status=QRCStatus.selected,
            ))

        qr_id = qr.id
        db.commit()

        flash("Votre demande de devis a ete envoyee avec succes.", "success")
        return redirect(url_for("client.request_detail", request_id=qr_id))

    @bp.route("/requests/<uuid:request_id>")
    @login_required
    @role_required("client_admin", "client_user")
    def request_detail(request_id):
        user = g.current_user
        db = get_db()
        qr = get_company_request(request_id, user.company_id)

        qrcs = db.execute(
            select(QuoteRequestCaterer).where(
                QuoteRequestCaterer.quote_request_id == request_id
            )
        ).scalars().all()

        quotes = db.execute(
            select(Quote).where(Quote.quote_request_id == request_id)
            .order_by(Quote.created_at.asc())
        ).scalars().all()

        # Attach per-quote PDF preview data so the template can render a
        # read-only modal for "Voir le devis" without doing arithmetic in
        # Jinja. quote.pdf_preview stays None for any quote that has no
        # line items (defensive — the modal opener checks for it).
        for quote in quotes:
            if quote.lines:
                line_dicts = [ln.as_dict() for ln in quote.lines]
                totals = calculate_quote_totals(
                    line_dicts,
                    qr.guest_count,
                    commission_rate=quote.caterer.commission_rate,
                )
                lines_by_section: dict[str, list] = {}
                for ln in quote.lines:
                    lines_by_section.setdefault(ln.section, []).append(ln)
                quote.pdf_preview = {
                    "lines_by_section": lines_by_section,
                    "totals": totals,
                }
            else:
                quote.pdf_preview = None

        return render_template(
            "client/requests/detail.html",
            user=user,
            qr=qr,
            qrcs=qrcs,
            quotes=quotes,
            meal_type_labels=MEAL_TYPE_LABELS,
        )

    @bp.route("/requests/<uuid:request_id>/accept-quote", methods=["POST"])
    @limiter.limit("10 per minute")
    @login_required
    @role_required("client_admin")
    def accept_quote(request_id):
        form = QuoteAcceptForm()
        if not form.validate_on_submit():
            abort(400)
        try:
            quote_uuid = uuid.UUID(form.quote_id.data)
        except ValueError:
            abort(400)

        db = get_db()
        try:
            order = workflow.accept_quote(
                db,
                request_id=request_id,
                quote_id=quote_uuid,
                user=g.current_user,
            )
        except workflow.RequestNotFound:
            abort(404)
        except workflow.QuoteNotAvailable:
            flash("Ce devis n'est plus disponible.", "error")
            return redirect(url_for("client.request_detail", request_id=request_id))
        except workflow.QuoteExpired:
            flash("Ce devis a expire.", "error")
            return redirect(url_for("client.request_detail", request_id=request_id))
        db.commit()

        flash("Devis accepte ! La commande a ete creee.", "success")
        return redirect(url_for("client.order_detail", order_id=order.id))

    @bp.route("/requests/<uuid:request_id>/refuse-quote", methods=["POST"])
    @login_required
    @role_required("client_admin")
    def refuse_quote(request_id):
        form = QuoteRefuseForm()
        if not form.validate_on_submit():
            abort(400)
        try:
            quote_uuid = uuid.UUID(form.quote_id.data)
        except ValueError:
            abort(400)

        db = get_db()
        try:
            workflow.refuse_quote(
                db,
                request_id=request_id,
                quote_id=quote_uuid,
                user=g.current_user,
                reason=form.refusal_reason.data or None,
            )
        except (workflow.RequestNotFound, workflow.QuoteNotFound):
            abort(404)
        db.commit()

        flash("Devis refuse.", "info")
        return redirect(url_for("client.request_detail", request_id=request_id))

    @bp.route("/requests/<uuid:request_id>/edit", methods=["GET"])
    @login_required
    @role_required("client_admin", "client_user")
    def request_edit(request_id):
        user = g.current_user
        db = get_db()
        qr = get_company_request(request_id, user.company_id)
        if qr.status not in (QuoteRequestStatus.draft, QuoteRequestStatus.pending_review):
            flash("Cette demande ne peut plus etre modifiee.", "error")
            return redirect(url_for("client.request_detail", request_id=request_id))

        services = db.execute(
            select(CompanyService).where(CompanyService.company_id == user.company_id)
        ).scalars().all()

        return render_template(
            "client/requests/edit.html",
            user=user,
            qr=qr,
            services=services,
        )

    @bp.route("/requests/<uuid:request_id>/edit", methods=["POST"])
    @login_required
    @role_required("client_admin", "client_user")
    def request_edit_post(request_id):
        user = g.current_user

        db = get_db()
        qr = get_company_request(request_id, user.company_id)
        if qr.status not in (QuoteRequestStatus.draft, QuoteRequestStatus.pending_review):
            flash("Cette demande ne peut plus etre modifiee.", "error")
            return redirect(url_for("client.request_detail", request_id=request_id))

        form = QuoteRequestForm()
        if not form.validate_on_submit():
            flash("Veuillez corriger les erreurs du formulaire.", "error")
            services = db.execute(
                select(CompanyService).where(CompanyService.company_id == user.company_id)
            ).scalars().all()
            return render_template(
                "client/requests/edit.html",
                user=user,
                qr=qr,
                services=services,
            ), 400

        qr.company_service_id = own_service_id(db, user, form.company_service_id.data)
        apply_quote_request_form(qr, form)

        # VULN-36: editing a request that is already awaiting admin qualification
        # MUST keep it in pending_review.
        if qr.status == QuoteRequestStatus.pending_review:
            qr.status = QuoteRequestStatus.pending_review
        else:
            qr.status = (
                QuoteRequestStatus.pending_review if form.is_compare_mode.data
                else QuoteRequestStatus.sent_to_caterers
            )

        db.commit()

        flash("Demande mise a jour.", "success")
        return redirect(url_for("client.request_detail", request_id=request_id))

    @bp.route("/search")
    @login_required
    @role_required("client_admin", "client_user")
    def search():
        page = request.args.get("page", 1, type=int)
        q = request.args.get("q", "").strip()
        structure_type = request.args.get("structure_type", "")
        dietary = request.args.getlist("dietary")
        capacity = request.args.get("capacity", type=int)
        service_type = request.args.get("service_type", "")

        db = get_db()
        stmt = select(Caterer).where(Caterer.is_validated.is_(True))

        if structure_type:
            if structure_type in STRUCTURE_GROUPS:
                stmt = stmt.where(Caterer.structure_type.in_(
                    STRUCTURE_GROUPS[structure_type]
                ))
            else:
                stmt = stmt.where(Caterer.structure_type == structure_type)

        for flag in dietary:
            col = getattr(Caterer, f"dietary_{flag}", None)
            if col is not None:
                stmt = stmt.where(col.is_(True))

        if capacity:
            stmt = stmt.where(
                or_(Caterer.capacity_max.is_(None), Caterer.capacity_max >= capacity)
            )

        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Caterer.name.ilike(pattern),
                    Caterer.description.ilike(pattern),
                )
            )

        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        total_pages = max(1, math.ceil(total / ITEMS_PER_PAGE))
        page = max(1, min(page, total_pages))

        caterers = db.scalars(
            stmt.order_by(Caterer.name)
            .offset((page - 1) * ITEMS_PER_PAGE)
            .limit(ITEMS_PER_PAGE)
        ).all()

        return render_template(
            "client/search.html",
            user=g.current_user,
            caterers=caterers,
            page=page,
            total_pages=total_pages,
            total=total,
            q=q,
            structure_type=structure_type,
            dietary=dietary,
            capacity=capacity,
            service_type=service_type,
            dietary_flags=DIETARY_FLAGS,
            meal_type_labels=MEAL_TYPE_LABELS,
        )

    @bp.route("/caterers/<uuid:caterer_id>")
    @login_required
    @role_required("client_admin", "client_user")
    def caterer_detail(caterer_id):
        db = get_db()
        caterer = db.get(Caterer, caterer_id)
        if not caterer or not caterer.is_validated:
            abort(404)
        return render_template(
            "client/caterer_detail.html",
            user=g.current_user,
            caterer=caterer,
            dietary_flags=DIETARY_FLAGS,
            meal_type_labels=MEAL_TYPE_LABELS,
        )
