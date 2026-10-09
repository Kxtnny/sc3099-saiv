"""
Attendance export for gradebooks and compliance audits.

Exports carry personal data, so every call is recorded as a `data_exported`
audit event naming who exported what.
"""

import csv
import io
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.utils import utcnow
from app.dependencies import require_staff
from app.enums import AuditAction, CheckInStatus
from app.models import AttendanceSession, CheckIn, Course, Enrollment, User
from app.services.audit import log_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["export"])

CSV_COLUMNS = [
    "student_id",
    "student_name",
    "student_email",
    "course_code",
    "course_name",
    "session_id",
    "session_name",
    "session_date",
    "status",
    "checked_in_at",
    "risk_score",
    "distance_from_venue_meters",
]


def _csv_response(rows: List[dict], filename: str) -> StreamingResponse:
    """Render rows as a downloadable CSV."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _row(checkin: CheckIn) -> dict:
    session = checkin.session
    course = session.course if session else None
    return {
        "student_id": checkin.student_id,
        "student_name": checkin.student.full_name if checkin.student else "",
        "student_email": checkin.student.email if checkin.student else "",
        "course_code": course.code if course else "",
        "course_name": course.name if course else "",
        "session_id": checkin.session_id,
        "session_name": session.name if session else "",
        "session_date": (
            session.scheduled_start.date().isoformat() if session else ""
        ),
        "status": checkin.status,
        "checked_in_at": checkin.checked_in_at.isoformat() + "Z",
        "risk_score": checkin.risk_score,
        "distance_from_venue_meters": checkin.distance_from_venue_meters,
    }


@router.get("/session/{session_id}")
def export_session(
    session_id: str,
    request: Request,
    export_format: str = Query(default="json", alias="format", pattern="^(csv|json)$"),
    staff: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Export one session's attendance as JSON or CSV."""
    session = (
        db.query(AttendanceSession)
        .options(joinedload(AttendanceSession.course))
        .filter(AttendanceSession.id == session_id)
        .first()
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    checkins = (
        db.query(CheckIn)
        .options(
            joinedload(CheckIn.student),
            joinedload(CheckIn.session).joinedload(AttendanceSession.course),
        )
        .filter(CheckIn.session_id == session_id)
        .order_by(CheckIn.checked_in_at)
        .all()
    )
    total_enrolled = (
        db.query(Enrollment)
        .filter(
            Enrollment.course_id == session.course_id,
            Enrollment.is_active.is_(True),
        )
        .count()
    )

    records = [_row(c) for c in checkins]

    log_action(
        db,
        AuditAction.DATA_EXPORTED,
        user_id=staff.id,
        resource_type="session",
        resource_id=session_id,
        request=request,
        details={"format": export_format, "records": len(records)},
        commit=True,
    )

    if export_format == "csv":
        return _csv_response(records, f"attendance_{session_id}.csv")

    approved = sum(
        1 for c in checkins if c.status == CheckInStatus.APPROVED.value
    )
    flagged = sum(1 for c in checkins if c.status == CheckInStatus.FLAGGED.value)

    return {
        "session_id": session.id,
        "session_name": session.name,
        "course_id": session.course_id,
        "course_code": session.course.code if session.course else None,
        "scheduled_start": session.scheduled_start.isoformat() + "Z",
        "exported_at": utcnow().isoformat() + "Z",
        "summary": {
            "total_enrolled": total_enrolled,
            "total_checkins": len(checkins),
            "approved": approved,
            "flagged": flagged,
            "attendance_rate": (
                round(len(checkins) / total_enrolled, 4) if total_enrolled else 0.0
            ),
        },
        "records": records,
    }


@router.get("/attendance/{course_id}")
def export_course_attendance(
    course_id: str,
    request: Request,
    export_format: str = Query(default="csv", alias="format", pattern="^(csv|json)$"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    staff: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Export a whole course's attendance for the gradebook."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
        )

    query = (
        db.query(CheckIn)
        .options(
            joinedload(CheckIn.student),
            joinedload(CheckIn.session).joinedload(AttendanceSession.course),
        )
        .join(AttendanceSession, AttendanceSession.id == CheckIn.session_id)
        .filter(AttendanceSession.course_id == course_id)
    )
    if start_date:
        query = query.filter(CheckIn.checked_in_at >= start_date)
    if end_date:
        query = query.filter(CheckIn.checked_in_at <= end_date)

    checkins = query.order_by(CheckIn.checked_in_at).all()
    records = [_row(c) for c in checkins]

    total_enrolled = (
        db.query(Enrollment)
        .filter(
            Enrollment.course_id == course_id, Enrollment.is_active.is_(True)
        )
        .count()
    )
    total_sessions = (
        db.query(AttendanceSession)
        .filter(AttendanceSession.course_id == course_id)
        .count()
    )

    log_action(
        db,
        AuditAction.DATA_EXPORTED,
        user_id=staff.id,
        resource_type="course",
        resource_id=course_id,
        request=request,
        details={"format": export_format, "records": len(records)},
        commit=True,
    )

    if export_format == "csv":
        return _csv_response(records, f"attendance_{course.code}.csv")

    possible = total_enrolled * total_sessions
    return {
        "course_id": course.id,
        "course_code": course.code,
        "course_name": course.name,
        "summary": {
            "total_enrolled": total_enrolled,
            "total_sessions": total_sessions,
            "total_checkins": len(records),
            "attendance_rate": (
                round(len(records) / possible, 4) if possible else 0.0
            ),
        },
        "records": records,
    }
