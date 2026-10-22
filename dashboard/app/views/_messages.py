"""Flash messages that survive a Streamlit rerun."""

from typing import Optional

import streamlit as st


_FLASH_MESSAGE_KEY = "dashboard_flash_message"


def set_flash_message(message: str, level: str = "success") -> None:
    """Store a user-visible message for the next script run."""
    if level not in {"success", "warning", "info", "error"}:
        raise ValueError(f"Unsupported flash message level: {level}")
    st.session_state[_FLASH_MESSAGE_KEY] = {"message": message, "level": level}


def render_flash_message() -> None:
    """Display and consume a message stored before a script rerun."""
    flash: Optional[dict] = st.session_state.pop(_FLASH_MESSAGE_KEY, None)
    if not isinstance(flash, dict):
        return
    message = flash.get("message")
    level = flash.get("level")
    if not isinstance(message, str) or level not in {
        "success",
        "warning",
        "info",
        "error",
    }:
        return
    getattr(st, level)(message)
