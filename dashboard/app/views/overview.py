"""
Overview Dashboard View - High-level metrics, trends, and verification analytics.
"""

from typing import Any, Dict
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.api_client import api_client
from app.auth import get_token


def render() -> None:
    """Render the Overview landing page."""
    st.title("📊 Attendance Overview")
    st.caption("Real-time telemetry and system-wide verification analytics.")

    token = get_token()
    if not token:
        st.warning("Please sign in to view analytics.")
        return

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
    m1, m2, m3, m4, m5 = st.columns(5)

    with m1:
        st.metric(
            label="Active Sessions",
            value=stats.get("active_sessions", 0),
            delta=f"Total: {stats.get('total_sessions', 0)}",
            delta_color="off",
        )
    with m2:
        today_checkins = stats.get("today_checkins", 0)
        week_checkins = stats.get("total_checkins_week", 0)
        st.metric(
            label="Today's Check-ins",
            value=today_checkins,
            delta=f"{week_checkins} this week",
        )
    with m3:
        approval_rate = stats.get("approval_rate", 0.0) * 100
        st.metric(
            label="Approval Rate",
            value=f"{approval_rate:.1f}%",
            delta=f"Avg Risk: {stats.get('average_risk_score', 0.0):.2f}",
        )
    with m4:
        st.metric(
            label="Enrolled Students",
            value=stats.get("total_students", 0),
            delta=f"{stats.get('total_courses', 0)} active courses",
            delta_color="off",
        )
    with m5:
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
        st.subheader("Verification Health")
        # Build status pie chart
        approved = int(stats.get("total_checkins", 0) * stats.get("approval_rate", 0.0))
        flagged = stats.get("flagged_pending", 0)
        total = stats.get("total_checkins", 0)
        rejected = max(0, total - approved - flagged)

        if total > 0:
            status_df = pd.DataFrame(
                [
                    {"Status": "Approved", "Count": approved, "Color": "#10B981"},
                    {"Status": "Flagged / Pending", "Count": flagged, "Color": "#F59E0B"},
                    {"Status": "Rejected", "Count": rejected, "Color": "#EF4444"},
                ]
            )
            fig_pie = px.pie(
                status_df,
                names="Status",
                values="Count",
                hole=0.5,
                color="Status",
                color_discrete_map={
                    "Approved": "#10B981",
                    "Flagged / Pending": "#F59E0B",
                    "Rejected": "#EF4444",
                },
            )
            fig_pie.update_layout(
                margin=dict(l=10, r=10, t=20, b=20),
                height=340,
                legend=dict(orientation="h", yanchor="bottom", y=-0.2),
            )
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("No verification records available to display distribution.")

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

