"""
Session Management View - Create, manage, live QR code display, and session attendance export.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import streamlit as st

from app.api_client import api_client
from app.auth import get_token


def render() -> None:
    """Render Session Management view."""
    st.title("📅 Session Management")
    st.caption("Schedule attendance windows, monitor live sessions, project classroom QR codes, and export records.")

    token = get_token()
    if not token:
        st.warning("Please sign in to manage sessions.")
        return

    # Tabs: Active & All Sessions vs Create Session
    tab_list, tab_create = st.tabs(["📋 All Sessions", "➕ Create New Session"])

    # -------------------------------------------------------------------------
    # TAB 1: Session Listing & Controls
    # -------------------------------------------------------------------------
    with tab_list:
        col_f1, col_f2, col_refresh = st.columns([2, 2, 1])
        with col_f1:
            status_filter = st.selectbox(
                "Filter by Status",
                options=["All", "active", "scheduled", "closed", "cancelled"],
                index=0,
            )
        with col_f2:
            ok_courses, courses_data = api_client.list_courses(token=token)
            course_map: Dict[str, Optional[str]] = {"All Courses": None}
            if ok_courses and isinstance(courses_data, dict) and "items" in courses_data:
                for c in courses_data["items"]:
                    course_map[f"{c.get('code', '')} - {c.get('name', '')}"] = c.get("id")
            selected_course_label = st.selectbox("Filter by Course", options=list(course_map.keys()))
            filter_course_id = course_map[selected_course_label]

        with col_refresh:
            st.write("")
            st.write("")
            st.button("🔄 Refresh", key="btn_refresh_sessions")

        # Fetch sessions
        status_param = None if status_filter == "All" else status_filter
        with st.spinner("Loading sessions..."):
            ok, res = api_client.list_sessions(
                token=token,
                status=status_param,
                course_id=filter_course_id,
                limit=100,
            )

        if not ok:
            st.error(f"Failed to load sessions: {res}")
            return

        sessions: List[Dict[str, Any]] = res.get("items", []) if isinstance(res, dict) else []

        if not sessions:
            st.info("No sessions found matching the filters.")
        else:
            st.write(f"Showing **{len(sessions)}** session(s):")

            for s in sessions:
                session_id = s.get("id", "")
                name = s.get("name", "Untitled")
                course_code = s.get("course_code") or "Course"
                status = s.get("status", "scheduled").lower()
                scheduled_start = s.get("scheduled_start", "")[:16].replace("T", " ")
                scheduled_end = s.get("scheduled_end", "")[:16].replace("T", " ")
                venue = s.get("venue_name") or "Campus Venue"
                enrolled = s.get("total_enrolled") or 0
                checked_in = s.get("checked_in_count") or 0

                status_color_map = {
                    "active": "🟢 ACTIVE",
                    "scheduled": "🟡 SCHEDULED",
                    "closed": "⚪ CLOSED",
                    "cancelled": "🔴 CANCELLED",
                }
                status_badge = status_color_map.get(status, status.upper())

                with st.expander(f"**{course_code}: {name}** — {status_badge} ({scheduled_start})", expanded=(status == "active")):
                    col_info1, col_info2, col_info3 = st.columns([2, 2, 2])

                    with col_info1:
                        st.markdown(f"**Course:** {course_code}")
                        st.markdown(f"**Type:** {s.get('session_type', 'lecture').capitalize()}")
                        st.markdown(f"**Venue:** {venue}")
                        radius = s.get("geofence_radius_meters", 50)
                        st.markdown(f"**Geofence Radius:** {radius}m")

                    with col_info2:
                        st.markdown(f"**Scheduled Start:** {scheduled_start}")
                        st.markdown(f"**Scheduled End:** {scheduled_end}")
                        st.markdown(f"**Risk Cutoff:** {s.get('risk_threshold', 0.5)}")
                        liveness_req = "Yes" if s.get("require_liveness_check") else "No"
                        st.markdown(f"**Liveness Required:** {liveness_req}")

                    with col_info3:
                        st.markdown(f"**Enrolled:** {enrolled} students")
                        st.markdown(f"**Checked In:** {checked_in} students")
                        if enrolled > 0:
                            pct = (checked_in / enrolled) * 100
                            st.progress(min(pct / 100, 1.0), text=f"Attendance: {pct:.1f}%")

                    st.markdown("---")

                    # Control Actions Row
                    btn_col1, btn_col2, btn_col3, btn_col4 = st.columns([2, 2, 2, 2])

                    with btn_col1:
                        if status == "scheduled":
                            if st.button("▶️ Start Session", key=f"start_{session_id}", type="primary"):
                                ok_update, update_res = api_client.update_session(
                                    token, session_id, {"status": "active"}
                                )
                                if ok_update:
                                    st.success("Session activated! Check-in is now open.")
                                    st.rerun()
                                else:
                                    st.error(f"Error: {update_res}")
                        elif status == "active":
                            if st.button("⏹️ Close Session", key=f"close_{session_id}"):
                                ok_update, update_res = api_client.update_session(
                                    token, session_id, {"status": "closed"}
                                )
                                if ok_update:
                                    st.success("Session closed.")
                                    st.rerun()
                                else:
                                    st.error(f"Error: {update_res}")

                    with btn_col2:
                        # Classroom QR Code Projector
                        qr_key = f"qr_open_{session_id}"
                        if st.button("📱 Classroom QR Mode", key=f"btn_qr_{session_id}"):
                            st.session_state[qr_key] = not st.session_state.get(qr_key, False)

                    with btn_col3:
                        # CSV Gradebook Export
                        ok_csv, csv_content = api_client.export_session_csv(token, session_id)
                        if ok_csv and isinstance(csv_content, bytes):
                            st.download_button(
                                label="📥 Export CSV",
                                data=csv_content,
                                file_name=f"attendance_{course_code}_{name}.csv",
                                mime="text/csv",
                                key=f"dl_csv_{session_id}",
                            )

                    with btn_col4:
                        if status == "scheduled":
                            if st.button("🗑️ Delete Session", key=f"del_{session_id}"):
                                ok_del, del_res = api_client.delete_session(token, session_id)
                                if ok_del:
                                    st.success("Session deleted.")
                                    st.rerun()
                                else:
                                    st.error(f"Error: {del_res}")

                    # Classroom QR Display Section
                    if st.session_state.get(qr_key, False):
                        st.markdown("#### 📱 Live Classroom QR Code")
                        st.caption(
                            "Project this screen in class. The code rotates and automatically expires to prevent screenshot sharing."
                        )

                        c_qr1, c_qr2 = st.columns([1, 2])
                        with c_qr1:
                            if st.button("🔄 Generate / Rotate QR", key=f"gen_qr_{session_id}"):
                                with st.spinner("Issuing fresh QR secret..."):
                                    ok_qr, qr_data = api_client.generate_session_qr(token, session_id)
                                    if ok_qr:
                                        st.session_state[f"qr_data_{session_id}"] = qr_data
                                    else:
                                        st.error(f"Error: {qr_data}")

                            if st.button("❌ Disable QR Code", key=f"clear_qr_{session_id}"):
                                api_client.clear_session_qr(token, session_id)
                                if f"qr_data_{session_id}" in st.session_state:
                                    del st.session_state[f"qr_data_{session_id}"]
                                st.info("QR code cleared.")
                                st.rerun()

                        with c_qr2:
                            current_qr = st.session_state.get(f"qr_data_{session_id}")
                            if current_qr:
                                qr_secret = current_qr.get("qr_code", "")
                                expires_at = current_qr.get("expires_at", "")[:19].replace("T", " ")
                                ttl = current_qr.get("ttl_seconds", 180)

                                qr_image_url = (
                                    f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={qr_secret}"
                                )
                                st.image(qr_image_url, caption="Scan using the SAIV Student App", width=220)
                                st.markdown(f"**Token:** `{qr_secret}`")
                                st.markdown(f"**Expires At:** `{expires_at} UTC` (TTL: {ttl}s)")
                            else:
                                st.info("Click 'Generate / Rotate QR' above to issue a one-time secret.")

    # -------------------------------------------------------------------------
    # TAB 2: Create New Session
    # -------------------------------------------------------------------------
    with tab_create:
        st.subheader("Schedule an Attendance Session")
        st.caption("Define the course, timing, geofence, and security thresholds for student check-ins.")

        # Ensure we have courses to choose from
        if not courses_data or not courses_data.get("items"):
            st.warning("No courses available. Please create courses in the Courses section first.")
            return

        with st.form("create_session_form"):
            c_sel1, c_sel2 = st.columns([2, 1])
            with c_sel1:
                course_select_options = {
                    f"{c.get('code')} - {c.get('name')}": c for c in courses_data.get("items", [])
                }
                selected_course_obj = st.selectbox(
                    "Course *",
                    options=list(course_select_options.keys()),
                )
                selected_course = course_select_options[selected_course_obj]

            with c_sel2:
                session_type = st.selectbox(
                    "Session Type *",
                    options=["lecture", "tutorial", "lab"],
                    index=0,
                )

            session_name = st.text_input(
                "Session Title *",
                value=f"{selected_course.get('code', 'Course')} Session",
                placeholder="e.g. Week 3: Deep Neural Networks",
            )
            session_desc = st.text_area("Description (Optional)", placeholder="Overview of lecture topics...")

            st.markdown("#### Schedule & Timing")
            col_d1, col_d2 = st.columns(2)
            today = datetime.now(timezone.utc).date()
            now_time = (datetime.now(timezone.utc) + timedelta(minutes=5)).time()
            end_time = (datetime.now(timezone.utc) + timedelta(hours=2)).time()

            with col_d1:
                date_val = st.date_input("Date *", value=today)
                start_t = st.time_input("Scheduled Start *", value=now_time)
            with col_d2:
                st.write("")
                st.write("")
                end_t = st.time_input("Scheduled End *", value=end_time)

            st.markdown("#### Geolocation & Security Constraints")
            col_g1, col_g2, col_g3 = st.columns(3)
            with col_g1:
                default_venue = selected_course.get("venue_name") or "LT1A"
                venue_name = st.text_input("Venue Name", value=default_venue)
            with col_g2:
                venue_lat = st.number_input(
                    "Venue Latitude",
                    value=float(selected_course.get("venue_latitude") or 1.3483),
                    format="%.6f",
                )
            with col_g3:
                venue_lon = st.number_input(
                    "Venue Longitude",
                    value=float(selected_course.get("venue_longitude") or 103.6831),
                    format="%.6f",
                )

            col_s1, col_s2, col_s3 = st.columns(3)
            with col_s1:
                geofence_radius = st.slider(
                    "Geofence Radius (meters)",
                    min_value=10,
                    max_value=500,
                    value=int(selected_course.get("geofence_radius_meters") or 50),
                    step=5,
                )
            with col_s2:
                risk_threshold = st.slider(
                    "Risk Flagging Threshold",
                    min_value=0.1,
                    max_value=1.0,
                    value=float(selected_course.get("risk_threshold") or 0.5),
                    step=0.05,
                    help="Check-ins scoring higher than this will be flagged for review.",
                )
            with col_s3:
                req_liveness = st.checkbox("Require Liveness Check", value=True)
                req_face = st.checkbox("Require Face Verification", value=True)

            submitted = st.form_submit_button("Create Session", type="primary", use_container_width=True)

        if submitted:
            if not session_name:
                st.error("Please provide a session title.")
                return

            dt_start = datetime.combine(date_val, start_t, tzinfo=timezone.utc)
            dt_end = datetime.combine(date_val, end_t, tzinfo=timezone.utc)

            if dt_end <= dt_start:
                st.error("Scheduled end time must be after scheduled start time.")
                return

            payload = {
                "course_id": selected_course["id"],
                "name": session_name.strip(),
                "session_type": session_type,
                "description": session_desc.strip() if session_desc else None,
                "scheduled_start": dt_start.isoformat(),
                "scheduled_end": dt_end.isoformat(),
                "venue_name": venue_name.strip(),
                "venue_latitude": venue_lat,
                "venue_longitude": venue_lon,
                "geofence_radius_meters": geofence_radius,
                "risk_threshold": risk_threshold,
                "require_liveness_check": req_liveness,
                "require_face_match": req_face,
            }

            with st.spinner("Creating session..."):
                ok_create, create_res = api_client.create_session(token, payload)

            if ok_create:
                st.success(f"Session '{session_name}' created successfully!")
                st.rerun()
            else:
                detail = create_res.get("detail", create_res) if isinstance(create_res, dict) else str(create_res)
                st.error(f"Failed to create session: {detail}")

