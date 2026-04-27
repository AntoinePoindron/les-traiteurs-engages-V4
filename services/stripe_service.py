"""Stripe Connect integration via the official `stripe` SDK.

The SDK handles HTTP, retries, idempotency, webhook signature verification
(with timestamp tolerance), and stays in sync with Stripe API changes.

Compared to the previous hand-rolled `_stripe_request`/`verify_webhook_signature`
this module is ~150 LOC shorter and closes audit Vuln 5 (no replay-attack
tolerance) by using `stripe.Webhook.construct_event` which enforces a
timestamp window by default.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import stripe

import config
from models import Caterer

CENTS_PER_EURO = Decimal("100")


def _to_cents(amount: Decimal) -> int:
    """Convert a Decimal euro amount to integer cents (Stripe's unit)."""
    return int((amount * CENTS_PER_EURO).quantize(Decimal("1")))


@dataclass(frozen=True)
class InvoiceAmounts:
    """Invoice / transfer amounts in integer cents.

    Invariant: `amount_to_caterer_cents + application_fee_cents ==
    invoice_total_cents`.
    """
    invoice_total_cents: int
    application_fee_cents: int
    amount_to_caterer_cents: int


def split_invoice_amounts(
    *,
    total_ttc: Decimal,
    fee_ht: Decimal,
    fee_tva: Decimal,
) -> InvoiceAmounts:
    """Compute the Stripe invoice amounts given the quote total and platform fee.

    The platform fee is charged to the customer as an additional invoice
    line on top of `total_ttc`. Stripe takes `application_fee_amount`
    from the total and transfers the rest to the caterer via
    `transfer_data.destination`. So:

        invoice_total  = total_ttc + fee_ttc
        transfer       = invoice_total − application_fee_amount
                       = total_ttc   (when application_fee == fee_ttc)

    Audit finding #7 (2026-04-24): the prior implementation recorded
    `amount_to_caterer = total_ttc − fee_ttc`, double-deducting the fee
    and understating caterer payouts by fee_ttc in the ledger.
    """
    fee_ttc_cents = _to_cents(fee_ht) + _to_cents(fee_tva)
    total_ttc_cents = _to_cents(total_ttc)
    invoice_total_cents = total_ttc_cents + fee_ttc_cents
    return InvoiceAmounts(
        invoice_total_cents=invoice_total_cents,
        application_fee_cents=fee_ttc_cents,
        amount_to_caterer_cents=invoice_total_cents - fee_ttc_cents,
    )

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


def create_or_get_tax_rate(percentage: Decimal, description: str) -> str:
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
