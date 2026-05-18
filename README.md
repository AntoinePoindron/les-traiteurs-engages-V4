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

## Deployment

| Env | Where | How |
|---|---|---|
| local | your machine | `docker compose up` (see [Quick start](#quick-start-docker)) |
| prod | Scalingo | `git push scalingo main` (see [SCALINGO.md](SCALINGO.md)) |

Production runs on **Scalingo** as a Python buildpack app with Postgres
and Redis addons. TLS, routing and load balancing are handled by the
Scalingo router — there is no Caddy/nginx in front of gunicorn.
Whitenoise serves `/static/*` at the WSGI layer so static assets don't
consume a gunicorn worker.

Critical reminders for the prod environment on Scalingo:
- `STRIPE_SECRET_KEY` is a **live** key (`sk_live_...`)
- `ENABLE_DEMO_SEED` MUST be unset (no demo accounts in prod)
- `ADMIN_INITIAL_PASSWORD` MUST be unset after first boot — manage admins
  via `scalingo run flask admin {create,reset-password,disable}`
- `S3_*` MUST be set (Scalingo dynos are ephemeral; uploads need S3)

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

Day-to-day super-admin management uses the Flask CLI (no env var needed).
Locally:

```bash
docker compose exec app flask admin create               # interactive prompt
docker compose exec app flask admin reset-password EMAIL # interactive prompt
docker compose exec app flask admin list
docker compose exec app flask admin disable EMAIL        # soft delete (audit trail kept)
```

On Scalingo, swap `docker compose exec app` for `scalingo --app <name> run`.

`ADMIN_INITIAL_PASSWORD` env var bootstrap remains available for first
boot only. Once the platform is live, prefer the CLI: passwords are
typed at the prompt (no shell history, no env exposure) and the policy
from `blueprints/auth.validate_password` is enforced.

## Local dev fixtures

`docker compose exec app python seed_data.py` populates a local DB with
two client companies, three caterers, a few demands and an order. The
seeder refuses to run unless `FLASK_DEBUG=1` (set in
`docker-compose.dev.yml`) or `SEED_FIXTURES_ALLOW=1` is in the
environment, so it can't be triggered accidentally on staging or prod.

> Make sure the dev overlay is the one running — `.dockerignore` strips
> `seed_data.py` from prod-style images, so the command above only
> resolves when the bind-mount from `docker-compose.dev.yml` is active.

The accounts it creates all share the same throwaway password. Read
[`seed_data.py`](seed_data.py) to find it — it is **not** documented
here on purpose: a previous audit (C-3, 2026-05-13) flagged this README
as a single-Google-search away from compromising the demo platform.

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
