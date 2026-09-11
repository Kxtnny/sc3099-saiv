"""
Check-in Explorer View - Comprehensive search, filtering, and audit inspection of all attendance records.
"""

from typing import Any, Dict, List, Optional
import pandas as pd
import streamlit as st

from app.api_client import api_client
from app.auth import get_token


def render() -> None:
    """Render Check-in Explorer view."""
    st.title("📋 Check-in Explorer")
    st.caption("Search, filter, and inspect detailed multi-signal verification records across all courses.")

    token = get_token()
    if not token:
        st.warning("Please sign in to view check-ins.")
        return

    # -------------------------------------------------------------------------
    # Filters Bar
    # -------------------------------------------------------------------------
    with st.expander("🔍 Filter & Search Criteria", expanded=True):
        col_f1, col_f2, col_f3 = st.columns(3)

        with col_f1:
            ok_courses, courses_data = api_client.list_courses(token=token)
            course_map: Dict[str, Optional[str]] = {"All Courses": None}
            if ok_courses and isinstance(courses_data, dict) and "items" in courses_data:
                for c in courses_data["items"]:
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

        col_r1, col_r2 = st.columns(2)
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

    # Fetch check-ins
    with st.spinner("Fetching attendance records..."):
        ok, res = api_client.list_checkins(
            token=token,
            course_id=course_filter,
            student_id=student_search.strip() if student_search else None,
            status=status_param,
            min_risk=risk_range[0],
            max_risk=risk_range[1],
            limit=page_limit,
            offset=0,
        )

    if not ok:
        st.error(f"Failed to fetch check-ins: {res}")
        return

    items: List[Dict[str, Any]] = res.get("items", []) if isinstance(res, dict) else []
    total = res.get("total", len(items)) if isinstance(res, dict) else len(items)

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
                device_trusted = detail_data.get("device_trusted")
                st.markdown(f"**Device Trusted:** `{device_trusted}`")

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

