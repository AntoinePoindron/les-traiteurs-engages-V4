"""Application configuration sourced from environment / .env files.

`SECRET_KEY` and `DATABASE_URL` are required at startup — there is no
default fallback. This is deliberate: a missing key must crash the
process at boot rather than silently signing sessions with a known
string in production.
"""
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".deploy.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    secret_key: SecretStr = Field(min_length=32)
    database_url: str

    stripe_secret_key: SecretStr | None = None
    stripe_publishable_key: str | None = None
    stripe_webhook_secret: SecretStr | None = None
    stripe_connect_client_id: str | None = None

    admin_email: str = "admin@traiteurs-engages.fr"
    admin_initial_password: SecretStr | None = None


settings = Settings()


# Backwards-compatible module-level constants for code that imports
# `config.SECRET_KEY` etc. SecretStr values are unwrapped at the boundary.
SECRET_KEY = settings.secret_key.get_secret_value()
DATABASE_URL = settings.database_url
STRIPE_SECRET_KEY = settings.stripe_secret_key.get_secret_value() if settings.stripe_secret_key else ""
STRIPE_PUBLISHABLE_KEY = settings.stripe_publishable_key or ""
STRIPE_WEBHOOK_SECRET = settings.stripe_webhook_secret.get_secret_value() if settings.stripe_webhook_secret else ""
STRIPE_CONNECT_CLIENT_ID = settings.stripe_connect_client_id or ""
