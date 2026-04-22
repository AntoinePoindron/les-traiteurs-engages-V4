from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker

import config

engine = create_engine(config.DATABASE_URL)
session_factory = sessionmaker(bind=engine)
ScopedSession = scoped_session(session_factory)


def init_db():
    """Create all tables from metadata."""
    from models import Base

    Base.metadata.create_all(engine)


@contextmanager
def get_session():
    """Yield a SQLAlchemy session, rolling back on error."""
    session: Session = ScopedSession()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        ScopedSession.remove()
