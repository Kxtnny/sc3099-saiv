"""
Check-in schemas.

PRIVACY: no response model exposes an image field. Submitted frames are held in
memory for the liveness and face-match calls and then discarded - only scores
and the SHA-256 template hash are persisted.
"""

import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enums import CheckInStatus
from app.schemas.common import UTCDateTime


def _coerce_risk_factors(value: Any) -> List[Dict[str, Any]]:
    """
    Accept risk_factors as either a list or the JSON string stored in the
    database, so the ORM row validates directly.
    """
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return []
        return parsed if isinstance(parsed, list) else []
    return value


class CheckInCreate(BaseModel):
    session_id: str
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    location_accuracy_meters: Optional[float] = Field(default=None, ge=0)
    device_fingerprint: Optional[str] = Field(default=None, max_length=64)
    # Base64 frame, processed in memory and never stored.
    liveness_challenge_response: Optional[str] = None
    liveness_challenge_type: Optional[str] = Field(default=None, max_length=50)
    qr_code: Optional[str] = Field(default=None, max_length=255)


class CheckInAppeal(BaseModel):
    appeal_reason: str = Field(min_length=1, max_length=2000)


class CheckInReview(BaseModel):
    status: CheckInStatus
    review_notes: Optional[str] = Field(default=None, max_length=2000)


class CheckInResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    student_id: str
    status: str
    checked_in_at: UTCDateTime
    verified_at: Optional[UTCDateTime] = None

    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_accuracy_meters: Optional[float] = None
    distance_from_venue_meters: Optional[float] = None

    liveness_passed: Optional[bool] = None
    liveness_score: Optional[float] = None
    face_match_passed: Optional[bool] = None
    face_match_score: Optional[float] = None

    risk_score: float
    risk_level: Optional[str] = None
    risk_factors: List[Dict[str, Any]] = []

    device_trusted: Optional[bool] = None
    appeal_reason: Optional[str] = None
    appealed_at: Optional[UTCDateTime] = None
    reviewed_by_id: Optional[str] = None
    reviewed_at: Optional[UTCDateTime] = None
    review_notes: Optional[str] = None

    @field_validator("risk_factors", mode="before")
    @classmethod
    def parse_risk_factors(cls, value: Any) -> List[Dict[str, Any]]:
        return _coerce_risk_factors(value)


class CheckInListItem(BaseModel):
    """Row shape for instructor-facing lists."""

    id: str
    session_id: str
    session_name: Optional[str] = None
    course_code: Optional[str] = None
    student_id: str
    student_name: Optional[str] = None
    student_email: Optional[str] = None
    status: str
    checked_in_at: UTCDateTime
    distance_from_venue_meters: Optional[float] = None
    risk_score: float
    risk_factors: List[Dict[str, Any]] = []
    liveness_passed: Optional[bool] = None
    device_trusted: Optional[bool] = None
    appeal_reason: Optional[str] = None
    appealed_at: Optional[UTCDateTime] = None

    @field_validator("risk_factors", mode="before")
    @classmethod
    def parse_risk_factors(cls, value: Any) -> List[Dict[str, Any]]:
        return _coerce_risk_factors(value)


class MyCheckInItem(BaseModel):
    """Row shape for a student's own history."""

    id: str
    session_id: str
    session_name: Optional[str] = None
    course_code: Optional[str] = None
    status: str
    checked_in_at: UTCDateTime
    risk_score: float
