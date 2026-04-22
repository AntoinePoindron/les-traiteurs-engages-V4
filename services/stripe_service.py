import hashlib
import hmac
import json
import math
import time

import httpx

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

STRIPE_BASE_URL = "https://api.stripe.com/v1"

_tax_rate_cache: dict[str, str] = {}


def _stripe_request(method, endpoint, data=None, idempotency_key=None):
    """Execute a Stripe API request via httpx."""
    headers = {
        "Authorization": f"Bearer {config.STRIPE_SECRET_KEY}",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    url = f"{STRIPE_BASE_URL}{endpoint}"
    response = httpx.request(method, url, data=data, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def create_connect_account(caterer):
    """Create a Stripe Connect Express account for a caterer."""
    user = caterer.users[0] if caterer.users else None
    email = user.email if user else None
    return _stripe_request("POST", "/accounts", data={
        "type": "express",
        "country": "FR",
        "email": email,
        "business_type": "company",
        "capabilities[card_payments][requested]": "true",
        "capabilities[transfers][requested]": "true",
        "metadata[caterer_id]": str(caterer.id),
    })


def create_account_link(account_id, refresh_url, return_url):
    """Create a Stripe account onboarding link."""
    result = _stripe_request("POST", "/account_links", data={
        "account": account_id,
        "refresh_url": refresh_url,
        "return_url": return_url,
        "type": "account_onboarding",
    })
    return result["url"]


def get_account(account_id):
    """Fetch Stripe account status."""
    result = _stripe_request("GET", f"/accounts/{account_id}")
    return {
        "charges_enabled": result.get("charges_enabled", False),
        "payouts_enabled": result.get("payouts_enabled", False),
    }


def get_or_create_customer(session, user):
    """Return existing Stripe customer ID or create one."""
    if user.stripe_customer_id:
        return user.stripe_customer_id
    result = _stripe_request("POST", "/customers", data={
        "email": user.email,
        "name": f"{user.first_name} {user.last_name}",
        "metadata[user_id]": str(user.id),
    })
    user.stripe_customer_id = result["id"]
    session.add(user)
    return result["id"]


def create_tax_rate(percentage, description):
    """Create a Stripe TaxRate or return cached ID."""
    cache_key = f"{percentage}"
    if cache_key in _tax_rate_cache:
        return _tax_rate_cache[cache_key]
    result = _stripe_request("POST", "/tax_rates", data={
        "display_name": "TVA",
        "description": description,
        "percentage": str(percentage),
        "inclusive": "false",
        "country": "FR",
        "jurisdiction": "FR",
    })
    _tax_rate_cache[cache_key] = result["id"]
    return result["id"]


def create_invoice_for_order(session, order):
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

    invoice_data = _stripe_request("POST", "/invoices", data={
        "customer": customer_id,
        "collection_method": "send_invoice",
        "days_until_due": "30",
        "transfer_data[destination]": caterer.stripe_account_id,
        "application_fee_amount": str(platform_fee_ttc_cents),
        "metadata[order_id]": str(order.id),
        "metadata[invoice_reference]": invoice_ref,
        "custom_fields[0][name]": "Traiteur",
        "custom_fields[0][value]": caterer.name,
        "custom_fields[1][name]": "SIRET",
        "custom_fields[1][value]": caterer.siret or "",
    })
    stripe_invoice_id = invoice_data["id"]

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
        tax_rate_id = create_tax_rate(tva_pct, f"TVA {tva_rate_str}%")
        amount_cents = math.ceil(group["amount_ht"] * 100)
        desc = ", ".join(d for d in group["descriptions"] if d)
        _stripe_request("POST", "/invoiceitems", data={
            "customer": customer_id,
            "invoice": stripe_invoice_id,
            "amount": str(amount_cents),
            "currency": "eur",
            "description": desc or "Prestation traiteur",
            "tax_rates[0]": tax_rate_id,
        })

    # Platform fee line: 5% HT + 20% TVA
    fee_tax_rate_id = create_tax_rate(20, "TVA 20%")
    fee_ht_cents = math.ceil(platform_fee_ht * 100)
    _stripe_request("POST", "/invoiceitems", data={
        "customer": customer_id,
        "invoice": stripe_invoice_id,
        "amount": str(fee_ht_cents),
        "currency": "eur",
        "description": "Frais de mise en relation",
        "tax_rates[0]": fee_tax_rate_id,
    })

    _stripe_request("POST", f"/invoices/{stripe_invoice_id}/finalize")
    send_result = _stripe_request("POST", f"/invoices/{stripe_invoice_id}/send")

    hosted_url = send_result.get("hosted_invoice_url", "")

    order.stripe_invoice_id = stripe_invoice_id
    order.stripe_hosted_invoice_url = hosted_url
    order.status = OrderStatus.invoiced

    total_ttc = totals.get("total_ttc", 0)
    total_ttc_cents = math.ceil(total_ttc * 100)
    caterer_amount_cents = total_ttc_cents - platform_fee_ttc_cents

    payment = Payment(
        order_id=order.id,
        caterer_id=caterer.id,
        stripe_invoice_id=stripe_invoice_id,
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

    return invoice_data


def verify_webhook_signature(payload, sig_header, secret):
    """Verify Stripe webhook HMAC-SHA256 signature."""
    if not sig_header:
        raise ValueError("Missing signature header")

    elements = {}
    for part in sig_header.split(","):
        key, _, value = part.strip().partition("=")
        elements.setdefault(key, []).append(value)

    timestamp = elements.get("t", [None])[0]
    if not timestamp:
        raise ValueError("Missing timestamp in signature")

    signatures = elements.get("v1", [])
    if not signatures:
        raise ValueError("Missing v1 signature")

    if isinstance(payload, bytes):
        payload_str = payload.decode("utf-8")
    else:
        payload_str = payload

    signed_payload = f"{timestamp}.{payload_str}"
    expected = hmac.new(
        secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not any(hmac.compare_digest(expected, sig) for sig in signatures):
        raise ValueError("Invalid signature")

    return json.loads(payload_str)
