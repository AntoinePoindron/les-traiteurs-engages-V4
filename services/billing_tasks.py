"""Background tasks for Stripe billing (P3.4).

Importing this module configures the dramatiq broker. Two contexts:

1. Web app (gunicorn): just importing initializes the broker so
   `send_invoice_for_order.send(...)` enqueues to Redis.
2. Worker (`dramatiq services.billing_tasks ...`): the entrypoint
   discovers actors here and starts consuming the queue.

REDIS_URL must be set in both contexts. In tests we stub the broker.
"""
from __future__ import annotations

import logging
import os
import uuid

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.brokers.stub import StubBroker
from sqlalchemy import select

logger = logging.getLogger(__name__)


def _make_broker():
    """Real Redis broker in normal runs, in-memory stub during tests.

    Tests set DRAMATIQ_TESTING=1 in conftest so they don't need a Redis
    container; jobs are then dispatched synchronously via stub_broker.join().
    """
    if os.getenv("DRAMATIQ_TESTING") == "1":
        return StubBroker()
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        # Fail loud rather than silently lose every queued invoice.
        raise RuntimeError(
            "REDIS_URL is not set. The web process and the worker both "
            "need it. Check docker-compose.yml or .deploy.env."
        )
    return RedisBroker(url=redis_url)


broker = _make_broker()
dramatiq.set_broker(broker)


@dramatiq.actor(
    max_retries=5,
    # Exponential backoff: 30s, 1min, 2min, 4min, 8min, then dead-letter.
    # Stripe outages rarely last more than a few minutes; longer gaps leave
    # the order in `invoicing` state for the retry CLI to handle.
    min_backoff=30_000,
    max_backoff=8 * 60_000,
    # Re-raise on any exception so dramatiq's retry policy kicks in.
    throws=(),
)
def send_invoice_for_order(order_id: str) -> None:
    """Phase 2 of order delivery: actually call Stripe.

    Receives a string UUID (dramatiq serialises args as JSON, so no
    native UUID type). Open a fresh DB session — we are NOT in a Flask
    request context, `g` and `database.get_db()` are unavailable.

    The Stripe SDK call carries `idempotency_key=invoice-order-<order_id>`
    so a retry after a partial failure does not double-bill.
    """
    # Imported lazily so importing this module from the web side does not
    # transitively boot the SQLAlchemy engine before app.py is ready.
    from database import get_session
    from models import Order, OrderStatus
    from services.stripe_service import create_invoice_for_order

    oid = uuid.UUID(order_id)
    with get_session() as db:
        order = db.scalar(
            select(Order).where(Order.id == oid)
        )
        if not order:
            logger.error("send_invoice_for_order: order %s not found", oid)
            return
        if order.status not in (OrderStatus.invoicing, OrderStatus.delivered):
            # Already invoiced (race with retry CLI) or moved past; nothing to do.
            logger.info(
                "send_invoice_for_order: order %s in status %s, skipping",
                oid, order.status,
            )
            return

        try:
            create_invoice_for_order(db, order)
        except Exception:
            # create_invoice_for_order leaves order.status in `invoicing` on
            # failure. The retry CLI (and dramatiq's own retry) will pick
            # it up. Re-raise so dramatiq counts it as a failure.
            logger.exception(
                "send_invoice_for_order: Stripe call failed for order %s", oid,
            )
            raise
