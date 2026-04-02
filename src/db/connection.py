"""Database connection and session management.

Provides a SQLAlchemy engine and session factory configured from application
settings. All DB operations should use the get_session() context manager to
ensure connections are properly released back to the pool.
"""

from contextlib import contextmanager
from typing import Generator

import structlog
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from src.config import settings
from src.models.claim import Base

logger = structlog.get_logger(__name__)

engine = create_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    pool_pre_ping=True,  # Verify connections before use
    echo=(settings.environment == "development"),
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Provide a transactional database session.

    Yields a SQLAlchemy Session and commits on clean exit, or rolls back on
    exception. Always releases the connection back to the pool on exit.

    Yields:
        Session: An active SQLAlchemy session.

    Raises:
        Exception: Re-raises any exception after rolling back the transaction.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("db.session.rollback")
        raise
    finally:
        session.close()


def create_all_tables() -> None:
    """Create all database tables defined in the ORM models.

    Should only be called during initial setup or in tests. In production,
    use SQL migrations in src/db/migrations/ instead.

    Returns:
        None
    """
    Base.metadata.create_all(bind=engine)
    logger.info("db.tables.created")
