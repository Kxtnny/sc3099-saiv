"""
Client for Module 3, the face recognition service.

Every call degrades gracefully: the face service is a separate process that may
be down or slow, and a check-in must still complete inside the 2 second latency
budget. A failed call returns a neutral result rather than raising, so an
outage never rejects a legitimate student.

A small circuit breaker backs this up: once a connection fails, calls on the
latency-critical check-in path are skipped for FACE_SERVICE_COOLDOWN_SECONDS.
Without it every check-in during an outage would pay a DNS lookup and connect
timeout before degrading.
"""

import logging
import threading
import time
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_breaker_lock = threading.Lock()
_unavailable_until = 0.0


def _breaker_open() -> bool:
    return time.monotonic() < _unavailable_until


def _trip_breaker() -> None:
    global _unavailable_until
    with _breaker_lock:
        _unavailable_until = time.monotonic() + settings.FACE_SERVICE_COOLDOWN_SECONDS
    logger.warning(
        "Face service unreachable; skipping check-in calls for %ss",
        settings.FACE_SERVICE_COOLDOWN_SECONDS,
    )


def _close_breaker() -> None:
    global _unavailable_until
    if _unavailable_until:
        with _breaker_lock:
            _unavailable_until = 0.0
        logger.info("Face service reachable again")


class FaceServiceUnavailable(Exception):
    """Raised only where the caller must surface a 503 (face enrollment)."""


def _post(
    path: str,
    payload: Dict[str, Any],
    timeout: float,
    *,
    latency_critical: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    POST to the face service, returning None on any failure.

    latency_critical calls (everything on the check-in path) honour the
    breaker; enrollment does not, so a student is never told the service is
    down purely because it was down thirty seconds ago.
    """
    if latency_critical and _breaker_open():
        return None

    url = f"{settings.FACE_SERVICE_URL.rstrip('/')}{path}"
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=payload)
        _close_breaker()
        if response.status_code >= 500:
            logger.warning("Face service %s returned %s", path, response.status_code)
            return None
        return response.json()
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        logger.warning("Face service %s unreachable: %s", path, exc)
        _trip_breaker()
        return None
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Face service %s failed: %s", path, exc)
        return None


def enroll_face(user_id: str, image: str, camera_consent: bool) -> Dict[str, Any]:
    """
    Register a face template for a user.

    Unlike the check-in path this raises when the service is unavailable: the
    caller cannot silently claim an enrollment succeeded.
    """
    result = _post(
        "/face/enroll",
        {"user_id": user_id, "image": image, "camera_consent": camera_consent},
        settings.FACE_SERVICE_TIMEOUT,
        latency_critical=False,
    )
    if result is None:
        raise FaceServiceUnavailable("Face recognition service unavailable")
    return result


def verify_face(image: str, reference_hash: str) -> Dict[str, Any]:
    """Compare a face against an enrolled template."""
    result = _post(
        "/face/verify",
        {"image": image, "reference_template_hash": reference_hash},
        settings.FACE_CHECKIN_TIMEOUT,
    )
    if result is None:
        # None means "not evaluated", which the risk engine treats as neutral -
        # distinct from False, which means "actively failed".
        return {"match_passed": None, "match_score": None, "available": False}
    result.setdefault("available", True)
    return result


def check_liveness(image: str, challenge_type: str = "passive") -> Dict[str, Any]:
    """Run a liveness/anti-spoofing check on a captured frame."""
    result = _post(
        "/liveness/check",
        {"challenge_response": image, "challenge_type": challenge_type},
        settings.FACE_CHECKIN_TIMEOUT,
    )
    if result is None:
        return {"liveness_passed": None, "liveness_score": None, "available": False}
    result.setdefault("available", True)
    return result


def assess_risk(signals: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Ask the face service for its own multi-signal risk opinion."""
    return _post("/risk/assess", signals, settings.FACE_RISK_TIMEOUT)


def is_available() -> bool:
    """Health probe, surfaced on the backend's own /health."""
    try:
        with httpx.Client(timeout=2.0) as client:
            ok = client.get(
                f"{settings.FACE_SERVICE_URL.rstrip('/')}/health"
            ).status_code == 200
    except httpx.HTTPError:
        _trip_breaker()
        return False
    if ok:
        _close_breaker()
    return ok
