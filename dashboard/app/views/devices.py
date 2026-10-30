"""
Device Trust View - Admin-only list of student devices, with trust and revocation controls.
"""

from typing import Any, Dict, List, Optional
import pandas as pd
import streamlit as st

from app.api_client import api_client
from app.auth import can_manage_devices, get_current_user, get_token
from app.views._messages import set_flash_message

# Matches CHECKINS_TO_EARN_TRUST in backend/app/services/device_trust.py.
CHECKINS_TO_EARN_TRUST = 3

# Filter label -> the backend's (is_trusted, is_active) filters.
STATUS_FILTERS: Dict[str, Dict[str, bool]] = {
    "All": {},
    "Trusted": {"is_trusted": True, "is_active": True},
    "Earning trust": {"is_trusted": False, "is_active": True},
    "Revoked": {"is_active": False},
}


def _trust_label(device: Dict[str, Any]) -> str:
    """One-line trust state, showing progress for a device still earning it."""
    if not device.get("is_active"):
        return "🚫 Revoked"
    if device.get("is_trusted"):
        return "✅ Trusted"
    clean = min(device.get("clean_checkins") or 0, CHECKINS_TO_EARN_TRUST)
    return f"⏳ Earning trust ({clean}/{CHECKINS_TO_EARN_TRUST})"


def _apply(token: str, device_id: str, changes: Dict[str, Any], message: str) -> None:
    """Send a device change and rerun on success."""
    ok, result = api_client.update_device(token, device_id, changes)
    if ok:
        set_flash_message(message)
        st.rerun()
    else:
        st.error(f"Error: {result}")


def render() -> None:
    """Render the Device Trust view."""
    st.title("📱 Device Trust")
    st.caption(
        f"Devices earn trust after {CHECKINS_TO_EARN_TRUST} clean check-ins. "
        "Removing trust or revoking a device restarts that count."
    )

    token = get_token()
    user = get_current_user()
    if not token or not user:
        st.warning("Please sign in to manage devices.")
        return

    if not can_manage_devices(user):
        st.error("Access restricted to Administrators.")
        return

    col_f1, col_f2 = st.columns([2, 1])
    with col_f1:
        email_search = st.text_input("Search by Student Email", placeholder="student1@demo.ntu")
    with col_f2:
        status_filter = st.selectbox("Trust Status", options=list(STATUS_FILTERS.keys()))

    with st.spinner("Loading devices..."):
        ok, res = api_client.list_devices(
            token=token,
            email=email_search.strip() if email_search else None,
            limit=100,
            **STATUS_FILTERS[status_filter],
        )

    if not ok:
        st.error(f"Failed to load devices: {res}")
        return

    devices: List[Dict[str, Any]] = res.get("items", []) if isinstance(res, dict) else []
    total = res.get("total", len(devices)) if isinstance(res, dict) else len(devices)

    st.write(f"Showing **{len(devices)}** of **{total}** device(s):")

    if not devices:
        st.info("No devices matched your filters.")
        return

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Student": d.get("user_email") or "N/A",
                    "Device": d.get("device_name") or "N/A",
                    "Trust": _trust_label(d),
                    "Check-ins": d.get("total_checkins", 0),
                    "Last Seen (UTC)": (d.get("last_seen_at") or "")[:19].replace("T", " "),
                }
                for d in devices
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("---")
    st.subheader("Manage a Device")

    # Keyed by ID, because a change moves the device within a filtered list.
    devices_by_id = {d["id"]: d for d in devices}
    selected_id: Optional[str] = st.selectbox(
        "Select a device:",
        options=list(devices_by_id.keys()),
        format_func=lambda device_id: (
            f"{devices_by_id[device_id].get('user_email') or 'N/A'} - "
            f"{devices_by_id[device_id].get('device_name') or 'Device'} - "
            f"{_trust_label(devices_by_id[device_id])}"
        ),
        key="device_select",
    )
    if selected_id is None:
        return
    device = devices_by_id[selected_id]
    is_active = bool(device.get("is_active"))
    is_trusted = bool(device.get("is_trusted"))

    col_a1, col_a2 = st.columns(2)
    with col_a1:
        if is_active and is_trusted:
            if st.button("↩️ Remove Trust", key="device_remove_trust", use_container_width=True):
                _apply(token, selected_id, {"is_trusted": False}, "Trust removed. The clean check-in count restarts.")
        elif is_active:
            if st.button("✅ Trust Device", key="device_trust", type="primary", use_container_width=True):
                _apply(token, selected_id, {"is_trusted": True}, "Device marked as trusted.")
    with col_a2:
        if is_active:
            if st.button("🚫 Revoke Device", key="device_revoke", use_container_width=True):
                _apply(token, selected_id, {"is_active": False}, "Device revoked.")
        else:
            if st.button("♻️ Reactivate Device", key="device_reactivate", use_container_width=True):
                _apply(token, selected_id, {"is_active": True}, "Device reactivated. It must earn trust again.")
