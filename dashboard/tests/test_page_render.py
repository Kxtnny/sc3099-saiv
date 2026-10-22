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
