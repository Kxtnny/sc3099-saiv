"""Individual risk indicators attached to a check-in."""

from sqlalchemy import Column, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.utils import new_uuid, utcnow


class RiskSignal(Base):
    __tablename__ = "risk_signals"

    id = Column(String(36), primary_key=True, default=new_uuid)
    checkin_id = Column(
        String(36), ForeignKey("checkins.id"), nullable=False, index=True
    )

    signal_type = Column(String(50), nullable=False, index=True)
    severity = Column(String(20), nullable=False, index=True)
    confidence = Column(Float, nullable=False, default=1.0)
    details = Column(Text, nullable=True)  # JSON-encoded metadata
    weight = Column(Float, nullable=False, default=0.1)
    detected_at = Column(DateTime, nullable=False, default=utcnow, index=True)

    checkin = relationship("CheckIn", back_populates="risk_signals")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RiskSignal {self.signal_type} ({self.severity})>"
