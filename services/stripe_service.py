"""Stripe Connect integration via the official `stripe` SDK.

The SDK handles HTTP, retries, idempotency, webhook signature verification
(with timestamp tolerance), and stays in sync with Stripe API changes.

Compared to the previous hand-rolled `_stripe_request`/`verify_webhook_signature`
this module is ~150 LOC shorter and closes audit Vuln 5 (no replay-attack
tolerance) by using `stripe.Webhook.construct_event` which enforces a
timestamp window by default.
"""
import math
from typing import Any

import stripe

import config
from models import (
    Caterer,
    CommissionInvoice,
    Invoice,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
)
from services.quotes import derive_invoice_reference

# Pin the API version so Stripe-side changes don't silently change behavior.
# Bump deliberately after testing each new version.
STRIPE_API_VERSION = "2024-12-18.acacia"

if config.STRIPE_SECRET_KEY:
    stripe.api_key = config.STRIPE_SECRET_KEY
    stripe.api_version = STRIPE_API_VERSION


def create_connect_account(caterer: Caterer) -> dict[str, Any]:
    """Create a Stripe Connect Express account for a caterer."""
    user = caterer.users[0] if caterer.users else None
    email = user.email if user else None
    account = stripe.Account.create(
        type="express",
        country="FR",
        email=email,
        business_type="company",
        capabilities={
            "card_payments": {"requested": True},
            "transfers": {"requested": True},
        },
        metadata={"caterer_id": str(caterer.id)},
        idempotency_key=f"caterer-account-{caterer.id}",
    )
    return account


def create_account_link(account_id: str, refresh_url: str, return_url: str) -> str:
    """Create a Stripe account onboarding link."""
    link = stripe.AccountLink.create(
        account=account_id,
        refresh_url=refresh_url,
        return_url=return_url,
        type="account_onboarding",
    )
    return link.url


def get_account(account_id: str) -> dict[str, bool]:
    """Fetch Stripe account status."""
    account = stripe.Account.retrieve(account_id)
    return {
        "charges_enabled": bool(account.get("charges_enabled", False)),
        "payouts_enabled": bool(account.get("payouts_enabled", False)),
    }


def get_or_create_customer(session, user) -> str:
    """Return existing Stripe customer ID or create one."""
    if user.stripe_customer_id:
        return user.stripe_customer_id
    customer = stripe.Customer.create(
        email=user.email,
        name=f"{user.first_name} {user.last_name}",
        metadata={"user_id": str(user.id)},
        idempotency_key=f"customer-user-{user.id}",
    )
    user.stripe_customer_id = customer.id
    session.add(user)
    return customer.id


def _create_or_get_tax_rate(percentage: float, description: str) -> str:
    """Find or create a Stripe TaxRate matching the given percentage.

    The previous in-process cache (`_tax_rate_cache`) was per-worker and would
    create duplicate TaxRates on each worker restart. We now query Stripe for
    an existing matching rate and only create one if absent.
    """
    pct_str = str(percentage)
    existing = stripe.TaxRate.list(active=True, limit=100)
    for rate in existing.auto_paging_iter():
        if str(rate.percentage) == pct_str and rate.country == "FR":
            return rate.id
    new_rate = stripe.TaxRate.create(
        display_name="TVA",
        description=description,
        percentage=pct_str,
        inclusive=False,
        country="FR",
        jurisdiction="FR",
    )
    return new_rate.id


def create_invoice_for_order(session, order: Order) -> dict[str, Any]:
    """Generate and send a Stripe invoice for a delivered order."""
    quote = order.quote
    caterer = quote.caterer
    client_user = order.client_admin
    details = quote.details or {}
    totals = details.get("totals", {})
    lines = details.get("lines", [])

    customer_id = get_or_create_customer(session, client_user)

    platform_fee_ht = totals.get("platform_fee_ht", 0)
    platform_fee_tva = totals.get("platform_fee_tva", 0)
    platform_fee_ttc_cents = math.ceil((platform_fee_ht + platform_fee_tva) * 100)

    invoice_ref = derive_invoice_reference(quote.reference)

    invoice = stripe.Invoice.create(
        customer=customer_id,
        collection_method="send_invoice",
        days_until_due=30,
        transfer_data={"destination": caterer.stripe_account_id},
        application_fee_amount=platform_fee_ttc_cents,
        metadata={
            "order_id": str(order.id),
            "invoice_reference": invoice_ref,
        },
        custom_fields=[
            {"name": "Traiteur", "value": caterer.name},
            {"name": "SIRET", "value": caterer.siret or ""},
        ],
        idempotency_key=f"invoice-order-{order.id}",
    )

    tva_grouped: dict[str, dict] = {}
    for line in lines:
        tva_rate = str(line.get("tva_rate", 10))
        if tva_rate not in tva_grouped:
            tva_grouped[tva_rate] = {"amount_ht": 0, "descriptions": []}
        qty = line.get("quantity", 0)
        unit_price = line.get("unit_price_ht", 0)
        line_ht = qty * unit_price
        tva_grouped[tva_rate]["amount_ht"] += line_ht
        tva_grouped[tva_rate]["descriptions"].append(line.get("description", ""))

    for tva_rate_str, group in tva_grouped.items():
        tva_pct = float(tva_rate_str)
        tax_rate_id = _create_or_get_tax_rate(tva_pct, f"TVA {tva_rate_str}%")
        amount_cents = math.ceil(group["amount_ht"] * 100)
        desc = ", ".join(d for d in group["descriptions"] if d)
        stripe.InvoiceItem.create(
            customer=customer_id,
            invoice=invoice.id,
            amount=amount_cents,
            currency="eur",
            description=desc or "Prestation traiteur",
            tax_rates=[tax_rate_id],
        )

    # Platform fee line: 5% HT + 20% TVA
    fee_tax_rate_id = _create_or_get_tax_rate(20, "TVA 20%")
    fee_ht_cents = math.ceil(platform_fee_ht * 100)
    stripe.InvoiceItem.create(
        customer=customer_id,
        invoice=invoice.id,
        amount=fee_ht_cents,
        currency="eur",
        description="Frais de mise en relation",
        tax_rates=[fee_tax_rate_id],
    )

    stripe.Invoice.finalize_invoice(invoice.id)
    sent = stripe.Invoice.send_invoice(invoice.id)
    hosted_url = sent.get("hosted_invoice_url", "") or ""

    order.stripe_invoice_id = invoice.id
    order.stripe_hosted_invoice_url = hosted_url
    order.status = OrderStatus.invoiced

    total_ttc = totals.get("total_ttc", 0)
    total_ttc_cents = math.ceil(total_ttc * 100)
    caterer_amount_cents = total_ttc_cents - platform_fee_ttc_cents

    payment = Payment(
        order_id=order.id,
        caterer_id=caterer.id,
        stripe_invoice_id=invoice.id,
        status=PaymentStatus.pending,
        amount_total_cents=total_ttc_cents + fee_ht_cents + math.ceil(platform_fee_tva * 100),
        application_fee_cents=platform_fee_ttc_cents,
        amount_to_caterer_cents=caterer_amount_cents,
    )
    session.add(payment)

    total_ht = totals.get("total_ht", 0)
    total_tva = totals.get("total_tva", 0)
    avg_tva_rate = total_tva / total_ht if total_ht else 0.10

    invoice_record = Invoice(
        order_id=order.id,
        caterer_id=caterer.id,
        reference=invoice_ref,
        amount_ht=total_ht,
        tva_rate=round(avg_tva_rate, 4),
        amount_ttc=total_ttc,
        valorisable_agefiph=totals.get("valorisable_agefiph"),
        esat_mention=f"Structure {caterer.structure_type}" if caterer.structure_type else None,
    )
    session.add(invoice_record)

    from sqlalchemy import func, select
    max_num = session.scalar(select(func.max(CommissionInvoice.invoice_number))) or 0

    commission_client = CommissionInvoice(
        invoice_number=max_num + 1,
        order_id=order.id,
        party="client",
        amount_ht=platform_fee_ht,
        tva_rate=0.20,
        amount_ttc=platform_fee_ht + platform_fee_tva,
    )
    session.add(commission_client)

    commission_caterer = CommissionInvoice(
        invoice_number=max_num + 2,
        order_id=order.id,
        party="caterer",
        amount_ht=platform_fee_ht,
        tva_rate=0.20,
        amount_ttc=platform_fee_ht + platform_fee_tva,
    )
    session.add(commission_caterer)

    return invoice


def verify_webhook_signature(payload: bytes | str, sig_header: str, secret: str):
    """Verify Stripe webhook signature using the official SDK.

    The SDK enforces a default 300s timestamp tolerance — closes audit Vuln 5
    (replay-attack window) which the previous hand-rolled HMAC parser lacked.

    Raises `ValueError` on any failure (signature mismatch, timestamp out of
    window, malformed header, malformed payload) to keep the existing API
    contract with `blueprints/api.py` unchanged.
    """
    try:
        return stripe.Webhook.construct_event(payload, sig_header, secret)
    except stripe.error.SignatureVerificationError as exc:
        raise ValueError(str(exc)) from exc
    except ValueError:
        raise
