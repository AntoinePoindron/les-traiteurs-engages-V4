# Les Traiteurs Engages

Plateforme de mise en relation entre entreprises et traiteurs de l'economie sociale et solidaire (ESAT, EA, EI, ACI). Permet aux entreprises de publier des demandes de devis, recevoir et comparer des propositions, passer commande, et valoriser leurs achats OETH/AGEFIPH.

## Quick start (Docker)

```bash
docker-compose up
# Visit http://localhost:8000
```

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
