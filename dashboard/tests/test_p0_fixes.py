from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timezone
from unittest.mock import Mock

import requests
import pytest
import streamlit as st

from app.api_client import APIClient, api_client
from app.auth import (
    _refresh_expired_access_token,
    can_create_sessions,
    can_manage_session,
    can_view_audit,
)
from app import auth
from app.views import _downloads
from app.views.administration import _load_pages
from app.views import audit, checkins
from app.views import observability
from app.views import overview
from app.views.review_queue import _factor_score
from app.views.sessions import (
    _build_qr_image,
    _format_singapore_time,
    _parse_singapore_datetime,
    _scheduled_time_utc,
    _utc_date_bound as _session_utc_date_bound,
    _utc_iso,
)


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


def test_scheduled_time_is_interpreted_as_singapore_time():
    converted = _scheduled_time_utc(date(2026, 10, 16), time(9, 30))

    assert converted == datetime(2026, 10, 16, 1, 30, tzinfo=timezone.utc)


def test_session_timestamp_helpers_round_trip_singapore_and_utc():
    parsed = _parse_singapore_datetime("2026-10-16T01:30:00Z")

    assert parsed.isoformat() == "2026-10-16T09:30:00+08:00"
    assert _utc_iso(parsed) == "2026-10-16T01:30:00Z"


def test_csv_export_is_requested_once_and_cached(monkeypatch):
    state = {}
    button_results = iter([True, False])
    csv_bytes = 'id,name\r\n1,"Anaïs, PhD"\r\n'.encode("utf-8")
    export = Mock(return_value=(True, csv_bytes))
    download_button = Mock()

    monkeypatch.setattr(st, "session_state", state)
    monkeypatch.setattr(st, "button", lambda *args, **kwargs: next(button_results))
    monkeypatch.setattr(st, "spinner", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(st, "download_button", download_button)

    for _ in range(2):
        _downloads.render_csv_download(
            token="test-token",
            cache_key="course-1",
            request_label="Export",
            download_label="Download",
            file_name="course.csv",
            export=export,
        )

    export.assert_called_once_with()
    assert download_button.call_count == 2
    assert download_button.call_args.kwargs["data"] == csv_bytes
    assert b"Ana\xc3\xafs" in download_button.call_args.kwargs["data"]


def test_csv_export_failure_is_reported_without_caching(monkeypatch):
    state = {}
    export = Mock(return_value=(False, "backend unavailable"))
    error = Mock()

    monkeypatch.setattr(st, "session_state", state)
    monkeypatch.setattr(st, "button", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(st, "spinner", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(st, "error", error)
    monkeypatch.setattr(st, "download_button", Mock())

    _downloads.render_csv_download(
        token="test-token",
        cache_key="audit",
        request_label="Export",
        download_label="Download",
        file_name="audit.csv",
        export=export,
    )

    export.assert_called_once_with()
    error.assert_called_once_with("Failed to export CSV: backend unavailable")
    assert not state


def test_json_export_is_requested_once_and_cached(monkeypatch):
    state = {}
    button_results = iter([True, False])
    export = Mock(return_value=(True, {"records": [{"id": "one"}]}))
    download_button = Mock()

    monkeypatch.setattr(st, "session_state", state)
    monkeypatch.setattr(st, "button", lambda *args, **kwargs: next(button_results))
    monkeypatch.setattr(st, "spinner", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(st, "download_button", download_button)

    for _ in range(2):
        _downloads.render_json_download(
            token="test-token",
            cache_key="session-1",
            request_label="Export",
            download_label="Download",
            file_name="session.json",
            export=export,
        )

    export.assert_called_once_with()
    assert download_button.call_count == 2
    assert download_button.call_args.kwargs["mime"] == "application/json"
    assert download_button.call_args.kwargs["data"] == b'{\n  "records": [\n    {\n      "id": "one"\n    }\n  ]\n}'


def test_json_exports_use_existing_authenticated_backend_routes():
    client = APIClient("https://api.example.test/api/v1")
    response = Mock(
        ok=True,
        status_code=200,
        headers={"content-type": "application/json"},
        json=Mock(return_value={"records": []}),
    )
    client.session.get = Mock(return_value=response)

    calls = (
        (
            client.export_session_json,
            ("session-1",),
            "/export/session/session-1?format=json",
            None,
        ),
        (
            client.export_course_json,
            ("course-1",),
            "/export/attendance/course-1",
            {"format": "json"},
        ),
        (client.export_audit_json, (), "/audit/export?format=json", None),
    )
    for method, args, expected_path, expected_params in calls:
        assert method("access-token", *args) == (True, {"records": []})
        request = client.session.get.call_args
        assert request.args[0] == f"https://api.example.test/api/v1{expected_path}"
        assert request.kwargs["headers"] == client._headers("access-token")
        if expected_params is not None:
            assert request.kwargs["params"] == expected_params

    assert client.session.get.call_count == 3


def test_course_export_passes_date_range_as_api_query_params():
    client = APIClient("https://api.example.test/api/v1")
    response = Mock(ok=True, content=b"csv")
    client.session.get = Mock(return_value=response)

    assert client.export_course_csv(
        "access-token",
        "course-1",
        start_date="2026-01-01T00:00:00Z",
        end_date="2026-01-31T23:59:59Z",
    ) == (True, b"csv")
    request = client.session.get.call_args
    assert request.args[0] == (
        "https://api.example.test/api/v1/export/attendance/course-1"
    )
    assert request.kwargs["params"] == {
        "format": "csv",
        "start_date": "2026-01-01T00:00:00Z",
        "end_date": "2026-01-31T23:59:59Z",
    }


def test_admin_api_client_uses_authorized_user_and_course_endpoints():
    client = APIClient("https://api.example.test/api/v1")
    response = Mock(
        ok=True,
        status_code=200,
        headers={"content-type": "application/json"},
        json=Mock(return_value={"id": "resource-1"}),
    )
    client.session.get = Mock(return_value=response)
    client.session.post = Mock(return_value=response)
    client.session.patch = Mock(return_value=response)
    client.session.delete = Mock(
        return_value=Mock(ok=True, status_code=204, headers={})
    )

    client.get_course_stats(
        "access-token",
        "course-1",
        start_date="2026-01-01T00:00:00Z",
        end_date="2026-01-31T23:59:59Z",
    )
    assert client.session.get.call_args.kwargs["params"] == {
        "start_date": "2026-01-01T00:00:00Z",
        "end_date": "2026-01-31T23:59:59Z",
    }

    client.create_users("access-token", [{"email": "ta@example.test"}])
    assert client.session.post.call_args.args[0].endswith("/admin/users/bulk")
    assert client.session.post.call_args.kwargs["json"] == {
        "users": [{"email": "ta@example.test"}]
    }
    client.create_course("access-token", {"code": "CS1000"})
    assert client.session.post.call_args.args[0].endswith("/courses/")
    client.update_course("access-token", "course-1", {"is_active": False})
    assert client.session.patch.call_args.args[0].endswith("/courses/course-1")
    client.update_user("access-token", "user-1", {"role": "ta"})
    assert client.session.patch.call_args.args[0].endswith("/users/user-1")
    assert client.delete_course("access-token", "course-1") == (True, {})
    assert client.session.delete.call_args.args[0].endswith("/courses/course-1")

    client.update_device(
        "access-token", "device-1", is_active=False, is_trusted=True
    )
    assert client.session.patch.call_args.args[0].endswith("/devices/device-1")
    assert client.session.patch.call_args.kwargs["json"] == {
        "is_active": False,
        "is_trusted": True,
    }
    client.list_devices("access-token", is_trusted=True)
    assert client.session.get.call_args.args[0].endswith("/devices/")
    assert client.session.get.call_args.kwargs["params"]["is_trusted"] is True


def test_admin_list_pagination_validates_progress_and_response_shape():
    responses = iter(
        [
            (True, {"items": [{"id": "one"}, {"id": "two"}], "total": 3}),
            (True, {"items": [{"id": "three"}], "total": 3}),
        ]
    )
    offsets = []

    def fetch(offset):
        offsets.append(offset)
        return next(responses)

    assert _load_pages(fetch) == (
        True,
        [{"id": "one"}, {"id": "two"}, {"id": "three"}],
        None,
    )
    assert offsets == [0, 2]

    ok, items, error = _load_pages(
        lambda _offset: (True, {"items": [], "total": 1})
    )
    assert not ok
    assert items == []
    assert error == "The API returned an invalid paginated response."


def test_ta_assignment_client_uses_authenticated_course_routes():
    client = APIClient("https://api.example.test/api/v1")
    response = Mock(
        ok=True,
        status_code=200,
        headers={"content-type": "application/json"},
        json=Mock(return_value={"items": [], "total": 0}),
    )
    client.session.get = Mock(return_value=response)
    client.session.post = Mock(return_value=response)
    client.session.delete = Mock(
        return_value=Mock(ok=True, status_code=204, headers={})
    )

    assert client.list_users("access-token", role="ta") == (
        True,
        {"items": [], "total": 0},
    )
    assert client.get_course_tas("access-token", "course-1") == (
        True,
        {"items": [], "total": 0},
    )
    assert client.assign_course_ta("access-token", "course-1", "ta-1") == (
        True,
        {"items": [], "total": 0},
    )
    assert client.unassign_course_ta("access-token", "course-1", "ta-1") == (
        True,
        {},
    )

    list_request = client.session.get.call_args_list[0]
    assert list_request.args[0] == "https://api.example.test/api/v1/users/"
    assert list_request.kwargs["params"]["role"] == "ta"
    assert list_request.kwargs["headers"] == client._headers("access-token")
    course_ta_request = client.session.get.call_args_list[1]
    assert course_ta_request.args[0].endswith("/courses/course-1/tas")
    assert client.session.post.call_args.kwargs["json"] == {"ta_id": "ta-1"}
    assert client.session.delete.call_args.args[0].endswith(
        "/courses/course-1/tas/ta-1"
    )


def test_ta_session_controls_follow_backend_ownership_rules():
    ta = {"id": "ta-id", "role": "ta"}
    own_session = {"instructor_id": "ta-id"}
    other_session = {"instructor_id": "instructor-id"}
    course = {"instructor_id": "instructor-id"}

    assert not can_create_sessions(ta)
    assert not can_manage_session(ta, own_session, course)
    assert not can_manage_session(ta, other_session, course)
    assert not can_view_audit(ta)
    assert can_create_sessions({"id": "instructor-id", "role": "instructor"})
    assert not can_view_audit({"id": "instructor-id", "role": "instructor"})
    assert can_view_audit({"id": "admin-id", "role": "admin"})


def test_session_action_permissions_cover_all_four_roles():
    instructor_session = {"instructor_id": "instructor-id"}
    instructor_course = {"instructor_id": "instructor-id"}
    other_session = {"instructor_id": "other-id"}

    assert not can_create_sessions({"id": "student-id", "role": "student"})
    assert not can_create_sessions({"id": "ta-id", "role": "ta"})
    assert can_create_sessions({"id": "instructor-id", "role": "instructor"})
    assert can_create_sessions({"id": "admin-id", "role": "admin"})

    assert not can_manage_session(
        {"id": "student-id", "role": "student"},
        instructor_session,
        instructor_course,
    )
    assert not can_manage_session(
        {"id": "ta-id", "role": "ta"},
        instructor_session,
        instructor_course,
    )
    assert can_manage_session(
        {"id": "instructor-id", "role": "instructor"},
        instructor_session,
        instructor_course,
    )
    assert not can_manage_session(
        {"id": "instructor-id", "role": "instructor"},
        other_session,
        {"instructor_id": "other-id"},
    )
    assert can_manage_session(
        {"id": "admin-id", "role": "admin"},
        other_session,
        {"instructor_id": "other-id"},
    )


def test_sidebar_escapes_untrusted_profile_html(monkeypatch):
    profile = {
        "full_name": '<img src=x onerror="alert(1)">',
        "email": "user@example.test<script>alert(1)</script>",
        "role": "student",
    }
    markdown = Mock()
    monkeypatch.setattr(auth, "get_current_user", lambda: profile)
    monkeypatch.setattr(st, "sidebar", nullcontext())
    monkeypatch.setattr(st, "markdown", markdown)
    monkeypatch.setattr(st, "button", Mock(return_value=False))

    auth.render_sidebar_user_profile()

    rendered_profile = markdown.call_args_list[1].args[0]
    assert "&lt;img" in rendered_profile
    assert "&lt;script&gt;" in rendered_profile
    assert "<img src=" not in rendered_profile
    assert "<script>" not in rendered_profile


def test_overview_refresh_runs_every_thirty_seconds(monkeypatch):
    auto_refresh = Mock()
    monkeypatch.setattr(overview, "st_autorefresh", auto_refresh)

    overview._schedule_auto_refresh()

    auto_refresh.assert_called_once_with(
        interval=30_000,
        key="overview_auto_refresh",
    )


def test_session_qr_is_generated_as_an_image_locally():
    image = _build_qr_image("existing-check-in-secret")

    assert image.size[0] > 0
    assert image.size[1] > 0


@pytest.mark.parametrize(
    ("factor", "expected"),
    [
        ({"weight": 0.4, "confidence": 0.75}, 0.3),
        ({"weight": 0, "confidence": 1}, 0),
        ({"weight": 1, "confidence": 1}, 1),
    ],
)
def test_risk_factor_score_uses_weight_times_confidence(factor, expected):
    assert _factor_score(factor) == pytest.approx(expected)


@pytest.mark.parametrize(
    "factor",
    [
        {},
        {"weight": 0.2},
        {"confidence": 0.5},
        {"weight": "0.2", "confidence": 0.5},
        {"weight": True, "confidence": 0.5},
        {"weight": float("nan"), "confidence": 0.5},
        {"weight": 1.1, "confidence": 0.5},
        None,
    ],
)
def test_risk_factor_score_rejects_missing_or_malformed_inputs(factor):
    assert _factor_score(factor) is None


def _unauthorized_response(token="expired-token"):
    request = requests.Request(
        "GET",
        "https://api.example.test/api/v1/stats/overview",
        headers={"Authorization": f"Bearer {token}"},
    ).prepare()
    response = requests.Response()
    response.status_code = 401
    response.request = request
    response.close = Mock()
    return response


def test_unauthorized_request_refreshes_and_retries_once_without_hook():
    client = APIClient("https://api.example.test/api/v1")
    refreshed_response = requests.Response()
    refreshed_response.status_code = 200
    refresh_handler = Mock(return_value="fresh-token")
    send = Mock(return_value=refreshed_response)
    client.set_refresh_handler(refresh_handler)
    client.session.send = send

    result = client._retry_after_unauthorized(
        _unauthorized_response(),
        timeout=5,
    )

    assert result is refreshed_response
    refresh_handler.assert_called_once_with("expired-token")
    send.assert_called_once()
    retried_request = send.call_args.args[0]
    assert retried_request.headers["Authorization"] == "Bearer fresh-token"
    assert retried_request.hooks["response"] == []


def test_concurrent_unauthorized_requests_rotate_tokens_once():
    client = APIClient("https://api.example.test/api/v1")
    current_token = {"value": "expired-token", "refresh_count": 0}

    def refresh(token):
        if token == current_token["value"]:
            current_token["refresh_count"] += 1
            current_token["value"] = "fresh-token"
        return current_token["value"]

    client.set_refresh_handler(refresh)
    send = Mock(side_effect=lambda *_args, **_kwargs: requests.Response())
    client.session.send = send

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: client._retry_after_unauthorized(
                    _unauthorized_response(),
                    timeout=5,
                ),
                range(2),
            )
        )

    assert current_token["refresh_count"] == 1
    assert len(results) == 2
    assert send.call_count == 2


def test_refresh_failure_clears_auth_and_sets_expiry_message(monkeypatch):
    state = _SessionState({
        "access_token": "expired-token",
        "refresh_token": "invalid-refresh",
        "user": {"id": "user-id"},
    })
    monkeypatch.setattr(st, "session_state", state)
    monkeypatch.setattr(
        api_client,
        "refresh_token",
        Mock(return_value=(False, "raw detail")),
    )

    assert _refresh_expired_access_token("expired-token") is None
    assert state["access_token"] is None
    assert state["refresh_token"] is None
    assert state["user"] is None
    assert state["dashboard_flash_message"] == {
        "message": "Your session has expired. Please sign in again.",
        "level": "warning",
    }


def test_refresh_uses_already_rotated_access_token(monkeypatch):
    state = _SessionState({
        "access_token": "fresh-token",
        "refresh_token": "rotated-refresh",
        "user": {"id": "user-id"},
    })
    monkeypatch.setattr(st, "session_state", state)
    assert _refresh_expired_access_token("expired-token") == "fresh-token"


def test_flash_message_survives_rerun_and_is_consumed(monkeypatch):
    from app.views._messages import render_flash_message, set_flash_message

    state = _SessionState()
    success = Mock()
    monkeypatch.setattr(st, "session_state", state)
    monkeypatch.setattr(st, "success", success)

    set_flash_message("Session created.")
    render_flash_message()

    success.assert_called_once_with("Session created.")
    assert "dashboard_flash_message" not in state


def test_unauthorized_response_does_not_expose_backend_auth_details():
    response = _unauthorized_response()
    response._content = b'{"detail":"token signature is invalid"}'

    assert APIClient()._handle_response(response) == (
        False,
        "Your session has expired. Please sign in again.",
    )


def test_failed_login_shows_backend_reason_not_session_expiry():
    response = requests.Response()
    response.status_code = 401
    response.headers["content-type"] = "application/json"
    response._content = b'{"detail":"Incorrect email or password"}'
    response.request = requests.Request(
        "POST", "https://api.example.test/api/v1/auth/login"
    ).prepare()

    assert APIClient()._handle_response(response) == (
        False,
        {"detail": "Incorrect email or password"},
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-16T06:00:00Z", "2026-10-16 14:00 SGT"),
        ("2026-10-16T06:00:00+00:00", "2026-10-16 14:00 SGT"),
        ("2026-10-16T06:00:00", "2026-10-16 14:00 SGT"),
        ("", "N/A"),
        (None, "N/A"),
        ("not-a-date", "not-a-date"),
    ],
)
def test_session_times_are_displayed_in_singapore_time(value, expected):
    assert _format_singapore_time(value) == expected


def test_overview_response_helpers_keep_exact_counts_and_valid_scores():
    assert overview._total_from_response({"total": 4}) == 4
    assert overview._total_from_response({"total": True}) is None
    assert overview._total_from_response({"total": -1}) is None
    assert overview._risk_scores(
        [
            {"risk_score": 0.3},
            {"risk_score": 1},
            {"risk_score": None},
            {"risk_score": 1.2},
            {"risk_score": float("nan")},
            {},
        ]
    ) == [0.3, 1.0]


def test_singapore_today_filters_convert_to_utc_day_bounds():
    assert overview._today_date_filters(date(2026, 10, 16)) == (
        "2026-10-15T16:00:00Z",
        "2026-10-16T15:59:59.999999Z",
    )


def test_p95_query_aggregates_histogram_buckets_across_endpoints():
    assert observability.P95_LATENCY_QUERY == (
        "histogram_quantile(0.95, sum by (le) "
        "(rate(http_request_duration_seconds_bucket[5m]))) * 1000"
    )


def test_prometheus_missing_or_malformed_values_are_unavailable():
    assert observability._extract_prom_value({"status": "success", "data": {"result": []}}) is None
    assert observability._extract_prom_value(
        {"status": "success", "data": {"result": [{"value": [1, "NaN"]}]}}
    ) is None
    assert observability._extract_prom_value(
        {"status": "success", "data": {"result": [{"value": [1, "0"]}]}}
    ) == 0
    assert observability._extract_prom_series(
        {
            "status": "success",
            "data": {
                "result": [
                    {"values": [[1792141200, "12.5"], [1792141500, "bad"]]}
                ]
            },
        }
    ) == [
        {
            "Time (UTC)": datetime.fromtimestamp(1792141200, timezone.utc),
            "Value": 12.5,
        }
    ]


def test_dashboard_api_client_passes_session_and_audit_filter_parameters():
    client = APIClient("https://api.example.test/api/v1")
    response = Mock(
        ok=True,
        status_code=200,
        headers={"content-type": "application/json"},
        json=Mock(return_value={"items": [], "total": 0}),
    )
    client.session.get = Mock(return_value=response)

    assert client.list_sessions(
        "token",
        course_id="course-1",
        instructor_id="instructor-1",
        start_date="2026-10-01T00:00:00Z",
        end_date="2026-10-31T23:59:59Z",
        limit=25,
        offset=50,
    ) == (True, {"items": [], "total": 0})
    assert client.session.get.call_args.kwargs["params"] == {
        "limit": 25,
        "offset": 50,
        "course_id": "course-1",
        "instructor_id": "instructor-1",
        "start_date": "2026-10-01T00:00:00Z",
        "end_date": "2026-10-31T23:59:59Z",
    }

    assert client.list_audit_logs(
        "token",
        user_id="user-1",
        action="login_failed",
        resource_type="session",
        resource_id="resource-1",
        success=False,
        start_date="2026-10-01T00:00:00Z",
        end_date="2026-10-31T23:59:59Z",
        limit=25,
        offset=25,
    ) == (True, {"items": [], "total": 0})
    assert client.session.get.call_args.kwargs["params"] == {
        "limit": 25,
        "offset": 25,
        "user_id": "user-1",
        "action": "login_failed",
        "resource_type": "session",
        "resource_id": "resource-1",
        "success": False,
        "start_date": "2026-10-01T00:00:00Z",
        "end_date": "2026-10-31T23:59:59Z",
    }


def test_prometheus_range_query_sends_time_range_and_step():
    client = APIClient()
    response = Mock(
        ok=True,
        status_code=200,
        headers={"content-type": "application/json"},
        json=Mock(return_value={"status": "success", "data": {"result": []}}),
    )
    client.session.get = Mock(return_value=response)

    assert client.query_prometheus_range(
        "up", "2026-10-21T00:00:00Z", "2026-10-21T01:00:00Z", "60s"
    ) == (True, {"status": "success", "data": {"result": []}})
    assert client.session.get.call_args.args[0].endswith("/api/v1/query_range")
    assert client.session.get.call_args.kwargs["params"] == {
        "query": "up",
        "start": "2026-10-21T00:00:00Z",
        "end": "2026-10-21T01:00:00Z",
        "step": "60s",
    }


def test_filter_date_helpers_include_the_full_selected_day():
    expected = "2026-10-21T23:59:59.999999Z"
    assert checkins._utc_date_bound(date(2026, 10, 21), end=True) == expected
    assert audit._utc_date_bound(date(2026, 10, 21), end=True) == expected
    assert _session_utc_date_bound(date(2026, 10, 21), end=True) == (
        "2026-10-21T15:59:59.999999Z"
    )


def test_course_scoped_overview_trend_aggregates_singapore_dates():
    assert overview._daily_counts(
        [
            {"checked_in_at": "2026-10-20T16:30:00Z"},
            {"checked_in_at": "2026-10-20T18:30:00Z"},
            {"checked_in_at": "not-a-timestamp"},
            None,
        ]
    ) == [{"date": "2026-10-21", "count": 2}]
