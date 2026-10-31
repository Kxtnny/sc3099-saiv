from unittest.mock import Mock

from app.access import filter_courses_for_user, load_visible_courses


COURSES = [
    {"id": "course-1", "instructor_id": "instructor-1"},
    {"id": "course-2", "instructor_id": "instructor-2"},
]


def test_course_scopes_are_fail_closed_and_role_specific(monkeypatch):
    list_courses = Mock(
        side_effect=[
            (True, {"items": [COURSES[0]], "total": 2}),
            (True, {"items": [COURSES[1]], "total": 2}),
        ]
    )
    monkeypatch.setattr("app.access.api_client.list_courses", list_courses)

    ok, courses, message = load_visible_courses(
        "token", {"id": "instructor-1", "role": "instructor"}
    )
    assert ok
    assert courses == [COURSES[0]]
    assert message is None
    assert list_courses.call_count == 2
    assert list_courses.call_args_list[0].kwargs == {
        "token": "token",
        "limit": 100,
        "offset": 0,
    }

    ok, courses, message = load_visible_courses("token", {"role": "ta"})
    assert ok
    assert courses == []
    assert "TA course assignments" in message
    assert list_courses.call_count == 2

    assert filter_courses_for_user({"role": "admin"}, COURSES) == COURSES
    assert filter_courses_for_user({"role": "student"}, COURSES) == []
    assert filter_courses_for_user({"role": "invalid"}, COURSES) == []
    assert filter_courses_for_user(
        {"id": "instructor-1", "role": "instructor"}, COURSES
    ) == [COURSES[0]]


def test_course_loader_surfaces_invalid_pagination_response(monkeypatch):
    monkeypatch.setattr(
        "app.access.api_client.list_courses",
        Mock(return_value=(True, {"items": [], "total": -1})),
    )

    ok, courses, error = load_visible_courses(
        "token", {"id": "instructor-1", "role": "instructor"}
    )

    assert not ok
    assert courses == []
    assert "invalid total count" in error
