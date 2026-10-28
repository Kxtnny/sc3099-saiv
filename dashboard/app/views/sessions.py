"""
Session Management View - Create, manage, live QR code display, and session attendance export.
"""

from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from typing import Any, Dict, List, Optional
import pandas as pd
import qrcode
import streamlit as st

from app.api_client import api_client
from app.auth import can_create_sessions, can_manage_session, get_current_user, get_token
from app.views._downloads import render_csv_download, render_json_download
from app.views._messages import set_flash_message


SINGAPORE_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Singapore")


def _scheduled_time_utc(date_value: date, time_value: time) -> datetime:
    """Interpret instructor input in Singapore time and convert it to UTC."""
    local_datetime = datetime.combine(date_value, time_value, tzinfo=SINGAPORE_TIMEZONE)
    return local_datetime.astimezone(timezone.utc)


def _parse_singapore_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(SINGAPORE_TIMEZONE)


def _format_singapore_time(value: Any) -> str:
    """Show a backend UTC timestamp in Singapore time, matching the create form."""
    if not isinstance(value, str) or not value:
        return "N/A"
    try:
        parsed = _parse_singapore_datetime(value)
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%d %H:%M SGT")


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_date_bound(value: date, *, end: bool = False) -> str:
    bound = datetime.combine(
        value + timedelta(days=1) if end else value,
        time.min,
        tzinfo=SINGAPORE_TIMEZONE,
    ).astimezone(timezone.utc)
    if end:
        bound -= timedelta(microseconds=1)
    return _utc_iso(bound)


def _build_qr_image(secret: str):
    """Render the existing QR secret locally without sending it to a third party."""
    return qrcode.make(secret)


def render() -> None:
    """Render Session Management view."""
    st.title("📅 Session Management")
    st.caption("Schedule attendance windows, monitor live sessions, project classroom QR codes, and export records.")

    token = get_token()
    user = get_current_user()
    if not token or not user:
        st.warning("Please sign in to manage sessions.")
        return
    st.caption(
        "Scheduled session times and scheduling inputs use Singapore time (SGT). "
        "Check-in timestamps are labeled UTC."
    )

    # Tabs: Active & All Sessions vs Create Session
    can_create = can_create_sessions(user)
    tabs = st.tabs(
        ["📋 All Sessions", "➕ Create New Session"]
        if can_create
        else ["📋 All Sessions"]
    )
    tab_list = tabs[0]
    tab_create = tabs[1] if can_create else None

    # -------------------------------------------------------------------------
    # TAB 1: Session Listing & Controls
    # -------------------------------------------------------------------------
    with tab_list:
        col_f1, col_f2, col_f3, col_f4 = st.columns([2, 2, 2, 1])
        with col_f1:
            status_filter = st.selectbox(
                "Filter by Status",
                options=["All", "active", "scheduled", "closed", "cancelled"],
                index=0,
            )
        with col_f2:
            ok_courses, courses_data = api_client.list_courses(token=token)
            course_map: Dict[str, Optional[str]] = {"All Courses": None}
            courses_by_id: Dict[str, Dict[str, Any]] = {}
            if ok_courses and isinstance(courses_data, dict) and "items" in courses_data:
                for c in courses_data["items"]:
                    course_map[f"{c.get('code', '')} - {c.get('name', '')}"] = c.get("id")
                    if c.get("id"):
                        courses_by_id[c["id"]] = c
            selected_course_label = st.selectbox("Filter by Course", options=list(course_map.keys()))
            filter_course_id = course_map[selected_course_label]

        with col_f3:
            instructor_id = st.text_input(
                "Instructor ID",
                placeholder="Optional instructor UUID",
                key="sessions_instructor_filter",
            ).strip()
        with col_f4:
            st.button("🔄 Refresh", key="btn_refresh_sessions")

        date_col1, date_col2, date_col3 = st.columns([2, 2, 1])
        with date_col1:
            start_filter = st.date_input(
                "Scheduled from (SGT)",
                value=None,
                key="sessions_start_date_filter",
            )
        with date_col2:
            end_filter = st.date_input(
                "Scheduled through (SGT)",
                value=None,
                key="sessions_end_date_filter",
            )
        with date_col3:
            st.write("")
            st.write("")

        if start_filter and end_filter and end_filter < start_filter:
            st.error("The end date must be on or after the start date.")
            return

        # Fetch sessions
        status_param = None if status_filter == "All" else status_filter
        filter_signature = (
            status_param,
            filter_course_id,
            instructor_id,
            start_filter,
            end_filter,
        )
        if st.session_state.get("sessions_filter_signature") != filter_signature:
            st.session_state["sessions_filter_signature"] = filter_signature
            st.session_state["sessions_page"] = 0
        page = st.session_state.get("sessions_page", 0)
        page_limit = 25
        with st.spinner("Loading sessions..."):
            ok, res = api_client.list_sessions(
                token=token,
                status=status_param,
                course_id=filter_course_id,
                instructor_id=instructor_id or None,
                start_date=(
                    _utc_date_bound(start_filter)
                    if start_filter
                    else None
                ),
                end_date=(
                    _utc_date_bound(end_filter, end=True)
                    if end_filter
                    else None
                ),
                limit=page_limit,
                offset=page * page_limit,
            )

        if not ok:
            st.error(f"Failed to load sessions: {res}")
            return

        sessions: List[Dict[str, Any]] = res.get("items", []) if isinstance(res, dict) else []
        total_sessions = res.get("total", len(sessions)) if isinstance(res, dict) else len(sessions)
        page_count = max(1, (total_sessions + page_limit - 1) // page_limit)
        nav_prev, nav_page, nav_next = st.columns([1, 3, 1])
        with nav_prev:
            if st.button("← Previous", disabled=page <= 0, key="sessions_prev"):
                st.session_state["sessions_page"] = page - 1
                st.rerun()
        with nav_page:
            st.caption(
                f"Page {page + 1} of {page_count} · {total_sessions} sessions"
            )
        with nav_next:
            if st.button(
                "Next →",
                disabled=page + 1 >= page_count,
                key="sessions_next",
            ):
                st.session_state["sessions_page"] = page + 1
                st.rerun()

        if not sessions:
            st.info("No sessions found matching the filters.")
        else:
            st.write(f"Showing **{len(sessions)}** session(s) on this page:")

            for s in sessions:
                session_id = s.get("id", "")
                name = s.get("name", "Untitled")
                course_code = s.get("course_code") or "Course"
                status = s.get("status", "scheduled").lower()
                can_manage = can_manage_session(
                    user, s, courses_by_id.get(s.get("course_id"))
                )
                scheduled_start = _format_singapore_time(s.get("scheduled_start"))
                scheduled_end = _format_singapore_time(s.get("scheduled_end"))
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

                with st.expander(
                    f"**{course_code}: {name}** — {status_badge} "
                    f"({scheduled_start})",
                    expanded=(status == "active"),
                ):
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
                        opens_at = s.get("checkin_opens_at")
                        closes_at = s.get("checkin_closes_at")
                        st.markdown(
                            "**Check-in Window:** "
                            f"{opens_at[:16].replace('T', ' ') if opens_at else 'N/A'} — "
                            f"{closes_at[:16].replace('T', ' ') if closes_at else 'N/A'} UTC"
                        )
                        st.markdown(f"**Risk Cutoff:** {s.get('risk_threshold', 0.5)}")
                        liveness_req = "Yes" if s.get("require_liveness_check") else "No"
                        st.markdown(f"**Liveness Required:** {liveness_req}")

                    with col_info3:
                        st.markdown(f"**Enrolled:** {enrolled} students")
                        st.markdown(f"**Checked In:** {checked_in} students")
                        if enrolled > 0:
                            pct = (checked_in / enrolled) * 100
                            st.progress(min(pct / 100, 1.0), text=f"Attendance: {pct:.1f}%")

                    analytics_key = (
                        f"session_analytics_{sha256(token.encode('utf-8')).hexdigest()}_"
                        f"{session_id}"
                    )
                    with st.expander("📊 Session attendance analytics"):
                        if st.button(
                            "Refresh session analytics"
                            if analytics_key in st.session_state
                            else "Load session analytics",
                            key=f"session_analytics_button_{session_id}",
                        ):
                            with st.spinner("Loading session analytics..."):
                                ok_analytics, analytics_data = (
                                    api_client.get_session_stats(token, session_id)
                                )
                            if ok_analytics and isinstance(analytics_data, dict):
                                st.session_state[analytics_key] = analytics_data
                            else:
                                st.error(f"Unable to load session analytics: {analytics_data}")

                        analytics_data = st.session_state.get(analytics_key)
                        if isinstance(analytics_data, dict):
                            metric_columns = st.columns(4)
                            with metric_columns[0]:
                                st.metric(
                                    "Attendance rate",
                                    f"{analytics_data.get('attendance_rate', 0) * 100:.1f}%",
                                )
                            with metric_columns[1]:
                                st.metric(
                                    "Approved",
                                    analytics_data.get("approved_count", "Unavailable"),
                                )
                            with metric_columns[2]:
                                st.metric(
                                    "Flagged / appealed",
                                    analytics_data.get("flagged_count", 0)
                                    + analytics_data.get("appealed_count", 0),
                                )
                            with metric_columns[3]:
                                st.metric(
                                    "Average risk",
                                    f"{analytics_data.get('average_risk_score', 0):.2f}",
                                )
                            st.caption(
                                f"Rejected: {analytics_data.get('rejected_count', 'Unavailable')} · "
                                f"Pending: {analytics_data.get('pending_count', 'Unavailable')}"
                            )
                            status_counts = analytics_data.get("by_status", {})
                            if isinstance(status_counts, dict) and status_counts:
                                st.dataframe(
                                    pd.DataFrame(
                                        [
                                            {"Status": status.title(), "Check-ins": count}
                                            for status, count in status_counts.items()
                                        ]
                                    ),
                                    use_container_width=True,
                                    hide_index=True,
                                )
                            risk_distribution = analytics_data.get(
                                "risk_distribution", {}
                            )
                            if isinstance(risk_distribution, dict) and risk_distribution:
                                st.bar_chart(
                                    pd.DataFrame(
                                        [
                                            {"Risk category": category.title(), "Count": count}
                                            for category, count in risk_distribution.items()
                                        ]
                                    ),
                                    x="Risk category",
                                    y="Count",
                                )

                    st.markdown("---")

                    if can_manage and status == "scheduled":
                        with st.expander("✏️ Edit session details"):
                            start_dt = _parse_singapore_datetime(
                                s["scheduled_start"]
                            )
                            end_dt = _parse_singapore_datetime(s["scheduled_end"])
                            open_dt = _parse_singapore_datetime(
                                s["checkin_opens_at"]
                            )
                            close_dt = _parse_singapore_datetime(
                                s["checkin_closes_at"]
                            )
                            with st.form(f"edit_session_{session_id}"):
                                edit_name = st.text_input(
                                    "Session title",
                                    value=name,
                                    key=f"edit_name_{session_id}",
                                )
                                edit_type = st.selectbox(
                                    "Session type",
                                    options=["lecture", "tutorial", "lab", "exam"],
                                    index=(
                                        ["lecture", "tutorial", "lab", "exam"].index(
                                            s.get("session_type", "lecture")
                                        )
                                        if s.get("session_type")
                                        in ["lecture", "tutorial", "lab", "exam"]
                                        else 0
                                    ),
                                    key=f"edit_type_{session_id}",
                                )
                                edit_description = st.text_area(
                                    "Description",
                                    value=s.get("description") or "",
                                    key=f"edit_description_{session_id}",
                                )

                                edit_start_col, edit_end_col = st.columns(2)
                                with edit_start_col:
                                    edit_start_date = st.date_input(
                                        "Scheduled start date",
                                        value=start_dt.date(),
                                        key=f"edit_start_date_{session_id}",
                                    )
                                    edit_start_time = st.time_input(
                                        "Scheduled start time",
                                        value=start_dt.time().replace(tzinfo=None),
                                        key=f"edit_start_time_{session_id}",
                                    )
                                with edit_end_col:
                                    edit_end_date = st.date_input(
                                        "Scheduled end date",
                                        value=end_dt.date(),
                                        key=f"edit_end_date_{session_id}",
                                    )
                                    edit_end_time = st.time_input(
                                        "Scheduled end time",
                                        value=end_dt.time().replace(tzinfo=None),
                                        key=f"edit_end_time_{session_id}",
                                    )

                                edit_open_col, edit_close_col = st.columns(2)
                                with edit_open_col:
                                    edit_open_date = st.date_input(
                                        "Check-in opens date",
                                        value=open_dt.date(),
                                        key=f"edit_open_date_{session_id}",
                                    )
                                    edit_open_time = st.time_input(
                                        "Check-in opens time",
                                        value=open_dt.time().replace(tzinfo=None),
                                        key=f"edit_open_time_{session_id}",
                                    )
                                with edit_close_col:
                                    edit_close_date = st.date_input(
                                        "Check-in closes date",
                                        value=close_dt.date(),
                                        key=f"edit_close_date_{session_id}",
                                    )
                                    edit_close_time = st.time_input(
                                        "Check-in closes time",
                                        value=close_dt.time().replace(tzinfo=None),
                                        key=f"edit_close_time_{session_id}",
                                    )

                                edit_venue = st.text_input(
                                    "Venue",
                                    value=s.get("venue_name") or "",
                                    key=f"edit_venue_{session_id}",
                                )
                                edit_geo_col1, edit_geo_col2, edit_geo_col3 = st.columns(3)
                                with edit_geo_col1:
                                    edit_latitude = st.number_input(
                                        "Venue latitude",
                                        min_value=-90.0,
                                        max_value=90.0,
                                        value=float(s.get("venue_latitude") or 0.0),
                                        format="%.6f",
                                        key=f"edit_latitude_{session_id}",
                                    )
                                with edit_geo_col2:
                                    edit_longitude = st.number_input(
                                        "Venue longitude",
                                        min_value=-180.0,
                                        max_value=180.0,
                                        value=float(s.get("venue_longitude") or 0.0),
                                        format="%.6f",
                                        key=f"edit_longitude_{session_id}",
                                    )
                                with edit_geo_col3:
                                    edit_radius = st.number_input(
                                        "Geofence radius (m)",
                                        min_value=1.0,
                                        max_value=100_000.0,
                                        value=float(
                                            s.get("geofence_radius_meters") or 50.0
                                        ),
                                        key=f"edit_radius_{session_id}",
                                    )
                                edit_risk = st.slider(
                                    "Risk flagging threshold",
                                    min_value=0.0,
                                    max_value=1.0,
                                    value=float(
                                        s.get("risk_threshold")
                                        if s.get("risk_threshold") is not None
                                        else 0.5
                                    ),
                                    step=0.05,
                                    key=f"edit_risk_{session_id}",
                                )
                                edit_liveness = st.checkbox(
                                    "Require liveness check",
                                    value=bool(s.get("require_liveness_check")),
                                    key=f"edit_liveness_{session_id}",
                                )
                                edit_face = st.checkbox(
                                    "Require face verification",
                                    value=bool(s.get("require_face_match")),
                                    key=f"edit_face_{session_id}",
                                )
                                save_edit = st.form_submit_button(
                                    "Save session changes",
                                    type="primary",
                                )

                            if save_edit:
                                edited_start = _scheduled_time_utc(
                                    edit_start_date, edit_start_time
                                )
                                edited_end = _scheduled_time_utc(
                                    edit_end_date, edit_end_time
                                )
                                edited_open = _scheduled_time_utc(
                                    edit_open_date, edit_open_time
                                )
                                edited_close = _scheduled_time_utc(
                                    edit_close_date, edit_close_time
                                )
                                if not edit_name.strip():
                                    st.error("Please provide a session title.")
                                elif edited_start <= datetime.now(timezone.utc):
                                    st.error("Scheduled start time must be in the future.")
                                elif edited_end <= edited_start:
                                    st.error(
                                        "Scheduled end time must be after scheduled start time."
                                    )
                                elif edited_close <= edited_open:
                                    st.error(
                                        "Check-in close time must be after check-in open time."
                                    )
                                else:
                                    edit_payload = {
                                        "name": edit_name.strip(),
                                        "session_type": edit_type,
                                        "description": edit_description.strip() or None,
                                        "scheduled_start": _utc_iso(edited_start),
                                        "scheduled_end": _utc_iso(edited_end),
                                        "checkin_opens_at": _utc_iso(edited_open),
                                        "checkin_closes_at": _utc_iso(edited_close),
                                        "venue_name": edit_venue.strip() or None,
                                        "venue_latitude": edit_latitude,
                                        "venue_longitude": edit_longitude,
                                        "geofence_radius_meters": edit_radius,
                                        "risk_threshold": edit_risk,
                                        "require_liveness_check": edit_liveness,
                                        "require_face_match": edit_face,
                                    }
                                    with st.spinner("Saving session changes..."):
                                        ok_edit, edit_result = api_client.update_session(
                                            token, session_id, edit_payload
                                        )
                                    if ok_edit:
                                        set_flash_message("Session updated successfully.")
                                        st.rerun()
                                    else:
                                        st.error(f"Failed to update session: {edit_result}")

                    # Control Actions Row
                    btn_col1, btn_col2, btn_col3, btn_col4 = st.columns([2, 2, 2, 2])

                    with btn_col1:
                        if can_manage and status == "scheduled":
                            if st.button("▶️ Start Session", key=f"start_{session_id}", type="primary"):
                                ok_update, update_res = api_client.update_session(
                                    token, session_id, {"status": "active"}
                                )
                                if ok_update:
                                    set_flash_message("Session activated! Check-in is now open.")
                                    st.rerun()
                                else:
                                    st.error(f"Error: {update_res}")
                        elif can_manage and status == "active":
                            if st.button("⏹️ Close Session", key=f"close_{session_id}"):
                                ok_update, update_res = api_client.update_session(
                                    token, session_id, {"status": "closed"}
                                )
                                if ok_update:
                                    set_flash_message("Session closed.")
                                    st.rerun()
                                else:
                                    st.error(f"Error: {update_res}")
                        if can_manage and status in {"scheduled", "active", "closed"}:
                            confirm_cancel = st.checkbox(
                                "Confirm cancellation",
                                key=f"confirm_cancel_{session_id}",
                            )
                            if st.button(
                                "Cancel Session",
                                key=f"cancel_{session_id}",
                                disabled=not confirm_cancel,
                            ):
                                ok_cancel, cancel_res = api_client.update_session(
                                    token, session_id, {"status": "cancelled"}
                                )
                                if ok_cancel:
                                    set_flash_message("Session cancelled.", level="warning")
                                    st.rerun()
                                else:
                                    st.error(f"Failed to cancel session: {cancel_res}")

                    # Classroom QR Code Projector (the backend lets only session owners issue QR codes)
                    qr_key = f"qr_open_{session_id}"
                    with btn_col2:
                        if can_manage and st.button("📱 Classroom QR Mode", key=f"btn_qr_{session_id}"):
                            st.session_state[qr_key] = not st.session_state.get(qr_key, False)

                    with btn_col3:
                        csv_col, json_col = st.columns(2)
                        with csv_col:
                            render_csv_download(
                                token=token,
                                cache_key=f"session_{session_id}",
                                request_label="📥 Export CSV",
                                download_label="Download CSV",
                                file_name=f"attendance_{course_code}_{name}.csv",
                                export=lambda: api_client.export_session_csv(token, session_id),
                            )
                        with json_col:
                            render_json_download(
                                token=token,
                                cache_key=f"session_{session_id}",
                                request_label="📥 Export JSON",
                                download_label="Download JSON",
                                file_name=f"attendance_{course_code}_{name}.json",
                                export=lambda: api_client.export_session_json(token, session_id),
                            )

                    with btn_col4:
                        if can_manage and status == "scheduled":
                            confirm_delete = st.checkbox(
                                "Confirm deletion",
                                key=f"confirm_delete_{session_id}",
                            )
                            if st.button(
                                "🗑️ Delete Session",
                                key=f"del_{session_id}",
                                disabled=not confirm_delete,
                            ):
                                ok_del, del_res = api_client.delete_session(token, session_id)
                                if ok_del:
                                    set_flash_message("Session deleted.")
                                    st.rerun()
                                else:
                                    st.error(f"Error: {del_res}")

                    # Classroom QR Display Section
                    if can_manage and st.session_state.get(qr_key, False):
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
                                ok_clear, clear_res = api_client.clear_session_qr(token, session_id)
                                if ok_clear:
                                    st.session_state.pop(f"qr_data_{session_id}", None)
                                    set_flash_message("QR code cleared.", level="info")
                                    st.rerun()
                                else:
                                    st.error(f"Error: {clear_res}")

                        with c_qr2:
                            current_qr = st.session_state.get(f"qr_data_{session_id}")
                            if current_qr:
                                qr_secret = current_qr.get("qr_code", "")
                                expires_at = current_qr.get("expires_at", "")[:19].replace("T", " ")
                                ttl = current_qr.get("ttl_seconds", 180)

                                st.image(
                                    _build_qr_image(qr_secret),
                                    caption="Scan using the SAIV Student App",
                                    width=220,
                                )
                                st.markdown(f"**Token:** `{qr_secret}`")
                                st.markdown(f"**Expires At:** `{expires_at} UTC` (TTL: {ttl}s)")
                            else:
                                st.info("Click 'Generate / Rotate QR' above to issue a one-time secret.")

                    checkins_state_key = (
                        f"session_checkins_{sha256(token.encode('utf-8')).hexdigest()}_{session_id}"
                    )
                    with st.expander("View session check-ins"):
                        has_checkins = checkins_state_key in st.session_state
                        if st.button(
                            "🔄 Refresh check-ins" if has_checkins else "📋 Load check-ins",
                            key=f"load_checkins_{session_id}",
                        ):
                            st.session_state.pop(checkins_state_key, None)
                            with st.spinner("Loading session check-ins..."):
                                ok_checkins, checkin_res = api_client.get_session_checkins(
                                    token, session_id
                                )
                            if not ok_checkins:
                                st.error(f"Failed to load session check-ins: {checkin_res}")
                            elif not isinstance(checkin_res, list):
                                st.error("Failed to load session check-ins: invalid response format.")
                            else:
                                st.session_state[checkins_state_key] = checkin_res

                        if checkins_state_key in st.session_state:
                            checkins = st.session_state[checkins_state_key]
                            if not checkins:
                                st.info("No check-ins recorded for this session.")
                            else:
                                checkin_rows = []
                                for checkin in checkins:
                                    distance = checkin.get("distance_from_venue_meters")
                                    risk_score = checkin.get("risk_score")
                                    checkin_rows.append(
                                        {
                                            "Student": checkin.get("student_name") or "N/A",
                                            "Email": checkin.get("student_email") or "N/A",
                                            "Status": checkin.get("status", "N/A").upper(),
                                            "Risk Score": (
                                                f"{risk_score:.2f}"
                                                if isinstance(risk_score, (int, float))
                                                else "N/A"
                                            ),
                                            "Distance": (
                                                f"{distance:.1f}m"
                                                if isinstance(distance, (int, float))
                                                else "N/A"
                                            ),
                                            "Checked In At (UTC)": checkin.get(
                                                "checked_in_at", ""
                                            )[:19].replace("T", " "),
                                            "Liveness": (
                                                "Passed"
                                                if checkin.get("liveness_passed") is True
                                                else "Failed"
                                                if checkin.get("liveness_passed") is False
                                                else "N/A"
                                            ),
                                            "Trusted Device": (
                                                "Yes"
                                                if checkin.get("device_trusted") is True
                                                else "No"
                                                if checkin.get("device_trusted") is False
                                                else "N/A"
                                            ),
                                        }
                                    )
                                st.dataframe(
                                    pd.DataFrame(checkin_rows),
                                    use_container_width=True,
                                    hide_index=True,
                                )

    # -------------------------------------------------------------------------
    # TAB 2: Create New Session
    # -------------------------------------------------------------------------
    if tab_create is None:
        return

    with tab_create:
        st.subheader("Schedule an Attendance Session")
        st.caption(
            "Define the course, timing, geofence, and security thresholds. "
            "Schedule inputs use Singapore time (SGT); the backend stores UTC."
        )

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
                    options=["lecture", "tutorial", "lab", "exam"],
                    index=0,
                )

            session_name = st.text_input(
                "Session Title *",
                value=f"{selected_course.get('code', 'Course')} Session",
                placeholder="e.g. Week 3: Deep Neural Networks",
            )
            session_desc = st.text_area("Description (Optional)", placeholder="Overview of lecture topics...")

            st.markdown("#### Schedule & Timing")
            st.caption("Times are in Singapore time (SGT, UTC+8).")
            col_d1, col_d2 = st.columns(2)
            now_singapore = datetime.now(SINGAPORE_TIMEZONE)
            start_default = now_singapore + timedelta(minutes=5)
            end_default = start_default + timedelta(hours=2)

            with col_d1:
                date_val = st.date_input(
                    "Scheduled Start Date (SGT) *",
                    value=start_default.date(),
                )
                start_t = st.time_input(
                    "Scheduled Start (SGT) *",
                    value=start_default.time().replace(tzinfo=None),
                )
            with col_d2:
                end_date_val = st.date_input(
                    "Scheduled End Date (SGT) *",
                    value=end_default.date(),
                )
                end_t = st.time_input(
                    "Scheduled End (SGT) *",
                    value=end_default.time().replace(tzinfo=None),
                )

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
                    value=min(
                        500,
                        max(
                            10,
                            int(selected_course.get("geofence_radius_meters") or 50),
                        ),
                    ),
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

            window_col1, window_col2 = st.columns(2)
            with window_col1:
                checkin_opens_before = st.number_input(
                    "Open check-in (minutes before start)",
                    min_value=0,
                    max_value=180,
                    value=15,
                    step=5,
                )
            with window_col2:
                checkin_closes_after = st.number_input(
                    "Close check-in (minutes after start)",
                    min_value=1,
                    max_value=360,
                    value=30,
                    step=5,
                )

            submitted = st.form_submit_button("Create Session", type="primary", use_container_width=True)

        if submitted:
            if not session_name.strip():
                st.error("Please provide a session title.")
                return

            dt_start = _scheduled_time_utc(date_val, start_t)
            dt_end = _scheduled_time_utc(end_date_val, end_t)

            if dt_start <= datetime.now(timezone.utc):
                st.error("Scheduled start time must be in the future.")
                return
            if dt_end <= dt_start:
                st.error("Scheduled end time must be after scheduled start time.")
                return
            checkin_opens_at = dt_start - timedelta(minutes=checkin_opens_before)
            checkin_closes_at = dt_start + timedelta(minutes=checkin_closes_after)

            payload = {
                "course_id": selected_course["id"],
                "name": session_name.strip(),
                "session_type": session_type,
                "description": session_desc.strip() if session_desc else None,
                "scheduled_start": dt_start.isoformat().replace("+00:00", "Z"),
                "scheduled_end": dt_end.isoformat().replace("+00:00", "Z"),
                "checkin_opens_at": _utc_iso(checkin_opens_at),
                "checkin_closes_at": _utc_iso(checkin_closes_at),
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
                set_flash_message(f"Session '{session_name}' created successfully!")
                st.rerun()
            else:
                detail = create_res.get("detail", create_res) if isinstance(create_res, dict) else str(create_res)
                st.error(f"Failed to create session: {detail}")
