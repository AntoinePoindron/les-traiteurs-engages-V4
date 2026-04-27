"""Facturation Stripe en deux phases.

Pattern :
- **Phase 1** (`queue_invoice`) : crée le Payment local, l'Invoice
  fournisseur et les CommissionInvoice côté DB. Aucun appel Stripe.
  Idempotente sous UNIQUE(payments.order_id) — un 2e appel pour la
  même Order lèvera IntegrityError au flush ; le caller rollback et
  retrouve le Payment existant pour passer en Phase 2.
- **Phase 2** (`send_stripe_invoice`) : crée la facture côté Stripe et
  lie l'id au Payment local. Idempotente côté Stripe via
  `idempotency_key=f"payment-{payment.id}"`.

Invariants :
- Une facture Stripe (id non null) implique un Payment local
  correspondant ; il n'existe jamais de facture Stripe sans trace côté
  plateforme.
- Au plus un Payment par Order (UNIQUE(order_id)).
- `payment.stripe_invoice_id IS NULL` ⇒ Phase 2 pas encore terminée :
  rejouable par le retry CLI sans risque de duplication.
"""
from __future__ import annotations

from decimal import Decimal

from models import (
    CommissionInvoice,
    Invoice,
    Order,
    Payment,
    PaymentStatus,
)
from services.quotes import calculate_quote_totals, derive_invoice_reference

CENTS_PER_EURO = Decimal("100")


def _to_cents(amount: Decimal) -> int:
    """Convertit un montant Decimal en euros vers des cents entiers."""
    return int((amount * CENTS_PER_EURO).quantize(Decimal("1")))


def _totals_from_quote(quote) -> dict:
    """Calcule tous les totaux d'un Quote à partir de ses lignes."""
    line_dicts = [
        {
            "section": ln.section,
            "description": ln.description or "",
            "quantity": float(ln.quantity),
            "unit_price_ht": float(ln.unit_price_ht),
            "tva_rate": float(ln.tva_rate),
        }
        for ln in quote.lines
    ]
    return calculate_quote_totals(line_dicts, quote.quote_request.guest_count)


def queue_invoice(db, *, order: Order) -> Payment:
    """Phase 1 : crée Payment + Invoice + CommissionInvoice. Aucun appel Stripe.

    Idempotente : un second appel pour la même Order lève IntegrityError au
    flush via UNIQUE(payments.order_id). Le caller doit alors rollback et
    retrouver le Payment existant pour passer en Phase 2.

    Retourne le Payment créé (status=`pending`, `stripe_invoice_id=NULL`).
    """
    quote = order.quote
    caterer = quote.caterer
    totals = _totals_from_quote(quote)

    platform_fee_ht = totals["platform_fee_ht"]
    platform_fee_tva = totals["platform_fee_tva"]
    fee_ttc_cents = _to_cents(platform_fee_ht) + _to_cents(platform_fee_tva)
    total_ttc_cents = _to_cents(totals["total_ttc"])
    invoice_total_cents = total_ttc_cents + fee_ttc_cents

    payment = Payment(
        order_id=order.id,
        caterer_id=caterer.id,
        status=PaymentStatus.pending,
        amount_total_cents=invoice_total_cents,
        application_fee_cents=fee_ttc_cents,
        amount_to_caterer_cents=invoice_total_cents - fee_ttc_cents,
    )
    db.add(payment)

    total_ht = totals["total_ht"]
    total_tva = totals["total_tva"]
    # Moyenne pondérée mono-taux ; sur base nulle on n'invente pas de taux.
    avg_tva_rate = (total_tva / total_ht).quantize(Decimal("0.0001")) if total_ht else None

    db.add(Invoice(
        order_id=order.id,
        caterer_id=caterer.id,
        reference=derive_invoice_reference(quote.reference),
        amount_ht=total_ht,
        tva_rate=avg_tva_rate,
        amount_ttc=totals["total_ttc"],
        valorisable_agefiph=totals["valorisable_agefiph"],
        esat_mention=f"Structure {caterer.structure_type}" if caterer.structure_type else None,
    ))

    fee_ttc = platform_fee_ht + platform_fee_tva
    for party in ("client", "caterer"):
        db.add(CommissionInvoice(
            order_id=order.id,
            party=party,
            amount_ht=platform_fee_ht,
            tva_rate=Decimal("0.20"),
            amount_ttc=fee_ttc,
        ))

    db.flush()
    return payment
