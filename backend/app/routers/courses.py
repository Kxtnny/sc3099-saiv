"""
Course management.

Listing and reading courses are open to anonymous callers: the student PWA
shows the catalogue before login, and the public tests exercise GET /courses/
without a token. Writes are admin-only.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import false
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.sanitize import sanitize_text
from app.dependencies import (
    get_current_user,
    get_optional_user,
    paginate,
    require_admin,
)
from app.enums import AuditAction, UserRole
from app.models import Course, CourseTA, User
from app.schemas.common import PaginatedResponse
from app.schemas.course import (
    CourseCreate,
    CourseResponse,
    CourseTAAssignmentCreate,
    CourseTAAssignmentResponse,
    CourseUpdate,
)
from app.services.authorization import (
    accessible_course_ids,
    has_course_access,
    require_course_access,
)
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
    is_active: Optional[bool] = True,
    semester: Optional[str] = Query(default=None, max_length=20),
    instructor_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """List courses. Readable without authentication."""
    query = db.query(Course).options(joinedload(Course.instructor))

    if current_user and current_user.role in (
        UserRole.INSTRUCTOR.value,
        UserRole.TA.value,
    ):
        course_ids = accessible_course_ids(db, current_user)
        query = query.filter(
            Course.id.in_(course_ids) if course_ids else false()
        )
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
    if current_user and current_user.role in (
        UserRole.INSTRUCTOR.value,
        UserRole.TA.value,
    ):
        require_course_access(db, current_user, course_id)
    return _serialize(course)


@router.get(
    "/{course_id}/tas", response_model=list[CourseTAAssignmentResponse]
)
def list_course_tas(
    course_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List TAs assigned to a course the caller is allowed to access."""
    course = db.query(Course.id).filter(Course.id == course_id).first()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
        )
    require_course_access(db, current_user, course_id)
    assignments = (
        db.query(CourseTA)
        .options(joinedload(CourseTA.ta))
        .filter(CourseTA.course_id == course_id)
        .order_by(CourseTA.assigned_at)
        .all()
    )
    return [
        CourseTAAssignmentResponse(
            id=assignment.id,
            course_id=assignment.course_id,
            ta_id=assignment.ta_id,
            assigned_by_id=assignment.assigned_by_id,
            assigned_at=assignment.assigned_at,
            ta_email=assignment.ta.email if assignment.ta else None,
            ta_name=assignment.ta.full_name if assignment.ta else None,
        )
        for assignment in assignments
    ]


@router.post(
    "/{course_id}/tas",
    response_model=CourseTAAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def assign_course_ta(
    course_id: str,
    payload: CourseTAAssignmentCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Assign a TA to a course. Assignment management is admin-only."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
        )
    ta = db.query(User).filter(User.id == payload.ta_id).first()
    if ta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="TA not found"
        )
    if ta.role != UserRole.TA.value or not ta.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The assigned user must be an active TA account",
        )
    assignment = (
        db.query(CourseTA)
        .filter(CourseTA.course_id == course_id, CourseTA.ta_id == ta.id)
        .first()
    )
    if assignment is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="TA is already assigned to this course",
        )

    assignment = CourseTA(
        course_id=course_id,
        ta_id=ta.id,
        assigned_by_id=admin.id,
    )
    db.add(assignment)
    log_action(
        db,
        AuditAction.COURSE_TA_ASSIGNED,
        user_id=admin.id,
        resource_type="course",
        resource_id=course_id,
        request=request,
        details={"ta_id": ta.id},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="TA is already assigned to this course",
        ) from exc
    db.refresh(assignment)
    return CourseTAAssignmentResponse(
        id=assignment.id,
        course_id=assignment.course_id,
        ta_id=assignment.ta_id,
        assigned_by_id=assignment.assigned_by_id,
        assigned_at=assignment.assigned_at,
        ta_email=ta.email,
        ta_name=ta.full_name,
    )


@router.delete(
    "/{course_id}/tas/{ta_id}", status_code=status.HTTP_204_NO_CONTENT
)
def unassign_course_ta(
    course_id: str,
    ta_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Remove a TA assignment. Assignment management is admin-only."""
    assignment = (
        db.query(CourseTA)
        .filter(CourseTA.course_id == course_id, CourseTA.ta_id == ta_id)
        .first()
    )
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="TA assignment not found",
        )
    db.delete(assignment)
    log_action(
        db,
        AuditAction.COURSE_TA_REMOVED,
        user_id=admin.id,
        resource_type="course",
        resource_id=course_id,
        request=request,
        details={"ta_id": ta_id},
    )
    db.commit()
    return None


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
    if changes.get("instructor_id"):
        instructor = (
            db.query(User)
            .filter(User.id == changes["instructor_id"])
            .first()
        )
        if instructor is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Instructor not found",
            )
        if instructor.role not in (
            UserRole.INSTRUCTOR.value,
            UserRole.ADMIN.value,
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Assigned user is not an instructor",
            )
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
