"""
Review Queue View - Review, investigate, and approve or reject flagged & appealed check-ins.
"""

from typing import Any, Dict, List
import streamlit as st

from app.api_client import api_client
from app.auth import get_token


def render() -> None:
    """Render the Flagged & Appealed Check-ins Review Queue."""
    st.title("🚨 Flagged Check-ins Review Queue")
    st.caption("Review suspicious check-ins flagged by multi-signal risk heuristics, or student appeals.")

    token = get_token()
    if not token:
        st.warning("Please sign in to access the review queue.")
        return

    # Filter controls
    col_f1, col_f2, col_btn = st.columns([2, 2, 1])
    with col_f1:
        ok_courses, courses_data = api_client.list_courses(token=token)
        course_map = {"All Courses": None}
        if ok_courses and isinstance(courses_data, dict) and "items" in courses_data:
            for c in courses_data["items"]:
                course_map[f"{c.get('code')} - {c.get('name')}"] = c.get("id")
        selected_course_label = st.selectbox("Filter by Course", options=list(course_map.keys()), key="rq_course_filter")
        course_filter_id = course_map[selected_course_label]

    with col_btn:
        st.write("")
        st.write("")
        st.button("🔄 Refresh Queue", key="btn_refresh_queue")

    with st.spinner("Loading review queue..."):
        ok, res = api_client.get_flagged_checkins(
            token=token,
            course_id=course_filter_id,
            limit=100,
        )

    if not ok:
        st.error(f"Failed to load flagged check-ins: {res}")
        return

    items: List[Dict[str, Any]] = res.get("items", []) if isinstance(res, dict) else []

    if not items:
        st.success("🎉 All clear! There are currently no flagged or appealed check-ins requiring review.")
        return

    st.markdown(f"Found **{len(items)}** check-in(s) requiring your decision:")

    for item in items:
        checkin_id = item.get("id", "")
        student_name = item.get("student_name") or item.get("student_email") or "Student"
        student_email = item.get("student_email", "")
        course_code = item.get("course_code") or "Course"
        session_name = item.get("session_name") or "Session"
        status = item.get("status", "flagged").lower()
        risk_score = item.get("risk_score", 0.0)
        timestamp = item.get("checked_in_at", "")[:19].replace("T", " ")
        distance = item.get("distance_from_venue_meters")
        liveness_passed = item.get("liveness_passed")
        device_trusted = item.get("device_trusted")
        appeal_reason = item.get("appeal_reason")
        appealed_at = item.get("appealed_at", "")[:19].replace("T", " ") if item.get("appealed_at") else None
        risk_factors = item.get("risk_factors", [])

        # Color badges
        badge_text = "🚨 FLAGGED" if status == "flagged" else "📩 UNDER APPEAL"
        border_color = "#EF4444" if status == "flagged" else "#F59E0B"

        with st.container(border=True):
            head_col1, head_col2 = st.columns([3, 1])
            with head_col1:
                st.markdown(
                    f"### {student_name} (`{student_email}`) — <span style='color:{border_color}; font-size:1.1rem; font-weight:700;'>{badge_text}</span>",
                    unsafe_allow_html=True,
                )
                st.caption(f"Course: **{course_code}** | Session: **{session_name}** | Time: **{timestamp} UTC**")

            with head_col2:
                risk_pct = risk_score * 100
                st.metric(label="Risk Score", value=f"{risk_score:.2f}", delta=f"{risk_pct:.0f}% Risk", delta_color="inverse")

            # Risk Signals Breakdown
            st.markdown("##### 🔍 Detected Risk Signals:")
            sig_col1, sig_col2, sig_col3, sig_col4 = st.columns(4)

            with sig_col1:
                dist_str = f"{distance:.1f} m" if distance is not None else "Unknown"
                st.markdown(f"**GPS Distance:** {dist_str}")
            with sig_col2:
                live_str = "✅ Passed" if liveness_passed is True else ("❌ Failed" if liveness_passed is False else "⚪ Not Checked")
                st.markdown(f"**Liveness:** {live_str}")
            with sig_col3:
                dev_str = "✅ Trusted" if device_trusted is True else ("⚠️ Untrusted" if device_trusted is False else "⚪ Unknown")
                st.markdown(f"**Device Binding:** {dev_str}")
            with sig_col4:
                st.markdown(f"**Triggered Factors:** {len(risk_factors)}")

            if risk_factors:
                st.markdown("**Factor Details:**")
                for rf in risk_factors:
                    rf_type = rf.get("type", "Signal").replace("_", " ").title()
                    rf_score = rf.get("score", 0.0)
                    rf_desc = rf.get("description") or rf.get("details") or ""
                    st.markdown(f"- **{rf_type}** (Score: `{rf_score:.2f}`): {rf_desc}")

            # Appeal Reason (if under appeal)
            if appeal_reason:
                st.info(f"**Student's Appeal Explanation ({appealed_at} UTC):**\n\n> {appeal_reason}", icon="📝")

            st.markdown("---")

            # Decision Action Form
            rev_col1, rev_col2, rev_col3 = st.columns([3, 1, 1])

            with rev_col1:
                notes_key = f"notes_{checkin_id}"
                review_notes = st.text_input(
                    "Review Decision Notes (Optional)",
                    key=notes_key,
                    placeholder="e.g. Verified classroom presence in lecture recording",
                )

            with rev_col2:
                st.write("")
                st.write("")
                if st.button("✅ Approve", key=f"app_{checkin_id}", type="primary", use_container_width=True):
                    with st.spinner("Approving check-in..."):
                        ok_rev, rev_res = api_client.review_checkin(
                            token=token,
                            checkin_id=checkin_id,
                            status="approved",
                            review_notes=review_notes.strip() if review_notes else None,
                        )
                    if ok_rev:
                        st.success(f"Check-in for {student_name} has been APPROVED.")
                        st.rerun()
                    else:
                        st.error(f"Error: {rev_res}")

            with rev_col3:
                st.write("")
                st.write("")
                if st.button("❌ Reject", key=f"rej_{checkin_id}", use_container_width=True):
                    with st.spinner("Rejecting check-in..."):
                        ok_rev, rev_res = api_client.review_checkin(
                            token=token,
                            checkin_id=checkin_id,
                            status="rejected",
                            review_notes=review_notes.strip() if review_notes else None,
                        )
                    if ok_rev:
                        st.warning(f"Check-in for {student_name} has been marked REJECTED.")
                        st.rerun()
                    else:
                        st.error(f"Error: {rev_res}")

