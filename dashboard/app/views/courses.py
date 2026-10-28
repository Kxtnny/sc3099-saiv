"""
Courses & Roster View - View course rosters, bulk enroll students, and export complete gradebooks.
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List
import pandas as pd
import plotly.express as px
import streamlit as st

from app.api_client import api_client
from app.auth import get_token
from app.views._downloads import render_csv_download, render_json_download
from app.views._messages import set_flash_message


def _utc_date_bound(value: date, *, end: bool = False) -> str:
    bound = datetime.combine(
        value + timedelta(days=1) if end else value,
        time.min,
        tzinfo=timezone.utc,
    )
    if end:
        bound -= timedelta(microseconds=1)
    return bound.isoformat().replace("+00:00", "Z")


def render() -> None:
    """Render Courses & Enrollment Roster view."""
    st.title("🎓 Courses & Student Rosters")
    st.caption("Manage course catalogs, inspect enrolled students, bulk-enroll cohorts, and export course gradebooks.")

    token = get_token()
    if not token:
        st.warning("Please sign in to manage courses.")
        return

    # Fetch courses
    with st.spinner("Loading courses..."):
        ok, res = api_client.list_courses(token=token, limit=100)

    if not ok:
        st.error(f"Failed to load courses: {res}")
        return

    courses: List[Dict[str, Any]] = res.get("items", []) if isinstance(res, dict) else []

    if not courses:
        st.info("No courses found. Please ensure courses are created in the database.")
        return

    # Course Selector
    course_options = {f"{c.get('code')} - {c.get('name')} ({c.get('semester', '')})": c for c in courses}
    selected_label = st.selectbox("Select Course:", options=list(course_options.keys()))
    selected_course = course_options[selected_label]
    course_id = selected_course.get("id", "")
    range_col1, range_col2 = st.columns(2)
    with range_col1:
        start_filter = st.date_input(
            "Analytics from",
            value=None,
            key=f"course_stats_start_{course_id}",
        )
    with range_col2:
        end_filter = st.date_input(
            "Analytics through",
            value=None,
            key=f"course_stats_end_{course_id}",
        )
    if start_filter and end_filter and end_filter < start_filter:
        st.error("The end date must be on or after the start date.")
        return

    # Course Summary Cards
    with st.spinner("Loading course statistics..."):
        ok_stats, c_stats = api_client.get_course_stats(token, course_id)

    if not ok_stats or not isinstance(c_stats, dict):
        st.error(f"Failed to load course statistics: {c_stats}")
        return
    stats_data = c_stats

    course_statuses = ("approved", "flagged", "rejected", "pending", "appealed")
    with st.spinner("Loading course attendance breakdown..."):
        status_results = {
            status: api_client.list_checkins(
                token=token,
                course_id=course_id,
                status=status,
                start_date=_utc_date_bound(start_filter) if start_filter else None,
                end_date=_utc_date_bound(end_filter, end=True) if end_filter else None,
                limit=1,
            )
            for status in course_statuses
        }
        ok_risk_sample, risk_sample = api_client.list_checkins(
            token=token,
            course_id=course_id,
            start_date=_utc_date_bound(start_filter) if start_filter else None,
            end_date=_utc_date_bound(end_filter, end=True) if end_filter else None,
            limit=100,
            offset=0,
        )
    status_counts = {
        status: (
            response.get("total")
            if ok and isinstance(response, dict)
            and isinstance(response.get("total"), int)
            and not isinstance(response.get("total"), bool)
            else None
        )
        for status, (ok, response) in status_results.items()
    }
    sample_items = (
        risk_sample.get("items", [])
        if ok_risk_sample and isinstance(risk_sample, dict)
        else []
    )
    risk_values = [
        value
        for item in sample_items
        if isinstance(item, dict)
        for value in [item.get("risk_score")]
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0 <= value <= 1
    ]
    average_sample_risk = (
        sum(risk_values) / len(risk_values) if risk_values else None
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("All-time Enrolled", stats_data.get("total_enrolled", 0))
    with c2:
        st.metric("All-time Sessions", stats_data.get("total_sessions", 0))
    with c3:
        avg_rate = stats_data.get("average_attendance_rate", 0.0) * 100
        st.metric("All-time Avg Attendance Rate", f"{avg_rate:.1f}%")
    with c4:
        st.metric("All-time Flagged Check-ins", stats_data.get("flagged_checkins", 0))
    with c5:
        st.metric(
            "Avg Risk (latest sample)",
            f"{average_sample_risk:.2f}"
            if average_sample_risk is not None
            else "Unavailable",
        )

    trend_sessions = stats_data.get("sessions", [])
    if isinstance(trend_sessions, list):
        trend_sessions = [
            session
            for session in trend_sessions
            if (not start_filter or session.get("date", "") >= start_filter.isoformat())
            and (not end_filter or session.get("date", "") <= end_filter.isoformat())
        ]
    st.subheader("Attendance by Session")
    st.caption(
        "Session attendance trend uses the selected date range; summary rate above is all-time."
    )
    if isinstance(trend_sessions, list) and trend_sessions:
        trend_df = pd.DataFrame(trend_sessions)
        if {"name", "date", "attendance_rate"}.issubset(trend_df.columns):
            trend_df["attendance_percent"] = trend_df["attendance_rate"] * 100
            trend_df = trend_df.sort_values("date")
            trend_figure = px.line(
                trend_df,
                x="date",
                y="attendance_percent",
                markers=True,
                hover_name="name",
                labels={
                    "date": "Session date",
                    "attendance_percent": "Attendance (%)",
                },
                title="Attendance trend by session",
            )
            trend_figure.update_yaxes(rangemode="tozero", range=[0, 100])
            st.plotly_chart(trend_figure, use_container_width=True)
            display_columns = [
                column
                for column in ("date", "name", "status", "checked_in")
                if column in trend_df.columns
            ]
            trend_table = trend_df[display_columns].rename(
                columns={
                    "date": "Date (UTC)",
                    "name": "Session",
                    "status": "Status",
                    "checked_in": "Checked in",
                }
            )
            trend_table["Attendance rate"] = trend_df[
                "attendance_percent"
            ].map(lambda value: f"{value:.1f}%")
            st.dataframe(
                trend_table,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.warning("Course session statistics did not include attendance trend fields.")
    else:
        st.info("No session attendance history is available for this course yet.")

    st.subheader("Check-in Status Breakdown")
    if any(value is None for value in status_counts.values()):
        st.warning("One or more status totals could not be loaded.")
    status_df = pd.DataFrame(
        [
            {"Status": status.title(), "Check-ins": count}
            for status, count in status_counts.items()
            if count is not None
        ]
    )
    if not status_df.empty:
        status_figure = px.bar(
            status_df,
            x="Status",
            y="Check-ins",
            color="Status",
            title="Check-ins by verification status",
        )
        status_figure.update_yaxes(rangemode="tozero")
        st.plotly_chart(status_figure, use_container_width=True)

    if not ok_risk_sample:
        st.error(f"Unable to load risk-score distribution: {risk_sample}")
    elif risk_values:
        risk_categories = pd.cut(
            risk_values,
            bins=[-0.001, 0.3, 0.5, 1.0],
            labels=["Low (0–0.30)", "Medium (>0.30–0.50)", "High (>0.50–1.00)"],
            include_lowest=True,
        )
        risk_counts = (
            pd.Series(risk_categories)
            .value_counts(sort=False)
            .rename_axis("Risk category")
            .reset_index(name="Check-ins")
        )
        st.subheader("Risk-score Distribution")
        st.caption("Distribution from up to the latest 100 course check-ins.")
        risk_figure = px.bar(
            risk_counts,
            x="Risk category",
            y="Check-ins",
            color="Risk category",
            title="Risk categories",
        )
        risk_figure.update_yaxes(rangemode="tozero")
        st.plotly_chart(risk_figure, use_container_width=True)
    else:
        st.info("No valid risk scores are available for this course.")

    # Gradebook CSV Download
    col_dl1, col_dl2 = st.columns([3, 1])
    with col_dl2:
        render_csv_download(
            token=token,
            cache_key=f"course_{course_id}",
            request_label="📥 Export Full Gradebook CSV",
            download_label="Download Full Gradebook CSV",
            file_name=f"gradebook_{selected_course.get('code', 'course')}.csv",
            export=lambda: api_client.export_course_csv(token, course_id),
            button_type="primary",
            use_container_width=True,
        )
        render_json_download(
            token=token,
            cache_key=f"course_{course_id}",
            request_label="📥 Export Gradebook JSON",
            download_label="Download Gradebook JSON",
            file_name=f"gradebook_{selected_course.get('code', 'course')}.json",
            export=lambda: api_client.export_course_json(token, course_id),
            use_container_width=True,
        )

    st.markdown("---")

    # Tabs: Roster vs Bulk Enroll
    tab_roster, tab_bulk = st.tabs(["👥 Student Roster", "➕ Bulk Enroll Students"])

    # -------------------------------------------------------------------------
    # TAB 1: Student Roster
    # -------------------------------------------------------------------------
    with tab_roster:
        search_term = st.text_input("Search student name or email", placeholder="Type to search...", key="roster_search")

        with st.spinner("Fetching enrolled students..."):
            ok_roster, roster_data = api_client.get_course_enrollments(
                token=token,
                course_id=course_id,
                search=search_term.strip() if search_term else None,
            )

        if not ok_roster:
            st.error(f"Failed to load roster: {roster_data}")
        else:
            students = roster_data.get("students", []) if isinstance(roster_data, dict) else []
            st.write(f"Enrolled Students: **{len(students)}**")

            if students:
                roster_rows = []
                for s in students:
                    roster_rows.append(
                        {
                            "Enrollment ID": s.get("id"),
                            "Name": s.get("student_name", "N/A"),
                            "Email": s.get("student_email", "N/A"),
                            "Face Enrolled": "✅ Enrolled" if s.get("face_enrolled") else "⚪ Pending",
                            "Enrolled At": s.get("enrolled_at", "")[:10] if s.get("enrolled_at") else "N/A",
                            "Status": "Active" if s.get("is_active") else "Dropped",
                        }
                    )
                df_roster = pd.DataFrame(roster_rows)
                st.dataframe(
                    df_roster.drop(columns=["Enrollment ID"]),
                    use_container_width=True,
                    hide_index=True,
                )

                student_options = {
                    f"{student.get('student_name', 'Student')} "
                    f"({student.get('student_email', 'N/A')})": student.get(
                        "student_id"
                    )
                    for student in students
                    if student.get("student_id")
                }
                if student_options:
                    st.subheader("Student Attendance Detail")
                    selected_student = st.selectbox(
                        "Inspect student attendance",
                        options=list(student_options.keys()),
                        key=f"student_stats_select_{course_id}",
                    )
                    student_id = student_options[selected_student]
                    with st.spinner("Loading student attendance history..."):
                        ok_student_stats, student_stats = api_client.get_student_stats(
                            token, student_id
                        )
                    if ok_student_stats and isinstance(student_stats, dict):
                        st.caption(
                            "These student statistics cover the student's attendance across all courses."
                        )
                        student_rate = student_stats.get("attendance_rate")
                        s_col1, s_col2, s_col3 = st.columns(3)
                        with s_col1:
                            st.metric(
                                "Attendance rate",
                                f"{student_rate * 100:.1f}%"
                                if isinstance(student_rate, (int, float))
                                else "Unavailable",
                            )
                        with s_col2:
                            st.metric(
                                "Attended sessions",
                                student_stats.get("attended_sessions", "Unavailable"),
                            )
                        with s_col3:
                            st.metric(
                                "Average risk score",
                                f"{student_stats.get('average_risk_score', 0):.2f}",
                            )
                        recent_sessions = student_stats.get("recent_sessions", [])
                        if recent_sessions:
                            st.dataframe(
                                pd.DataFrame(recent_sessions),
                                use_container_width=True,
                                hide_index=True,
                            )
                    else:
                        st.error(f"Failed to load student statistics: {student_stats}")

                # Drop student action
                with st.expander("Drop a student from course"):
                    enrollment_map = {
                        f"{s.get('student_name', '')} ({s.get('student_email', '')})": s.get("id")
                        for s in students
                    }
                    drop_student_label = st.selectbox("Select student to drop:", options=list(enrollment_map.keys()))
                    if st.button("Drop Student", type="secondary"):
                        drop_id = enrollment_map[drop_student_label]
                        ok_drop, drop_res = api_client.delete_enrollment(token, drop_id)
                        if ok_drop:
                            set_flash_message("Student dropped from course.")
                            st.rerun()
                        else:
                            st.error(f"Error: {drop_res}")
            else:
                st.info("No students enrolled in this course yet.")

    # -------------------------------------------------------------------------
    # TAB 2: Bulk Enrollment
    # -------------------------------------------------------------------------
    with tab_bulk:
        st.subheader(f"Enroll Cohort into {selected_course.get('code')}")
        st.caption("Paste a list of student email addresses (comma, semicolon, or newline separated).")

        with st.form("bulk_enroll_form"):
            raw_emails = st.text_area(
                "Student Emails *",
                height=180,
                placeholder="alice@ntu.edu.sg\nbob@ntu.edu.sg\ncarol@ntu.edu.sg",
            )
            create_accounts = st.checkbox(
                "Auto-create placeholder accounts if email not found in system",
                value=True,
                help="Creates student account with temporary credentials if the user has not registered yet.",
            )
            submit_bulk = st.form_submit_button("Bulk Enroll Students", type="primary")

        if submit_bulk:
            if not raw_emails.strip():
                st.error("Please enter at least one student email.")
                return

            # Clean email list
            cleaned_emails = []
            for line in raw_emails.replace(",", "\n").replace(";", "\n").splitlines():
                email_clean = line.strip().lower()
                if email_clean and "@" in email_clean:
                    cleaned_emails.append(email_clean)

            if not cleaned_emails:
                st.error("No valid email addresses parsed.")
                return

            with st.spinner(f"Enrolling {len(cleaned_emails)} students..."):
                ok_bulk, bulk_res = api_client.bulk_enroll(
                    token=token,
                    course_id=course_id,
                    student_emails=cleaned_emails,
                    create_accounts=create_accounts,
                )

            if ok_bulk and isinstance(bulk_res, dict):
                set_flash_message(
                    f"Enrollment processed: **{bulk_res.get('enrolled', 0)}** newly enrolled, "
                    f"**{bulk_res.get('already_enrolled', 0)}** already enrolled, "
                    f"**{bulk_res.get('created', 0)}** accounts created."
                )
                st.rerun()
            else:
                detail = bulk_res.get("detail", bulk_res) if isinstance(bulk_res, dict) else str(bulk_res)
                st.error(f"Bulk enrollment failed: {detail}")
