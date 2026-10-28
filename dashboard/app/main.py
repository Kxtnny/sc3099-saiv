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
    can_view_audit,
    get_current_user,
    get_token,
    is_authenticated,
    render_login_page,
    render_sidebar_user_profile,
)
from app.views import (
    audit,
    checkins,
    courses,
    observability,
    overview,
    review_queue,
    sessions,
)
from app.views._messages import render_flash_message

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

    with st.sidebar:
        st.markdown(
            """
            <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 1rem;">
                <span style="font-size: 2rem;">🛡️</span>
                <div>
                    <h2 style="margin: 0; font-size: 1.4rem; color: #1E3A8A;">SAIV</h2>
                    <span style="font-size: 0.8rem; color: #6B7280; font-weight: 500;">INSTRUCTOR PORTAL</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Check for pending flagged check-ins to show alert badge in menu.
        ok_flag, flag_data = api_client.get_flagged_checkins(token=token, limit=1)
        flagged_count = (
            flag_data.get("total", len(flag_data.get("items", [])))
            if ok_flag and isinstance(flag_data, dict)
            else None
        )

        nav_options = [
            "📊 Overview",
            "📅 Sessions",
            "🚨 Review Queue",
            "📋 Check-in Explorer",
            "🎓 Courses & Rosters",
        ]
        if can_view_audit(user):
            nav_options.append("📜 Security Audit")
        nav_options.append("📈 Observability")

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
            st.caption("Review queue count is currently unavailable.")

        # User profile & logout button at bottom of sidebar
        render_sidebar_user_profile()

    # -------------------------------------------------------------------------
    # View Routing
    # -------------------------------------------------------------------------
    if selected_page == "📊 Overview":
        overview.render()
    elif selected_page == "📅 Sessions":
        sessions.render()
    elif selected_page == "🚨 Review Queue":
        review_queue.render()
    elif selected_page == "📋 Check-in Explorer":
        checkins.render()
    elif selected_page == "🎓 Courses & Rosters":
        courses.render()
    elif selected_page == "📜 Security Audit":
        audit.render()
    elif selected_page == "📈 Observability":
        observability.render()

    if not is_authenticated():
        st.rerun()


if __name__ == "__main__":
    main()
