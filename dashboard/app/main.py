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
    audit,
    checkins,
    courses,
    observability,
    overview,
    review_queue,
    sessions,
)

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

        # Check for pending flagged check-ins to show alert badge in menu
        flagged_badge = ""
        try:
            ok_flag, flag_data = api_client.get_flagged_checkins(token=token, limit=1)
            if ok_flag and isinstance(flag_data, dict):
                flagged_count = flag_data.get("total", len(flag_data.get("items", [])))
                if flagged_count > 0:
                    flagged_badge = f" ({flagged_count})"
        except Exception:
            pass

        nav_options = [
            "📊 Overview",
            "📅 Sessions",
            f"🚨 Review Queue{flagged_badge}",
            "📋 Check-in Explorer",
            "🎓 Courses & Rosters",
            "📜 Security Audit",
            "📈 Observability",
        ]

        selected_page = st.radio(
            "Navigation",
            options=nav_options,
            label_visibility="collapsed",
        )

        # User profile & logout button at bottom of sidebar
        render_sidebar_user_profile()

    # -------------------------------------------------------------------------
    # View Routing
    # -------------------------------------------------------------------------
    if selected_page == "📊 Overview":
        overview.render()
    elif selected_page == "📅 Sessions":
        sessions.render()
    elif selected_page.startswith("🚨 Review Queue"):
        review_queue.render()
    elif selected_page == "📋 Check-in Explorer":
        checkins.render()
    elif selected_page == "🎓 Courses & Rosters":
        courses.render()
    elif selected_page == "📜 Security Audit":
        audit.render()
    elif selected_page == "📈 Observability":
        observability.render()


if __name__ == "__main__":
    main()
