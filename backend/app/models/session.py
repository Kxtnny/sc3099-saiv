"""
Attendance sessions (lectures, tutorials, labs, exams).

The model class is named AttendanceSession to avoid confusion with
sqlalchemy.orm.Session; the table is still `sessions` as specified.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.utils import new_uuid, utcnow
from app.enums import SessionStatus, SessionType


class AttendanceSession(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=new_uuid)
    course_id = Column(
        String(36), ForeignKey("courses.id"), nullable=False, index=True
    )
    instructor_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)

    name = Column(String(255), nullable=False)
    session_type = Column(String(50), nullable=False, default=SessionType.LECTURE.value)
    description = Column(Text, nullable=True)

    scheduled_start = Column(DateTime, nullable=False, index=True)
    scheduled_end = Column(DateTime, nullable=False)
    checkin_opens_at = Column(DateTime, nullable=False)
    checkin_closes_at = Column(DateTime, nullable=False)

    status = Column(
        String(20), nullable=False, default=SessionStatus.SCHEDULED.value, index=True
    )
    actual_start = Column(DateTime, nullable=True)
    actual_end = Column(DateTime, nullable=True)

    # Venue overrides; fall back to the course defaults when null.
    venue_latitude = Column(Float, nullable=True)
    venue_longitude = Column(Float, nullable=True)
    venue_name = Column(String(255), nullable=True)
    geofence_radius_meters = Column(Float, nullable=True)

    require_liveness_check = Column(Boolean, nullable=False, default=True)
    require_face_match = Column(Boolean, nullable=False, default=False)
    risk_threshold = Column(Float, nullable=True)

    qr_code_secret = Column(String(64), nullable=True)
    qr_code_expires_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    course = relationship("Course", back_populates="sessions")
    instructor = relationship("User", foreign_keys=[instructor_id])
    checkins = relationship(
        "CheckIn", back_populates="session", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_sessions_checkin_window", "checkin_opens_at", "checkin_closes_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AttendanceSession {self.name} ({self.status})>"
