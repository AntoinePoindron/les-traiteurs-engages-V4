# Deploying on Scalingo

## Prerequisites

- A Scalingo account
- The [Scalingo CLI](https://doc.scalingo.com/platform/cli/start) installed
- A Stripe account (optional — leave keys empty to disable billing features)

## Quick Start

```bash
# Create the app
scalingo create les-traiteurs-engages

# Add required addons
scalingo --app les-traiteurs-engages addons-add postgresql postgresql-starter-512
scalingo --app les-traiteurs-engages addons-add redis redis-starter-256
```

Scalingo automatically provisions `DATABASE_URL` and `REDIS_URL` environment
variables when addons are created.

## Environment Variables

Set the required variables:

```bash
scalingo --app les-traiteurs-engages env-set \
  SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')" \
  SECURE_COOKIES=true \
  TRUST_PROXY_HEADERS=true \
  ADMIN_EMAIL=admin@traiteurs-engages.fr \
  ADMIN_INITIAL_PASSWORD=your-bootstrap-password
```

Optional Stripe variables (leave unset to disable Stripe):

```bash
scalingo --app les-traiteurs-engages env-set \
  STRIPE_SECRET_KEY=sk_live_... \
  STRIPE_PUBLISHABLE_KEY=pk_live_... \
  STRIPE_WEBHOOK_SECRET=whsec_... \
  STRIPE_CONNECT_CLIENT_ID=ca_...
```

## Deploy

```bash
git remote add scalingo git@ssh.osc-fr1.scalingo.com:les-traiteurs-engages.git
git push scalingo main
```

Scalingo detects the Python buildpack via `requirements.txt` and `runtime.txt`.

## Process Types

Defined in `Procfile`:

| Process | Command | Scalingo container size |
|---------|---------|------------------------|
| `web`   | gunicorn (Flask app) | M |
| `worker` | dramatiq (background Stripe billing jobs) | S |

Scale the worker after first deploy:

```bash
scalingo --app les-traiteurs-engages scale worker:1:S
```

## Post-Deploy

Migrations (`alembic upgrade head`) and admin bootstrap (`init_db.py`) run
automatically via the `postdeploy` script in `scalingo.json` on every deploy.

## Health Check

The app exposes `GET /health` which checks the database connection and returns
HTTP 200. Configure Scalingo's health check to use this endpoint.

## File Uploads (S3)

Uploads are stored on S3-compatible object storage when `S3_BUCKET` is set.
Without it, files fall back to local disk (dev only — ephemeral on Scalingo).

Any S3-compatible provider works (Scaleway, AWS, MinIO, etc.). Example with
Scaleway Object Storage:

```bash
scalingo --app les-traiteurs-engages env-set \
  S3_BUCKET=les-traiteurs-engages-uploads \
  S3_REGION=fr-par \
  S3_ACCESS_KEY=SCWXXXXXXXXXXXXXXXXX \
  S3_SECRET_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
  S3_ENDPOINT_URL=https://s3.fr-par.scw.cloud \
  S3_PUBLIC_URL=https://les-traiteurs-engages-uploads.s3.fr-par.scw.cloud
```

The bucket must exist and have a **public read** policy for uploaded objects
(images are served directly to browsers via `<img src="...">`).

## Architecture on Scalingo

```
Internet
  |
Scalingo Router (TLS termination)
  |
  +-- web container (gunicorn + Flask)
  |       |
  |       +-- PostgreSQL addon (DATABASE_URL)
  |       +-- Redis addon (REDIS_URL)
  |       +-- S3 object storage (uploads)
  |
  +-- worker container (dramatiq)
          |
          +-- PostgreSQL addon
          +-- Redis addon
```

Scalingo handles TLS, routing, and load balancing. The Caddy reverse proxy
from the Docker Compose setup is not needed.
