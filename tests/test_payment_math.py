"""Audit finding #7: the Payment ledger math must reflect the actual
Stripe transfer.

Stripe invoice total = quote_total_ttc + fee_ttc (the platform fee is
added on top as an extra invoice line). `application_fee_amount` is
taken from that total, so the transfer to the caterer equals
    invoice_total - application_fee  =  quote_total_ttc.

Before the fix, `amount_to_caterer_cents` was recorded as
    total_ttc_cents - platform_fee_ttc_cents
which double-deducts the fee and makes the ledger understate caterer
payouts by fee_ttc.
"""

from decimal import Decimal


def test_split_invoice_amounts_matches_stripe_transfer():
    """The pure helper must produce amounts that sum correctly for Stripe.

    total_ttc is the lines' TTC. Platform fee is added ON TOP as a fresh
    line. Stripe invoice_total = total_ttc + fee_ttc. Transfer to caterer
    = invoice_total − application_fee = total_ttc.
    """
    from services.stripe_service import split_invoice_amounts

    total_ttc = Decimal("120.00")  # e.g. 100 HT + 20 TVA
    fee_ht = Decimal("5.00")  # 5% of 100 HT
    fee_tva = Decimal("1.00")  # 20% TVA on 5 HT

    result = split_invoice_amounts(
        total_ttc=total_ttc,
        fee_ht=fee_ht,
        fee_tva=fee_tva,
    )

    # Sanity: sum of HT + TVA parts, in cents.
    fee_ttc_cents = 500 + 100  # 5€ + 1€
    invoice_total_cents = 12000 + fee_ttc_cents  # 120€ + 6€
    assert result.invoice_total_cents == invoice_total_cents
    assert result.application_fee_cents == fee_ttc_cents
    # The caterer receives the *full* lines TTC (120€), not 120 − 6.
    assert result.amount_to_caterer_cents == 12000, (
        f"caterer should receive {12000} cents, got {result.amount_to_caterer_cents}"
    )
    # Ledger invariant: transfer + application_fee == invoice total.
    assert (
        result.amount_to_caterer_cents + result.application_fee_cents
        == result.invoice_total_cents
    )
