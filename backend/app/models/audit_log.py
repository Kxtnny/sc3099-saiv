"""
Immutable audit trail.

Deliberately has no `updated_at` column: entries are append-only and must never
be modified or deleted once written.
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.core.utils import new_uuid, utcnow


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=new_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)

    action = Column(String(50), nullable=False, index=True)
    resource_type = Column(String(50), nullable=True)
    resource_id = Column(String(36), nullable=True)

    ip_address = Column(String(45), nullable=True, index=True)  # IPv4 or IPv6
    user_agent = Column(String(500), nullable=True)
    device_id = Column(String(36), nullable=True)

    details = Column(Text, nullable=True)  # JSON-encoded details
    success = Column(Boolean, nullable=False, default=True)
    timestamp = Column(DateTime, nullable=False, default=utcnow, index=True)

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditLog {self.action} at {self.timestamp}>"
