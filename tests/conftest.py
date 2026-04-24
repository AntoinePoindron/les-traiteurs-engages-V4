"""Test fixtures.

Tests run against a real Postgres database (the same dev container) so
features like sequences, NUMERIC, and constraints behave identically to
production. Run via:

    docker compose exec app pytest

Each session creates a fresh `traiteurs_test` database, applies all
Alembic migrations, then seeds known users for role-based tests.
"""
import os

import bcrypt
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def _ensure_test_db():
    """Drop + recreate the test database from the parent server."""
    parent_url = os.environ.get("DATABASE_URL", "postgresql://traiteurs:traiteurs@db:5432/traiteurs")
    test_db_name = "traiteurs_test"
    parent_engine = create_engine(parent_url, isolation_level="AUTOCOMMIT")
    with parent_engine.connect() as conn:
        # Disconnect anyone holding the test DB open before dropping
        conn.execute(text(
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{test_db_name}' AND pid <> pg_backend_pid()"
        ))
        conn.execute(text(f"DROP DATABASE IF EXISTS {test_db_name}"))
        conn.execute(text(f"CREATE DATABASE {test_db_name}"))
    parent_engine.dispose()
    test_url = parent_url.rsplit("/", 1)[0] + f"/{test_db_name}"
    return test_url


@pytest.fixture(scope="session", autouse=True)
def _required_env():
    """Provide SECRET_KEY + a clean test DB url before any app import."""
    os.environ.setdefault("SECRET_KEY", "x" * 32)
    test_url = _ensure_test_db()
    os.environ["DATABASE_URL"] = test_url
    os.environ.pop("STRIPE_SECRET_KEY", None)
    yield


@pytest.fixture(scope="session")
def app(_required_env):
    # Late import — config.Settings() runs at import and needs SECRET_KEY/DATABASE_URL.
    from alembic import command
    from alembic.config import Config as AlembicConfig

    alembic_cfg = AlembicConfig("alembic.ini")
    command.upgrade(alembic_cfg, "head")

    from app import create_app
    flask_app = create_app()
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
    )
    # Kill the rate limiter for tests — otherwise the 10/min login limit
    # collides with the 23 parametrised logins this suite performs.
    from extensions import limiter
    limiter.enabled = False

    with flask_app.app_context():
        _seed_users()
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _seed_users():
    from database import engine
    from models import Caterer, CatererStructureType, Company, User, UserRole
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        if s.query(User).count() > 0:
            return
        pwhash = bcrypt.hashpw(b"testpass", bcrypt.gensalt()).decode()
        company = Company(name="ACME Test", siret="12345678901234")
        s.add(company)
        s.flush()
        caterer = Caterer(
            name="Test Caterer",
            siret="98765432109876",
            structure_type=CatererStructureType.ESAT,
            invoice_prefix="TST",
            is_validated=True,
        )
        s.add(caterer)
        s.flush()
        s.add_all([
            User(email="admin@test.local", password_hash=pwhash,
                 first_name="A", last_name="A", role=UserRole.super_admin),
            User(email="alice@test.local", password_hash=pwhash,
                 first_name="A", last_name="L", role=UserRole.client_admin,
                 company_id=company.id),
            User(email="bob@test.local", password_hash=pwhash,
                 first_name="B", last_name="B", role=UserRole.client_user,
                 company_id=company.id),
            User(email="cook@test.local", password_hash=pwhash,
                 first_name="C", last_name="K", role=UserRole.caterer,
                 caterer_id=caterer.id),
        ])
        s.commit()
    finally:
        s.close()


@pytest.fixture
def login(client):
    """Log `client` in as a known seeded user. CSRF is disabled in tests."""
    def _login(email, password="testpass"):
        return client.post("/login", data={"email": email, "password": password},
                           follow_redirects=False)
    return _login
