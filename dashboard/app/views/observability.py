"""
Observability View - System health diagnostics, dependency status, and Prometheus telemetry.
"""

from datetime import datetime, timedelta, timezone
import math
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from app.api_client import api_client
from app.auth import get_token
from app.config import GRAFANA_URL, PROMETHEUS_URL


P95_LATENCY_QUERY = (
    "histogram_quantile(0.95, sum by (le) "
    "(rate(http_request_duration_seconds_bucket[5m]))) * 1000"
)
REQUEST_RATE_QUERY = "sum(rate(http_requests_total[5m]))"
ERROR_RATE_QUERY = (
    'sum(rate(http_requests_total{status=~"5.."}[5m])) '
    "/ sum(rate(http_requests_total[5m])) * 100"
)
CHECKIN_RATE_QUERY = "sum(rate(checkin_decisions_total[5m]))"


def _extract_prom_value(data: Any) -> Optional[float]:
    """Return a valid instant-query value, or None when Prometheus has no data."""
    if not isinstance(data, dict) or data.get("status") != "success":
        return None
    result_data = data.get("data")
    results = result_data.get("result") if isinstance(result_data, dict) else None
    if not isinstance(results, list) or not results:
        return None
    value = results[0].get("value") if isinstance(results[0], dict) else None
    if not isinstance(value, list) or len(value) < 2:
        return None
    try:
        parsed = float(value[1])
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _extract_prom_series(data: Any) -> List[Dict[str, Any]]:
    """Convert Prometheus range-query points into chart-ready timestamp/value rows."""
    if not isinstance(data, dict) or data.get("status") != "success":
        return []
    result_data = data.get("data")
    results = result_data.get("result") if isinstance(result_data, dict) else None
    if not isinstance(results, list):
        return []

    points: List[Dict[str, Any]] = []
    for series in results:
        if not isinstance(series, dict) or not isinstance(series.get("values"), list):
            continue
        for point in series["values"]:
            if not isinstance(point, list) or len(point) < 2:
                continue
            try:
                timestamp = datetime.fromtimestamp(float(point[0]), timezone.utc)
                value = float(point[1])
            except (TypeError, ValueError, OverflowError, OSError):
                continue
            if math.isfinite(value):
                points.append({"Time (UTC)": timestamp, "Value": value})
    return points


def _service_state(ok: bool, healthy: bool) -> str:
    if not ok:
        return "Unavailable"
    return "Healthy" if healthy else "Degraded"


def render() -> None:
    """Render Observability & System Metrics view."""
    st.title("📈 System Observability & Telemetry")
    st.caption(
        "Live health diagnostics, service dependency checks, and Prometheus performance metrics."
    )

    col_range, col_refresh, col_grafana = st.columns([2, 1, 2])
    with col_range:
        range_label = st.selectbox(
            "Metric time range",
            options=["Last hour", "Last 6 hours", "Last 24 hours", "Last 7 days"],
            key="observability_time_range",
        )
    range_hours = {
        "Last hour": 1,
        "Last 6 hours": 6,
        "Last 24 hours": 24,
        "Last 7 days": 168,
    }[range_label]
    step_seconds = max(60, min(3600, range_hours * 3600 // 120))
    with col_refresh:
        st.write("")
        st.button("🔄 Refresh", key="refresh_observability")
    with col_grafana:
        st.link_button(
            "📊 Open Grafana Dashboard",
            url=GRAFANA_URL,
            type="primary",
            use_container_width=True,
        )

    st_autorefresh(interval=30_000, key="observability_auto_refresh")

    st.subheader("🏥 Service Health & Readiness")
    with st.spinner("Probing microservices..."):
        ok_health, health_data = api_client.get_backend_health()
        ok_deps, deps_data = api_client.get_dependency_health()
        ok_face, face_data = api_client.get_face_service_health()

    backend_state = _service_state(
        ok_health,
        isinstance(health_data, dict) and health_data.get("status") == "healthy",
    )
    database_state = (
        "Unavailable"
        if not ok_deps
        else "Healthy"
        if isinstance(deps_data, dict) and deps_data.get("database") is True
        else "Degraded"
    )
    redis_state = (
        "Unavailable"
        if not ok_deps
        else "Healthy"
        if isinstance(deps_data, dict) and deps_data.get("redis") is True
        else "Degraded"
    )
    face_healthy = (
        isinstance(face_data, dict) and face_data.get("status") == "healthy"
    ) or (isinstance(deps_data, dict) and deps_data.get("face_service") is True)
    face_state = _service_state(ok_face or ok_deps, face_healthy)

    health_columns = st.columns(4)
    for column, label, state in zip(
        health_columns,
        (
            "Backend API (:8000)",
            "PostgreSQL Database",
            "Redis Cache",
            "Face Service (:8001)",
        ),
        (backend_state, database_state, redis_state, face_state),
    ):
        with column:
            st.metric(label=label, value=state)

    if any(
        state != "Healthy"
        for state in (backend_state, database_state, redis_state, face_state)
    ):
        st.warning("One or more services are degraded or unavailable.")

    st.caption(
        f"Last checked: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}."
    )

    token = get_token()
    if token:
        ok_attendance, attendance = api_client.get_overview_stats(token, days=1)
        ok_queue, queue_data = api_client.get_flagged_checkins(token, limit=1)
        if not ok_attendance:
            st.error(f"Unable to load today's high-risk alert count: {attendance}")
        elif isinstance(attendance, dict):
            high_risk_count = attendance.get("high_risk_checkins_today")
            if isinstance(high_risk_count, int) and high_risk_count > 0:
                st.warning(
                    f"{high_risk_count} check-in(s) today (backend UTC day) "
                    "have a high risk score."
                )
        else:
            st.error("The backend returned an invalid high-risk summary.")
        if not ok_queue:
            st.error(f"Unable to load pending review count: {queue_data}")
        elif isinstance(queue_data, dict):
            pending_count = queue_data.get(
                "total", len(queue_data.get("items", []))
            )
            if isinstance(pending_count, int) and pending_count > 0:
                st.warning(
                    f"{pending_count} flagged or appealed check-in(s) are awaiting review."
                )
                if st.button("Open pending review queue", key="observability_review_queue"):
                    st.session_state["dashboard_page"] = "🚨 Review Queue"
                    st.rerun()
        else:
            st.error("The backend returned an invalid review-queue summary.")

    st.markdown("---")

    st.subheader("⚡ Prometheus Performance Telemetry")
    st.caption(f"Metrics source: `{PROMETHEUS_URL}` · range: {range_label.lower()}.")
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=range_hours)
    range_params = (
        start_time.isoformat().replace("+00:00", "Z"),
        end_time.isoformat().replace("+00:00", "Z"),
        f"{step_seconds}s",
    )

    with st.spinner("Querying Prometheus..."):
        instant_results = {
            "p95": api_client.query_prometheus(P95_LATENCY_QUERY),
            "requests": api_client.query_prometheus(REQUEST_RATE_QUERY),
            "errors": api_client.query_prometheus(ERROR_RATE_QUERY),
            "checkins": api_client.query_prometheus(CHECKIN_RATE_QUERY),
        }
        range_results = {
            "p95": api_client.query_prometheus_range(
                P95_LATENCY_QUERY, *range_params
            ),
            "requests": api_client.query_prometheus_range(
                REQUEST_RATE_QUERY, *range_params
            ),
            "errors": api_client.query_prometheus_range(
                ERROR_RATE_QUERY, *range_params
            ),
        }
    st.caption(
        f"Prometheus queried at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}."
    )

    p95_latency = (
        _extract_prom_value(instant_results["p95"][1])
        if instant_results["p95"][0]
        else None
    )
    request_rate = (
        _extract_prom_value(instant_results["requests"][1])
        if instant_results["requests"][0]
        else None
    )
    error_rate = (
        _extract_prom_value(instant_results["errors"][1])
        if instant_results["errors"][0]
        else None
    )
    checkin_rate = (
        _extract_prom_value(instant_results["checkins"][1])
        if instant_results["checkins"][0]
        else None
    )

    metrics = st.columns(4)
    with metrics[0]:
        st.metric(
            "p95 Latency",
            f"{p95_latency:.1f} ms" if p95_latency is not None else "Unavailable",
            delta=(
                "Normal" if p95_latency < 200 else "Elevated"
            )
            if p95_latency is not None
            else "No data",
            delta_color=(
                "normal" if p95_latency < 200 else "inverse"
            )
            if p95_latency is not None
            else "off",
        )
    with metrics[1]:
        st.metric(
            "HTTP Throughput",
            f"{request_rate:.2f} req/s" if request_rate is not None else "Unavailable",
            delta="5-minute moving rate" if request_rate is not None else "No data",
        )
    with metrics[2]:
        st.metric(
            "5xx Error Rate",
            f"{error_rate:.2f}%" if error_rate is not None else "Unavailable",
            delta="Target: 0%" if error_rate is not None else "No data",
            delta_color=(
                "normal" if error_rate == 0 else "inverse"
            )
            if error_rate is not None
            else "off",
        )
    with metrics[3]:
        st.metric(
            "Check-in Decision Rate",
            f"{checkin_rate:.2f} /s"
            if checkin_rate is not None
            else "Unavailable",
            delta="5-minute moving rate" if checkin_rate is not None else "No data",
        )

    if error_rate is not None and error_rate > 0:
        st.warning(f"Current 5xx error rate is {error_rate:.2f}%.")
    failed_instants = [
        metric
        for metric, result in instant_results.items()
        if not result[0]
        or not isinstance(result[1], dict)
        or result[1].get("status") != "success"
    ]
    if failed_instants:
        st.error(
            "Prometheus instant query failed for: "
            + ", ".join(failed_instants)
            + "."
        )

    st.subheader("Performance Trends")
    trend_columns = st.columns(2)
    for column, metric_key, metric_name, unit in (
        (trend_columns[0], "p95", "p95 HTTP latency", "Latency (ms)"),
        (trend_columns[1], "requests", "HTTP request rate", "Requests / second"),
        (trend_columns[0], "errors", "5xx error rate", "Errors (%)"),
    ):
        with column:
            ok_range, range_data = range_results[metric_key]
            if (
                not ok_range
                or not isinstance(range_data, dict)
                or range_data.get("status") != "success"
            ):
                st.error(f"Unable to load {metric_name} trend: {range_data}")
                continue
            series_points = _extract_prom_series(range_data)
            if not series_points:
                st.info(f"No {metric_name} trend data is available.")
                continue
            trend_df = pd.DataFrame(series_points)
            figure = px.line(
                trend_df,
                x="Time (UTC)",
                y="Value",
                labels={"Value": unit},
                title=metric_name,
            )
            figure.update_yaxes(rangemode="tozero")
            st.plotly_chart(figure, use_container_width=True)

    st.markdown("#### PromQL Query Console")
    custom_query = st.text_input(
        "Run PromQL Query:",
        value="http_requests_total",
        help="Execute a PromQL expression against Prometheus.",
    )
    if st.button("Execute Query"):
        with st.spinner("Querying Prometheus..."):
            ok_query, query_result = api_client.query_prometheus(custom_query)
        if ok_query:
            st.json(query_result)
        else:
            st.error(f"Query error: {query_result}")
