"""
Overview Dashboard View - High-level metrics, trends, and verification analytics.
"""

from datetime import date, datetime, time, timedelta, timezone
import math
from numbers import Real
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from app.api_client import api_client
from app.auth import get_token


SINGAPORE_TIMEZONE = ZoneInfo("Asia/Singapore")
CHECKIN_STATUSES = ("approved", "flagged", "rejected")
RISK_SAMPLE_LIMIT = 100


def _schedule_auto_refresh() -> None:
    st_autorefresh(interval=30_000, key="overview_auto_refresh")


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _today_date_filters(today: date) -> Tuple[str, str]:
    start = datetime.combine(today, time.min, tzinfo=SINGAPORE_TIMEZONE)
    end = datetime.combine(
        today + timedelta(days=1), time.min, tzinfo=SINGAPORE_TIMEZONE
    ) - timedelta(microseconds=1)
    return _utc_iso(start), _utc_iso(end)


def _total_from_response(response: Any) -> Optional[int]:
    if not isinstance(response, dict):
        return None
    total = response.get("total")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        return None
    return total


def _risk_scores(items: Any) -> List[float]:
    if not isinstance(items, list):
        return []
    scores = []
    for item in items:
        if not isinstance(item, dict):
            continue
        score = item.get("risk_score")
        if (
            isinstance(score, bool)
            or not isinstance(score, Real)
            or not math.isfinite(score)
            or not 0 <= score <= 1
        ):
            continue
        scores.append(float(score))
    return scores


def render() -> None:
    """Render the Overview landing page."""
    st.title("📊 Attendance Overview")
    st.caption("Real-time telemetry and system-wide verification analytics.")

    token = get_token()
    if not token:
        st.warning("Please sign in to view analytics.")
        return

    _schedule_auto_refresh()
    st.caption("This read-only overview refreshes automatically every 30 seconds.")

    # Filter controls in a top bar
    col_filter1, col_filter2, col_btn = st.columns([2, 2, 1])
    with col_filter1:
        time_window = st.selectbox(
            "Time Horizon",
            options=[7, 14, 30, 90],
            format_func=lambda x: f"Last {x} days",
            index=0,
        )
    with col_filter2:
        # Load courses for optional filter
        ok_courses, courses_data = api_client.list_courses(token=token)
        course_options = {"All Courses": None}
        if ok_courses and isinstance(courses_data, dict) and "items" in courses_data:
            for c in courses_data["items"]:
                course_options[f"{c.get('code', '')} - {c.get('name', '')}"] = c.get("id")
        selected_course_label = st.selectbox("Course Scope", options=list(course_options.keys()))
        selected_course_id = course_options[selected_course_label]

    with col_btn:
        st.write("")
        st.write("")
        refresh_clicked = st.button("🔄 Refresh", use_container_width=True)

    with st.spinner("Fetching system statistics..."):
        ok, stats = api_client.get_overview_stats(
            token, days=time_window, course_id=selected_course_id
        )

    if not ok:
        st.error(f"Unable to load statistics: {stats}")
        return

    period_end = datetime.now(timezone.utc)
    period_start_iso = _utc_iso(period_end - timedelta(days=time_window))
    period_end_iso = _utc_iso(period_end)
    today_start, today_end = _today_date_filters(
        datetime.now(SINGAPORE_TIMEZONE).date()
    )
    with st.spinner("Loading exact check-in outcomes and today's sessions..."):
        outcome_results = {
            status: api_client.list_checkins(
                token=token,
                course_id=selected_course_id,
                status=status,
                start_date=period_start_iso,
                end_date=period_end_iso,
                limit=1,
            )
            for status in CHECKIN_STATUSES
        }
        ok_sample, sample_response = api_client.list_checkins(
            token=token,
            course_id=selected_course_id,
            start_date=period_start_iso,
            end_date=period_end_iso,
            limit=RISK_SAMPLE_LIMIT,
            offset=0,
        )
        ok_today_sessions, today_sessions_response = api_client.list_sessions(
            token=token,
            course_id=selected_course_id,
            start_date=today_start,
            end_date=today_end,
            limit=1,
        )

    outcome_counts = {
        status: _total_from_response(response)
        if ok and isinstance(response, dict)
        else None
        for status, (ok, response) in outcome_results.items()
    }
    today_session_count = (
        _total_from_response(today_sessions_response)
        if ok_today_sessions
        else None
    )

    # Pending review alert
    flagged_count = stats.get("flagged_pending", 0)
    if flagged_count > 0:
        st.warning(
            f"🚨 **Attention Required:** There are **{flagged_count}** flagged check-in(s) "
            f"awaiting review. Please navigate to the **Flagged Review Queue** to take action.",
            icon="⚠️",
        )

    # -------------------------------------------------------------------------
    # Key Metric Cards
    # -------------------------------------------------------------------------
    st.markdown("### Key Performance Indicators")
    m1, m2, m3, m4, m5, m6 = st.columns(6)

    with m1:
        st.metric(
            label="Active Sessions",
            value=stats.get("active_sessions", 0),
            delta=f"Total: {stats.get('total_sessions', 0)}",
            delta_color="off",
        )
    with m2:
        st.metric(
            label="Today's Sessions",
            value=(
                today_session_count
                if today_session_count is not None
                else "Unavailable"
            ),
            delta="Scheduled today (Singapore time)",
        )
    with m3:
        today_checkins = stats.get("today_checkins", 0)
        week_checkins = stats.get("total_checkins_week", 0)
        st.metric(
            label="Today's Check-ins",
            value=today_checkins,
            delta=f"{week_checkins} this week",
        )
    with m4:
        approval_rate = stats.get("approval_rate", 0.0) * 100
        st.metric(
            label="Approval Rate",
            value=f"{approval_rate:.1f}%",
            delta=f"Avg Risk: {stats.get('average_risk_score', 0.0):.2f}",
        )
    with m5:
        st.metric(
            label="Enrolled Students",
            value=stats.get("total_students", 0),
            delta=f"{stats.get('total_courses', 0)} active courses",
            delta_color="off",
        )
    with m6:
        st.metric(
            label="Flagged Queue",
            value=flagged_count,
            delta="Pending review" if flagged_count > 0 else "All clear",
            delta_color="inverse" if flagged_count > 0 else "normal",
        )

    st.markdown("---")

    # -------------------------------------------------------------------------
    # Visual Analytics & Charts
    # -------------------------------------------------------------------------
    chart_col1, chart_col2 = st.columns([3, 2])

    with chart_col1:
        st.subheader("Daily Attendance Volume")
        trend_data = stats.get("trends", {}).get("checkins_by_day", [])
        if trend_data:
            df_trends = pd.DataFrame(trend_data)
            df_trends["date"] = pd.to_datetime(df_trends["date"])
            df_trends = df_trends.sort_values("date")

            fig_trend = px.bar(
                df_trends,
                x="date",
                y="count",
                labels={"date": "Date", "count": "Check-in Count"},
                title=f"Check-ins over past {time_window} days",
                color_discrete_sequence=["#2563EB"],
            )
            fig_trend.update_layout(
                xaxis_title="",
                yaxis_title="Total Check-ins",
                margin=dict(l=20, r=20, t=40, b=20),
                height=340,
            )
            st.plotly_chart(fig_trend, use_container_width=True)
        else:
            st.info("No check-in history recorded within the selected period.")

    with chart_col2:
        st.subheader("Exact Check-in Outcomes")
        outcome_columns = st.columns(3)
        for column, status in zip(outcome_columns, CHECKIN_STATUSES):
            with column:
                count = outcome_counts[status]
                st.metric(
                    status.title(),
                    count if count is not None else "Unavailable",
                )
        st.caption(
            f"Counts use actual check-in records for the selected {time_window}-day window."
        )
        if any(value is None for value in outcome_counts.values()):
            st.warning("One or more outcome counts could not be loaded.")

    st.markdown("---")
    st.subheader("Risk-score Distribution")
    st.caption(
        f"Scores from the latest {RISK_SAMPLE_LIMIT} check-ins in the selected "
        f"{time_window}-day window; invalid scores are omitted."
    )
    if not ok_sample or not isinstance(sample_response, dict):
        st.error("Unable to load check-ins for the risk-score distribution.")
    else:
        sample_items = sample_response.get("items", [])
        sample_scores = _risk_scores(sample_items)
        if sample_scores:
            risk_df = pd.DataFrame({"Risk score (0–1)": sample_scores})
            risk_figure = px.histogram(
                risk_df,
                x="Risk score (0–1)",
                nbins=10,
                range_x=[0, 1],
                title=f"Risk scores ({len(sample_scores)} valid sampled records)",
            )
            risk_figure.update_layout(
                xaxis_title="Risk score (0–1)",
                yaxis_title="Number of check-ins",
                bargap=0.05,
                margin=dict(l=20, r=20, t=50, b=20),
            )
            st.plotly_chart(risk_figure, use_container_width=True)
        else:
            st.info("No valid risk scores were returned for the selected window.")

    # -------------------------------------------------------------------------
    # Recent Check-ins Quick Table
    # -------------------------------------------------------------------------
    st.markdown("### Recent Activity")
    ok_recent, recent_data = api_client.list_checkins(
        token=token,
        course_id=selected_course_id,
        limit=10,
    )
    if ok_recent and isinstance(recent_data, dict) and "items" in recent_data:
        items = recent_data["items"]
        if items:
            table_rows = []
            for item in items:
                table_rows.append(
                    {
                        "Student": item.get("student_name") or item.get("student_email", "N/A"),
                        "Course": item.get("course_code", "N/A"),
                        "Session": item.get("session_name", "N/A"),
                        "Status": item.get("status", "").upper(),
                        "Risk Score": f"{item.get('risk_score', 0.0):.2f}",
                        "Distance": f"{item.get('distance_from_venue_meters', 0.0):.1f}m"
                        if item.get("distance_from_venue_meters") is not None
                        else "N/A",
                        "Time": item.get("checked_in_at", "")[:19].replace("T", " "),
                    }
                )
            df_recent = pd.DataFrame(table_rows)
            st.dataframe(df_recent, use_container_width=True, hide_index=True)
        else:
            st.caption("No recent check-ins found.")
