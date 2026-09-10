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
    enforce_audit_immutability()


# Postgres triggers that make audit_logs append-only. Application code has no
# update or delete path, but this holds even for someone with a psql prompt.
_AUDIT_GUARD_FUNCTION = """
CREATE OR REPLACE FUNCTION saiv_audit_logs_guard() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;
"""

_AUDIT_GUARD_TRIGGERS = [
    "DROP TRIGGER IF EXISTS audit_logs_no_update_delete ON audit_logs",
    "CREATE TRIGGER audit_logs_no_update_delete "
    "BEFORE UPDATE OR DELETE ON audit_logs "
    "FOR EACH ROW EXECUTE FUNCTION saiv_audit_logs_guard()",
    "DROP TRIGGER IF EXISTS audit_logs_no_truncate ON audit_logs",
    "CREATE TRIGGER audit_logs_no_truncate "
    "BEFORE TRUNCATE ON audit_logs "
    "FOR EACH STATEMENT EXECUTE FUNCTION saiv_audit_logs_guard()",
]


def enforce_audit_immutability() -> None:
    """Install the append-only guard on audit_logs (PostgreSQL only)."""
    if engine.dialect.name != "postgresql":
        logger.warning("Audit immutability trigger skipped: not PostgreSQL")
        return
    try:
        with engine.begin() as conn:
            conn.execute(text(_AUDIT_GUARD_FUNCTION))
            for statement in _AUDIT_GUARD_TRIGGERS:
                conn.execute(text(statement))
        logger.info("audit_logs append-only guard installed")
    except Exception as exc:  # noqa: BLE001 - never block startup on this
        logger.error("Could not install audit_logs guard: %s", exc)


def check_database() -> bool:
    """Cheap liveness probe used by /health."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - health must never raise
        logger.warning("Database health check failed: %s", exc)
        return False
