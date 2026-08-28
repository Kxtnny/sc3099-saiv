"""Courses, including default venue and geofence settings."""

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from app.core.config import settings
from app.core.database import Base
from app.core.utils import new_uuid, utcnow


class Course(Base):
    __tablename__ = "courses"

    id = Column(String(36), primary_key=True, default=new_uuid)
    code = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    semester = Column(String(20), nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    # The schema does not list instructor_id, but the API returns
    # instructor_id / instructor_name on every course, so it is stored here.
    instructor_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)

    # Default venue - sessions may override these.
    venue_latitude = Column(Float, nullable=True)
    venue_longitude = Column(Float, nullable=True)
    venue_name = Column(String(255), nullable=True)
    geofence_radius_meters = Column(
        Float, nullable=False, default=settings.DEFAULT_GEOFENCE_RADIUS_METERS
    )

    require_face_recognition = Column(Boolean, nullable=False, default=False)
    require_device_binding = Column(Boolean, nullable=False, default=True)
    risk_threshold = Column(Float, nullable=False, default=settings.RISK_SCORE_THRESHOLD)

    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    instructor = relationship("User", foreign_keys=[instructor_id])
    enrollments = relationship(
        "Enrollment", back_populates="course", cascade="all, delete-orphan"
    )
    sessions = relationship(
        "AttendanceSession", back_populates="course", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Course {self.code}>"
