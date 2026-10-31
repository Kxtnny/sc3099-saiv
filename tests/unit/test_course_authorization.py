import asyncio
import csv
import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.core.database import Base
from app.dependencies import require_admin, require_instructor
from app.enums import CheckInStatus, SessionStatus, UserRole
from app.models import AttendanceSession, CheckIn, Course, CourseTA, Enrollment, User
from app.routers import checkins as checkins_router
from app.routers import courses as courses_router
from app.routers import enrollments as enrollments_router
from app.routers import export as export_router
from app.routers import stats as stats_router
from app.schemas.course import CourseTAAssignmentCreate
from app.schemas.enrollment import EnrollmentCreate
from app.services.authorization import (
    accessible_course_ids,
    has_course_access,
    require_course_access,
    require_session_access,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _user(db: Session, role: str, suffix: str) -> User:
    user = User(
        id=f"{role}-{suffix}",
        email=f"{role}-{suffix}@example.test",
        full_name=f"{role.title()} {suffix}",
        hashed_password="not-a-login-credential",
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _course(db: Session, code: str, instructor: User) -> Course:
    course = Course(
        id=f"course-{code}",
        code=code,
        name=f"Course {code}",
        semester="AY 2026-27 Sem 1",
        instructor_id=instructor.id,
    )
    db.add(course)
    db.flush()
    return course


def test_instructor_and_ta_course_access_is_explicit_and_cumulative(db):
    instructor = _user(db, UserRole.INSTRUCTOR.value, "owner")
    other_instructor = _user(db, UserRole.INSTRUCTOR.value, "other")
    ta = _user(db, UserRole.TA.value, "assigned")
    admin = _user(db, UserRole.ADMIN.value, "system")
    owned_course = _course(db, "OWNED", instructor)
    other_course = _course(db, "OTHER", other_instructor)
    db.add(CourseTA(course_id=owned_course.id, ta_id=ta.id, assigned_by_id=admin.id))
    db.flush()

    assert accessible_course_ids(db, instructor) == [owned_course.id]
    assert accessible_course_ids(db, ta) == [owned_course.id]
    assert has_course_access(db, instructor, owned_course.id)
    assert not has_course_access(db, instructor, other_course.id)
    assert has_course_access(db, ta, owned_course.id)
    assert not has_course_access(db, ta, other_course.id)
    assert has_course_access(db, admin, other_course.id)
    review_record = SimpleNamespace(
        session=SimpleNamespace(course_id=owned_course.id)
    )
    assert checkins_router._can_review(ta, review_record, db)
    assert checkins_router._can_review(admin, review_record, db)
    assert not checkins_router._can_review(
        _user(db, UserRole.TA.value, "unassigned"), review_record, db
    )

    with pytest.raises(HTTPException) as denied:
        require_course_access(db, ta, other_course.id)
    assert denied.value.status_code == 403

    session = SimpleNamespace(course_id=other_course.id)
    with pytest.raises(HTTPException) as denied_session:
        require_session_access(db, instructor, session)
    assert denied_session.value.status_code == 403

    db.query(CourseTA).filter(CourseTA.ta_id == ta.id).delete()
    db.flush()
    assert not has_course_access(db, ta, owned_course.id)


def test_ta_cannot_use_instructor_only_operations(db):
    ta = _user(db, UserRole.TA.value, "no-management")

    with pytest.raises(HTTPException) as denied:
        require_instructor(ta)
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as denied_admin:
        require_admin(ta)
    assert denied_admin.value.status_code == 403


def test_enrollment_route_scopes_course_before_shared_record_creation(
    db, monkeypatch
):
    instructor = _user(db, UserRole.INSTRUCTOR.value, "enrollment-owner")
    other_instructor = _user(db, UserRole.INSTRUCTOR.value, "enrollment-other")
    student = _user(db, UserRole.STUDENT.value, "enrollment-student")
    course = _course(db, "ENROLL", instructor)
    monkeypatch.setattr(enrollments_router, "log_action", lambda *args, **kwargs: None)
    payload = EnrollmentCreate(student_id=student.id, course_id=course.id)

    enrollment = enrollments_router.create_enrollment(
        payload, _request(), instructor, db
    )
    assert enrollment.student_id == student.id
    assert enrollment.course_id == course.id

    with pytest.raises(HTTPException) as denied:
        enrollments_router.create_enrollment(
            payload, _request(), other_instructor, db
        )
    assert denied.value.status_code == 403


def test_admin_ta_assignment_routes_create_and_remove_course_scope(db, monkeypatch):
    admin = _user(db, UserRole.ADMIN.value, "assignment-admin")
    instructor = _user(db, UserRole.INSTRUCTOR.value, "assignment-owner")
    ta = _user(db, UserRole.TA.value, "assignment-ta")
    course = _course(db, "ASSIGNED", instructor)
    monkeypatch.setattr(courses_router, "log_action", lambda *args, **kwargs: None)

    assignment = courses_router.assign_course_ta(
        course.id,
        CourseTAAssignmentCreate(ta_id=ta.id),
        _request(),
        admin,
        db,
    )
    assert assignment.course_id == course.id
    assert assignment.ta_id == ta.id
    assert has_course_access(db, ta, course.id)

    with pytest.raises(HTTPException) as duplicate:
        courses_router.assign_course_ta(
            course.id,
            CourseTAAssignmentCreate(ta_id=ta.id),
            _request(),
            admin,
            db,
        )
    assert duplicate.value.status_code == 409

    assert courses_router.unassign_course_ta(
        course.id, ta.id, _request(), admin, db
    ) is None
    assert not has_course_access(db, ta, course.id)


def test_course_stats_honors_date_range_and_rejects_reversed_range(db):
    instructor = _user(db, UserRole.INSTRUCTOR.value, "stats-owner")
    course = _course(db, "STATS", instructor)
    for session_id, scheduled_start in (
        ("stats-jan", datetime(2026, 1, 15)),
        ("stats-feb", datetime(2026, 2, 15)),
    ):
        db.add(
            AttendanceSession(
                id=session_id,
                course_id=course.id,
                instructor_id=instructor.id,
                name=session_id,
                session_type="lecture",
                status=SessionStatus.CLOSED.value,
                scheduled_start=scheduled_start,
                scheduled_end=scheduled_start + timedelta(hours=1),
                checkin_opens_at=scheduled_start - timedelta(minutes=15),
                checkin_closes_at=scheduled_start + timedelta(minutes=30),
            )
        )
    db.flush()

    result = stats_router.course_stats(
        course.id,
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 31, 23, 59, tzinfo=timezone.utc),
        instructor,
        db,
    )
    assert result["total_sessions"] == 1
    assert result["sessions"][0]["session_id"] == "stats-jan"

    with pytest.raises(HTTPException) as invalid_range:
        stats_router.course_stats(
            course.id,
            datetime(2026, 2, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            instructor,
            db,
        )
    assert invalid_range.value.status_code == 422


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/export",
            "raw_path": b"/api/v1/export",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 1234),
        }
    )


def _export_fixture_data(db: Session):
    instructor = _user(db, UserRole.INSTRUCTOR.value, "export-owner")
    other_instructor = _user(db, UserRole.INSTRUCTOR.value, "export-other")
    student = _user(db, UserRole.STUDENT.value, "export-student")
    course = _course(db, "EXPORT", instructor)
    other_course = _course(db, "EXPORT2", other_instructor)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session = AttendanceSession(
        id="session-export",
        course_id=course.id,
        instructor_id=instructor.id,
        name="Lecture, 1",
        session_type="lecture",
        status=SessionStatus.CLOSED.value,
        scheduled_start=now,
        scheduled_end=now + timedelta(hours=1),
        checkin_opens_at=now - timedelta(minutes=15),
        checkin_closes_at=now + timedelta(minutes=30),
    )
    db.add_all(
        [
            session,
            Enrollment(student_id=student.id, course_id=course.id),
            Enrollment(
                student_id=_user(db, UserRole.STUDENT.value, "export-absent").id,
                course_id=course.id,
            ),
        ]
    )
    db.add(
        CheckIn(
            id="checkin-approved",
            session_id=session.id,
            student_id=student.id,
            status=CheckInStatus.APPROVED.value,
            risk_score=0.1,
        )
    )
    db.flush()
    return instructor, other_instructor, student, course, other_course, session


def test_course_export_is_course_scoped_and_uses_approved_attendance(
    db, monkeypatch
):
    instructor, other_instructor, _, course, _, _ = _export_fixture_data(db)
    monkeypatch.setattr(export_router, "log_action", lambda *args, **kwargs: None)

    result = export_router.export_course_attendance(
        course.id, _request(), "json", None, None, instructor, db
    )
    assert result["course_id"] == course.id
    assert result["summary"]["attendance_rate"] == 0.5

    with pytest.raises(HTTPException) as denied:
        export_router.export_course_attendance(
            course.id, _request(), "json", None, None, other_instructor, db
        )
    assert denied.value.status_code == 403

    with pytest.raises(HTTPException) as invalid_range:
        export_router.export_course_attendance(
            course.id,
            _request(),
            "json",
            "2026-01-02T00:00:00Z",
            "2026-01-01T00:00:00Z",
            instructor,
            db,
        )
    assert invalid_range.value.status_code == 422


def test_csv_export_preserves_utf8_quoting_and_neutralizes_formulas():
    response = export_router._csv_response(
        [
            {
                "student_name": "=SUM(1,1)",
                "student_email": "élève@example.test",
                "session_name": 'Lecture, "A"',
            }
        ],
        "attendance.csv",
    )
    payload = asyncio.run(_collect(response.body_iterator))

    assert payload.startswith(b"\xef\xbb\xbf")
    decoded = payload.decode("utf-8-sig")
    row = next(csv.DictReader(io.StringIO(decoded)))
    assert row["student_name"] == "'=SUM(1,1)"
    assert row["student_email"] == "élève@example.test"
    assert row["session_name"] == 'Lecture, "A"'
    assert response.media_type == "text/csv; charset=utf-8"


async def _collect(body_iterator) -> bytes:
    chunks = []
    async for chunk in body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)
