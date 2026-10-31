"""
SAIV Instructor & Observability Dashboard - Module 4 Entrypoint
"""

import sys
from pathlib import Path

# Ensure the dashboard directory is on sys.path so 'app.*' imports resolve cleanly
DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

import streamlit as st

from app.api_client import api_client
from app.auth import (
    get_current_user,
    get_token,
    is_authenticated,
    render_login_page,
    render_sidebar_user_profile,
)
from app.views import (
    administration,
    audit,
    checkins,
    courses,
    observability,
    overview,
    review_queue,
    sessions,
)
from app.views._messages import render_flash_message
from app.rbac import (
    DASHBOARD_PAGE_PERMISSIONS,
    Permission,
    allowed_dashboard_pages,
    has_permission,
    require_permission,
    resolve_dashboard_page,
    role_for_user,
)
from app.views import session_checkins, student

# Page configuration
st.set_page_config(
    page_title="SAIV Dashboard",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown(
    """
    <style>
    /* Metric styling */
    div[data-testid="stMetricValue"] {
        font-size: 1.8rem;
        font-weight: 700;
    }
    div[data-testid="stMetricLabel"] {
        font-weight: 500;
        color: #4B5563;
    }
    /* Buttons */
    .stButton button {
        border-radius: 6px;
    }
    @media (max-width: 700px) {
        .block-container {
            padding-left: 1rem;
            padding-right: 1rem;
        }
        div[data-testid="stHorizontalBlock"] {
            flex-wrap: wrap;
        }
        div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
            min-width: 100% !important;
            flex: 1 1 100% !important;
        }
        div[data-testid="stDataFrame"] {
            max-width: 100%;
            overflow-x: auto;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def main() -> None:
    # -------------------------------------------------------------------------
    # Authentication Gate
    # -------------------------------------------------------------------------
    if not is_authenticated():
        render_login_page()
        return

    render_flash_message()

    # -------------------------------------------------------------------------
    # Sidebar Navigation & Branding
    # -------------------------------------------------------------------------
    token = get_token()
    user = get_current_user()
    role = role_for_user(user)

    if role is None:
        with st.sidebar:
            render_sidebar_user_profile()
        st.error(
            "Access denied. Your account has a missing or unrecognized dashboard role."
        )
        return

    page_renderers = {
        "👤 My Attendance & Devices": student.render,
        "📊 Overview": overview.render,
        "📅 Sessions": sessions.render,
        "📋 Session Check-ins": session_checkins.render,
        "🚨 Review Queue": review_queue.render,
        "🎓 Courses & Rosters": courses.render,
        "📋 Check-in Explorer": checkins.render,
        "📜 Security Audit": audit.render,
        "📈 Observability": observability.render,
        "🛠️ Administration": administration.render,
    }
    page_definitions = [
        (label, permission, page_renderers[label])
        for label, permission in DASHBOARD_PAGE_PERMISSIONS.items()
    ]
    visible_pages = [
        (label, permission, render)
        for label, permission, render in page_definitions
        if label in allowed_dashboard_pages(user)
    ]
    default_pages = {
        "student": "👤 My Attendance & Devices",
        "ta": "📋 Session Check-ins",
        "instructor": "📊 Overview",
        "admin": "📊 Overview",
    }
    allowed_page_labels = frozenset(label for label, _, _ in visible_pages)
    if not allowed_page_labels:
        st.error("Access denied. No dashboard pages are available for this role.")
        return
    requested_page = st.session_state.get("dashboard_page")
    default_page = default_pages[role]
    st.session_state["dashboard_page"] = resolve_dashboard_page(
        requested_page, allowed_page_labels, default_page
    )

    with st.sidebar:
        st.markdown(
            """
            <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 1rem;">
                <span style="font-size: 2rem;">🛡️</span>
                <div>
                    <h2 style="margin: 0; font-size: 1.4rem; color: #1E3A8A;">SAIV</h2>
                    <span style="font-size: 0.8rem; color: #6B7280; font-weight: 500;">ROLE-BASED DASHBOARD</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        flagged_count = None
        if (
            role == "admin"
            and has_permission(user, Permission.REVIEW_FLAGGED_CHECKINS)
        ):
            ok_flag, flag_data = api_client.get_flagged_checkins(
                token=token, limit=1
            )
            if ok_flag and isinstance(flag_data, dict):
                total = flag_data.get("total")
                items = flag_data.get("items")
                if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
                    flagged_count = total
                elif isinstance(items, list):
                    flagged_count = len(items)

        nav_options = [label for label, _, _ in visible_pages]

        selected_page = st.radio(
            "Navigation",
            options=nav_options,
            format_func=lambda page: (
                f"{page} ({flagged_count})"
                if page == "🚨 Review Queue"
                and flagged_count is not None
                and flagged_count > 0
                else page
            ),
            label_visibility="collapsed",
            key="dashboard_page",
        )
        if flagged_count is None:
            if role == "admin":
                st.caption("Review queue count is currently unavailable.")

        # User profile & logout button at bottom of sidebar
        render_sidebar_user_profile()

    # -------------------------------------------------------------------------
    # View Routing
    # -------------------------------------------------------------------------
    selected_definition = next(
        (item for item in visible_pages if item[0] == selected_page), None
    )
    if selected_definition is None:
        st.error("Access denied. This dashboard page is not available to your role.")
    elif require_permission(user, selected_definition[1]):
        selected_definition[2]()

    if not is_authenticated():
        st.rerun()


if __name__ == "__main__":
    main()
