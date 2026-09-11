"""
Observability View - System health diagnostics, dependency status, and Prometheus PromQL telemetry.
"""

from typing import Any, Dict
import streamlit as st

from app.api_client import api_client
from app.config import GRAFANA_URL, PROMETHEUS_URL


def _extract_prom_value(data: Any) -> float:
    """Helper to parse a single scalar or vector value from Prometheus response."""
    try:
        if isinstance(data, dict) and data.get("status") == "success":
            results = data.get("data", {}).get("result", [])
            if results:
                # [timestamp, "value"]
                val_str = results[0].get("value", [None, 0.0])[1]
                return float(val_str)
    except Exception:
        pass
    return 0.0


def render() -> None:
    """Render Observability & System Metrics view."""
    st.title("📈 System Observability & Telemetry")
    st.caption("Live health diagnostics, service dependency checks, and Prometheus performance metrics.")

    # Top action bar with Grafana link
    col_t1, col_t2 = st.columns([3, 1])
    with col_t2:
        st.link_button(
            "📊 Open Grafana Dashboard",
            url=GRAFANA_URL,
            type="primary",
            use_container_width=True,
        )

    # -------------------------------------------------------------------------
    # 1. Service Health & Dependencies Probe
    # -------------------------------------------------------------------------
    st.subheader("🏥 Service Health & Readiness")

    with st.spinner("Probing microservices..."):
        ok_health, health_data = api_client.get_backend_health()
        ok_deps, deps_data = api_client.get_dependency_health()
        ok_face, face_data = api_client.get_face_service_health()

    h1, h2, h3, h4 = st.columns(4)

    with h1:
        backend_healthy = ok_health and isinstance(health_data, dict) and health_data.get("status") == "healthy"
        st.metric(
            label="Backend API (:8000)",
            value="Healthy" if backend_healthy else "Unreachable",
            delta="Online" if backend_healthy else "Offline",
            delta_color="normal" if backend_healthy else "inverse",
        )

    with h2:
        db_ok = ok_deps and isinstance(deps_data, dict) and deps_data.get("database") is True
        st.metric(
            label="PostgreSQL Database",
            value="Connected" if db_ok else "Unavailable",
            delta="Ready" if db_ok else "Error",
            delta_color="normal" if db_ok else "inverse",
        )

    with h3:
        redis_ok = ok_deps and isinstance(deps_data, dict) and deps_data.get("redis") is True
        st.metric(
            label="Redis Cache",
            value="Connected" if redis_ok else "Unavailable",
            delta="Ready" if redis_ok else "Degraded",
            delta_color="normal" if redis_ok else "inverse",
        )

    with h4:
        face_ok = (ok_face and isinstance(face_data, dict) and face_data.get("status") == "healthy") or (
            ok_deps and isinstance(deps_data, dict) and deps_data.get("face_service") is True
        )
        st.metric(
            label="Face Service (:8001)",
            value="Active" if face_ok else "Unavailable",
            delta="Model Loaded" if face_ok else "Offline",
            delta_color="normal" if face_ok else "inverse",
        )

    st.markdown("---")

    # -------------------------------------------------------------------------
    # 2. Prometheus Metrics & Performance
    # -------------------------------------------------------------------------
    st.subheader("⚡ Prometheus Performance Telemetry")
    st.caption(f"Scraped from Prometheus server at `{PROMETHEUS_URL}`.")

    # Queries
    p95_query = "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) * 1000"
    rps_query = "sum(rate(http_requests_total[5m]))"
    err_query = "sum(rate(http_requests_total{status=~'5..'}[5m])) / sum(rate(http_requests_total[5m])) * 100"
    checkin_query = "sum(rate(checkin_attempts_total[5m]))"

    with st.spinner("Executing PromQL queries..."):
        ok_p95, p95_res = api_client.query_prometheus(p95_query)
        ok_rps, rps_res = api_client.query_prometheus(rps_query)
        ok_err, err_res = api_client.query_prometheus(err_query)
        ok_ci, ci_res = api_client.query_prometheus(checkin_query)

    p95_latency = _extract_prom_value(p95_res)
    req_throughput = _extract_prom_value(rps_res)
    error_rate = _extract_prom_value(err_res)
    checkin_rate = _extract_prom_value(ci_res)

    m1, m2, m3, m4 = st.columns(4)

    with m1:
        st.metric(
            label="p95 Latency",
            value=f"{p95_latency:.1f} ms" if p95_latency > 0 else "< 10 ms",
            delta="Normal" if p95_latency < 200 else "Elevated",
            delta_color="normal" if p95_latency < 200 else "inverse",
        )

    with m2:
        st.metric(
            label="HTTP Throughput",
            value=f"{req_throughput:.2f} req/s",
            delta="5m moving rate",
        )

    with m3:
        st.metric(
            label="5xx Error Rate",
            value=f"{error_rate:.2f}%",
            delta="Target: 0%",
            delta_color="normal" if error_rate == 0 else "inverse",
        )

    with m4:
        st.metric(
            label="Check-in Rate",
            value=f"{checkin_rate:.2f} /s",
            delta="5m moving rate",
        )

    st.markdown("#### PromQL Query Console")
    custom_query = st.text_input(
        "Run PromQL Query:",
        value="http_requests_total",
        help="Execute any PromQL expression against Prometheus directly.",
    )
    if st.button("Execute Query"):
        with st.spinner("Querying Prometheus..."):
            ok_q, res_q = api_client.query_prometheus(custom_query)
        if ok_q:
            st.json(res_q)
        else:
            st.error(f"Query error: {res_q}")

