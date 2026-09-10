"""
SAIV Backend API - Module 2

Core business logic: authentication, courses, sessions, check-ins, risk
assessment, audit logging.

See docs/API-SPECIFICATION.md for the endpoint contract.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app import __version__
from app.core.config import settings
from app.core.database import check_database, init_db, wait_for_database
from app.core.errors import install_exception_handlers, install_request_id_middleware
from app.core.redis_client import check_redis, close_redis
from app.routers import (
    admin,
    audit,
    auth,
    checkins,
    courses,
    devices,
    enrollments,
    export,
    sessions,
    stats,
    users,
)
from app.services import face_client, retention

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
# httpx/httpcore log every connection attempt at DEBUG, which floods dev logs
# with expected face-service connection failures.
logging.getLogger("httpcore").setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Prometheus series scraped by Module 4's dashboard.
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
)
CHECKIN_COUNT = Counter(
    "checkin_attempts_total", "Check-in attempts by outcome", ["status"]
)


async def _retention_loop() -> None:
    """Periodically scrub records whose retention window has passed."""
    interval = max(settings.RETENTION_SWEEP_INTERVAL_SECONDS, 60)
    while True:
        await asyncio.sleep(interval)
        # Sync SQLAlchemy work runs in a worker thread so it never blocks
        # request handling.
        await asyncio.to_thread(retention.run_sweep)


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

    sweeper = None
    if settings.RETENTION_SWEEP_ENABLED:
        sweeper = asyncio.create_task(_retention_loop())
        logger.info(
            "Retention sweep scheduled every %ss (%s-day policy)",
            settings.RETENTION_SWEEP_INTERVAL_SECONDS,
            settings.DATA_RETENTION_DAYS,
        )

    yield

    if sweeper is not None:
        sweeper.cancel()
    close_redis()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Secure Attendance & Identity Verification System",
    version=__version__,
    lifespan=lifespan,
)

install_exception_handlers(app)


# =============================================================================
# Middleware - each add_middleware wraps the previous, so the last one added
# is outermost. Order: metrics (inner) -> request id -> CORS (outer), so even
# error responses carry a request id and CORS headers.
# =============================================================================

@app.middleware("http")
async def record_metrics(request: Request, call_next):
    """
    Time every request for Prometheus.

    The route template is used as the label rather than the raw path, so
    /checkins/{id} stays one series instead of one per check-in, and unmatched
    paths collapse into a single bucket.
    """
    started = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - started

    route = request.scope.get("route")
    endpoint = getattr(route, "path", None) or "unmatched"

    REQUEST_COUNT.labels(
        method=request.method, endpoint=endpoint, status=response.status_code
    ).inc()
    REQUEST_LATENCY.labels(method=request.method, endpoint=endpoint).observe(elapsed)

    if endpoint.endswith("/checkins/") and request.method == "POST":
        CHECKIN_COUNT.labels(status=str(response.status_code)).inc()

    return response


install_request_id_middleware(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Retry-After", "Content-Disposition"],
)


# =============================================================================
# Service endpoints
# =============================================================================

@app.get("/health", tags=["health"])
def health_check():
    """
    Service health.

    Returns 200 while the database is reachable and 503 otherwise. Redis and
    the face service are optional dependencies, so an outage there is reported
    but does not make this service unhealthy.
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


@app.get("/health/dependencies", tags=["health"])
def dependency_health():
    """Deeper probe including the face service; slower, so kept off /health."""
    return {
        "database": check_database(),
        "redis": check_redis(),
        "face_service": face_client.is_available(),
    }


@app.get("/metrics", tags=["health"], include_in_schema=False)
def metrics():
    """Prometheus scrape endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/", tags=["health"])
def root():
    """Service metadata."""
    return {
        "service": settings.PROJECT_NAME,
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics",
        "api_prefix": settings.API_V1_PREFIX,
    }


# =============================================================================
# Routers
# =============================================================================
# admin is mounted first so /admin/... never falls through to a
# parameterised route on another router.
app.include_router(admin.router, prefix=settings.API_V1_PREFIX)
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)
app.include_router(courses.router, prefix=settings.API_V1_PREFIX)
app.include_router(enrollments.router, prefix=settings.API_V1_PREFIX)
app.include_router(sessions.router, prefix=settings.API_V1_PREFIX)
app.include_router(devices.router, prefix=settings.API_V1_PREFIX)
app.include_router(checkins.router, prefix=settings.API_V1_PREFIX)
app.include_router(stats.router, prefix=settings.API_V1_PREFIX)
app.include_router(audit.router, prefix=settings.API_V1_PREFIX)
app.include_router(export.router, prefix=settings.API_V1_PREFIX)
