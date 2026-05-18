import logging
import math
import uuid
from io import BytesIO

from flask import (
    abort,
    flash,
    g,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from blueprints.client._helpers import (
    DIETARY_FLAGS,
    ITEMS_PER_PAGE,
    STRUCTURE_GROUPS,
    apply_quote_request_form,
    own_service_id,
)
from blueprints.middleware import login_required, role_required
from blueprints.scoping import get_company_request, own_requests_filter
from database import get_db
from extensions import limiter
from forms.client import QuoteAcceptForm, QuoteRefuseForm, QuoteRequestForm
from models import (
    MEAL_TYPE_LABELS,
    PRICE_BAND_BOUNDS,
    SERVICE_OFFERING_LABELS,
    Caterer,
    CompanyService,
    Notification,
    QRCStatus,
    Quote,
    QuoteRequest,
    QuoteRequestCaterer,
    QuoteRequestStatus,
    QuoteStatus,
)
from services import workflow
from services.notifications import (
    caterer_user_ids,
    notify_users,
    super_admin_user_ids,
)
from services.quotes import calculate_quote_totals

logger = logging.getLogger(__name__)


def _no_store(response):
    """Tag a response so the browser does not keep it in history.

    Without this, pressing "back" after submitting the wizard restores
    the cached HTML — pre-ticked checkboxes carried only in DOM state
    (not in the server-rendered attributes) appear blank, and the user
    can re-submit a stale form. `no-store` evicts the response from
    bfcache (Chrome/Firefox) and from regular cache, forcing the
    browser to re-fetch on back/forward navigation.

    Modern browsers honor `Cache-Control: no-store` on its own — the
    `Pragma: no-cache` (HTTP/1.0) and `Expires: 0` headers we used to
    add alongside are folklore here and some CDN middlewares re-
    interpret them in surprising ways, so we keep this single header.
    """
    response.headers["Cache-Control"] = "no-store"
    return response


# Icon glyph (lucide) per MealType slug — kept next to the templates'
# step-1 radios. Anything not listed falls back to `utensils`.
_MEAL_TYPE_ICONS: dict[str, str] = {
    "petit_dejeuner": "coffee",
    "pause_gourmande": "cookie",
    "plateaux_repas": "utensils",
    "cocktail_dinatoire": "wine",
    "cocktail_dejeunatoire": "wine",
    "aperitif": "martini",
}


def _resolve_target_caterer(db, raw_id):
    """Resolve a `target_caterer_id` string (form or query param) to a
    validated Caterer row, or None if blank/invalid/not-validated.

    Same gate as the workflow: only `is_validated=True` caterers can
    receive a targeted demand. Returning None here means "treat as open
    demand", which the route handler does upstream.
    """
    raw = (raw_id or "").strip()
    if not raw:
        return None
    try:
        cid = uuid.UUID(raw)
    except ValueError:
        return None
    return db.scalar(
        select(Caterer).where(Caterer.id == cid).where(Caterer.is_validated.is_(True))
    )


def _caterer_capabilities(caterer):
    """Wizard step-4 needs to grey out régimes the caterer can't honor.

    Returns None for open demands so the template falls through to
    "no restriction"; otherwise a dict of dietary booleans.
    """
    if caterer is None:
        return None
    return {
        "dietary": {
            "vegetarian": bool(caterer.dietary_vegetarian),
            "vegan": bool(caterer.dietary_vegan),
            "halal": bool(caterer.dietary_halal),
            "gluten_free": bool(caterer.dietary_gluten_free),
            "lactose_free": bool(caterer.dietary_lactose_free),
        },
    }


def _meal_type_options(restrict_to: set[str] | None = None) -> list[dict]:
    """Render-ready list of `{slug, label, icon}` for the step-1 radios.

    Pass `restrict_to` to filter on what a targeted caterer publishes
    (= `Caterer.service_offerings`). With no argument the caller gets
    the full canonical list.
    """
    options = [
        {
            "slug": m.value,
            "label": label,
            "icon": _MEAL_TYPE_ICONS.get(m.value, "utensils"),
        }
        for m, label in MEAL_TYPE_LABELS.items()
    ]
    if restrict_to is None:
        return options
    return [opt for opt in options if opt["slug"] in restrict_to]


# Filter tabs visible on /client/requests. Each tab maps to one of the
# values _derive_request_display_status() returns (or "all").
REQUEST_STATUS_TABS = {
    "all": "Toutes",
    "awaiting_quotes": "En attente de devis",
    "quotes_received": "Devis reçu(s)",
    "completed": "Commande créée",
    "closed": "Clôturées",
}

# Quote statuses that count as "the caterer actually responded" (drafts
# don't, since the client can't see them).
_QUOTE_RECEIVED_STATUSES = (
    QuoteStatus.sent,
    QuoteStatus.accepted,
    QuoteStatus.refused,
    QuoteStatus.expired,
)

# Mirror of the cap on caterer/requests.py: refuse to render a quote
# whose line items list is implausibly long. Stops a malicious or
# corrupted row from saturating the WeasyPrint worker.
_MAX_PDF_LINES = 500


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
        own_only = own_requests_filter(user)
        if own_only is not None:
            stmt = stmt.where(own_only)
        requests = db.execute(stmt).scalars().all()

        # Hydrate row-level helpers used by the template so it stays
        # arithmetic-free.
        for qr in requests:
            qr.display_status = _derive_request_display_status(qr)
            qr.received_quotes, qr.expected_quotes = _request_quote_counts(qr)

        # Tab filter: "closed" buckets cancelled + closed for the user
        # but each row keeps its own badge.
        if status_filter == "closed":
            requests = [
                r for r in requests if r.display_status in ("closed", "cancelled")
            ]
        elif status_filter != "all":
            requests = [r for r in requests if r.display_status == status_filter]

        # Free-text search across the cheap-to-check fields. Stays in
        # Python because the volume per company is small (< 100 demands).
        if search_q:

            def _matches(qr):
                haystack = " ".join(
                    filter(
                        None,
                        [
                            MEAL_TYPE_LABELS.get(qr.meal_type, "")
                            if qr.meal_type
                            else "",
                            qr.service_type or "",
                            qr.event_city or "",
                            qr.message_to_caterer or "",
                        ],
                    )
                ).lower()
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
        services = (
            db.execute(
                select(CompanyService).where(
                    CompanyService.company_id == user.company_id
                )
            )
            .scalars()
            .all()
        )
        # When the wizard is opened from a specific caterer profile
        # (?caterer_id=...), prefill target_caterer so the form ships the
        # demand straight to that caterer and bypasses admin matching.
        target_caterer = _resolve_target_caterer(db, request.args.get("caterer_id"))

        # Build the list of prestation options the wizard's step 1 will
        # render as radios. Two cases:
        #  - Targeted demand : filter to what the caterer actually
        #    publishes under "Catalogue & tarifs" (= service_offerings).
        #  - Open demand     : the full canonical MEAL_TYPE_LABELS list.
        # The radio's `value` IS the MealType slug — the wizard no longer
        # needs a hidden meal_type field nor a service_offering → meal_type
        # mapping, since the two surfaces now share the same slug set.
        restrict = (
            set(target_caterer.service_offerings or [])
            if target_caterer is not None
            else None
        )
        return _no_store(
            make_response(
                render_template(
                    "client/requests/new.html",
                    user=user,
                    services=services,
                    target_caterer=target_caterer,
                    meal_type_options=_meal_type_options(restrict_to=restrict),
                    caterer_capabilities=_caterer_capabilities(target_caterer),
                    # Idempotency token: a fresh GET in another tab
                    # produces a new one. The POST handler uses it to
                    # deduplicate. Combined with the `no_store` header
                    # below, "back + resubmit" doesn't even reach this
                    # branch — bfcache is bypassed.
                    form_token=str(uuid.uuid4()),
                )
            )
        )

    @bp.route("/requests/new", methods=["POST"])
    @login_required
    @role_required("client_admin", "client_user")
    def requests_new_post():
        user = g.current_user
        db = get_db()
        form = QuoteRequestForm()

        # Idempotency : the GET emits a one-shot UUID into a hidden
        # `form_token` field. A "back + resubmit" replays the same
        # token; we short-circuit straight to the existing detail page
        # instead of creating a duplicate row. Scoping to company_id
        # closes a (very unlikely) cross-tenant clash.
        form_token = (request.form.get("form_token") or "").strip()
        if form_token:
            try:
                uuid.UUID(form_token)
            except ValueError:
                form_token = ""
        if form_token:
            existing = db.scalar(
                select(QuoteRequest).where(
                    QuoteRequest.submission_token == form_token,
                    QuoteRequest.company_id == user.company_id,
                )
            )
            if existing is not None:
                flash("Cette demande a deja ete envoyee.", "info")
                return redirect(
                    url_for("client.request_detail", request_id=existing.id)
                )

        # Resolve the targeted caterer (if any) before validation so the
        # form-side `validate_meal_type` cross-field rule has the right
        # offerings set to gate against. A tampered POST with
        # `meal_type=pause_gourmande` for a caterer that doesn't offer
        # it gets rejected here, not silently persisted.
        target_caterer = _resolve_target_caterer(db, form.target_caterer_id.data)
        if target_caterer is not None:
            form.target_offerings = set(target_caterer.service_offerings or [])

        if not form.validate_on_submit():
            flash("Veuillez corriger les erreurs du formulaire.", "error")
            services = (
                db.execute(
                    select(CompanyService).where(
                        CompanyService.company_id == user.company_id
                    )
                )
                .scalars()
                .all()
            )
            restrict = (
                set(target_caterer.service_offerings or [])
                if target_caterer is not None
                else None
            )
            response = _no_store(
                make_response(
                    render_template(
                        "client/requests/new.html",
                        user=user,
                        services=services,
                        target_caterer=target_caterer,
                        meal_type_options=_meal_type_options(restrict_to=restrict),
                        caterer_capabilities=_caterer_capabilities(target_caterer),
                        # Echo the token back so the user's correction
                        # stays idempotent — a tab-restored form keeps
                        # the same token.
                        form_token=form_token or str(uuid.uuid4()),
                    )
                )
            )
            response.status_code = 400
            return response

        service_id = own_service_id(db, user, form.company_service_id.data)

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
            submission_token=form_token or None,
        )
        apply_quote_request_form(qr, form)
        # Force the persisted is_compare_mode to match the resolved flow
        # (apply_quote_request_form may have written it from the form).
        qr.is_compare_mode = is_compare
        db.add(qr)
        try:
            db.flush()
        except IntegrityError:
            # Race condition: a concurrent POST landed first and grabbed
            # the same token. Resolve to that one instead of failing.
            db.rollback()
            existing = db.scalar(
                select(QuoteRequest).where(
                    QuoteRequest.submission_token == form_token,
                    QuoteRequest.company_id == user.company_id,
                )
            )
            if existing is None:
                # Token clash that's NOT the dedup case — surface it.
                raise
            flash("Cette demande a deja ete envoyee.", "info")
            return redirect(url_for("client.request_detail", request_id=existing.id))

        if target_caterer is not None:
            db.add(
                QuoteRequestCaterer(
                    quote_request_id=qr.id,
                    caterer_id=target_caterer.id,
                    status=QRCStatus.selected,
                )
            )
            # Single-caterer demand bypasses admin curation, so notify
            # the caterer directly. The « 3 devis » flow goes through
            # workflow.approve_quote_request which already notifies.
            notify_users(
                db,
                caterer_user_ids(db, target_caterer.id),
                type="quote_request_received",
                title="Nouvelle demande de devis",
                body=f"Une demande pour {qr.guest_count or '?'} convives "
                f"({qr.event_city or 'lieu non renseigné'}) vous a été transmise.",
                related_entity_type="quote_request",
                related_entity_id=qr.id,
            )
        elif qr.status == QuoteRequestStatus.pending_review:
            # « Recevoir 3 devis » : la demande arrive en file de
            # qualification — alerter les super_admins.
            notify_users(
                db,
                super_admin_user_ids(db),
                type="quote_request_to_qualify",
                title="Nouvelle demande à qualifier",
                body=f"Une demande de {qr.guest_count or '?'} convives à "
                f"{qr.event_city or 'lieu non renseigné'} attend qualification.",
                related_entity_type="quote_request",
                related_entity_id=qr.id,
            )

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
        qr = get_company_request(request_id, user)

        # Order by id so qrcs[0] is deterministic — the model has no
        # created_at, and the template indexes into qrcs in direct mode
        # to render the pending-caterer card.
        qrcs = (
            db.execute(
                select(QuoteRequestCaterer)
                .where(QuoteRequestCaterer.quote_request_id == request_id)
                .order_by(QuoteRequestCaterer.id)
            )
            .scalars()
            .all()
        )

        # Drafts are caterer-only — they're work-in-progress quotes the
        # caterer hasn't sent yet. Surfacing them on the client side
        # leaks pricing + caterer identity before the caterer is ready
        # to commit. Allow-list rather than `!= draft` so a future
        # status doesn't leak by default — same gate as the dashboard
        # helpers and the client.quote_pdf route.
        quotes = (
            db.execute(
                select(Quote)
                .where(Quote.quote_request_id == request_id)
                .where(Quote.status.in_(_QUOTE_RECEIVED_STATUSES))
                .order_by(Quote.created_at.asc())
            )
            .scalars()
            .all()
        )

        # Same display_status logic as the list page so the header badge
        # uses a French, user-facing label instead of the raw enum value.
        qr.display_status = _derive_request_display_status(qr)

        # Resolve the contactable caterer user once per quote / qrc so
        # the template doesn't have to do `caterer.users[0] if ... else
        # None` in two separate loops (button render + modal render).
        # Same shape for qrcs so the pending-caterer card reads from a
        # single source of truth.
        for quote in quotes:
            quote.caterer_user = quote.caterer.users[0] if quote.caterer.users else None
        for qrc in qrcs:
            qrc.caterer_user = qrc.caterer.users[0] if qrc.caterer.users else None

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

        # Surface admin → client messages tied to this QR. The
        # super_admin sends them from /admin/qualification/<id>; the
        # write path stores one Notification per company_admin. Pulling
        # them here means the client sees them inline on the request
        # detail even before the bell-notification UI lands.
        admin_messages = (
            db.execute(
                select(Notification)
                .where(
                    Notification.user_id == user.id,
                    Notification.type == "admin_message",
                    Notification.related_entity_type == "quote_request",
                    Notification.related_entity_id == qr.id,
                )
                .order_by(Notification.created_at.desc())
            )
            .scalars()
            .all()
        )

        return render_template(
            "client/requests/detail.html",
            user=user,
            qr=qr,
            qrcs=qrcs,
            quotes=quotes,
            meal_type_labels=MEAL_TYPE_LABELS,
            admin_messages=admin_messages,
        )

    @bp.route("/requests/<uuid:request_id>/accept-quote", methods=["POST"])
    @limiter.limit("10 per minute")
    @login_required
    # Both client_admin and client_user can accept on behalf of the
    # company. Scoping by `qr.company_id == user.company_id` inside
    # `workflow.accept_quote` is what stops a member of another company
    # from acting on this QR — the role isn't the right gate.
    @role_required("client_admin", "client_user")
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

        from services import email_triggers

        email_triggers.order_confirmed(db, order=order)

        flash("Devis accepte ! La commande a ete creee.", "success")
        return redirect(url_for("client.order_detail", order_id=order.id))

    @bp.route("/requests/<uuid:request_id>/refuse-quote", methods=["POST"])
    @login_required
    # Symmetric with accept-quote: any company member can refuse a
    # quote on behalf of the company. Company-scoping lives in
    # `workflow.refuse_quote`.
    @role_required("client_admin", "client_user")
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

    @bp.route("/requests/<uuid:request_id>/quote/<uuid:q_id>/pdf", methods=["GET"])
    @login_required
    @role_required("client_admin", "client_user")
    @limiter.limit("20 per minute")
    def quote_pdf(request_id, q_id):
        """Download a received quote as a server-rendered PDF.

        Mirrors `caterer.quote_pdf` but the scope check goes the other
        way: the quote must belong to a request the viewer's company
        owns. Reuses `services.quote_pdf.render_quote_pdf` so the file
        looks identical to what the client sees in the in-app preview
        modal (same template, same totals).
        """
        # Lazy import — WeasyPrint pulls Cairo/Pango bindings at import
        # time. Same rationale as caterer.quote_pdf.
        from services.quote_pdf import render_quote_pdf

        user = g.current_user
        db = get_db()
        # Gate scope via get_company_request: applies company_id AND
        # own_requests_filter (a client_user only sees QRs they
        # themselves created — a colleague's QR is out of scope, same
        # rule as the page detail). 404 keeps the existence of an
        # off-scope QR opaque.
        qr = get_company_request(request_id, user)
        quote = db.scalar(
            select(Quote)
            .options(
                selectinload(Quote.lines),
                joinedload(Quote.caterer),
                joinedload(Quote.quote_request).options(
                    joinedload(QuoteRequest.company),
                    joinedload(QuoteRequest.user),
                ),
            )
            .where(Quote.id == q_id)
            .where(Quote.quote_request_id == qr.id)
            # Drafts are caterer-only — refuse to serve a brouillon PDF
            # to the client even if they guess the URL. Allow-list
            # rather than `!= draft` so a future status doesn't leak by
            # default.
            .where(Quote.status.in_(_QUOTE_RECEIVED_STATUSES))
        )
        if not quote:
            abort(404)
        if len(quote.lines) > _MAX_PDF_LINES:
            abort(413)

        pdf_bytes = render_quote_pdf(quote, quote.quote_request, quote.caterer)
        logger.info(
            "quote_pdf_downloaded company_id=%s user_id=%s quote_id=%s reference=%s lines=%d",
            user.company_id,
            user.id,
            quote.id,
            quote.reference,
            len(quote.lines),
        )
        return send_file(
            BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"devis-{quote.reference}.pdf",
        )

    @bp.route("/requests/<uuid:request_id>/edit", methods=["GET"])
    @login_required
    @role_required("client_admin", "client_user")
    def request_edit(request_id):
        user = g.current_user
        db = get_db()
        qr = get_company_request(request_id, user)
        if qr.status not in (
            QuoteRequestStatus.draft,
            QuoteRequestStatus.pending_review,
        ):
            flash("Cette demande ne peut plus etre modifiee.", "error")
            return redirect(url_for("client.request_detail", request_id=request_id))

        services = (
            db.execute(
                select(CompanyService).where(
                    CompanyService.company_id == user.company_id
                )
            )
            .scalars()
            .all()
        )

        return _no_store(
            make_response(
                render_template(
                    "client/requests/edit.html",
                    user=user,
                    qr=qr,
                    services=services,
                    meal_type_options=_meal_type_options(),
                )
            )
        )

    @bp.route("/requests/<uuid:request_id>/edit", methods=["POST"])
    @login_required
    @role_required("client_admin", "client_user")
    def request_edit_post(request_id):
        user = g.current_user

        db = get_db()
        qr = get_company_request(request_id, user)
        if qr.status not in (
            QuoteRequestStatus.draft,
            QuoteRequestStatus.pending_review,
        ):
            flash("Cette demande ne peut plus etre modifiee.", "error")
            return redirect(url_for("client.request_detail", request_id=request_id))

        form = QuoteRequestForm()
        if not form.validate_on_submit():
            flash("Veuillez corriger les erreurs du formulaire.", "error")
            services = (
                db.execute(
                    select(CompanyService).where(
                        CompanyService.company_id == user.company_id
                    )
                )
                .scalars()
                .all()
            )
            response = _no_store(
                make_response(
                    render_template(
                        "client/requests/edit.html",
                        user=user,
                        qr=qr,
                        services=services,
                        meal_type_options=_meal_type_options(),
                    )
                )
            )
            response.status_code = 400
            return response

        qr.company_service_id = own_service_id(db, user, form.company_service_id.data)
        apply_quote_request_form(qr, form)

        # VULN-36: editing a request that is already awaiting admin qualification
        # MUST keep it in pending_review.
        if qr.status == QuoteRequestStatus.pending_review:
            qr.status = QuoteRequestStatus.pending_review
        else:
            qr.status = (
                QuoteRequestStatus.pending_review
                if form.is_compare_mode.data
                else QuoteRequestStatus.sent_to_caterers
            )

        db.commit()

        flash("Demande mise a jour.", "success")
        return redirect(url_for("client.request_detail", request_id=request_id))

    @bp.route("/search")
    @limiter.limit("60 per minute")
    def search():
        # Catalogue public — accessible aux visiteurs non connectés depuis
        # le bloc de recherche de la landing. Les actions qui nécessitent
        # un compte (lancer une demande, voir une fiche, accepter un
        # devis, etc.) restent gatées par leur propre `@login_required`
        # et redirigeront via le `next=` standard si on clique dessus
        # sans session.
        #
        # Per-IP rate limit (the per-blueprint default only applies to
        # POSTs): /search is now public + GET, so a scraper could
        # otherwise harvest the catalogue at high RPS. 60/min is loose
        # enough for legitimate paginated browsing, tight enough to make
        # bulk scraping inconvenient.
        page = request.args.get("page", 1, type=int)
        q = request.args.get("q", "").strip()
        location = request.args.get("location", "").strip()
        # The structure filter is a multi-select in the new UI: 0..n of
        # ("STPA", "SIAE"). Kept the legacy single-value `structure_type`
        # as fallback so existing query strings don't break.
        structure_groups = request.args.getlist("structure_type_multi")
        structure_type = request.args.get("structure_type", "")
        dietary = request.args.getlist("dietary")
        capacity = request.args.get("capacity", type=int)
        service_offerings = request.args.getlist("service_offering")
        # Validate price-band slugs against the canonical list — anything
        # we don't recognize is silently dropped to keep query strings
        # tamper-safe.
        budget_bands = [
            b for b in request.args.getlist("budget_range") if b in PRICE_BAND_BOUNDS
        ]
        service_type = request.args.get("service_type", "")

        db = get_db()
        stmt = select(Caterer).where(Caterer.is_validated.is_(True))

        # Structure filter: collapse the multi-select groups + legacy
        # single value into one IN clause.
        struct_codes: set[str] = set()
        for group in structure_groups:
            if group in STRUCTURE_GROUPS:
                struct_codes.update(STRUCTURE_GROUPS[group])
            elif group:
                struct_codes.add(group)
        if structure_type:
            if structure_type in STRUCTURE_GROUPS:
                struct_codes.update(STRUCTURE_GROUPS[structure_type])
            else:
                struct_codes.add(structure_type)
        if struct_codes:
            stmt = stmt.where(Caterer.structure_type.in_(struct_codes))

        for flag in dietary:
            col = getattr(Caterer, f"dietary_{flag}", None)
            if col is not None:
                stmt = stmt.where(col.is_(True))

        if capacity:
            stmt = stmt.where(
                or_(Caterer.capacity_max.is_(None), Caterer.capacity_max >= capacity)
            )

        if location:
            # Loose match: city OR zip_code starts with the input. Lets the
            # user type "75" to find Paris, or "Paris" to find by city name.
            loc_pattern = f"%{location}%"
            stmt = stmt.where(
                or_(
                    Caterer.city.ilike(loc_pattern),
                    Caterer.zip_code.ilike(loc_pattern),
                )
            )

        # service_offerings filter (Type de prestation): caterer matches
        # if its service_offerings JSON contains any of the requested
        # slugs. JSON-array-contains is portable enough across Postgres
        # and SQLite when expressed as a LIKE on the JSON-encoded text.
        for slug in service_offerings:
            if slug in SERVICE_OFFERING_LABELS:
                # Match the slug between quotes so "petit_dejeuner" doesn't
                # also match a hypothetical "petit_dejeuner_xyz".
                stmt = stmt.where(
                    cast(Caterer.service_offerings, String).ilike(f'%"{slug}"%')
                )

        # Budget bands (per person): the caterer's [min, max] range must
        # overlap with the requested band's bounds. Implemented per-band
        # then OR'd together so multiple bands act as a union.
        if budget_bands:
            band_clauses = []
            for band in budget_bands:
                band_min, band_max = PRICE_BAND_BOUNDS[band]
                clauses = []
                if band_min is not None:
                    # caterer's max price must reach the band floor
                    clauses.append(
                        or_(
                            Caterer.price_per_person_max.is_(None),
                            Caterer.price_per_person_max >= band_min,
                        )
                    )
                if band_max is not None:
                    # caterer's min price must be under the band ceiling
                    clauses.append(
                        or_(
                            Caterer.price_per_person_min.is_(None),
                            Caterer.price_per_person_min <= band_max,
                        )
                    )
                if clauses:
                    band_clauses.append(and_(*clauses))
            if band_clauses:
                stmt = stmt.where(or_(*band_clauses))

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

        # Hydrate review aggregates for the current page in a single
        # query — the catalogue card displays "★ 4.3 · 12 avis" per row.
        from services.reviews import (
            ReviewAggregate,
            aggregates_for_caterers,
        )

        review_aggregates = aggregates_for_caterers(db, [c.id for c in caterers])
        for c in caterers:
            agg = review_aggregates.get(c.id, ReviewAggregate(avg=None, count=0))
            c.review_avg = agg.avg
            c.review_count = agg.count

        return render_template(
            "client/search.html",
            user=g.current_user,
            caterers=caterers,
            page=page,
            total_pages=total_pages,
            total=total,
            q=q,
            location=location,
            structure_groups=structure_groups,
            structure_type=structure_type,
            dietary=dietary,
            capacity=capacity,
            service_type=service_type,
            service_offerings=service_offerings,
            budget_bands=budget_bands,
            dietary_flags=DIETARY_FLAGS,
            meal_type_labels=MEAL_TYPE_LABELS,
            service_offering_labels=SERVICE_OFFERING_LABELS,
        )

    @bp.route("/caterers/<uuid:caterer_id>")
    @limiter.limit("60 per minute")
    def caterer_detail(caterer_id):
        # Fiche traiteur publique — accessible aux visiteurs non connectés
        # qui naviguent depuis le catalogue public (cf. la route /search
        # qui a aussi perdu son @login_required). Les CTA d'action
        # (demande de devis) restent gatées par leur propre login_required
        # côté /client/requests/new.
        #
        # Per-IP rate limit for the same reason as /search above: this
        # route is now public + GET so it needs explicit throttling
        # (the per-blueprint default only catches POSTs).
        db = get_db()
        caterer = db.get(Caterer, caterer_id)
        if not caterer or not caterer.is_validated:
            abort(404)
        from services.reviews import (
            aggregate_for_caterer,
            format_author,
            list_for_caterer,
        )

        review_aggregate = aggregate_for_caterer(db, caterer.id)
        reviews = list_for_caterer(db, caterer.id, limit=50)
        return render_template(
            "client/caterer_detail.html",
            user=g.current_user,
            caterer=caterer,
            dietary_flags=DIETARY_FLAGS,
            meal_type_labels=MEAL_TYPE_LABELS,
            service_offering_labels=SERVICE_OFFERING_LABELS,
            review_aggregate=review_aggregate,
            reviews=reviews,
            review_format_author=format_author,
        )
