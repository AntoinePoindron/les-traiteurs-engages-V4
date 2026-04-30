from flask import g, render_template
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

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
                QuoteRequest.status.in_([
                    QuoteRequestStatus.draft,
                    QuoteRequestStatus.pending_review,
                    QuoteRequestStatus.sent_to_caterers,
                ]),
            )
        ).scalar_one()

        recent_orders = db.execute(
            select(Order)
            .join(Quote, Order.quote_id == Quote.id)
            .join(QuoteRequest, Quote.quote_request_id == QuoteRequest.id)
            .options(joinedload(Order.quote).joinedload(Quote.caterer))
            .where(QuoteRequest.company_id == user.company_id)
            .order_by(Order.created_at.desc())
            .limit(5)
        ).unique().scalars().all()

        recent_requests = db.execute(
            select(QuoteRequest)
            .where(QuoteRequest.company_id == user.company_id)
            .order_by(QuoteRequest.created_at.desc())
            .limit(10)
        ).scalars().all()

        services = db.execute(
            select(CompanyService).where(CompanyService.company_id == user.company_id)
        ).scalars().all()

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
            budget_data.append({
                "name": service.name,
                "budget": float(service.annual_budget or 0),
                "spent": float(spent),
            })

        return render_template(
            "client/dashboard.html",
            user=user,
            active_requests_count=active_requests_count,
            recent_orders=recent_orders,
            recent_requests=recent_requests,
            budget_data=budget_data,
            order_status_labels=ORDER_STATUS_LABELS,
            meal_type_labels=MEAL_TYPE_LABELS,
        )
