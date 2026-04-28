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

## Deployment (staging / prod)

The stack ships in three flavours selected via overlay compose files:

| Env | Compose files | TLS | Cookies | Ports exposed |
|---|---|---|---|---|
| dev (local) | `docker-compose.yml` | none | insecure | 8000 on `0.0.0.0` |
| staging | base + `docker-compose.staging.yml` | Caddy + Let's Encrypt | secure | 80 + 443 only |
| prod | base + `docker-compose.prod.yml` | Caddy + Let's Encrypt | secure | 80 + 443 only |

Both deployed flavours rely on **Caddy** as a reverse-proxy (auto-HTTPS,
HSTS, HTTP/3) in front of gunicorn, and rebind the app to `127.0.0.1:8000`
so only Caddy can reach it.

### Staging deploy

```bash
# One-time: copy the env template, fill in real values
cp .deploy.env.staging.example .deploy.env
# Edit .deploy.env: SECRET_KEY, DATABASE_URL with prod password, Stripe test keys

# Make sure DNS is set: A record for staging.traiteurs.engages.inclusion.gouv.fr
# pointing to the staging server's public IP, BEFORE first start.

docker compose --env-file .deploy.env \
  -f docker-compose.yml \
  -f .deploy-override.yml \
  -f docker-compose.staging.yml \
  up -d --build

# First boot only — provision the super admin via CLI:
docker compose -p traiteurs-staging exec app flask admin create
```

Caddy will request a Let's Encrypt cert on first start. Watch the
logs: `docker compose -p traiteurs-staging logs -f caddy`.

### Prod deploy

Same as staging, but use `.deploy.env.prod.example`,
`docker-compose.prod.yml`, and `traiteurs.engages.inclusion.gouv.fr`.

Critical differences from staging:
- `STRIPE_SECRET_KEY` is a **live** key (`sk_live_...`)
- `ENABLE_DEMO_SEED` MUST be empty (no demo accounts in prod)
- `ADMIN_INITIAL_PASSWORD` MUST be empty after first boot — manage admins
  exclusively via `flask admin {create,reset-password,disable}`

### DNS prerequisite

Before first start, an A record (or CNAME) must point `CADDY_DOMAIN`
at the server's public IP. If Let's Encrypt cannot validate via HTTP-01,
the cert fails to provision and Caddy serves an empty HTTPS endpoint.

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy connection string | `sqlite:///traiteurs.db` |
| `SECRET_KEY` | Flask session secret | `dev-secret-change-me` |
| `STRIPE_SECRET_KEY` | Stripe API secret key | (empty) |
| `STRIPE_PUBLISHABLE_KEY` | Stripe publishable key | (empty) |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret | (empty) |
| `STRIPE_CONNECT_CLIENT_ID` | Stripe Connect client ID | (empty) |

## Admin lifecycle (CLI)

Day-to-day super-admin management uses the Flask CLI (no env var needed):

```bash
docker compose exec app flask admin create               # interactive prompt
docker compose exec app flask admin reset-password EMAIL # interactive prompt
docker compose exec app flask admin list
docker compose exec app flask admin disable EMAIL        # soft delete (audit trail kept)
```

`ADMIN_INITIAL_PASSWORD` env var bootstrap remains available for first
boot only. Once the platform is live, prefer the CLI: passwords are
typed at the prompt (no shell history, no `.deploy.env` exposure) and
the policy from `blueprints/auth.validate_password` is enforced.

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
