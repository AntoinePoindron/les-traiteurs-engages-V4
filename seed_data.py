import datetime
import uuid

import bcrypt
from sqlalchemy import select

from database import get_session
from decimal import Decimal

from models import (
    Caterer,
    CatererStructureType,
    Company,
    CompanyService,
    MembershipStatus,
    Message,
    MealType,
    Notification,
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

PASSWORD_HASH = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode()


def seed():
    with get_session() as db:
        if db.scalar(select(Company).where(Company.name == "Acme Solutions")):
            print("Seed data already exists, skipping.")
            return

        # --- Companies ---
        acme = Company(
            name="Acme Solutions",
            siret="12345678901234",
            address="15 rue de Rivoli",
            city="Paris",
            zip_code="75001",
            oeth_eligible=True,
            budget_annual=50000,
        )
        techcorp = Company(
            name="TechCorp France",
            siret="98765432109876",
            address="42 avenue Jean Jaures",
            city="Lyon",
            zip_code="69007",
            oeth_eligible=False,
            budget_annual=30000,
        )
        db.add_all([acme, techcorp])
        db.flush()

        # --- Company services ---
        svc_direction = CompanyService(company_id=acme.id, name="Direction", annual_budget=25000)
        svc_marketing = CompanyService(company_id=acme.id, name="Marketing", annual_budget=25000)
        svc_rh = CompanyService(company_id=techcorp.id, name="RH", annual_budget=30000)
        db.add_all([svc_direction, svc_marketing, svc_rh])
        db.flush()

        # --- Users ---
        admin = db.scalar(select(User).where(User.role == UserRole.super_admin))

        alice = User(
            email="alice@acme-solutions.fr",
            password_hash=PASSWORD_HASH,
            first_name="Alice",
            last_name="Dupont",
            role=UserRole.client_admin,
            company_id=acme.id,
            membership_status=MembershipStatus.active,
        )
        bob = User(
            email="bob@techcorp.fr",
            password_hash=PASSWORD_HASH,
            first_name="Bob",
            last_name="Martin",
            role=UserRole.client_admin,
            company_id=techcorp.id,
            membership_status=MembershipStatus.active,
        )
        claire = User(
            email="claire@acme-solutions.fr",
            password_hash=PASSWORD_HASH,
            first_name="Claire",
            last_name="Bernard",
            role=UserRole.client_user,
            company_id=acme.id,
            membership_status=MembershipStatus.active,
        )
        db.add_all([alice, bob, claire])
        db.flush()

        # --- Caterers ---
        cat_esat = Caterer(
            name="ESAT Les Saveurs Solidaires",
            siret="11111111111111",
            structure_type=CatererStructureType.ESAT,
            address="8 rue des Lilas",
            city="Paris",
            zip_code="75011",
            latitude=48.8606,
            longitude=2.3786,
            description="Traiteur solidaire specialise en cuisine francaise et du monde.",
            specialties=["francais", "mediterraneen", "asiatique"],
            capacity_min=10,
            capacity_max=200,
            delivery_radius_km=20,
            dietary_vegetarian=True,
            dietary_vegan=True,
            dietary_halal=True,
            is_validated=True,
            invoice_prefix="ESAT1",
            service_offerings=[
                "petit_dejeuner", "pause_gourmande",
                "plateaux_repas", "cocktail_dinatoire",
            ],
            price_per_person_min=Decimal("18"),
            price_per_person_max=Decimal("45"),
            min_advance_days=8,
        )
        cat_ea = Caterer(
            name="EA Traiteur & Co",
            siret="22222222222222",
            structure_type=CatererStructureType.EA,
            address="120 cours Lafayette",
            city="Lyon",
            zip_code="69003",
            latitude=45.7610,
            longitude=4.8510,
            description="Entreprise adaptee proposant des prestations traiteur haut de gamme.",
            specialties=["gastronomique", "buffet", "cocktail"],
            capacity_min=20,
            capacity_max=150,
            delivery_radius_km=30,
            dietary_vegetarian=True,
            dietary_gluten_free=True,
            is_validated=True,
            invoice_prefix="EATCO",
            service_offerings=[
                "plateaux_repas", "cocktail_dinatoire",
                "cocktail_dejeunatoire", "aperitif",
            ],
            price_per_person_min=Decimal("32"),
            price_per_person_max=Decimal("75"),
            min_advance_days=5,
        )
        cat_ei = Caterer(
            name="EI Delices Engages",
            siret="33333333333333",
            structure_type=CatererStructureType.EI,
            address="25 rue Oberkampf",
            city="Paris",
            zip_code="75011",
            latitude=48.8650,
            longitude=2.3800,
            description="Entreprise d'insertion preparant des repas bio et locaux.",
            specialties=["bio", "local", "patisserie"],
            capacity_min=5,
            capacity_max=80,
            delivery_radius_km=15,
            dietary_vegetarian=True,
            dietary_vegan=True,
            dietary_casher=True,
            is_validated=True,
            invoice_prefix="EIDEL",
            service_offerings=[
                "petit_dejeuner", "pause_gourmande", "aperitif",
            ],
            price_per_person_min=Decimal("12"),
            price_per_person_max=Decimal("28"),
            min_advance_days=3,
        )
        db.add_all([cat_esat, cat_ea, cat_ei])
        db.flush()

        # --- Caterer users ---
        user_esat = User(
            email="contact@saveurs-solidaires.fr",
            password_hash=PASSWORD_HASH,
            first_name="Sophie",
            last_name="Leroy",
            role=UserRole.caterer,
            caterer_id=cat_esat.id,
            membership_status=MembershipStatus.active,
        )
        user_ea = User(
            email="contact@traiteur-co.fr",
            password_hash=PASSWORD_HASH,
            first_name="Marc",
            last_name="Petit",
            role=UserRole.caterer,
            caterer_id=cat_ea.id,
            membership_status=MembershipStatus.active,
        )
        user_ei = User(
            email="contact@delices-engages.fr",
            password_hash=PASSWORD_HASH,
            first_name="Nadia",
            last_name="Amrani",
            role=UserRole.caterer,
            caterer_id=cat_ei.id,
            membership_status=MembershipStatus.active,
        )
        db.add_all([user_esat, user_ea, user_ei])
        db.flush()

        # --- Quote requests ---
        today = datetime.date.today()

        qr_draft = QuoteRequest(
            company_id=acme.id,
            user_id=alice.id,
            company_service_id=svc_marketing.id,
            status=QuoteRequestStatus.draft,
            meal_type=MealType.cocktail,
            event_date=today + datetime.timedelta(days=30),
            guest_count=50,
            event_address="15 rue de Rivoli",
            event_city="Paris",
            event_zip_code="75001",
            event_latitude=48.8566,
            event_longitude=2.3522,
            budget_global=2500,
            budget_per_person=50,
            dietary_vegetarian=True,
            is_compare_mode=True,
            message_to_caterer="Cocktail pour le lancement de notre nouveau produit.",
        )

        qr_sent = QuoteRequest(
            company_id=acme.id,
            user_id=alice.id,
            company_service_id=svc_direction.id,
            status=QuoteRequestStatus.sent_to_caterers,
            meal_type=MealType.dejeuner,
            event_date=today + datetime.timedelta(days=15),
            guest_count=30,
            event_address="15 rue de Rivoli",
            event_city="Paris",
            event_zip_code="75001",
            event_latitude=48.8566,
            event_longitude=2.3522,
            budget_global=1500,
            budget_per_person=50,
            dietary_vegetarian=True,
            dietary_halal=True,
            vegetarian_count=5,
            halal_count=3,
            is_compare_mode=True,
            message_to_caterer="Dejeuner d'equipe mensuel, ambiance conviviale.",
        )

        qr_completed = QuoteRequest(
            company_id=techcorp.id,
            user_id=bob.id,
            company_service_id=svc_rh.id,
            status=QuoteRequestStatus.completed,
            meal_type=MealType.diner,
            event_date=today - datetime.timedelta(days=10),
            guest_count=20,
            event_address="42 avenue Jean Jaures",
            event_city="Lyon",
            event_zip_code="69007",
            event_latitude=45.7640,
            event_longitude=4.8357,
            budget_global=1200,
            budget_per_person=60,
            dietary_vegetarian=True,
            dietary_gluten_free=True,
            vegetarian_count=4,
            gluten_free_count=2,
            is_compare_mode=False,
            message_to_caterer="Diner de fin d'annee pour l'equipe RH.",
        )
        db.add_all([qr_draft, qr_sent, qr_completed])
        db.flush()

        # --- QRCs for qr_sent ---
        qrc_esat = QuoteRequestCaterer(
            quote_request_id=qr_sent.id,
            caterer_id=cat_esat.id,
            status=QRCStatus.transmitted_to_client,
            responded_at=datetime.datetime.utcnow() - datetime.timedelta(days=2),
            response_rank=1,
        )
        qrc_ei = QuoteRequestCaterer(
            quote_request_id=qr_sent.id,
            caterer_id=cat_ei.id,
            status=QRCStatus.selected,
        )
        db.add_all([qrc_esat, qrc_ei])
        db.flush()

        # --- QRC for qr_completed ---
        qrc_ea = QuoteRequestCaterer(
            quote_request_id=qr_completed.id,
            caterer_id=cat_ea.id,
            status=QRCStatus.transmitted_to_client,
            responded_at=datetime.datetime.utcnow() - datetime.timedelta(days=20),
            response_rank=1,
        )
        db.add(qrc_ea)
        db.flush()

        # --- Quotes ---
        quote_sent = Quote(
            quote_request_id=qr_sent.id,
            caterer_id=cat_esat.id,
            reference="DEVIS-ESAT1-2026-001",
            total_amount_ht=Decimal("1350.00"),
            amount_per_person=Decimal("45.00"),
            valorisable_agefiph=Decimal("1350.00"),
            notes="Menu compose avec des produits de saison.",
            valid_until=today + datetime.timedelta(days=30),
            status=QuoteStatus.sent,
            lines=[
                QuoteLine(position=0, section="principal", description="Menu dejeuner complet",
                          quantity=Decimal("30"), unit_price_ht=Decimal("40"), tva_rate=Decimal("10")),
                QuoteLine(position=1, section="boissons", description="Boissons sans alcool",
                          quantity=Decimal("30"), unit_price_ht=Decimal("5"), tva_rate=Decimal("10")),
            ],
        )

        quote_accepted = Quote(
            quote_request_id=qr_completed.id,
            caterer_id=cat_ea.id,
            reference="DEVIS-EATCO-2026-001",
            total_amount_ht=Decimal("1100.00"),
            amount_per_person=Decimal("55.00"),
            valorisable_agefiph=Decimal("1100.00"),
            notes="Menu gastronomique adapte aux regimes specifiques.",
            valid_until=today - datetime.timedelta(days=5),
            status=QuoteStatus.accepted,
            lines=[
                QuoteLine(position=0, section="principal", description="Diner gastronomique",
                          quantity=Decimal("20"), unit_price_ht=Decimal("50"), tva_rate=Decimal("10")),
                QuoteLine(position=1, section="boissons", description="Vin et boissons",
                          quantity=Decimal("20"), unit_price_ht=Decimal("5"), tva_rate=Decimal("20")),
            ],
        )
        db.add_all([quote_sent, quote_accepted])
        db.flush()

        # --- Order ---
        order = Order(
            quote_id=quote_accepted.id,
            client_admin_id=bob.id,
            status=OrderStatus.confirmed,
            delivery_date=today - datetime.timedelta(days=10),
            delivery_address="42 avenue Jean Jaures, 69007 Lyon",
            notes="Acces par le parking souterrain, niveau -1.",
        )
        db.add(order)
        db.flush()

        # --- Messages ---
        thread_alice_esat = uuid.uuid5(
            uuid.NAMESPACE_URL,
            ":".join(sorted([str(alice.id), str(user_esat.id)])),
        )
        thread_bob_ea = uuid.uuid5(
            uuid.NAMESPACE_URL,
            ":".join(sorted([str(bob.id), str(user_ea.id)])),
        )

        now = datetime.datetime.utcnow()
        messages = [
            Message(
                thread_id=thread_alice_esat,
                sender_id=alice.id,
                recipient_id=user_esat.id,
                quote_request_id=qr_sent.id,
                body="Bonjour, pouvez-vous confirmer la disponibilite de votre equipe pour le 15 ?",
                created_at=now - datetime.timedelta(hours=5),
            ),
            Message(
                thread_id=thread_alice_esat,
                sender_id=user_esat.id,
                recipient_id=alice.id,
                quote_request_id=qr_sent.id,
                body="Bonjour Alice, oui nous sommes disponibles. Je vous envoie le devis rapidement.",
                created_at=now - datetime.timedelta(hours=4),
            ),
            Message(
                thread_id=thread_bob_ea,
                sender_id=bob.id,
                recipient_id=user_ea.id,
                order_id=order.id,
                body="Merci pour le diner, tout etait parfait !",
                created_at=now - datetime.timedelta(hours=1),
            ),
        ]
        db.add_all(messages)
        db.flush()

        # --- Notifications ---
        notifications = [
            Notification(
                user_id=alice.id,
                type="quote_received",
                title="Nouveau devis recu",
                body="ESAT Les Saveurs Solidaires vous a envoye un devis pour votre dejeuner.",
                related_entity_type="quote",
                related_entity_id=quote_sent.id,
            ),
            Notification(
                user_id=user_ea.id,
                type="new_message",
                title="Nouveau message",
                body="Bob Martin vous a envoye un message.",
                related_entity_type="message",
                related_entity_id=messages[2].id,
            ),
            Notification(
                user_id=bob.id,
                type="order_confirmed",
                title="Commande confirmee",
                body="Votre commande pour le diner du RH a ete confirmee.",
                related_entity_type="order",
                related_entity_id=order.id,
            ),
        ]
        db.add_all(notifications)

    print("Seed data created:")
    print(f"  Companies: Acme Solutions, TechCorp France")
    print(f"  Services: Direction, Marketing (Acme), RH (TechCorp)")
    print(f"  Users: alice@acme-solutions.fr, bob@techcorp.fr, claire@acme-solutions.fr")
    print(f"  Caterers: ESAT Les Saveurs Solidaires, EA Traiteur & Co, EI Delices Engages")
    print(f"  Caterer users: contact@saveurs-solidaires.fr, contact@traiteur-co.fr, contact@delices-engages.fr")
    print(f"  Quote requests: 1 draft, 1 sent_to_caterers, 1 completed")
    print(f"  Quotes: 1 sent, 1 accepted")
    print(f"  Orders: 1 confirmed")
    print(f"  Messages: 3")
    print(f"  Notifications: 3")
    print(f"  All passwords: password123")


if __name__ == "__main__":
    # Schema management lives in alembic — run `alembic upgrade head` first.
    seed()
