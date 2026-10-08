"""
Courses & Roster View - View course rosters, bulk enroll students, and export complete gradebooks.
"""

from typing import Any, Dict, List
import pandas as pd
import streamlit as st

from app.api_client import api_client
from app.auth import get_token


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

    # Course Summary Cards
    with st.spinner("Loading course statistics..."):
        ok_stats, c_stats = api_client.get_course_stats(token, course_id)

    stats_data = c_stats if ok_stats and isinstance(c_stats, dict) else {}

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Total Enrolled", stats_data.get("total_enrolled", 0))
    with c2:
        st.metric("Total Sessions", stats_data.get("total_sessions", 0))
    with c3:
        avg_rate = stats_data.get("average_attendance_rate", 0.0) * 100
        st.metric("Avg Attendance Rate", f"{avg_rate:.1f}%")
    with c4:
        st.metric("Flagged Check-ins", stats_data.get("flagged_checkins", 0))

    # Gradebook CSV Download
    col_dl1, col_dl2 = st.columns([3, 1])
    with col_dl2:
        ok_csv, csv_data = api_client.export_course_csv(token, course_id)
        if ok_csv and isinstance(csv_data, bytes):
            st.download_button(
                label="📥 Export Full Gradebook CSV",
                data=csv_data,
                file_name=f"gradebook_{selected_course.get('code', 'course')}.csv",
                mime="text/csv",
                use_container_width=True,
                type="primary",
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
                            st.success(f"Student dropped from course.")
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
                st.success(
                    f"Enrollment processed: **{bulk_res.get('enrolled', 0)}** newly enrolled, "
                    f"**{bulk_res.get('already_enrolled', 0)}** already enrolled, "
                    f"**{bulk_res.get('created', 0)}** accounts created."
                )
                st.rerun()
            else:
                detail = bulk_res.get("detail", bulk_res) if isinstance(bulk_res, dict) else str(bulk_res)
                st.error(f"Bulk enrollment failed: {detail}")

