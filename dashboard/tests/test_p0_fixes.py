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
from app.views import _downloads
from app.views import observability
from app.views import overview
from app.views.review_queue import _factor_score
from app.views.sessions import (
    _build_qr_image,
    _format_singapore_time,
    _scheduled_time_utc,
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


def test_csv_export_is_requested_once_and_cached(monkeypatch):
    state = {}
    button_results = iter([True, False])
    export = Mock(return_value=(True, b"csv-data"))
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
    assert download_button.call_args.kwargs["data"] == b"csv-data"


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
        (client.export_session_json, ("session-1",), "/export/session/session-1?format=json"),
        (client.export_course_json, ("course-1",), "/export/attendance/course-1?format=json"),
        (client.export_audit_json, (), "/audit/export?format=json"),
    )
    for method, args, expected_path in calls:
        assert method("access-token", *args) == (True, {"records": []})
        request = client.session.get.call_args
        assert request.args[0] == f"https://api.example.test/api/v1{expected_path}"
        assert request.kwargs["headers"] == client._headers("access-token")

    assert client.session.get.call_count == 3


def test_ta_session_controls_follow_backend_ownership_rules():
    ta = {"id": "ta-id", "role": "ta"}
    own_session = {"instructor_id": "ta-id"}
    other_session = {"instructor_id": "instructor-id"}
    course = {"instructor_id": "instructor-id"}

    assert not can_create_sessions(ta)
    assert can_manage_session(ta, own_session, course)
    assert not can_manage_session(ta, other_session, course)
    assert not can_view_audit(ta)
    assert can_create_sessions({"id": "instructor-id", "role": "instructor"})
    assert not can_view_audit({"id": "instructor-id", "role": "instructor"})
    assert can_view_audit({"id": "admin-id", "role": "admin"})


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
