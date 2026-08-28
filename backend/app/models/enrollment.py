"""Student-course enrollments."""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.utils import new_uuid, utcnow


class Enrollment(Base):
    __tablename__ = "enrollments"

    id = Column(String(36), primary_key=True, default=new_uuid)
    student_id = Column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    course_id = Column(
        String(36), ForeignKey("courses.id"), nullable=False, index=True
    )
    is_active = Column(Boolean, nullable=False, default=True)
    enrolled_at = Column(DateTime, nullable=False, default=utcnow)
    dropped_at = Column(DateTime, nullable=True)

    student = relationship("User", back_populates="enrollments")
    course = relationship("Course", back_populates="enrollments")

    # A student may only be enrolled in a course once.
    __table_args__ = (
        UniqueConstraint("student_id", "course_id", name="uq_enrollment_student_course"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Enrollment student={self.student_id} course={self.course_id}>"
