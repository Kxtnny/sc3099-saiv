"""
User management endpoints.

Route order matters: /me is declared before /{user_id} so the literal path
wins over the parameterised one.
"""

import logging
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.sanitize import escape_like
from app.core.utils import utcnow
from app.dependencies import get_current_user, is_staff, paginate, require_admin
from app.enums import AuditAction, UserRole
from app.models import Course, Enrollment, User
from app.schemas.common import PaginatedResponse
from app.schemas.user import (
    FaceEnrollRequest,
    FaceEnrollResponse,
    UserAdminUpdate,
    UserResponse,
    UserUpdate,
)
from app.services import face_client
from app.services.audit import log_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


def _can_view(viewer: User, target: User, db: Session) -> bool:
    """
    Whether `viewer` may read `target`'s profile.

    Admins see everyone and users see themselves. Instructors and TAs see
    students enrolled in a course they teach.
    """
    if viewer.role == UserRole.ADMIN.value or viewer.id == target.id:
        return True

    if is_staff(viewer):
        shared = (
            db.query(Enrollment.id)
            .join(Course, Course.id == Enrollment.course_id)
            .filter(
                Enrollment.student_id == target.id,
                Enrollment.is_active.is_(True),
                Course.instructor_id == viewer.id,
            )
            .first()
        )
        return shared is not None

    return False


# =============================================================================
# Self-service
# =============================================================================

@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Current user's profile, including consent flags."""
    return current_user


@router.put("/me", response_model=UserResponse)
def update_me(
    payload: UserUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update the current user's own profile and consent preferences.

    Only name and the two consent flags are settable here - role and
    is_active are administrative fields, so a user cannot escalate themselves.
    Markup in full_name is stripped by the schema validator.
    """
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(current_user, field, value)

    if changes:
        log_action(
            db,
            AuditAction.USER_UPDATED,
            user_id=current_user.id,
            resource_type="user",
            resource_id=current_user.id,
            request=request,
            details={"fields": sorted(changes.keys())},
        )

    db.commit()
    db.refresh(current_user)
    return current_user


# =============================================================================
# Administration
# =============================================================================

@router.get("/", response_model=PaginatedResponse[UserResponse])
def list_users(
    role: Optional[UserRole] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List users with filters and pagination. Admin only."""
    query = db.query(User)

    if role is not None:
        query = query.filter(User.role == role.value)
    if is_active is not None:
        query = query.filter(User.is_active.is_(is_active))
    if search:
        term = f"%{escape_like(search.strip())}%"
        query = query.filter(
            or_(User.full_name.ilike(term), User.email.ilike(term))
        )

    total = query.count()
    users = (
        query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()
    )
    return paginate(
        [UserResponse.model_validate(u) for u in users], total, limit, offset
    )


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Read one user. Admin, the user themselves, or their course staff."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if not _can_view(current_user, user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    return user


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    payload: UserAdminUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Update a user's role or status. Admin only."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    changes = payload.model_dump(exclude_unset=True)
    if "role" in changes and changes["role"] is not None:
        changes["role"] = changes["role"].value

    for field, value in changes.items():
        setattr(user, field, value)

    if changes:
        log_action(
            db,
            AuditAction.USER_UPDATED,
            user_id=admin.id,
            resource_type="user",
            resource_id=user.id,
            request=request,
            details={"fields": sorted(changes.keys()), "target": user.email},
        )

    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Request deletion of an account (GDPR-style right to erasure).

    Deactivates the account and schedules purging after the retention window
    rather than deleting immediately: check-ins and audit entries reference
    this row, and audit logs must stay intact. A cleanup job removes the
    personal data once scheduled_deletion_at passes.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if current_user.role != UserRole.ADMIN.value and current_user.id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    user.is_active = False
    user.scheduled_deletion_at = utcnow() + timedelta(days=settings.DATA_RETENTION_DAYS)

    log_action(
        db,
        AuditAction.USER_DELETED,
        user_id=current_user.id,
        resource_type="user",
        resource_id=user.id,
        request=request,
        details={"scheduled_deletion_at": user.scheduled_deletion_at.isoformat()},
    )
    db.commit()
    return None


# =============================================================================
# Face enrollment (Module 3 integration)
# =============================================================================

@router.post("/me/face/enroll", response_model=FaceEnrollResponse)
def enroll_face(
    payload: FaceEnrollRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Enrol the caller's face for later verification.

    PRIVACY: the image is forwarded to the face service, which returns a
    256-bit SimHash of the face embedding (64 hex characters). Only that hash
    is stored - the image is never written to disk, the database, or the logs.
    """
    if not current_user.camera_consent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Camera consent is required before face enrollment",
        )

    try:
        result = face_client.enroll_face(
            current_user.id, payload.image, current_user.camera_consent
        )
    except face_client.FaceServiceUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Face recognition service unavailable",
        )

    if not result.get("enrollment_successful"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("detail") or "No face detected in the supplied image",
        )

    template_hash = result.get("face_template_hash")
    if not template_hash or len(template_hash) != 64:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Face service returned an invalid template hash",
        )

    current_user.face_embedding_hash = template_hash
    current_user.face_enrolled = True

    log_action(
        db,
        AuditAction.FACE_ENROLLED,
        user_id=current_user.id,
        resource_type="user",
        resource_id=current_user.id,
        request=request,
        # Deliberately records only the quality score, never the hash itself.
        details={"quality_score": result.get("quality_score")},
    )
    db.commit()

    return FaceEnrollResponse(
        success=True,
        message="Face enrolled successfully",
        face_enrolled=True,
        quality_score=result.get("quality_score"),
    )
