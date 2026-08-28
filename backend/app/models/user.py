"""User accounts: students, TAs, instructors and admins."""

from sqlalchemy import Boolean, Column, DateTime, Index, String
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.utils import new_uuid, utcnow
from app.enums import UserRole


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=new_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default=UserRole.STUDENT.value, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    # Consent tracking - both must be true before a check-in is allowed.
    camera_consent = Column(Boolean, nullable=False, default=False)
    geolocation_consent = Column(Boolean, nullable=False, default=False)

    # PRIVACY: only the SHA-256 hash of the face template, never an image or
    # a raw embedding. 64 hex characters.
    face_embedding_hash = Column(String(64), nullable=True)
    face_enrolled = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    last_login_at = Column(DateTime, nullable=True)

    # 30-day retention policy for personal data.
    scheduled_deletion_at = Column(DateTime, nullable=True)

    enrollments = relationship(
        "Enrollment", back_populates="student", cascade="all, delete-orphan"
    )
    devices = relationship(
        "Device", back_populates="user", cascade="all, delete-orphan"
    )
    checkins = relationship(
        "CheckIn",
        back_populates="student",
        foreign_keys="CheckIn.student_id",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_users_role_active", "role", "is_active"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.email} ({self.role})>"
