from datetime import date

from flask import g, render_template
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

from blueprints.middleware import login_required, role_required
from database import get_db
from models import (
    MEAL_TYPE_LABELS,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    QRCStatus,
    Quote,
    QuoteRequest,
    QuoteRequestCaterer,
    QuoteStatus,
)


def register(bp):
    @bp.route("/dashboard")
    @login_required
    @role_required("caterer")
    def dashboard():
        caterer = g.current_user.caterer
        db = get_db()

        new_requests_count = (
            db.scalar(
                select(func.count(QuoteRequestCaterer.id))
                .where(QuoteRequestCaterer.caterer_id == caterer.id)
                .where(QuoteRequestCaterer.status == QRCStatus.selected)
            )
            or 0
        )

        pending_quotes_count = (
            db.scalar(
                select(func.count(Quote.id))
                .where(Quote.caterer_id == caterer.id)
                .where(Quote.status == QuoteStatus.sent)
            )
            or 0
        )

        orders_in_progress_count = (
            db.scalar(
                select(func.count(Order.id))
                .join(Quote, Order.quote_id == Quote.id)
                .where(Quote.caterer_id == caterer.id)
                .where(
                    Order.status.in_(
                        [
                            OrderStatus.confirmed,
                            OrderStatus.delivered,
                            OrderStatus.invoicing,
                            OrderStatus.invoiced,
                        ]
                    )
                )
            )
            or 0
        )

        total_revenue = (
            db.scalar(
                select(func.sum(Payment.amount_to_caterer_cents))
                .join(Order, Payment.order_id == Order.id)
                .join(Quote, Order.quote_id == Quote.id)
                .where(Quote.caterer_id == caterer.id)
                .where(Payment.status == PaymentStatus.succeeded)
            )
            or 0
        )

        # Mirror the /caterer/requests list: hydrate every QRC with the
        # same `display_status` derivation + eager-load the caterer's
        # own Quote so the row badge can show "Nouvelle" / "Devis envoyé"
        # / "Commande créée" exactly like the list page.
        from blueprints.caterer.requests import _derive_qrc_display_status

        new_requests = (
            db.scalars(
                select(QuoteRequestCaterer)
                .options(
                    joinedload(QuoteRequestCaterer.quote_request).joinedload(
                        QuoteRequest.company
                    ),
                    joinedload(QuoteRequestCaterer.quote_request).selectinload(
                        QuoteRequest.caterers
                    ),
                    joinedload(QuoteRequestCaterer.quote_request).selectinload(
                        QuoteRequest.quotes
                    ),
                )
                .where(QuoteRequestCaterer.caterer_id == caterer.id)
                .where(QuoteRequestCaterer.status == QRCStatus.selected)
                .order_by(QuoteRequestCaterer.id.desc())
                .limit(5)
            )
            .unique()
            .all()
        )
        for qrc in new_requests:
            qrc.display_status = _derive_qrc_display_status(
                qrc.quote_request, caterer.id
            )

        upcoming_deliveries = (
            db.scalars(
                select(Order)
                .join(Quote, Order.quote_id == Quote.id)
                .options(
                    joinedload(Order.quote)
                    .joinedload(Quote.quote_request)
                    .joinedload(QuoteRequest.company)
                )
                .where(Quote.caterer_id == caterer.id)
                .where(Order.status == OrderStatus.confirmed)
                .where(Order.delivery_date >= date.today())
                .order_by(Order.delivery_date)
                .limit(5)
            )
            .unique()
            .all()
        )

        return render_template(
            "caterer/dashboard.html",
            user=g.current_user,
            new_requests_count=new_requests_count,
            pending_quotes_count=pending_quotes_count,
            orders_in_progress_count=orders_in_progress_count,
            total_revenue=total_revenue / 100,
            new_requests=new_requests,
            upcoming_deliveries=upcoming_deliveries,
            meal_type_labels=MEAL_TYPE_LABELS,
        )
