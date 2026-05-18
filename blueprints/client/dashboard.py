from flask import g, render_template
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

from blueprints.client._helpers import ORDER_STATUS_LABELS
from blueprints.middleware import login_required, role_required
from blueprints.scoping import own_requests_filter
from database import get_db
from models import (
    MEAL_TYPE_LABELS,
    CompanyService,
    Order,
    Quote,
    QuoteRequest,
    QuoteRequestStatus,
    QuoteStatus,
    UserRole,
)
from services.impact import compute_social_impact


def register(bp):
    @bp.route("/dashboard")
    @login_required
    @role_required("client_admin", "client_user")
    def dashboard():
        user = g.current_user
        db = get_db()
        # `own_only` is None for client_admin (sees the whole company),
        # `QR.user_id == user.id` for client_user (sees only their own).
        own_only = own_requests_filter(user)
        is_admin = user.role == UserRole.client_admin

        # KPI : demandes actives
        active_stmt = select(func.count(QuoteRequest.id)).where(
            QuoteRequest.company_id == user.company_id,
            QuoteRequest.status.in_(
                [
                    QuoteRequestStatus.draft,
                    QuoteRequestStatus.pending_review,
                    QuoteRequestStatus.sent_to_caterers,
                ]
            ),
        )
        if own_only is not None:
            active_stmt = active_stmt.where(own_only)
        active_requests_count = db.execute(active_stmt).scalar_one()

        # Last 5 commandes (scoped via the underlying QR's user_id for
        # non-admins).
        orders_stmt = (
            select(Order)
            .join(Quote, Order.quote_id == Quote.id)
            .join(QuoteRequest, Quote.quote_request_id == QuoteRequest.id)
            .options(joinedload(Order.quote).joinedload(Quote.caterer))
            .where(QuoteRequest.company_id == user.company_id)
            .order_by(Order.created_at.desc())
            .limit(5)
        )
        if own_only is not None:
            orders_stmt = orders_stmt.where(own_only)
        recent_orders = db.execute(orders_stmt).unique().scalars().all()

        # Last 5 demandes — same row format as /client/requests so the
        # dashboard and the list render identical cards. Hydrate
        # display_status + received/expected counts via the helpers in
        # requests.py; selectinload(QuoteRequest.quotes) avoids the N+1
        # the helpers would otherwise trigger.
        from blueprints.client.requests import (
            _derive_request_display_status,
            _request_quote_counts,
        )

        requests_stmt = (
            select(QuoteRequest)
            .where(QuoteRequest.company_id == user.company_id)
            .options(selectinload(QuoteRequest.quotes))
            .order_by(QuoteRequest.created_at.desc())
            .limit(5)
        )
        if own_only is not None:
            requests_stmt = requests_stmt.where(own_only)
        recent_requests = db.execute(requests_stmt).scalars().all()
        for qr in recent_requests:
            qr.display_status = _derive_request_display_status(qr)
            qr.received_quotes, qr.expected_quotes = _request_quote_counts(qr)

        # Per-service budget breakdown is a company-wide aggregate that
        # only makes sense for an admin's coordination view. For
        # client_user we hide the panel entirely (template guards on
        # `if budget_data`).
        budget_data = []
        if is_admin:
            services = (
                db.execute(
                    select(CompanyService).where(
                        CompanyService.company_id == user.company_id
                    )
                )
                .scalars()
                .all()
            )
            for service in services:
                spent = db.execute(
                    select(func.coalesce(func.sum(Quote.total_amount_ht), 0)).where(
                        Quote.quote_request_id.in_(
                            select(QuoteRequest.id).where(
                                QuoteRequest.company_service_id == service.id,
                            )
                        ),
                        Quote.status == QuoteStatus.accepted,
                    )
                ).scalar_one()
                budget_data.append(
                    {
                        "name": service.name,
                        "budget": float(service.annual_budget or 0),
                        "spent": float(spent),
                    }
                )

        # « Budget consommé » KPI : admin sees the company-wide total,
        # a client_user sees only their own contributions.
        budget_total_stmt = (
            select(func.coalesce(func.sum(Quote.total_amount_ht), 0))
            .join(QuoteRequest, Quote.quote_request_id == QuoteRequest.id)
            .where(
                QuoteRequest.company_id == user.company_id,
                Quote.status == QuoteStatus.accepted,
            )
        )
        if own_only is not None:
            budget_total_stmt = budget_total_stmt.where(own_only)
        budget_spent_total = db.execute(budget_total_stmt).scalar_one()

        # « Impact social » : montant HT réellement dépensé (orders en
        # `paid` uniquement) ventilé SIAE / STPA, plus une estimation
        # d'heures d'insertion financées. Même scoping que le KPI
        # budget : admin = entreprise complète, client_user = ses
        # propres demandes uniquement. Montants convertis en float pour
        # rester homogène avec `budget_spent_total` côté template — le
        # filtre Jinja `%f` n'aime pas les Decimal.
        impact = compute_social_impact(
            db,
            company_id=user.company_id,
            requester_user_id=None if is_admin else user.id,
        )
        social_impact = {
            "total_ht": float(impact.total_ht),
            "siae_ht": float(impact.siae_ht),
            "stpa_ht": float(impact.stpa_ht),
            "hours_financed": impact.hours_financed,
        }

        return render_template(
            "client/dashboard.html",
            user=user,
            active_requests_count=active_requests_count,
            recent_orders=recent_orders,
            recent_requests=recent_requests,
            budget_data=budget_data,
            budget_spent_total=float(budget_spent_total),
            social_impact=social_impact,
            order_status_labels=ORDER_STATUS_LABELS,
            meal_type_labels=MEAL_TYPE_LABELS,
        )
