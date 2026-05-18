"""Application configuration sourced from environment / .env files.

`SECRET_KEY` and `DATABASE_URL` are required at startup — there is no
default fallback. This is deliberate: a missing key must crash the
process at boot rather than silently signing sessions with a known
string in production.
"""

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _empty_to_none(v):
    """Coerce empty strings (common when docker-compose passes ${VAR:-}) to None."""
    if isinstance(v, str) and v == "":
        return None
    return v


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    secret_key: SecretStr = Field(min_length=32)
    database_url: str

    @field_validator("database_url", mode="before")
    @classmethod
    def _fix_postgres_scheme(cls, v: str) -> str:
        if isinstance(v, str) and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql://", 1)
        return v

    # Optional in dev (unit tests stub the broker), required wherever the
    # background worker runs — the app side will only enqueue jobs if set.
    redis_url: str | None = None

    stripe_secret_key: SecretStr | None = None
    stripe_publishable_key: str | None = None
    stripe_webhook_secret: SecretStr | None = None
    stripe_connect_client_id: str | None = None

    admin_email: str = "admin@traiteurs-engages.fr"
    admin_initial_password: SecretStr | None = None

    # Object storage credentials. On Scalingo we ship the values under
    # the `SCW_*` env-var names (so an ops person sees them clearly as
    # Scaleway-specific), but the application stays provider-neutral —
    # `S3_*` is also accepted, which keeps local dev / future moves
    # (e.g. to MinIO for CI) trivial. `AliasChoices` matches the first
    # name found at runtime.
    s3_bucket: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SCW_S3_BUCKET", "S3_BUCKET"),
    )
    s3_region: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SCW_S3_REGION", "S3_REGION"),
    )
    s3_access_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SCW_ACCESS_KEY", "S3_ACCESS_KEY"),
    )
    s3_secret_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("SCW_SECRET_KEY", "S3_SECRET_KEY"),
    )
    s3_endpoint_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SCW_S3_ENDPOINT_URL", "S3_ENDPOINT_URL"),
    )
    # Kept for completeness when serving objects through a CDN/public
    # URL instead of the Flask proxy. Unused today (we proxy via Flask),
    # but the field stays so future code paths can opt in without a
    # schema migration.
    s3_public_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SCW_S3_PUBLIC_URL", "S3_PUBLIC_URL"),
    )

    # 4 gunicorn workers x 2 threads = 8 concurrent requests per worker max.
    # pool_size=10 + max_overflow=10 keeps each worker's pool ahead of demand
    # without blowing past Postgres `max_connections` (4 workers * 20 = 80).
    db_pool_size: int = 10
    db_pool_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

    # Audit H-13 (2026-05-13): default flipped to True so HTTPS deployments
    # don't lose Secure cookies + HSTS because the operator forgot the
    # env var. Local dev (HTTP) MUST set SECURE_COOKIES=false explicitly
    # — docker-compose passes `${SECURE_COOKIES:-}` which the validator
    # below coerces to False on empty input, preserving local behaviour.
    secure_cookies: bool = True
    # Only True behind a reverse proxy: with the flag on, direct clients
    # can otherwise spoof X-Forwarded-For to bypass rate limits.
    trust_proxy_headers: bool = False

    # Off = la livraison d'une commande ne déclenche PAS de facture Stripe ;
    # l'admin pilote `delivered → invoiced → paid` manuellement depuis
    # /admin/orders/<id>/transition et la facturation se fait hors plateforme.
    # L'onboarding Stripe Connect des traiteurs reste actif quel que soit le flag.
    billing_enabled: bool = False

    # Brevo (formerly Sendinblue) transactional email API. When the key
    # is unset, services.email logs the would-be email instead of sending
    # — keeps local dev / unit tests workable without a real account.
    brevo_api_key: SecretStr | None = None
    mail_from_email: str = "noreply@les-traiteurs-engages.fr"
    mail_from_name: str = "Les Traiteurs Engagés"
    # Public origin used to build absolute URLs in emails (password reset
    # links, order links). Falls back to localhost in dev.
    base_url: str = "http://localhost:8000"

    # Comma-separated list of super_admin emails that regular users
    # (client/caterer) are allowed to address without a prior business
    # relationship. When unset, every active super_admin is contactable —
    # backwards-compatible with the v1 messagerie. When set, only the
    # listed inbox is exposed as a support contact; messages to any other
    # super_admin still require an active order/QR gate.
    support_user_emails: str | None = None

    @field_validator(
        "stripe_secret_key",
        "stripe_publishable_key",
        "stripe_webhook_secret",
        "stripe_connect_client_id",
        "admin_initial_password",
        "s3_bucket",
        "s3_region",
        "s3_access_key",
        "s3_secret_key",
        "s3_endpoint_url",
        "s3_public_url",
        "brevo_api_key",
        mode="before",
    )
    @classmethod
    def _opt_empty_to_none(cls, v):
        return _empty_to_none(v)

    @field_validator("mail_from_email", "mail_from_name", "base_url", mode="before")
    @classmethod
    def _mail_empty_to_default(cls, v, info):
        # Empty strings from docker-compose interpolation (`${VAR:-}`)
        # land here as "" before Pydantic applies the field default.
        # Substitute the default explicitly so the field stays non-Optional.
        defaults = {
            "mail_from_email": "noreply@les-traiteurs-engages.fr",
            "mail_from_name": "Les Traiteurs Engagés",
            "base_url": "http://localhost:8000",
        }
        if isinstance(v, str) and v == "":
            return defaults[info.field_name]
        return v

    @field_validator("admin_email", mode="before")
    @classmethod
    def _email_empty_to_default(cls, v):
        return v if (isinstance(v, str) and v) else "admin@traiteurs-engages.fr"

    @field_validator(
        "secure_cookies", "trust_proxy_headers", "billing_enabled", mode="before"
    )
    @classmethod
    def _bool_empty_to_false(cls, v):
        if isinstance(v, str) and v == "":
            return False
        return v


settings = Settings()


# Backwards-compatible module-level constants for code that imports
# `config.SECRET_KEY` etc. SecretStr values are unwrapped at the boundary.
SECRET_KEY = settings.secret_key.get_secret_value()
DATABASE_URL = settings.database_url
STRIPE_SECRET_KEY = (
    settings.stripe_secret_key.get_secret_value() if settings.stripe_secret_key else ""
)
STRIPE_PUBLISHABLE_KEY = settings.stripe_publishable_key or ""
STRIPE_WEBHOOK_SECRET = (
    settings.stripe_webhook_secret.get_secret_value()
    if settings.stripe_webhook_secret
    else ""
)
STRIPE_CONNECT_CLIENT_ID = settings.stripe_connect_client_id or ""

BREVO_API_KEY = (
    settings.brevo_api_key.get_secret_value() if settings.brevo_api_key else ""
)
MAIL_FROM_EMAIL = settings.mail_from_email
MAIL_FROM_NAME = settings.mail_from_name
BASE_URL = settings.base_url.rstrip("/")
SUPPORT_USER_EMAILS = frozenset(
    e.strip().lower()
    for e in (settings.support_user_emails or "").split(",")
    if e.strip()
)
