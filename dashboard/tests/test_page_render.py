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


@pytest.mark.parametrize(
    "user",
    [
        {"id": "instructor-id", "role": "instructor"},
        {"id": "ta-id", "role": "ta"},
    ],
)
def test_sessions_page_renders_session_panels_without_errors(monkeypatch, user):
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
