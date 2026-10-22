"""Shared helpers for user-requested exports."""

import json
from hashlib import sha256
from typing import Any, Callable, Tuple

import streamlit as st


def render_csv_download(
    *,
    token: str,
    cache_key: str,
    request_label: str,
    download_label: str,
    file_name: str,
    export: Callable[[], Tuple[bool, Any]],
    button_type: str = "secondary",
    use_container_width: bool = False,
) -> None:
    """Fetch CSV data only after an explicit request and retain it for download."""
    token_key = sha256(token.encode("utf-8")).hexdigest()
    state_key = f"csv_export_{token_key}_{cache_key}"
    if st.button(
        request_label,
        key=f"{state_key}_request",
        type=button_type,
        use_container_width=use_container_width,
    ):
        st.session_state.pop(state_key, None)
        with st.spinner("Preparing CSV export..."):
            ok, result = export()
        if not ok:
            st.error(f"Failed to export CSV: {result}")
        elif not isinstance(result, bytes):
            st.error("Failed to export CSV: the server returned an invalid response.")
        else:
            st.session_state[state_key] = result

    csv_data = st.session_state.get(state_key)
    if isinstance(csv_data, bytes):
        st.download_button(
            label=download_label,
            data=csv_data,
            file_name=file_name,
            mime="text/csv",
            key=f"{state_key}_download",
            type=button_type,
            use_container_width=use_container_width,
        )


def render_json_download(
    *,
    token: str,
    cache_key: str,
    request_label: str,
    download_label: str,
    file_name: str,
    export: Callable[[], Tuple[bool, Any]],
    button_type: str = "secondary",
    use_container_width: bool = False,
) -> None:
    """Fetch JSON only after a user request, then cache it for download."""
    token_key = sha256(token.encode("utf-8")).hexdigest()
    state_key = f"json_export_{token_key}_{cache_key}"
    if st.button(
        request_label,
        key=f"{state_key}_request",
        type=button_type,
        use_container_width=use_container_width,
    ):
        st.session_state.pop(state_key, None)
        with st.spinner("Preparing JSON export..."):
            ok, result = export()
        if not ok:
            st.error(f"Failed to export JSON: {result}")
        elif not isinstance(result, (dict, list)):
            st.error("Failed to export JSON: the server returned an invalid response.")
        else:
            st.session_state[state_key] = json.dumps(
                result, ensure_ascii=False, indent=2
            ).encode("utf-8")

    json_data = st.session_state.get(state_key)
    if isinstance(json_data, bytes):
        st.download_button(
            label=download_label,
            data=json_data,
            file_name=file_name,
            mime="application/json",
            key=f"{state_key}_download",
            type=button_type,
            use_container_width=use_container_width,
        )
