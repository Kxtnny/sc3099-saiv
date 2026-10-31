"""Session-scoped check-in records for staff with the corresponding permission."""

from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from app.api_client import api_client
from app.auth import get_current_user, get_token
from app.access import load_visible_courses
from app.rbac import Permission, require_permission, role_for_user


def render() -> None:
    """Select a session and display only its check-in records."""
    user = get_current_user()
    if not require_permission(user, Permission.VIEW_SESSION_CHECKINS):
        return

    token = get_token()
    if not token:
        st.warning("Please sign in to view session check-ins.")
        return

    st.title("📋 Session Check-ins")
    st.caption("View attendance records for one selected session.")

    role = role_for_user(user)
    if role == "ta":
        st.warning(
            "Session check-ins are withheld because the API does not expose "
            "which courses are assigned to this TA."
        )
        return

    if role == "instructor":
        ok_courses, courses, scope_message = load_visible_courses(token, user)
        if not ok_courses:
            st.error(scope_message or "Unable to load assigned courses.")
            return
        if not courses:
            st.info("No courses are assigned to this instructor.")
            return
        allowed_course_ids = {
            course.get("id")
            for course in courses
            if isinstance(course.get("id"), str)
        }
        with st.spinner("Loading your sessions..."):
            ok_sessions, response = api_client.get_my_sessions(token)
        if not ok_sessions:
            st.error(f"Unable to load your sessions: {response}")
            return
        if not isinstance(response, list):
            st.error("Unable to load your sessions: invalid response format.")
            return
        sessions = [
            item
            for item in response
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and item.get("course_id") in allowed_course_ids
        ]
    else:
        all_sessions: List[Dict[str, Any]] = []
        offset = 0
        total = None
        while total is None or offset < total:
            with st.spinner("Loading sessions..."):
                ok_sessions, response = api_client.list_sessions(
                    token=token, limit=100, offset=offset
                )
            if not ok_sessions:
                st.error(f"Unable to load sessions: {response}")
                return
            if not isinstance(response, dict) or not isinstance(
                response.get("items"), list
            ):
                st.error("Unable to load sessions: invalid response format.")
                return
            page = response["items"]
            if any(not isinstance(item, dict) for item in page):
                st.error("Unable to load sessions: invalid session entry.")
                return
            all_sessions.extend(page)
            total = response.get("total")
            if (
                not isinstance(total, int)
                or isinstance(total, bool)
                or total < 0
            ):
                st.error("Unable to load sessions: invalid total count.")
                return
            offset += len(page)
            if not page:
                break
        sessions = [
            item for item in all_sessions if isinstance(item.get("id"), str)
        ]
    if not sessions:
        st.info("No sessions are available.")
        return

    session_options: Dict[str, str] = {}
    for session in sessions:
        session_options[
            f"{session.get('course_code') or 'Course'} · "
            f"{session.get('name') or 'Session'} · "
            f"{str(session.get('scheduled_start') or '')[:16]}"
        ] = session["id"]
    selected_label = st.selectbox(
        "Session",
        options=list(session_options.keys()),
        key="session_checkins_selected",
    )
    session_id: Optional[str] = session_options.get(selected_label)
    if not session_id:
        st.error("Select a valid session to continue.")
        return

    with st.spinner("Loading check-ins for this session..."):
        ok_checkins, checkins = api_client.get_session_checkins(token, session_id)
    if not ok_checkins:
        st.error(f"Unable to load session check-ins: {checkins}")
        return
    if not isinstance(checkins, list):
        st.error("Unable to load session check-ins: invalid response format.")
        return
    if not checkins:
        st.info("No check-ins have been recorded for this session.")
        return

    rows: List[Dict[str, Any]] = [
        {
            "Student": item.get("student_name") or item.get("student_email") or "N/A",
            "Status": str(item.get("status") or "unknown").upper(),
            "Checked in at (UTC)": item.get("checked_in_at") or "N/A",
            "Risk score": item.get("risk_score", "N/A"),
            "Liveness": (
                "Passed"
                if item.get("liveness_passed") is True
                else "Failed"
                if item.get("liveness_passed") is False
                else "N/A"
            ),
        }
        for item in checkins
        if isinstance(item, dict)
    ]
    st.write(f"Showing **{len(rows)}** check-in(s).")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
