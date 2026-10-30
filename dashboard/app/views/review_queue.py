"""
Review Queue View - Review, investigate, and approve or reject flagged & appealed check-ins,
and acknowledge check-ins that were approved with a flag (MEDIUM risk band or above).
"""

import math
from numbers import Real
from typing import Any, Dict, List, Optional
import streamlit as st

from app.api_client import api_client
from app.auth import get_token
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


def _render_header(item: Dict[str, Any], badge_text: str, badge_color: str) -> None:
    """Student, course and session line with the badge, beside the risk score."""
    student_name = item.get("student_name") or item.get("student_email") or "Student"
    student_email = item.get("student_email", "")
    course_code = item.get("course_code") or "Course"
    session_name = item.get("session_name") or "Session"
    risk_score = item.get("risk_score", 0.0)
    risk_level = item.get("risk_level")
    timestamp = item.get("checked_in_at", "")[:19].replace("T", " ")

    head_col1, head_col2 = st.columns([3, 1])
    with head_col1:
        st.markdown(
            f"### {student_name} (`{student_email}`) — <span style='color:{badge_color}; font-size:1.1rem; font-weight:700;'>{badge_text}</span>",
            unsafe_allow_html=True,
        )
        st.caption(f"Course: **{course_code}** | Session: **{session_name}** | Time: **{timestamp} UTC**")

    with head_col2:
        risk_pct = risk_score * 100
        delta = f"{risk_level} · {risk_pct:.0f}% Risk" if risk_level else f"{risk_pct:.0f}% Risk"
        st.metric(label="Risk Score", value=f"{risk_score:.2f}", delta=delta, delta_color="inverse")


def _render_signals(item: Dict[str, Any]) -> None:
    """Signal summary and per-factor contributions."""
    distance = item.get("distance_from_venue_meters")
    liveness_passed = item.get("liveness_passed")
    device_trusted = item.get("device_trusted")
    risk_factors = item.get("risk_factors", [])

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


def _submit_review(
    token: str,
    checkin_id: str,
    status: str,
    review_notes: Optional[str],
    spinner_text: str,
    flash_text: str,
    flash_level: str = "success",
) -> None:
    """Post a review decision and rerun on success."""
    with st.spinner(spinner_text):
        ok_rev, rev_res = api_client.review_checkin(
            token=token,
            checkin_id=checkin_id,
            status=status,
            review_notes=review_notes.strip() if review_notes else None,
        )
    if ok_rev:
        set_flash_message(flash_text, level=flash_level)
        st.rerun()
    else:
        st.error(f"Error: {rev_res}")


def _render_decision_card(item: Dict[str, Any], token: str) -> None:
    """A flagged or appealed check-in awaiting approve or reject."""
    checkin_id = item.get("id", "")
    student_name = item.get("student_name") or item.get("student_email") or "Student"
    status = item.get("status", "flagged").lower()
    appeal_reason = item.get("appeal_reason")
    appealed_at = item.get("appealed_at", "")[:19].replace("T", " ") if item.get("appealed_at") else None

    # Color badges
    badge_text = "🚨 FLAGGED" if status == "flagged" else "📩 UNDER APPEAL"
    border_color = "#EF4444" if status == "flagged" else "#F59E0B"

    with st.container(border=True):
        _render_header(item, badge_text, border_color)
        _render_signals(item)

        # Appeal Reason (if under appeal)
        if appeal_reason:
            st.info(f"**Student's Appeal Explanation ({appealed_at} UTC):**\n\n> {appeal_reason}", icon="📝")

        st.markdown("---")

        # Decision Action Form
        rev_col1, rev_col2, rev_col3 = st.columns([3, 1, 1])

        with rev_col1:
            review_notes = st.text_input(
                "Review Decision Notes (Optional)",
                key=f"notes_{checkin_id}",
                placeholder="e.g. Verified classroom presence in lecture recording",
            )

        with rev_col2:
            st.write("")
            st.write("")
            if st.button("✅ Approve", key=f"app_{checkin_id}", type="primary", use_container_width=True):
                _submit_review(
                    token, checkin_id, "approved", review_notes,
                    "Approving check-in...",
                    f"Check-in for {student_name} has been APPROVED.",
                )

        with rev_col3:
            st.write("")
            st.write("")
            if st.button("❌ Reject", key=f"rej_{checkin_id}", use_container_width=True):
                _submit_review(
                    token, checkin_id, "rejected", review_notes,
                    "Rejecting check-in...",
                    f"Check-in for {student_name} has been marked REJECTED.",
                    flash_level="warning",
                )


def _render_flag_card(item: Dict[str, Any], token: str) -> None:
    """An approved-with-flag check-in: acknowledge it, or overturn it."""
    checkin_id = item.get("id", "")
    student_name = item.get("student_name") or item.get("student_email") or "Student"
    reviewed_at = item.get("reviewed_at")

    if reviewed_at:
        badge_text, badge_color = "✔️ APPROVED · ACKNOWLEDGED", "#22C55E"
    else:
        badge_text, badge_color = "⚑ APPROVED WITH FLAG", "#EAB308"

    with st.container(border=True):
        _render_header(item, badge_text, badge_color)
        _render_signals(item)

        if reviewed_at:
            st.info(
                f"**Acknowledged {reviewed_at[:19].replace('T', ' ')} UTC.** "
                f"Notes: {item.get('review_notes') or 'None'}",
                icon="ℹ️",
            )

        st.markdown("---")

        rev_col1, rev_col2, rev_col3 = st.columns([3, 1, 1])

        with rev_col1:
            review_notes = st.text_input(
                "Review Notes (Optional)",
                key=f"flag_notes_{checkin_id}",
                placeholder="e.g. Known GPS drift in this lecture theatre",
            )

        with rev_col2:
            st.write("")
            st.write("")
            if not reviewed_at and st.button(
                "👁️ Acknowledge", key=f"ack_{checkin_id}", type="primary", use_container_width=True
            ):
                _submit_review(
                    token, checkin_id, "approved", review_notes,
                    "Acknowledging check-in...",
                    f"Flagged approval for {student_name} acknowledged.",
                )

        with rev_col3:
            st.write("")
            st.write("")
            if st.button("❌ Reject", key=f"flag_rej_{checkin_id}", use_container_width=True):
                _submit_review(
                    token, checkin_id, "rejected", review_notes,
                    "Rejecting check-in...",
                    f"Check-in for {student_name} has been marked REJECTED.",
                    flash_level="warning",
                )


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

    with col_f2:
        st.write("")
        st.write("")
        include_acknowledged = st.checkbox(
            "Show acknowledged approvals",
            key="rq_include_acknowledged",
            help="Also list approved-with-flag check-ins an instructor has already acknowledged.",
        )

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
        ok_flag, flag_res = api_client.get_approved_flagged_checkins(
            token=token,
            course_id=course_filter_id,
            include_acknowledged=include_acknowledged,
            limit=100,
        )

    items: List[Dict[str, Any]] = res.get("items", []) if ok and isinstance(res, dict) else []
    flag_items: List[Dict[str, Any]] = (
        flag_res.get("items", []) if ok_flag and isinstance(flag_res, dict) else []
    )
    flag_total = flag_res.get("total", len(flag_items)) if ok_flag and isinstance(flag_res, dict) else 0

    tab_decide, tab_flag = st.tabs(
        [
            f"🚨 Needs decision ({len(items) if ok else '?'})",
            f"⚑ Approved with flag ({flag_total if ok_flag else '?'})",
        ]
    )

    with tab_decide:
        if not ok:
            st.error(f"Failed to load flagged check-ins: {res}")
        elif not items:
            st.success("🎉 All clear! There are currently no flagged or appealed check-ins requiring review.")
        else:
            st.markdown(f"Found **{len(items)}** check-in(s) requiring your decision:")
            for item in items:
                _render_decision_card(item, token)

    with tab_flag:
        st.caption(
            "Auto-approved check-ins in the MEDIUM risk band or above (risk ≥ 0.30). "
            "No decision is needed: acknowledge them once checked, or reject to overturn the approval."
        )
        if not ok_flag:
            st.error(f"Failed to load approved-with-flag check-ins: {flag_res}")
        elif not flag_items:
            st.success("🎉 Nothing to acknowledge. No approved check-ins carry a risk flag.")
        else:
            st.markdown(f"Found **{flag_total}** approved check-in(s) carrying a risk flag:")
            for item in flag_items:
                _render_flag_card(item, token)
