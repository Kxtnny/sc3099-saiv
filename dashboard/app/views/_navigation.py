"""Buttons that jump to another dashboard page."""

from typing import Optional

import streamlit as st


def open_page(page: str, checkin_id: Optional[str] = None) -> None:
    """
    Switch the sidebar to another page.

    Use this as a button's on_click. The sidebar is drawn before the page body,
    so code that runs after st.button returns True is too late to change it.
    """
    st.session_state["dashboard_page"] = page
    if checkin_id:
        st.session_state["checkin_target_id"] = checkin_id
