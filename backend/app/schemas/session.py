"""Attendance session schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.enums import SessionStatus, SessionType
from app.schemas.common import UTCDateTime


class SessionCreate(BaseModel):
    """
    Create a session.

    The check-in window is optional: it defaults to 15 minutes before the
    scheduled start and 30 minutes after it, per API-SPECIFICATION.md.
    """

    course_id: str
    name: str = Field(min_length=1, max_length=255)
    session_type: SessionType = SessionType.LECTURE
    description: Optional[str] = None

    scheduled_start: datetime
    scheduled_end: datetime
    checkin_opens_at: Optional[datetime] = None
    checkin_closes_at: Optional[datetime] = None

    venue_name: Optional[str] = Field(default=None, max_length=255)
    venue_latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    venue_longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    geofence_radius_meters: Optional[float] = Field(default=None, gt=0, le=100_000)

    require_liveness_check: bool = True
    require_face_match: bool = False
    risk_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def check_ordering(self) -> "SessionCreate":
        if self.scheduled_end <= self.scheduled_start:
            raise ValueError("scheduled_end must be after scheduled_start")
        if (
            self.checkin_opens_at
            and self.checkin_closes_at
            and self.checkin_closes_at <= self.checkin_opens_at
        ):
            raise ValueError("checkin_closes_at must be after checkin_opens_at")
        return self


class SessionUpdate(BaseModel):
    """Partial update, including the status transition."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    session_type: Optional[SessionType] = None
    status: Optional[SessionStatus] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    checkin_opens_at: Optional[datetime] = None
    checkin_closes_at: Optional[datetime] = None
    venue_name: Optional[str] = Field(default=None, max_length=255)
    venue_latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    venue_longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    geofence_radius_meters: Optional[float] = Field(default=None, gt=0, le=100_000)
    require_liveness_check: Optional[bool] = None
    require_face_match: Optional[bool] = None
    risk_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class SessionStatusUpdate(BaseModel):
    """Admin status override, used by the test suite to open check-in."""

    status: SessionStatus


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    course_code: Optional[str] = None
    course_name: Optional[str] = None
    instructor_id: Optional[str] = None
    name: str
    session_type: str
    description: Optional[str] = None
    status: str

    scheduled_start: UTCDateTime
    scheduled_end: UTCDateTime
    checkin_opens_at: UTCDateTime
    checkin_closes_at: UTCDateTime

    venue_name: Optional[str] = None
    venue_latitude: Optional[float] = None
    venue_longitude: Optional[float] = None
    geofence_radius_meters: Optional[float] = None

    require_liveness_check: bool
    require_face_match: bool
    risk_threshold: Optional[float] = None
    qr_code_enabled: bool = False

    total_enrolled: Optional[int] = None
    checked_in_count: Optional[int] = None

    created_at: UTCDateTime
    updated_at: Optional[UTCDateTime] = None
