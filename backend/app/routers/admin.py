"""
Administrative endpoints.

These exist so an operator - or an automated test harness - can set up state
that the normal role-scoped API deliberately makes hard to reach: deactivating
an account, forcing a session status, or enrolling a student into a course the
caller does not teach. Every route is admin-only and audited.
"""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.sanitize import sanitize_text
from app.core.security import get_password_hash
from app.core.utils import utcnow
from app.dependencies import require_admin
from app.enums import AuditAction, SessionStatus, UserRole
from app.models import AttendanceSession, User
from app.routers.enrollments import create_enrollment_record
from app.schemas.enrollment import EnrollmentCreate, EnrollmentResponse
from app.schemas.session import SessionStatusUpdate
from app.services import retention
from app.services.audit import log_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


class BulkUserItem(BaseModel):
    email: EmailStr
    password: str = Field(min_length=settings.MIN_PASSWORD_LENGTH, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    role: UserRole = UserRole.STUDENT


class BulkUserCreate(BaseModel):
    users: List[BulkUserItem] = Field(min_length=1, max_length=500)


def _get_user(db: Session, user_id: str) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return user


@router.patch("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Disable an account. The user can no longer log in."""
    user = _get_user(db, user_id)
    user.is_active = False

    log_action(
        db,
        AuditAction.USER_UPDATED,
        user_id=admin.id,
        resource_type="user",
        resource_id=user.id,
        request=request,
        details={"action": "deactivated", "email": user.email},
    )
    db.commit()

    return {
        "id": user.id,
        "email": user.email,
        "is_active": False,
        "message": "User deactivated successfully",
    }


@router.patch("/users/{user_id}/activate")
def activate_user(
    user_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Re-enable a disabled account."""
    user = _get_user(db, user_id)
    user.is_active = True

    log_action(
        db,
        AuditAction.USER_UPDATED,
        user_id=admin.id,
        resource_type="user",
        resource_id=user.id,
        request=request,
        details={"action": "activated", "email": user.email},
    )
    db.commit()

    return {
        "id": user.id,
        "email": user.email,
        "is_active": True,
        "message": "User activated successfully",
    }


@router.post("/users/bulk", status_code=status.HTTP_201_CREATED)
def bulk_create_users(
    payload: BulkUserCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Create many accounts at once, for seeding or load testing.

    Individual failures - a duplicate email, say - are collected and reported
    rather than aborting the whole batch.
    """
    created: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    existing_emails = {
        email
        for (email,) in db.query(User.email).filter(
            User.email.in_([str(u.email).lower().strip() for u in payload.users])
        )
    }

    for item in payload.users:
        email = str(item.email).lower().strip()
        if email in existing_emails:
            errors.append({"email": email, "error": "Email already registered"})
            continue

        user = User(
            email=email,
            full_name=sanitize_text(item.full_name),
            hashed_password=get_password_hash(item.password),
            role=item.role.value,
            is_active=True,
        )
        db.add(user)
        db.flush()
        existing_emails.add(email)
        created.append(
            {
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
            }
        )

    log_action(
        db,
        AuditAction.USER_CREATED,
        user_id=admin.id,
        resource_type="user",
        request=request,
        details={"bulk": True, "created": len(created), "failed": len(errors)},
    )
    db.commit()

    return {
        "created": len(created),
        "failed": len(errors),
        "users": created,
        "errors": errors,
    }


@router.patch("/sessions/{session_id}/status")
def set_session_status(
    session_id: str,
    payload: SessionStatusUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Force a session into a given status, bypassing ownership.

    This is how check-in is opened for a session created by another user.
    """
    session = (
        db.query(AttendanceSession)
        .filter(AttendanceSession.id == session_id)
        .first()
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    previous = session.status
    session.status = payload.status.value

    if payload.status == SessionStatus.ACTIVE and session.actual_start is None:
        session.actual_start = utcnow()
    if payload.status == SessionStatus.CLOSED:
        session.actual_end = utcnow()

    log_action(
        db,
        AuditAction.SESSION_UPDATED,
        user_id=admin.id,
        resource_type="session",
        resource_id=session.id,
        request=request,
        details={"from": previous, "to": session.status},
    )
    db.commit()
    db.refresh(session)

    return {
        "id": session.id,
        "name": session.name,
        "status": session.status,
        "message": f"Session status changed from '{previous}' to '{session.status}'",
    }


@router.get("/retention")
def retention_status(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """What the retention policy has queued for scrubbing."""
    return {
        "retention_days": settings.DATA_RETENTION_DAYS,
        "sweep_enabled": settings.RETENTION_SWEEP_ENABLED,
        "sweep_interval_seconds": settings.RETENTION_SWEEP_INTERVAL_SECONDS,
        **retention.pending_counts(db),
    }


@router.post("/retention/purge")
def run_retention_purge(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Run the retention sweep now rather than waiting for the scheduler.

    Anonymises users and scrubs check-ins whose scheduled_deletion_at has
    passed. Audit logs are never touched.
    """
    counts = retention.purge_expired(db, actor_id=admin.id)
    return {"message": "Retention sweep complete", **counts}


@router.post(
    "/enrollments/",
    response_model=EnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/enrollments",
    response_model=EnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def admin_create_enrollment(
    payload: EnrollmentCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Enroll a student without the instructor-ownership check."""
    enrollment = create_enrollment_record(db, payload.student_id, payload.course_id)

    log_action(
        db,
        AuditAction.ENROLLMENT_ADDED,
        user_id=admin.id,
        resource_type="enrollment",
        resource_id=enrollment.id,
        request=request,
        details={
            "student_id": payload.student_id,
            "course_id": payload.course_id,
            "admin_override": True,
        },
    )
    db.commit()
    db.refresh(enrollment)
    return enrollment
