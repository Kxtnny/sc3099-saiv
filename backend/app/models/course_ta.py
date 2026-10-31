"""Explicit TA-to-course assignments used by backend authorization."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.utils import new_uuid, utcnow


class CourseTA(Base):
    __tablename__ = "course_tas"

    id = Column(String(36), primary_key=True, default=new_uuid)
    course_id = Column(
        String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    ta_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    assigned_by_id = Column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assigned_at = Column(DateTime, nullable=False, default=utcnow)

    course = relationship("Course", back_populates="ta_assignments")
    ta = relationship("User", foreign_keys=[ta_id], back_populates="course_assignments")
    assigned_by = relationship("User", foreign_keys=[assigned_by_id])

    __table_args__ = (
        UniqueConstraint("course_id", "ta_id", name="uq_course_ta"),
        Index("ix_course_tas_ta_course", "ta_id", "course_id"),
    )
