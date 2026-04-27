# Les Traiteurs Engages

Plateforme de mise en relation entre entreprises et traiteurs de l'economie sociale et solidaire (ESAT, EA, EI, ACI). Permet aux entreprises de publier des demandes de devis, recevoir et comparer des propositions, passer commande, et valoriser leurs achats OETH/AGEFIPH.

## Quick start (Docker)

```bash
docker-compose up
# Visit http://localhost:8000
```

## Tests

```bash
docker compose exec app pytest
```

The test suite recreates a fresh `traiteurs_test` Postgres database on each run,
applies all Alembic migrations, then exercises auth + per-role page rendering.
Tests must run inside the `app` container so they can reach the `db` service.

## Manual setup

```bash
pip install -r requirements.txt
export DATABASE_URL="sqlite:///traiteurs.db"
export SECRET_KEY="change-me-in-production"
python init_db.py
python seed_data.py
flask run --port 8000
```

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy connection string | `sqlite:///traiteurs.db` |
| `SECRET_KEY` | Flask session secret | `dev-secret-change-me` |
| `STRIPE_SECRET_KEY` | Stripe API secret key | (empty) |
| `STRIPE_PUBLISHABLE_KEY` | Stripe publishable key | (empty) |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret | (empty) |
| `STRIPE_CONNECT_CLIENT_ID` | Stripe Connect client ID | (empty) |

## Default credentials

| Role | Email | Password |
|---|---|---|
| Super admin | admin@traiteurs-engages.fr | admin |
| Client admin (Acme) | alice@acme-solutions.fr | password123 |
| Client admin (TechCorp) | bob@techcorp.fr | password123 |
| Client user | claire@acme-solutions.fr | password123 |
| Caterer (ESAT) | contact@saveurs-solidaires.fr | password123 |
| Caterer (EA) | contact@traiteur-co.fr | password123 |
| Caterer (EI) | contact@delices-engages.fr | password123 |

## Architecture

```
app.py              Flask app factory, landing page, healthcheck
config.py           Environment variables
database.py         SQLAlchemy engine and session management
models.py           All SQLAlchemy models (source of truth for schema)
init_db.py          Create tables and default super admin
seed_data.py        Populate realistic test data

blueprints/
  auth.py           Login, signup, logout
  client.py         Client dashboard, quote requests, orders, team, search
  caterer.py        Caterer dashboard, quote management, Stripe onboarding
  admin.py          Super admin dashboard
  api.py            REST endpoints (messages, notifications, Stripe webhooks)
  middleware.py     login_required, role_required decorators

services/
  quotes.py         Quote reference generation, totals calculation
  slugs.py          Invoice prefix generation
  uploads.py        File upload handling
  notifications.py  Notification creation helpers
  stripe_service.py Stripe Connect integration

templates/          Jinja2 templates
static/             CSS, JS, uploaded files
```

## API endpoints

- `GET /health` -- Healthcheck (database connectivity)
- `GET /api/messages/<thread_id>` -- Fetch messages in a thread
- `POST /api/messages` -- Send a message
- `GET /api/notifications` -- Unread notifications
- `POST /api/notifications/<id>/read` -- Mark notification as read
- `POST /api/webhooks/stripe` -- Stripe webhook receiver

## Stripe billing — two-phase commit

Order delivery splits Stripe invoicing into two committed phases so a
crash between Stripe and our DB cannot leave a customer billed without
a local trace:

1. **Phase 1** (`services.billing.queue_invoice`): persist a `Payment`,
   `Invoice` and `CommissionInvoice` rows locally. No Stripe call.
2. **Phase 2** (`services.billing.send_stripe_invoice`): create the
   Stripe invoice with `idempotency_key=f"payment-{payment.id}"`,
   finalize, send, link the id back. Idempotent — a retry after partial
   failure reuses the same Stripe invoice rather than duplicating it.

If Phase 2 fails (network glitch, Stripe outage, DB commit error after
the SDK call), the `Payment` row stays at `status=pending` with
`stripe_invoice_id IS NULL`. The retry CLI picks these up:

```bash
docker compose exec -T app flask retry-pending-invoices
```

Suggested cron (every 10 minutes):

```cron
*/10 * * * * cd /path/to/traiteurs && docker compose exec -T app flask retry-pending-invoices
```

The CLI selects only payments older than 2 minutes to avoid stepping on
in-flight HTTP requests that just haven't committed Phase 2 yet.
