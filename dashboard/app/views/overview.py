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
from app.auth import get_current_user
from app.access import load_visible_courses
from app.rbac import Permission, require_permission, role_for_user


SINGAPORE_TIMEZONE = ZoneInfo("Asia/Singapore")
CHECKIN_STATUSES = ("approved", "flagged", "rejected", "pending", "appealed")
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


def _flagged_share(outcome_counts: Dict[str, Any]) -> Optional[float]:
    """Return flagged/(all known outcomes), or None for incomplete/empty data."""
    counts = [outcome_counts.get(status) for status in CHECKIN_STATUSES]
    if any(
        isinstance(count, bool)
        or not isinstance(count, int)
        or count < 0
        for count in counts
    ):
        return None
    total = sum(counts)
    return outcome_counts["flagged"] / total if total else None


def _daily_counts(items: Any) -> List[Dict[str, Any]]:
    """Aggregate a bounded, course-scoped check-in sample by Singapore day."""
    if not isinstance(items, list):
        return []
    counts: Dict[str, int] = {}
    for item in items:
        checked_in_at = item.get("checked_in_at") if isinstance(item, dict) else None
        if not isinstance(checked_in_at, str):
            continue
        try:
            timestamp = datetime.fromisoformat(
                checked_in_at.replace("Z", "+00:00")
            ).astimezone(SINGAPORE_TIMEZONE)
        except ValueError:
            continue
        day = timestamp.date().isoformat()
        counts[day] = counts.get(day, 0) + 1
    return [{"date": day, "count": count} for day, count in sorted(counts.items())]


def render() -> None:
    """Render the Overview landing page."""
    if not require_permission(
        get_current_user(), Permission.VIEW_COURSE_ANALYTICS
    ):
        return
    st.title("📊 Attendance Overview")
    st.caption("Real-time telemetry and system-wide verification analytics.")

    token = get_token()
    if not token:
        st.warning("Please sign in to view analytics.")
        return

    _schedule_auto_refresh()
    st.caption("This read-only overview refreshes automatically every 30 seconds.")

    user = get_current_user()
    role = role_for_user(user)

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
        ok_courses, visible_courses, scope_message = load_visible_courses(
            token, user
        )
        if not ok_courses:
            st.error(scope_message or "Unable to load courses.")
            return
        course_options = {"All Courses": None} if role == "admin" else {}
        for course in visible_courses:
            course_id = course.get("id")
            if isinstance(course_id, str) and course_id:
                course_options[
                    f"{course.get('code', '')} - {course.get('name', '')}"
                ] = course_id
        if not course_options:
            st.info(scope_message or "No courses are available for this account.")
            return
        selected_course_label = st.selectbox(
            "Course Scope",
            options=list(course_options.keys()),
            index=0,
        )
        selected_course_id = course_options[selected_course_label]

    with col_btn:
        st.write("")
        st.write("")
        st.button("🔄 Refresh", use_container_width=True)

    with st.spinner("Fetching system statistics..."):
        ok, stats = api_client.get_overview_stats(
            token, days=time_window, course_id=selected_course_id
        )

    if not ok:
        st.error(f"Unable to load statistics: {stats}")
        return
    if not isinstance(stats, dict):
        st.error("Unable to load statistics: the server returned an invalid response.")
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
        ok_today_checkins, today_checkins_response = api_client.list_checkins(
            token=token,
            course_id=selected_course_id,
            start_date=today_start,
            end_date=today_end,
            limit=1,
        )
        ok_today_sample, today_sample_response = api_client.list_checkins(
            token=token,
            course_id=selected_course_id,
            start_date=today_start,
            end_date=today_end,
            limit=100,
            offset=0,
        )
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
    flagged_share = _flagged_share(outcome_counts)

    course_summary = None
    if selected_course_id:
        ok_course_summary, course_summary_response = api_client.get_course_stats(
            token, selected_course_id
        )
        if ok_course_summary and isinstance(course_summary_response, dict):
            course_summary = course_summary_response
        else:
            st.error(
                f"Unable to load selected-course attendance summary: "
                f"{course_summary_response}"
            )
    today_session_count = (
        _total_from_response(today_sessions_response)
        if ok_today_sessions
        else None
    )
    today_checkin_count = (
        _total_from_response(today_checkins_response)
        if ok_today_checkins
        else None
    )
    st.caption(
        f"Last updated: {datetime.now(SINGAPORE_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S %Z')}."
    )

    # Pending review alert
    flagged_count = stats.get("flagged_pending", 0)
    if flagged_count > 0:
        st.warning(
            f"🚨 **Attention Required:** There are **{flagged_count}** flagged check-in(s) "
            "awaiting review. Open the review queue to take action.",
            icon="⚠️",
        )
        if st.button("Open flagged review queue", type="primary"):
            st.session_state["dashboard_page"] = "🚨 Review Queue"
            st.rerun()

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
        week_checkins = stats.get("total_checkins_week", 0)
        st.metric(
            label="Today's Check-ins",
            value=(
                today_checkin_count
                if today_checkin_count is not None
                else "Unavailable"
            ),
            delta=f"{week_checkins} this week",
        )
    with m4:
        approval_rate = stats.get("approval_rate")
        st.metric(
            label="Approval Rate",
            value=(
                f"{approval_rate * 100:.1f}%"
                if isinstance(approval_rate, Real)
                and not isinstance(approval_rate, bool)
                else "Unavailable"
            ),
            delta=f"Avg Risk: {stats.get('average_risk_score', 0.0):.2f}",
        )
    with m5:
        enrolled_count = (
            course_summary.get("total_enrolled")
            if course_summary
            else stats.get("total_students", 0)
        )
        st.metric(
            label=(
                "Enrolled Students"
                if selected_course_id
                else "Active Students (all courses)"
            ),
            value=enrolled_count,
            delta=(
                "Selected course"
                if selected_course_id
                else f"{stats.get('total_courses', 0)} active courses"
            ),
            delta_color="off",
        )
    with m6:
        st.metric(
            label="Flagged Queue",
            value=flagged_count,
            delta="Pending review" if flagged_count > 0 else "All clear",
            delta_color="inverse" if flagged_count > 0 else "normal",
        )

    summary_columns = st.columns(3)
    with summary_columns[0]:
        attendance_rate = (
            course_summary.get("average_attendance_rate")
            if course_summary
            else None
        )
        st.metric(
            "Recorded Check-in Rate",
            f"{attendance_rate * 100:.1f}%"
            if isinstance(attendance_rate, Real)
            and not isinstance(attendance_rate, bool)
            else "Unavailable",
            delta="API count includes all recorded statuses"
            if selected_course_id
            else "Select a course for a course-scoped rate",
        )
    with summary_columns[1]:
        flagged_count_period = outcome_counts.get("flagged")
        approved_count_period = outcome_counts.get("approved")
        st.metric(
            "Flagged / Approved",
            f"{flagged_count_period} / {approved_count_period}"
            if flagged_count_period is not None
            and approved_count_period is not None
            else "Unavailable",
            delta=(
                f"{flagged_share:.1%} flagged share"
                if flagged_share is not None
                else "No check-ins in selected period"
            ),
        )
    with summary_columns[2]:
        st.metric(
            "Average Risk Score",
            f"{stats.get('average_risk_score'):.2f}"
            if isinstance(stats.get("average_risk_score"), Real)
            and not isinstance(stats.get("average_risk_score"), bool)
            else "Unavailable",
            delta="Backend summary",
        )

    st.markdown("---")

    # -------------------------------------------------------------------------
    # Visual Analytics & Charts
    # -------------------------------------------------------------------------
    chart_col1, chart_col2 = st.columns([3, 2])

    with chart_col1:
        st.subheader("Daily Attendance Volume")
        trend_data = (
            _daily_counts(sample_response.get("items", []))
            if selected_course_id
            and ok_sample
            and isinstance(sample_response, dict)
            else stats.get("trends", {}).get("checkins_by_day", [])
        )
        if trend_data:
            df_trends = pd.DataFrame(trend_data)
            df_trends["date"] = pd.to_datetime(df_trends["date"])
            df_trends = df_trends.sort_values("date")

            fig_trend = px.bar(
                df_trends,
                x="date",
                y="count",
                labels={"date": "Date", "count": "Check-in Count"},
                title=(
                    f"Sampled check-ins over past {time_window} days"
                    if selected_course_id
                    else f"Check-ins over past {time_window} days"
                ),
                color_discrete_sequence=["#2563EB"],
            )
            fig_trend.update_layout(
                xaxis_title="",
                yaxis_title="Total Check-ins",
                yaxis_rangemode="tozero",
                margin=dict(l=20, r=20, t=40, b=20),
                height=340,
            )
            st.plotly_chart(fig_trend, use_container_width=True)
        else:
            if selected_course_id and not ok_sample:
                st.error("Unable to load course check-ins for the attendance trend.")
            else:
                st.info("No check-in history recorded within the selected period.")

    with chart_col2:
        st.subheader("Exact Check-in Outcomes")
        outcome_columns = st.columns(len(CHECKIN_STATUSES))
        for column, status in zip(outcome_columns, CHECKIN_STATUSES):
            with column:
                count = outcome_counts[status]
                st.metric(
                    status.title(),
                    count if count is not None else "Unavailable",
                )
        st.caption(
            f"Counts use actual records for the selected {time_window}-day window."
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
                yaxis_rangemode="tozero",
                bargap=0.05,
                margin=dict(l=20, r=20, t=50, b=20),
            )
            st.plotly_chart(risk_figure, use_container_width=True)
        else:
            st.info("No valid risk scores were returned for the selected window.")

    # -------------------------------------------------------------------------
    # Today's check-in pattern
    st.subheader("Today's Check-ins by Hour")
    if not ok_today_sample or not isinstance(today_sample_response, dict):
        st.error("Unable to load today's check-ins by hour.")
    else:
        today_sample_items = today_sample_response.get("items", [])
        sample_items_valid = isinstance(today_sample_items, list)
        if not sample_items_valid:
            st.error("Today's check-in response had an invalid format.")
            today_sample_items = []
        hourly_counts = {hour: 0 for hour in range(24)}
        for item in today_sample_items:
            if not isinstance(item, dict):
                continue
            checked_in_at = item.get("checked_in_at")
            if not isinstance(checked_in_at, str):
                continue
            try:
                checkin_time = datetime.fromisoformat(
                    checked_in_at.replace("Z", "+00:00")
                ).astimezone(SINGAPORE_TIMEZONE)
            except ValueError:
                continue
            hourly_counts[checkin_time.hour] += 1

        if not sample_items_valid:
            pass
        elif today_checkin_count == 0 and not today_sample_items:
            st.info("No check-ins have been recorded today.")
        elif today_checkin_count is None and not today_sample_items:
            st.warning("Today's check-in count is unavailable.")
        else:
            hour_df = pd.DataFrame(
                [
                    {"Hour (Singapore time)": f"{hour:02d}:00", "Check-ins": count}
                    for hour, count in hourly_counts.items()
                ]
            )
            hour_figure = px.bar(
                hour_df,
                x="Hour (Singapore time)",
                y="Check-ins",
                title="Hourly check-ins today (up to the latest 100 records)",
                color_discrete_sequence=["#2563EB"],
            )
            hour_figure.update_layout(
                yaxis_rangemode="tozero",
                margin=dict(l=20, r=20, t=50, b=20),
                height=320,
            )
            st.plotly_chart(hour_figure, use_container_width=True)

    # Recent Check-ins Quick Table
    # -------------------------------------------------------------------------
    st.markdown("### Recent Activity")
    ok_recent, recent_data = api_client.list_checkins(
        token=token,
        course_id=selected_course_id,
        limit=10,
    )
    if not ok_recent:
        st.error(f"Unable to load recent check-ins: {recent_data}")
    elif isinstance(recent_data, dict) and isinstance(recent_data.get("items"), list):
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
            recent_options = {
                f"#{item.get('id', '')[:8]} · "
                f"{item.get('student_name') or item.get('student_email', 'Student')} · "
                f"{item.get('status', '').upper()}": item.get("id")
                for item in items
                if item.get("id")
            }
            if recent_options:
                selected_recent = st.selectbox(
                    "Inspect a recent check-in",
                    options=list(recent_options.keys()),
                    key="overview_recent_checkin",
                )
                if st.button("Open selected check-in", key="overview_inspect_checkin"):
                    st.session_state["checkin_target_id"] = recent_options[
                        selected_recent
                    ]
                    st.session_state["dashboard_page"] = "📋 Check-in Explorer"
                    st.rerun()
        else:
            st.caption("No recent check-ins found.")
    else:
        st.error("Unable to load recent check-ins: invalid response format.")
