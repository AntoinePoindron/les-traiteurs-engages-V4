"""Create 4 demo requests showcasing each caterer-side status flow.

After running this script, log in as the ESAT demo caterer
(contact@saveurs-solidaires.fr / password123) and visit /caterer/requests
to see one row per badge: Nouvelle, Devis envoyé, Devis refusé, Commande
créée. Each row's detail page exercises a different layout branch in
templates/caterer/requests/detail.html.

Run inside the running app container:

    docker compose exec app python scripts/demo_caterer_statuses.py

Idempotent: every fixture is tagged with [STATUS_DEMO] in
message_to_caterer; re-running this script wipes the previous demo set
before re-creating it, so it's safe to call after every db reset.

Pre-req: scripts/seed_data.py must have run first (we reuse its caterer
ESAT and the Acme Solutions client, instead of re-seeding the world).
"""
from __future__ import annotations

import datetime
import sys
from decimal import Decimal

from sqlalchemy import select

from database import get_session
from models import (
    Caterer,
    Company,
    MealType,
    Order,
    OrderStatus,
    QRCStatus,
    Quote,
    QuoteLine,
    QuoteRequest,
    QuoteRequestCaterer,
    QuoteRequestStatus,
    QuoteStatus,
    User,
    UserRole,
)

DEMO_TAG = "[STATUS_DEMO]"


def _wipe_previous_fixtures(db) -> int:
    """Delete every QR previously created by this script (matched by tag).

    Cascades the cleanup down to QRCs, Quotes, QuoteLines and Orders so
    we don't leave orphans.
    """
    old_qrs = db.scalars(
        select(QuoteRequest).where(
            QuoteRequest.message_to_caterer.like(f"{DEMO_TAG}%")
        )
    ).all()
    for qr in old_qrs:
        for qrc in list(qr.caterers):
            db.delete(qrc)
        for q in list(qr.quotes):
            if q.order:
                db.delete(q.order)
            for ln in list(q.lines):
                db.delete(ln)
            db.delete(q)
        db.delete(qr)
    db.flush()
    return len(old_qrs)


def main():
    today = datetime.date.today()
    now = datetime.datetime.utcnow()

    with get_session() as db:
        # --- Resolve seed dependencies ---
        caterer = db.scalar(
            select(Caterer).where(Caterer.siret == "11111111111111")
        )
        if not caterer:
            print("Caterer ESAT not found — run seed_data.py first.", file=sys.stderr)
            sys.exit(1)

        company = db.scalar(
            select(Company).where(Company.name == "Acme Solutions")
        )
        if not company:
            print("Company 'Acme Solutions' not found — run seed_data.py first.", file=sys.stderr)
            sys.exit(1)

        client_admin = db.scalar(
            select(User)
            .where(User.role == UserRole.client_admin)
            .where(User.company_id == company.id)
        )
        if not client_admin:
            print("No client_admin found for Acme — run seed_data.py first.", file=sys.stderr)
            sys.exit(1)

        # --- Wipe previous demo fixtures so the script stays idempotent ---
        wiped = _wipe_previous_fixtures(db)
        if wiped:
            print(f"Cleaned {wiped} previous demo request(s).")

        # --- Common fields shared by the 4 fixtures ---
        common = dict(
            company_id=company.id,
            user_id=client_admin.id,
            event_address="15 rue de Rivoli",
            event_city="Paris",
            event_zip_code="75001",
            event_latitude=48.8566,
            event_longitude=2.3522,
            is_compare_mode=True,
            dietary_vegetarian=True,
            vegetarian_count=5,
        )

        # --- 1. Nouvelle (no quote yet) ---
        qr_new = QuoteRequest(
            **common,
            status=QuoteRequestStatus.sent_to_caterers,
            meal_type=MealType.dejeuner,
            event_date=today + datetime.timedelta(days=20),
            guest_count=25,
            budget_global=Decimal("1250"),
            budget_per_person=Decimal("50"),
            message_to_caterer=(
                f"{DEMO_TAG} Aucun devis encore — affiche le badge 'Nouvelle' "
                f"et les boutons d'action."
            ),
        )

        # --- 2. Devis envoyé ---
        qr_sent = QuoteRequest(
            **common,
            status=QuoteRequestStatus.sent_to_caterers,
            meal_type=MealType.cocktail,
            event_date=today + datetime.timedelta(days=35),
            guest_count=40,
            budget_global=Decimal("2000"),
            budget_per_person=Decimal("50"),
            message_to_caterer=(
                f"{DEMO_TAG} Devis envoye, en attente de la decision client — "
                f"badge 'Devis envoye'."
            ),
        )

        # --- 3. Devis refusé ---
        qr_refused = QuoteRequest(
            **common,
            status=QuoteRequestStatus.quotes_refused,
            meal_type=MealType.petit_dejeuner,
            event_date=today + datetime.timedelta(days=10),
            guest_count=15,
            budget_global=Decimal("450"),
            budget_per_person=Decimal("30"),
            message_to_caterer=(
                f"{DEMO_TAG} Le client a refuse le devis avec un motif — "
                f"badge 'Devis refuse' + bloc rouge 'Motif du refus'."
            ),
        )

        # --- 4. Commande créée ---
        qr_accepted = QuoteRequest(
            **common,
            status=QuoteRequestStatus.completed,
            meal_type=MealType.diner,
            event_date=today + datetime.timedelta(days=45),
            guest_count=30,
            budget_global=Decimal("1800"),
            budget_per_person=Decimal("60"),
            message_to_caterer=(
                f"{DEMO_TAG} Devis accepte, commande creee — badge "
                f"'Commande creee' + CTA 'Voir la commande'."
            ),
        )

        db.add_all([qr_new, qr_sent, qr_refused, qr_accepted])
        db.flush()

        # --- QRCs (one per QR, all targeting our caterer) ---
        db.add_all([
            QuoteRequestCaterer(
                quote_request_id=qr_new.id,
                caterer_id=caterer.id,
                status=QRCStatus.selected,
            ),
            QuoteRequestCaterer(
                quote_request_id=qr_sent.id,
                caterer_id=caterer.id,
                status=QRCStatus.transmitted_to_client,
                responded_at=now - datetime.timedelta(days=1),
                response_rank=1,
            ),
            QuoteRequestCaterer(
                quote_request_id=qr_refused.id,
                caterer_id=caterer.id,
                status=QRCStatus.transmitted_to_client,
                responded_at=now - datetime.timedelta(days=4),
                response_rank=1,
            ),
            QuoteRequestCaterer(
                quote_request_id=qr_accepted.id,
                caterer_id=caterer.id,
                status=QRCStatus.transmitted_to_client,
                responded_at=now - datetime.timedelta(days=8),
                response_rank=1,
            ),
        ])
        db.flush()

        # --- Quotes (3 of 4 — "Nouvelle" deliberately has none) ---
        # Reference suffix uses a timestamp so reruns don't collide with
        # the unique constraint on Quote.reference.
        ts = int(now.timestamp())
        prefix = caterer.invoice_prefix

        quote_sent = Quote(
            quote_request_id=qr_sent.id,
            caterer_id=caterer.id,
            reference=f"DEMO-{prefix}-SENT-{ts}",
            total_amount_ht=Decimal("1800.00"),
            amount_per_person=Decimal("45.00"),
            valorisable_agefiph=Decimal("1800.00"),
            notes="Cocktail dinatoire avec produits du marche.",
            valid_until=today + datetime.timedelta(days=30),
            status=QuoteStatus.sent,
            lines=[
                QuoteLine(position=0, section="principal", description="Buffet cocktail",
                          quantity=Decimal("40"), unit_price_ht=Decimal("40"), tva_rate=Decimal("10")),
                QuoteLine(position=1, section="boissons", description="Boissons sans alcool",
                          quantity=Decimal("40"), unit_price_ht=Decimal("5"), tva_rate=Decimal("10")),
            ],
        )

        quote_refused = Quote(
            quote_request_id=qr_refused.id,
            caterer_id=caterer.id,
            reference=f"DEMO-{prefix}-REFUSED-{ts}",
            total_amount_ht=Decimal("420.00"),
            amount_per_person=Decimal("28.00"),
            valorisable_agefiph=Decimal("420.00"),
            notes="Petit-dejeuner buffet : viennoiseries, fruits, boissons chaudes.",
            valid_until=today + datetime.timedelta(days=10),
            status=QuoteStatus.refused,
            refusal_reason=(
                "Le budget propose par le traiteur depasse notre enveloppe "
                "annuelle pour les petits-dejeuners de ce trimestre."
            ),
            lines=[
                QuoteLine(position=0, section="principal", description="Petit-dejeuner buffet",
                          quantity=Decimal("15"), unit_price_ht=Decimal("28"), tva_rate=Decimal("10")),
            ],
        )

        quote_accepted = Quote(
            quote_request_id=qr_accepted.id,
            caterer_id=caterer.id,
            reference=f"DEMO-{prefix}-ACCEPTED-{ts}",
            total_amount_ht=Decimal("1700.00"),
            amount_per_person=Decimal("56.67"),
            valorisable_agefiph=Decimal("1700.00"),
            notes="Diner gastronomique 3 services, service a l'assiette.",
            valid_until=today + datetime.timedelta(days=20),
            status=QuoteStatus.accepted,
            lines=[
                QuoteLine(position=0, section="principal", description="Diner 3 services",
                          quantity=Decimal("30"), unit_price_ht=Decimal("50"), tva_rate=Decimal("10")),
                QuoteLine(position=1, section="boissons", description="Vin et boissons",
                          quantity=Decimal("30"), unit_price_ht=Decimal("6.67"), tva_rate=Decimal("20")),
            ],
        )

        db.add_all([quote_sent, quote_refused, quote_accepted])
        db.flush()

        # --- Order for the accepted quote ---
        order = Order(
            quote_id=quote_accepted.id,
            client_admin_id=client_admin.id,
            status=OrderStatus.confirmed,
            delivery_date=qr_accepted.event_date,
            delivery_address="15 rue de Rivoli, 75001 Paris",
            notes="Service complet sur place. Equipe attendue a partir de 19h.",
        )
        db.add(order)
        db.flush()

        print()
        print("Demo requests created for caterer ESAT.")
        print("Login: contact@saveurs-solidaires.fr / password123")
        print()
        print("Visit /caterer/requests to see all four:")
        print("  1. Nouvelle           - Dejeuner 25 pers., Paris")
        print("  2. Devis envoye       - Cocktail 40 pers., Paris")
        print("  3. Devis refuse       - Petit-dejeuner 15 pers., Paris (with refusal reason)")
        print("  4. Commande creee    - Diner 30 pers., Paris (with order)")


if __name__ == "__main__":
    main()
