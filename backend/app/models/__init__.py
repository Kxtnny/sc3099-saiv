"""
SQLAlchemy models registered in the application's database metadata.

Importing this package registers every table on Base.metadata, which init_db()
uses to create missing tables, including the TA-course assignment table.
"""

from app.models.audit_log import AuditLog
from app.models.checkin import CheckIn
from app.models.course import Course
from app.models.course_ta import CourseTA
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
    "CourseTA",
    "Device",
    "Enrollment",
    "RiskSignal",
    "User",
]
