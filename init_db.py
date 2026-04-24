import bcrypt
from sqlalchemy import select

from config import settings
from database import get_session, init_db
from models import User, UserRole


def create_default_admin():
    """Create the first super-admin from env vars.

    Requires both ADMIN_EMAIL (defaulted in config) and ADMIN_INITIAL_PASSWORD.
    If ADMIN_INITIAL_PASSWORD is unset, this is a no-op — operators must
    provision the first admin manually (e.g., via a CLI or DB tool).
    """
    if settings.admin_initial_password is None:
        print(
            "ADMIN_INITIAL_PASSWORD not set; skipping default admin creation. "
            "Provision the super-admin manually."
        )
        return

    with get_session() as session:
        existing = session.scalar(select(User).where(User.role == UserRole.super_admin))
        if existing:
            print(f"Super admin already exists: {existing.email}")
            return

        password = settings.admin_initial_password.get_secret_value()
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        admin = User(
            email=settings.admin_email,
            password_hash=password_hash,
            first_name="Admin",
            last_name="Plateforme",
            role=UserRole.super_admin,
            is_active=True,
        )
        session.add(admin)
        print(f"Default super admin created: {settings.admin_email}")


if __name__ == "__main__":
    init_db()
    print("Tables created.")
    create_default_admin()
