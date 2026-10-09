"""
Course management.

Listing and reading courses are open to anonymous callers: the student PWA
shows the catalogue before login, and the public tests exercise GET /courses/
without a token. Writes are admin-only.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.sanitize import sanitize_text
from app.dependencies import get_optional_user, paginate, require_admin
from app.enums import AuditAction, UserRole
from app.models import Course, User
from app.schemas.common import PaginatedResponse
from app.schemas.course import CourseCreate, CourseResponse, CourseUpdate
from app.services.audit import log_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/courses", tags=["courses"])


def _serialize(course: Course) -> CourseResponse:
    """Attach the instructor's display name to the course payload."""
    payload = CourseResponse.model_validate(course)
    if course.instructor is not None:
        payload.instructor_name = course.instructor.full_name
    return payload


@router.get("/", response_model=PaginatedResponse[CourseResponse])
def list_courses(
    is_active: Optional[bool] = None,
    semester: Optional[str] = Query(default=None, max_length=20),
    instructor_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """List courses. Readable without authentication."""
    query = db.query(Course).options(joinedload(Course.instructor))

    if is_active is not None:
        query = query.filter(Course.is_active.is_(is_active))
    if semester:
        query = query.filter(Course.semester == semester)
    if instructor_id:
        query = query.filter(Course.instructor_id == instructor_id)

    total = query.count()
    courses = (
        query.order_by(Course.created_at.desc()).offset(offset).limit(limit).all()
    )
    return paginate([_serialize(c) for c in courses], total, limit, offset)


@router.get("/{course_id}", response_model=CourseResponse)
def get_course(
    course_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Course details, including venue and geofence settings."""
    course = (
        db.query(Course)
        .options(joinedload(Course.instructor))
        .filter(Course.id == course_id)
        .first()
    )
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
        )
    return _serialize(course)


@router.post("/", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
def create_course(
    payload: CourseCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create a course. Admin only."""
    code = payload.code.strip().upper()
    if db.query(Course.id).filter(Course.code == code).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course code already exists",
        )

    if payload.instructor_id:
        instructor = db.query(User).filter(User.id == payload.instructor_id).first()
        if instructor is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Instructor not found"
            )
        if instructor.role not in (UserRole.INSTRUCTOR.value, UserRole.ADMIN.value):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Assigned user is not an instructor",
            )

    data = payload.model_dump()
    data["code"] = code
    data["name"] = sanitize_text(data["name"])
    if data.get("description"):
        data["description"] = sanitize_text(data["description"], max_length=2000)

    course = Course(**data)
    db.add(course)

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course code already exists",
        )

    log_action(
        db,
        AuditAction.COURSE_CREATED,
        user_id=admin.id,
        resource_type="course",
        resource_id=course.id,
        request=request,
        details={"code": course.code},
    )
    db.commit()
    db.refresh(course)
    return _serialize(course)


@router.put("/{course_id}", response_model=CourseResponse)
@router.patch("/{course_id}", response_model=CourseResponse)
def update_course(
    course_id: str,
    payload: CourseUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Update a course. Admin only."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
        )

    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"]:
        changes["name"] = sanitize_text(changes["name"])
    if "description" in changes and changes["description"]:
        changes["description"] = sanitize_text(changes["description"], max_length=2000)

    for field, value in changes.items():
        setattr(course, field, value)

    log_action(
        db,
        AuditAction.COURSE_UPDATED,
        user_id=admin.id,
        resource_type="course",
        resource_id=course.id,
        request=request,
        details={"fields": sorted(changes.keys())},
    )
    db.commit()
    db.refresh(course)
    return _serialize(course)


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(
    course_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Soft-delete a course.

    Sets is_active=False rather than removing the row: sessions, enrollments
    and check-ins reference it, and attendance history must survive.
    """
    course = db.query(Course).filter(Course.id == course_id).first()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
        )

    course.is_active = False
    log_action(
        db,
        AuditAction.COURSE_DELETED,
        user_id=admin.id,
        resource_type="course",
        resource_id=course.id,
        request=request,
        details={"code": course.code},
    )
    db.commit()
    return None
