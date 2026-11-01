"""Render pages through Streamlit's AppTest so layout errors fail in CI, not in the browser."""

from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from app.api_client import api_client


COURSE = {"id": "course-1", "code": "CS1001", "name": "Intro", "instructor_id": "instructor-id"}
SESSION = {
    "id": "session-1",
    "name": "Week 1",
    "course_id": "course-1",
    "course_code": "CS1001",
    "instructor_id": "instructor-id",
    "status": "active",
    "session_type": "lecture",
    "scheduled_start": "2026-10-16T06:00:00Z",
    "scheduled_end": "2026-10-16T08:00:00Z",
    "venue_name": "LT1",
    "total_enrolled": 10,
    "checked_in_count": 4,
}


def _render_sessions():
    from app.views import sessions

    sessions.render()


def test_sessions_page_renders_session_panels_without_errors(monkeypatch):
    user = {"id": "instructor-id", "role": "instructor"}
    monkeypatch.setattr(
        api_client, "list_courses", Mock(return_value=(True, {"items": [COURSE], "total": 1}))
    )
    monkeypatch.setattr(
        api_client, "list_sessions", Mock(return_value=(True, {"items": [SESSION], "total": 1}))
    )

    app = AppTest.from_function(_render_sessions)
    app.session_state["access_token"] = "access-token"
    app.session_state["refresh_token"] = "refresh-token"
    app.session_state["user"] = user
    app.run()

    assert not app.exception, [e.message for e in app.exception]
    assert any("Session Check-ins" in m.value for m in app.markdown)


DEVICE = {
    "id": "device-1",
    "user_email": "student@example.com",
    "device_name": "Phone",
    "is_trusted": False,
    "is_active": True,
    "clean_checkins": 2,
    "total_checkins": 4,
    "last_seen_at": "2026-10-16T06:00:00Z",
}


def _render_devices():
    from app.views import devices

    devices.render()


@pytest.mark.parametrize(
    ("overrides", "visible", "hidden"),
    [
        ({}, "✅ Trust Device", "♻️ Reactivate Device"),
        ({"is_trusted": True}, "↩️ Remove Trust", "✅ Trust Device"),
        ({"is_active": False}, "♻️ Reactivate Device", "🚫 Revoke Device"),
    ],
)
def test_device_page_offers_actions_for_the_device_state(monkeypatch, overrides, visible, hidden):
    monkeypatch.setattr(
        api_client,
        "list_devices",
        Mock(return_value=(True, {"items": [{**DEVICE, **overrides}], "total": 1})),
    )

    app = AppTest.from_function(_render_devices)
    app.session_state["access_token"] = "access-token"
    app.session_state["user"] = {"id": "admin-id", "role": "admin"}
    app.run()

    labels = [button.label for button in app.button]
    assert not app.exception
    assert visible in labels
    assert hidden not in labels


def test_device_page_is_refused_to_non_admins(monkeypatch):
    list_devices = Mock(return_value=(True, {"items": [], "total": 0}))
    monkeypatch.setattr(api_client, "list_devices", list_devices)

    app = AppTest.from_function(_render_devices)
    app.session_state["access_token"] = "access-token"
    app.session_state["user"] = {"id": "instructor-id", "role": "instructor"}
    app.run()

    assert not app.exception
    assert app.error[0].value == "Access restricted to Administrators."
    list_devices.assert_not_called()


def _render_session_checkins():
    from app.views import session_checkins

    session_checkins.render()


def test_assigned_ta_can_open_a_session_and_see_its_checkins(monkeypatch):
    get_checkins = Mock(return_value=(True, []))
    monkeypatch.setattr(
        api_client, "list_courses", Mock(return_value=(True, {"items": [COURSE], "total": 1}))
    )
    monkeypatch.setattr(api_client, "get_my_sessions", Mock(return_value=(True, [SESSION])))
    monkeypatch.setattr(api_client, "get_session_checkins", get_checkins)

    app = AppTest.from_function(_render_session_checkins)
    app.session_state["access_token"] = "access-token"
    app.session_state["user"] = {"id": "ta-id", "role": "ta"}
    app.run()

    assert not app.exception
    get_checkins.assert_called_once_with("access-token", "session-1")


ADMIN_USERS = [
    {
        "id": "admin-id",
        "email": "admin@example.com",
        "full_name": "Admin",
        "role": "admin",
        "is_active": True,
    },
    {
        "id": "instructor-a",
        "email": "a@example.com",
        "full_name": "Instructor A",
        "role": "instructor",
        "is_active": True,
    },
    {
        "id": "instructor-b",
        "email": "b@example.com",
        "full_name": "Instructor B",
        "role": "instructor",
        "is_active": True,
    },
]
LABEL_A = "Instructor A (a@example.com)"
LABEL_B = "Instructor B (b@example.com)"


def _render_administration():
    from app.views import administration

    administration.render()


def _open_course_form(monkeypatch, instructor_id, users_ok=True, instructor_name=None):
    course = {
        "id": "course-1",
        "code": "CS1001",
        "name": "Intro",
        "semester": "AY1",
        "is_active": True,
        "instructor_id": instructor_id,
        "instructor_name": instructor_name,
    }
    monkeypatch.setattr(
        api_client,
        "list_users",
        Mock(
            return_value=(True, {"items": ADMIN_USERS, "total": 3})
            if users_ok
            else (False, "unavailable")
        ),
    )
    monkeypatch.setattr(
        api_client,
        "list_courses",
        lambda token, is_active, limit, offset: (
            True,
            {"items": [course] if is_active else [], "total": 1 if is_active else 0},
        ),
    )
    update_course = Mock(return_value=(True, {}))
    monkeypatch.setattr(api_client, "update_course", update_course)
    # AppTest keeps the submit button pressed, so a real rerun would save forever.
    monkeypatch.setattr("streamlit.rerun", Mock())

    app = AppTest.from_function(_render_administration)
    app.session_state["access_token"] = "access-token"
    app.session_state["user"] = {"id": "admin-id", "role": "admin"}
    app.run()
    assert not app.exception
    return app, update_course


def _save_course(app):
    next(button for button in app.button if button.label == "Save course").click().run()


@pytest.mark.parametrize(
    ("current", "chosen", "expected"),
    [
        (None, LABEL_A, "instructor-a"),
        ("instructor-a", LABEL_B, "instructor-b"),
        ("instructor-a", "Unassigned", None),
    ],
)
def test_admin_can_change_a_courses_instructor(monkeypatch, current, chosen, expected):
    app, update_course = _open_course_form(monkeypatch, current)

    app.selectbox(key="admin_course_instructor_course-1").set_value(chosen)
    _save_course(app)

    assert not app.exception
    assert update_course.call_args.args[2]["instructor_id"] == expected


def test_saving_a_course_leaves_an_unchanged_instructor_alone(monkeypatch):
    app, update_course = _open_course_form(monkeypatch, "instructor-a")

    assert app.selectbox(key="admin_course_instructor_course-1").value == LABEL_A
    _save_course(app)

    assert "instructor_id" not in update_course.call_args.args[2]


def test_failed_user_list_cannot_unassign_a_course(monkeypatch):
    app, update_course = _open_course_form(monkeypatch, "instructor-a", users_ok=False)

    assert "admin_course_instructor_course-1" not in [box.key for box in app.selectbox]
    _save_course(app)

    assert "instructor_id" not in update_course.call_args.args[2]


def test_unlisted_current_instructor_stays_selected(monkeypatch):
    app, update_course = _open_course_form(
        monkeypatch, "instructor-left", instructor_name="Former Instructor"
    )

    assert (
        app.selectbox(key="admin_course_instructor_course-1").value
        == "Former Instructor (current)"
    )
    _save_course(app)

    assert "instructor_id" not in update_course.call_args.args[2]


def _render_checkin_explorer():
    from app.views import checkins

    checkins.render()


def test_checkin_explorer_searches_by_student_and_labels_the_check_in_id(monkeypatch):
    list_checkins = Mock(
        return_value=(
            True,
            {
                "items": [
                    {
                        "id": "b18e9037-0000",
                        "student_name": "Demo Student 1",
                        "student_email": "student1@demo.ntu",
                        "status": "approved",
                        "risk_score": 0.15,
                    }
                ],
                "total": 1,
            },
        )
    )
    monkeypatch.setattr(api_client, "list_checkins", list_checkins)
    monkeypatch.setattr(api_client, "get_checkin", Mock(return_value=(False, "unused")))
    monkeypatch.setattr(
        api_client, "list_courses", Mock(return_value=(True, {"items": [COURSE], "total": 1}))
    )
    monkeypatch.setattr(
        api_client, "list_sessions", Mock(return_value=(True, {"items": [SESSION], "total": 1}))
    )

    app = AppTest.from_function(_render_checkin_explorer)
    app.session_state["access_token"] = "access-token"
    app.session_state["user"] = {"id": "instructor-id", "role": "instructor"}
    app.session_state["ci_student_search"] = "  student1 "
    app.run()

    assert not app.exception
    assert list_checkins.call_args.kwargs["search"] == "student1"
    assert "student_id" not in list_checkins.call_args.kwargs
    assert "Check-in ID" in app.dataframe[0].value.columns
