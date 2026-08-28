"""Check-in records: one attendance record per student per session."""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.utils import new_uuid, utcnow
from app.enums import CheckInStatus


class CheckIn(Base):
    __tablename__ = "checkins"

    id = Column(String(36), primary_key=True, default=new_uuid)
    session_id = Column(
        String(36), ForeignKey("sessions.id"), nullable=False, index=True
    )
    student_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    device_id = Column(String(36), ForeignKey("devices.id"), nullable=True)

    status = Column(
        String(20), nullable=False, default=CheckInStatus.PENDING.value, index=True
    )
    checked_in_at = Column(DateTime, nullable=False, default=utcnow, index=True)
    verified_at = Column(DateTime, nullable=True)

    # Location data - captured only with geolocation consent, used only for
    # the geofence check.
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    location_accuracy_meters = Column(Float, nullable=True)
    distance_from_venue_meters = Column(Float, nullable=True)

    liveness_passed = Column(Boolean, nullable=True)
    liveness_score = Column(Float, nullable=True)
    liveness_challenge_type = Column(String(50), nullable=True)

    face_match_passed = Column(Boolean, nullable=True)
    face_match_score = Column(Float, nullable=True)
    # PRIVACY: hash only, never the image or the embedding itself.
    face_embedding_hash = Column(String(64), nullable=True)

    risk_score = Column(Float, nullable=False, default=0.0, index=True)
    risk_factors = Column(Text, nullable=True)  # JSON-encoded array

    qr_code_verified = Column(Boolean, nullable=False, default=False)

    reviewed_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_notes = Column(Text, nullable=True)

    appeal_reason = Column(Text, nullable=True)
    appealed_at = Column(DateTime, nullable=True)

    # 30-day retention policy.
    scheduled_deletion_at = Column(DateTime, nullable=True)

    session = relationship("AttendanceSession", back_populates="checkins")
    student = relationship(
        "User", back_populates="checkins", foreign_keys=[student_id]
    )
    reviewer = relationship("User", foreign_keys=[reviewed_by_id])
    device = relationship("Device", foreign_keys=[device_id])
    risk_signals = relationship(
        "RiskSignal", back_populates="checkin", cascade="all, delete-orphan"
    )

    # One check-in per student per session.
    __table_args__ = (
        UniqueConstraint("session_id", "student_id", name="uq_checkin_session_student"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CheckIn {self.id} status={self.status} risk={self.risk_score}>"
