"""
Redis client used for rate limiting and caching.

Redis is treated as optional infrastructure: if it is unreachable the API keeps
serving requests (rate limiting fails open) rather than returning 500s.
"""

import logging
from typing import Optional

import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Optional[redis.Redis] = None


def get_redis() -> Optional[redis.Redis]:
    """Return a shared Redis client, or None when Redis is unavailable."""
    global _client
    if _client is None:
        try:
            _client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                health_check_interval=30,
            )
            _client.ping()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis unavailable, continuing without it: %s", exc)
            _client = None
    return _client


def check_redis() -> bool:
    """Cheap liveness probe used by /health."""
    client = get_redis()
    if client is None:
        return False
    try:
        client.ping()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis health check failed: %s", exc)
        return False


def close_redis() -> None:
    """Release the connection pool on shutdown."""
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:  # noqa: BLE001
            pass
        _client = None
