import datetime

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, select

from blueprints.middleware import login_required, role_required
from database import get_session
from models import (
    Caterer,
    Company,
    CompanyEmployee,
    CompanyService,
    MealType,
    Message,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    Quote,
    QuoteRequest,
    QuoteRequestCaterer,
    QuoteRequestStatus,
    QuoteStatus,
    QRCStatus,
    User,
)
from services.matching import find_matching_caterers

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/dashboard")
@login_required
@role_required("super_admin")
def dashboard():
    with get_session() as session:
        pending_requests = session.scalar(
            select(func.count(QuoteRequest.id)).where(
                QuoteRequest.status == QuoteRequestStatus.pending_review
            )
        )
        pending_caterers = session.scalar(
            select(func.count(Caterer.id)).where(Caterer.is_validated.is_(False))
        )
        active_companies = session.scalar(select(func.count(Company.id)))
        month_start = datetime.date.today().replace(day=1)
        orders_this_month = session.scalar(
            select(func.count(Order.id)).where(Order.created_at >= month_start)
        )
        recent_requests = session.scalars(
            select(QuoteRequest).order_by(QuoteRequest.created_at.desc()).limit(5)
        ).all()

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
    with get_session() as session:
        requests = session.scalars(
            select(QuoteRequest)
            .where(QuoteRequest.status == QuoteRequestStatus.pending_review)
            .order_by(QuoteRequest.created_at.desc())
        ).all()
    return render_template("admin/qualification/list.html", user=g.current_user, requests=requests)


@admin_bp.route("/qualification/<uuid:request_id>")
@login_required
@role_required("super_admin")
def qualification_detail(request_id):
    with get_session() as session:
        qr = session.get(QuoteRequest, request_id)
        if not qr:
            abort(404)
        matches = find_matching_caterers(session, qr)
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
    with get_session() as session:
        qr = session.get(QuoteRequest, request_id)
        if not qr:
            abort(404)
        matches = find_matching_caterers(session, qr)
        if not matches:
            flash("Aucun traiteur compatible trouve. Impossible d'approuver.", "error")
            return redirect(url_for("admin.qualification_detail", request_id=request_id))
        for caterer, _distance in matches:
            session.add(
                QuoteRequestCaterer(
                    quote_request_id=qr.id,
                    caterer_id=caterer.id,
                    status=QRCStatus.selected,
                )
            )
        qr.status = QuoteRequestStatus.sent_to_caterers
    flash(f"Demande approuvee et envoyee a {len(matches)} traiteur(s).", "success")
    return redirect(url_for("admin.qualification"))


@admin_bp.route("/qualification/<uuid:request_id>/reject", methods=["POST"])
@login_required
@role_required("super_admin")
def qualification_reject(request_id):
    with get_session() as session:
        qr = session.get(QuoteRequest, request_id)
        if not qr:
            abort(404)
        qr.status = QuoteRequestStatus.cancelled
        qr.message_to_caterer = request.form.get("rejection_reason", "")
    flash("Demande rejetee.", "info")
    return redirect(url_for("admin.qualification"))


@admin_bp.route("/caterers")
@login_required
@role_required("super_admin")
def caterers_list():
    with get_session() as session:
        caterers = session.scalars(select(Caterer).order_by(Caterer.name)).all()
    return render_template("admin/caterers/list.html", user=g.current_user, caterers=caterers)


@admin_bp.route("/caterers/<uuid:caterer_id>")
@login_required
@role_required("super_admin")
def caterer_detail(caterer_id):
    with get_session() as session:
        caterer = session.get(Caterer, caterer_id)
        if not caterer:
            abort(404)
    return render_template("admin/caterers/detail.html", user=g.current_user, caterer=caterer)


@admin_bp.route("/caterers/<uuid:caterer_id>/validate", methods=["POST"])
@login_required
@role_required("super_admin")
def caterer_validate(caterer_id):
    with get_session() as session:
        caterer = session.get(Caterer, caterer_id)
        if not caterer:
            abort(404)
        caterer.is_validated = True
    flash(f"Traiteur {caterer.name} valide.", "success")
    return redirect(url_for("admin.caterer_detail", caterer_id=caterer_id))


@admin_bp.route("/caterers/<uuid:caterer_id>/invalidate", methods=["POST"])
@login_required
@role_required("super_admin")
def caterer_invalidate(caterer_id):
    with get_session() as session:
        caterer = session.get(Caterer, caterer_id)
        if not caterer:
            abort(404)
        caterer.is_validated = False
    flash(f"Traiteur {caterer.name} invalide.", "info")
    return redirect(url_for("admin.caterer_detail", caterer_id=caterer_id))


@admin_bp.route("/companies")
@login_required
@role_required("super_admin")
def companies_list():
    with get_session() as session:
        companies = session.scalars(select(Company).order_by(Company.name)).all()
    return render_template("admin/companies/list.html", user=g.current_user, companies=companies)


@admin_bp.route("/companies/<uuid:company_id>")
@login_required
@role_required("super_admin")
def company_detail(company_id):
    with get_session() as session:
        company = session.get(Company, company_id)
        if not company:
            abort(404)
        employees = session.scalars(
            select(CompanyEmployee).where(CompanyEmployee.company_id == company_id)
        ).all()
        services = session.scalars(
            select(CompanyService).where(CompanyService.company_id == company_id)
        ).all()
        requests = session.scalars(
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
    with get_session() as session:
        stmt = select(Payment).order_by(Payment.created_at.desc())
        if status_filter != "all":
            stmt = stmt.where(Payment.status == status_filter)
        payment_list = session.scalars(stmt).all()

        total_revenue = session.scalar(
            select(func.coalesce(func.sum(Payment.amount_total_cents), 0)).where(
                Payment.status == PaymentStatus.succeeded
            )
        ) or 0
        total_commission = session.scalar(
            select(func.coalesce(func.sum(Payment.application_fee_cents), 0)).where(
                Payment.status == PaymentStatus.succeeded
            )
        ) or 0
        pending_count = session.scalar(
            select(func.count(Payment.id)).where(
                Payment.status.in_([PaymentStatus.pending, PaymentStatus.processing])
            )
        ) or 0

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
    with get_session() as session:
        today = datetime.date.today()
        months = []
        for i in range(11, -1, -1):
            d = today.replace(day=1) - datetime.timedelta(days=i * 30)
            month_start = d.replace(day=1)
            if month_start.month == 12:
                month_end = month_start.replace(year=month_start.year + 1, month=1)
            else:
                month_end = month_start.replace(month=month_start.month + 1)
            revenue = session.scalar(
                select(func.coalesce(func.sum(Payment.amount_total_cents), 0)).where(
                    Payment.status == PaymentStatus.succeeded,
                    Payment.created_at >= month_start,
                    Payment.created_at < month_end,
                )
            ) or 0
            months.append({
                "label": month_start.strftime("%b %Y"),
                "revenue": revenue / 100,
            })

        top_caterers_rows = session.execute(
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
            {"name": r.name, "revenue": (r.revenue or 0) / 100, "order_count": r.order_count}
            for r in top_caterers_rows
        ]

        total_requests = session.scalar(select(func.count(QuoteRequest.id))) or 0
        quotes_sent = session.scalar(
            select(func.count(Quote.id)).where(Quote.status != QuoteStatus.draft)
        ) or 0
        quotes_accepted = session.scalar(
            select(func.count(Quote.id)).where(Quote.status == QuoteStatus.accepted)
        ) or 0
        orders_paid = session.scalar(
            select(func.count(Payment.id)).where(Payment.status == PaymentStatus.succeeded)
        ) or 0

        geo_rows = session.execute(
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

        meal_rows = session.execute(
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


@admin_bp.route("/messages")
@login_required
@role_required("super_admin")
def messages():
    with get_session() as session:
        all_messages = session.scalars(
            select(Message).order_by(Message.created_at.desc())
        ).all()
        threads = {}
        for msg in all_messages:
            tid = str(msg.thread_id)
            if tid not in threads:
                sender = session.get(User, msg.sender_id)
                recipient = session.get(User, msg.recipient_id)
                threads[tid] = {
                    "thread_id": tid,
                    "sender_name": f"{sender.first_name} {sender.last_name}" if sender else "Inconnu",
                    "recipient_name": f"{recipient.first_name} {recipient.last_name}" if recipient else "Inconnu",
                    "last_message": msg.body[:80],
                    "last_at": msg.created_at,
                    "message_count": session.scalar(
                        select(func.count(Message.id)).where(Message.thread_id == msg.thread_id)
                    ),
                }
    return render_template(
        "admin/messages.html",
        user=g.current_user,
        threads=list(threads.values()),
    )
