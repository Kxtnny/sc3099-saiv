from unittest.mock import Mock

import streamlit as st

from app.api_client import APIClient
from app.auth import _refresh_expired_access_token
from app.config import STAFF_ROLES
from app.rbac import (
    DASHBOARD_PAGE_PERMISSIONS,
    Permission,
    ROLE_PERMISSIONS,
    allowed_dashboard_pages,
    has_permission,
    require_permission,
    resolve_dashboard_page,
    role_for_user,
)
from app.views import (
    audit,
    checkins,
    courses,
    observability,
    overview,
    review_queue,
    sessions,
    session_checkins,
)


def test_roles_have_cumulative_permissions():
    student_permissions = {
        Permission.CHECK_IN,
        Permission.VIEW_OWN_RECORDS,
        Permission.MANAGE_OWN_DEVICES,
        Permission.APPEAL_OWN_CHECKIN,
    }
    ta_permissions = student_permissions | {
        Permission.VIEW_SESSION_CHECKINS,
        Permission.REVIEW_FLAGGED_CHECKINS,
    }
    instructor_permissions = ta_permissions | {
        Permission.MANAGE_SESSIONS,
        Permission.VIEW_COURSE_ANALYTICS,
        Permission.MANAGE_ENROLLMENTS,
    }

    assert ROLE_PERMISSIONS["student"] == student_permissions
    assert ROLE_PERMISSIONS["ta"] == ta_permissions
    assert ROLE_PERMISSIONS["instructor"] == instructor_permissions
    assert ROLE_PERMISSIONS["admin"] == set(Permission)
    assert set(STAFF_ROLES) == set(ROLE_PERMISSIONS)


def test_navigation_pages_match_the_cumulative_role_matrix():
    student_pages = {"👤 My Attendance & Devices"}
    ta_pages = student_pages | {"📋 Session Check-ins", "🚨 Review Queue"}
    instructor_pages = ta_pages | {
        "📊 Overview",
        "📅 Sessions",
        "🎓 Courses & Rosters",
    }

    assert allowed_dashboard_pages({"role": "student"}) == student_pages
    assert allowed_dashboard_pages({"role": "ta"}) == ta_pages
    assert allowed_dashboard_pages({"role": "instructor"}) == instructor_pages
    assert allowed_dashboard_pages({"role": "admin"}) == set(
        DASHBOARD_PAGE_PERMISSIONS
    )
    assert allowed_dashboard_pages({"role": "invalid"}) == set()
    assert "🛠️ Administration" not in allowed_dashboard_pages({"role": "instructor"})
    assert "🛠️ Administration" in allowed_dashboard_pages({"role": "admin"})


def test_missing_and_invalid_roles_fail_closed():
    for user in (
        None,
        {},
        {"role": None},
        {"role": 42},
        {"role": "unknown"},
        {"role": object()},
    ):
        assert role_for_user(user) is None
        assert not has_permission(user, Permission.VIEW_AUDIT)
        assert not has_permission(user, Permission.VIEW_OWN_RECORDS)

    assert role_for_user({"role": "  TA "}) == "ta"


def test_direct_page_permission_check_denies_unauthorized_role(monkeypatch):
    error = Mock()
    monkeypatch.setattr(st, "error", error)

    assert not require_permission(
        {"role": "student"}, Permission.MANAGE_SESSIONS
    )
    error.assert_called_once()


def test_direct_session_page_invocation_denies_student_before_render(monkeypatch):
    error = Mock()
    title = Mock()
    monkeypatch.setattr(sessions, "get_current_user", lambda: {"role": "student"})
    monkeypatch.setattr(sessions.st, "error", error)
    monkeypatch.setattr(sessions.st, "title", title)

    sessions.render()

    error.assert_called_once()
    title.assert_not_called()


def test_direct_page_invocation_denies_each_unauthorized_role(monkeypatch):
    protected_views = (
        (overview, Permission.VIEW_COURSE_ANALYTICS),
        (sessions, Permission.MANAGE_SESSIONS),
        (session_checkins, Permission.VIEW_SESSION_CHECKINS),
        (review_queue, Permission.REVIEW_FLAGGED_CHECKINS),
        (courses, Permission.VIEW_COURSE_ANALYTICS),
        (checkins, Permission.VIEW_CHECKIN_EXPLORER),
        (audit, Permission.VIEW_AUDIT),
        (observability, Permission.VIEW_OBSERVABILITY),
    )
    error = Mock()
    monkeypatch.setattr(st, "error", error)
    for role in ("student", "ta", "instructor", "admin"):
        user = {"id": f"{role}-id", "role": role}
        for view, permission in protected_views:
            if has_permission(user, permission):
                continue
            monkeypatch.setattr(view, "get_current_user", lambda user=user: user)
            if hasattr(view, "get_token"):
                monkeypatch.setattr(view, "get_token", lambda: "access-token")
            error.reset_mock()

            view.render()

            error.assert_called_once()


def test_page_selection_survives_refresh_and_rejects_stale_or_forged_values():
    for role, allowed_pages in (
        ("student", allowed_dashboard_pages({"role": "student"})),
        ("ta", allowed_dashboard_pages({"role": "ta"})),
        ("instructor", allowed_dashboard_pages({"role": "instructor"})),
        ("admin", allowed_dashboard_pages({"role": "admin"})),
    ):
        default_page = next(iter(DASHBOARD_PAGE_PERMISSIONS))
        if default_page not in allowed_pages:
            default_page = next(
                page for page in DASHBOARD_PAGE_PERMISSIONS
                if page in allowed_pages
            )
        requested_page = next(
            page for page in DASHBOARD_PAGE_PERMISSIONS
            if page in allowed_pages and page != default_page
        ) if len(allowed_pages) > 1 else default_page
        assert (
            resolve_dashboard_page(
                requested_page, allowed_pages, default_page
            )
            == requested_page
        )
        forbidden_page = next(
            (
                page
                for page in DASHBOARD_PAGE_PERMISSIONS
                if page not in allowed_pages
            ),
            None,
        )
        if forbidden_page is not None:
            assert (
                resolve_dashboard_page(
                    forbidden_page, allowed_pages, default_page
                )
                == default_page
            )


def test_token_refresh_preserves_authenticated_role(monkeypatch):
    class SessionState(dict):
        __getattr__ = dict.__getitem__
        __setattr__ = dict.__setitem__

    user = {"id": "ta-id", "role": "ta"}
    state = SessionState(
        access_token="expired-token",
        refresh_token="old-refresh",
        user=user,
    )
    monkeypatch.setattr(st, "session_state", state)
    monkeypatch.setattr(
        "app.auth.api_client.refresh_token",
        Mock(
            return_value=(
                True,
                {"access_token": "new-token", "refresh_token": "new-refresh"},
            )
        ),
    )

    assert _refresh_expired_access_token("expired-token") == "new-token"
    assert state["user"] == user
    assert state["user"]["role"] == "ta"


def test_personal_api_wrappers_use_authenticated_user_endpoints():
    client = APIClient("https://api.example.test/api/v1")
    response = Mock(ok=True, headers={"content-type": "application/json"})
    response.json.return_value = []
    client.session.get = Mock(return_value=response)

    assert client.get_my_checkins("access-token") == (True, [])
    request = client.session.get.call_args
    assert request.args[0] == (
        "https://api.example.test/api/v1/checkins/my-checkins"
    )
    assert request.kwargs["headers"] == client._headers("access-token")

    assert client.get_my_devices("access-token") == (True, [])
    request = client.session.get.call_args
    assert request.args[0] == (
        "https://api.example.test/api/v1/devices/my-devices"
    )

    client.session.patch = Mock(return_value=response)
    assert client.update_device(
        "access-token", "device-1", device_name="Laptop"
    ) == (True, [])
    request = client.session.patch.call_args
    assert request.args[0] == (
        "https://api.example.test/api/v1/devices/device-1"
    )
    assert request.kwargs["headers"] == client._headers("access-token")
    assert request.kwargs["json"] == {"device_name": "Laptop"}

    client.session.delete = Mock(return_value=response)
    assert client.revoke_device("access-token", "device-1") == (True, [])
    request = client.session.delete.call_args
    assert request.args[0] == (
        "https://api.example.test/api/v1/devices/device-1"
    )


def test_student_appeal_api_uses_authenticated_owner_endpoint():
    client = APIClient("https://api.example.test/api/v1")
    response = Mock(ok=True, headers={"content-type": "application/json"})
    response.json.return_value = {"status": "appealed"}
    client.session.post = Mock(return_value=response)

    assert client.appeal_checkin(
        "access-token", "checkin-1", "GPS was inaccurate"
    ) == (True, {"status": "appealed"})
    request = client.session.post.call_args
    assert request.args[0] == (
        "https://api.example.test/api/v1/checkins/checkin-1/appeal"
    )
    assert request.kwargs["json"] == {"appeal_reason": "GPS was inaccurate"}
    assert request.kwargs["headers"] == client._headers("access-token")


def test_instructor_session_scope_uses_authenticated_my_sessions_endpoint():
    client = APIClient("https://api.example.test/api/v1")
    response = Mock(ok=True, headers={"content-type": "application/json"})
    response.json.return_value = []
    client.session.get = Mock(return_value=response)

    assert client.get_my_sessions("access-token", limit=100) == (True, [])
    request = client.session.get.call_args
    assert request.args[0] == (
        "https://api.example.test/api/v1/sessions/my-sessions"
    )
    assert request.kwargs["params"] == {"limit": 100}
    assert request.kwargs["headers"] == client._headers("access-token")


def test_student_detail_uses_course_and_student_scoped_checkin_query():
    client = APIClient("https://api.example.test/api/v1")
    response = Mock(ok=True, headers={"content-type": "application/json"})
    response.json.return_value = {"items": [], "total": 0}
    client.session.get = Mock(return_value=response)

    assert client.list_checkins(
        token="access-token",
        course_id="course-1",
        student_id="student-1",
        limit=100,
        offset=0,
    ) == (True, {"items": [], "total": 0})
    request = client.session.get.call_args
    assert request.args[0] == "https://api.example.test/api/v1/checkins/"
    assert request.kwargs["params"] == {
        "limit": 100,
        "offset": 0,
        "course_id": "course-1",
        "student_id": "student-1",
    }
