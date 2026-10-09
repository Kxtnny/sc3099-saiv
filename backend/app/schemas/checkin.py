"""
Check-in schemas.

PRIVACY: no response model exposes an image field. Submitted frames are held in
memory for the liveness and face-match calls and then discarded - only scores
and the 256-bit SimHash template are persisted.
"""

import json
from typing import Annotated, Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enums import CheckInStatus
from app.schemas.common import UTCDateTime

# Liveness frame sequence limits, matching the face service (5-45 frames).
MIN_LIVENESS_FRAMES = 5
MAX_LIVENESS_FRAMES = 45
# ~1.5 MB of base64 per frame; a 640x480 JPEG at quality 0.7 is ~50 KB.
MAX_FRAME_CHARS = 2_000_000


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
    # Base64 frame, processed in memory and never stored. Used for face match.
    liveness_challenge_response: Optional[str] = None
    liveness_challenge_type: Optional[str] = Field(default=None, max_length=50)
    # Challenge flow (optional, so older clients keep working): the id from
    # GET /checkins/liveness-challenge plus the frames recorded while the
    # student performed it. Base64 JPEGs, never stored.
    liveness_challenge_id: Optional[str] = Field(default=None, max_length=64)
    liveness_frames: Optional[
        List[Annotated[str, Field(max_length=MAX_FRAME_CHARS)]]
    ] = Field(default=None, min_length=MIN_LIVENESS_FRAMES, max_length=MAX_LIVENESS_FRAMES)
    qr_code: Optional[str] = Field(default=None, max_length=255)


class LivenessChallengeResponse(BaseModel):
    challenge_id: str
    challenge_type: str
    expires_in: int


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
