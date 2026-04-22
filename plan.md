# Les Traiteurs Engages — Plan technique

## Stack

| Composant | Choix |
|---|---|
| Backend | Flask (blueprints) |
| ORM | SQLAlchemy 2.0 (select style) |
| Base de donnees | PostgreSQL (via DATABASE_URL) |
| Templates | Jinja2 + Tailwind CSS 4 (palette warm, Fraunces/Marianne, Lucide icons) |
| JS | Vanilla JS (pas de framework frontend) |
| HTTP client | httpx (Stripe API, geocodage) |
| Auth | Sessions Flask (flask-login ou session cookie signee) |
| Paiements | Stripe API directe via httpx |
| Geocodage | Nominatim (OpenStreetMap) |
| Fichiers | Upload local dans data/interactive/uploads/ |

## Architecture

```
data/interactive/traiteurs/
  app.py              # Point d'entree Flask
  config.py           # Variables d'environnement
  models.py           # Tous les modeles SQLAlchemy
  auth.py             # Blueprint auth (login, signup, logout, middleware)
  views/
    client.py         # Blueprint client (dashboard, requests, orders, team, search)
    caterer.py        # Blueprint caterer (dashboard, profile, requests, quotes, orders, stripe)
    admin.py          # Blueprint admin (dashboard, qualification, caterers, companies, payments, stats, messages)
    api.py            # Blueprint API (webhooks Stripe)
  services/
    matching.py       # Matching geographique (haversine) + filtres
    stripe_service.py # Onboarding, invoices, webhooks, customers, tax rates
    geocoding.py      # Geocodage Nominatim
    slugs.py          # Generation invoice_prefix unique
    quotes.py         # Logique devis (references, calculs)
  templates/
    base.html         # Layout Tailwind avec sidebar role-aware (palette warm)
    auth/             # login.html, signup.html
    client/           # dashboard, requests/, orders/, team, search, settings, profile
    caterer/          # dashboard, profile, requests/, orders/, stripe
    admin/            # dashboard, qualification/, caterers/, companies/, payments, stats, messages
    components/       # Partials reutilisables (status_badge, modals, forms)
  static/
    css/              # Tailwind output + variables custom (palette warm)
    js/               # Wizard multi-etapes, editeur devis, messaging, uploads
```

## Modeles SQLAlchemy

### Enums

```python
class UserRole(str, Enum):
    client_admin = "client_admin"
    client_user = "client_user"
    caterer = "caterer"
    super_admin = "super_admin"

class MembershipStatus(str, Enum):
    pending = "pending"
    active = "active"
    rejected = "rejected"

class CatererStructureType(str, Enum):
    ESAT = "ESAT"
    EA = "EA"
    EI = "EI"
    ACI = "ACI"

class QuoteRequestStatus(str, Enum):
    draft = "draft"
    pending_review = "pending_review"
    approved = "approved"
    sent_to_caterers = "sent_to_caterers"
    completed = "completed"
    cancelled = "cancelled"
    quotes_refused = "quotes_refused"

class QRCStatus(str, Enum):
    selected = "selected"
    responded = "responded"
    transmitted_to_client = "transmitted_to_client"
    rejected = "rejected"
    closed = "closed"

class QuoteStatus(str, Enum):
    draft = "draft"
    sent = "sent"
    accepted = "accepted"
    refused = "refused"
    expired = "expired"

class OrderStatus(str, Enum):
    confirmed = "confirmed"
    delivered = "delivered"
    invoiced = "invoiced"
    paid = "paid"
    disputed = "disputed"

class MealType(str, Enum):
    dejeuner = "dejeuner"
    diner = "diner"
    cocktail = "cocktail"
    petit_dejeuner = "petit_dejeuner"
    autre = "autre"

class PaymentStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    succeeded = "succeeded"
    failed = "failed"
    refunded = "refunded"
    canceled = "canceled"
```

### Tables (15)

1. **users** — id, email, password_hash, first_name, last_name, role (UserRole), company_id (FK), caterer_id (FK), is_active, membership_status, stripe_customer_id, created_at, updated_at
2. **companies** — id, name, siret, address, city, zip_code, oeth_eligible, budget_annual, logo_url, created_at
3. **caterers** — id, name, siret, structure_type (CatererStructureType), address, city, zip_code, latitude, longitude, description, specialties (ARRAY), photos (ARRAY), capacity_min, capacity_max, is_validated, commission_rate, logo_url, delivery_radius_km, dietary_vegetarian/vegan/halal/casher/gluten_free/lactose_free (booleans), service_config (JSON), stripe_account_id, stripe_onboarded_at, stripe_charges_enabled, stripe_payouts_enabled, invoice_prefix, created_at, updated_at
4. **company_services** — id, company_id (FK), name, description, annual_budget
5. **company_employees** — id, company_id (FK), service_id (FK), first_name, last_name, email, position, invited_at, user_id (FK)
6. **quote_requests** — id, company_id (FK), user_id (FK), company_service_id (FK), status (QuoteRequestStatus), service_type, meal_type (MealType), event_date, guest_count, event_address, event_city, event_zip_code, event_latitude, event_longitude, budget_global, budget_per_person, dietary_* (booleans + counts), drinks_* (details), service_* (details), service_waitstaff_details, is_compare_mode, message_to_caterer, created_at, updated_at
7. **quote_request_caterers** — id, quote_request_id (FK), caterer_id (FK), status (QRCStatus), responded_at, response_rank
8. **quotes** — id, quote_request_id (FK), caterer_id (FK), reference, total_amount_ht, amount_per_person, valorisable_agefiph, details (JSON), notes, valid_until, status (QuoteStatus), refusal_reason, created_at, updated_at
9. **orders** — id, quote_id (FK), client_admin_id (FK), status (OrderStatus), delivery_date, delivery_address, notes, stripe_invoice_id, stripe_hosted_invoice_url, created_at, updated_at
10. **invoices** — id, order_id (FK), caterer_id (FK), amount_ht, tva_rate, amount_ttc, valorisable_agefiph, esat_mention, created_at
11. **commission_invoices** — id, invoice_number, order_id (FK), party (client/caterer), amount_ht, tva_rate, amount_ttc, created_at
12. **payments** — id, order_id (FK), caterer_id (FK), stripe_checkout_session_id, stripe_payment_intent_id, stripe_invoice_id, stripe_charge_id, status (PaymentStatus), amount_total_cents, application_fee_cents, amount_to_caterer_cents, created_at, updated_at
13. **notifications** — id, user_id (FK), type, title, body, is_read, related_entity_type, related_entity_id, created_at
14. **messages** — id, thread_id, sender_id (FK), recipient_id (FK), order_id (FK), quote_request_id (FK), body, is_read, created_at

## Routes (~55)

### Auth (auth.py)
- GET/POST `/login`
- GET/POST `/signup` (3 parcours)
- GET `/logout`

### Client (client.py) — ~20 routes
- GET `/client/dashboard`
- GET `/client/requests` — liste demandes
- GET `/client/requests/new` — wizard nouvelle demande
- POST `/client/requests/new` — soumettre demande
- GET `/client/requests/<id>` — detail + devis recus
- GET `/client/requests/<id>/edit` — edition demande
- POST `/client/requests/<id>/edit`
- POST `/client/requests/<id>/accept-quote` — accepter devis → creer commande
- POST `/client/requests/<id>/refuse-quote` — refuser devis
- GET `/client/orders` — liste commandes
- GET `/client/orders/<id>` — detail commande
- GET `/client/orders/<id>/invoice` — facture
- POST `/client/orders/<id>/pay` — creer session paiement
- GET `/client/messages` — messagerie
- POST `/client/messages` — envoyer message
- GET `/client/search` — catalogue traiteurs
- GET `/client/caterers/<id>` — fiche traiteur
- GET `/client/team` — gestion equipe
- POST `/client/team/*` — CRUD services/employes/invitations/membership
- GET/POST `/client/settings` — parametres entreprise
- GET/POST `/client/profile` — profil utilisateur

### Caterer (caterer.py) — ~15 routes
- GET `/caterer/dashboard`
- GET/POST `/caterer/profile` — edition profil
- GET `/caterer/requests` — demandes recues
- GET `/caterer/requests/<id>` — detail demande
- GET/POST `/caterer/requests/<id>/quote/new` — creer devis
- GET/POST `/caterer/requests/<id>/quote/<qid>/edit` — editer devis
- POST `/caterer/requests/<id>/quote/<qid>/send` — envoyer devis
- GET `/caterer/orders` — commandes
- GET `/caterer/orders/<id>` — detail commande
- POST `/caterer/orders/<id>/deliver` — marquer livre → generer facture Stripe
- GET `/caterer/orders/<id>/invoice` — facture
- GET `/caterer/messages` — messagerie
- POST `/caterer/messages` — envoyer message
- GET `/caterer/stripe` — statut onboarding
- POST `/caterer/stripe/onboard` — demarrer onboarding
- GET `/caterer/stripe/complete` — callback retour onboarding

### Admin (admin.py) — ~15 routes
- GET `/admin/dashboard` — KPIs
- GET `/admin/qualification` — demandes en attente
- GET `/admin/qualification/<id>` — detail + matching
- POST `/admin/qualification/<id>/approve` — approuver + broadcaster
- POST `/admin/qualification/<id>/reject` — rejeter
- GET `/admin/caterers` — liste traiteurs
- GET `/admin/caterers/<id>` — detail + validation
- POST `/admin/caterers/<id>/validate` — valider
- POST `/admin/caterers/<id>/invalidate` — invalider
- GET `/admin/companies` — liste entreprises
- GET `/admin/companies/<id>` — detail entreprise
- GET `/admin/payments` — monitoring paiements
- GET `/admin/stats` — statistiques
- GET `/admin/messages` — tous les messages

### API (api.py)
- POST `/api/webhooks/stripe` — webhook Stripe (HMAC)

### Public
- GET `/` — landing page (ou redirect dashboard si connecte)

## Services

### matching.py
- Haversine en Python (math.radians, math.sin, math.cos, math.asin, math.sqrt)
- Filtre distance, service_type, capacite, regimes alimentaires
- Tri par proximite

### stripe_service.py
- Onboarding Connect V2 via httpx POST
- Generation facture : lignes groupees par TVA + frais plateforme (5% HT + 20% TVA)
- Destination charges (application_fee_amount + transfer_data.destination)
- Customer management (get_or_create)
- TaxRate cache
- Webhook verification HMAC
- Days until due : 30

### geocoding.py
- Nominatim API via httpx
- Retourne (latitude, longitude) depuis adresse

### slugs.py
- Generation invoice_prefix : 5 chars → 8 chars → 10 chars → numerique
- Verification unicite en base

### quotes.py
- Generation reference : `DEVIS-{prefix}-YYYY-NNN`
- Derivation facture : `FAC-{prefix}-YYYY-NNN`
- Calcul totaux, TVA par taux, AGEFIPH

## Frontend

- **Tailwind CSS 4** avec palette custom via CSS variables :
  - `--color-cream` (#FAF7F2), `--color-terracotta` (#C4714A), `--color-coral-red` (#FF5455)
  - `--color-olive` (#6B7C4A), `--color-navy` (#1A3A52), `--color-navy-light`, grays
  - Scrollbars custom terracotta
- **Polices** : Fraunces (serif, titres/display) + Marianne (sans-serif, corps) — Google Fonts
- **Icones** : Lucide SVG inline (pas de font icons)
- **Composants UI custom** (templates Jinja2 partials) :
  - StatusBadge (21 variantes pour tous les workflows devis/commande)
  - StructureTypeBadge (ESAT/EA/EI/ACI)
  - InfoChip (tags generiques)
  - ConfirmDialog (modale confirmation)
  - BackButton, SubmitButton (avec loading state), ContactCard
- Wizard multi-etapes en JS vanilla (afficher/masquer les etapes, validation)
- Editeur de devis en JS vanilla (ajout/suppression lignes, calcul temps reel)
- Messagerie : polling ou simple refresh
- Upload photos : FormData + fetch
- Modales : dialog HTML natif + styles Tailwind
- Charts admin stats : Chart.js

## Securite

- Decorateurs role-based sur chaque route (`@login_required`, `@role_required(...)`)
- CSRF protection (Flask-WTF ou token manuel)
- Stripe webhook HMAC verification
- Pas d'injection SQL (ORM + parametres nommes)
- Validation SIRET (format 14 chiffres)
- Rate limiting sur login

## Variables d'environnement

Via `os.getenv` dans config.py de l'app :
- `DATABASE_URL` — PostgreSQL
- `SECRET_KEY` — Sessions Flask
- `STRIPE_SECRET_KEY` — API Stripe
- `STRIPE_WEBHOOK_SECRET` — Verification webhooks
- `STRIPE_CONNECT_CLIENT_ID` — OAuth Connect (si applicable)
