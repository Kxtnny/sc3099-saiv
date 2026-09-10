"""
Enrollment management.

Course staff (TA, instructor, admin) may manage any course roster. Ownership is
deliberately not required: courses are created centrally by an admin and often
have no instructor assigned, so an ownership check would lock the real teaching
staff out of their own roster.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.sanitize import escape_like
from app.core.security import get_password_hash
from app.core.utils import new_uuid, utcnow
from app.dependencies import get_current_user, require_staff
from app.enums import AuditAction, UserRole
from app.models import Course, Enrollment, User
from app.schemas.enrollment import (
    BulkEnrollmentResult,
    CourseEnrollmentList,
    EnrolledStudent,
    EnrollmentBulkCreate,
    EnrollmentCreate,
    EnrollmentResponse,
    MyEnrollmentResponse,
)
from app.services.audit import log_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/enrollments", tags=["enrollments"])


def create_enrollment_record(
    db: Session, student_id: str, course_id: str
) -> Enrollment:
    """
    Enroll a student, reactivating a dropped enrollment if one exists.

    Shared with the admin router so both paths behave identically.
    """
    student = db.query(User).filter(User.id == student_id).first()
    if student is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Student not found"
        )

    course = db.query(Course).filter(Course.id == course_id).first()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
        )

    existing = (
        db.query(Enrollment)
        .filter(
            Enrollment.student_id == student_id, Enrollment.course_id == course_id
        )
        .first()
    )
    if existing is not None:
        if existing.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Student already enrolled in this course",
            )
        existing.is_active = True
        existing.dropped_at = None
        existing.enrolled_at = utcnow()
        db.flush()
        return existing

    enrollment = Enrollment(student_id=student_id, course_id=course_id)
    db.add(enrollment)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student already enrolled in this course",
        )
    return enrollment


@router.get("/my-enrollments", response_model=List[MyEnrollmentResponse])
def my_enrollments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Courses the current student is enrolled in."""
    rows = (
        db.query(Enrollment)
        .options(joinedload(Enrollment.course).joinedload(Course.instructor))
        .filter(
            Enrollment.student_id == current_user.id,
            Enrollment.is_active.is_(True),
        )
        .order_by(Enrollment.enrolled_at.desc())
        .all()
    )

    return [
        MyEnrollmentResponse(
            id=row.id,
            course_id=row.course_id,
            course_code=row.course.code if row.course else "",
            course_name=row.course.name if row.course else "",
            semester=row.course.semester if row.course else "",
            instructor_name=(
                row.course.instructor.full_name
                if row.course and row.course.instructor
                else None
            ),
            enrolled_at=row.enrolled_at,
            is_active=row.is_active,
        )
        for row in rows
    ]


@router.get("/course/{course_id}", response_model=CourseEnrollmentList)
def course_enrollments(
    course_id: str,
    is_active: bool = True,
    search: Optional[str] = Query(default=None, max_length=255),
    _staff: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Roster for a course. Course staff only."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
        )

    # joinedload avoids one query per student (N+1) when building the roster.
    query = (
        db.query(Enrollment)
        .options(joinedload(Enrollment.student))
        .join(User, User.id == Enrollment.student_id)
        .filter(Enrollment.course_id == course_id)
    )
    if is_active is not None:
        query = query.filter(Enrollment.is_active.is_(is_active))
    if search:
        term = f"%{escape_like(search.strip())}%"
        query = query.filter(
            or_(User.full_name.ilike(term), User.email.ilike(term))
        )

    rows = query.order_by(User.full_name).all()

    return CourseEnrollmentList(
        course_id=course.id,
        course_code=course.code,
        total_enrolled=len(rows),
        students=[
            EnrolledStudent(
                id=row.id,
                student_id=row.student_id,
                student_email=row.student.email,
                student_name=row.student.full_name,
                enrolled_at=row.enrolled_at,
                is_active=row.is_active,
                face_enrolled=row.student.face_enrolled,
            )
            for row in rows
            if row.student is not None
        ],
    )


@router.post(
    "/", response_model=EnrollmentResponse, status_code=status.HTTP_201_CREATED
)
def create_enrollment(
    payload: EnrollmentCreate,
    request: Request,
    staff: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Enroll one student in a course."""
    enrollment = create_enrollment_record(db, payload.student_id, payload.course_id)
    log_action(
        db,
        AuditAction.ENROLLMENT_ADDED,
        user_id=staff.id,
        resource_type="enrollment",
        resource_id=enrollment.id,
        request=request,
        details={"student_id": payload.student_id, "course_id": payload.course_id},
    )
    db.commit()
    db.refresh(enrollment)
    return enrollment


@router.post("/bulk", response_model=BulkEnrollmentResult)
def bulk_enroll(
    payload: EnrollmentBulkCreate,
    request: Request,
    staff: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Enroll many students by email, optionally creating missing accounts."""
    course = db.query(Course).filter(Course.id == payload.course_id).first()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
        )

    enrolled = already = not_found = created = 0
    details = []

    for raw_email in payload.student_emails:
        email = str(raw_email).lower().strip()
        student = db.query(User).filter(User.email == email).first()

        if student is None:
            if not payload.create_accounts:
                not_found += 1
                details.append({"email": email, "status": "not_found"})
                continue
            # Placeholder account with an unguessable random password: it
            # cannot be logged into until the student resets it.
            student = User(
                id=new_uuid(),
                email=email,
                full_name=email.split("@")[0],
                hashed_password=get_password_hash(new_uuid()),
                role=UserRole.STUDENT.value,
                is_active=True,
            )
            db.add(student)
            db.flush()
            created += 1

        existing = (
            db.query(Enrollment)
            .filter(
                Enrollment.student_id == student.id,
                Enrollment.course_id == payload.course_id,
            )
            .first()
        )
        if existing is not None and existing.is_active:
            already += 1
            details.append({"email": email, "status": "already_enrolled"})
            continue

        if existing is not None:
            existing.is_active = True
            existing.dropped_at = None
        else:
            db.add(Enrollment(student_id=student.id, course_id=payload.course_id))
        db.flush()
        enrolled += 1
        details.append({"email": email, "status": "enrolled"})

    log_action(
        db,
        AuditAction.ENROLLMENT_ADDED,
        user_id=staff.id,
        resource_type="course",
        resource_id=payload.course_id,
        request=request,
        details={"bulk": True, "enrolled": enrolled, "created": created},
    )
    db.commit()

    return BulkEnrollmentResult(
        enrolled=enrolled,
        already_enrolled=already,
        not_found=not_found,
        created=created,
        details=details,
    )


@router.delete("/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_enrollment(
    enrollment_id: str,
    request: Request,
    staff: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """
    Drop an enrollment.

    Soft-deleted so past check-ins stay attributable to a real roster entry.
    """
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if enrollment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Enrollment not found"
        )

    enrollment.is_active = False
    enrollment.dropped_at = utcnow()

    log_action(
        db,
        AuditAction.ENROLLMENT_REMOVED,
        user_id=staff.id,
        resource_type="enrollment",
        resource_id=enrollment.id,
        request=request,
        details={
            "student_id": enrollment.student_id,
            "course_id": enrollment.course_id,
        },
    )
    db.commit()
    return None
