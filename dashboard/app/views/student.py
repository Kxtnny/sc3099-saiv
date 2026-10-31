"""Authenticated user's own attendance history and device management."""

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from app.api_client import api_client
from app.auth import get_current_user, get_token
from app.config import STUDENT_PORTAL_URL
from app.rbac import Permission, require_permission, role_for_user
from app.views._messages import set_flash_message


def render() -> None:
    """Render personal records and owner-managed devices."""
    user = get_current_user()
    if not require_permission(user, Permission.VIEW_OWN_RECORDS):
        return

    token = get_token()
    if not token:
        st.warning("Please sign in to view your attendance and devices.")
        return

    st.title("👤 My Attendance & Devices")
    st.caption("Review your own check-in history and manage devices registered to your account.")

    if role_for_user(user) == "student":
        st.link_button(
            "Open Student Check-in Portal",
            STUDENT_PORTAL_URL,
            type="primary",
        )
    else:
        st.info(
            "The existing check-in API currently accepts check-in submissions only "
            "from student accounts. Personal history and device management remain available."
        )

    with st.spinner("Loading your attendance history..."):
        ok_checkins, checkins = api_client.get_my_checkins(token)
    if not ok_checkins:
        st.error(f"Unable to load your check-in history: {checkins}")
    elif not isinstance(checkins, list):
        st.error("Unable to load your check-in history: invalid response format.")
    elif checkins:
        checkin_rows: List[Dict[str, Any]] = [
            {
                "Course": item.get("course_code") or "N/A",
                "Session": item.get("session_name") or "N/A",
                "Status": str(item.get("status") or "unknown").upper(),
                "Checked in at (UTC)": item.get("checked_in_at") or "N/A",
                "Risk score": item.get("risk_score", "N/A"),
            }
            for item in checkins
            if isinstance(item, dict)
        ]
        st.dataframe(
            pd.DataFrame(checkin_rows),
            use_container_width=True,
            hide_index=True,
        )
        if role_for_user(user) == "student":
            for item in checkins:
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status") or "").lower()
                checkin_id = item.get("id")
                if (
                    status not in {"flagged", "rejected"}
                    or not isinstance(checkin_id, str)
                    or not checkin_id
                    or item.get("appealed_at")
                ):
                    continue
                with st.expander(
                    f"Appeal {item.get('session_name') or 'check-in'} "
                    f"({status})"
                ):
                    with st.form(f"appeal_checkin_{checkin_id}"):
                        appeal_reason = st.text_area(
                            "Explain why this check-in should be reviewed",
                            max_chars=2000,
                            key=f"appeal_reason_{checkin_id}",
                        )
                        appeal_submitted = st.form_submit_button(
                            "Submit appeal"
                        )
                    if appeal_submitted:
                        if not require_permission(
                            user, Permission.APPEAL_OWN_CHECKIN
                        ):
                            return
                        if not appeal_reason.strip():
                            st.error("Please provide a reason for your appeal.")
                            continue
                        ok_appeal, result = api_client.appeal_checkin(
                            token, checkin_id, appeal_reason.strip()
                        )
                        if ok_appeal:
                            set_flash_message("Your appeal was submitted.")
                            st.rerun()
                        else:
                            st.error(f"Unable to submit appeal: {result}")
    else:
        st.info("No check-in history is associated with your account.")

    st.markdown("---")
    st.subheader("My Devices")
    if not require_permission(user, Permission.MANAGE_OWN_DEVICES):
        return
    with st.spinner("Loading your registered devices..."):
        ok_devices, devices = api_client.get_my_devices(token)
    if not ok_devices:
        st.error(f"Unable to load your devices: {devices}")
        return
    if not isinstance(devices, list):
        st.error("Unable to load your devices: invalid response format.")
        return
    if not devices:
        st.info(
            "No devices are registered yet. The Student Check-in Portal registers "
            "the current device when you check in."
        )
        return

    for device in devices:
        if not isinstance(device, dict):
            continue
        device_id = device.get("id")
        if not isinstance(device_id, str) or not device_id:
            continue
        device_name = device.get("device_name") or "Unnamed device"
        active_status = "Active" if device.get("is_active") else "Revoked"
        with st.expander(f"{device_name} · {active_status}"):
            st.caption(
                f"Platform: {device.get('platform') or 'N/A'} · "
                f"Last seen: {device.get('last_seen_at') or 'N/A'} · "
                f"Check-ins: {device.get('total_checkins', 0)}"
            )
            if not device.get("is_active"):
                continue
            with st.form(f"rename_device_{device_id}"):
                updated_name = st.text_input(
                    "Device name",
                    value=device.get("device_name") or "",
                    key=f"device_name_{device_id}",
                )
                rename_submitted = st.form_submit_button("Save device name")
            if rename_submitted:
                if not require_permission(
                    user, Permission.MANAGE_OWN_DEVICES
                ):
                    return
                ok_update, result = api_client.update_device(
                    token, device_id, device_name=updated_name.strip()
                )
                if ok_update:
                    set_flash_message("Device name updated.")
                    st.rerun()
                else:
                    st.error(f"Unable to update device: {result}")

            if st.button("Revoke device", key=f"revoke_device_{device_id}"):
                if not require_permission(
                    user, Permission.MANAGE_OWN_DEVICES
                ):
                    return
                ok_revoke, result = api_client.revoke_device(token, device_id)
                if ok_revoke:
                    set_flash_message("Device revoked.", level="warning")
                    st.rerun()
                else:
                    st.error(f"Unable to revoke device: {result}")
