# Technical Plan — Les Traiteurs Engagés

## Architecture

- **Backend** : Python 3.11+ avec Flask (léger, suffisant pour ce type d'app CRUD+formulaires)
- **ORM** : SQLAlchemy 2.0 (style `select()`, `session.scalars()`)
- **Base** : PostgreSQL (via `DATABASE_URL` ou SQLite pour le dev local)
- **Frontend** : Jinja2 templates + Tailwind CSS 4 (palette warm, Fraunces/Marianne, Lucide icons) + JavaScript vanilla
- **HTTP** : httpx (pour appels externes : Stripe, Nominatim)
- **Paiements** : Stripe Connect V2 (API REST via httpx, pas de SDK Python)
- **Géocodage** : Nominatim (OpenStreetMap, gratuit, sans clé)

Pas de SPA React — on fait du server-side rendering classique avec des formulaires multi-étapes côté serveur et du JS léger pour l'UX (wizard steps, validation temps réel).

## Data Model

### Enums (Python Enum, stockés comme VARCHAR)

```
UserRole: client_admin, client_user, caterer, super_admin
MembershipStatus: pending, active, rejected
QuoteRequestStatus: draft, pending_review, approved, sent_to_caterers, completed, cancelled
QuoteRequestCatererStatus: selected, responded, transmitted_to_client, rejected, closed
QuoteStatus: draft, sent, accepted, refused, expired
OrderStatus: confirmed, in_progress, delivered, invoiced, paid, disputed
InvoiceStatus: pending, paid, overdue
MealType: dejeuner, diner, cocktail, petit_dejeuner, autre
StructureType: ESAT, EA, EI, ACI
```

### Tables

**users**
- id (UUID PK), email, password_hash, first_name, last_name, role (UserRole)
- company_id (FK nullable), caterer_id (FK nullable)
- is_active, membership_status, created_at

**companies**
- id (UUID PK), name, siret (unique), address, city, postal_code
- oeth_eligible (bool), budget_annual (decimal), logo_url
- stripe_customer_id, created_at

**company_services**
- id (UUID PK), company_id (FK), name, description, budget_annual

**company_employees**
- id (UUID PK), company_id (FK), first_name, last_name, email, position

**caterers**
- id (UUID PK), name, siret, structure_type (StructureType)
- address, city, postal_code, latitude, longitude
- description, specialties (JSON array), photos (JSON array)
- capacity_min, capacity_max, delivery_radius_km
- is_validated (bool, default false), commission_rate (decimal, default 0.05)
- service_config (JSONB — clés par meal_type, chaque clé: {enabled, description})
- dietary flags: vegetarian, vegan, halal, kosher, gluten_free, organic (tous bool)
- logo_url, invoice_prefix
- stripe_account_id, stripe_charges_enabled, stripe_payouts_enabled, stripe_onboarded_at
- created_at

**quote_requests**
- id (UUID PK), title, client_user_id (FK), company_id (FK), company_service_id (FK nullable)
- event_date, event_start_time, event_end_time
- event_address, event_latitude, event_longitude
- guest_count, budget_global, budget_per_person, budget_flexibility (none/5%/10%)
- service_type, secondary_service_type, meal_type, secondary_meal_type
- is_full_day (bool)
- dietary flags + counts: vegetarian_count, vegan_count, halal_count, kosher_count, gluten_free_count, organic_count
- drinks options: drinks_still_water, drinks_sparkling_water, drinks_soft, drinks_alcohol, drinks_hot, drinks_details
- service options: wants_waitstaff, waitstaff_details, wants_equipment, wants_decoration, wants_setup, setup_time
- description, message_to_caterer
- compare_mode (bool), status (QuoteRequestStatus)
- super_admin_notes, created_at

**quote_request_caterers**
- id (UUID PK), quote_request_id (FK), caterer_id (FK)
- status (QuoteRequestCatererStatus), responded_at, response_rank, refusal_reason

**quotes**
- id (UUID PK), quote_request_id (FK), caterer_id (FK)
- reference (unique), total_amount_ht, amount_per_person
- valorisable_agefiph, details (JSONB — array of line items)
- valid_until, notes, status (QuoteStatus), created_at

**orders**
- id (UUID PK), quote_id (FK unique), client_admin_id (FK)
- status (OrderStatus), delivery_date, delivery_address, notes
- stripe_invoice_id, stripe_hosted_invoice_url, created_at

**payments**
- id (UUID PK), order_id (FK), caterer_id (FK)
- stripe_checkout_session_id, stripe_payment_intent_id, stripe_invoice_id, stripe_charge_id
- amount_cents, application_fee_cents, net_amount_cents
- currency (default EUR), status, succeeded_at, refunded_at, created_at

**invoices**
- id (UUID PK), esat_invoice_ref, order_id (FK), caterer_id (FK)
- amount_ht, tva_rate, amount_ttc, valorisable_agefiph, esat_mention
- status (InvoiceStatus), created_at

**commission_invoices**
- id (UUID PK), invoice_number (int, sequential from 1000)
- order_id (FK), party (client/caterer)
- amount_ht, tva_rate (default 0.20), amount_ttc
- status (InvoiceStatus), created_at

**notifications**
- id (UUID PK), user_id (FK), type, title, body
- is_read (bool), related_entity_type, related_entity_id, created_at

**messages**
- id (UUID PK), thread_id, sender_id (FK), recipient_id (FK)
- order_id (FK nullable), quote_request_id (FK nullable)
- body, is_read (bool), created_at

## API / Pages

### Auth (public)
- `GET /login` — formulaire login
- `POST /login` — authentification
- `GET /signup` — formulaire inscription (choix client/traiteur)
- `POST /signup/client` — inscription client (avec SIRET)
- `POST /signup/caterer` — inscription traiteur
- `GET /logout` — déconnexion
- `GET /reset-password` — demande de reset

### Client Dashboard
- `GET /client/dashboard` — tableau de bord client
- `GET /client/requests` — mes demandes de devis
- `GET /client/requests/new` — wizard nouvelle demande (7 étapes via query param ?step=1..7)
- `POST /client/requests/new` — soumission du wizard (sauvegarde à chaque étape)
- `GET /client/requests/<id>` — détail d'une demande + devis reçus
- `POST /client/requests/<id>/accept-quote` — accepter un devis
- `POST /client/requests/<id>/refuse-quote` — refuser un devis
- `GET /client/orders` — mes commandes
- `GET /client/orders/<id>` — détail commande
- `GET /client/search` — recherche traiteurs
- `GET /client/caterers/<id>` — fiche traiteur
- `GET /client/messages` — messagerie
- `GET /client/team` — gestion équipe (admin only)
- `POST /client/team/approve/<id>` — approuver un membre
- `POST /client/team/reject/<id>` — refuser un membre
- `GET /client/settings` — paramètres entreprise
- `GET /client/profile` — profil utilisateur

### Caterer Dashboard
- `GET /caterer/dashboard` — tableau de bord traiteur
- `GET /caterer/requests` — demandes reçues
- `GET /caterer/requests/<id>` — détail demande
- `POST /caterer/requests/<id>/respond` — marquer comme répondu
- `POST /caterer/requests/<id>/refuse` — refuser
- `GET /caterer/quotes/new?request=<id>` — éditeur de devis
- `POST /caterer/quotes` — sauvegarder/envoyer devis
- `GET /caterer/orders` — mes commandes
- `GET /caterer/orders/<id>` — détail commande
- `POST /caterer/orders/<id>/status` — mettre à jour le statut
- `GET /caterer/profile` — éditer profil
- `POST /caterer/profile` — sauvegarder profil
- `GET /caterer/stripe/onboarding` — démarrer onboarding Stripe
- `GET /caterer/stripe/return` — retour après onboarding
- `GET /caterer/messages` — messagerie

### Admin Dashboard
- `GET /admin/dashboard` — KPIs et stats
- `GET /admin/qualification` — demandes à qualifier
- `GET /admin/qualification/<id>` — détail demande
- `POST /admin/qualification/<id>/approve` — approuver + matching
- `POST /admin/qualification/<id>/reject` — rejeter
- `GET /admin/caterers` — gestion traiteurs
- `POST /admin/caterers/<id>/validate` — valider traiteur
- `GET /admin/companies` — gestion entreprises
- `GET /admin/payments` — suivi paiements
- `GET /admin/messages` — messagerie admin

### API (JSON)
- `POST /api/webhooks/stripe` — webhook Stripe (signature HMAC)
- `GET /api/geocode?q=<address>` — proxy Nominatim
- `POST /api/messages` — envoyer message (AJAX)
- `GET /api/notifications` — notifications non-lues (AJAX)
- `POST /api/notifications/<id>/read` — marquer comme lue

### Santé
- `GET /health` — healthcheck (pas d'appel externe)

## Dependencies

### Python (requirements.txt)
```
flask>=3.0
sqlalchemy>=2.0
alembic
psycopg2-binary
httpx
python-dotenv
werkzeug
gunicorn
stripe
```

### Frontend
- Tailwind CSS 4 via CDN (https://cdn.tailwindcss.com) avec configuration custom (palette warm, polices)
- Pas de npm, pas de build JS — JS vanilla inline ou fichiers statiques
- Polices Google Fonts : Fraunces (titres serif) + Marianne (corps sans-serif)
- Lucide icons via CDN (SVG inline)

### Services externes
- PostgreSQL (local ou managé)
- Stripe Connect (compte plateforme requis, clés via env vars)
- Nominatim (gratuit, rate-limited)

## LLM Integration

Pas d'intégration LLM dans le MVP. Potentiel futur : aide à la rédaction de menus, suggestion automatique de tarifs, chatbot support.

## Deployment

### Dockerfile
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "2", "app:create_app()"]
```

### docker-compose.yml
```yaml
services:
  app:
    build: .
    ports:
      - "${HOST_PORT:-8000}:8000"
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@db:5432/traiteurs
      - SECRET_KEY=${SECRET_KEY:-dev-secret}
      - STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY}
      - STRIPE_WEBHOOK_SECRET=${STRIPE_WEBHOOK_SECRET}
      - STRIPE_PUBLISHABLE_KEY=${STRIPE_PUBLISHABLE_KEY}
    depends_on:
      - db
  db:
    image: postgres:16
    environment:
      - POSTGRES_DB=traiteurs
      - POSTGRES_PASSWORD=postgres
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

### Variables d'environnement
| Variable | Obligatoire | Description |
|---|---|---|
| `DATABASE_URL` | oui | URL PostgreSQL |
| `SECRET_KEY` | oui | Clé de session Flask |
| `STRIPE_SECRET_KEY` | oui (prod) | Clé secrète Stripe |
| `STRIPE_PUBLISHABLE_KEY` | oui (prod) | Clé publique Stripe |
| `STRIPE_WEBHOOK_SECRET` | oui (prod) | Secret webhook Stripe |

### Structure des fichiers
```
/app/data/projects/bright-brook/
├── app.py                  # Factory Flask (create_app)
├── config.py               # Lecture env vars
├── models.py               # SQLAlchemy models (toutes les tables)
├── database.py             # Engine, session, init_db
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── static/
│   ├── css/
│   │   └── app.css         # Styles custom (palette warm, scrollbars, composants)
│   └── js/
│       ├── wizard.js       # Logique wizard multi-étapes
│       ├── quote-editor.js # Éditeur de devis interactif
│       └── messages.js     # Messagerie AJAX
├── templates/
│   ├── base.html           # Layout Tailwind (palette warm, sidebar role-aware)
│   ├── auth/
│   │   ├── login.html
│   │   └── signup.html
│   ├── client/
│   │   ├── dashboard.html
│   │   ├── requests/
│   │   ├── orders/
│   │   ├── search.html
│   │   ├── team.html
│   │   └── ...
│   ├── caterer/
│   │   ├── dashboard.html
│   │   ├── requests/
│   │   ├── quote_editor.html
│   │   ├── profile.html
│   │   └── ...
│   └── admin/
│       ├── dashboard.html
│       ├── qualification.html
│       └── ...
├── blueprints/
│   ├── auth.py             # Routes auth
│   ├── client.py           # Routes client
│   ├── caterer.py          # Routes caterer
│   ├── admin.py            # Routes admin
│   ├── api.py              # Routes API (webhooks, AJAX)
│   └── middleware.py       # Décorateurs auth/rôle
├── services/
│   ├── matching.py         # Algorithme matching traiteurs (haversine)
│   ├── stripe_service.py   # Intégration Stripe Connect
│   ├── geocoding.py        # Proxy Nominatim
│   ├── notifications.py    # Création notifications
│   └── quotes.py           # Logique devis (référence, calculs TVA, règle des 3)
└── alembic/
    └── ...                 # Migrations
```
