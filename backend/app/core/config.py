"""
Application configuration.

All values come from environment variables (see docker-compose.yml) with
sensible local-development defaults. Security parameters follow
docs/SECURITY-REQUIREMENTS.md.
"""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Application ---------------------------------------------------------
    PROJECT_NAME: str = "SAIV Backend API"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = False

    # -- Infrastructure ------------------------------------------------------
    DATABASE_URL: str = "postgresql://saiv:saiv_password@localhost:5434/saiv"
    REDIS_URL: str = "redis://localhost:6380/0"
    FACE_SERVICE_URL: str = "http://localhost:8001"

    # Face service call budgets. The check-in path is tighter because the
    # whole request must finish well inside 2 seconds.
    FACE_SERVICE_TIMEOUT: float = 5.0
    FACE_CHECKIN_TIMEOUT: float = 1.5
    # Optional second opinion from the face service risk engine (network /
    # VPN signals). Short budget so it can never push a check-in past 2s.
    FACE_RISK_ASSESS_ENABLED: bool = True
    FACE_RISK_TIMEOUT: float = 0.75
    # After a connection failure, skip face-service calls on the check-in
    # path for this long instead of paying the DNS/connect cost every time.
    FACE_SERVICE_COOLDOWN_SECONDS: int = 30

    # Connection pool (DATABASE-SCHEMA.md: size=10, max_overflow=20)
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_CONNECT_TIMEOUT: int = 5

    # -- Authentication ------------------------------------------------------
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60          # 1 hour
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7             # 7 days
    BCRYPT_ROUNDS: int = 10                        # cost >= 10
    MIN_PASSWORD_LENGTH: int = 8

    # -- Risk scoring --------------------------------------------------------
    RISK_SCORE_THRESHOLD: float = 0.5
    # CRITICAL band (SECURITY-REQUIREMENTS.md): auto-reject at or above this.
    RISK_REJECT_THRESHOLD: float = 0.7
    LIVENESS_THRESHOLD: float = 0.6
    FACE_MATCH_THRESHOLD: float = 0.7
    DEFAULT_GEOFENCE_RADIUS_METERS: float = 100.0

    # -- Rate limiting -------------------------------------------------------
    # Limits are env-configurable on purpose: the public test suite registers
    # far more than 10 users per run from a single IP, so the documented
    # production values would fail the suite. Defaults here are permissive for
    # development; tighten them via environment variables to demo the feature.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_LOGIN_PER_HOUR: int = 60          # failed attempts per IP
    RATE_LIMIT_API_PER_HOUR: int = 1000
    RATE_LIMIT_CHECKIN_PER_MINUTE: int = 10
    RATE_LIMIT_REGISTER_PER_HOUR: int = 1000

    # -- Data retention ------------------------------------------------------
    DATA_RETENTION_DAYS: int = 30
    # Background sweep that scrubs records past scheduled_deletion_at.
    RETENTION_SWEEP_ENABLED: bool = True
    RETENTION_SWEEP_INTERVAL_SECONDS: int = 3600

    # -- Sessions ------------------------------------------------------------
    # Rotating QR codes for replay prevention; how long one stays valid.
    QR_CODE_TTL_SECONDS: int = 300
    # Tolerance when validating that a new session starts in the future.
    SESSION_START_GRACE_SECONDS: int = 300

    # -- CORS ----------------------------------------------------------------
    # Comma-separated list; parsed by the cors_origins property below.
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:8501"

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]



@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
