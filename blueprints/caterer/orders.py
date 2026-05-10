from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from blueprints.middleware import login_required, role_required
from blueprints.scoping import get_caterer_order
from database import get_db
from extensions import limiter
from models import MEAL_TYPE_LABELS, Order, OrderStatus, Quote, QuoteRequest
from services import workflow
from services.quotes import build_pdf_preview


# Filter tabs visible on /caterer/orders. Keys map to ?status= URL params,
# values are the labels rendered in the tab pill.
ORDER_STATUS_TABS = {
    "all": "Toutes",
    "upcoming": "À venir",
    "delivered": "Livrées",
    "invoiced": "Facturées",
    "paid": "Payées",
    "disputed": "Litige",
}


# "invoiced" tab covers both `invoicing` (Stripe call in flight) and `invoiced`
# (invoice issued) — the caterer experiences them as the same stage.
_TAB_TO_STATUSES = {
    "upcoming": (OrderStatus.confirmed,),
    "delivered": (OrderStatus.delivered,),
    "invoiced": (OrderStatus.invoicing, OrderStatus.invoiced),
    "paid": (OrderStatus.paid,),
    "disputed": (OrderStatus.disputed,),
}


def register(bp):
    @bp.route("/orders")
    @login_required
    @role_required("caterer")
    def orders_list():
        caterer = g.current_user.caterer
        db = get_db()
        status_filter = request.args.get("status") or "all"
        if status_filter not in ORDER_STATUS_TABS:
            status_filter = "all"

        stmt = (
            select(Order)
            .join(Quote, Order.quote_id == Quote.id)
            .where(Quote.caterer_id == caterer.id)
            .order_by(Order.created_at.desc())
        )
        if status_filter != "all":
            stmt = stmt.where(Order.status.in_(_TAB_TO_STATUSES[status_filter]))

        orders = db.scalars(stmt).all()
        for o in orders:
            _ = o.quote
            _ = o.quote.quote_request
        return render_template(
            "caterer/orders/list.html",
            user=g.current_user,
            orders=orders,
            status_tabs=ORDER_STATUS_TABS,
            current_tab=status_filter,
        )

    @bp.route("/orders/<uuid:order_id>")
    @login_required
    @role_required("caterer")
    def order_detail(order_id):
        caterer = g.current_user.caterer
        order = get_caterer_order(
            order_id,
            caterer.id,
            options=[
                joinedload(Order.quote).options(
                    selectinload(Quote.lines),
                    joinedload(Quote.caterer),
                    joinedload(Quote.quote_request).options(
                        joinedload(QuoteRequest.company),
                        joinedload(QuoteRequest.user),
                    ),
                ),
                selectinload(Order.payments),
            ],
        )
        pdf_preview = (
            build_pdf_preview(
                order.quote, order.quote.quote_request, order.quote.caterer
            )
            if order.quote.lines
            else None
        )
        return render_template(
            "caterer/orders/detail.html",
            user=g.current_user,
            order=order,
            pdf_preview=pdf_preview,
            meal_type_labels=MEAL_TYPE_LABELS,
        )

    @bp.route("/orders/<uuid:order_id>/deliver", methods=["POST"])
    @limiter.limit("10 per minute")
    @login_required
    @role_required("caterer")
    def order_deliver(order_id):
        caterer = g.current_user.caterer
        db = get_db()
        try:
            order = workflow.mark_delivered(db, order_id=order_id, caterer=caterer)
        except workflow.OrderNotFound:
            # `mark_delivered` raises OrderNotFound for two cases: the
            # order genuinely doesn't exist (or doesn't belong to this
            # caterer) → real 404; or it's already past `confirmed`
            # (typical replay: 2nd click, browser back+resubmit, stale
            # tab) → flash + redirect, not an error.
            existing = db.scalar(
                select(Order)
                .join(Quote, Order.quote_id == Quote.id)
                .where(Order.id == order_id, Quote.caterer_id == caterer.id)
            )
            if existing is None:
                abort(404)
            flash("Cette commande a deja ete marquee comme livree.", "info")
            return redirect(url_for("caterer.order_detail", order_id=order_id))

        if caterer.stripe_account_id and caterer.stripe_charges_enabled:
            order.status = OrderStatus.invoicing
            db.commit()
            from services.billing_tasks import send_invoice_for_order

            send_invoice_for_order.send(order_id=str(order.id))
            flash(
                "Commande livree. La facture Stripe est en cours de generation.",
                "success",
            )
        else:
            db.commit()
            flash("Commande marquee comme livree.", "success")
        return redirect(url_for("caterer.order_detail", order_id=order_id))
