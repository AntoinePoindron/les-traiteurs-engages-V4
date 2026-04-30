from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker

import config

engine = create_engine(
    config.DATABASE_URL,
    pool_size=config.settings.db_pool_size,
    max_overflow=config.settings.db_pool_max_overflow,
    pool_timeout=config.settings.db_pool_timeout,
    pool_recycle=config.settings.db_pool_recycle,
    pool_pre_ping=True,
)
session_factory = sessionmaker(bind=engine)
ScopedSession = scoped_session(session_factory)


def get_db() -> Session:
    """Return the current scoped session (one per request/thread)."""
    return ScopedSession()


@contextmanager
def get_session():
    """Standalone session context for scripts (init_db, seed, etc.)."""
    session: Session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
