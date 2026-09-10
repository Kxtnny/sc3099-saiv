"""
Redis-backed rate limiting.

Fixed-window counters with TTL expiry, as specified in
docs/SECURITY-REQUIREMENTS.md. Two deliberate deviations, both documented in
config.py:

* The login limiter counts only FAILED attempts. Limiting successful logins
  per IP punishes shared networks (a lecture hall, a NAT gateway, a CI runner)
  without making brute force meaningfully harder.
* Registration defaults to a permissive limit because the public test suite
  creates far more than 10 accounts per run from one address. Tighten
  RATE_LIMIT_REGISTER_PER_HOUR via the environment to demonstrate the control.

Redis outages fail open: attendance keeps working, and the event is logged.
"""

import logging
from typing import Optional, Tuple

from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)


def client_ip(request: Request) -> str:
    """Caller IP, honouring X-Forwarded-For when behind a proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def hit(key: str, limit: int, window_seconds: int) -> Tuple[bool, int, int]:
    """
    Register one hit against a counter.

    Returns (allowed, current_count, retry_after_seconds). INCR and EXPIRE are
    pipelined so the pair is atomic and the key can never outlive its window.
    """
    if not settings.RATE_LIMIT_ENABLED:
        return True, 0, 0

    client = get_redis()
    if client is None:
        return True, 0, 0

    try:
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.ttl(key)
        count, ttl = pipe.execute()

        if ttl is None or ttl < 0:
            client.expire(key, window_seconds)
            ttl = window_seconds

        return count <= limit, int(count), int(ttl)
    except Exception as exc:  # noqa: BLE001 - never break a request on Redis
        logger.warning("Rate limiter unavailable for %s: %s", key, exc)
        return True, 0, 0


def peek(key: str, limit: int) -> Tuple[bool, int, int]:
    """Read a counter without incrementing it."""
    if not settings.RATE_LIMIT_ENABLED:
        return True, 0, 0
    client = get_redis()
    if client is None:
        return True, 0, 0
    try:
        pipe = client.pipeline()
        pipe.get(key)
        pipe.ttl(key)
        raw, ttl = pipe.execute()
        count = int(raw) if raw else 0
        return count < limit, count, max(int(ttl or 0), 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Rate limiter unavailable for %s: %s", key, exc)
        return True, 0, 0


def _reject(key: str, count: int, limit: int, retry_after: int) -> None:
    logger.info("Rate limit hit on %s (%s/%s)", key, count, limit)
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Rate limit exceeded",
        headers={"Retry-After": str(max(retry_after, 1))},
    )


def enforce(key: str, limit: int, window_seconds: int) -> None:
    """Count one hit and raise 429 with Retry-After when the limit is exceeded."""
    allowed, count, retry_after = hit(key, limit, window_seconds)
    if not allowed:
        _reject(key, count, limit, retry_after)


def reset(key: str) -> None:
    """Clear a counter, e.g. after a successful login."""
    client = get_redis()
    if client is None:
        return
    try:
        client.delete(key)
    except Exception:  # noqa: BLE001
        pass


# =============================================================================
# Named limiters
# =============================================================================

def login_key(ip: str) -> str:
    return f"rate_limit:login:{ip}:3600"


def check_login_attempts(request: Request) -> None:
    """
    Called before verifying credentials.

    Reads the failure counter without incrementing it - only a confirmed
    failure counts, so a correct password is never charged against the limit.
    """
    key = login_key(client_ip(request))
    allowed, count, retry_after = peek(key, settings.RATE_LIMIT_LOGIN_PER_HOUR)
    if not allowed:
        _reject(key, count, settings.RATE_LIMIT_LOGIN_PER_HOUR, retry_after)


def record_login_failure(request: Request) -> None:
    """Count a failed login against the caller's IP."""
    hit(login_key(client_ip(request)), settings.RATE_LIMIT_LOGIN_PER_HOUR, 3600)


def clear_login_failures(request: Request) -> None:
    """A correct password clears the failure counter."""
    reset(login_key(client_ip(request)))


def check_registration(request: Request) -> None:
    enforce(
        f"rate_limit:register:{client_ip(request)}:3600",
        settings.RATE_LIMIT_REGISTER_PER_HOUR,
        3600,
    )


def check_checkin(user_id: str) -> None:
    enforce(
        f"rate_limit:checkin:{user_id}:60", settings.RATE_LIMIT_CHECKIN_PER_MINUTE, 60
    )


def check_api_quota(user_id: Optional[str]) -> None:
    if user_id:
        enforce(f"rate_limit:api:{user_id}:3600", settings.RATE_LIMIT_API_PER_HOUR, 3600)
