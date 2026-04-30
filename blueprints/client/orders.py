import uuid

from flask import abort, g, render_template, url_for
from sqlalchemy import select

from blueprints.client._helpers import ORDER_STATUS_LABELS
from blueprints.middleware import login_required, role_required
from blueprints.scoping import get_company_order
from database import get_db
from models import Order, Quote, QuoteRequest


def register(bp):
    @bp.route("/orders")
    @login_required
    @role_required("client_admin", "client_user")
    def orders_list():
        user = g.current_user
        db = get_db()
        orders = db.execute(
            select(Order)
            .join(Quote, Order.quote_id == Quote.id)
            .join(QuoteRequest, Quote.quote_request_id == QuoteRequest.id)
            .where(QuoteRequest.company_id == user.company_id)
            .order_by(Order.created_at.desc())
        ).scalars().all()
        return render_template(
            "client/orders/list.html",
            user=user,
            orders=orders,
            order_status_labels=ORDER_STATUS_LABELS,
        )

    @bp.route("/orders/<uuid:order_id>")
    @login_required
    @role_required("client_admin", "client_user")
    def order_detail(order_id):
        user = g.current_user
        order = get_company_order(order_id, user.company_id)

        caterer = order.quote.caterer
        caterer_user = caterer.users[0] if caterer.users else None
        if caterer_user:
            pair = sorted([str(user.id), str(caterer_user.id)])
            thread_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{pair[0]}:{pair[1]}")
            caterer_message_href = url_for("client.message_thread", thread_id=thread_id)
        else:
            caterer_message_href = url_for("client.messages")

        return render_template(
            "client/orders/detail.html",
            user=user,
            order=order,
            order_status_labels=ORDER_STATUS_LABELS,
            caterer_message_href=caterer_message_href,
        )
