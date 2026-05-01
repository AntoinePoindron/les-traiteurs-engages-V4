import datetime

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import func, select, update
from sqlalchemy.orm import joinedload

from blueprints.middleware import login_required, role_required
from database import get_db
from forms.caterer import RejectionForm
from models import (
    Caterer,
    Company,
    CompanyEmployee,
    CompanyService,
    Message,
    Notification,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    Quote,
    QuoteRequest,
    QuoteRequestStatus,
    QuoteStatus,
    User,
)
from services import workflow
from services.audit import log_admin_action
from services.notifications import (
    caterer_user_ids,
    company_admin_user_ids,
    notification_target_url,
    notify_users,
)
from services.matching import find_matching_caterers

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/dashboard")
@login_required
@role_required("super_admin")
def dashboard():
    db = get_db()
    pending_requests = db.scalar(
        select(func.count(QuoteRequest.id)).where(
            QuoteRequest.status == QuoteRequestStatus.pending_review
        )
    )
    pending_caterers = db.scalar(
        select(func.count(Caterer.id)).where(Caterer.is_validated.is_(False))
    )
    active_companies = db.scalar(select(func.count(Company.id)))
    month_start = datetime.date.today().replace(day=1)
    orders_this_month = db.scalar(
        select(func.count(Order.id)).where(Order.created_at >= month_start)
    )
    recent_requests = (
        db.scalars(
            select(QuoteRequest)
            .options(joinedload(QuoteRequest.company))
            .order_by(QuoteRequest.created_at.desc())
            .limit(5)
        )
        .unique()
        .all()
    )

    return render_template(
        "admin/dashboard.html",
        user=g.current_user,
        pending_requests=pending_requests or 0,
        pending_caterers=pending_caterers or 0,
        active_companies=active_companies or 0,
        orders_this_month=orders_this_month or 0,
        recent_requests=recent_requests,
    )


@admin_bp.route("/qualification")
@login_required
@role_required("super_admin")
def qualification():
    db = get_db()
    requests = db.scalars(
        select(QuoteRequest)
        .where(QuoteRequest.status == QuoteRequestStatus.pending_review)
        .order_by(QuoteRequest.created_at.desc())
    ).all()
    return render_template(
        "admin/qualification/list.html", user=g.current_user, requests=requests
    )


@admin_bp.route("/qualification/<uuid:request_id>")
@login_required
@role_required("super_admin")
def qualification_detail(request_id):
    db = get_db()
    qr = db.get(QuoteRequest, request_id)
    if not qr:
        abort(404)
    matches = find_matching_caterers(db, qr)
    return render_template(
        "admin/qualification/detail.html",
        user=g.current_user,
        qr=qr,
        matches=matches,
    )


@admin_bp.route("/qualification/<uuid:request_id>/approve", methods=["POST"])
@login_required
@role_required("super_admin")
def qualification_approve(request_id):
    db = get_db()
    try:
        qrcs = workflow.approve_quote_request(db, request_id=request_id)
    except workflow.RequestNotFound:
        abort(404)
    except workflow.NoMatchingCaterers:
        flash("Aucun traiteur compatible trouve. Impossible d'approuver.", "error")
        return redirect(url_for("admin.qualification_detail", request_id=request_id))
    log_admin_action(
        db,
        g.current_user,
        "quote_request.approve",
        target_type="quote_request",
        target_id=request_id,
        extra={"matched_caterers": len(qrcs)},
    )
    db.commit()
    flash(f"Demande approuvee et envoyee a {len(qrcs)} traiteur(s).", "success")
    return redirect(url_for("admin.qualification"))


@admin_bp.route("/qualification/<uuid:request_id>/reject", methods=["POST"])
@login_required
@role_required("super_admin")
def qualification_reject(request_id):
    form = RejectionForm()
    if not form.validate_on_submit():
        flash("Veuillez corriger les erreurs du formulaire.", "error")
        return redirect(url_for("admin.qualification_detail", request_id=request_id))
    db = get_db()
    try:
        workflow.reject_quote_request(
            db,
            request_id=request_id,
            reason=form.rejection_reason.data,
        )
    except workflow.RequestNotFound:
        abort(404)
    log_admin_action(
        db,
        g.current_user,
        "quote_request.reject",
        target_type="quote_request",
        target_id=request_id,
        extra={"reason": form.rejection_reason.data},
    )
    db.commit()
    flash("Demande rejetee.", "info")
    return redirect(url_for("admin.qualification"))


@admin_bp.route("/caterers")
@login_required
@role_required("super_admin")
def caterers_list():
    db = get_db()
    caterers = db.scalars(select(Caterer).order_by(Caterer.name)).all()
    return render_template(
        "admin/caterers/list.html", user=g.current_user, caterers=caterers
    )


@admin_bp.route("/caterers/<uuid:caterer_id>")
@login_required
@role_required("super_admin")
def caterer_detail(caterer_id):
    db = get_db()
    caterer = db.get(Caterer, caterer_id)
    if not caterer:
        abort(404)
    return render_template(
        "admin/caterers/detail.html", user=g.current_user, caterer=caterer
    )


@admin_bp.route("/caterers/<uuid:caterer_id>/validate", methods=["POST"])
@login_required
@role_required("super_admin")
def caterer_validate(caterer_id):
    db = get_db()
    caterer = db.get(Caterer, caterer_id)
    if not caterer:
        abort(404)
    caterer.is_validated = True
    log_admin_action(
        db,
        g.current_user,
        "caterer.validate",
        target_type="caterer",
        target_id=caterer_id,
        extra={"caterer_name": caterer.name},
    )
    db.commit()
    flash(f"Traiteur {caterer.name} valide.", "success")
    return redirect(url_for("admin.caterer_detail", caterer_id=caterer_id))


@admin_bp.route("/caterers/<uuid:caterer_id>/invalidate", methods=["POST"])
@login_required
@role_required("super_admin")
def caterer_invalidate(caterer_id):
    db = get_db()
    caterer = db.get(Caterer, caterer_id)
    if not caterer:
        abort(404)
    caterer.is_validated = False
    log_admin_action(
        db,
        g.current_user,
        "caterer.invalidate",
        target_type="caterer",
        target_id=caterer_id,
        extra={"caterer_name": caterer.name},
    )
    db.commit()
    flash(f"Traiteur {caterer.name} invalide.", "info")
    return redirect(url_for("admin.caterer_detail", caterer_id=caterer_id))


@admin_bp.route("/companies")
@login_required
@role_required("super_admin")
def companies_list():
    db = get_db()
    companies = db.scalars(select(Company).order_by(Company.name)).all()
    return render_template(
        "admin/companies/list.html", user=g.current_user, companies=companies
    )


@admin_bp.route("/companies/<uuid:company_id>")
@login_required
@role_required("super_admin")
def company_detail(company_id):
    db = get_db()
    company = db.get(Company, company_id)
    if not company:
        abort(404)
    employees = db.scalars(
        select(CompanyEmployee).where(CompanyEmployee.company_id == company_id)
    ).all()
    services = db.scalars(
        select(CompanyService).where(CompanyService.company_id == company_id)
    ).all()
    requests = db.scalars(
        select(QuoteRequest)
        .where(QuoteRequest.company_id == company_id)
        .order_by(QuoteRequest.created_at.desc())
    ).all()
    return render_template(
        "admin/companies/detail.html",
        user=g.current_user,
        company=company,
        employees=employees,
        services=services,
        requests=requests,
    )


@admin_bp.route("/payments")
@login_required
@role_required("super_admin")
def payments():
    status_filter = request.args.get("status", "all")
    db = get_db()
    stmt = select(Payment).order_by(Payment.created_at.desc())
    if status_filter != "all":
        try:
            status_enum = PaymentStatus(status_filter)
        except ValueError:
            status_filter = "all"
        else:
            stmt = stmt.where(Payment.status == status_enum)
    payment_list = db.scalars(stmt).all()

    total_revenue = (
        db.scalar(
            select(func.coalesce(func.sum(Payment.amount_total_cents), 0)).where(
                Payment.status == PaymentStatus.succeeded
            )
        )
        or 0
    )
    total_commission = (
        db.scalar(
            select(func.coalesce(func.sum(Payment.application_fee_cents), 0)).where(
                Payment.status == PaymentStatus.succeeded
            )
        )
        or 0
    )
    pending_count = (
        db.scalar(
            select(func.count(Payment.id)).where(
                Payment.status.in_([PaymentStatus.pending, PaymentStatus.processing])
            )
        )
        or 0
    )

    return render_template(
        "admin/payments.html",
        user=g.current_user,
        payments=payment_list,
        total_revenue=total_revenue,
        total_commission=total_commission,
        pending_count=pending_count,
        current_status=status_filter,
    )


@admin_bp.route("/stats")
@login_required
@role_required("super_admin")
def stats():
    db = get_db()
    today = datetime.date.today()
    months = []
    for i in range(11, -1, -1):
        d = today.replace(day=1) - datetime.timedelta(days=i * 30)
        month_start = d.replace(day=1)
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1)
        revenue = (
            db.scalar(
                select(func.coalesce(func.sum(Payment.amount_total_cents), 0)).where(
                    Payment.status == PaymentStatus.succeeded,
                    Payment.created_at >= month_start,
                    Payment.created_at < month_end,
                )
            )
            or 0
        )
        months.append(
            {
                "label": month_start.strftime("%b %Y"),
                "revenue": revenue / 100,
            }
        )

    top_caterers_rows = db.execute(
        select(
            Caterer.name,
            func.sum(Payment.amount_total_cents).label("revenue"),
            func.count(Payment.id).label("order_count"),
        )
        .join(Caterer, Payment.caterer_id == Caterer.id)
        .where(Payment.status == PaymentStatus.succeeded)
        .group_by(Caterer.id, Caterer.name)
        .order_by(func.sum(Payment.amount_total_cents).desc())
        .limit(5)
    ).all()
    top_caterers = [
        {
            "name": r.name,
            "revenue": (r.revenue or 0) / 100,
            "order_count": r.order_count,
        }
        for r in top_caterers_rows
    ]

    total_requests = db.scalar(select(func.count(QuoteRequest.id))) or 0
    quotes_sent = (
        db.scalar(select(func.count(Quote.id)).where(Quote.status != QuoteStatus.draft))
        or 0
    )
    quotes_accepted = (
        db.scalar(
            select(func.count(Quote.id)).where(Quote.status == QuoteStatus.accepted)
        )
        or 0
    )
    orders_paid = (
        db.scalar(
            select(func.count(Payment.id)).where(
                Payment.status == PaymentStatus.succeeded
            )
        )
        or 0
    )

    geo_rows = db.execute(
        select(
            QuoteRequest.event_city,
            func.count(QuoteRequest.id).label("cnt"),
        )
        .where(QuoteRequest.event_city.isnot(None))
        .group_by(QuoteRequest.event_city)
        .order_by(func.count(QuoteRequest.id).desc())
        .limit(10)
    ).all()
    geo_data = [{"city": r.event_city, "count": r.cnt} for r in geo_rows]

    meal_rows = db.execute(
        select(
            QuoteRequest.meal_type,
            func.count(QuoteRequest.id).label("cnt"),
        )
        .where(QuoteRequest.meal_type.isnot(None))
        .group_by(QuoteRequest.meal_type)
        .order_by(func.count(QuoteRequest.id).desc())
    ).all()
    meal_labels = {
        "dejeuner": "Dejeuner",
        "diner": "Diner",
        "cocktail": "Cocktail",
        "petit_dejeuner": "Petit-dejeuner",
        "autre": "Autre",
    }
    meal_data = [
        {"type": meal_labels.get(r.meal_type, r.meal_type), "count": r.cnt}
        for r in meal_rows
    ]

    return render_template(
        "admin/stats.html",
        user=g.current_user,
        months=months,
        top_caterers=top_caterers,
        funnel={
            "requests": total_requests,
            "quotes_sent": quotes_sent,
            "quotes_accepted": quotes_accepted,
            "orders_paid": orders_paid,
        },
        geo_data=geo_data,
        meal_data=meal_data,
    )


ORDER_STATUS_TABS = {
    "all": "Toutes",
    "upcoming": "À venir",
    "delivered": "Livrées",
    "invoiced": "Facturées",
    "paid": "Payées",
    "disputed": "Litige",
}

_TAB_TO_STATUSES = {
    "upcoming": (OrderStatus.confirmed,),
    "delivered": (OrderStatus.delivered,),
    "invoiced": (OrderStatus.invoicing, OrderStatus.invoiced),
    "paid": (OrderStatus.paid,),
    "disputed": (OrderStatus.disputed,),
}

# Manual transitions the super-admin can apply from the order detail page.
# Each move requires the order's current status to match the source.
_ADMIN_ORDER_TRANSITIONS = {
    "invoice": (OrderStatus.delivered, OrderStatus.invoiced),
    "pay": (OrderStatus.invoiced, OrderStatus.paid),
}


@admin_bp.route("/orders")
@login_required
@role_required("super_admin")
def orders_list():
    db = get_db()
    status_filter = request.args.get("status") or "all"
    if status_filter not in ORDER_STATUS_TABS:
        status_filter = "all"

    stmt = (
        select(Order)
        .options(
            joinedload(Order.quote)
            .joinedload(Quote.quote_request)
            .joinedload(QuoteRequest.company),
            joinedload(Order.quote).joinedload(Quote.caterer),
        )
        .order_by(Order.created_at.desc())
    )
    if status_filter != "all":
        stmt = stmt.where(Order.status.in_(_TAB_TO_STATUSES[status_filter]))

    orders = db.scalars(stmt).unique().all()
    return render_template(
        "admin/orders/list.html",
        user=g.current_user,
        orders=orders,
        status_tabs=ORDER_STATUS_TABS,
        current_tab=status_filter,
    )


@admin_bp.route("/orders/<uuid:order_id>")
@login_required
@role_required("super_admin")
def order_detail(order_id):
    db = get_db()
    order = db.get(Order, order_id)
    if not order:
        abort(404)
    _ = order.quote
    _ = order.quote.quote_request
    _ = order.quote.quote_request.company
    _ = order.quote.caterer
    _ = order.payments
    return render_template(
        "admin/orders/detail.html",
        user=g.current_user,
        order=order,
    )


@admin_bp.route("/orders/<uuid:order_id>/transition", methods=["POST"])
@login_required
@role_required("super_admin")
def order_transition(order_id):
    action = request.form.get("action")
    if action not in _ADMIN_ORDER_TRANSITIONS:
        abort(400)
    expected, target = _ADMIN_ORDER_TRANSITIONS[action]

    db = get_db()
    order = db.get(Order, order_id)
    if not order:
        abort(404)

    if order.status != expected:
        flash(
            f"Transition impossible : la commande est en statut {order.status.value}.",
            "error",
        )
        return redirect(url_for("admin.order_detail", order_id=order_id))

    previous = (
        OrderStatus(order.status) if isinstance(order.status, str) else order.status
    )
    order.status = target
    log_admin_action(
        db,
        g.current_user,
        f"order.{action}",
        target_type="order",
        target_id=order_id,
        extra={"from": previous.value, "to": target.value},
    )

    # Both sides of the order want to know about the transition. The
    # body wording is per-action so the notification reads sensibly
    # without exposing the raw status enum.
    qr = order.quote.quote_request
    caterer_id = order.quote.caterer_id
    if action == "invoice":
        client_title = "Facture disponible"
        client_body = "Votre facture est prête. Vous pouvez la consulter depuis le détail de la commande."
        caterer_title = "Commande facturée"
        caterer_body = "La commande a été facturée par notre équipe."
    elif action == "pay":
        client_title = "Paiement reçu"
        client_body = "Le paiement de votre commande a été enregistré. Merci !"
        caterer_title = "Paiement reçu"
        caterer_body = "Le paiement de la commande a été enregistré et sera viré sous peu."
    else:
        client_title = caterer_title = f"Commande passée en {target.value}"
        client_body = caterer_body = ""

    notify_users(
        db,
        company_admin_user_ids(db, qr.company_id),
        type=f"order_{action}",
        title=client_title,
        body=client_body,
        related_entity_type="order",
        related_entity_id=order_id,
    )
    notify_users(
        db,
        caterer_user_ids(db, caterer_id),
        type=f"order_{action}",
        title=caterer_title,
        body=caterer_body,
        related_entity_type="order",
        related_entity_id=order_id,
    )

    db.commit()
    flash(f"Commande passée en {target.value}.", "success")
    return redirect(url_for("admin.order_detail", order_id=order_id))


_MESSAGES_PAGE_SIZE = 25


@admin_bp.route("/messages")
@login_required
@role_required("super_admin")
def messages():
    """Paginated thread overview. VULN-21: replaces a load-all-then-N+1
    implementation that OOM'd past a few thousand messages.

    Three queries total regardless of dataset size:
      1. Aggregate per thread (count + last_at), paginated.
      2. Fetch the latest Message per thread via PostgreSQL DISTINCT ON.
      3. Bulk-fetch the involved Users.
    """
    db = get_db()
    page = max(1, request.args.get("page", 1, type=int) or 1)

    total_threads = db.scalar(select(func.count(func.distinct(Message.thread_id)))) or 0
    total_pages = (total_threads + _MESSAGES_PAGE_SIZE - 1) // _MESSAGES_PAGE_SIZE

    # 1. Per-thread aggregates, paginated by last activity.
    summaries = db.execute(
        select(
            Message.thread_id.label("thread_id"),
            func.count(Message.id).label("message_count"),
            func.max(Message.created_at).label("last_at"),
        )
        .group_by(Message.thread_id)
        .order_by(func.max(Message.created_at).desc())
        .limit(_MESSAGES_PAGE_SIZE)
        .offset((page - 1) * _MESSAGES_PAGE_SIZE)
    ).all()

    if not summaries:
        return render_template(
            "admin/messages.html",
            user=g.current_user,
            threads=[],
            page=page,
            total_pages=total_pages,
            total=total_threads,
        )

    thread_ids = [s.thread_id for s in summaries]
    count_by_thread = {s.thread_id: s.message_count for s in summaries}

    # 2. Last message per paginated thread. PostgreSQL-specific DISTINCT ON
    # picks the row with the greatest created_at per thread in one pass.
    last_messages = (
        db.execute(
            select(Message)
            .where(Message.thread_id.in_(thread_ids))
            .order_by(Message.thread_id, Message.created_at.desc())
            .distinct(Message.thread_id)
        )
        .scalars()
        .all()
    )
    last_by_thread = {m.thread_id: m for m in last_messages}

    # 3. Bulk-fetch every user referenced by the paginated last messages.
    user_ids = set()
    for msg in last_messages:
        user_ids.add(msg.sender_id)
        user_ids.add(msg.recipient_id)
    users = (
        {
            u.id: u
            for u in db.execute(select(User).where(User.id.in_(user_ids)))
            .scalars()
            .all()
        }
        if user_ids
        else {}
    )

    threads = []
    for tid in thread_ids:  # preserves the ORDER BY last_at DESC
        msg = last_by_thread.get(tid)
        if not msg:
            continue
        sender = users.get(msg.sender_id)
        recipient = users.get(msg.recipient_id)
        threads.append(
            {
                "thread_id": str(tid),
                "sender_name": f"{sender.first_name} {sender.last_name}"
                if sender
                else "Inconnu",
                "recipient_name": f"{recipient.first_name} {recipient.last_name}"
                if recipient
                else "Inconnu",
                "last_message": (msg.body or "")[:80],
                "last_at": msg.created_at,
                "message_count": count_by_thread.get(tid, 0),
            }
        )

    return render_template(
        "admin/messages.html",
        user=g.current_user,
        threads=threads,
        page=page,
        total_pages=total_pages,
        total=total_threads,
    )


@admin_bp.route("/notifications")
@login_required
@role_required("super_admin")
def notifications():
    user = g.current_user
    db = get_db()
    notes = db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(100)
    ).all()
    unread_count = sum(1 for n in notes if not n.is_read)
    return render_template(
        "notifications/list.html",
        user=user,
        notes=notes,
        unread_count=unread_count,
        mark_all_endpoint="admin.notifications_mark_all_read",
        read_one_endpoint="admin.notifications_read_one",
    )


@admin_bp.route("/notifications/<uuid:notification_id>/read", methods=["POST"])
@login_required
@role_required("super_admin")
def notifications_read_one(notification_id):
    user = g.current_user
    db = get_db()
    note = db.get(Notification, notification_id)
    if note and note.user_id == user.id:
        note.is_read = True
        db.commit()
    return redirect(url_for("admin.notifications"))


@admin_bp.route("/notifications/<uuid:notification_id>/visit", methods=["POST"])
@login_required
@role_required("super_admin")
def notifications_visit(notification_id):
    user = g.current_user
    db = get_db()
    note = db.get(Notification, notification_id)
    target = url_for("admin.notifications")
    if note and note.user_id == user.id:
        resolved = notification_target_url(note, user.role)
        if resolved:
            target = resolved
        note.is_read = True
        db.commit()
    return redirect(target)


@admin_bp.route("/notifications/mark-all-read", methods=["POST"])
@login_required
@role_required("super_admin")
def notifications_mark_all_read():
    user = g.current_user
    db = get_db()
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    db.commit()
    flash("Toutes les notifications sont marquées comme lues.", "info")
    return redirect(url_for("admin.notifications"))
