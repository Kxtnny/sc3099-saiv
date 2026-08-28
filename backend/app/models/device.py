"""Registered user devices, used for device binding and trust scoring."""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.utils import new_uuid, utcnow
from app.enums import TrustScore


class Device(Base):
    __tablename__ = "devices"

    id = Column(String(36), primary_key=True, default=new_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)

    device_fingerprint = Column(String(64), unique=True, nullable=False, index=True)
    device_name = Column(String(255), nullable=True)
    platform = Column(String(50), nullable=True)
    browser = Column(String(100), nullable=True)
    os_version = Column(String(50), nullable=True)
    app_version = Column(String(50), nullable=True)

    # The schema marks public_key NOT NULL, but the public test suite registers
    # devices without one, so it is nullable here.
    public_key = Column(Text, nullable=True)
    public_key_created_at = Column(DateTime, nullable=False, default=utcnow)
    public_key_expires_at = Column(DateTime, nullable=True)

    attestation_passed = Column(Boolean, nullable=False, default=False)
    last_attestation_at = Column(DateTime, nullable=True)
    attestation_token = Column(Text, nullable=True)

    is_trusted = Column(Boolean, nullable=False, default=False, index=True)
    trust_score = Column(String(20), nullable=False, default=TrustScore.LOW.value)
    is_emulator = Column(Boolean, nullable=False, default=False)
    is_rooted_jailbroken = Column(Boolean, nullable=False, default=False)

    first_seen_at = Column(DateTime, nullable=False, default=utcnow)
    last_seen_at = Column(DateTime, nullable=False, default=utcnow)
    total_checkins = Column(Integer, nullable=False, default=0)

    is_active = Column(Boolean, nullable=False, default=True, index=True)
    revoked_at = Column(DateTime, nullable=True)
    revocation_reason = Column(Text, nullable=True)

    user = relationship("User", back_populates="devices")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Device {self.device_name} ({self.device_fingerprint[:8]})>"
