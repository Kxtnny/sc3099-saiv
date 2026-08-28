"""
Password hashing and JWT token handling.

Uses the `bcrypt` package directly rather than passlib: passlib 1.7.4 emits a
spurious "error reading bcrypt version" warning against bcrypt 4.x and is no
longer maintained. Parameters follow docs/SECURITY-REQUIREMENTS.md
(bcrypt cost >= 10, HS256, 1h access / 7d refresh).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

logger = logging.getLogger(__name__)

# bcrypt only consumes the first 72 bytes of input and raises on longer values.
BCRYPT_MAX_BYTES = 72

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


# =============================================================================
# Passwords
# =============================================================================

def _prepare(password: str) -> bytes:
    """Encode to UTF-8 and truncate to bcrypt's 72-byte input limit."""
    return password.encode("utf-8")[:BCRYPT_MAX_BYTES]


def get_password_hash(password: str) -> str:
    """Hash a plaintext password. Never store the plaintext."""
    salt = bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    return bcrypt.hashpw(_prepare(password), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Constant-time password comparison; returns False on malformed hashes."""
    try:
        return bcrypt.checkpw(_prepare(plain_password), hashed_password.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        logger.warning("Password verification failed: %s", exc)
        return False


# =============================================================================
# JWT tokens
# =============================================================================

def _create_token(
    subject: str,
    token_type: str,
    expires_delta: timedelta,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(
    subject: str, extra_claims: Optional[Dict[str, Any]] = None
) -> str:
    """Access token, 1 hour TTL. Carries no sensitive data - identity only."""
    return _create_token(
        subject,
        TOKEN_TYPE_ACCESS,
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        extra_claims,
    )


def create_refresh_token(
    subject: str, extra_claims: Optional[Dict[str, Any]] = None
) -> str:
    """Refresh token, 7 day TTL."""
    return _create_token(
        subject,
        TOKEN_TYPE_REFRESH,
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        extra_claims,
    )


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode and verify a JWT.

    Returns None for any invalid token - bad signature, expired, malformed -
    so callers can respond with 401 without leaking the reason.
    """
    try:
        return jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError as exc:
        logger.debug("Token rejected: %s", exc)
        return None


def decode_token_of_type(token: str, expected_type: str) -> Optional[Dict[str, Any]]:
    """Decode a token and confirm it is the expected kind (access vs refresh)."""
    payload = decode_token(token)
    if payload is None:
        return None
    if payload.get("type") != expected_type:
        logger.debug(
            "Token type mismatch: expected %s, got %s",
            expected_type,
            payload.get("type"),
        )
        return None
    return payload
