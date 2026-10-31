"""
Check-in Explorer View - Comprehensive search, filtering, and audit inspection of all attendance records.
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional
import pandas as pd
import streamlit as st

from app.api_client import api_client
from app.auth import get_current_user, get_token
from app.rbac import Permission, require_permission


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
    """Render Check-in Explorer view."""
    if not require_permission(
        get_current_user(), Permission.VIEW_CHECKIN_EXPLORER
    ):
        return
    st.title("📋 Check-in Explorer")
    st.caption("Search, filter, and inspect detailed multi-signal verification records across all courses.")

    token = get_token()
    if not token:
        st.warning("Please sign in to view check-ins.")
        return

    target_checkin_id = st.session_state.get("checkin_target_id")
    if isinstance(target_checkin_id, str) and target_checkin_id:
        st.subheader("Selected recent check-in")
        with st.spinner("Loading selected check-in details..."):
            ok_target, target_data = api_client.get_checkin(
                token, target_checkin_id
            )
        if not ok_target:
            st.error(f"Unable to load selected check-in: {target_data}")
        elif isinstance(target_data, dict):
            with st.container(border=True):
                st.write(
                    f"**{target_data.get('student_name') or target_data.get('student_id', 'Student')}** · "
                    f"{str(target_data.get('status') or 'Unknown').upper()} · "
                    f"Risk {target_data.get('risk_score', 'N/A')}"
                )
                st.json(target_data)
        else:
            st.error("Unable to load selected check-in: invalid response format.")
        if st.button("Dismiss selected check-in", key="dismiss_target_checkin"):
            st.session_state.pop("checkin_target_id", None)
            st.rerun()

    # -------------------------------------------------------------------------
    # Filters Bar
    # -------------------------------------------------------------------------
    with st.expander("🔍 Filter & Search Criteria", expanded=True):
        col_f1, col_f2, col_f3 = st.columns(3)

        with col_f1:
            ok_courses, courses_data = api_client.list_courses(token=token)
            course_map: Dict[str, Optional[str]] = {"All Courses": None}
            if not ok_courses:
                st.error(f"Unable to load course filters: {courses_data}")
            elif (
                not isinstance(courses_data, dict)
                or not isinstance(courses_data.get("items"), list)
            ):
                st.error("Unable to load course filters: invalid response format.")
            else:
                for c in courses_data["items"]:
                    if not isinstance(c, dict):
                        continue
                    course_map[f"{c.get('code')} - {c.get('name')}"] = c.get("id")
            selected_course_label = st.selectbox("Course", options=list(course_map.keys()), key="ci_course")
            course_filter = course_map[selected_course_label]

        with col_f2:
            status_filter = st.selectbox(
                "Verification Status",
                options=["All", "approved", "flagged", "rejected", "appealed", "pending"],
                index=0,
                key="ci_status",
            )
            status_param = None if status_filter == "All" else status_filter

        with col_f3:
            page_limit = st.selectbox("Records per Page", options=[25, 50, 100], index=1)

        session_options: Dict[str, Optional[str]] = {"All Sessions": None}
        ok_sessions, session_response = api_client.list_sessions(
            token=token,
            course_id=course_filter,
            limit=100,
        )
        if ok_sessions and isinstance(session_response, dict):
            session_items = session_response.get("items")
            if not isinstance(session_items, list):
                st.error("Unable to load sessions for filtering: invalid response format.")
                session_items = []
            for session in session_items:
                if not isinstance(session, dict):
                    continue
                label = (
                    f"{session.get('name', 'Session')} · "
                    f"{session.get('scheduled_start', '')[:10]}"
                )
                session_options[label] = session.get("id")
        elif not ok_sessions:
            st.error(f"Unable to load sessions for filtering: {session_response}")
        else:
            st.error("Unable to load sessions for filtering: invalid response format.")
        selected_session_label = st.selectbox(
            "Session",
            options=list(session_options.keys()),
            key=f"ci_session_{course_filter or 'all'}",
        )
        session_filter = session_options[selected_session_label]

        col_r1, col_r2, col_r3, col_r4 = st.columns(4)
        with col_r1:
            risk_range = st.slider(
                "Risk Score Range",
                min_value=0.0,
                max_value=1.0,
                value=(0.0, 1.0),
                step=0.05,
                key="ci_risk_slider",
            )
        with col_r2:
            student_search = st.text_input("Filter by Student ID (Optional)", placeholder="UUID of student")
        with col_r3:
            start_filter = st.date_input(
                "Checked in from (UTC)",
                value=None,
                key="ci_start_date",
            )
        with col_r4:
            end_filter = st.date_input(
                "Checked in through (UTC)",
                value=None,
                key="ci_end_date",
            )

    if start_filter and end_filter and end_filter < start_filter:
        st.error("The end date must be on or after the start date.")
        return

    filter_signature = (
        course_filter,
        status_param,
        session_filter,
        risk_range,
        student_search.strip() if student_search else None,
        start_filter,
        end_filter,
        page_limit,
    )
    if st.session_state.get("checkins_filter_signature") != filter_signature:
        st.session_state["checkins_filter_signature"] = filter_signature
        st.session_state["checkins_page"] = 0
    page = st.session_state.get("checkins_page", 0)

    # Fetch check-ins
    with st.spinner("Fetching attendance records..."):
        ok, res = api_client.list_checkins(
            token=token,
            course_id=course_filter,
            session_id=session_filter,
            student_id=student_search.strip() if student_search else None,
            status=status_param,
            min_risk=risk_range[0],
            max_risk=risk_range[1],
            limit=page_limit,
            offset=page * page_limit,
            start_date=_utc_date_bound(start_filter) if start_filter else None,
            end_date=_utc_date_bound(end_filter, end=True) if end_filter else None,
        )

    if not ok:
        st.error(f"Failed to fetch check-ins: {res}")
        return

    if not isinstance(res, dict) or not isinstance(res.get("items"), list):
        st.error("Failed to fetch check-ins: invalid response format.")
        return
    items = res["items"]
    total = res.get("total")
    if (
        not isinstance(total, int)
        or isinstance(total, bool)
        or total < 0
        or any(not isinstance(item, dict) for item in items)
    ):
        st.error("Failed to fetch check-ins: invalid response data.")
        return
    page_count = max(1, (total + page_limit - 1) // page_limit)
    nav_prev, nav_page, nav_next = st.columns([1, 3, 1])
    with nav_prev:
        if st.button("← Previous", disabled=page <= 0, key="checkins_prev"):
            st.session_state["checkins_page"] = page - 1
            st.rerun()
    with nav_page:
        st.caption(f"Page {page + 1} of {page_count}")
    with nav_next:
        if st.button(
            "Next →",
            disabled=page + 1 >= page_count,
            key="checkins_next",
        ):
            st.session_state["checkins_page"] = page + 1
            st.rerun()

    st.write(f"Showing **{len(items)}** of **{total}** total record(s):")

    if not items:
        st.info("No check-ins matched your filter criteria.")
        return

    # Render tabular summary
    table_rows = []
    for c in items:
        table_rows.append(
            {
                "ID": c.get("id", "")[:8],
                "Student": c.get("student_name") or c.get("student_email", "N/A"),
                "Email": c.get("student_email", "N/A"),
                "Course": c.get("course_code", "N/A"),
                "Session": c.get("session_name", "N/A"),
                "Status": c.get("status", "").upper(),
                "Risk": f"{c.get('risk_score', 0.0):.2f}",
                "Distance": f"{c.get('distance_from_venue_meters', 0.0):.1f}m"
                if c.get("distance_from_venue_meters") is not None
                else "N/A",
                "Timestamp (UTC)": c.get("checked_in_at", "")[:19].replace("T", " "),
            }
        )

    df_ci = pd.DataFrame(table_rows)
    st.dataframe(df_ci, use_container_width=True, hide_index=True)

    # Detailed Inspection on selected check-in
    st.markdown("---")
    st.subheader("🔬 Check-in Signal Inspection")
    selected_idx = st.selectbox(
        "Select a record to inspect verification signals:",
        options=range(len(items)),
        format_func=lambda i: f"#{items[i].get('id', '')[:8]} - {items[i].get('student_name') or items[i].get('student_email')} - {items[i].get('status', '').upper()}",
    )

    if items:
        selected_item = items[selected_idx]
        cid = selected_item.get("id")

        with st.spinner("Fetching full risk breakdown..."):
            ok_detail, full_detail = api_client.get_checkin(token, cid)

        detail_data = full_detail if ok_detail and isinstance(full_detail, dict) else selected_item

        with st.container(border=True):
            d1, d2, d3 = st.columns(3)
            with d1:
                st.markdown(f"**Check-in ID:** `{detail_data.get('id')}`")
                st.markdown(f"**Student ID:** `{detail_data.get('student_id')}`")
                st.markdown(f"**Session ID:** `{detail_data.get('session_id')}`")
            with d2:
                st.markdown(f"**Status:** `{detail_data.get('status', '').upper()}`")
                st.markdown(f"**Risk Score:** `{detail_data.get('risk_score', 0.0):.4f}`")
                st.markdown(f"**Timestamp:** `{detail_data.get('checked_in_at')}`")
            with d3:
                dist = detail_data.get("distance_from_venue_meters")
                st.markdown(f"**Distance from Venue:** `{f'{dist:.1f} m' if dist is not None else 'N/A'}`")
                liveness = detail_data.get("liveness_passed")
                st.markdown(f"**Liveness Passed:** `{liveness}`")
                st.markdown(
                    f"**Liveness Score:** `{detail_data.get('liveness_score') if detail_data.get('liveness_score') is not None else 'N/A'}`"
                )
                st.markdown(
                    f"**Face Match:** `{detail_data.get('face_match_passed') if detail_data.get('face_match_passed') is not None else 'N/A'}`"
                )
                st.markdown(
                    f"**Face Match Score:** `{detail_data.get('face_match_score') if detail_data.get('face_match_score') is not None else 'N/A'}`"
                )
                device_trusted = detail_data.get("device_trusted")
                st.markdown(f"**Device Trusted:** `{device_trusted}`")
                latitude = detail_data.get("latitude")
                longitude = detail_data.get("longitude")
                st.markdown(
                    f"**GPS Coordinates:** `{latitude}, {longitude}`"
                    if latitude is not None and longitude is not None
                    else "**GPS Coordinates:** `N/A`"
                )

            # Risk factors
            r_factors = detail_data.get("risk_factors", [])
            if r_factors:
                st.markdown("##### Detailed Risk Factors Evaluated:")
                for rf in r_factors:
                    st.json(rf)
            else:
                st.caption("No elevated risk factors detected.")

            # Staff Review Notes if reviewed
            if detail_data.get("reviewed_at"):
                st.info(
                    f"**Staff Review ({detail_data.get('reviewed_at')[:19].replace('T', ' ')} UTC):**\n\n"
                    f"Notes: {detail_data.get('review_notes') or 'None'}",
                    icon="ℹ️",
                )
