"""
Database engine, session factory and declarative base.

Uses SQLAlchemy ORM exclusively - no raw SQL with user input - which satisfies
the SQL injection requirement in docs/SECURITY-REQUIREMENTS.md.
"""

import logging
import time
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,      # drop dead connections instead of erroring
    pool_recycle=1800,
    connect_args={"connect_timeout": settings.DB_CONNECT_TIMEOUT},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def wait_for_database(max_attempts: int = 10, delay: float = 1.0) -> bool:
    """
    Block until Postgres accepts connections.

    docker-compose already gates the backend on a Postgres healthcheck, but
    this makes local runs (and container restarts) resilient.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except OperationalError as exc:
            logger.warning(
                "Database not ready (attempt %s/%s): %s", attempt, max_attempts, exc
            )
            time.sleep(delay)
    return False


def init_db() -> None:
    """
    Create every table declared on Base.

    Alembic is configured for later; create_all keeps the startup path simple
    and is safe because it only creates tables that do not already exist.
    """
    # Importing the models package registers all 8 tables on Base.metadata.
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    logger.info("Database schema ready (%s tables)", len(Base.metadata.tables))


def check_database() -> bool:
    """Cheap liveness probe used by /health."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - health must never raise
        logger.warning("Database health check failed: %s", exc)
        return False
