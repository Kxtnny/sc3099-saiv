"""
SQLAlchemy models - all 8 tables from docs/recommended_design/DATABASE-SCHEMA.md.

Importing this package registers every table on Base.metadata, which is what
init_db() relies on to create the schema.
"""

from app.models.audit_log import AuditLog
from app.models.checkin import CheckIn
from app.models.course import Course
from app.models.device import Device
from app.models.enrollment import Enrollment
from app.models.risk_signal import RiskSignal
from app.models.session import AttendanceSession
from app.models.user import User

__all__ = [
    "AuditLog",
    "AttendanceSession",
    "CheckIn",
    "Course",
    "Device",
    "Enrollment",
    "RiskSignal",
    "User",
]
