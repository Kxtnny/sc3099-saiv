"""
Domain enumerations.

These are stored as plain VARCHAR columns rather than native Postgres ENUM
types: adding a value to a native enum needs an ALTER TYPE migration, while a
string column is validated by Pydantic at the API boundary and stays easy to
evolve. Every member is a `str` subclass, so it serialises directly to JSON.
"""

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @classmethod
    def values(cls) -> list:
        return [member.value for member in cls]


class UserRole(StrEnum):
    STUDENT = "student"
    TA = "ta"
    INSTRUCTOR = "instructor"
    ADMIN = "admin"


# Privilege ordering from SECURITY-REQUIREMENTS.md (admin=4 ... student=1).
ROLE_LEVELS = {
    UserRole.STUDENT: 1,
    UserRole.TA: 2,
    UserRole.INSTRUCTOR: 3,
    UserRole.ADMIN: 4,
}


class SessionStatus(StrEnum):
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class SessionType(StrEnum):
    LECTURE = "lecture"
    TUTORIAL = "tutorial"
    LAB = "lab"
    EXAM = "exam"


class CheckInStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    FLAGGED = "flagged"
    REJECTED = "rejected"
    APPEALED = "appealed"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TrustScore(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DevicePlatform(StrEnum):
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"
    DESKTOP = "desktop"


class SignalSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SignalType(StrEnum):
    """Risk signal types from DATABASE-SCHEMA.md."""

    # Geolocation
    GEO_OUT_OF_BOUNDS = "geo_out_of_bounds"
    IMPOSSIBLE_TRAVEL = "impossible_travel"
    GEO_ACCURACY_LOW = "geo_accuracy_low"
    # Network
    VPN_DETECTED = "vpn_detected"
    PROXY_DETECTED = "proxy_detected"
    TOR_DETECTED = "tor_detected"
    SUSPICIOUS_IP = "suspicious_ip"
    # Device
    DEVICE_UNKNOWN = "device_unknown"
    DEVICE_EMULATOR = "device_emulator"
    DEVICE_ROOTED = "device_rooted"
    ATTESTATION_FAILED = "attestation_failed"
    # Behavioural
    RAPID_SUCCESSION = "rapid_succession"
    UNUSUAL_TIME = "unusual_time"
    PATTERN_ANOMALY = "pattern_anomaly"
    # Liveness
    LIVENESS_FAILED = "liveness_failed"
    LIVENESS_LOW_CONFIDENCE = "liveness_low_confidence"
    DEEPFAKE_SUSPECTED = "deepfake_suspected"
    REPLAY_SUSPECTED = "replay_suspected"
    # Face matching
    FACE_MATCH_FAILED = "face_match_failed"
    FACE_MATCH_LOW_CONFIDENCE = "face_match_low_confidence"


class AuditAction(StrEnum):
    """The 18 tracked action types from API-SPECIFICATION.md."""

    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    CHECKIN_ATTEMPTED = "checkin_attempted"
    CHECKIN_APPROVED = "checkin_approved"
    CHECKIN_FLAGGED = "checkin_flagged"
    CHECKIN_REJECTED = "checkin_rejected"
    CHECKIN_APPEALED = "checkin_appealed"
    CHECKIN_REVIEWED = "checkin_reviewed"
    SESSION_CREATED = "session_created"
    SESSION_UPDATED = "session_updated"
    SESSION_DELETED = "session_deleted"
    ENROLLMENT_ADDED = "enrollment_added"
    ENROLLMENT_REMOVED = "enrollment_removed"
    DEVICE_REGISTERED = "device_registered"
    FACE_ENROLLED = "face_enrolled"
    # Additional actions referenced by SECURITY-REQUIREMENTS.md
    DATA_EXPORTED = "data_exported"
    SECURITY_VIOLATION = "security_violation"
    USER_DELETED = "user_deleted"
