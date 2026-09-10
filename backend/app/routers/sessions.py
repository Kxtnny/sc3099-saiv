"""
Session management.

Sessions are the check-in windows students attend. Any instructor or admin may
create one for any course - courses are seeded centrally and frequently have no
instructor assigned, so requiring ownership at creation would make sessions
impossible to schedule. Editing and deleting *are* ownership-checked, so one
instructor cannot alter another's session.
"""

import logging
import secrets
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.config import settings
from app.core.sanitize import sanitize_text
from app.core.utils import to_naive_utc, utcnow
from app.dependencies import (
    get_current_user,
    paginate,
    require_instructor,
    require_staff,
)
from app.enums import AuditAction, CheckInStatus, SessionStatus, UserRole
from app.models import AttendanceSession, CheckIn, Course, Enrollment, User
from app.schemas.common import PaginatedResponse
from app.schemas.session import SessionCreate, SessionResponse, SessionUpdate
from app.services.audit import log_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])

# Defaults applied when a session is created without an explicit window.
DEFAULT_CHECKIN_OPENS_BEFORE = timedelta(minutes=15)
DEFAULT_CHECKIN_CLOSES_AFTER = timedelta(minutes=30)


def _serialize(
    session: AttendanceSession,
    *,
    enrolled: Optional[int] = None,
    checked_in: Optional[int] = None,
) -> SessionResponse:
    payload = SessionResponse.model_validate(session)
    if session.course is not None:
        payload.course_code = session.course.code
        payload.course_name = session.course.name
        # Fall back to the course venue when the session does not override it.
        if payload.venue_name is None:
            payload.venue_name = session.course.venue_name
        if payload.venue_latitude is None:
            payload.venue_latitude = session.course.venue_latitude
        if payload.venue_longitude is None:
            payload.venue_longitude = session.course.venue_longitude
        if payload.geofence_radius_meters is None:
            payload.geofence_radius_meters = session.course.geofence_radius_meters
        if payload.risk_threshold is None:
            payload.risk_threshold = session.course.risk_threshold
    payload.qr_code_enabled = session.qr_code_secret is not None
    payload.total_enrolled = enrolled
    payload.checked_in_count = checked_in
    return payload


def _owns(user: User, session: AttendanceSession) -> bool:
    """Admins, the session creator, and the course instructor may edit."""
    if user.role == UserRole.ADMIN.value:
        return True
    if session.instructor_id == user.id:
        return True
    return session.course is not None and session.course.instructor_id == user.id


@router.get("/", response_model=PaginatedResponse[SessionResponse])
def list_sessions(
    status_filter: Optional[SessionStatus] = Query(default=None, alias="status"),
    course_id: Optional[str] = None,
    instructor_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _staff: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """List sessions with filters. Course staff only."""
    query = db.query(AttendanceSession).options(
        joinedload(AttendanceSession.course)
    )

    if status_filter is not None:
        query = query.filter(AttendanceSession.status == status_filter.value)
    if course_id:
        query = query.filter(AttendanceSession.course_id == course_id)
    if instructor_id:
        query = query.filter(AttendanceSession.instructor_id == instructor_id)
    if start_date:
        query = query.filter(AttendanceSession.scheduled_start >= start_date)
    if end_date:
        query = query.filter(AttendanceSession.scheduled_start <= end_date)

    total = query.count()
    sessions = (
        query.order_by(AttendanceSession.scheduled_start.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return paginate([_serialize(s) for s in sessions], total, limit, offset)


@router.get("/active", response_model=List[SessionResponse])
def active_sessions(db: Session = Depends(get_db)):
    """
    Sessions currently open for check-in. Public - no authentication.

    The student app shows these before the user signs in, so only
    non-sensitive scheduling data is returned.
    """
    now = utcnow()
    sessions = (
        db.query(AttendanceSession)
        .options(joinedload(AttendanceSession.course))
        .filter(
            AttendanceSession.status == SessionStatus.ACTIVE.value,
            AttendanceSession.checkin_closes_at >= now,
        )
        .order_by(AttendanceSession.scheduled_start)
        .limit(100)
        .all()
    )
    return [_serialize(s) for s in sessions]


@router.get("/my-sessions", response_model=List[SessionResponse])
def my_sessions(
    status_filter: Optional[SessionStatus] = Query(default=None, alias="status"),
    upcoming: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sessions for courses the caller teaches, or is enrolled in."""
    query = db.query(AttendanceSession).options(
        joinedload(AttendanceSession.course)
    )

    if current_user.role == UserRole.STUDENT.value:
        query = query.join(
            Enrollment, Enrollment.course_id == AttendanceSession.course_id
        ).filter(
            Enrollment.student_id == current_user.id,
            Enrollment.is_active.is_(True),
        )
    elif current_user.role != UserRole.ADMIN.value:
        query = query.outerjoin(
            Course, Course.id == AttendanceSession.course_id
        ).filter(
            (AttendanceSession.instructor_id == current_user.id)
            | (Course.instructor_id == current_user.id)
        )

    if status_filter is not None:
        query = query.filter(AttendanceSession.status == status_filter.value)
    if upcoming:
        query = query.filter(AttendanceSession.scheduled_start >= utcnow())

    sessions = (
        query.order_by(AttendanceSession.scheduled_start.desc()).limit(limit).all()
    )
    return [_serialize(s) for s in sessions]


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Session details, including the venue and geofence a client needs."""
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

    enrolled = (
        db.query(Enrollment)
        .filter(
            Enrollment.course_id == session.course_id,
            Enrollment.is_active.is_(True),
        )
        .count()
    )
    checked_in = (
        db.query(CheckIn).filter(CheckIn.session_id == session.id).count()
    )
    return _serialize(session, enrolled=enrolled, checked_in=checked_in)


@router.post("/", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: SessionCreate,
    request: Request,
    instructor: User = Depends(require_instructor),
    db: Session = Depends(get_db),
):
    """
    Schedule a session.

    New sessions start as `scheduled`; check-in only opens once the status
    moves to `active`.
    """
    course = db.query(Course).filter(Course.id == payload.course_id).first()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
        )

    start = to_naive_utc(payload.scheduled_start)
    end = to_naive_utc(payload.scheduled_end)

    # API-SPECIFICATION.md: scheduled_start must be in the future. A short
    # grace period absorbs clock skew between client and server.
    grace = timedelta(seconds=settings.SESSION_START_GRACE_SECONDS)
    if start < utcnow() - grace:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="scheduled_start must be in the future",
        )
    opens = to_naive_utc(payload.checkin_opens_at) or (
        start - DEFAULT_CHECKIN_OPENS_BEFORE
    )
    closes = to_naive_utc(payload.checkin_closes_at) or (
        start + DEFAULT_CHECKIN_CLOSES_AFTER
    )

    session = AttendanceSession(
        course_id=payload.course_id,
        instructor_id=instructor.id,
        name=sanitize_text(payload.name),
        session_type=payload.session_type.value,
        description=(
            sanitize_text(payload.description, max_length=2000)
            if payload.description
            else None
        ),
        scheduled_start=start,
        scheduled_end=end,
        checkin_opens_at=opens,
        checkin_closes_at=closes,
        status=SessionStatus.SCHEDULED.value,
        venue_name=payload.venue_name,
        venue_latitude=payload.venue_latitude,
        venue_longitude=payload.venue_longitude,
        geofence_radius_meters=payload.geofence_radius_meters,
        require_liveness_check=payload.require_liveness_check,
        require_face_match=payload.require_face_match,
        risk_threshold=payload.risk_threshold,
    )
    db.add(session)
    db.flush()

    log_action(
        db,
        AuditAction.SESSION_CREATED,
        user_id=instructor.id,
        resource_type="session",
        resource_id=session.id,
        request=request,
        details={"course_id": payload.course_id, "name": session.name},
    )
    db.commit()
    db.refresh(session)
    return _serialize(session)


@router.patch("/{session_id}", response_model=SessionResponse)
@router.put("/{session_id}", response_model=SessionResponse)
def update_session(
    session_id: str,
    payload: SessionUpdate,
    request: Request,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """
    Update a session, including its status transition.

    scheduled -> active opens check-in, active -> closed finalises attendance,
    and anything -> cancelled abandons the session.
    """
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
    if not _owns(current_user, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    changes = payload.model_dump(exclude_unset=True)

    if "name" in changes and changes["name"]:
        changes["name"] = sanitize_text(changes["name"])
    if changes.get("description"):
        changes["description"] = sanitize_text(changes["description"], max_length=2000)
    if changes.get("session_type") is not None:
        changes["session_type"] = changes["session_type"].value

    new_status = changes.get("status")
    if new_status is not None:
        changes["status"] = new_status.value
        if new_status == SessionStatus.ACTIVE and session.actual_start is None:
            session.actual_start = utcnow()
        if new_status == SessionStatus.CLOSED:
            session.actual_end = utcnow()

    for field in ("scheduled_start", "scheduled_end", "checkin_opens_at", "checkin_closes_at"):
        if field in changes and changes[field] is not None:
            changes[field] = to_naive_utc(changes[field])

    for field, value in changes.items():
        setattr(session, field, value)

    log_action(
        db,
        AuditAction.SESSION_UPDATED,
        user_id=current_user.id,
        resource_type="session",
        resource_id=session.id,
        request=request,
        details={"fields": sorted(changes.keys())},
    )
    db.commit()
    db.refresh(session)
    return _serialize(session)


@router.post("/{session_id}/qr")
def generate_qr_code(
    session_id: str,
    request: Request,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """
    Issue a fresh one-time QR secret for a session.

    Replay prevention: the instructor projects the code, it expires after
    QR_CODE_TTL_SECONDS, and each regeneration invalidates the previous one -
    so a screenshot sent to an absent friend stops working within minutes.
    """
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
    if not _owns(current_user, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    session.qr_code_secret = secrets.token_urlsafe(32)
    session.qr_code_expires_at = utcnow() + timedelta(
        seconds=settings.QR_CODE_TTL_SECONDS
    )

    log_action(
        db,
        AuditAction.QR_GENERATED,
        user_id=current_user.id,
        resource_type="session",
        resource_id=session.id,
        request=request,
        details={"expires_at": session.qr_code_expires_at.isoformat() + "Z"},
    )
    db.commit()

    return {
        "session_id": session.id,
        "qr_code": session.qr_code_secret,
        "expires_at": session.qr_code_expires_at.isoformat() + "Z",
        "ttl_seconds": settings.QR_CODE_TTL_SECONDS,
    }


@router.delete("/{session_id}/qr", status_code=status.HTTP_204_NO_CONTENT)
def clear_qr_code(
    session_id: str,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Stop requiring a QR code for this session."""
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
    if not _owns(current_user, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )
    session.qr_code_secret = None
    session.qr_code_expires_at = None
    db.commit()
    return None


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str,
    request: Request,
    current_user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """
    Delete a scheduled session.

    Only sessions still in `scheduled` can be removed; once check-in has opened
    the attendance record matters, so those must be cancelled instead.
    """
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
    if not _owns(current_user, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )
    if session.status != SessionStatus.SCHEDULED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only scheduled sessions can be deleted; cancel it instead",
        )

    log_action(
        db,
        AuditAction.SESSION_DELETED,
        user_id=current_user.id,
        resource_type="session",
        resource_id=session.id,
        request=request,
        details={"name": session.name},
    )
    db.delete(session)
    db.commit()
    return None
