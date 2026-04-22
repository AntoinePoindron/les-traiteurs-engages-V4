import bcrypt
from sqlalchemy import select

from database import get_session, init_db
from models import User, UserRole


def create_default_admin():
    with get_session() as session:
        existing = session.scalar(select(User).where(User.role == UserRole.super_admin))
        if existing:
            print(f"Super admin already exists: {existing.email}")
            return

        password_hash = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode()
        admin = User(
            email="admin@traiteurs-engages.fr",
            password_hash=password_hash,
            first_name="Admin",
            last_name="Plateforme",
            role=UserRole.super_admin,
            is_active=True,
        )
        session.add(admin)
        print("Default super admin created: admin@traiteurs-engages.fr")


if __name__ == "__main__":
    init_db()
    print("Tables created.")
    create_default_admin()
