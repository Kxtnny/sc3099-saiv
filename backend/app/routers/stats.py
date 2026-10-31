"""
Analytics endpoints powering the instructor dashboard.

Every figure is computed with SQL aggregates rather than by loading rows and
counting in Python, so these stay fast as attendance data grows.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.utils import to_naive_utc, utcnow
from app.dependencies import get_current_user, require_instructor
from app.enums import CheckInStatus, SessionStatus, UserRole
from app.models import AttendanceSession, CheckIn, Course, Enrollment, User
from app.services.authorization import (
    accessible_course_ids,
    require_course_access,
    require_session_access,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stats", tags=["statistics"])


def _rate(numerator: int, denominator: int) -> float:
    """Guard against dividing by zero before any data exists."""
    if not denominator:
        return 0.0
    return round(numerator / denominator, 4)


def _status_counts(db: Session, session_ids: List[str]) -> Dict[str, int]:
    """Count check-ins by status for a set of sessions, in one query."""
    if not session_ids:
        return {}
    rows = (
        db.query(CheckIn.status, func.count(CheckIn.id))
        .filter(CheckIn.session_id.in_(session_ids))
        .group_by(CheckIn.status)
        .all()
    )
    return {status_value: count for status_value, count in rows}


@router.get("/overview")
def overview(
    course_id: Optional[str] = None,
    days: int = Query(default=7, ge=1, le=365),
    current_user: User = Depends(require_instructor),
    db: Session = Depends(get_db),
):
    """Course-scoped counters and trends for instructors and administrators."""
    now = utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=days)

    session_query = db.query(AttendanceSession)
    checkin_query = db.query(CheckIn).join(
        AttendanceSession, AttendanceSession.id == CheckIn.session_id
    )
    if course_id:
        require_course_access(db, current_user, course_id)
        session_query = session_query.filter(
            AttendanceSession.course_id == course_id
        )
        checkin_query = checkin_query.filter(
            AttendanceSession.course_id == course_id
        )
        scoped_course_ids = [course_id]
    elif current_user.role != UserRole.ADMIN.value:
        scoped_course_ids = accessible_course_ids(db, current_user)
        session_query = session_query.filter(
            AttendanceSession.course_id.in_(scoped_course_ids)
        )
        checkin_query = checkin_query.filter(
            AttendanceSession.course_id.in_(scoped_course_ids)
        )
    else:
        scoped_course_ids = None

    total_sessions = session_query.count()
    active_sessions = session_query.filter(
        AttendanceSession.status == SessionStatus.ACTIVE.value
    ).count()

    total_checkins = checkin_query.count()
    today_checkins = checkin_query.filter(
        CheckIn.checked_in_at >= today_start
    ).count()
    week_checkins = checkin_query.filter(CheckIn.checked_in_at >= week_start).count()

    approved = checkin_query.filter(
        CheckIn.status == CheckInStatus.APPROVED.value
    ).count()
    flagged_pending = checkin_query.filter(
        CheckIn.status.in_(
            [CheckInStatus.FLAGGED.value, CheckInStatus.APPEALED.value]
        )
    ).count()
    high_risk_today = checkin_query.filter(
        CheckIn.checked_in_at >= today_start, CheckIn.risk_score >= 0.5
    ).count()

    average_risk = checkin_query.with_entities(
        func.avg(CheckIn.risk_score)
    ).scalar() or 0.0

    # Daily counts for the trend chart, in one grouped query.
    trend_rows = (
        checkin_query.with_entities(
            func.date(CheckIn.checked_in_at).label("day"),
            func.count(CheckIn.id),
        )
        .filter(CheckIn.checked_in_at >= week_start)
        .group_by(func.date(CheckIn.checked_in_at))
        .order_by(func.date(CheckIn.checked_in_at).desc())
        .all()
    )

    enrollment_query = db.query(Enrollment).filter(
        Enrollment.is_active.is_(True)
    )
    if scoped_course_ids is not None:
        enrollment_query = enrollment_query.filter(
            Enrollment.course_id.in_(scoped_course_ids)
        )
    total_enrollments = enrollment_query.count()
    total_students = enrollment_query.join(
        User, User.id == Enrollment.student_id
    ).filter(User.is_active.is_(True)).with_entities(
        func.count(func.distinct(User.id))
    ).scalar() or 0
    course_query = db.query(Course).filter(Course.is_active.is_(True))
    if scoped_course_ids is not None:
        course_query = course_query.filter(Course.id.in_(scoped_course_ids))
    total_courses = course_query.count()
    possible_attendance = (
        db.query(func.count(Enrollment.id))
        .join(
            AttendanceSession,
            AttendanceSession.course_id == Enrollment.course_id,
        )
        .filter(Enrollment.is_active.is_(True))
    )
    if scoped_course_ids is not None:
        possible_attendance = possible_attendance.filter(
            AttendanceSession.course_id.in_(scoped_course_ids)
        )

    return {
        "total_sessions": total_sessions,
        "active_sessions": active_sessions,
        "total_courses": total_courses,
        "total_students": total_students,
        "total_checkins": total_checkins,
        "today_checkins": today_checkins,
        "total_checkins_today": today_checkins,
        "total_checkins_week": week_checkins,
        "flagged_pending": flagged_pending,
        "flagged_pending_review": flagged_pending,
        "approval_rate": _rate(approved, total_checkins),
        "average_attendance_rate": _rate(
            checkin_query.filter(
                CheckIn.status == CheckInStatus.APPROVED.value
            ).count(),
            possible_attendance.scalar() or 0,
        ),
        "average_risk_score": round(float(average_risk), 4),
        "high_risk_checkins_today": high_risk_today,
        "trends": {
            "checkins_by_day": [
                {"date": str(day), "count": count} for day, count in trend_rows
            ]
        },
    }


@router.get("/sessions/{session_id}")
def session_stats(
    session_id: str,
    _staff: User = Depends(require_instructor),
    db: Session = Depends(get_db),
):
    """Attendance breakdown for a single session."""
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
    require_session_access(db, _staff, session)

    total_enrolled = (
        db.query(Enrollment)
        .filter(
            Enrollment.course_id == session.course_id,
            Enrollment.is_active.is_(True),
        )
        .count()
    )

    counts = _status_counts(db, [session.id])
    checked_in = sum(counts.values())
    verified_attendance = counts.get(CheckInStatus.APPROVED.value, 0)

    average_risk = (
        db.query(func.avg(CheckIn.risk_score))
        .filter(CheckIn.session_id == session.id)
        .scalar()
        or 0.0
    )
    average_distance = (
        db.query(func.avg(CheckIn.distance_from_venue_meters))
        .filter(CheckIn.session_id == session.id)
        .scalar()
        or 0.0
    )

    risk_buckets = {"low": 0, "medium": 0, "high": 0}
    for (score,) in db.query(CheckIn.risk_score).filter(
        CheckIn.session_id == session.id
    ):
        if score < 0.3:
            risk_buckets["low"] += 1
        elif score < 0.5:
            risk_buckets["medium"] += 1
        else:
            risk_buckets["high"] += 1

    return {
        "session_id": session.id,
        "session_name": session.name,
        "course_id": session.course_id,
        "course_code": session.course.code if session.course else None,
        "scheduled_start": session.scheduled_start.isoformat() + "Z",
        "status": session.status,
        "total_enrolled": total_enrolled,
        "checked_in_count": checked_in,
        "checked_in": checked_in,
        "approved_count": counts.get(CheckInStatus.APPROVED.value, 0),
        "flagged_count": counts.get(CheckInStatus.FLAGGED.value, 0),
        "rejected_count": counts.get(CheckInStatus.REJECTED.value, 0),
        "pending_count": counts.get(CheckInStatus.PENDING.value, 0),
        "appealed_count": counts.get(CheckInStatus.APPEALED.value, 0),
        "attendance_rate": _rate(verified_attendance, total_enrolled),
        "average_risk_score": round(float(average_risk), 4),
        "average_distance_meters": round(float(average_distance), 2),
        "by_status": counts,
        "risk_distribution": risk_buckets,
    }


@router.get("/courses/{course_id}")
def course_stats(
    course_id: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    _staff: User = Depends(require_instructor),
    db: Session = Depends(get_db),
):
    """Attendance across every session of a course."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
        )
    require_course_access(db, _staff, course_id)

    start = to_naive_utc(start_date)
    end = to_naive_utc(end_date)
    if start and end and start > end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_date must be earlier than or equal to end_date",
        )

    session_query = db.query(AttendanceSession).filter(
        AttendanceSession.course_id == course_id
    )
    if start:
        session_query = session_query.filter(
            AttendanceSession.scheduled_start >= start
        )
    if end:
        session_query = session_query.filter(
            AttendanceSession.scheduled_start <= end
        )
    sessions = session_query.order_by(
        AttendanceSession.scheduled_start.desc()
    ).all()
    session_ids = [s.id for s in sessions]

    total_enrolled = (
        db.query(Enrollment)
        .filter(
            Enrollment.course_id == course_id, Enrollment.is_active.is_(True)
        )
        .count()
    )

    # One grouped query for per-session attendance instead of one per session.
    per_session = dict(
        db.query(CheckIn.session_id, func.count(CheckIn.id))
        .filter(CheckIn.session_id.in_(session_ids))
        .group_by(CheckIn.session_id)
        .all()
    ) if session_ids else {}
    approved_per_session = dict(
        db.query(CheckIn.session_id, func.count(CheckIn.id))
        .filter(
            CheckIn.session_id.in_(session_ids),
            CheckIn.status == CheckInStatus.APPROVED.value,
        )
        .group_by(CheckIn.session_id)
        .all()
    ) if session_ids else {}

    counts = _status_counts(db, session_ids)
    total_checkins = sum(counts.values())
    approved_checkins = counts.get(CheckInStatus.APPROVED.value, 0)
    flagged = counts.get(CheckInStatus.FLAGGED.value, 0) + counts.get(
        CheckInStatus.APPEALED.value, 0
    )

    possible = total_enrolled * len(sessions)

    return {
        "course_id": course.id,
        "course_code": course.code,
        "course_name": course.name,
        "semester": course.semester,
        "total_enrolled": total_enrolled,
        "total_sessions": len(sessions),
        "total_checkins": total_checkins,
        "average_attendance_rate": _rate(approved_checkins, possible),
        "overall_attendance_rate": _rate(approved_checkins, possible),
        "verified_attendance_count": approved_checkins,
        "flagged_checkins": flagged,
        "approved_checkins": approved_checkins,
        "sessions": [
            {
                "session_id": s.id,
                "name": s.name,
                "date": s.scheduled_start.date().isoformat(),
                "status": s.status,
                "checked_in": per_session.get(s.id, 0),
                "attendance_rate": _rate(
                    approved_per_session.get(s.id, 0), total_enrolled
                ),
                "approved_checkins": approved_per_session.get(s.id, 0),
            }
            for s in sessions
        ],
    }


@router.get("/students/{student_id}")
def student_stats(
    student_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One student's attendance record, restricted to self or assigned staff."""
    if (
        current_user.role == UserRole.STUDENT.value
        and current_user.id != student_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Students may only view their own attendance",
        )
    student = db.query(User).filter(User.id == student_id).first()
    if student is None or student.role != UserRole.STUDENT.value:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Student not found"
        )
    if current_user.role not in (
        UserRole.STUDENT.value,
        UserRole.INSTRUCTOR.value,
        UserRole.ADMIN.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    scoped_course_ids = (
        None
        if current_user.role
        in (UserRole.ADMIN.value, UserRole.STUDENT.value)
        else accessible_course_ids(db, current_user)
    )
    enrollments_query = (
        db.query(Enrollment)
        .options(joinedload(Enrollment.course))
        .filter(
            Enrollment.student_id == student_id, Enrollment.is_active.is_(True)
        )
    )
    if scoped_course_ids is not None:
        enrollments_query = enrollments_query.filter(
            Enrollment.course_id.in_(scoped_course_ids)
        )
    enrollments = enrollments_query.all()
    if current_user.role == UserRole.INSTRUCTOR.value and not enrollments:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student is not enrolled in a course you are assigned to",
        )
    course_ids = [e.course_id for e in enrollments]

    total_sessions = (
        db.query(AttendanceSession)
        .filter(AttendanceSession.course_id.in_(course_ids))
        .count()
        if course_ids
        else 0
    )

    checkins_query = (
        db.query(CheckIn)
        .options(
            joinedload(CheckIn.session).joinedload(AttendanceSession.course)
        )
        .filter(CheckIn.student_id == student_id)
    )
    if scoped_course_ids is not None:
        checkins_query = checkins_query.join(
            AttendanceSession,
            AttendanceSession.id == CheckIn.session_id,
        ).filter(AttendanceSession.course_id.in_(course_ids))
    checkins = checkins_query.order_by(CheckIn.checked_in_at.desc()).all()
    attended = sum(
        1
        for c in checkins
        if c.status == CheckInStatus.APPROVED.value
    )
    average_risk = (
        sum(c.risk_score for c in checkins) / len(checkins) if checkins else 0.0
    )

    return {
        "student_id": student.id,
        "student_name": student.full_name,
        "student_email": student.email,
        "total_enrolled_courses": len(enrollments),
        "total_sessions": total_sessions,
        "attended_sessions": attended,
        "attendance_rate": _rate(attended, total_sessions),
        "average_risk_score": round(average_risk, 4),
        "courses": [
            {
                "course_id": e.course_id,
                "course_code": e.course.code if e.course else None,
                "course_name": e.course.name if e.course else None,
            }
            for e in enrollments
        ],
        "recent_sessions": [
            {
                "session_id": c.session_id,
                "session_name": c.session.name if c.session else None,
                "course_code": (
                    c.session.course.code if c.session and c.session.course else None
                ),
                "checked_in_at": c.checked_in_at.isoformat() + "Z",
                "status": c.status,
                "risk_score": c.risk_score,
            }
            for c in checkins[:10]
        ],
    }
