import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///traiteurs.db")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_CONNECT_CLIENT_ID = os.getenv("STRIPE_CONNECT_CLIENT_ID", "")
