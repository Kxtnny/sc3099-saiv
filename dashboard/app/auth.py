"""
Authentication & session state management for the Streamlit dashboard.
"""

from typing import Any, Dict, Optional
import streamlit as st

from app.api_client import api_client
from app.config import STAFF_ROLES
from app.views._messages import render_flash_message, set_flash_message


def init_session_state() -> None:
    """Ensure essential authentication keys exist in session state."""
    if "access_token" not in st.session_state:
        st.session_state.access_token = None
    if "refresh_token" not in st.session_state:
        st.session_state.refresh_token = None
    if "user" not in st.session_state:
        st.session_state.user = None


def is_authenticated() -> bool:
    """Check if the user is currently signed in."""
    init_session_state()
    return st.session_state.access_token is not None and st.session_state.user is not None


def get_token() -> Optional[str]:
    """Return the current access token."""
    init_session_state()
    return st.session_state.access_token


def get_current_user() -> Optional[Dict[str, Any]]:
    """Return user dictionary if authenticated."""
    init_session_state()
    return st.session_state.user


def _refresh_expired_access_token(expired_access_token: str) -> Optional[str]:
    """Rotate tokens once, or clear authentication and show an expiry message."""
    current_token = st.session_state.get("access_token")
    if current_token and current_token != expired_access_token:
        return current_token

    refresh_token = st.session_state.get("refresh_token")
    if refresh_token:
        ok, result = api_client.refresh_token(refresh_token)
        if (
            ok
            and isinstance(result, dict)
            and result.get("access_token")
            and result.get("refresh_token")
        ):
            st.session_state.access_token = result["access_token"]
            st.session_state.refresh_token = result["refresh_token"]
            return result["access_token"]

    st.session_state.access_token = None
    st.session_state.refresh_token = None
    st.session_state.user = None
    set_flash_message(
        "Your session has expired. Please sign in again.",
        level="warning",
    )
    return None


def can_view_audit(user: Optional[Dict[str, Any]]) -> bool:
    """Audit data and exports are restricted to administrators."""
    return bool(user and (user.get("role") or "").lower() == "admin")


def can_create_sessions(user: Optional[Dict[str, Any]]) -> bool:
    """Match the backend's instructor-or-admin session creation rule."""
    return bool(
        user and (user.get("role") or "").lower() in {"admin", "instructor"}
    )


def can_manage_session(
    user: Optional[Dict[str, Any]],
    session: Dict[str, Any],
    course: Optional[Dict[str, Any]],
) -> bool:
    """Match the backend's admin, session-creator, or course-instructor rule."""
    if not user:
        return False
    role = (user.get("role") or "").lower()
    if role == "admin":
        return True
    if role not in {"instructor", "ta"}:
        return False

    user_id = user.get("id")
    return bool(
        user_id
        and (
            session.get("instructor_id") == user_id
            or (course and course.get("instructor_id") == user_id)
        )
    )


def logout_user() -> None:
    """Clear session state and notify backend."""
    token = get_token()
    if token:
        try:
            api_client.logout(token)
        except Exception:
            pass
    st.session_state.access_token = None
    st.session_state.refresh_token = None
    st.session_state.user = None
    st.session_state.pop("checkin_target_id", None)
    st.rerun()


def render_login_page() -> None:
    """Render a clean, secure login card for instructors and admins."""
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown(
            """
            <div style="text-align: center; margin-bottom: 2rem; margin-top: 2rem;">
                <h1 style="color: #1E3A8A; font-size: 2.5rem; margin-bottom: 0.2rem;">🛡️ SAIV</h1>
                <h3 style="color: #4B5563; font-weight: 500; margin-top: 0;">Instructor & Observability Dashboard</h3>
                <p style="color: #6B7280; font-size: 0.95rem;">
                    Secure Attendance & Identity Verification System
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.container(border=True):
            render_flash_message()
            st.subheader("Sign In")
            st.caption("Access requires Instructor, TA, or Administrator credentials.")

            with st.form("login_form", clear_on_submit=False):
                email = st.text_input("Email Address", placeholder="instructor@ntu.edu.sg")
                password = st.text_input("Password", type="password", placeholder="••••••••")
                submitted = st.form_submit_button("Sign In", use_container_width=True, type="primary")

            if submitted:
                if not email or not password:
                    st.error("Please enter both email and password.")
                    return

                with st.spinner("Authenticating..."):
                    ok, data = api_client.login(email.strip(), password)

                if not ok:
                    detail = data.get("detail", data) if isinstance(data, dict) else str(data)
                    st.error(f"Login failed: {detail}")
                    return

                # Check user role
                user_info = data.get("user", {})
                role = user_info.get("role", "").lower()
                if role not in STAFF_ROLES:
                    st.error(f"Access Denied: Role '{role}' does not have dashboard privileges.")
                    return

                # Store tokens in session state
                st.session_state.access_token = data.get("access_token")
                st.session_state.refresh_token = data.get("refresh_token")
                st.session_state.user = user_info
                set_flash_message("Authentication successful.")
                st.rerun()


def render_sidebar_user_profile() -> None:
    """Render the active user's identity card and logout button in the sidebar."""
    user = get_current_user()
    if not user:
        return

    full_name = user.get("full_name") or user.get("email", "User")
    email = user.get("email", "")
    role = user.get("role", "staff").upper()

    role_colors = {
        "ADMIN": "#EF4444",
        "INSTRUCTOR": "#3B82F6",
        "TA": "#10B981",
    }
    badge_color = role_colors.get(role, "#6B7280")

    with st.sidebar:
        st.markdown("---")
        st.markdown(
            f"""
            <div style="background-color: rgba(243, 244, 246, 0.6); padding: 0.75rem; border-radius: 8px; margin-bottom: 0.5rem;">
                <div style="font-weight: 600; color: #111827; font-size: 0.95rem;">{full_name}</div>
                <div style="color: #6B7280; font-size: 0.8rem; word-break: break-all;">{email}</div>
                <div style="margin-top: 0.35rem;">
                    <span style="background-color: {badge_color}; color: white; padding: 2px 8px; border-radius: 9999px; font-size: 0.7rem; font-weight: 600;">
                        {role}
                    </span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("🚪 Sign Out", use_container_width=True):
            logout_user()


api_client.set_refresh_handler(_refresh_expired_access_token)
