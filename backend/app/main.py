"""
SAIV Backend API - Module 2

Core business logic: authentication, courses, sessions, check-ins, risk
assessment, audit logging.

See docs/API-SPECIFICATION.md for the endpoint contract.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.core.config import settings
from app.core.database import check_database, init_db, wait_for_database
from app.core.redis_client import check_redis, close_redis
from app.routers import auth, users

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the schema on startup, release connections on shutdown."""
    logger.info("Starting %s v%s", settings.PROJECT_NAME, __version__)
    if wait_for_database():
        init_db()
    else:
        # Do not crash the process: /health will report the database as
        # unavailable and the container stays up for diagnosis.
        logger.error("Database unreachable at startup; schema not initialised")

    check_redis()  # warm the connection pool; failure is non-fatal
    yield

    close_redis()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Secure Attendance & Identity Verification System",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
def health_check():
    """
    Service health.

    Returns 200 while the database is reachable and 503 otherwise. Redis is
    optional infrastructure, so an outage there is reported but does not make
    the service unhealthy.
    """
    database_ok = check_database()
    redis_ok = check_redis()

    payload = {
        "status": "healthy" if database_ok else "unhealthy",
        "api": "ok",
        "database": "ok" if database_ok else "unavailable",
        "redis": "ok" if redis_ok else "unavailable",
        "version": __version__,
    }
    return JSONResponse(status_code=200 if database_ok else 503, content=payload)


@app.get("/", tags=["health"])
def root():
    """Service metadata."""
    return {
        "service": settings.PROJECT_NAME,
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
        "api_prefix": settings.API_V1_PREFIX,
    }


# =============================================================================
# Routers (mounted as each is implemented)
# =============================================================================
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)

# Still to come: courses, sessions, checkins, devices, enrollments, stats,
# audit, export, admin.
