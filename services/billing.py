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

import datetime
import logging
from decimal import Decimal

import stripe
from sqlalchemy import select

from models import (
    CommissionInvoice,
    Invoice,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
)
from services.quotes import calculate_quote_totals, derive_invoice_reference
from services.stripe_service import create_or_get_tax_rate, get_or_create_customer

logger = logging.getLogger(__name__)

DEFAULT_RETRY_AGE = datetime.timedelta(minutes=2)

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


def send_stripe_invoice(db, *, payment: Payment) -> None:
    """Phase 2 : crée la facture Stripe correspondant au Payment et lie l'id.

    Pré-condition : `payment.stripe_invoice_id IS NULL` (sinon no-op).
    Post-condition :
    - `payment.stripe_invoice_id` renseigné ;
    - `payment.order.stripe_invoice_id` et `payment.order.stripe_hosted_invoice_url` renseignés ;
    - `payment.order.status == invoiced` ;
    - facture Stripe finalisée et envoyée au customer.

    Idempotente côté Stripe via `idempotency_key=f"payment-{payment.id}"`.
    Un retry après crash entre l'envoi Stripe et le commit DB réutilise la
    même facture Stripe — pas de duplication. Risque résiduel : un re-send
    d'email au customer (acceptable, loggué).
    """
    if payment.stripe_invoice_id:
        return

    order = payment.order
    quote = order.quote
    caterer = quote.caterer
    client_user = order.client_admin

    totals = _totals_from_quote(quote)
    platform_fee_ht = totals["platform_fee_ht"]
    fee_ttc_cents = payment.application_fee_cents

    customer_id = get_or_create_customer(db, client_user)

    invoice = stripe.Invoice.create(
        customer=customer_id,
        collection_method="send_invoice",
        days_until_due=30,
        transfer_data={"destination": caterer.stripe_account_id},
        application_fee_amount=fee_ttc_cents,
        metadata={
            "order_id": str(order.id),
            "payment_id": str(payment.id),
            "invoice_reference": derive_invoice_reference(quote.reference),
        },
        custom_fields=[
            {"name": "Traiteur", "value": caterer.name},
            {"name": "SIRET", "value": caterer.siret or ""},
        ],
        idempotency_key=f"payment-{payment.id}",
    )

    # InvoiceItems groupés par taux de TVA, comme avant.
    tva_grouped: dict[str, dict] = {}
    for ln in quote.lines:
        key = str(ln.tva_rate)
        if key not in tva_grouped:
            tva_grouped[key] = {"amount_ht": Decimal("0"), "descriptions": []}
        tva_grouped[key]["amount_ht"] += ln.quantity * ln.unit_price_ht
        tva_grouped[key]["descriptions"].append(ln.description or "")

    for tva_rate_str, group in tva_grouped.items():
        tax_rate_id = create_or_get_tax_rate(Decimal(tva_rate_str), f"TVA {tva_rate_str}%")
        stripe.InvoiceItem.create(
            customer=customer_id,
            invoice=invoice.id,
            amount=_to_cents(group["amount_ht"]),
            currency="eur",
            description=", ".join(d for d in group["descriptions"] if d) or "Prestation traiteur",
            tax_rates=[tax_rate_id],
        )

    fee_tax_rate_id = create_or_get_tax_rate(Decimal("20"), "TVA 20%")
    stripe.InvoiceItem.create(
        customer=customer_id,
        invoice=invoice.id,
        amount=_to_cents(platform_fee_ht),
        currency="eur",
        description="Frais de mise en relation",
        tax_rates=[fee_tax_rate_id],
    )

    stripe.Invoice.finalize_invoice(invoice.id)
    sent = stripe.Invoice.send_invoice(invoice.id)
    hosted_url = sent.get("hosted_invoice_url", "") or ""

    payment.stripe_invoice_id = invoice.id
    order.stripe_invoice_id = invoice.id
    order.stripe_hosted_invoice_url = hosted_url
    order.status = OrderStatus.invoiced
    db.flush()


def retry_pending_invoices(
    db,
    *,
    age_threshold: datetime.timedelta = DEFAULT_RETRY_AGE,
) -> tuple[int, int]:
    """Rejoue la Phase 2 pour tous les Payment en attente d'envoi Stripe.

    Sélection : `Payment.stripe_invoice_id IS NULL` ET `status == pending`,
    et plus ancien que `age_threshold` (par défaut 2 min) pour ne pas
    interférer avec une requête HTTP encore en vol qui n'a juste pas
    encore commit la phase 2.

    Commit après chaque succès, rollback après chaque échec — les
    paiements indépendants ne se bloquent pas mutuellement.

    Retourne `(success_count, failed_count)`.
    """
    cutoff = datetime.datetime.utcnow() - age_threshold
    pending = db.scalars(
        select(Payment)
        .where(Payment.stripe_invoice_id.is_(None))
        .where(Payment.status == PaymentStatus.pending)
        .where(Payment.created_at < cutoff)
    ).all()
    success = 0
    failed = 0
    for p in pending:
        try:
            send_stripe_invoice(db, payment=p)
            db.commit()
            logger.info("Retried payment %s -> stripe %s", p.id, p.stripe_invoice_id)
            success += 1
        except stripe.StripeError as exc:
            db.rollback()
            logger.error("Retry failed for payment %s: %s", p.id, exc)
            failed += 1
    return success, failed
