"""Course and resource authorization shared by API routers."""

from typing import List

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.enums import UserRole
from app.models import AttendanceSession, Course, CourseTA, User


def accessible_course_ids(db: Session, user: User) -> List[str]:
    """Return all course IDs assigned to an instructor or TA."""
    if user.role == UserRole.ADMIN.value:
        return [course_id for (course_id,) in db.query(Course.id).all()]
    if user.role == UserRole.INSTRUCTOR.value:
        return [
            course_id
            for (course_id,) in db.query(Course.id)
            .filter(Course.instructor_id == user.id)
            .all()
        ]
    if user.role == UserRole.TA.value:
        return [
            course_id
            for (course_id,) in db.query(CourseTA.course_id)
            .join(Course, Course.id == CourseTA.course_id)
            .filter(CourseTA.ta_id == user.id, Course.is_active.is_(True))
            .all()
        ]
    return []


def has_course_access(db: Session, user: User, course_id: str) -> bool:
    """Check role and explicit course ownership/assignment."""
    if user.role == UserRole.ADMIN.value:
        return True
    if user.role == UserRole.INSTRUCTOR.value:
        return (
            db.query(Course.id)
            .filter(Course.id == course_id, Course.instructor_id == user.id)
            .first()
            is not None
        )
    if user.role == UserRole.TA.value:
        return (
            db.query(CourseTA.id)
            .join(Course, Course.id == CourseTA.course_id)
            .filter(
                CourseTA.course_id == course_id,
                CourseTA.ta_id == user.id,
                Course.is_active.is_(True),
            )
            .first()
            is not None
        )
    return False


def require_course_access(db: Session, user: User, course_id: str) -> None:
    if not has_course_access(db, user, course_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this course",
        )


def require_session_access(
    db: Session, user: User, session: AttendanceSession
) -> None:
    require_course_access(db, user, session.course_id)
