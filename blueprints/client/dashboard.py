from flask import g, render_template
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

from blueprints.client._helpers import ORDER_STATUS_LABELS
from blueprints.middleware import login_required, role_required
from database import get_db
from models import (
    MEAL_TYPE_LABELS,
    CompanyService,
    Order,
    Quote,
    QuoteRequest,
    QuoteRequestStatus,
    QuoteStatus,
)


def register(bp):
    @bp.route("/dashboard")
    @login_required
    @role_required("client_admin", "client_user")
    def dashboard():
        user = g.current_user
        db = get_db()
        active_requests_count = db.execute(
            select(func.count(QuoteRequest.id)).where(
                QuoteRequest.company_id == user.company_id,
                QuoteRequest.status.in_(
                    [
                        QuoteRequestStatus.draft,
                        QuoteRequestStatus.pending_review,
                        QuoteRequestStatus.sent_to_caterers,
                    ]
                ),
            )
        ).scalar_one()

        recent_orders = (
            db.execute(
                select(Order)
                .join(Quote, Order.quote_id == Quote.id)
                .join(QuoteRequest, Quote.quote_request_id == QuoteRequest.id)
                .options(joinedload(Order.quote).joinedload(Quote.caterer))
                .where(QuoteRequest.company_id == user.company_id)
                .order_by(Order.created_at.desc())
                .limit(5)
            )
            .unique()
            .scalars()
            .all()
        )

        # Same row format as /client/requests — hydrate display_status +
        # received/expected quote counts via the helpers in requests.py
        # so the dashboard and the full list render identical cards.
        # selectinload(QuoteRequest.quotes) avoids the N+1 the helpers
        # would otherwise trigger.
        from blueprints.client.requests import (
            _derive_request_display_status,
            _request_quote_counts,
        )

        recent_requests = (
            db.execute(
                select(QuoteRequest)
                .where(QuoteRequest.company_id == user.company_id)
                .options(selectinload(QuoteRequest.quotes))
                .order_by(QuoteRequest.created_at.desc())
                .limit(5)
            )
            .scalars()
            .all()
        )
        for qr in recent_requests:
            qr.display_status = _derive_request_display_status(qr)
            qr.received_quotes, qr.expected_quotes = _request_quote_counts(qr)

        services = (
            db.execute(
                select(CompanyService).where(
                    CompanyService.company_id == user.company_id
                )
            )
            .scalars()
            .all()
        )

        budget_data = []
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

        # Company-wide consumed budget = sum of accepted-quote totals across
        # every service. Surfaced as a top KPI on the dashboard.
        budget_spent_total = db.execute(
            select(func.coalesce(func.sum(Quote.total_amount_ht), 0))
            .join(QuoteRequest, Quote.quote_request_id == QuoteRequest.id)
            .where(
                QuoteRequest.company_id == user.company_id,
                Quote.status == QuoteStatus.accepted,
            )
        ).scalar_one()

        return render_template(
            "client/dashboard.html",
            user=user,
            active_requests_count=active_requests_count,
            recent_orders=recent_orders,
            recent_requests=recent_requests,
            budget_data=budget_data,
            budget_spent_total=float(budget_spent_total),
            order_status_labels=ORDER_STATUS_LABELS,
            meal_type_labels=MEAL_TYPE_LABELS,
        )
