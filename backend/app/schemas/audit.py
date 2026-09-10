"""Audit log schemas."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from app.enums import AuditAction
from app.schemas.common import UTCDateTime


class AuditLogCreate(BaseModel):
    action: AuditAction
    resource_type: Optional[str] = Field(default=None, max_length=50)
    resource_id: Optional[str] = Field(default=None, max_length=36)
    details: Optional[Dict[str, Any]] = None
    success: bool = True


class AuditLogResponse(BaseModel):
    id: str
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    device_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    success: bool
    timestamp: UTCDateTime


class AuditSummary(BaseModel):
    period_days: int
    total_logs: int
    by_action: Dict[str, int]
    by_success: Dict[str, int]
    unique_users: int
