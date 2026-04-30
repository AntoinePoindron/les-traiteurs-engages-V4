from flask import abort, flash, g, redirect, render_template, url_for
from sqlalchemy import select

from blueprints.middleware import login_required, role_required
from database import get_db
from models import Order, OrderStatus, Quote
from services import workflow


def register(bp):
    @bp.route("/orders")
    @login_required
    @role_required("caterer")
    def orders_list():
        caterer = g.current_user.caterer
        db = get_db()
        orders = db.scalars(
            select(Order)
            .join(Quote, Order.quote_id == Quote.id)
            .where(Quote.caterer_id == caterer.id)
            .order_by(Order.created_at.desc())
        ).all()
        for o in orders:
            _ = o.quote
            _ = o.quote.quote_request
        return render_template("caterer/orders/list.html", user=g.current_user, orders=orders)

    @bp.route("/orders/<uuid:order_id>")
    @login_required
    @role_required("caterer")
    def order_detail(order_id):
        caterer = g.current_user.caterer
        db = get_db()
        order = db.scalar(
            select(Order)
            .join(Quote, Order.quote_id == Quote.id)
            .where(Order.id == order_id)
            .where(Quote.caterer_id == caterer.id)
        )
        if not order:
            abort(404)
        _ = order.quote
        _ = order.quote.quote_request
        _ = order.quote.quote_request.company
        _ = order.payments
        return render_template("caterer/orders/detail.html", user=g.current_user, order=order)

    @bp.route("/orders/<uuid:order_id>/deliver", methods=["POST"])
    @login_required
    @role_required("caterer")
    def order_deliver(order_id):
        caterer = g.current_user.caterer
        db = get_db()
        try:
            order = workflow.mark_delivered(db, order_id=order_id, caterer=caterer)
        except workflow.OrderNotFound:
            abort(404)

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
