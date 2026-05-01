from flask import g, render_template, request, url_for
from sqlalchemy import and_, or_, select

from blueprints.client._helpers import ORDER_STATUS_LABELS
from blueprints.middleware import login_required, role_required
from blueprints.scoping import get_company_order
from database import get_db
from models import MEAL_TYPE_LABELS, Message, Order, OrderStatus, Quote, QuoteRequest


# Filter tabs visible on /client/orders. Keys map to ?status= URL params,
# values are the labels rendered in the tab pill.
ORDER_STATUS_TABS = {
    "all": "Toutes",
    "upcoming": "À venir",
    "to_pay": "À payer",
    "paid": "Payées",
}


def _derive_order_display_status(order):
    """Collapse OrderStatus into the three buckets the client cares about.

    Returns one of: 'upcoming', 'to_pay', 'paid'. The mapping mirrors
    the labels and badge colours used in templates/components/status_badge.html.
    """
    if order.status == OrderStatus.paid:
        return "paid"
    if order.status == OrderStatus.invoiced:
        return "to_pay"
    # confirmed / delivered / invoicing / disputed all surface as
    # "À venir" — the client has nothing actionable until the invoice is
    # ready.
    return "upcoming"


def register(bp):
    @bp.route("/orders")
    @login_required
    @role_required("client_admin", "client_user")
    def orders_list():
        user = g.current_user
        db = get_db()
        status_filter = request.args.get("status") or "all"
        if status_filter not in ORDER_STATUS_TABS:
            status_filter = "all"

        orders = (
            db.execute(
                select(Order)
                .join(Quote, Order.quote_id == Quote.id)
                .join(QuoteRequest, Quote.quote_request_id == QuoteRequest.id)
                .where(QuoteRequest.company_id == user.company_id)
                .order_by(Order.created_at.desc())
            )
            .scalars()
            .all()
        )

        for order in orders:
            order.display_status = _derive_order_display_status(order)

        if status_filter != "all":
            orders = [o for o in orders if o.display_status == status_filter]

        return render_template(
            "client/orders/list.html",
            user=user,
            orders=orders,
            order_status_labels=ORDER_STATUS_LABELS,
            meal_type_labels=MEAL_TYPE_LABELS,
            status_tabs=ORDER_STATUS_TABS,
            current_tab=status_filter,
        )

    @bp.route("/orders/<uuid:order_id>")
    @login_required
    @role_required("client_admin", "client_user")
    def order_detail(order_id):
        user = g.current_user
        db = get_db()
        order = get_company_order(order_id, user.company_id)

        caterer = order.quote.caterer
        caterer_user = caterer.users[0] if caterer.users else None
        if caterer_user:
            existing_tid = db.scalar(
                select(Message.thread_id)
                .where(
                    or_(
                        and_(
                            Message.sender_id == user.id,
                            Message.recipient_id == caterer_user.id,
                        ),
                        and_(
                            Message.sender_id == caterer_user.id,
                            Message.recipient_id == user.id,
                        ),
                    )
                )
                .limit(1)
            )
            if existing_tid:
                caterer_message_href = url_for(
                    "client.message_thread", thread_id=existing_tid
                )
            else:
                caterer_message_href = url_for("client.messages")
        else:
            caterer_message_href = url_for("client.messages")

        return render_template(
            "client/orders/detail.html",
            user=user,
            order=order,
            order_status_labels=ORDER_STATUS_LABELS,
            caterer_message_href=caterer_message_href,
        )
