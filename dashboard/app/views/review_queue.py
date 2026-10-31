"""
Review Queue View - Review, investigate, and approve or reject flagged & appealed check-ins.
"""

import math
from numbers import Real
from typing import Any, Dict, List, Optional
import html

import streamlit as st

from app.api_client import api_client
from app.auth import get_current_user, get_token
from app.access import load_visible_courses
from app.rbac import Permission, require_permission
from app.views._messages import set_flash_message


def _factor_score(risk_factor: Any) -> Optional[float]:
    """Return the backend's weighted contribution when both inputs are valid."""
    if not isinstance(risk_factor, dict):
        return None

    weight = risk_factor.get("weight")
    confidence = risk_factor.get("confidence")
    if (
        isinstance(weight, bool)
        or isinstance(confidence, bool)
        or not isinstance(weight, Real)
        or not isinstance(confidence, Real)
        or not math.isfinite(weight)
        or not math.isfinite(confidence)
        or not 0 <= weight <= 1
        or not 0 <= confidence <= 1
    ):
        return None
    return float(weight * confidence)


def render() -> None:
    """Render the Flagged & Appealed Check-ins Review Queue."""
    user = get_current_user()
    if not require_permission(
        user, Permission.REVIEW_FLAGGED_CHECKINS
    ):
        return
    st.title("🚨 Flagged Check-ins Review Queue")
    st.caption("Review suspicious check-ins flagged by multi-signal risk heuristics, or student appeals.")

    token = get_token()
    if not token:
        st.warning("Please sign in to access the review queue.")
        return

    # Filter controls
    col_f1, col_f2, col_btn = st.columns([2, 2, 1])
    with col_f1:
        ok_courses, visible_courses, scope_message = load_visible_courses(
            token, user
        )
        if not ok_courses:
            st.error(scope_message or "Unable to load courses.")
            return
        course_map = {"All Courses": None} if user.get("role") == "admin" else {}
        for course in visible_courses:
            course_id = course.get("id")
            if isinstance(course_id, str) and course_id:
                course_map[
                    f"{course.get('code')} - {course.get('name')}"
                ] = course_id
        if not course_map:
            st.info(scope_message or "No assigned courses are available.")
            return
        selected_course_label = st.selectbox(
            "Filter by Course",
            options=list(course_map.keys()),
            key="rq_course_filter",
        )
        course_filter_id = course_map[selected_course_label]

    with col_btn:
        st.write("")
        st.write("")
        st.button("🔄 Refresh Queue", key="btn_refresh_queue")

    filter_signature = course_filter_id
    if st.session_state.get("review_queue_filter_signature") != filter_signature:
        st.session_state["review_queue_filter_signature"] = filter_signature
        st.session_state["review_queue_page"] = 0
    page = st.session_state.get("review_queue_page", 0)
    page_limit = 50
    with st.spinner("Loading review queue..."):
        ok, res = api_client.get_flagged_checkins(
            token=token,
            course_id=course_filter_id,
            limit=page_limit,
            offset=page * page_limit,
        )

    if not ok:
        st.error(f"Failed to load flagged check-ins: {res}")
        return

    if not isinstance(res, dict) or not isinstance(res.get("items"), list):
        st.error("Failed to load flagged check-ins: invalid response format.")
        return
    items = res["items"]
    total = res.get("total")
    if (
        not isinstance(total, int)
        or isinstance(total, bool)
        or total < 0
        or any(not isinstance(item, dict) for item in items)
    ):
        st.error("Failed to load flagged check-ins: invalid response data.")
        return
    page_count = max(1, (total + page_limit - 1) // page_limit)
    nav_prev, nav_page, nav_next = st.columns([1, 3, 1])
    with nav_prev:
        if st.button("← Previous", disabled=page <= 0, key="review_prev"):
            st.session_state["review_queue_page"] = page - 1
            st.rerun()
    with nav_page:
        st.caption(f"Page {page + 1} of {page_count} · {total} items to review")
    with nav_next:
        if st.button(
            "Next →",
            disabled=page + 1 >= page_count,
            key="review_next",
        ):
            st.session_state["review_queue_page"] = page + 1
            st.rerun()

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
                    f"<h3>{html.escape(str(student_name))} "
                    f"<small>({html.escape(str(student_email))})</small> — "
                    f"<span style='color:{border_color}; font-size:1.1rem; "
                    f"font-weight:700;'>{badge_text}</span></h3>",
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
                    if not isinstance(rf, dict):
                        st.markdown("- **Risk factor unavailable** (missing or malformed data)")
                        continue
                    rf_type = rf.get("type", "Signal")
                    if isinstance(rf_type, str):
                        rf_type = rf_type.replace("_", " ").title()
                    factor_score = _factor_score(rf)
                    score_text = (
                        f"{factor_score:.2f}"
                        if factor_score is not None
                        else "unavailable (weight/confidence missing or invalid)"
                    )
                    rf_desc = rf.get("description") or rf.get("details") or ""
                    st.markdown(
                        f"- **{rf_type}** (Contribution: `{score_text}`): {rf_desc}"
                    )

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
                    if not require_permission(
                        user, Permission.REVIEW_FLAGGED_CHECKINS
                    ):
                        return
                    with st.spinner("Approving check-in..."):
                        ok_rev, rev_res = api_client.review_checkin(
                            token=token,
                            checkin_id=checkin_id,
                            status="approved",
                            review_notes=review_notes.strip() if review_notes else None,
                        )
                    if ok_rev:
                        set_flash_message(f"Check-in for {student_name} has been APPROVED.")
                        st.rerun()
                    else:
                        st.error(f"Error: {rev_res}")

            with rev_col3:
                st.write("")
                st.write("")
                if st.button("❌ Reject", key=f"rej_{checkin_id}", use_container_width=True):
                    if not require_permission(
                        user, Permission.REVIEW_FLAGGED_CHECKINS
                    ):
                        return
                    with st.spinner("Rejecting check-in..."):
                        ok_rev, rev_res = api_client.review_checkin(
                            token=token,
                            checkin_id=checkin_id,
                            status="rejected",
                            review_notes=review_notes.strip() if review_notes else None,
                        )
                    if ok_rev:
                        set_flash_message(
                            f"Check-in for {student_name} has been marked REJECTED.",
                            level="warning",
                        )
                        st.rerun()
                    else:
                        st.error(f"Error: {rev_res}")
